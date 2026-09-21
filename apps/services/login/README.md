# Microservicio de autenticación

Registro y sesión de usuarios de la Librería Online, en **Python + Flask +
Psycopg 3 + PostgreSQL**, sobre la misma base que el monolito. Responde en
**XML y en JSON** indistintamente.

| Método | Endpoint | Función |
|---|---|---|
| `POST` | `/register` | Registrar un nuevo usuario |
| `POST` | `/login` | Autenticar e iniciar sesión |
| `POST` | `/logout` | Cerrar la sesión |
| `GET` | `/session` | Consultar si existe una sesión autenticada |
| `GET` | `/health` | Estado del microservicio, de PostgreSQL y de Postfix |
| `GET` | `/docs` | Documentación Swagger (OpenAPI 3) |

**Es un servicio, no una aplicación web.** No sirve HTML, formularios ni
páginas de login: recibe datos y devuelve XML o JSON. Lo único que renderiza
una página es `/docs`.

## El formato

`?format=json` devuelve JSON; `?format=xml` —o **la ausencia del parámetro**—
devuelve XML. Cualquier otro valor es un 400 explicado. Aplica a los cinco
endpoints y también a los errores: un cliente que pide JSON nunca recibe un XML
de error.

Como respaldo secundario, si no viene `format` pero el `Accept` pide
`application/json`, se responde JSON. Un `Accept: */*` —lo que manda `curl`—
sigue recibiendo XML.

Internamente ninguna vista construye XML: arma una estructura neutra de dicts y
listas, y un único despachador elige serializador. Si cada formato se
construyera por su lado, al primer campo nuevo dejarían de coincidir y nadie se
enteraría hasta que un cliente se rompiera.

## El nombre no se guarda en `usuarios`

El alta pide **nombre, apellido paterno y apellido materno** por separado, y
así se guardan, en la tabla `personas`. `usuarios.persona_id` apunta allá.

`usuarios.nombre` sigue existiendo con el nombre completo porque **el monolito
Node la lee y la escribe**, y el monolito no se toca. No puede ser una columna
`GENERATED` justamente por eso: esas son de sólo lectura. La mantienen al día
los disparadores de [`db/05_triggers.sql`](../../../db/05_triggers.sql), en los
dos sentidos.

Este servicio escribe **sólo en `personas`** y deja que el disparador componga
el nombre plano. Si lo escribiera él también, habría dos fuentes para el mismo
dato y podrían discrepar.

## La contraseña

Nunca se almacena ni se registra en claro: sólo su hash **bcrypt**, con el
mismo coste que [`src/modules/auth/auth.model.js`](../../../src/modules/auth/auth.model.js),
así que una cuenta creada aquí puede iniciar sesión en el monolito y al revés.

No sirve el `generate_password_hash` de Werkzeug: produce pbkdf2, y la
restricción `ck_usuarios_hash_bcrypt` de la base rechaza cualquier hash que no
sea un bcrypt de 60 caracteres. La defensa está en la base de datos, no sólo en
el código.

Un correo desconocido, una contraseña incorrecta y una cuenta desactivada
devuelven **el mismo 401 con el mismo mensaje**, y siempre se gasta el tiempo de
una comparación bcrypt aunque la cuenta no exista. Distinguirlos sería más
amable y convertiría el endpoint en un comprobador de qué correos tienen cuenta.

## La verificación del correo contra Postfix

Tres capas, de la más barata a la más cara:

1. **Sintaxis**, en el servicio.
2. **El dominio existe** — lo resuelve Postfix (`reject_unknown_recipient_domain`).
3. **El buzón existe** — sonda `RCPT TO` contra Postfix en `127.0.0.1:25`.

La sonda **nunca envía un correo**: abre el diálogo SMTP, dice `MAIL FROM` y
`RCPT TO`, lee el código y cuelga. No llega a `DATA`.

Lo importante es cómo se interpreta la respuesta:

| Respuesta | Significado | Qué hace `/register` |
|---|---|---|
| `250` | El buzón existe | Registra, `estado=verificado` |
| `5xx` | No existe el buzón o el dominio | **400**, rechazo explicado |
| `4xx` | No se pudo comprobar | Registra, `estado=no_verificable` |
| Postfix caído | No se pudo comprobar | Registra, `estado=no_verificable` |

**Un 4xx no es un "no existe".** Convertir un "no sé" en un rechazo dejaría
fuera a usuarios legítimos cada vez que el otro extremo aplica greylisting,
tarda, o no se puede alcanzar.

### Dos ajustes de Postfix sin los cuales nada de esto funciona

En una VM de GCP, Postfix se llama a sí mismo `maquina01.localdomain`, no por el
FQDN de la instancia. Como `mydestination` vale `$myhostname, …`, el dominio
real de la VM queda fuera y Postfix lo trata como un servidor ajeno: se conecta
a su propia IP interna y se rechaza solo, porque escucha únicamente en loopback.
El síntoma es que **todo** devuelve 450 y parece que la verificación no sirve.
Y después de arreglarlo hay que vaciar la caché, porque los resultados negativos
se guardan tres horas. Los dos comandos están en
[`docs/GCP_COMMANDS.md`](../../../docs/GCP_COMMANDS.md) §7b.

### El límite real de esta instalación

**GCP bloquea la salida por el puerto 25 en las VMs**, y el bloqueo está en la
red de Google, aguas arriba del firewall: una regla de egress no lo levanta.
Así que la sonda contra dominios externos siempre devuelve 450 —Postfix lo dice
literalmente: `Network is unreachable`— y **todo correo externo se registra como
`no_verificable`**.

Lo que sí se verifica de verdad, comprobado en la VM:

| Dirección | Respuesta | `/register` |
|---|---|---|
| buzón que existe en el dominio de la VM | `250` | 201 `verificado` |
| buzón inexistente en el dominio de la VM | `550` | **400** |
| dominio sin DNS | `550` | **400** |
| cualquier dominio externo | `450` | 201 `no_verificable` |

Y aunque el 25 estuviera abierto, la verificación por SMTP tendría techo: un
dominio *catch-all* acepta cualquier dirección, así que un `250` tampoco
probaría que el buzón existe. Por eso el único resultado en el que se confía
para **rechazar** es el 5xx.

La configuración de Postfix que hace falta está en
[`docs/GCP_COMMANDS.md`](../../../docs/GCP_COMMANDS.md).

## La sesión

Cookie firmada del lado de Flask (`libreria_sesion`), `HttpOnly` y
`SameSite=Lax`. La `SECRET_KEY` sale del entorno y **el servicio no arranca sin
ella**: con un valor por omisión en un repositorio público, cualquiera podría
fabricarse una sesión.

`/session` no se limita a leer la cookie: vuelve a consultar la cuenta, porque
pudo borrarse o desactivarse después de que la cookie se firmara. La cookie dice
quién dijo ser, no quién sigue siendo.

## Levantarlo

```bash
cd apps/services/login
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && chmod 600 .env    # y rellenarlo
python3 app.py                            # -> http://127.0.0.1:5000/docs
```

En la VM va con gunicorn bajo systemd: ver
[`deploy/libreria-login.service`](../../../deploy/libreria-login.service).
**Puerto 5000**, el que pide el enunciado; lo ocupaba el microservicio de
catálogo, que se mudó al 5002.

## Pruebas

```bash
python3 pruebas.py
```

84 comprobaciones en proceso, con el `test_client` de Flask y dobles en lugar de
PostgreSQL y Postfix: el contrato de formato, los códigos de estado, que el hash
no se filtre en ninguna respuesta, la interpretación de cada código SMTP y que
Swagger documente los dos formatos en todas las operaciones. Lo que **no**
cubren es que la base conteste: eso sólo se puede comprobar en la VM.
