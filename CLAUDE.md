# CLAUDE.md

Librería Online — **monorepo**. La pieza principal es la app monolítica
Node.js + Express + **EJS** + PostgreSQL (`apps/web-monolito/`), patrón MVC
organizado por módulos de dominio; a su lado viven un cliente de escritorio y
siete microservicios Python que hablan con la misma base.
Documentación completa en [README.md](README.md).

## Mapa del monorepo

| Ruta | Qué es |
|---|---|
| `apps/web-monolito/` | El monolito Node + Express + EJS. Puerto 3000 |
| `apps/electron-app/` | Cliente de escritorio Electron |
| `apps/services/catalogo/` | Microservicio Flask de catálogo, bilingüe XML/JSON. Puerto 5002 |
| `apps/services/soap/` | Microservicio SOAP de clasificación Cloud, con WSDL. Puerto 5001 |
| `apps/services/login/` | Microservicio Flask de autenticación. Puerto 5000 |
| `apps/services/users/` `authors/` `pedidos/` `pagos/` | Microservicios Flask JSON + JWT del ejercicio guiado de servicios. Puertos 5003 · 5004 · 5005 · 5006 |
| `clients/` | Clientes Java y Python del servicio SOAP |
| `db/` `deploy/` `docs/` `tests/` `evidencias/` | Compartidos por todo el repo: SQL · despliegue · documentación · pruebas · capturas |

Cada app y cada servicio es autónomo: sus dependencias, su `.env` y su unidad
de systemd son suyos. No comparten código, sólo la base de datos. Antes de
tocar algo, ubica en qué carpeta de `apps/` vive.

### Al escribir una ruta, ten presente

El monolito vivía en la raíz hasta 2026-09-21. Si algo suena a ruta del
monolito, va con prefijo — es el error fácil de cometer aquí:

- Las rutas de código del monolito (`app.js`, `src/`, `views/`, `middleware/`,
  `config/`, `services/`, `public/`, `uploads/`) son **relativas a
  `apps/web-monolito/`**. Dentro de esa carpeta se escriben tal cual; desde la
  raíz o desde un documento de `docs/`, con el prefijo completo.
- `db/`, `deploy/`, `docs/`, `tests/` y `evidencias/` siguen en la raíz y se
  escriben sin prefijo. `npm` y `node` se ejecutan desde `apps/web-monolito/`;
  `bash tests/pruebas.sh` y `sudo cp deploy/…`, desde la raíz.
- Los documentos de `docs/` que vienen de entregas anteriores llevan una nota al
  inicio aclarando esa relatividad, en vez de tener las rutas reescritas una por
  una. Si agregas una ruta nueva ahí, escríbela completa.
- Ojo con el nombre `soap`: `apps/services/soap/` es el **servicio SOAP**
  (WSDL, 5001), y `apps/services/catalogo/` es el de catálogo XML/JSON (5002),
  que antes se llamaba `services/soap/`. Al leer historial o documentos viejos,
  `services/soap` significa el de catálogo.
- `docs/ejercicio03/publicar.sh` empaqueta `apps/services/soap/` pero conserva
  el nombre `library_soap_service.tar.gz`: el enlace ya está publicado en
  `index.html`. No lo renombres.

## Regla crítica: cambios en la base de datos

La base de datos **no es local**: corre en PostgreSQL instalado en una VM de GCP,
donde también está clonado el repo y corre la app. No hay conexión a la BD desde
este entorno y no se dispone de sus credenciales — nunca asumas que puedes
ejecutar una query ni verificar el esquema real.

Por eso, **todo SQL se escribe pero no se ejecuta**:

1. Cualquier cambio que toque la BD (tabla nueva, columna, índice, `ALTER`,
   corrección de datos) se escribe como archivo en `db/pending/`.
2. Nombre: `YYYYMMDD-descripcion-corta.sql`, con un comentario al inicio
   explicando qué hace y por qué.
3. `db/applied/` es historial de lo ya ejecutado en la VM. Mueve ahí un archivo
   de `db/pending/` con `git mv` **en cuanto el usuario confirme que ya corrió la
   query** en la VM — nunca antes ni por tu cuenta. Tampoco edites los que ya
   están.
4. Si algo aplicado hay que corregir, se escribe un archivo nuevo en
   `db/pending/`, no se modifica el viejo.
5. **Nunca escribas una credencial en claro en el `.sql`, ni siquiera en los
   comentarios.** Va el hash y nada más; el comentario dice qué hace la query, no
   cuál es el valor.

En el mismo cambio, siempre:

- Actualizar [`db/01_schema.sql`](db/01_schema.sql) para que refleje el estado
  final de las tablas.
- Actualizar el **diagrama de relaciones** del README (sección "Base de datos").

Nada valida `db/01_schema.sql` contra la VM automáticamente: si se saltan esos
dos pasos, la documentación del esquema queda mintiendo. Ver
[Flujo de cambios en la base de datos](README.md#flujo-de-cambios-en-la-base-de-datos).

### Scripts canónicos de `db/`

`db/00…06_*.sql` reconstruyen la base desde cero y **son entregables del
ejercicio**: se ejecutan en ese orden y no se reordenan. Ojo con dos detalles ya
resueltos, para no reintroducirlos:

- `fn_buscar_libros` (en `04`) lee de `v_libros_detalle` (creada en `06`). Está
  declarada en `plpgsql`, no en `sql`, porque el cuerpo de una función `sql` se
  valida al crearla y la vista todavía no existe en ese momento.
- `02` siembra imágenes con `es_portada = true` **antes** de que existan los
  triggers de `05`. Es correcto; no muevas el orden.

## Arquitectura del monolito

Las rutas de esta sección son **relativas a `apps/web-monolito/`**.

| Directorio | Responsabilidad |
|---|---|
| `app.js` | Inicialización de Express, middleware general, montaje de rutas, arranque |
| `config/` | `env.js` (lee y valida `.env`) · `db.js` (Pool único de `pg`). **Nada más lee `process.env`** |
| `middleware/` | `auth.js` · `locals.js` (CSRF) · `subidas.js` (Multer) · `errores.js` |
| `services/` | `validacion.js` (validación server-side) · `crudCatalogo.js` (lógica común de catálogos) |
| `src/modules/<n>/` | Un dominio: `<n>.model.js` · `<n>.controller.js` · `<n>.routes.js` |
| `views/` | Plantillas EJS. `views/parciales/` para lo compartido |
| `public/` `uploads/` | Estáticos · imágenes subidas (fuera de `public/`) |

Cada módulo de dominio tiene exactamente tres archivos JS:

| Archivo | Responsabilidad |
|---|---|
| `*.model.js` | Todo el SQL (parametrizado). Devuelve datos puros, no conoce HTTP ni HTML |
| `*.controller.js` | Valida, llama al model, elige la vista y responde. Sin SQL ni HTML |
| `*.routes.js` | Mapea método + URL → controller, con middleware. Sin lógica |

Las vistas viven en `views/<modulo>/*.ejs`, no dentro del módulo: es donde
Express las busca y comparten parciales entre dominios.

Un módulo nuevo se registra en [app.js](apps/web-monolito/app.js) con
`app.use('/ruta', require('./src/modules/<nombre>/<nombre>.routes'));`.

Al agregar código, sigue el patrón del módulo vecino más parecido en vez de
introducir estructuras nuevas. Si el módulo es un catálogo simple
(`nombre` + `descripcion`), su controller se resuelve con
`services/crudCatalogo.js` y sus vistas con `views/catalogo/`.

## Convenciones

- **EJS renderizado en el servidor.** Sin JSON ni XML entre navegador y servidor;
  no hay `express.json()` a propósito.
- **Escapado.** Usa siempre `<%= %>`, que escapa. `<%- %>` se reserva
  **exclusivamente** para `include` de parciales, nunca para datos.
- **Prefijo de rutas.** Todo enlace y todo `action` se construye como
  `<%= base %>/…`, y todo `redirect` como `res.locals.base + '/…'`. Sin eso, la
  app se rompe al publicarse bajo `/library` en la VM.
- **CSRF.** Todo formulario que escribe incluye
  `<%- include('../parciales/csrf') %>`. Para `multipart/form-data`,
  `verificarCsrf` va **después** de `subirImagen` en la ruta (el token viaja en
  el cuerpo y sólo existe una vez que Multer lo parseó).
- **Sin ORM:** `pg` directo, siempre con queries parametrizadas (`$1`, `$2`…).
  Ninguna consulta concatena valores del usuario.
- **Validación server-side obligatoria.** Todo lo que entra por `req.body` pasa
  por `services/validacion.js`. Los formularios llevan `novalidate`: la
  validación del navegador es ayuda visual, no control.
- **Errores.** Los controllers async se envuelven con `asyncH(...)` en la ruta.
  El usuario final nunca ve un stack trace, un nombre de tabla ni SQL.
- Código y documentación en español, igual que los nombres de tablas y módulos.
- **Ninguna credencial en claro en el repositorio.** Ni contraseñas, ni tokens,
  ni claves de API — en código, documentación, `.sql`, ejemplos del README **y
  tampoco en los comentarios**. Las credenciales reales viven sólo en el `.env`
  de la VM, que no está versionado.
  El repositorio es público y el historial de git conserva cada versión: borrar
  el archivo después no deshace la publicación, sólo rotar la credencial lo hace.
  Si detectas una credencial en claro ya versionada, díselo al usuario en vez de
  limitarte a borrarla.

## Servicios del ejercicio guiado (Users, Authors, Pedidos, Pagos) — estado 2026-10-04

**Desplegado y probado en la VM** (31 pruebas en la VM, 29 desde fuera, por HTTP
y por HTTPS, 0 fallos; evidencias en `docs/evidencias/pruebas_servicios_*.txt`).
Cada servicio es un `app.py` Flask + psycopg3 con pool, `.env` propio y unidad
`deploy/libreria-<n>.service`. Las cuatro comparten el mismo bloque base
(JWT, CORS, errores) **copiado**, no importado: un cambio ahí se replica a mano
en los cuatro `app.py`. Detalle y despliegue: [README.md](README.md), sección
"Microservicios Users, Authors, Pedidos y Pagos (JWT)".

| Servicio | Puerto | Rutas | Quién escribe |
|---|---|---|---|
| users | 5003 | `/users` | admin; un lector sólo su cuenta; DELETE = baja lógica |
| authors | 5004 | `/authors` | admin; los GET son públicos |
| pedidos | 5005 | `/orders` | cualquier autenticado sobre lo suyo; estados sólo admin |
| pagos | 5006 | `/payments` | dueño del pedido o admin; pagos simulados |

- **JWT.** Lo emite `login` (5000): HS256, **20 min**, claims `sub`, `user_id`,
  `role_id` (admin=1, lector=2, mapa `ROLES_ID` en login; la BD sigue con
  `usuarios.rol` en texto), `rol`, `email`, `iss='login-libreria'`. Lleva `jti`.
  Renovable con `POST /token/refresh` y el `refresh_token` opaco de un solo uso
  que entrega `/login` (rotación). Cada
  servicio verifica firma, `algorithms=['HS256']` fijo, `exp`, `iss` y claims;
  401 sin token válido, 403 con rol insuficiente. El catálogo (5002) sigue
  validando por `rol == 'admin'`.
- **Secreto.** `JWT_SECRET_KEY`, **el mismo valor** en el `.env` de login y de los
  cuatro (login y catálogo aceptan también el nombre viejo `JWT_SECRET`).
  Sin él, ninguno arranca. `CORS_ORIGENES` lista orígenes; vacío = ninguno,
  nunca `*`.
- **BD, normalizada hasta 4FN** (exigencia del usuario para todo cambio):
  [db/applied/20261004-pedidos-pagos.sql](db/applied/20261004-pedidos-pagos.sql)
  ya corrió en la VM. Catálogos `estados_pedido`, `estados_pago`, `metodos_pago`;
  `pedidos`, `pedidos_lineas`, `pedidos_estados_historial` (lo llena el trigger
  `trg_pedido_historial`; el servicio fija `app.usuario_id` con `set_config`),
  `pagos`, vista `v_pedidos_total`. **No hay columna `total`**: es derivado y se
  lee de la vista. El stock vive en `libros.stock` y se ajusta sólo con
  `sp_ajustar_stock`, en la misma transacción que el pedido.
- **HTTPS.** `deploy/nginx-api-tls.conf` (nginx, 443) reenvía `/login`,
  `/register`, `/logout`, `/session`, `/token/*` → 5000, `/users` → 5003,
  `/authors` → 5004, `/orders` → 5005, `/payments` → 5006. **No hay dominio, sólo
  la IP**, así que el certificado es **autofirmado** (en la VM:
  `/etc/pki/tls/certs/libreria-api.crt` y su clave en `/etc/pki/tls/private/`,
  nunca en el repo). `curl` necesita `--cacert`; el flujo completo corre con
  `CA_CERT=<crt> HOST=<ip> … python3 tests/pruebas_servicios.py`.
- **Pendiente (opcional):** los puertos 5003–5006 siguen hablando HTTP y abiertos
  a una IP concreta en GCP (`libreria-permitir-servicios-jwt`) y en `firewalld`;
  para que HTTPS proteja de verdad, ligar las unidades a `127.0.0.1` y cerrar esos
  puertos. Login (5000) y catálogo (5002) no se han tocado.
- **Pruebas.** `python3 pruebas.py` en cada carpeta (seguridad, sin BD) y
  `tests/pruebas_servicios.py` contra la VM, con credenciales por variable de
  entorno (`ADMIN_EMAIL`, `ADMIN_PASS`, `LECTOR_EMAIL`, `LECTOR_PASS`). Deja una
  cuenta de prueba dada de baja y un pedido cancelado con su pago reembolsado:
  los pagos no se borran.

### Redis (desplegado y probado en la VM el 2026-10-05)

- **Capa compartida y auxiliar**, `REDIS_URL` común en login, catálogo, users,
  authors, pedidos y pagos (contraseña sólo en el `.env` de la VM). Claves:
  `session:<sid>`, `refresh:<sha256>` (el refresh nunca en claro, un solo uso),
  `jwt:revoked:<jti>`, `ratelimit:login:*`, `books:list:<filtros>` y
  `books:<isbn>` (60 s), `metrics:<servicio>:*`. Tabla de TTL en el README.
- **Política ante caída:** sesión, refresh, logout y **toda ruta con JWT** fallan
  **cerrado** (503; nunca se acepta un token sin poder comprobar la revocación);
  `GET /books` y `/books/<isbn>` fallan **abierto** (PostgreSQL). `/health` sigue
  200 con `redis: caido` → semáforo amarillo en el cliente.
- Cada `app.py` lleva **copiado** el mismo bloque Redis (`redis_cliente`,
  `redis_op`, `revocado`, `metrica`, `invalidar_catalogo`, `/metrics`): un cambio
  se replica a mano en los seis. `jti` es claim **obligatorio** en `reclamos_jwt`.
  `authors` y `pedidos` invalidan `books:*` tras escribir (autores y stock se ven
  en el catálogo).
- **Estado en la VM:** Redis es el paquete `redis` del módulo de remi
  (`redis.service`), `/etc/redis/redis.conf` con `bind 127.0.0.1`,
  `protected-mode yes`, `requirepass` (la contraseña sólo vive ahí y en el
  `REDIS_URL` de los **seis** `.env`), `maxmemory 128mb` y
  `maxmemory-policy volatile-lru`. Los seis servicios corren con el código nuevo.
  Evidencias: `docs/evidencias/pruebas_redis_vm.txt` (26 pruebas, 0 fallos) y
  `docs/evidencias/pruebas_redis_caida_vm.txt` (Redis parado: login 503, sin token
  401, `GET /books` 200 desde PostgreSQL, semáforos en amarillo). Métricas por
  nginx: `/metrics/<servicio>` (JWT de admin).
- Pruebas locales con un `RedisFalso` en memoria (cada `pruebas.py`) y
  `tests/pruebas_redis.py` contra la VM (`REDIS_CAIDO=1` para la prueba de caída).

### Cliente de escritorio (Tkinter)

La app Tk es la **ya existente** `apps/services/soap/cliente/cliente_escritorio.py`,
ampliada (no hay otra): el clasificador SOAP quedó como una pestaña y se
añadieron Libros, Autores, Usuarios, Pedidos y Pagos, sesión JWT con renovación
automática y semáforos. Módulos hermanos: `api_rest.py` (red/JWT/semáforos) y
`pestanas.py`. Habla por HTTPS (`API_BASE`, `CA_CERT`) a nginx; para eso
`deploy/nginx-api-tls.conf` expone `/books`, `/concepts` y `/health/<servicio>`.
Pruebas sin pantalla: `apps/services/soap/tests/pruebas_cliente_rest.py`.

### Datos de la VM que cuestan averiguar

- Dueño real de las tablas: `libreria_user` (no `libreria_owner`, que aparece en
  los scripts). Para correr un `.sql` de `db/pending/` sin pedir su contraseña:
  `(echo "SET ROLE libreria_user;"; cat archivo.sql) | sudo -u postgres psql -d libreria_db -v ON_ERROR_STOP=1`.
- El rol `libreria_app` es el de los servicios; los `GRANT` a tablas nuevas van
  explícitos en el `.sql`.
- Tras `pip install` en un servicio nuevo: `sudo restorecon -R` sobre su carpeta o
  systemd falla con 203/EXEC.
- `curl -s ifconfig.me` en la VM da la IP **de la VM**; para la del usuario hay
  que correrlo en su Mac. Desde la propia VM, la IP pública no sirve para probar
  un puerto nuevo (sale a la red de Google y `firewalld` lo descarta): probar con
  `--connect-to <ip>:443:127.0.0.1:443`.
- **La IP del usuario cambia** (otra red): las reglas de GCP
  `libreria-permitir-api-tls` (443) y `libreria-permitir-servicios-jwt`
  (5003–5006) sólo aceptan la IP con que se crearon; si de pronto todo da timeout
  desde su Mac, comparar `curl -s ifconfig.me` (en el Mac) y
  `gcloud compute firewall-rules update <regla> --source-ranges=<ip>/32`.
  El 443 se actualizó a 189.159.107.64; la de 5003–5006 sigue con la IP vieja.
- Un `requirements.txt` que no lleva una dependencia nueva rompe el servicio sólo
  en la VM (`ModuleNotFoundError` en el worker de gunicorn): al añadir una
  librería, revisar el `requirements.txt` de **cada** servicio que la importe.
- Tras `git pull` en la VM, un servicio sólo toma el código nuevo con
  `sudo systemctl restart libreria-<n>`.

### Cómo trabaja el usuario en la VM

El usuario ejecuta los comandos en la VM y pega la salida; Claude no tiene acceso.
**Un paso por mensaje**, con **un comando por bloque** y sin cadenas con `;`: su
terminal al pegar añade una `\` antes del `;` y rompe el comando. Su shell en el
Mac es zsh (`read "VAR?texto"`, no `read -p`). Las contraseñas se piden con
`read -s` y nunca se pegan en el chat.

## Secretos: dónde vive cada uno (nunca sus valores)

Ningún valor de esta tabla está en el repositorio, ni en el chat, ni en un log.
Si una sesión necesita uno, **pídele al usuario que lo escriba él** (`read -s`) o que
lo lea en la VM; no lo pidas pegado en la conversación.

| Secreto | Dónde está | Notas |
|---|---|---|
| Contraseña de **Redis** | VM: `requirepass` en `/etc/redis/redis.conf` y `REDIS_URL=redis://:<pass>@127.0.0.1:6379/0` en el `.env` de **los seis** servicios (login, catalogo, users, authors, pedidos, pagos) | Generada con `secrets.token_urlsafe(32)` el 2026-10-05. Para usar `redis-cli`: `REDISCLI_AUTH='<pass>' redis-cli PING` |
| `JWT_SECRET_KEY` | VM: `.env` de login y de los 4 servicios nuevos; el de **catalogo** y el de login conservan el nombre viejo `JWT_SECRET` | El **mismo valor** en todos. Cambiarlo invalida todos los tokens |
| `DB_PASSWORD` (rol `libreria_app`) | VM: `.env` de cada servicio y del monolito | Mismo valor; los 4 nuevos lo copiaron del `.env` de login |
| `SECRET_KEY` (cookie de login) | VM: `apps/services/login/.env` | Distinta de `JWT_SECRET_KEY`; sólo firma la cookie con el `sid` |
| Clave del certificado TLS | VM: `/etc/pki/tls/private/libreria-api.key` (600, root) | Nunca sale de la VM |
| Certificado público TLS | VM: `/etc/pki/tls/certs/libreria-api.crt`; copia en el Mac del usuario: `~/libreria-api.crt` (`gcloud compute scp`) | Autofirmado para la IP `34.51.108.167`; vence a un año de 2026-10-04 |
| Contraseñas de las cuentas de prueba | **No se guardan**. Las pruebas las reciben por `ADMIN_PASS`/`LECTOR_PASS` | Admin de prueba: `admin@libreria.com`. Lector: `cesar.villalobos@libreria.udem.mx` (el del monolito es `ana.ruiz@libreria.udem.mx`) |

Los `.env` de la VM son `600`, dueño `pablogcp26`, y **no están versionados**; los
`.env.example` sólo traen claves vacías o `CONTRASENA` de relleno.

**Rotar la contraseña de Redis** (si se filtra): generar otra, cambiar `requirepass`
en `/etc/redis/redis.conf`, reescribir la línea `REDIS_URL` en los seis `.env`
(`sed -i '/^REDIS_URL=/d'` y volver a añadirla), `sudo systemctl restart redis` y
reiniciar los seis servicios. Rotar el secreto JWT cierra todas las sesiones.

## Bitácora de la sesión 2026-10-04 / 05 (qué se hizo, en orden)

1. **Servicios Users, Authors, Pedidos y Pagos** (5003–5006) con JWT; login con JWT de
   20 min, `user_id` y `role_id`. Migración `db/applied/20261004-pedidos-pagos.sql`
   (4FN) aplicada en la VM. Pruebas: 31 en la VM, 29 desde fuera.
2. **HTTPS**: `deploy/nginx-api-tls.conf` en el 443 con certificado autofirmado (sin
   dominio). Pruebas por HTTPS: `docs/evidencias/pruebas_servicios_https.txt`.
3. **Redis** en los seis servicios (sesión, refresh de un solo uso, revocación por
   `jti`, caché del catálogo, limitador de login, métricas) con falla cerrada/abierta.
   Pruebas en la VM: `pruebas_redis_vm.txt` (26/0 fallos) y `pruebas_redis_caida_vm.txt`.
4. **App de escritorio** `cliente_escritorio.py` ampliada (pestañas REST, sesión,
   semáforos), verificada a mano contra la VM: login admin, CRUD de autores, y
   semáforos en amarillo/rojo al parar Redis y de vuelta a verde al arrancarlo.
5. **Errores que costaron tiempo** (no repetir): `redis` faltaba en el
   `requirements.txt` de login (el worker no arrancaba); `/metrics` no existía en
   login ni estaba en nginx; la IP del usuario cambió y las reglas de GCP daban
   timeout; pegar en zsh un `;` lo convierte en `\;`.
6. **Pendiente opcional:** cerrar 5003–5006 hacia fuera (ligar a `127.0.0.1` y quitar
   reglas), probar la app con el usuario lector, borrar el libro de prueba
   `9999999999998 / Evidencia curl`, y rediseño visual de la app (portadas).

## Comandos

```bash
cd apps/web-monolito
npm install
npm start        # → http://127.0.0.1:3000  (node app.js)
```

No hay workspaces de npm ni herramienta de monorepo: cada app se instala y se
arranca desde su propia carpeta. Los servicios Python, cada uno con su `.venv`
y su `requirements.txt` (ver el README de cada uno).

Pruebas (requieren la app levantada y las credenciales por variable de entorno):

```bash
BASE_URL=http://127.0.0.1:3000 ADMIN_EMAIL=… ADMIN_PASS=… \
LECTOR_EMAIL=… LECTOR_PASS=… bash tests/pruebas.sh   # desde la raíz del repo
```

`BASE_URL` **lleva el prefijo público**: el script concatena `"$BASE_URL/login"`
y no sabe nada de `BASE_PATH`. En la VM va `http://127.0.0.1:3000/library`; en
local, sin `BASE_PATH`, sin sufijo. Sin el prefijo todo da 404 y luego 403,
porque el script no llega a leer el token CSRF — parece un fallo de seguridad y
es una URL mal armada. El lector de prueba es `ana.ruiz@libreria.udem.mx`. Si
salen 429, es el limitador de intentos de login: vive en memoria del proceso y
se borra reiniciando el servicio.

### Actualizar la VM

El `git pull` solo no basta desde que el monolito se mudó: `npm ci` se corre
dentro de `apps/web-monolito/` y la unidad de systemd hay que recopiarla, porque
su `WorkingDirectory` cambió.

```bash
cd /opt/udem/libreria && git pull
cd apps/web-monolito && sudo npm ci --omit=dev
sudo cp /opt/udem/libreria/deploy/libreria.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl restart libreria
```

Los `alias` de `uploads/` y `public/` en la configuración del proxy también
cambiaron: si se sirven imágenes o CSS en 404, es eso. Ver
[docs/GCP_COMMANDS.md](docs/GCP_COMMANDS.md).

No hay build ni linter. No intentes ejecutarlos.
