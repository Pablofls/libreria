# Reflexión: monolito vs. microservicios bajo carga

Datos de `RESULTADOS.md` y `tabla_resultados.md`; gráficas en cada `<perfil>/` y
`comparativa_p95.png`. Pruebas del 2026-11-07, de 1 a 20 usuarios, desde el Mac.

## 1. Diferencias entre el monolito y los microservicios

La diferencia más clara está en el **listado de libros**. En el perfil load,
`/library/libros` (monolito) tuvo un p50 de 140 ms y un p95 de 220 ms. `/books`
(catálogo) tuvo 90 y 170 ms, y `/orders/books` (pedidos), 43 y 120 ms. El mismo orden
se repite en los seis perfiles de carga (el smoke tiene 1 o 2 muestras por ruta). El monolito devuelve **menos** bytes (25 KB de HTML)
que el catálogo (38 KB de JSON) y aun así tarda más: el tiempo extra se va en el
servidor (consulta y render de EJS), no en la transferencia. En cambio,
`/library/autores/1` (p50 de 43–48 ms) tarda lo mismo que `/authors` (41–44 ms). Así
que la diferencia **no viene de que sea un monolito**, sino de cuánto trabaja cada
ruta. Las rutas pequeñas de los microservicios (`/users/[id]`, `/payments`,
`/session`) tienen un p50 de 40–45 ms: casi sólo la ida y vuelta por internet. Que la
mediana de casi todo esté en ~42 ms marca el **piso de red** de esta medición.

## 2. Primera ruta en mostrar degradación

**Ninguna cruzó el umbral.** La que más se acercó de forma sostenida fue
`[monolito] /library/libros`: en todos los perfiles de carga tuvo el p95 más alto o empatado
(210–240 ms; `comparativa_p95.png`), y en `stress_p95.png` la línea morada discontinua
va siempre por encima del resto. Hubo picos más altos pero aislados:
`[login] /health` (860 ms en el quiebre), `[users] /users/[id]` (650 ms en el soak) y
`[monolito] /library/autores/[id]` (510 ms en el stress). Con ~0.2–0.6 peticiones/s por
ruta, la ventana de 10 s tiene 2 a 6 muestras, así que una sola petición lenta se
convierte en el p95. No se repitieron, y por eso no los cuento como degradación.

## 3. Load, stress, spike, soak y quiebre

- **Load** (5 usuarios): 4.6 RPS y un p95 de 160 ms, plano.
- **Stress**: el RPS subió en escalones (1.9 → 4.3 → 8.6 → 12.9 → 17.8) mientras el p50
  se quedaba en 44–47 ms. Es la firma de un sistema **no saturado**: el throughput
  crece en proporción a los usuarios y la latencia no cambia.
- **Spike**: el salto a 15 usuarios se absorbió. El RPS pasó de ~2 a ~15 y volvió en
  unos 13 s, con el p50 medio de 44 a 54 ms.
- **Soak**: 4 min planos.
- **Quiebre**: llegó a 20 usuarios y 18.2 RPS sin incumplir el umbral.

Las cinco miden cosas distintas (estabilidad, escalabilidad, elasticidad, deriva en el
tiempo y límite), pero en este rango todas dan la misma respuesta.

## 4. Limitaciones

- **Carga baja:** 20 usuarios con ~1 s de pausa son ~18 RPS, muy por debajo de lo que
  aguanta la VM. El techo está en el **generador de carga**, no en el sistema.
- **Red:** cada medición incluye internet de ida y vuelta (~40 ms) y su variación. La
  1.ª corrida del spike tuvo 3 peticiones sin respuesta con el cliente detenido 13 s.
- **Transporte distinto:** el monolito va por HTTP y la API por HTTPS (con Apache y
  nginx en medio). Las rutas son equivalentes, no idénticas: HTML frente a JSON, y
  `/books` tiene caché Redis de 60 s.
- **Datos y duración:** 34 libros y un soak de 4 min no revelan efectos de tablas
  grandes ni fugas de memoria. La VM e2-small la comparten otros servicios y otro
  proyecto, y no se midió su CPU durante las pruebas.

## 5. Uso de IA

- **Sugerencia útil:** usar un solo tipo de usuario con rotación de destinos. Con una
  clase por servicio, el smoke de 1 usuario habría probado un único sistema.
- **Lo que hubo que corregir:**
  - El primer smoke trajo 14 rutas, no 15: la IA supuso que la cookie de login se
    llamaba `session` y en `apps/services/login/app.py` es `libreria_sesion`. Se
    detectó contando las filas del resumen.
  - El script cortaba la cadena de perfiles cuando Locust salía con código 1 por un
    solo fallo.
  - Los fallos sólo decían "HTTP 0", sin la excepción real.
  - Las direcciones del enunciado (`:3000`, `:5000–5005`) no coinciden con la VM. Se
    comprobaron en `deploy/nginx-api-tls.conf` y `deploy/apache-libreria.conf`.
- **Lo que aprendí por mi cuenta:** _(pendiente: lo escribe el alumno)._

## 6. Qué cambiaría

- **En la prueba:** generar carga **desde otra VM de la misma región** de GCP para
  quitar la red doméstica. Subir de 20 usuarios (o quitar la pausa) hasta ver la
  saturación de verdad, y registrar CPU y memoria de la VM (`vmstat`) durante la
  prueba para saber qué se agota primero. Medir el monolito también detrás de TLS
  para igualar las condiciones.
- **En la arquitectura:** `/library/libros` es la ruta más cara. Paginarla o cachear
  la consulta, como ya hace `/books` con Redis, es lo primero que la mejoraría. No
  propongo más réplicas: con estos datos no hay evidencia de que hagan falta.

## 7. Qué indican las gráficas

- **`<perfil>_carga.png`:** arriba, los usuarios (los escalones del perfil); en medio,
  el RPS total y los fallos por segundo; abajo, el % de errores en ventanas de 10 s
  frente a la línea del 5 %.
  - En `stress_carga.png` el RPS dibuja la misma escalera que los usuarios, con la
    línea de fallos en cero: el servidor responde a todo lo que se le pide.
  - En `spike_carga.png` el RPS sube a ~15 en unos 10 s (lo que tardan los usuarios en
    hacer su primera petición) y vuelve a ~2. En `spike_1_carga.png` se ve el hueco en
    el que el RPS cae a 0 tras el pico, y el error se dispara al 100 % porque la
    ventana tiene sólo 3 peticiones y fallan las 3.
- **`<perfil>_p95.png`:** p95 de cada ruta de negocio en ventanas de ~10 s (el monolito
  en línea discontinua), con el umbral de 1000 ms punteado arriba. Todas las líneas
  viven entre 40 y 300 ms. Los rectángulos altos y de unos 10 s (por ejemplo, 590 ms
  en `soak_p95.png`) son una sola petición lenta que permanece en la ventana hasta
  que sale de ella.
- **`<perfil>_salud.png`:** lo mismo para `/health`. Responden en ~40 ms con picos
  sueltos: la disponibilidad nunca estuvo en duda.
- **`comparativa_p95.png`:** el p95 de toda la ejecución por ruta y perfil. Las barras
  apenas cambian entre perfiles: la carga no movió la latencia. La diferencia está
  entre rutas (`/library/libros` y `/books` arriba, las rutas pequeñas abajo). Las
  barras bajas del smoke tienen 1 o 2 muestras y no son comparables.
