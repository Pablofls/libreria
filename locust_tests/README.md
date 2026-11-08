# Pruebas de rendimiento con Locust: monolito vs. microservicios

| Archivo | Qué es |
|---|---|
| `locustfile.py` | Escenario y los seis perfiles de carga (la cabecera explica User, `@task`, `wait_time`, usuarios, spawn_rate, duración y umbral) |
| `ejecutar.sh` | Corre un perfil sin GUI y guarda CSV, HTML y consola en `evidencias/<perfil>/` |
| `graficas.py` | PNG por perfil, comparativa de p95 y `evidencias/tabla_resultados.md`, a partir de los CSV |
| `evidencias/RESULTADOS.md` | Una fila por perfil y destino, con hipótesis y conclusión |
| `evidencias/REFLEXION.md` | Reflexión de ~1 página |
| `evidencias/smoke_manual.txt` | Smoke manual con `curl` (salud de los seis servicios, `/authors` y el monolito) |
| `catalogo_escalonado.py` · `README_catalogo_escalonado.md` · `smoketestes_books.md` | Prueba anterior, sólo del catálogo (200+ usuarios). Se lanza con `locust -f catalogo_escalonado.py` |

## Qué se mide y por qué estas rutas

Antes de escribir código: se quiere comparar el **tiempo de respuesta (p95), el
throughput (RPS) y los errores** de operaciones de **lectura** equivalentes en el
monolito y en los microservicios, vistos desde un cliente externo (el Mac) contra
la IP pública de la VM. Ninguna ruta escribe datos.

| Comparación | Monolito | Microservicios |
|---|---|---|
| Listado de libros | `GET /library/libros` (EJS + PostgreSQL, sesión) | `GET /books?format=json` (catálogo, caché Redis 60 s) · `GET /orders/books` (pedidos, JWT, sin caché) |
| Autor | `GET /library/autores/1` (sesión) | `GET /authors` (público) |
| Propias del servicio | — | `GET /users/<mi id>` · `GET /payments` · `GET /session` (login: Redis + PostgreSQL) |
| Salud | `GET /library/login` (página pública) | `GET /health/<servicio>?format=json` en los seis |

Salud y negocio salen en filas separadas: un 200 de `/health` dice que el servicio
está arriba, no que sus operaciones funcionen.

## Direcciones: enunciado vs. nuestra VM

El enunciado supone que todo corre en `ip:3000` y `ip:5000…5005`, levantado con
`levanta_todo.ps1`. En nuestra VM los servicios corren con **systemd**, con otros
puertos, y hacia fuera sólo están abiertos el 80 y el 443 (Apache). No se movió
ningún puerto: Locust usa las entradas públicas que ya existen.

| Enunciado | Nuestro servicio (puerto interno) | Lo que usa Locust |
|---|---|---|
| monolito `:3000` | `apps/web-monolito` (3000) | `http://34.51.108.167/library` (Apache 80 → nginx 8009 → 3000) |
| login `:5000` | login (5000) | `https://34.51.108.167/session`, `/health/login` |
| books `:5001` | **catalogo (5002)**; el 5001 es el servicio SOAP | `/books`, `/health/catalogo` |
| pagos `:5002` | pagos (5006) | `/payments`, `/health/pagos` |
| pedidos `:5003` | pedidos (5005) | `/orders/books`, `/health/pedidos` |
| users `:5004` | users (5003) | `/users/<id>`, `/health/users` |
| autores `:5005` | authors (5004) | `/authors`, `/health/authors` |

Consecuencia que hay que declarar: el monolito va por **HTTP** y la API por
**HTTPS** (Apache termina TLS y añade un salto). Esa diferencia está dentro de los
tiempos medidos.

## 1. Comprobar que la VM está arriba (smoke manual)

Antes de generar carga, una petición a mano a cada sistema. En el Mac:

```bash
curl -s --cacert ~/libreria-api.crt "https://34.51.108.167/health/catalogo?format=json"
```

```bash
curl -s --cacert ~/libreria-api.crt -o /dev/null -w "%{http_code} %{time_total}\n" https://34.51.108.167/authors
```

```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}\n" http://34.51.108.167/library/login
```

Deben dar `"status": "ok"` y dos `200`. Si dan timeout, la VM está apagada o
Apache/nginx caídos: en la VM, `sudo systemctl status httpd nginx`.

## 2. Instalar Locust (una vez)

```bash
cd locust_tests
```

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install "locust==2.47.0" matplotlib
```

```bash
.venv/bin/locust --version
```

## 3. Credenciales (cuentas lector, nunca en archivos)

```bash
export LECTOR_EMAIL=cesar.villalobos@libreria.udem.mx
```

```bash
read -s "LECTOR_PASS?Contraseña del lector (servicios): "
```

```bash
export LECTOR_PASS
```

```bash
export MONO_EMAIL=ana.ruiz@libreria.udem.mx
```

```bash
read -s "MONO_PASS?Contraseña del lector (monolito): "
```

```bash
export MONO_PASS
```

Cada ejecución hace **un** login a cada sistema al empezar (fuera de las
estadísticas) y todos los usuarios virtuales comparten ese token y esa cookie.
Así no se mide bcrypt ni se dispara el limitador de intentos. Si falta una
variable, las rutas que la necesitan se omiten y la consola lo avisa.

## 4. Correr los perfiles

Uno por vez, en este orden; antes de cada uno, anotar la hipótesis en
`evidencias/RESULTADOS.md`.

```bash
bash ejecutar.sh smoke
```

Revisa que el resumen tenga **15 filas** (7 de salud + 8 de negocio) y 0 fallos.
Si algo falla aquí, no tiene sentido seguir con la carga.

```bash
bash ejecutar.sh load
```

```bash
bash ejecutar.sh stress
```

```bash
bash ejecutar.sh spike
```

```bash
bash ejecutar.sh soak
```

```bash
bash ejecutar.sh quiebre
```

Duración total ≈ 16 min (30 s + 2 + 3 + 2 + 4 + ≤4). Si el JWT de 20 min caducara
en medio, `/users`, `/orders` y `/payments` darían 401: cada ejecución pide uno nuevo.

| Perfil | Usuarios | spawn_rate | Duración | Qué busca |
|---|---|---|---|---|
| smoke | 1 | 1/s | 30 s | Que el escenario y las rutas respondan bien |
| load | 5 | 1/s | 2 min | Comportamiento con la carga esperada |
| stress | 2 → 5 → 10 → 15 → 20 (36 s c/u) | 2/s | 3 min | Degradación al pasar la carga esperada |
| spike | 2 → 15 → 2 (30 s / 30 s / 60 s) | 15/s | 2 min | Efecto de un pico súbito y recuperación |
| soak | 3 | 1/s | 4 min | Degradación sostenida (miniatura; uno real dura horas) |
| quiebre | +1 cada 12 s, máx 20 | 1/s | ≤ 4 min | Cuándo se incumple el umbral |

- **Pausa entre tareas:** `between(0.5, 1.5)` s → cada usuario ≈ 1 petición/s.
- **Umbral (el del enunciado):** degradado si p95 > 1 s o errores > 5 %.
- **Quiebre:** evalúa el agregado de los últimos ~10 s (con ≥ 20 peticiones); al
  incumplir, congela los usuarios 20 s y termina. Escribe el momento en
  `evidencias/quiebre/quiebre_punto.txt`. Ojo: como el agregado mezcla las 15
  rutas, basta con que una ruta lenta supere ~5 % de las peticiones para que el
  p95 agregado la refleje; la gráfica `quiebre_p95.png` dice cuál fue.
- Si el Mac se satura (CPU de Locust al 90 %+, aviso en consola), baja los usuarios
  y anótalo en RESULTADOS.

## 5. Gráficas y tabla

```bash
.venv/bin/python graficas.py
```

Deja en cada `evidencias/<perfil>/` los PNG `_carga`, `_p95` y `_salud`, y en
`evidencias/` `comparativa_p95.png` y `tabla_resultados.md` (los números de
RESULTADOS salen de ahí, copiados tal cual).

## Si algo sale mal

| Síntoma | Causa probable |
|---|---|
| Todo `ConnectionError` / timeout | VM apagada, o Apache/nginx caídos |
| `ERROR login servicios: HTTP 401` | Contraseña del lector mal escrita |
| `ERROR login servicios: HTTP 429` | Limitador de login: espera unos minutos |
| `[monolito] … HTTP 302 a /library/login` | La sesión del monolito no se abrió o expiró |
| `HTTP 503` en rutas con JWT | Redis caído: la revocación falla cerrada |
| `SSLError` | `CA_CERT` no apunta al `.crt` de la VM (`~/libreria-api.crt`) |
