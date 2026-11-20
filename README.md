# Librería Online

Plataforma de una librería en línea construida como **monorepo** para la materia
de Integración de Aplicaciones Computacionales. Reúne en un mismo sistema las
formas de integración que se ven en el curso: un **monolito** web MVC, **ocho
microservicios** (REST/JSON, XML, SOAP y WebSocket), **tres clientes de
escritorio** (Electron, Tkinter y JavaFX), una capa de **Redis** compartida y una
base **PostgreSQL** normalizada hasta 4FN, todo desplegado en una VM de GCP detrás
de un **proxy inverso con TLS**.

> Este archivo es la visión general. El manual técnico detallado (rutas, esquema
> de la base, variables de entorno, despliegue paso a paso) está en
> [MANUAL_TECNICO.md](MANUAL_TECNICO.md).

---

## Contenido

1. [Propósito](#propósito)
2. [Arquitectura del sistema](#arquitectura-del-sistema)
3. [El monolito](#el-monolito)
4. [Microservicios](#microservicios)
5. [Aplicaciones cliente](#aplicaciones-cliente)
6. [Datos compartidos: PostgreSQL y Redis](#datos-compartidos-postgresql-y-redis)
7. [Seguridad](#seguridad)
8. [Pruebas y rendimiento](#pruebas-y-rendimiento)
9. [Mapa del repositorio](#mapa-del-repositorio)
10. [Documentación](#documentación)

---

## Propósito

El sistema administra y vende el catálogo de una librería: libros con varios
autores y géneros, categorías, formatos, precio, existencias, portadas y un
glosario de conceptos por título; usuarios con rol (`admin` y `lector`); pedidos,
pagos simulados y el rastreo en mapa de cada entrega.

El objetivo académico es **integrar aplicaciones heterogéneas** sobre los mismos
datos y comparar estilos de arquitectura:

| Pregunta del curso | Dónde se responde |
|---|---|
| ¿Cómo se ve un monolito MVC bien organizado? | `apps/web-monolito/` |
| ¿Qué cambia al partirlo en servicios con JWT? | `apps/services/{login,users,authors,pedidos,pagos}` |
| ¿Cómo convive un contrato SOAP/WSDL con REST? | `apps/services/soap/` + `clients/` |
| ¿Un mismo servicio puede hablar XML y JSON? | `apps/services/catalogo/` |
| ¿Cómo se empuja información en tiempo real? | `gps/` (WebSocket) |
| ¿Qué aporta una caché y un almacén de sesiones? | Redis en los seis servicios Flask |
| ¿Cuál rinde mejor bajo carga? | `locust_tests/` y `docs/benchmark_proxy/` |

---

## Arquitectura del sistema

```
                         Internet  (IP pública 34.51.108.167, sin dominio)
                                   │
                  ┌────────────────┴─────────────────┐
                  │  Apache httpd  :80 / :443 (TLS)  │  VirtualHost por IP
                  │  (comparte la VM con otro proyecto)│  TLS 1.2/1.3, cert. autofirmado
                  └───────┬──────────────────┬───────┘
                 :80 → 127.0.0.1:8009   :443 → 127.0.0.1:8443
                  ┌───────▼───────┐   ┌──────▼──────────────────────────────┐
                  │ nginx (sitio) │   │ nginx (API gateway): /api/* con JWT │
                  │ /library →    │   │ en el borde, auth_request, WebSocket│
                  │ estáticos     │   │ portadas, /health y /metrics        │
                  └───────┬───────┘   └──┬───┬───┬───┬───┬───┬───┬───┬─────┘
                          │              │   │   │   │   │   │   │   │
                 Monolito Node :3000   login users authors pedidos pagos catálogo soap  gps
                 (Express + EJS)       5000  5003  5004   5005   5006   5002   5001  5900
                          │              └───┴───┴──┬┴───┴───┴───┘      │      │
                          │                        Redis (127.0.0.1:6379)│      │
                          └─────────────────┬─────────────────────────────┴──────┘
                                     PostgreSQL (localhost) — libreria_db
```

- **Una sola base de datos, procesos independientes.** Cada app y cada servicio
  tiene sus dependencias, su `.env` y su unidad de systemd; no comparten código,
  sólo la base. Si uno cae, los demás siguen.
- **Nada escucha directo en internet salvo Apache.** nginx, el monolito,
  PostgreSQL y Redis están en loopback; los servicios se alcanzan por nginx.
- **Tres puertas de entrada:** el navegador (monolito, `/library`), las apps de
  escritorio por HTTPS (API en `/`), y los clientes SOAP.

---

## El monolito

`apps/web-monolito/` — **Node.js + Express + EJS + PostgreSQL**, renderizado en el
servidor, puerto 3000 (publicado como `http://<IP>/library`).

Es la aplicación principal de administración y consulta del catálogo. Una sola
unidad desplegable organizada por **módulos de dominio**, cada uno con tres
archivos: `*.model.js` (todo el SQL, parametrizado), `*.controller.js` (valida,
orquesta y elige la vista) y `*.routes.js` (método + URL → controller con su
middleware). Las vistas viven en `views/<módulo>/`.

| Funcionalidad | Quién |
|---|---|
| Catálogo, detalle, búsqueda, fichas de autor y concepto | `lector` y `admin` |
| CRUD de libros, autores, géneros, categorías, formatos, conceptos | `admin` |
| Subida de portadas (validación en cinco capas) | `admin` |
| Gestión de usuarios (un solo administrador, impuesto en la BD) | `admin` |

Sin JSON entre navegador y servidor (no existe `express.json()` a propósito):
formularios HTML, sesión por cookie y token CSRF.

```bash
cd apps/web-monolito && npm install && npm start   # → http://127.0.0.1:3000
```

---

## Microservicios

Ocho procesos en `apps/services/` y `gps/`. Los seis Flask comparten el mismo
bloque base **copiado** (no importado): JWT, CORS, manejo de errores, Redis y
métricas.

| Servicio | Puerto | Tecnología | Formato | Rutas públicas (vía nginx) | Responsabilidad |
|---|---|---|---|---|---|
| **login** | 5000 | Flask + psycopg + Redis | JSON / XML | `/login` `/register` `/logout` `/session` `/token/refresh` | Autenticación: emite el JWT (HS256, 20 min) y el refresh token de un solo uso; verifica el correo contra Postfix |
| **soap** | 5001 | Flask + SOAP 1.1 a mano | XML / WSDL | `/soap` `/wsdl/library-classifier.wsdl` | Clasifica conceptos en IaaS/PaaS/SaaS/FaaS. WS-Security UsernameToken |
| **catalogo** | 5002 | Flask + psycopg + Redis | XML **y** JSON | `/books` `/concepts` | Catálogo bilingüe con caché de 60 s; escrituras sólo con JWT de admin |
| **users** | 5003 | Flask + psycopg3 | JSON | `/users` | Cuentas; un lector sólo ve la suya; baja lógica |
| **authors** | 5004 | Flask + psycopg3 | JSON | `/authors` | Autores; lectura pública, escritura de admin |
| **pedidos** | 5005 | Flask + psycopg3 | JSON | `/orders` | Pedidos y líneas; ajusta stock con `sp_ajustar_stock` en la misma transacción |
| **pagos** | 5006 | Flask + psycopg3 | JSON | `/payments` | Pagos simulados del dueño del pedido; reembolsos, nunca borrado |
| **gps** | 5900 | Flask + flask-sock | WebSocket | `/track/ws?code=LIB-MTY-…` | Rastreo en tiempo real de la entrega de cada pedido; delega la autorización a pedidos |

Además, `/health/<servicio>` (semáforos de los clientes) y `/metrics/<servicio>`
(JWT de admin) se publican por nginx para los seis servicios Flask.

**API Gateway (`/api/*`).** Por HTTPS, nginx publica también la tabla de rutas
del ejercicio: `/` → monolito, `/api/login`, `/api/books`, `/api/autores`,
`/api/pedidos`, `/api/pagos` y `/api/users`. Sin un JWT válido, el gateway
responde 401 sin llegar al servicio. Las tres apps de escritorio lo usan.
Detalle en [MANUAL_TECNICO.md](MANUAL_TECNICO.md#api-gateway-nginx-rutas-api);
entrega en [docs/gateway/README.md](docs/gateway/README.md).

**Flujo típico de compra (app de escritorio):**

```
POST /login ─► JWT + refresh        GET /books ─► catálogo (caché Redis)
POST /orders ─► pedido + stock      POST /payments ─► pago simulado
wss /track/ws?code=LIB-MTY-2026-000123 ─► posición del repartidor cada segundo
POST /token/refresh (antes de los 20 min)   POST /logout ─► jti revocado
```

---

## Aplicaciones cliente

| App | Carpeta | Tecnología | Qué consume | Para qué |
|---|---|---|---|---|
| **Navegador** | — | HTML renderizado por EJS | Monolito `/library` | Administración y consulta del catálogo |
| **Electron** | `apps/electron-app/` | Electron, sin dependencias de UI | Catálogo **sólo en XML** | Vitrina del catálogo en tarjetas Material Design, 6 por página |
| **Tkinter** | `apps/services/soap/cliente/` | Python + `ttk` | Toda la API por HTTPS + SOAP | Tienda: catálogo con portadas, carrito, compra; paneles CRUD según rol; semáforos de salud |
| **JavaFX** | `apps/JavaDesktop_app/` | Java 21 + JavaFX + Maven | REST + JWT, SOAP, WebSocket | Tienda completa y rastreo del pedido en un mapa Leaflet de Monterrey |
| **Clientes SOAP** | `clients/` | Java y Python | Servicio SOAP (WSDL) | Interoperabilidad del contrato en dos lenguajes |
| **Simulador GPS** | `gps/GPSapp/` | Python | WebSocket `role=gps` | Vehículos que siguen calles reales (OSRM) |

Ninguna app de escritorio toca PostgreSQL: todo pasa por los servicios. Las que
usan HTTPS verifican el certificado autofirmado con una copia local (`CA_CERT`);
la verificación nunca se desactiva.

---

## Datos compartidos: PostgreSQL y Redis

**PostgreSQL** (`libreria_db`, sólo `localhost`) es la fuente de verdad, normalizada
hasta **4FN**: libros, personas/autores, géneros, categorías, formatos, imágenes,
conceptos, usuarios, pedidos, líneas, historial de estados y pagos. Integridad en
la propia base: claves foráneas, `CHECK`, índices únicos parciales (un solo admin,
una sola portada), triggers, procedimientos (`sp_ajustar_stock`) y vistas
(`v_libros_detalle`, `v_pedidos_total`; el total de un pedido es derivado, no
columna). Scripts canónicos en `db/00…06_*.sql`; los cambios se escriben en
`db/pending/` y pasan a `db/applied/` cuando se ejecutan en la VM.

**Redis** es una capa auxiliar compartida por los seis servicios Flask:

| Uso | Clave | TTL |
|---|---|---|
| Sesión de login | `session:<sid>` | 8 h |
| Refresh token (sólo su hash, un solo uso) | `refresh:<sha256>` | 8 h |
| Lista de JWT revocados | `jwt:revoked:<jti>` | lo que le queda al token |
| Limitador de login | `ratelimit:login:<ip>:<correo>` | 15 min |
| Caché del catálogo | `books:list:<filtros>` · `books:<isbn>` | 60 s |
| Métricas entre workers | `metrics:<servicio>:*` | — |

---

## Seguridad

La seguridad se aplica **en capas**: si una falla, la siguiente sigue protegiendo.
Detalle de cada control con su amenaza y su evidencia en
[docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md).

### 1. Red y perímetro

| Control | Detalle |
|---|---|
| Un solo punto expuesto | Sólo Apache (80/443) escucha en la IP pública; nginx, Node, PostgreSQL y Redis escuchan en `127.0.0.1` |
| TLS | Apache termina TLS 1.2/1.3 con un certificado autofirmado para la IP; los clientes lo verifican con `--cacert` / `CA_CERT` |
| Lista blanca de rutas | nginx sólo reenvía las rutas de la API, las portadas (`uuid` + extensión de imagen) y `/health`/`/metrics`; todo lo demás es **404** |
| Doble firewall | Regla de GCP **y** `firewalld` en la VM; el puerto 25 nunca se abre (Postfix sólo en loopback) |
| Proxy sin huella | `server_tokens off`, `ServerSignature Off`, cuerpo máximo 1–3 MB en nginx |

### 2. Autenticación

| Control | Detalle |
|---|---|
| Contraseñas | **bcrypt** (coste 10) en monolito y login, compatibles entre sí; la BD rechaza todo hash que no sea bcrypt (`ck_usuarios_hash_bcrypt`) |
| Sin enumeración de usuarios | Mismo 401 y mismo tiempo (hash señuelo) para correo inexistente, contraseña errónea o cuenta desactivada |
| Fuerza bruta | 5 intentos por IP + correo en 15 min → **429** (en memoria en el monolito, en Redis en login) |
| Sesión del monolito | Cookie `libreria.sid` `httpOnly`, `SameSite=Lax`, `secure` con HTTPS, regenerada al autenticar (anti-fijación) |
| **JWT** | HS256 con algoritmo **fijo** (nunca el del token), 20 min, `iss`, `exp`, `jti` obligatorio; se verifican firma y claims antes de tocar datos |
| Refresh token | Opaco, **de un solo uso** y rotado; Redis guarda sólo su SHA-256 |
| Revocación | `/logout` y cada refresh revocan el `jti`; **todos** los servicios lo consultan en Redis |
| SOAP | WS-Security UsernameToken con PasswordDigest, ventana de frescura y rechazo de *nonces* repetidos; además, nginx exige un JWT válido (`auth_request` contra pedidos) |
| WebSocket de rastreo | El servicio GPS no conoce el secreto: reenvía el JWT a `GET /orders/<id>`; un pedido ajeno se cierra. Revalida cada 60 s |

### 3. Autorización

- **Roles** `admin` / `lector` verificados en el servidor en cada ruta
  (`requireAdmin` en el monolito, `requiere_jwt(*roles)` en los servicios):
  **401** sin credencial, **403** con rol insuficiente. Ocultar botones en la
  interfaz es comodidad, no protección.
- **Propiedad del recurso:** un lector sólo ve su cuenta, sus pedidos y sus pagos.
- **Un solo administrador**, impuesto por el índice único parcial
  `ux_usuarios_admin_unico` (sin condición de carrera).

### 4. Entrada, salida y aplicación web

| Amenaza | Control |
|---|---|
| Inyección SQL | 100 % de consultas parametrizadas (`$1`, `%s`); ninguna concatena datos del usuario |
| XSS | EJS escapa siempre (`<%= %>`); CSP con `script-src 'self'` |
| CSRF | Token de 32 bytes por sesión, comparado en tiempo constante, en todo formulario que escribe |
| Validación | Server-side obligatoria (`services/validacion.js` y validadores de cada servicio); `novalidate` en formularios |
| Subida de archivos | MIME y extensión en lista blanca, 2 MB, **firma binaria** verificada, nombre UUID generado por el servidor, `uploads/` fuera de `public/`, `nosniff`, el proxy niega extensiones ejecutables |
| Cabeceras | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, CSP, sin `x-powered-by` |
| Fugas por errores | Ningún stack trace, nombre de tabla, SQL ni SOAP Fault con detalle llega al cliente; el detalle va al log |
| CORS | `CORS_ORIGENES` en lista explícita; vacío = ninguno, nunca `*` |

### 5. Datos y secretos

- **Mínimo privilegio en PostgreSQL:** `libreria_app` sólo tiene
  `SELECT/INSERT/UPDATE/DELETE` (sin `DROP`/`ALTER`, no es dueño); `libreria_soap`
  sólo lee las columnas que expone su contrato y no puede leer `usuarios`.
- **Ninguna credencial en el repositorio** (ni en comentarios ni en `.sql`). Los
  secretos —`JWT_SECRET_KEY`, `DB_PASSWORD`, `SECRET_KEY`, contraseña de Redis,
  clave TLS— viven sólo en los `.env` (600) de la VM; `.env.example` sólo trae
  nombres. Cada servicio **se niega a arrancar** si le falta un secreto.
- **Redis endurecido:** `bind 127.0.0.1`, `protected-mode`, `requirepass`,
  `maxmemory` con política `volatile-lru`; la contraseña se enmascara en los logs.
- **Falla segura ante caída de Redis:** sesión, refresh y toda ruta con JWT
  fallan **cerrado** (503: no se acepta un token sin comprobar su revocación); sólo
  la lectura del catálogo falla abierto, desde PostgreSQL.

### 6. Procesos en la VM

Cada unidad de systemd corre con usuario sin privilegios y `NoNewPrivileges`,
`PrivateTmp`, `ProtectSystem=strict`, `ProtectHome`, `ProtectKernelTunables`,
`ProtectControlGroups` y `RestrictAddressFamilies`; reinicio automático ante
fallo. SELinux en modo *enforcing* (`restorecon`, `httpd_can_network_connect`).

### Riesgos conocidos

| Riesgo | Estado |
|---|---|
| Contraseñas antiguas en el historial de git (H-01) | Rotadas; borrar el archivo no basta |
| Puertos 5003–5006 aún hablan HTTP y tienen una regla de GCP a una IP vieja | Pendiente: ligarlos a `127.0.0.1` y quitar la regla |
| Regla heredada `allow-3000` en GCP | Pendiente de borrar (Node escucha en loopback, así que no responde) |
| Certificado autofirmado | Cifra igual; faltaría un dominio + Let's Encrypt para eliminar avisos |
| Un cambio de rol tarda hasta 20 min en verse en los servicios | Aceptado: es la vida del JWT; el refresh sí reconsulta la BD |

---

## Pruebas y rendimiento

| Qué | Cómo | Evidencia |
|---|---|---|
| Monolito: 60 casos (funcionales y de seguridad) | `bash tests/pruebas.sh` | `docs/evidencias/` |
| Base de datos: consultas + pruebas negativas de integridad | `db/03_all_quieries_before_stored_procedures.sql` | `docs/evidencias/` |
| Servicios JWT (31 en la VM, 29 desde fuera, HTTP y HTTPS) | `tests/pruebas_servicios.py` | `docs/evidencias/pruebas_servicios_*.txt` |
| Redis (26 pruebas) y caída de Redis | `tests/pruebas_redis.py` (`REDIS_CAIDO=1`) | `docs/evidencias/pruebas_redis_*.txt` |
| Seguridad de cada servicio, sin red | `python3 pruebas.py` en cada carpeta | — |
| SOAP | `apps/services/soap/tests/pruebas_soap.py` | `apps/services/soap/docs/evidencias/` |
| Carga: monolito vs. microservicios (Locust) | `locust_tests/ejecutar.sh <perfil>` | `locust_tests/evidencias/` |
| **Benchmark de proxy inverso, balanceador y API gateway** | `bash docs/benchmark_proxy/ejecutar.sh` | [docs/benchmark_proxy/BENCHMARK.md](docs/benchmark_proxy/BENCHMARK.md) |

Las credenciales de prueba se pasan siempre por variable de entorno.

---

## Mapa del repositorio

| Ruta | Qué es |
|---|---|
| `apps/web-monolito/` | Monolito Node + Express + EJS |
| `apps/services/{login,catalogo,soap,users,authors,pedidos,pagos}/` | Microservicios Python |
| `apps/electron-app/` · `apps/JavaDesktop_app/` | Clientes de escritorio |
| `clients/` | Clientes SOAP en Java y Python |
| `gps/` | Microservicio WebSocket, simulador GPS y mapa |
| `db/` | Scripts canónicos `00…06`, `pending/` y `applied/` |
| `deploy/` | Apache, nginx, unidades de systemd, endurecimiento de Redis |
| `tests/` · `locust_tests/` | Pruebas funcionales, de seguridad y de carga |
| `docs/` · `evidencias/` | Documentación, reportes y capturas |

Cada app se instala y arranca desde su propia carpeta (no hay workspaces); ver el
README de cada una.

---

## Documentación

| Documento | Contenido |
|---|---|
| [MANUAL_TECNICO.md](MANUAL_TECNICO.md) | Manual técnico completo: rutas, esquema, variables, despliegue |
| [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) | Controles, hallazgos y riesgos residuales |
| [docs/ENGINEERING_DECISIONS.md](docs/ENGINEERING_DECISIONS.md) | Decisiones con alternativas y condición de reversa |
| [docs/TECHNICAL_REPORT.md](docs/TECHNICAL_REPORT.md) | Reporte técnico |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) · [docs/TEST_PLAN.md](docs/TEST_PLAN.md) | Requisitos y plan de pruebas |
| [docs/GCP_COMMANDS.md](docs/GCP_COMMANDS.md) | Infraestructura y despliegue en GCP |
| [docs/benchmark_proxy/BENCHMARK.md](docs/benchmark_proxy/BENCHMARK.md) | Benchmark de proxy inverso, balanceador y API gateway |
| [docs/gateway/README.md](docs/gateway/README.md) | API Gateway con nginx: apps de escritorio por `/api/*`, evidencias y configuración |
| [gps/README.md](gps/README.md) | GPS en tiempo real |
| [docs/javadesktop/AppJava.pdf](docs/javadesktop/AppJava.pdf) | Entrega de la app Java |
