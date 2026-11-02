# Prueba smoke del catálogo (books) con Locust

Prueba de carga escalonada del microservicio de catálogo
(`apps/services/catalogo/`, puerto 5002), lanzada desde el Mac contra la VM por
HTTPS (`https://34.51.108.167`, nginx → 5002), con la interfaz web de Locust.

| Archivo | Qué es |
|---|---|
| `locustfile.py` | Usuarios, endpoints y escalonado de la prueba |
| `smoketestes_books.md` | El enunciado original |

## Qué hace la prueba

Los endpoints salen del swagger del servicio (`/apispec.json`, visible en
`/docs` cuando se corre en local). Las rutas `/api/...` son alias de las mismas
funciones y nginx no las publica, así que se prueban las `/books`.

| Etapa | Usuarios nuevos | Endpoint | Total |
|---|---|---|---|
| 0 | 100 | `GET /books` (catálogo en **XML**) | 200 |
|   | 100 | `GET /books?format=json` (catálogo en **JSON**) | |
| 1 | +10 | `GET /books/search` (`q`, `titulo`, `formato`, precio, año, stock…) | 210 |
| 2 | +10 | `GET /books/summary?limite=` | 220 |
| 3 | +10 | `GET /concepts` y `GET /concepts?termino=` | 230 |
| 4 | +10 | `GET /books/<isbn>` (ISBN reales leídos del propio catálogo) | 240 |
| 5 | +10 | `GET /books/author/<id>` (ids 1–30 del seed; 404 cuenta como válido) | 250 |
| 6 | +10 | `GET /health/catalogo` | 260 |
| 7 | +10 | `POST /books/insert` → `PUT /books/update/<isbn>` → `DELETE /books/delete/<isbn>` — **sólo si das credenciales de admin** | 270 |
| final | — | se sostiene la carga completa una etapa más y la prueba se detiene sola | |

- Cada etapa dura **60 s** (`ETAPA_SEGUNDOS`). La prueba completa tarda
  **8 min** sin escritura y **9 min** con ella.
- Desde la etapa 1, cada endpoint se pide al azar en XML o en JSON; en las
  estadísticas aparecen por separado (`/books/search [xml]`, `… [json]`).
- Una petición falla si el código no es el esperado **o** si el `Content-Type`
  no corresponde al formato pedido.
- Cada usuario espera de 1 a 3 s entre peticiones.
- Las filas `(setup) …` son peticiones de preparación (leer ISBN, login), no
  parte de la medición.

## 1. Instalar Locust (una sola vez)

Desde la raíz del repo, en la terminal del Mac:

```bash
cd locus_tests
```

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install --upgrade pip
```

```bash
pip install "locust>=2.24"
```

```bash
locust --version
```

Probado con Locust 2.47. La carpeta `.venv/` no se versiona.

## 2. Comprobar que el certificado está en el Mac

La VM usa un certificado autofirmado. El locustfile lo busca en
`~/libreria-api.crt` (la copia que ya tienes de `gcloud compute scp`):

```bash
curl -s --cacert ~/libreria-api.crt "https://34.51.108.167/health/catalogo"
```

Debe responder un XML con `<status>ok</status>`. Si el archivo está en otra
ruta, pásala en `CA_CERT` (paso 3). Si no lo encuentra, Locust avisa al
arrancar con `CA_CERT: NO ENCONTRADO` y desactiva la verificación TLS.

## 3. Arrancar la GUI de Locust

### Sólo lectura (recomendado para la smoke)

```bash
locust
```

### Con la etapa de escritura (insert / update / delete)

Necesita una cuenta **admin**. La contraseña se escribe con `read -s` (zsh) y
nunca se pega en el chat ni se guarda en un archivo:

```bash
export ADMIN_EMAIL=admin@libreria.com
```

```bash
read -s "ADMIN_PASS?Contraseña del admin: "
```

```bash
export ADMIN_PASS
```

```bash
locust
```

Cada iteración crea un libro con ISBN `999-xxxxxxxxxx`, le cambia el stock y
lo borra: el catálogo queda igual que antes. Cada alta o baja invalida la caché
`books:*` de Redis, así que con escritura activa verás más `MISS` en `/books`.

### Usar la GUI

1. Abre **http://localhost:8089** en el navegador.
2. El host ya viene puesto (`https://34.51.108.167`). Como el locustfile define
   la forma de la carga (`Escalonado`), los campos de usuarios y spawn rate no
   se usan: pulsa **Start**.
3. Pestañas útiles:
   - **Statistics**: peticiones, fallos y percentiles por endpoint y formato.
   - **Charts**: RPS, tiempos de respuesta y número de usuarios; se ve el
     escalón de 200 → 210 → … cada minuto.
   - **Failures**: el motivo de cada fallo (`HTTP 503`, `Content-Type …`).
   - **Download Data**: CSV y **reporte HTML** para guardarlo como evidencia
     (por ejemplo en `docs/evidencias/`).
4. La prueba se detiene sola. Para detenerla antes, **Stop**. Para cerrar
   Locust, `Ctrl+C` en la terminal.

## Variables de entorno

Todas opcionales.

| Variable | Por defecto | Para qué |
|---|---|---|
| `HOST` | `https://34.51.108.167` | Base del catálogo |
| `CA_CERT` | `~/libreria-api.crt` | Certificado autofirmado de la VM |
| `HEALTH_PATH` | `/health/catalogo` | Usa `/health` si apuntas directo al 5002 |
| `ETAPA_SEGUNDOS` | `60` | Duración de cada etapa |
| `SPAWN_RATE` | `20` | Usuarios nuevos por segundo al subir de etapa |
| `AUTOR_MAX` | `30` | Mayor id de autor para `/books/author/<id>` |
| `ADMIN_EMAIL` / `ADMIN_PASS` | vacías | Activan la etapa de escritura |
| `LOGIN_URL` | igual que `HOST` | Dónde está `POST /login` |

Ejemplo, etapas de 30 s:

```bash
ETAPA_SEGUNDOS=30 locust
```

Contra el servicio corriendo en local (`python app.py` en
`apps/services/catalogo/`), sin TLS:

```bash
HOST=http://127.0.0.1:5002 HEALTH_PATH=/health locust
```

## Sin GUI (opcional)

Misma prueba, con el resumen en la terminal y el reporte HTML en un archivo:

```bash
locust --headless --html reporte_books.html
```

## Si algo sale mal

| Síntoma | Causa probable |
|---|---|
| `SSLError` / `CERTIFICATE_VERIFY_FAILED` | `CA_CERT` apunta a un archivo que no es el `.crt` de la VM |
| Todo en `ConnectionError` o timeout | nginx o Apache caídos en la VM, o `firewalld` sin 443 (ver `CLAUDE.md`) |
| `HTTP 503` en lecturas | PostgreSQL sin conexión (el catálogo sigue sirviendo si sólo cae Redis) |
| `HTTP 503` en insert/update/delete | Redis caído: la escritura falla cerrada |
| `/books/insert` en `HTTP 401` repetido | Credenciales de admin incorrectas, o `(setup) /login` falló |
| `HTTP 403` en insert | La cuenta no tiene rol admin |
| `(setup) /login` en `HTTP 429` | Limitador de intentos de login por contraseña mal escrita; espera unos minutos |
| `Too many open files` | Sube el límite de la terminal: `ulimit -n 10240` y vuelve a lanzar `locust` |
