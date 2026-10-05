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
  `usuarios.rol` en texto), `rol`, `email`, `iss='login-libreria'`. Renovable con
  `POST /token/refresh` (Bearer vigente; uno vencido exige `/login`). Cada
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
- Tras `git pull` en la VM, un servicio sólo toma el código nuevo con
  `sudo systemctl restart libreria-<n>`.

### Cómo trabaja el usuario en la VM

El usuario ejecuta los comandos en la VM y pega la salida; Claude no tiene acceso.
**Un paso por mensaje**, con **un comando por bloque** y sin cadenas con `;`: su
terminal al pegar añade una `\` antes del `;` y rompe el comando. Su shell en el
Mac es zsh (`read "VAR?texto"`, no `read -p`). Las contraseñas se piden con
`read -s` y nunca se pegan en el chat.

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
