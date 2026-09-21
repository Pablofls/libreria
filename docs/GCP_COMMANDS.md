# Infraestructura en GCP — comandos

Comandos de aprovisionamiento y configuración de la VM y de PostgreSQL.

> **Ninguna llave privada, token, contraseña ni cadena de conexión se escribe en
> este archivo.** Donde va un secreto, el comando lo pide de forma interactiva o
> se indica el nombre de la variable y nada más.

Sustituye los valores entre `<…>` por los de tu proyecto antes de ejecutar.

---

## 1. Variables del entorno de trabajo

```bash
export PROYECTO="<id-de-tu-proyecto>"
export ZONA="us-central1-a"
export REGION="us-central1"
export VM="libreria-vm"

gcloud config set project "$PROYECTO"
gcloud config set compute/zone "$ZONA"
```

**Por qué `us-central1`.** Es la región más barata de Compute Engine y la latencia
desde Monterrey es de unas decenas de milisegundos, irrelevante para una
aplicación de gestión con un puñado de usuarios. Una región mexicana o
`northamerica-northeast` reduciría la latencia sin ningún beneficio perceptible y
a mayor costo.

---

## 2. Crear la instancia de Compute Engine

```bash
gcloud compute instances create "$VM" \
  --zone="$ZONA" \
  --machine-type=e2-small \
  --image-family=centos-stream-10 \
  --image-project=centos-cloud \
  --boot-disk-size=20GB \
  --boot-disk-type=pd-balanced \
  --tags=http-server,https-server \
  --metadata=enable-oslogin=TRUE \
  --scopes=default \
  --description="Libreria Online - Integracion de Aplicaciones Computacionales"
```

### Justificación del dimensionamiento

| Parámetro | Valor | Por qué |
|---|---|---|
| `machine-type` | `e2-small` (2 vCPU compartidas, 2 GB) | La aplicación y PostgreSQL conviven en la misma máquina. 2 GB alcanzan holgadamente para un catálogo de decenas de libros: Node ronda los 80 MB y PostgreSQL con `shared_buffers` por omisión, unos 200 MB. `e2-micro` (1 GB) serviría, pero deja demasiado poco margen para que bcrypt y PostgreSQL coincidan bajo carga. Escalar es cambiar el tipo de máquina y reiniciar |
| `image-family` | `centos-stream-10` | Lo pide el enunciado. La familia, y no una imagen concreta, para tomar siempre la más reciente |
| `boot-disk-size` | 20 GB | 10 GB del sistema + margen para las imágenes subidas y los logs. `pd-balanced` porque `pd-standard` (disco magnético) hace notablemente lento el arranque de PostgreSQL |
| `enable-oslogin` | TRUE | Gestiona el acceso SSH con identidades de IAM en vez de llaves sueltas en metadatos. Revocar el acceso de alguien es quitarle el rol, no editar un archivo `authorized_keys` |
| `scopes` | `default` | Sin permisos extra sobre otras APIs de GCP. La VM no necesita hablar con ningún otro servicio |

**Alternativa considerada y descartada:** Cloud SQL para PostgreSQL, en vez de
instalarlo en la propia VM. Da respaldos automáticos y alta disponibilidad, pero
el enunciado pide instalar y configurar PostgreSQL a mano, y además el costo
mensual supera al de la instancia entera. Queda anotado como la primera mejora si
esto pasara a producción real.

---

## 3. Reglas de firewall

```bash
# HTTP hacia el reverse proxy. Es lo ÚNICO que se abre a internet.
gcloud compute firewall-rules create libreria-permitir-http \
  --direction=INGRESS --action=ALLOW --rules=tcp:80 \
  --target-tags=http-server --source-ranges=0.0.0.0/0 \
  --description="HTTP hacia Apache/NGINX"

# HTTPS, para cuando haya certificado.
gcloud compute firewall-rules create libreria-permitir-https \
  --direction=INGRESS --action=ALLOW --rules=tcp:443 \
  --target-tags=https-server --source-ranges=0.0.0.0/0 \
  --description="HTTPS hacia Apache/NGINX"

# Microservicios. La segunda y última excepción: el cliente Electron corre en
# la máquina del usuario, fuera de la VM, y consume el XML directo; y el
# microservicio de autenticación se prueba desde fuera con curl y Postman.
#   5000 -> autenticación (apps/services/login)
#   5002 -> catálogo XML/JSON (apps/services/catalogo)
# El 5001 del módulo SOAP NO se abre: va por túnel SSH.
gcloud compute firewall-rules create libreria-permitir-microservicios \
  --direction=INGRESS --action=ALLOW --rules=tcp:5000,tcp:5002 \
  --target-tags=http-server --source-ranges=0.0.0.0/0 \
  --description="Microservicios de autenticacion y catalogo"
```

**Una regla por etiqueta sólo sirve si la VM lleva esa etiqueta.** Si no la
tiene, la regla se crea sin error y no abre nada. Compruébalo antes:

```bash
gcloud compute instances describe maquina01 --zone northamerica-south1-c \
  --format="value(tags.items.list())"
```

**Y abrir en GCP no basta:** dentro de la VM está `firewalld`, que bloquea por su
cuenta. El síntoma de olvidarlo es un `curl` que se queda colgado sin responder
(si diera *connection refused*, el problema sería otro: el servicio no corre, o
escucha sólo en loopback).

```bash
sudo firewall-cmd --add-port=5000/tcp --add-port=5002/tcp --permanent
sudo firewall-cmd --reload && sudo firewall-cmd --list-ports
```

El 5002 queda abierto a `0.0.0.0/0`, y hay que asumir lo que implica: el
catálogo expone `/books/insert`, `/books/update` y `/books/delete` corriendo con
el rol `libreria_app`, que sí escribe. Lo único que separa esas rutas de
cualquiera que alcance el puerto es `API_TOKEN`, vacío por omisión. Defínelo en
`apps/services/catalogo/.env` antes de dejar la regla abierta, o estrecha la regla a una
sola IP:

```bash
gcloud compute firewall-rules update libreria-permitir-catalogo \
  --source-ranges=TU_IP/32
```

### Puertos que NO se abren, y por qué

| Puerto | Servicio | Decisión |
|---|---|---|
| 3000 | Node.js | **Debería estar cerrado.** Node escucha en `127.0.0.1`, así que ni abriéndolo se llegaría; se mantendría cerrado igualmente, por tener dos capas. Ver la nota de abajo: hoy no lo está |
| 5001 | Módulo SOAP | **Cerrado.** `RegistrarClasificacion` escribe en la base, así que no se publica: los clientes Java y Python llegan por un túnel SSH (`gcloud compute ssh maquina01 -- -N -L 5001:127.0.0.1:5001`) |
| 5432 | PostgreSQL | **Cerrado.** La base sólo acepta conexiones locales. Exponerla a internet sería el error de configuración más caro posible en este proyecto |
| 25 | Postfix | **Cerrado, y además imposible de abrir hacia fuera.** De entrada no se abre porque un Postfix alcanzable desde internet es un relay abierto; escucha sólo en loopback y sólo lo consulta el microservicio de autenticación. De salida lo bloquea la propia red de Google, aguas arriba del firewall: una regla de egress no lo levanta. Ver §7b |
| 22 | SSH | Se usa la regla por omisión de la VPC con IAP, o `gcloud compute ssh`, que no requiere abrir el puerto al mundo |

> **Discrepancia pendiente entre esta tabla y la realidad del proyecto.** Un
> listado de reglas muestra `allow-3000` abriendo `tcp:3000` a `0.0.0.0/0` sin
> etiqueta —y sin etiqueta aplica a TODAS las instancias de la red—, además de
> `permitir-8000-devoluciones` en el 8000 y `default-allow-rdp` en el 3389, que
> es un puerto de Windows y esta VM es CentOS. Ninguna de las tres debería
> existir. Revisar con:
>
> ```bash
> gcloud compute firewall-rules list --format="table(name,allowed[].map().firewall_rule().list(),sourceRanges.list(),targetTags.list())"
> ```

```bash
# Comprobar qué quedó realmente abierto:
gcloud compute firewall-rules list \
  --format="table(name,direction,allowed[].map().firewall_rule().list(),sourceRanges.list(),targetTags.list())"
```

---

## 4. Conectarse

```bash
gcloud compute ssh "$VM" --zone="$ZONA"
```

Con OS Login no hay que gestionar llaves manualmente: `gcloud` genera y rota la
suya. **No se sube ninguna llave privada al repositorio ni a la página de
evidencias.**

---

## 5. Instalar el software base (dentro de la VM)

```bash
sudo dnf -y update
sudo dnf -y install git nginx postgresql-server postgresql-contrib

# Node.js 20 LTS desde el repositorio de NodeSource
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo dnf -y install nodejs

node --version && npm --version && psql --version
```

---

## 6. Inicializar y arrancar PostgreSQL

```bash
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql
sudo systemctl status postgresql --no-pager
```

### Restringir a conexiones locales

```bash
sudo -u postgres psql -c "SHOW config_file;"       # ruta de postgresql.conf
```

En `postgresql.conf`, confirmar que la escucha es sólo local:

```
listen_addresses = 'localhost'
```

En `pg_hba.conf`, la aplicación se conecta por TCP local con contraseña cifrada:

```
# TYPE  DATABASE      USER           ADDRESS         METHOD
local   all           postgres                       peer
host    libreria_db   libreria_app   127.0.0.1/32    scram-sha-256
host    libreria_db   libreria_owner 127.0.0.1/32    scram-sha-256
```

`scram-sha-256` y no `md5`: `md5` está obsoleto en PostgreSQL y su hash es
trivial de romper si alguien captura el tráfico o llega al archivo.

```bash
sudo systemctl reload postgresql
```

---

## 7. Crear la base de datos y cargar los scripts

Se ejecutan **en este orden**. Cada uno imprime un resultado de control.

```bash
cd /opt/udem/libreria

# 1. Base de datos y roles. Pide las contraseñas de forma interactiva:
#    no quedan en el archivo ni en el historial del shell.
sudo -u postgres psql -f db/00_create_database.sql

# 2. Esquema, datos y objetos de base de datos
psql -U libreria_owner -h 127.0.0.1 -d libreria_db -f db/01_schema.sql
psql -U libreria_owner -h 127.0.0.1 -d libreria_db -f db/02_seed_30_per_table.sql
psql -U libreria_owner -h 127.0.0.1 -d libreria_db -f db/03_all_quieries_before_stored_procedures.sql
psql -U libreria_owner -h 127.0.0.1 -d libreria_db -f db/04_stored_procedures.sql
psql -U libreria_owner -h 127.0.0.1 -d libreria_db -f db/05_triggers.sql
psql -U libreria_owner -h 127.0.0.1 -d libreria_db -f db/06_views.sql
```

Para que el historial del shell no guarde nada, exportar la contraseña así:

```bash
read -rs PGPASSWORD && export PGPASSWORD    # no se muestra al escribirla
# … ejecutar los psql …
unset PGPASSWORD
```

### Verificación posterior en psql

```sql
\c libreria_db

-- Tablas y su tamaño
\dt+

-- Conteo por tabla: deben ser 30 en las tablas base
SELECT 'usuarios' AS tabla, count(*) FROM usuarios
UNION ALL SELECT 'libros', count(*) FROM libros
UNION ALL SELECT 'autores', count(*) FROM autores
UNION ALL SELECT 'generos', count(*) FROM generos
UNION ALL SELECT 'categorias', count(*) FROM categorias
UNION ALL SELECT 'formatos', count(*) FROM formatos
UNION ALL SELECT 'conceptos', count(*) FROM conceptos
UNION ALL SELECT 'imagenes_libros', count(*) FROM imagenes_libros
UNION ALL SELECT 'libros_autores', count(*) FROM libros_autores
UNION ALL SELECT 'libros_generos', count(*) FROM libros_generos
UNION ALL SELECT 'libros_conceptos', count(*) FROM libros_conceptos
ORDER BY 1;

-- Procedimientos y funciones
\df public.*

-- Disparadores
SELECT c.relname AS tabla, t.tgname AS disparador
FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE NOT t.tgisinternal AND c.relnamespace = 'public'::regnamespace
ORDER BY 1, 2;

-- Vistas
\dv

-- Restricciones de una tabla concreta
\d libros
\d usuarios

-- Índices, incluidos los parciales que imponen las reglas de negocio
\di

-- Privilegios: libreria_app no debe tener ninguno de sistema
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles
WHERE rolname LIKE 'libreria%';
```

> Al capturar pantalla de estas salidas, **no incluyas** la columna
> `password_hash` de `usuarios` ni el contenido de `.env`.

---

## 7b. Postfix, para verificar que los correos existen

Lo usa el microservicio de autenticación: antes de dar de alta a alguien, le
pregunta a Postfix si la dirección existe. **Nunca envía correo**: abre el
diálogo SMTP, dice `RCPT TO`, lee el código y cuelga.

```bash
sudo dnf install -y postfix telnet
sudo systemctl enable --now postfix
systemctl is-active postfix && ss -lntp | grep ':25'
```

Debe escuchar **sólo en loopback** (`127.0.0.1:25` y `[::1]:25`), que es el
valor por omisión en CentOS. Ni se abre el 25 en el firewall ni se cambia
`inet_interfaces`: un Postfix alcanzable desde internet es un relay abierto.

### La configuración, y por qué cada línea

```bash
sudo postconf -e \
  'smtpd_recipient_restrictions = reject_unknown_recipient_domain, reject_unverified_recipient, permit_mynetworks, reject_unauth_destination' \
  'address_verify_map = lmdb:$data_directory/verify' \
  'address_verify_poll_count = 3' \
  'address_verify_poll_delay = 1s' \
  'smtp_connect_timeout = 5s' \
  'unverified_recipient_reject_code = 550' \
  'unknown_address_reject_code = 550' \
  'maximal_queue_lifetime = 1h' \
  'bounce_queue_lifetime = 1h'
sudo systemctl reload postfix
```

- **`reject_unverified_recipient` ANTES de `permit_mynetworks`.** Postfix evalúa
  en orden y se queda con la primera restricción que decide. Con
  `permit_mynetworks` primero, la sonda —que sale de `127.0.0.1`— quedaría
  permitida sin verificar nada y Postfix contestaría `250` a cualquier
  dirección, incluidas las inventadas. Es el error que hace que una
  verificación *parezca* funcionar sin verificar nada.
- **`unverified_recipient_reject_code = 550`.** Por omisión vale 450, incluso
  cuando la sonda **sí** determinó que el buzón no existe. Sin subirlo, el
  servicio no puede distinguir «no existe» de «no pude comprobarlo».
- **`unknown_address_reject_code = 550`.** Un dominio sin DNS es un hecho
  permanente. Los fallos transitorios de DNS siguen dando 4xx por otro camino
  (`unknown_address_tempfail_action`), así que esto no castiga un hipo de red.
- **`smtp_connect_timeout = 5s`.** Cada sonda a un dominio externo se queda
  colgada contra el puerto 25 bloqueado; con el valor por omisión serían 30 s.
- **`*_queue_lifetime = 1h`.** Cada sonda externa deja un mensaje que jamás
  podrá salir, y Postfix lo reintentaría 5 días. Esta VM no manda correo real.

### `myhostname`: sin esto, la verificación local no funciona

En una VM de GCP el nombre que Postfix se da a sí mismo **no** es el FQDN de la
instancia, sino `maquina01.localdomain`. Como `mydestination` vale
`$myhostname, localhost.$mydomain, localhost`, el dominio real de la VM
—`maquina01.<zona>.c.<proyecto>.internal`— queda fuera, y Postfix lo trata como
un servidor ajeno: intenta conectarse a sí mismo por su IP interna y se rechaza
solo, porque escucha únicamente en loopback:

```
Recipient address rejected: unverified address:
connect to maquina01.<zona>.c.<proyecto>.internal[10.224.0.2]:25: Connection refused
```

El síntoma es que **todo** devuelve 450 y parece que la verificación no sirve
para nada. Se arregla diciéndole su nombre verdadero:

```bash
sudo postconf -e "myhostname = $(hostname -f)"
sudo systemctl restart postfix
```

### Y vaciar la caché, o seguirás viendo el error viejo

Postfix guarda los resultados negativos **tres horas**
(`address_verify_negative_refresh_time`), así que después de arreglar la
configuración sigue sirviendo el 450 de antes sin volver a intentarlo. Hay que
borrar su caché —que él regenera solo; no es configuración ni correo—:

```bash
sudo systemctl stop postfix
sudo rm -f /var/lib/postfix/verify.lmdb /var/lib/postfix/verify.db
sudo systemctl start postfix
```

Con las dos cosas hechas, la sonda distingue de verdad los tres casos:

```
pablogcp26@maquina01.<zona>.c.<proyecto>.internal  -> 250  buzon local que existe
noexiste999@maquina01.<zona>.c.<proyecto>.internal -> 550  dominio propio, buzon inexistente
algo@gmail.com                                     -> 450  no verificable (puerto 25 bloqueado)
```

### Comprobarlo

```bash
python3 - <<'SONDA'
import smtplib
for addr in ['root@localhost', 'noexiste12345@localhost',
             'algo@gmail.com', 'algo@dominio-que-no-existe-12345.com']:
    s = smtplib.SMTP('127.0.0.1', 25, timeout=15)
    s.ehlo('libreria.local'); s.mail('verificador@localhost')
    print(f'{addr:45} -> {s.rcpt(addr)}')
    s.quit()
SONDA
```

Las tres respuestas que el servicio traduce a HTTP:

| Respuesta | Significado | Qué hace `/register` |
|---|---|---|
| `250` | El buzón existe | Registra, `verificado` |
| `550` | No existe el buzón o el dominio | **400** |
| `450` | No se pudo comprobar | Registra, `no_verificable` |

### GCP bloquea la salida por el puerto 25

Y no se puede abrir: el bloqueo está en la red de Google, aguas arriba del
firewall de la VM. Una regla de egress permitiendo `tcp:25` no lo levanta.
Compruébalo:

```bash
timeout 8 bash -c 'exec 3<>/dev/tcp/gmail-smtp-in.l.google.com/25 && head -1 <&3'
echo "salida: $?"      # 124 = timeout = bloqueado
```

Consecuencia real, y conviene decirla en vez de disimularla: **la sonda contra
dominios externos siempre devuelve 450**, con Postfix diciéndolo literalmente
(`Network is unreachable`), así que todo correo externo se registra como
`no_verificable`. Lo que sí se verifica de verdad, y se comprobó en la VM, son
las direcciones del dominio propio —250 si el buzón existe, 550 si no— y los
dominios sin DNS, que se rechazan con 550.

`telnet localhost 25` funciona igualmente —es loopback, no pasa por la red de
Google—, y es la prueba de que Postfix está levantado y acepta el diálogo. Son
dos capas distintas: sólo la de salida está cerrada.

La única forma de verificar buzones ajenos sería un relay SMTP autenticado por
el puerto 587 (SendGrid, Mailgun…). Sus credenciales irían al `.env` de la VM,
nunca al repositorio.
---

## 8. Desplegar la aplicación

La ruta de instalación es `/opt/udem/libreria`. Si despliegas en otra, ajústala
también en los tres archivos de `deploy/`, que la traen escrita.

```bash
sudo mkdir -p /opt/udem
cd /opt/udem
sudo git clone <URL-DEL-REPOSITORIO> libreria
sudo chown -R "$USER:$USER" /opt/udem/libreria

# El repositorio es un monorepo: el monolito Node vive en apps/web-monolito/
cd /opt/udem/libreria/apps/web-monolito
sudo npm ci --omit=dev

# Copiar las portadas de prueba al directorio de subidas
sudo mkdir -p uploads
sudo cp ../../db/seed_uploads/*.png uploads/

# .env: se crea a mano y NUNCA se versiona
sudo cp .env.example .env
sudo nano .env        # completar DB_PASSWORD y SESSION_SECRET

# Generar un SESSION_SECRET nuevo para esta VM:
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"

# Permisos: sólo el usuario de la aplicación puede leer el .env
sudo chmod 600 /opt/udem/libreria/apps/web-monolito/.env
sudo chmod 750 /opt/udem/libreria/apps/web-monolito/uploads

# Prueba local antes de publicar
node app.js
# En otra terminal:  curl -I http://127.0.0.1:3000/library/login
```

### Servicio de systemd

```bash
sudo cp deploy/libreria.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now libreria
sudo systemctl status libreria --no-pager
journalctl -u libreria -n 50 --no-pager
```

---

## 9. Reverse proxy

```bash
sudo cp deploy/nginx-library.conf /etc/nginx/conf.d/library.conf
sudo nginx -t                       # validar antes de recargar
sudo systemctl enable --now nginx
sudo systemctl reload nginx

# SELinux: sin esto, el proxy hacia Node falla con 503 sin explicar por qué
sudo setsebool -P httpd_can_network_connect 1

# Que NGINX pueda leer los archivos subidos
sudo chcon -R -t httpd_sys_content_t \
  /opt/udem/libreria/apps/web-monolito/uploads \
  /opt/udem/libreria/apps/web-monolito/public
```

Para Apache en lugar de NGINX, usar `deploy/apache-library.conf` y `httpd`.

---

## 10. Verificación del despliegue

```bash
# Dentro de la VM: prueba local
curl -I http://127.0.0.1:3000/library/login       # 200 desde Node
curl -I http://127.0.0.1/library/login            # 200 a través del proxy

# Desde fuera de la VM
IP=$(gcloud compute instances describe "$VM" --zone="$ZONA" \
     --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
echo "$IP"

curl -I "http://$IP/library/login"                # debe responder 200
curl -I --max-time 5 "http://$IP:3000/"           # debe FALLAR: Node no expuesto
curl -I --max-time 5 "http://$IP:5432/"           # debe FALLAR: PostgreSQL no expuesto
```

Las dos últimas son parte de la evidencia: demuestran que sólo el proxy está
publicado (MN-06 del plan de pruebas).

---

## 11. Operación

```bash
sudo systemctl restart libreria         # reiniciar la aplicación
journalctl -u libreria -f               # seguir los logs en vivo
journalctl -u libreria --since "1 hour ago" -p err

# Actualizar tras un git push
cd /opt/udem/libreria
git pull
cd apps/web-monolito && sudo npm ci --omit=dev
sudo systemctl restart libreria

# Respaldo de la base de datos
pg_dump -U libreria_owner -h 127.0.0.1 libreria_db \
  | gzip > "$HOME/libreria-$(date +%F).sql.gz"
```

---

## 12. Limpieza

```bash
gcloud compute instances delete "$VM" --zone="$ZONA"
gcloud compute firewall-rules delete libreria-permitir-http libreria-permitir-https
```

> Borrar la instancia elimina también el disco de arranque y con él las imágenes
> de `uploads/`. Respalda antes lo que necesites conservar.
