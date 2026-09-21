# Microservicio de autenticación — evidencias

Microservicio Flask + Psycopg 3 + PostgreSQL en el puerto **5000** de la VM,
con `/register`, `/login`, `/logout`, `/session` y `/health`, respondiendo en
**XML y JSON** y verificando el correo contra **Postfix**.

Código: [`apps/services/login/`](../../apps/services/login/) ·
Migración: [`db/applied/20260921-separa-nombre-en-personas.sql`](../../db/applied/20260921-separa-nombre-en-personas.sql)

---

## Capturas

Numéralas al guardarlas (`01-…png`, `02-…png`). Sustituye `IP` por la IP
pública de la VM (`gcloud compute instances list`).

| # | Qué capturar | Dónde |
|---|---|---|
| 01 | `http://IP:5000/docs` — Swagger con los cinco endpoints | Navegador |
| 02 | En Swagger, `POST /register` desplegado: se ven los cinco campos y las dos respuestas, `application/xml` y `application/json` | Navegador |
| 03 | `http://IP:5000/health` — XML **sin** parámetro | Navegador |
| 04 | `http://IP:5000/health?format=json` — el mismo recurso en JSON | Navegador |
| 05 | `http://IP:5000/health?format=yaml` — 400 explicado, **servido en XML** | Navegador |
| 06 | Los tres `/register`: verificado, no_verificable y rechazado | Terminal |
| 07 | El ciclo de sesión: login malo, login bueno, `/session`, `/logout` | Terminal |
| 08 | La sonda a Postfix con sus tres respuestas (250 / 550 / 450) | Terminal |
| 09 | `systemctl status` de los cuatro servicios y `ss -lntp` con los puertos | Terminal |
| 10 | La consulta a la base: `usuarios.nombre` derivado junto a las tres columnas de `personas` | Terminal |
| 11 | El panel del monolito funcionando: alta y edición de un usuario | Navegador |

Los comandos de cada captura de terminal están abajo.

---

## Por qué se hizo así

### El nombre se separó porque era tres datos en una columna

`usuarios.nombre` guardaba nombre y apellidos juntos. Eso no es un detalle
estético: con un campo compuesto no se puede ordenar por apellido, ni buscar por
el materno, ni saber dónde termina el nombre de pila. Es 1FN aplicada a un
atributo que en realidad son tres, y el enunciado lo hace evidente al pedir los
tres por separado en el registro.

### Pero la columna vieja se conservó, y eso es lo interesante

El monolito Node lee y escribe `usuarios.nombre`, y el encargo era no tocarlo.
La tentación es hacerla `GENERATED` —una columna calculada por la base— y
olvidarse. **No se puede:** una columna generada es de sólo lectura, y el
monolito la escribe en cada alta y en cada edición. El primer usuario creado
desde el panel habría fallado.

La solución fue conservarla como copia derivada y sostener la coherencia con
disparadores en los dos sentidos: si el monolito escribe el nombre plano, un
trigger lo reparte en `personas`; si el microservicio escribe `personas`, otro
recompone el plano. Ambos comparan antes de escribir, así que el eco de uno en
el otro no escribe nada y la recursión se corta sola.

Es redundancia deliberada, que normalmente sería un defecto. Aquí es el precio
de migrar un esquema sin detener ni reescribir la aplicación que ya vive encima,
y lo que la hace aceptable es que **una sola cosa la mantiene**: nadie escribe
las dos representaciones a mano. El microservicio escribe sólo en `personas` y
deja que el disparador componga el resto; si escribiera ambas, habría dos
fuentes para el mismo dato y tarde o temprano discreparían.

El punto ciego, dicho sin adornos: repartir un nombre suelto en tres campos es
una heurística, no una función reversible. `"María de la Cruz"` se reparte mal.
Sólo se dispara cuando el cambio viene del monolito —la única fuente que no
distingue las partes—; cuando el dato entra por el microservicio, las tres
columnas son la verdad y no se adivina nada.

### La contraseña: la defensa está en la base, no sólo en el código

Se guarda como hash **bcrypt**, nunca en claro, y con el mismo coste que el
monolito, de modo que una cuenta creada en el microservicio puede iniciar sesión
en la aplicación web y al revés. No sirve el `generate_password_hash` de
Werkzeug, que es lo primero que uno encuentra: produce pbkdf2, y la restricción
`ck_usuarios_hash_bcrypt` de la base **rechaza** cualquier hash que no sea un
bcrypt de 60 caracteres. Esa restricción es la que convierte "no guardamos
contraseñas en claro" de una promesa del programador en algo que el motor hace
cumplir aunque el código se equivoque.

Correo desconocido, contraseña incorrecta y cuenta desactivada devuelven **el
mismo 401 con el mismo mensaje**, y siempre se gasta el tiempo de una
comparación bcrypt aunque la cuenta no exista. Distinguirlos sería más amable
para el usuario y convertiría el endpoint en un comprobador de qué correos
tienen cuenta aquí: quien quisiera saber si alguien está registrado sólo tendría
que mirar el mensaje, o incluso el tiempo de respuesta.

### La verificación del correo, y su techo

La sonda abre el diálogo SMTP contra el Postfix local, dice `RCPT TO`, lee el
código y cuelga. **Nunca llega a `DATA`**: no manda correo, sólo pregunta.

Lo que de verdad importa es cómo se interpreta la respuesta:

| Respuesta | Significa | Qué hace `/register` |
|---|---|---|
| `250` | El buzón existe | Registra, `verificado` |
| `5xx` | No existe el buzón o el dominio | **400**, rechazo explicado |
| `4xx` | No se pudo comprobar | Registra, `no_verificable` |

**Un 4xx no es un "no existe".** Convertir un "no sé" en un rechazo dejaría
fuera a usuarios legítimos cada vez que el otro extremo aplica greylisting,
tarda o no se puede alcanzar. Por omisión Postfix responde 450 incluso cuando la
sonda **sí** determinó que el buzón no existe, así que hubo que subir
`unverified_recipient_reject_code` a 550 para que el servicio pudiera distinguir
los dos casos. Sin eso, la verificación no rechaza nada.

Y el límite honesto: **GCP bloquea la salida por el puerto 25**, aguas arriba
del firewall de la VM, así que no se puede abrir. La sonda contra dominios
externos siempre devuelve 450 —Postfix lo dice literalmente: `Network is
unreachable`— y todo correo de Gmail o similar se registra como
`no_verificable`. Lo que sí se verifica de verdad son las direcciones del
dominio propio y los dominios sin DNS.

Aunque el 25 estuviera abierto, el método tendría techo: un dominio *catch-all*
acepta cualquier dirección, así que un `250` tampoco probaría que el buzón
existe. Por eso el único resultado en el que se confía para **rechazar** es el
5xx. Una verificación que dice "no puedo asegurarlo" es más útil que una que
miente.

### Dos formatos, una sola fuente

Ninguna vista construye XML. Arma una estructura neutra de diccionarios y listas
—la única fuente de verdad— y un despachador elige serializador según
`?format=`. Si cada formato se construyera por su lado, al primer campo nuevo
dejarían de coincidir y nadie se enteraría hasta que un cliente se rompiera.
Por eso los errores también pasan por ahí: un cliente que pide JSON recibe un
error en JSON, incluso el 404 de una ruta que no existe.

**El formato por omisión es XML** aunque JSON sea más cómodo, porque lo pide el
enunciado y porque el microservicio hermano ya lo hace así. Un cliente existente
que no manda `?format=` debe seguir recibiendo lo mismo que recibía ayer.

### Es un servicio, no una aplicación web

No sirve HTML, ni formularios, ni una página de login. Recibe datos y devuelve
XML o JSON. Lo único que renderiza una página es `/docs`, que es documentación.
La interfaz de usuario es problema de quien consuma el servicio.

---

## Comandos de las capturas de terminal

**06 — los tres caminos del registro**

```bash
B=http://127.0.0.1:5000; N=$RANDOM; F=$(hostname -f)
curl -s -X POST "$B/register" -d "nombre=Correo&apellido_paterno=Verificado&apellido_materno=Prueba&email=postmaster$N@$F&password=contrasena123"
curl -s -X POST "$B/register?format=json" -d "nombre=Sofia&apellido_paterno=Herrera&apellido_materno=Gomez&email=prueba.$N@gmail.com&password=contrasena123"
curl -s -X POST "$B/register?format=json" -d "nombre=X&apellido_paterno=Y&apellido_materno=Z&email=x$N@dominio-que-no-existe-12345.com&password=contrasena123"
```

**07 — el ciclo de sesión**

```bash
B=http://127.0.0.1:5000; J=/tmp/ck.$$; E=postmaster@$(hostname -f)
curl -s -X POST "$B/login?format=json" -d "email=$E&password=incorrecta"
curl -s -c $J -X POST "$B/login?format=json" -d "email=$E&password=contrasena123"
curl -s -b $J $B/session
curl -s -b $J -c $J -X POST "$B/logout?format=json"
curl -s -b $J "$B/session?format=json"; rm -f $J
```

**08 — la sonda a Postfix**

```bash
python3 - <<'PY'
import smtplib, socket
fqdn = socket.getfqdn()
for addr in [f'postmaster@{fqdn}', f'noexiste999@{fqdn}', 'algo@gmail.com']:
    s = smtplib.SMTP('127.0.0.1', 25, timeout=15)
    s.ehlo('libreria.local'); s.mail('verificador@localhost')
    print(f'{addr[:45]:45} -> {s.rcpt(addr)}')
    s.quit()
PY
```

**09 — los cuatro servicios y sus puertos**

```bash
systemctl is-active libreria libreria-login libreria-soap libreria-catalogo
ss -lntp | grep -E ':(3000|5000|5001|5002)\s'
```

**10 — las dos representaciones del nombre en la base**

```bash
psql -U libreria_user -d libreria_db -h 127.0.0.1 -c "SELECT u.id, u.email, u.nombre AS derivado, p.nombre, p.apellido_paterno, p.apellido_materno FROM usuarios u JOIN personas p ON p.id=u.persona_id ORDER BY u.id DESC LIMIT 5;"
```
