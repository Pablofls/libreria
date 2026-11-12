# Benchmark: proxy inverso, balanceador de carga y API gateway

Compara las herramientas más usadas para los tres papeles que hoy cumplen Apache y
nginx en la VM de la librería, las mide en las mismas condiciones y termina con
una recomendación concreta para este proyecto.

- Números completos (mediana de 3 repeticiones): [RESULTADOS.md](RESULTADOS.md)
- Datos crudos de k6 y salida de consola: [resultados/](resultados/) · [consola.txt](consola.txt)
- Reproducir: `bash docs/benchmark_proxy/ejecutar.sh` (Docker, unos 25 min)

Corrido el 2026-11-10 en un Mac M1 (8 núcleos) con Docker Desktop; **no** en la VM.

---

## 1. Los tres papeles y dónde están hoy en la librería

| Papel | Qué hace | En la librería hoy |
|---|---|---|
| **Proxy inverso** | Es la única cara pública: termina TLS, oculta los procesos internos, sirve estáticos, fija tiempos y tamaños | **Apache** (80/443, TLS, VirtualHost por IP) → **nginx** en loopback |
| **Balanceador de carga** | Reparte peticiones entre varias réplicas del mismo servicio, detecta las caídas y las saca del reparto | **No hay**: cada servicio es un proceso único con 2 workers de gunicorn; el "reparto" es interno de gunicorn |
| **API gateway** | Una sola entrada para muchas APIs: enrutamiento por ruta, autenticación (JWT), límite de peticiones, métricas | **nginx hecho a mano**: enruta `/login`, `/users`, `/orders`… a cada puerto y, sólo para `/soap`, valida el JWT con `auth_request` contra pedidos. El resto de los JWT los valida **cada servicio** (con revocación en Redis) |

Los tres papeles se solapan: nginx, HAProxy, Traefik y Envoy hacen los dos
primeros; nginx, Envoy y Kong pueden hacer el tercero.

---

## 2. Comparativa cualitativa

| | nginx 1.27 | HAProxy 3.0 | Traefik 3.2 | Envoy 1.32 | Apache 2.4 | Kong 3.8 |
|---|---|---|---|---|---|---|
| Lenguaje / modelo | C, eventos | C, eventos | Go | C++, eventos | C, hilos (event MPM) | nginx + Lua (OpenResty) |
| Papel natural | Proxy + web server | Balanceador L4/L7 | Proxy para contenedores | Proxy de *service mesh* | Web server + proxy | API gateway |
| Chequeo de salud activo | Sólo en NGINX Plus (pasivo en OSS) | Sí | Sí | Sí | Sí (`mod_proxy_hcheck`) | Sí |
| JWT nativo | No (Plus sí; OSS con `auth_request`/njs) | Sí desde 2.5 (convertidor `jwt_verify`) | No (plugin o `forwardAuth`) | **Sí** (`jwt_authn`) | No | **Sí** (plugin) |
| Límite de peticiones | Sí (`limit_req`) | Sí (stick tables) | Sí (middleware) | Sí (local / global) | Módulos de terceros | Sí (plugin) |
| WebSocket | Sí | Sí | Sí | Sí | Sí (`mod_proxy_wstunnel`) | Sí |
| Configuración | Archivo, recarga sin cortes | Archivo, recarga sin cortes | Archivo/Docker/K8s, **dinámica** | YAML verboso o xDS (API) | Archivo | Declarativa (DB-less) o Admin API |
| Observabilidad | Logs; `stub_status` | Página de estadísticas muy completa | Dashboard, Prometheus | Estadísticas muy detalladas, Prometheus | Logs, `mod_status` | Plugins (Prometheus…) |
| Curva de aprendizaje | Baja | Media | Baja | **Alta** | Baja | Media |
| Memoria en reposo (medida) | **5 MiB** | 10 MiB | 27 MiB | 22 MiB | 6 MiB | **118 MiB** |

---

## 3. Metodología

**Topología.** Todo en una red de Docker, con IPs fijas y núcleos asignados
(`cpuset`) para que nadie le robe CPU a nadie:

| Núcleos | Qué corre |
|---|---|
| 0–2 | k6, el generador de carga |
| 3 | La herramienta bajo prueba, **un solo núcleo** para todas (`worker_processes 1`, `nbthread 1`, `--concurrency 1`…) |
| 4, 5, 6 | Backends `b1`, `b2`, `b3`: `traefik/whoami`, un servidor Go mínimo que responde con su nombre de host |
| 7 | Validador de JWT en **Flask + PyJWT + gunicorn (2 workers × 8 hilos)**, el mismo stack que los servicios de la VM |

**Carga.** k6 con 50 usuarios concurrentes sin pausa durante 20 s (capacidad
máxima), precedidos de 3 s de calentamiento; 3 repeticiones por escenario, se
reporta la mediana. CPU y memoria se muestrean a media corrida con `docker stats`
(100 % = un núcleo). Logs de acceso apagados en todas las herramientas.

**Escenarios.**

1. **Proxy inverso** (1 backend): directo (línea base), nginx, HAProxy, Traefik,
   Envoy, Apache, **Apache → nginx** (la cadena real de la VM) y **nginx sin
   keepalive al backend** (así está escrito hoy `deploy/nginx-api-tls.conf`).
2. **Balanceador** (3 backends, round robin): nginx, HAProxy, Traefik, Envoy.
3. **Conmutación por error:** 30 s de carga; `b3` se mata a los 10 s y vuelve a
   los 20 s. Cada balanceador con reintentos y detección de caídas configurados.
4. **API gateway** (JWT HS256 + límite de peticiones): nginx + `auth_request`
   contra el validador Python (el patrón de `/soap`), el mismo con la respuesta del
   validador **cacheada 30 s**, Kong (plugins `jwt` y `rate-limiting`) y Envoy
   (`jwt_authn` y `local_ratelimit`).

**Seguridad antes que velocidad.** Antes de medir, `verificar.py` comprueba en
cada gateway: sin token → 401, token válido → 200, token expirado, firmado con otro
secreto y `alg=none` → 401, y que una ráfaga de 50 peticiones contra una ruta de
10 r/s recibe 429. **Los tres gateways pasaron los 18 casos.** El secreto JWT se
genera en cada corrida (`generar.py`) y vive sólo en `generado/`, que no se versiona.

---

## 4. Resultados

### 4.1 Proxy inverso

| Herramienta | RPS | p50 ms | p95 ms | p99 ms | CPU del proxy | CPU por cada 1 000 RPS |
|---|---:|---:|---:|---:|---:|---:|
| directo (sin proxy) | 6 831 | 5.28 | 22.0 | 54.7 | — | — |
| **nginx** | **7 251** | **5.24** | **20.1** | **44.6** | 27 % | **3.7 %** |
| HAProxy | 7 070 | 5.41 | 22.9 | 45.4 | 30 % | 4.2 % |
| Traefik | 5 965 | 6.04 | 26.4 | 58.5 | 52 % | 8.6 % |
| Envoy | 5 793 | 6.36 | 26.9 | 56.1 | 52 % | 9.0 % |
| Apache → nginx (VM) | 5 764 | 6.17 | 28.3 | 64.5 | 37 % + 21 % | 10.0 % |
| Apache | 4 883 | 6.30 | 37.0 | 95.7 | 40 % | 8.2 % |
| nginx **sin keepalive** (config actual) | **3 384** | **13.52** | 25.2 | 36.4 | 43 % | 12.7 % |

El cuello de botella aquí es el backend (b1 al 100 % de su núcleo), no el proxy:
ninguno pasó del 52 % de CPU. Por eso la columna que mejor compara las
herramientas es **la CPU por cada 1 000 RPS**. nginx y HAProxy cuestan menos de la
mitad que los demás y no agregan latencia medible. Que nginx y HAProxy den algo más
de RPS que la conexión directa no es un error: reutilizan sus conexiones al backend
mejor de lo que lo hace k6.

**Hallazgo principal:** sin `keepalive` al upstream, nginx abre una conexión TCP
nueva al backend en cada petición. Eso **reduce los RPS a la mitad y suma 8 ms al
p50**, y el costo lo paga el backend, que gasta CPU aceptando conexiones. Así
reenvía hoy `deploy/nginx-api-tls.conf` (`proxy_pass http://127.0.0.1:500x` sin
bloque `upstream`).

### 4.2 Balanceador

| Herramienta | RPS | p50 ms | p95 ms | p99 ms | Reparto b1/b2/b3 | CPU | Memoria |
|---|---:|---:|---:|---:|---|---:|---:|
| Envoy | 10 740 | 2.31 | 12.8 | 32.3 | 33.3 / 33.3 / 33.3 % | 66 % | 27 MiB |
| nginx | 10 573 | **1.07** | 17.3 | 40.5 | 33.3 / 33.3 / 33.3 % | 55 % | **8 MiB** |
| HAProxy | 9 721 | 1.42 | 18.3 | 38.4 | 33.3 / 33.3 / 33.3 % | 53 % | 13 MiB |
| Traefik | 9 074 | 4.33 | 12.9 | **23.2** | 33.3 / 33.3 / 33.3 % | **98 %** | 136 MiB |

Los cuatro reparten exactamente en tercios. Con tres backends, nginx, HAProxy y
Envoy quedan a menos de un 10 % entre sí. Traefik llegó al 98 % de su núcleo:
es el único que se saturó.

### 4.3 Conmutación por error (b3 cae 10 s y vuelve)

| Balanceador | Peticiones | Fallidas | % | ¿Recuperó a b3? |
|---|---:|---:|---:|---|
| **HAProxy** | 277 086 | **0** | 0.000 % | Sí (24.7 % del total) |
| **nginx** | 288 314 | **0** | 0.000 % | Sí (21.6 %) |
| Traefik | 252 394 | 54 | 0.021 % | Sí (21.8 %) |
| Envoy | 311 789 | 1 235 | 0.396 % | Sí (23.5 %) |

nginx (pasivo: `max_fails` + `proxy_next_upstream`) y HAProxy (chequeo activo +
`redispatch`) reintentaron en otro backend sin que el cliente lo notara. Los
errores de Envoy vienen de su *circuit breaker* por omisión, que sólo permite **3
reintentos simultáneos**: con 50 conexiones concurrentes, los reintentos de sobra
se responden con 503. Se corrige subiendo `circuit_breakers.thresholds.max_retries`.
Esto ilustra el costo de Envoy: es muy capaz, pero sus valores por omisión son
estrictos y hay que conocerlos.

### 4.4 API gateway (JWT + límite de peticiones)

| Gateway | RPS | p50 ms | p95 ms | p99 ms | CPU | Memoria |
|---|---:|---:|---:|---:|---:|---:|
| nginx + `auth_request` **cacheado 30 s** | 5 231 | 7.04 | 29.3 | 57.1 | 32 % (+ validador ≈ 0 %) | 8 MiB + 56 MiB |
| **Envoy** (`jwt_authn`) | 4 716 | 7.61 | 31.6 | 59.2 | 59 % | 27 MiB |
| Kong (plugin `jwt`) | 3 949 | 9.40 | 32.0 | 53.4 | **98 %** | **192 MiB** |
| nginx + `auth_request` → Python (patrón de `/soap`) | **1 560** | **29.96** | 46.4 | 74.3 | 54 % + **validador 101 %** | 12 MiB + 58 MiB |

- **Validar el JWT en el propio gateway** (Envoy, Kong) mantiene entre el 55 % y el
  65 % de los RPS de nginx como proxy sin autenticación. Envoy lo hace con menos CPU;
  Kong se satura antes (Lua) y usa 7 veces más memoria.
- **Delegar la validación a un servicio Python** (`auth_request`) cuesta un salto
  HTTP más por petición. El validador se satura (101 %) en unas 1 500 RPS, que es
  **el techo de todo el gateway**, con 30 ms de p50.
- **Cachear la respuesta del validador** recupera el rendimiento (5 231 RPS), pero
  un token revocado con `/logout` **seguiría valiendo hasta 30 s**. Eso contradice
  la política del proyecto de fallar cerrado ante una revocación.

---

## 5. Limitaciones

- **Es local, no la VM.** Mac M1 con Docker y HTTP sin TLS, contra un backend Go
  trivial. Los números absolutos no se trasladan a la VM; lo que vale es la
  **comparación entre herramientas** en igualdad de condiciones.
- En la VM, el tiempo del servicio Flask + PostgreSQL domina. Las pruebas de
  Locust dieron p50 de unos 45 ms desde el Mac
  ([locust_tests/evidencias/tabla_resultados.md](../../locust_tests/evidencias/tabla_resultados.md)),
  así que el ~1 ms que agrega un buen proxy es ruido. Lo que **sí** se nota es lo que
  multiplica el trabajo del backend: no reutilizar conexiones o agregar un salto
  Python por petición.
- Kong y Envoy validan firma, `exp` e `iss`, pero **no la revocación por `jti` en
  Redis**. Igualarlo requeriría un plugin propio (Kong) o `ext_authz` (Envoy), que
  vuelve a ser un salto hacia un servicio.
- Cada herramienta se configuró "razonablemente", no al máximo. Con otros ajustes
  (más núcleos, buffers, HTTP/2 al backend), el orden entre herramientas cercanas
  podría cambiar.

---

## 6. Recomendación para la librería

1. **Proxy inverso: mantener Apache → nginx.** Apache es obligatorio mientras
   comparta los puertos 80/443 con el otro proyecto de la VM, y nginx es la
   herramienta más barata medida (3.7 % de CPU por cada 1 000 RPS, 5 MiB). La
   cadena cuesta ~1 ms y ~16 % de capacidad frente a la conexión directa, imperceptible ante los ~45 ms del
   servicio.
2. **Mejora inmediata: keepalive de nginx hacia los servicios.** Pasar
   `deploy/nginx-api-tls.conf` a bloques `upstream { server 127.0.0.1:500x;
   keepalive 16; }` con `proxy_set_header Connection "";` (gunicorn con hilos
   mantiene viva la conexión). En la prueba duplicó los RPS y bajó 8 ms el p50.
   No cambia ninguna ruta ni la seguridad.
3. **Balanceador: no hace falta hoy.** Hay una sola VM y un proceso por servicio.
   Si algún servicio se replica (por ejemplo, el catálogo, que no guarda estado),
   **nginx `upstream`** basta: empató con los mejores en rendimiento y tuvo 0 errores
   al caer un backend. HAProxy es la alternativa si se quieren chequeos activos y su
   página de estadísticas. Traefik conviene sólo si se pasa a contenedores, porque
   descubre los servicios solo.
4. **API gateway: dejar la validación JWT en los servicios.** Es la única capa que
   consulta la revocación en Redis, y nginx ya cumple el papel de enrutador. El
   `auth_request` de `/soap` está bien así por su poco tráfico, pero **no conviene
   extenderlo** a rutas con mucha carga (techo de ~1 500 RPS en un núcleo) **ni
   cachearlo** (rompe la revocación inmediata). Si el curso pide un gateway dedicado:
   **Envoy** por rendimiento y memoria, o **Kong (DB-less)** por facilidad y
   ecosistema de plugins, a cambio de 120–190 MiB de RAM.

---

## 7. Archivos

| Archivo | Qué es |
|---|---|
| `ejecutar.sh` | Corre todo: genera el secreto, levanta el banco, verifica, mide, analiza y apaga |
| `docker-compose.yml` | Backends, herramientas, validador y k6, con núcleos e IPs fijos |
| `config/` | nginx, HAProxy, Traefik, Apache y las plantillas de Envoy y Kong |
| `auth/` | Validador JWT en Flask + gunicorn |
| `generar.py` · `verificar.py` | Secreto y tokens efímeros · pruebas de seguridad de los gateways |
| `k6/carga.js` | Escenario de carga; cuenta códigos de estado y reparto por backend |
| `analizar.py` | Genera `RESULTADOS.md` y `graficas/*.svg` |

Variables de `ejecutar.sh`: `REPS` (3), `DURACION` (20s), `VUS` (50),
`SOLO=rp|lb|gw|fo` (una sola parte) y `CONSERVAR=1` (no apaga los contenedores).
