# Plan de pruebas

> **Rutas.** El repositorio es un monorepo. Las rutas de código del monolito
> que aparecen aquí (`app.js`, `src/`, `views/`, `middleware/`, `config/`,
> `services/`, `public/`, `uploads/`) son **relativas a `apps/web-monolito/`**.
> Lo compartido —`db/`, `deploy/`, `docs/`, `tests/`— sigue en la raíz.

Matriz de pruebas del sistema. Cada caso indica requisito relacionado,
precondición, entrada, pasos, resultado esperado, resultado observado, estado y
evidencia.

Las pruebas de aplicación (**PR-nn**) están automatizadas en
[`tests/pruebas.sh`](../tests/pruebas.sh) y no dependen de que alguien recuerde
repetirlas. Las de base de datos (**C-nn**) están en
[`db/03_all_quieries_before_stored_procedures.sql`](../db/03_all_quieries_before_stored_procedures.sql).

Una captura de pantalla sin explicación no es una prueba: cada evidencia dice qué
se ejecutó y qué se esperaba.

---

## Cómo reproducir

```bash
# 1. Base de datos: consultas y pruebas negativas de integridad
psql -U libreria_owner -d libreria_db -f db/03_all_quieries_before_stored_procedures.sql

# 2. Aplicación: la matriz PR-01 … PR-46
BASE_URL=http://127.0.0.1:3000/library \
ADMIN_EMAIL='admin@libreria.com'  ADMIN_PASS='…' \
LECTOR_EMAIL='ana.ruiz@libreria.udem.mx' LECTOR_PASS='…' \
bash tests/pruebas.sh
```

Las credenciales se pasan por variable de entorno; no están escritas en ningún
archivo del repositorio.

---

## Resultado de la última ejecución

| | |
|---|---|
| Fecha | 2026-08-30 |
| Pruebas de aplicación | **57 ejecutadas · 57 pasadas · 0 fallidas** |
| Pruebas negativas de base de datos | **7 ejecutadas · 7 pasadas · 0 fallidas** |
| Salida completa | [`docs/evidencias/pruebas_aplicacion.txt`](evidencias/pruebas_aplicacion.txt) · [`docs/evidencias/pruebas_integridad_sql.txt`](evidencias/pruebas_integridad_sql.txt) |

---

## A · Autenticación y sesión

| ID | RF/RNF | Precondición | Entrada | Pasos | Esperado | Observado | Estado |
|---|---|---|---|---|---|---|---|
| PR-01 | RF-02 | Sin sesión | — | `GET /libros` | 302 hacia `/login` | 302 | ✅ |
| PR-02 | RF-02 | Sin sesión | — | `GET /login` | 200 con el formulario | 200 | ✅ |
| PR-03 | RF-01 | Sin sesión | — | `GET /registro` | 200 con el formulario | 200 | ✅ |
| PR-04 | RNF-05 | Sin sesión | — | `GET /no-existe` | 404 sin datos técnicos | 404 | ✅ |
| PR-05 | RNF-01 | Sin sesión | POST sin `_csrf` | `POST /login` | 403 | 403 | ✅ |
| PR-06 | RF-02 | Token válido | Correo correcto, contraseña incorrecta | `POST /login` | 401, mensaje genérico | 401 | ✅ |
| PR-07 | RF-02 | Token válido | Correo inexistente | `POST /login` | 401 con **el mismo** mensaje que PR-06 | 401 | ✅ |
| PR-08 | RF-02 | Token válido | Credenciales del Administrador | `POST /login` | 302 hacia `/libros`, sesión creada | 302 | ✅ |
| PR-38 | RF-03 | Sesión activa | — | `GET /logout` | 302, sesión destruida | 302 | ✅ |
| PR-39 | RF-03 | Tras PR-38 | — | `GET /usuarios` | 302 hacia login | 302 | ✅ |

## B · Autorización por rol

| ID | RF/RNF | Precondición | Entrada | Pasos | Esperado | Observado | Estado |
|---|---|---|---|---|---|---|---|
| PR-09 | RF-11 | Sesión de admin | — | `GET` a `/panel`, `/usuarios`, `/autores`, `/generos`, `/categorias`, `/formatos`, `/conceptos`, `/libros/nuevo` | 200 en las 8 | 200 ×8 | ✅ |
| PR-10 | RF-02 | Token válido | Credenciales de lector | `POST /login` | 302 | 302 | ✅ |
| PR-11 | RF-05 | Sesión de lector | — | `GET /libros` | 200, rejilla de portadas | 200 | ✅ |
| PR-12 | RF-05 | Sesión de lector | — | `GET /libros/1` | 200, detalle | 200 | ✅ |
| PR-13 | RF-11 | Sesión de lector | — | `GET` a `/usuarios`, `/panel`, `/libros/nuevo`, `/autores`, `/generos` | **403** con página de acceso denegado, no redirect | 403 ×5 | ✅ |
| PR-14 | RF-11 | Sesión de lector | Token CSRF propio válido | `POST /libros/1/eliminar` | 403 y el libro intacto | 403, libro presente | ✅ |

> PR-14 es la prueba que importa: no basta con ocultar el botón. Se envía el POST
> directamente, con un token CSRF legítimo del lector, y aun así se rechaza —
> porque quien decide es `requireAdmin` en la ruta, no la vista.

## C · Búsqueda y parametrización

| ID | RF/RNF | Precondición | Entrada | Pasos | Esperado | Observado | Estado |
|---|---|---|---|---|---|---|---|
| PR-15 | RF-05 | Sesión | `q=978-607-32-2345-6` | `GET /libros?q=…` | Encuentra el libro por ISBN exacto | Encontrado | ✅ |
| PR-16 | RNF-01 | Sesión | `q=<script>alert(1)</script>` | `GET /libros?q=…` | Se muestra como `&lt;script&gt;` | Escapado | ✅ |
| PR-17 | RNF-01 | Sesión | igual que PR-16 | inspeccionar el HTML | **No** aparece `<script>alert` sin escapar | No aparece | ✅ |
| PR-18 | RNF-02 | Sesión | `q=' OR 1=1; DROP TABLE libros; --` | `GET /libros?q=…` | 200, cero coincidencias, sin error | 200 | ✅ |
| PR-19 | RNF-02 | Tras PR-18 | — | `GET /libros` | El catálogo sigue con sus 30 libros | 200, 30 libros | ✅ |

## D · CRUD y validación server-side

Todas se ejecutan con `curl`, **sin pasar por el navegador**, para comprobar que
la validación del formulario no es la que decide.

| ID | RF/RNF | Entrada | Esperado | Observado | Estado |
|---|---|---|---|---|---|
| PR-20 | RF-06, RF-07 | Libro válido con 2 autores y 1 género | 302; se crean 2 filas en `libros_autores` | 302, 2 filas | ✅ |
| PR-21 | RF-06 | ISBN ya existente | 400, mensaje de valor duplicado | 400 | ✅ |
| PR-22 | RF-07 | Libro sin ningún autor | 400 | 400 | ✅ |
| PR-23 | RF-06 | `precio = -10` | 400 | 400 | ✅ |
| PR-24 | RF-10 | `stock = -4` | 400 | 400 | ✅ |
| PR-25 | RF-06 | `isbn = no-es-un-isbn` | 400 | 400 | ✅ |
| PR-26 | RF-06 | `anio_publicacion = 99` | 400 | 400 | ✅ |
| PR-27 | RNF-02 | `categoria_id = 999999` | 400, rechazado por la clave foránea | 400 | ✅ |
| PR-30 | RNF-01 | Contraseña `abc` | 400, política de contraseñas | 400 | ✅ |
| PR-31 | RNF-03 | `email = esto-no-es-correo` | 400 | 400 | ✅ |

## E · Administrador único

| ID | RF/RNF | Precondición | Entrada | Esperado | Observado | Estado |
|---|---|---|---|---|---|---|
| PR-28 | RF-11 | Ya existe 1 admin | Alta de usuario con `rol=admin` | **409**, no se crea | 409 | ✅ |
| PR-29 | RF-11 | igual | igual | Mensaje «Ya existe un Administrador…» | Mensaje presente | ✅ |
| C-24 | RF-11 | igual | `INSERT` directo en psql con `rol='admin'` | Error `23505` desde la base de datos | `23505` | ✅ |

> PR-28 y C-24 comprueban la **misma** regla en dos capas distintas: por la
> interfaz y saltándose la aplicación por completo. Si sólo pasara la primera,
> la regla no estaría realmente garantizada.

## F · Subida de imágenes

| ID | RF/RNF | Entrada | Esperado | Observado | Estado |
|---|---|---|---|---|---|
| PR-40 | RNF-01 | PHP renombrado a `.png`, MIME `image/png` | 400 por firma binaria inválida | 400 | ✅ |
| PR-41 | RNF-01 | `.sh` con MIME `image/png` | 400 por extensión no permitida | 400 | ✅ |
| PR-42 | RNF-01 | PDF con `application/pdf` | 400 por tipo no permitido | 400 | ✅ |
| PR-43 | RNF-01 | Archivo de 3 MB | 400 por superar el límite de 2 MB | 400 | ✅ |
| PR-44 | RNF-10 | PNG válido sin texto alternativo | 400 | 400 | ✅ |
| PR-45 | RNF-01 | PNG válido sin token CSRF | 403 | 403 | ✅ |
| PR-46 | RF-09 | PNG válido con texto alternativo | 302, imagen registrada | 302 | ✅ |
| — | RF-09 | tras las 7 anteriores | `uploads/` crece **exactamente en 1** | +1 | ✅ |

> El conteo final es la prueba real: los seis intentos rechazados no dejaron
> ningún archivo en el disco de la VM.

## G · Cabeceras y cookies

| ID | RNF | Esperado | Observado | Estado |
|---|---|---|---|---|
| PR-32 | RNF-01 | `X-Content-Type-Options: nosniff` | Presente | ✅ |
| PR-33 | RNF-01 | `X-Frame-Options: DENY` | Presente | ✅ |
| PR-34 | RNF-01 | `Content-Security-Policy` presente | Presente | ✅ |
| PR-35 | RNF-01 | `X-Powered-By` **ausente** | Ausente | ✅ |
| PR-36 | RF-04 | Cookie con `HttpOnly` | Presente | ✅ |
| PR-37 | RF-04 | Cookie con `SameSite=Lax` | Presente | ✅ |

## H · Pruebas negativas de integridad en PostgreSQL

Cada bloque ejecuta una sentencia que **debe fallar** y captura el error real del
motor. La evidencia es el mensaje, no el éxito.

| ID | Sentencia | SQLSTATE esperado | Error observado | Estado |
|---|---|---|---|---|
| C-19 | `INSERT` de un libro con ISBN ya existente | `23505` | `duplicate key value violates unique constraint "uq_libros_isbn"` | ✅ |
| C-20 | `UPDATE libros SET stock = -5` | `23514` | `violates check constraint "ck_libros_stock"` | ✅ |
| C-21 | `UPDATE libros SET precio = -1` | `23514` | `violates check constraint "ck_libros_precio"` | ✅ |
| C-22 | `INSERT` en `libros_autores` con `autor_id = 999999` | `23503` | `violates foreign key constraint "fk_la_autor"` | ✅ |
| C-23 | `DELETE` de una categoría que tiene libros | `23503` | `violates foreign key constraint "fk_libros_categoria"` | ✅ |
| C-24 | `INSERT` de un segundo Administrador | `23505` | `Ya existe un Administrador. El sistema admite como maximo uno.` | ✅ |
| C-25 | `INSERT` de un usuario con contraseña sin hashear | `23514` | `violates check constraint "ck_usuarios_hash_bcrypt"` | ✅ |

Verificaciones adicionales ejecutadas en base de datos, con su resultado:

| Objeto | Prueba | Resultado |
|---|---|---|
| `sp_guardar_libro` | Alta con arreglo de 2 autores y 2 géneros | Libro creado con ambos vínculos en una transacción |
| `sp_guardar_libro` | Alta **sin** autores | `check_violation`: «Un libro debe tener al menos un autor» |
| `sp_guardar_concepto_libro` | Registrar «IaaS», que ya existe, en otro libro | Reutiliza el término; queda definido en 4 libros con textos distintos |
| `sp_ajustar_stock` | Restar más existencias de las que hay | `check_violation`; el stock no queda negativo |
| `trg_portada_unica` | Insertar una segunda imagen con `es_portada = true` | La portada anterior pasa a `false` automáticamente |
| `trg_conservar_admin` | Borrar al único Administrador | `restrict_violation`: «No se puede dejar el sistema sin Administrador» |
| `ck_imagenes_nombre` | Insertar `nombre_archivo = '../../etc/passwd'` | `check_violation` |

---

## I · Pruebas manuales (requieren navegador)

No están automatizadas porque verifican percepción visual o el despliegue
completo. Se documentan con captura **más** explicación.

| ID | RF/RNF | Pasos | Esperado | Evidencia |
|---|---|---|---|---|
| MN-01 | RF-08 | Entrar a `/conceptos/1` (IaaS) | Se listan las definiciones distintas que cada libro da al mismo término | captura + explicación |
| MN-02 | RF-08 | En un libro, agregar el concepto «Bucket» con una definición propia | El término se reutiliza del catálogo; la definición es del libro | captura |
| MN-03 | RF-09 | Subir dos imágenes y marcar la segunda como portada | La primera deja de ser portada sin intervención manual | captura antes/después |
| MN-04 | RF-13 | Entrar a `/panel` como Administrador | Conteos por tabla, inventario por categoría, libros incompletos | captura |
| MN-05 | RNF-08 | Abrir `http://IP_DEL_SERVIDOR/library` desde otro equipo | La aplicación responde bajo el prefijo; CSS, imágenes y formularios funcionan | ✅ Verificado desde fuera de la VM: `/library/login` y `/library/registro` → 200, `/library/` → 302, CSS → 200, `/` → 404. Las cabeceras `nosniff`, `X-Frame-Options`, CSP y `Referrer-Policy` llegan íntegras a través del proxy |
| MN-06 | RNF-08 | `curl http://IP_DEL_SERVIDOR:3000/` desde fuera de la VM | **Conexión rechazada**: Node no está expuesto | ✅ Verificado. Caso especialmente demostrativo: en el proyecto de GCP existía una regla de firewall `allow-3000` que abría el puerto 3000 a `0.0.0.0/0`. Aun con el firewall permitiendo el tráfico, el puerto **no responde**, porque Node escucha únicamente en `127.0.0.1`. Es la prueba de que la protección no depende del firewall. PostgreSQL (5432) también cerrado |
| MN-07 | RNF-10 | Reducir la ventana a 375 px de ancho | El catálogo se reordena en una columna, sin desbordamiento horizontal | captura |
| MN-08 | RF-11 | Entrar como lector y comparar la barra superior con la del admin | El lector no ve los enlaces de gestión (complemento visual de PR-13) | captura de ambas |

---

## Cobertura por requisito

| Requisito | Pruebas |
|---|---|
| RF-01 Registro | PR-03, PR-31 |
| RF-02 Login | PR-02, PR-06, PR-07, PR-08, PR-10 |
| RF-03 Logout | PR-38, PR-39 |
| RF-04 Sesión | PR-36, PR-37 |
| RF-05 Búsqueda | PR-15, PR-11, PR-12 |
| RF-06 CRUD libros | PR-20 … PR-27 |
| RF-07 Autores y géneros N:M | PR-20, PR-22 |
| RF-08 Conceptos | MN-01, MN-02, verificación de `sp_guardar_concepto_libro` |
| RF-09 Imágenes | PR-40 … PR-46, MN-03 |
| RF-10 Stock | PR-24, `sp_ajustar_stock` |
| RF-11 Admin único y autorización | PR-13, PR-14, PR-28, PR-29, C-24, MN-08 |
| RF-12 CRUD catálogos | PR-09 |
| RF-13 Panel | PR-09, MN-04 |
| RNF-01 Seguridad | PR-05, PR-13, PR-32 … PR-37, PR-40 … PR-45 |
| RNF-02 Integridad | PR-18, PR-19, PR-27, C-19 … C-25 |
| RNF-03 Validación | PR-21 … PR-27, PR-30, PR-31 |
| RNF-05 Errores controlados | PR-04 |
| RNF-08 Despliegue | MN-05, MN-06 |
| RNF-10 Usabilidad | PR-44, MN-07 |
