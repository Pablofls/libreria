# Reflexión: monolito vs. microservicios bajo carga

Pruebas del 2026-11-07, de 1 a 20 usuarios, desde el Mac contra la VM. Datos en
`RESULTADOS.md`; gráficas en cada `<perfil>/` y en `comparativa_p95.png`.

**1. Diferencias.** En el listado de libros, el monolito (`/library/libros`) fue el
más lento: en el perfil load tuvo un p50 de 140 ms y un p95 de 220 ms, frente a 90 y
170 ms de `/books` y 43 y 120 ms de `/orders/books`. El orden se repite en todos los
perfiles de carga. El monolito devuelve menos bytes (25 KB de HTML contra 38 KB de
JSON) y aun así tarda más, así que el costo está en el servidor (consulta y render de
EJS). En cambio, `/library/autores/1` (p50 de 43–48 ms) tarda lo mismo que
`/authors` (41–44 ms). La diferencia depende de cuánto trabaja cada ruta, no de que
sea un monolito. Las rutas pequeñas rondan los 42 ms de mediana: es el piso de red.

**2. Primera degradación.** Ninguna ruta cruzó el umbral. La que más se acercó de
forma sostenida fue `/library/libros`, con el p95 más alto (o empatado) en todos los
perfiles de carga (210–240 ms). Los picos mayores fueron aislados: 860 ms en
`[login] /health`, 650 ms en `/users/[id]`. Con 2 a 6 muestras por ventana, una sola
petición lenta se convierte en el p95, y ninguno se repitió.

**3. Perfiles.**
- **Load:** plano (4.6 RPS, p95 de 160 ms).
- **Stress:** el RPS subió en escalones de 1.9 a 17.8 con el p50 fijo en 44–47 ms,
  la firma de un sistema no saturado.
- **Spike:** subió de ~2 a ~15 RPS y volvió en ~13 s, con el p50 de 44 a 54 ms.
- **Soak:** 4 min estables.
- **Quiebre:** 20 usuarios y 18.2 RPS sin incumplir el umbral, así que no hubo punto
  de quiebre.

Cada perfil mide algo distinto (estabilidad, escalabilidad, elasticidad, deriva y
límite), pero en este rango todos coinciden.

**4. Limitaciones.**
- La carga máxima (~18 RPS) la puso el generador, no la VM.
- Cada medida incluye unos 40 ms de internet. En la 1.ª corrida del spike, 3
  peticiones no tuvieron respuesta mientras Locust estuvo detenido 13 s.
- El monolito va por HTTP y la API por HTTPS. Las rutas son equivalentes, no
  idénticas, y `/books` tiene caché Redis.
- Los datos son pequeños (34 libros), el soak duró 4 min y no se midió la CPU de la
  VM, que es compartida.

**5. Uso de IA.**
- **Sugerencia útil:** un solo usuario virtual que rota por los destinos. Con una
  clase por servicio, el smoke de 1 usuario habría probado un único sistema.
- **Lo que hubo que corregir:**
  - La IA supuso que la cookie de login se llamaba `session` (es `libreria_sesion`),
    y el primer smoke trajo 14 rutas en vez de 15. Se detectó contando las filas.
  - `ejecutar.sh` cortaba la cadena de perfiles ante un solo fallo.
  - Los errores sólo decían "HTTP 0", sin la excepción real.
  - Las direcciones del enunciado no coinciden con la VM; se verificaron en
    `deploy/`.
- **Lo que aprendí por mi cuenta:** Antes de esta práctica pensaba que si una ruta
  respondía en el navegador, el sistema “funcionaba”. Locust me enseñó que funcionar
  con un usuario no dice nada de cómo se comporta con veinte: hay que medirlo, no
  suponerlo. Mis hipótesis fallaron dos veces. Esperaba que el sistema se degradara
  entre 12 y 20 usuarios y no pasó. Esperaba que `/books` fuera más rápido que
  `/orders/books` por la caché y fue al revés, porque devuelve diez veces más datos.
  Sin la prueba habría defendido ideas falsas.

**6. Qué cambiaría.**
- **En la prueba:** generar la carga desde otra VM de la misma región, subir de 20
  usuarios hasta saturar, registrar CPU y memoria de la VM, y medir el monolito
  también detrás de TLS.
- **En la arquitectura:** paginar o cachear `/library/libros`, como ya hace `/books`.
  No propongo réplicas porque nada indica que hagan falta.

**7. Gráficas.**
- **`<perfil>_carga.png`:** usuarios, RPS y fallos/s, y el % de errores por ventana
  de 10 s frente al 5 %.
  - En `stress`, el RPS dibuja la misma escalera que los usuarios y los fallos se
    quedan en cero: se atiende todo lo que se pide.
  - En `spike`, el RPS sube y baja con el pico.
  - En `spike_1` se ve el hueco con el RPS en 0 y un 100 % de errores en una ventana
    con sólo 3 peticiones.
- **`<perfil>_p95.png`:** el p95 por ruta de negocio (el monolito en línea
  discontinua) se mueve entre 40 y 300 ms, lejos de los 1000 ms. Los rectángulos
  altos de ~10 s son una sola petición lenta que permanece en la ventana.
- **`<perfil>_salud.png`:** `/health` responde en ~40 ms con picos sueltos.
- **`comparativa_p95.png`:** las barras casi no cambian entre perfiles (la carga no
  movió la latencia), pero sí entre rutas (`/library/libros` y `/books` arriba). Las
  del smoke tienen 1 o 2 muestras y no son comparables.
