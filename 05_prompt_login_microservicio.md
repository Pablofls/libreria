# Tarea: microservicio de login en `apps/services/login` + normalización del nombre

Dos cosas en el mismo cambio: separar el nombre de `usuarios` en su propia
tabla, y construir sobre ella un microservicio Flask de registro/sesión que
responde en XML y JSON.

## 1. Normalización: el nombre sale de `usuarios`

Hoy `usuarios` tiene una sola columna `nombre VARCHAR(100) NOT NULL` (ver
`db/01_schema.sql`). El registro del microservicio pide **nombre, apellido
paterno y apellido materno** por separado, así que esos tres campos viven en
una tabla nueva y `usuarios` apunta a ella con una FK.

**La restricción dura: el monolito Node no se toca y no se puede romper.**
Antes de escribir una línea de SQL, lee `src/modules/usuarios/usuarios.model.js`
y las vistas `views/usuarios/*.ejs`: el monolito hace `SELECT nombre`,
`INSERT ... (nombre, ...)` y `UPDATE ... SET nombre = $1` sobre `usuarios`. Todo
eso tiene que seguir funcionando **sin editar ni un archivo JS ni un EJS**.

Eso obliga a una decisión de compatibilidad que quiero explícita y argumentada,
no resuelta en silencio: `usuarios.nombre` no puede desaparecer ni volverse
`GENERATED` (el monolito la escribe). Propón el mecanismo —columna conservada
más triggers de sincronización en ambos sentidos, u otro— y explica qué pasa
cuando el monolito inserta un usuario nuevo escribiendo sólo `nombre`, y qué
pasa cuando el microservicio inserta los tres campos. Si el mecanismo tiene un
punto ciego, dilo en vez de taparlo.

Ojo con las restricciones que ya existen en la tabla y que un `INSERT` mal hecho
va a golpear: `ck_usuarios_nombre` (nombre no vacío), `uq_usuarios_email`,
`ck_usuarios_rol`, `ck_usuarios_email`, `ck_usuarios_hash_bcrypt` y el índice
único parcial `ux_usuarios_admin_unico` (un solo admin).

### Reglas de base de datos (no negociables, están en CLAUDE.md)

- **La BD vive en una VM de GCP y no es alcanzable desde aquí.** No intentes
  conectarte, ni verificar el esquema real, ni ejecutar nada.
- El SQL se escribe, no se ejecuta: un archivo nuevo en
  `db/pending/YYYYMMDD-descripcion-corta.sql`, con el comentario de cabecera
  explicando qué hace y por qué. No lo muevas a `db/applied/`.
- El script debe ser idempotente y llevar el backfill: crear la tabla, poblarla
  desde los `nombre` que ya existen (explica cómo parte un nombre suelto en tres
  campos y qué haces cuando no se puede partir), y sólo entonces añadir la FK y
  su `NOT NULL`.
- En el mismo cambio, actualiza `db/01_schema.sql` (estado final) y el diagrama
  de relaciones del README, sección "Base de datos".
- Los scripts canónicos `db/00…06_*.sql` son entregables y se ejecutan en ese
  orden: si tu tabla nueva obliga a tocarlos, hazlo respetando el orden y di por
  qué.
- Ninguna credencial en claro, ni en el SQL ni en sus comentarios.

## 2. El microservicio

En `/services/login`, con **Python + Flask + Psycopg 3 + PostgreSQL**,
contra la base `library` que ya existe. Puerto **5000**.

| Método | Endpoint | Función |
|---|---|---|
| POST | `/register` | Alta de usuario (nombre, apellido paterno, apellido materno, email, password) |
| POST | `/login` | Autentica y abre sesión |
| POST | `/logout` | Cierra la sesión |
| GET | `/session` | Dice si hay sesión autenticada y de quién |
| GET | `/health` | Estado del servicio y de PostgreSQL |

Contrato de formato, idéntico al que ya sigue `services/soap/app.py` —léelo y
reaprovecha su enfoque: `?format=json` responde JSON, `?format=xml` o **sin el
parámetro** responde XML. Aplica a **todos** los endpoints y también a los
manejadores de error (400, 401, 404, 405, 409, 503 y el `Exception` genérico):
un cliente JSON nunca debe recibir un XML de error. Un solo punto de verdad —
estructura neutra en Python y un despachador que elige serializador—, no dos
serializadores en paralelo.

Cuidado con dos cosas concretas:

- **El hash.** `ck_usuarios_hash_bcrypt` exige un bcrypt de 60 caracteres
  (`$2a$/$2b$/$2y$`). El `generate_password_hash` por defecto de Werkzeug es
  pbkdf2 y la BD lo va a rechazar: usa bcrypt de verdad, compatible con el que
  genera el monolito, para que un usuario registrado aquí pueda entrar allá.
  La contraseña en claro no se guarda, no se registra en logs y no se devuelve.
- **El puerto 5000.** `services/soap/app.py` usa 5000 por defecto. Confirma que
  los dos no se levantan a la vez en la VM o documenta cómo conviven; no lo
  decidas en silencio.

**Esto es un servicio, no una aplicación web.** No hay interfaz: ni HTML, ni
plantillas, ni formularios, ni páginas de login. Los cinco endpoints reciben
datos y devuelven XML o JSON, y nada más. Lo único que puede servir HTML es la
página de Swagger.

El email se valida antes de registrar y es único: un duplicado es un 409
explicado, no una traza de `UniqueViolation`. La sesión es del lado de Flask
(cookie firmada); la clave sale de variable de entorno, con el servicio negándose
a arrancar si falta, nunca un valor por defecto en el código. SQL siempre
parametrizado. El rol de un alta por este endpoint es `lector`.

Añade el `requirements.txt` y un README corto con cómo levantarlo. Documenta los
endpoints con **Swagger**, declarando el parámetro `format` y las respuestas en
`application/xml` y `application/json` para cada operación.

## 3. El correo se valida contra Postfix, no sólo con una expresión regular

No basta con que el email tenga forma de email: hay que comprobar que la
dirección **existe de verdad**, y eso se hace con el Postfix que corre en la VM.

Escalona la validación y no la mezcles:

1. **Sintaxis y unicidad**, en la app y en la BD (`ck_usuarios_email`,
   `uq_usuarios_email`). Es lo barato y va primero.
2. **El dominio resuelve** (registro MX, o A como respaldo). Un dominio sin MX
   no recibe correo: rechazo inmediato, sin molestar a Postfix.
3. **La dirección existe**, preguntándoselo a Postfix en `localhost:25`. Postfix
   tiene verificación de destinatario nativa —`reject_unverified_recipient` con
   su `address_verify_map`—, que hace la sonda `RCPT TO` contra el servidor
   destino y cachea el resultado. Úsala en vez de improvisar un diálogo SMTP a
   mano desde Python.

Lo importante es cómo interpretas la respuesta, y quiero que lo dejes escrito:

- Un **5xx** en `RCPT TO` es un rechazo firme: la dirección no existe → 400.
- Un **4xx**, un timeout o un greylisting **no prueban nada**. No conviertas un
  "no sé" en un "no existe": decide una política —aceptar el registro marcándolo
  como no verificado, o pedir reintento— y justifícala.
- Un dominio **catch-all** acepta cualquier cosa. La verificación por SMTP tiene
  ese techo y hay que decirlo en la reflexión, no fingir que es infalible.
- La sonda tarda. No dejes que un `/register` se cuelgue esperando a un MX
  lento: pon timeout explícito y un fallo controlado.

Configura Postfix en la VM como **relay de sólo salida escuchando en loopback**,
nunca como open relay. Deja la configuración y los comandos en el README del
servicio y en `docs/GCP_COMMANDS.md`, y advierte del detalle práctico: **GCP
bloquea el puerto 25 saliente en las VMs**, así que la sonda directa a Internet
no va a funcionar sin un relay autenticado (o sin cambiar de puerto). Di cómo lo
resuelves; si acabas dependiendo de un relay con credenciales, esas credenciales
van al `.env` de la VM y **no al repositorio**, ni siquiera de ejemplo.

## 4. Evidencias y reflexión

**Las capturas las tomo yo:** no tienes acceso a la VM ni al navegador. Prepara
la carpeta siguiendo el patrón de `docs/ejercicio03/` —**pregúntame el número de
ejercicio antes de crearla**—, con el documento que explica cada endpoint, la URL
o el `curl` exacto de cada captura, los huecos con el nombre de archivo que debo
usar, y la reflexión.

La reflexión es lo que se califica, y va sobre las decisiones de *este* código,
no sobre REST en general: por qué el nombre se separa en su propia tabla y qué
anomalía evita; por qué la columna vieja se conserva y qué se rompería si se
borrara; por qué la contraseña se guarda hasheada y por qué la restricción vive
también en la BD; por qué el mismo recurso se sirve en dos formatos desde una
sola estructura neutra; por qué el default es XML; y qué garantiza y qué no
garantiza realmente la verificación del correo con Postfix.

## Verificación y cierre

- Verifica en proceso: `python3 -m py_compile`, el `test_client` de Flask con
  filas fabricadas, y una revisión a mano del SQL. No hay BD que consultar.
- Código, comentarios y documentación en español, con el estilo del repo:
  comentarios que explican el porqué, no el qué.
- Al terminar, dame los `curl` de los cinco endpoints en sus dos formatos, y
  dime explícitamente **qué no pudiste comprobar**.
