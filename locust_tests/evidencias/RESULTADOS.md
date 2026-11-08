# Resultados de las pruebas Locust

Ejecutadas el **2026-11-07** (20:35–20:59, hora local) desde el Mac del alumno
contra la IP pública de la VM de GCP. Todas las cifras salen de
`<perfil>/<perfil>_stats.csv` (las genera `graficas.py` en `tabla_resultados.md`,
que además trae las siete rutas de salud). No se redondeó ni se completó nada a mano.

## Condiciones (constantes en todos los perfiles)

- **Cliente:** Locust 2.47.0, un proceso, Mac → internet → `34.51.108.167`.
- **Destinos:** monolito por `http://IP/library` (Apache 80 → nginx → Node);
  microservicios por `https://IP/...` (Apache 443 con TLS → nginx → Flask).
- **Escenario:** 15 GET en rotación (8 de negocio + 7 de salud), igual en todos los perfiles; pausa `between(0.5, 1.5)` s.
- **Cuentas:** lector; un login por ejecución, fuera de las estadísticas.
- **Umbral:** degradado si **p95 > 1000 ms** o **errores > 5 %** (el del enunciado, sin cambios).

## Hipótesis (anotadas antes de ejecutar)

| Perfil | Hipótesis |
|---|---|
| smoke | 15 rutas con 200 y 0 % de errores; p95 dominado por la red (100–300 ms). |
| load | 5 usuarios es poca carga; p95 estable < 300 ms. `/books` más rápido que `/orders/books` por la caché Redis. |
| stress | El p95 sube a partir de 10–15 usuarios, primero en `/library/libros` y `/orders/books`. |
| spike | Salto del p95 en los 30 s a 15 usuarios y recuperación en 10–20 s al volver a 2. |
| soak | p95 plano durante 4 min. |
| quiebre | El umbral se incumple entre 12 y 20 usuarios. |

## Resumen por perfil

| Perfil | Usuarios | Duración real | Peticiones | RPS | p50 ms | p95 ms | Errores % | Umbral | ¿Hipótesis? | Conclusión |
|---|---|---|---|---|---|---|---|---|---|---|
| smoke | 1 | 30 s | 25 | 0.86 | 51 | 160 | 0.0 | cumple | sí | Las 15 rutas responden; escenario válido. (Primera corrida: 14 rutas, ver nota 1) |
| load | 5 | 121 s | 553 | 4.58 | 45 | 160 | 0.0 | cumple | sí | Estable. Pero `/books` (p95 170) fue **más lento** que `/orders/books` (p95 120): falla esa parte de la hipótesis |
| stress | 2→5→10→15→20 | 180 s | 1737 | 9.62 | 44 | 170 | 0.0 | cumple | **no** | No hubo degradación: el RPS creció con los usuarios (1.9 → 17.8) y el p50 se quedó en 44–47 ms |
| spike (1.ª) | 2→15→2 | 133 s | 593 | 4.47 | 45 | 180 | 0.5 | cumple | parcial | El pico se absorbió sin errores; 3 peticiones sin respuesta **después** del pico, con el cliente detenido 13 s (nota 2) |
| spike (2.ª) | 2→15→2 | 121 s | 606 | 5.03 | 42 | 150 | 0.0 | cumple | parcial | Sin errores; el RPS subió a ~15 y volvió a ~2 en ~13 s. El p95 no saltó (p50 medio de 44 ms a 54 ms en el pico) |
| soak | 3 | 240 s | 656 | 2.73 | 43 | 160 | 0.0 | cumple | sí | p95 plano; picos aislados de 1–2 peticiones (≤ 650 ms) que no se repiten |
| quiebre | 1→20 (+1 cada 12 s) | 241 s | 2352 | 9.77 | 43 | 160 | 0.0 | cumple | **no** | **No se encontró punto de quiebre**: con 20 usuarios (18.2 RPS) el p95 de ventana fue 144 ms (`quiebre/quiebre_punto.txt`) |

### Escalones del stress y del quiebre (medias de la ventana agregada, de `*_stats_history.csv`)

| Usuarios | RPS stress | p50 stress | p95 stress | RPS quiebre | p95 quiebre |
|---|---|---|---|---|---|
| 2 | 1.9 | 47 | 280 | 1.3 | 184 |
| 5 | 4.3 | 47 | 164 | 4.1 | 192 |
| 10 | 8.6 | 46 | 159 | 8.7 | 158 |
| 15 | 12.9 | 44 | 173 | 13.2 | 156 |
| 20 | 17.8 | 45 | 156 | 18.2 | 144 |

El p95 de 280 ms con 2 usuarios en el stress viene del arranque (primeras peticiones, conexiones TLS nuevas), no de la carga.

## Tabla por perfil y destino (rutas de negocio)

`p95 salud` es el p95 de `/health/<servicio>` (o `/library/login` en el monolito) en el mismo perfil.

| Perfil | Usuarios | Duración | Destino | Ruta de negocio | Peticiones | RPS | p50 ms | p95 ms | Errores % | p95 salud ms | Umbral | Hipótesis | Conclusión |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| smoke | 1 | 30 s | monolito | `/library/libros` | 1 | 0.03 | 120 | 120 | 0.0 | 82 | cumple | 15 rutas responden 200 | cumple, sin errores |
| smoke | 1 | 30 s | monolito | `/library/autores/[id]` | 1 | 0.03 | 100 | 100 | 0.0 | 82 | cumple | 15 rutas responden 200 | cumple, sin errores |
| smoke | 1 | 30 s | catalogo | `/books` | 2 | 0.07 | 160 | 160 | 0.0 | 47 | cumple | 15 rutas responden 200 | cumple, sin errores |
| smoke | 1 | 30 s | authors | `/authors` | 2 | 0.07 | 110 | 110 | 0.0 | 49 | cumple | 15 rutas responden 200 | cumple, sin errores |
| smoke | 1 | 30 s | users | `/users/[id]` | 2 | 0.07 | 59 | 59 | 0.0 | 46 | cumple | 15 rutas responden 200 | cumple, sin errores |
| smoke | 1 | 30 s | pedidos | `/orders/books` | 1 | 0.03 | 110 | 110 | 0.0 | 53 | cumple | 15 rutas responden 200 | cumple, sin errores |
| smoke | 1 | 30 s | pagos | `/payments` | 1 | 0.03 | 42 | 42 | 0.0 | 88 | cumple | 15 rutas responden 200 | cumple, sin errores |
| smoke | 1 | 30 s | login | `/session` | 1 | 0.03 | 43 | 43 | 0.0 | 230 | cumple | 15 rutas responden 200 | cumple, sin errores |
| **smoke** | 1 | 30 s | **total** | (15 rutas) | 25 | 0.86 | 51 | 160 | 0.0 | — | cumple | 15 rutas responden 200 | ver texto |
| load | 5 | 2 min | monolito | `/library/libros` | 35 | 0.29 | 140 | 220 | 0.0 | 180 | cumple | p95 estable < 300 ms | cumple; de las más lentas del perfil |
| load | 5 | 2 min | monolito | `/library/autores/[id]` | 35 | 0.29 | 48 | 140 | 0.0 | 180 | cumple | p95 estable < 300 ms | cumple, sin errores |
| load | 5 | 2 min | catalogo | `/books` | 38 | 0.31 | 90 | 170 | 0.0 | 120 | cumple | p95 estable < 300 ms | cumple, sin errores |
| load | 5 | 2 min | authors | `/authors` | 37 | 0.31 | 44 | 120 | 0.0 | 130 | cumple | p95 estable < 300 ms | cumple, sin errores |
| load | 5 | 2 min | users | `/users/[id]` | 37 | 0.31 | 42 | 87 | 0.0 | 110 | cumple | p95 estable < 300 ms | cumple, sin errores |
| load | 5 | 2 min | pedidos | `/orders/books` | 35 | 0.29 | 43 | 120 | 0.0 | 130 | cumple | p95 estable < 300 ms | cumple, sin errores |
| load | 5 | 2 min | pagos | `/payments` | 35 | 0.29 | 45 | 130 | 0.0 | 110 | cumple | p95 estable < 300 ms | cumple, sin errores |
| load | 5 | 2 min | login | `/session` | 35 | 0.29 | 42 | 130 | 0.0 | 130 | cumple | p95 estable < 300 ms | cumple, sin errores |
| **load** | 5 | 2 min | **total** | (15 rutas) | 553 | 4.58 | 45 | 160 | 0.0 | — | cumple | p95 estable < 300 ms | ver texto |
| stress | 2→20 | 3 min | monolito | `/library/libros` | 116 | 0.64 | 150 | 230 | 0.0 | 160 | cumple | p95 sube desde 10–15 usuarios | cumple; de las más lentas del perfil |
| stress | 2→20 | 3 min | monolito | `/library/autores/[id]` | 117 | 0.65 | 44 | 120 | 0.0 | 160 | cumple | p95 sube desde 10–15 usuarios | cumple, sin errores |
| stress | 2→20 | 3 min | catalogo | `/books` | 115 | 0.64 | 83 | 230 | 0.0 | 130 | cumple | p95 sube desde 10–15 usuarios | cumple; de las más lentas del perfil |
| stress | 2→20 | 3 min | authors | `/authors` | 115 | 0.64 | 42 | 120 | 0.0 | 130 | cumple | p95 sube desde 10–15 usuarios | cumple, sin errores |
| stress | 2→20 | 3 min | users | `/users/[id]` | 115 | 0.64 | 42 | 130 | 0.0 | 130 | cumple | p95 sube desde 10–15 usuarios | cumple, sin errores |
| stress | 2→20 | 3 min | pedidos | `/orders/books` | 115 | 0.64 | 42 | 130 | 0.0 | 120 | cumple | p95 sube desde 10–15 usuarios | cumple, sin errores |
| stress | 2→20 | 3 min | pagos | `/payments` | 116 | 0.64 | 44 | 130 | 0.0 | 130 | cumple | p95 sube desde 10–15 usuarios | cumple, sin errores |
| stress | 2→20 | 3 min | login | `/session` | 116 | 0.64 | 43 | 130 | 0.0 | 120 | cumple | p95 sube desde 10–15 usuarios | cumple, sin errores |
| **stress** | 2→20 | 3 min | **total** | (15 rutas) | 1737 | 9.62 | 44 | 170 | 0.0 | — | cumple | p95 sube desde 10–15 usuarios | ver texto |
| spike_1 | 2→15→2 | 2 min | monolito | `/library/libros` | 38 | 0.29 | 120 | 240 | 2.6 | 170 | cumple | salto en el pico y recuperación | 1 sin respuesta; cumple igual |
| spike_1 | 2→15→2 | 2 min | monolito | `/library/autores/[id]` | 39 | 0.29 | 43 | 130 | 0.0 | 170 | cumple | salto en el pico y recuperación | cumple, sin errores |
| spike_1 | 2→15→2 | 2 min | catalogo | `/books` | 40 | 0.30 | 110 | 210 | 0.0 | 230 | cumple | salto en el pico y recuperación | cumple; de las más lentas del perfil |
| spike_1 | 2→15→2 | 2 min | authors | `/authors` | 40 | 0.30 | 42 | 140 | 2.5 | 130 | cumple | salto en el pico y recuperación | 1 sin respuesta; cumple igual |
| spike_1 | 2→15→2 | 2 min | users | `/users/[id]` | 38 | 0.29 | 41 | 190 | 0.0 | 120 | cumple | salto en el pico y recuperación | cumple, sin errores |
| spike_1 | 2→15→2 | 2 min | pedidos | `/orders/books` | 39 | 0.29 | 45 | 230 | 0.0 | 160 | cumple | salto en el pico y recuperación | cumple; de las más lentas del perfil |
| spike_1 | 2→15→2 | 2 min | pagos | `/payments` | 40 | 0.30 | 45 | 140 | 0.0 | 200 | cumple | salto en el pico y recuperación | cumple, sin errores |
| spike_1 | 2→15→2 | 2 min | login | `/session` | 41 | 0.31 | 45 | 150 | 0.0 | 150 | cumple | salto en el pico y recuperación | cumple, sin errores |
| **spike_1** | 2→15→2 | 2 min | **total** | (15 rutas) | 593 | 4.47 | 45 | 180 | 0.5 | — | cumple | salto en el pico y recuperación | ver texto |
| spike | 2→15→2 | 2 min | monolito | `/library/libros` | 39 | 0.32 | 120 | 210 | 0.0 | 160 | cumple | salto en el pico y recuperación | cumple; de las más lentas del perfil |
| spike | 2→15→2 | 2 min | monolito | `/library/autores/[id]` | 40 | 0.33 | 44 | 140 | 0.0 | 160 | cumple | salto en el pico y recuperación | cumple, sin errores |
| spike | 2→15→2 | 2 min | catalogo | `/books` | 41 | 0.34 | 78 | 160 | 0.0 | 130 | cumple | salto en el pico y recuperación | cumple, sin errores |
| spike | 2→15→2 | 2 min | authors | `/authors` | 41 | 0.34 | 41 | 130 | 0.0 | 120 | cumple | salto en el pico y recuperación | cumple, sin errores |
| spike | 2→15→2 | 2 min | users | `/users/[id]` | 40 | 0.33 | 40 | 140 | 0.0 | 130 | cumple | salto en el pico y recuperación | cumple, sin errores |
| spike | 2→15→2 | 2 min | pedidos | `/orders/books` | 41 | 0.34 | 41 | 120 | 0.0 | 110 | cumple | salto en el pico y recuperación | cumple, sin errores |
| spike | 2→15→2 | 2 min | pagos | `/payments` | 40 | 0.33 | 41 | 130 | 0.0 | 130 | cumple | salto en el pico y recuperación | cumple, sin errores |
| spike | 2→15→2 | 2 min | login | `/session` | 40 | 0.33 | 40 | 130 | 0.0 | 140 | cumple | salto en el pico y recuperación | cumple, sin errores |
| **spike** | 2→15→2 | 2 min | **total** | (15 rutas) | 606 | 5.03 | 42 | 150 | 0.0 | — | cumple | salto en el pico y recuperación | ver texto |
| soak | 3 | 4 min | monolito | `/library/libros` | 43 | 0.18 | 130 | 210 | 0.0 | 160 | cumple | p95 plano | cumple; de las más lentas del perfil |
| soak | 3 | 4 min | monolito | `/library/autores/[id]` | 43 | 0.18 | 43 | 130 | 0.0 | 160 | cumple | p95 plano | cumple, sin errores |
| soak | 3 | 4 min | catalogo | `/books` | 44 | 0.18 | 110 | 180 | 0.0 | 120 | cumple | p95 plano | cumple, sin errores |
| soak | 3 | 4 min | authors | `/authors` | 44 | 0.18 | 42 | 120 | 0.0 | 110 | cumple | p95 plano | cumple, sin errores |
| soak | 3 | 4 min | users | `/users/[id]` | 43 | 0.18 | 42 | 130 | 0.0 | 130 | cumple | p95 plano | cumple, sin errores |
| soak | 3 | 4 min | pedidos | `/orders/books` | 43 | 0.18 | 42 | 110 | 0.0 | 110 | cumple | p95 plano | cumple, sin errores |
| soak | 3 | 4 min | pagos | `/payments` | 43 | 0.18 | 41 | 130 | 0.0 | 120 | cumple | p95 plano | cumple, sin errores |
| soak | 3 | 4 min | login | `/session` | 43 | 0.18 | 41 | 110 | 0.0 | 130 | cumple | p95 plano | cumple, sin errores |
| **soak** | 3 | 4 min | **total** | (15 rutas) | 656 | 2.73 | 43 | 160 | 0.0 | — | cumple | p95 plano | ver texto |
| quiebre | 1→20 | 4 min | monolito | `/library/libros` | 155 | 0.64 | 130 | 210 | 0.0 | 170 | cumple | quiebre entre 12 y 20 usuarios | cumple; de las más lentas del perfil |
| quiebre | 1→20 | 4 min | monolito | `/library/autores/[id]` | 155 | 0.64 | 43 | 120 | 0.0 | 170 | cumple | quiebre entre 12 y 20 usuarios | cumple, sin errores |
| quiebre | 1→20 | 4 min | catalogo | `/books` | 158 | 0.66 | 89 | 190 | 0.0 | 130 | cumple | quiebre entre 12 y 20 usuarios | cumple, sin errores |
| quiebre | 1→20 | 4 min | authors | `/authors` | 158 | 0.66 | 42 | 130 | 0.0 | 130 | cumple | quiebre entre 12 y 20 usuarios | cumple, sin errores |
| quiebre | 1→20 | 4 min | users | `/users/[id]` | 159 | 0.66 | 41 | 130 | 0.0 | 130 | cumple | quiebre entre 12 y 20 usuarios | cumple, sin errores |
| quiebre | 1→20 | 4 min | pedidos | `/orders/books` | 159 | 0.66 | 41 | 130 | 0.0 | 120 | cumple | quiebre entre 12 y 20 usuarios | cumple, sin errores |
| quiebre | 1→20 | 4 min | pagos | `/payments` | 157 | 0.65 | 42 | 120 | 0.0 | 130 | cumple | quiebre entre 12 y 20 usuarios | cumple, sin errores |
| quiebre | 1→20 | 4 min | login | `/session` | 155 | 0.64 | 41 | 130 | 0.0 | 130 | cumple | quiebre entre 12 y 20 usuarios | cumple, sin errores |
| **quiebre** | 1→20 | 4 min | **total** | (15 rutas) | 2352 | 9.77 | 43 | 160 | 0.0 | — | cumple | quiebre entre 12 y 20 usuarios | ver texto |

## Notas

1. **Smoke, primera corrida (descartada):** salieron 14 rutas, no 15. `[login] GET /session`
   se omitía porque el locustfile buscaba la cookie `session` y el servicio de login la
   llama `libreria_sesion`. Se corrigió y se repitió; la que vale es la de `smoke/`.
2. **Spike, primera corrida (`spike_1/`):** 3 peticiones sin respuesta (`[authors] /authors`,
   `[pagos] /health`, `[monolito] /library/libros`), todas en la fase de **vuelta a 2
   usuarios**, no en el pico. El historial tiene un hueco de 13 s sin datos y la prueba
   duró 133 s en vez de 120: el propio proceso de Locust estuvo detenido. En la ventana de
   10 s posterior el % de errores llegó al 100 % porque casi no hubo peticiones (3 de 3), y
   luego bajó a 0. Se atribuye al cliente o a la red, no a la VM, pero no se puede
   demostrar con estos datos (el mensaje sólo decía `HTTP 0`; desde entonces el locustfile
   registra la excepción). La segunda corrida (`spike/`) no repitió ningún error.
3. **Las cadenas de `&&` se cortaron** tras la 1.ª corrida del spike porque Locust sale con
   código 1 si hay algún fallo; soak y quiebre se corrieron después de corregir `ejecutar.sh`.

## Pruebas no completadas

Ninguna: los seis perfiles terminaron. Lo que **no** se obtuvo es un punto de quiebre: con
el máximo permitido (20 usuarios, 4 min) el umbral nunca se incumplió. Encontrarlo exigiría
más usuarios, y eso choca con el límite del enunciado y con el de un solo cliente.
