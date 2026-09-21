# Requisitos — Librería Online

> **Rutas.** El repositorio es un monorepo. Las rutas de código del monolito
> que aparecen aquí (`app.js`, `src/`, `views/`, `middleware/`, `config/`,
> `services/`, `public/`, `uploads/`) son **relativas a `apps/web-monolito/`**.
> Lo compartido —`db/`, `deploy/`, `docs/`, `tests/`— sigue en la raíz.

Documento de la **Parte 1** del ejercicio: qué debe hacer el sistema y bajo qué
condiciones debe operar, escrito **antes** de diseñar la base de datos.

- Identificadores: `RF-nn` funcionales, `RNF-nn` no funcionales.
- Cada requisito lleva su criterio de aceptación y la prueba que lo verifica
  (`PR-nn` en [TEST_PLAN.md](TEST_PLAN.md), ejecutable con `tests/pruebas.sh`).

---

## 1. Alcance

Aplicación web **monolítica** que permite a un administrador mantener el
catálogo de una librería —libros, autores, géneros, categorías, formatos,
conceptos e imágenes— y a los usuarios registrados consultarlo.

**Dentro del alcance:** registro y sesión de usuarios, CRUD de todas las tablas
administrables, búsqueda, control de existencias y precio, carga de imágenes con
portada, glosario de conceptos por libro, administración restringida a un único
Administrador.

**Fuera del alcance, explícitamente:** carrito de compras, pagos, envíos,
reseñas de usuarios, recuperación de contraseña por correo, API para terceros,
aplicación móvil. Se enumeran para que quede claro que su ausencia es una
decisión de alcance y no un olvido.

---

## 2. Actores

| Actor | Cómo se identifica | Qué puede hacer | Qué se le debe rechazar |
|---|---|---|---|
| **Visitante** | Sin sesión | Ver `/login` y `/registro`; crear una cuenta | Todo lo demás. Cualquier otra URL lo redirige a `/login`, incluso escribiéndola a mano |
| **Usuario Registrado** (`lector`) | Sesión con `rol = 'lector'` | Consultar el catálogo, el detalle de un libro, sus imágenes, sus conceptos y las fichas de autor; buscar | Toda ruta de gestión: alta, edición y borrado de cualquier entidad, panel, usuarios. Debe recibir **403 con una página explicativa**, no un redirect silencioso |
| **Administrador** | Sesión con `rol = 'admin'` | Todo lo anterior + CRUD completo, panel, gestión de usuarios y roles | Crear un segundo Administrador; quitarse a sí mismo el rol o su propia cuenta |

Sólo puede existir **un** Administrador. No es una convención de la interfaz:
está impuesto en la base de datos (`ux_usuarios_admin_unico` + `trg_un_solo_admin`).

---

## 3. Requisitos funcionales

### Cuentas y sesión

| ID | Requisito | Criterio de aceptación | Prueba |
|---|---|---|---|
| RF-01 | Registro de usuario | El alta crea la cuenta con rol `lector` **siempre**, sin importar lo que traiga el formulario. La contraseña se guarda con bcrypt (coste 10). Un correo repetido devuelve un error entendible, no un 500 | PR-03 |
| RF-02 | Inicio de sesión | Con credenciales correctas se crea la sesión y se redirige al catálogo. Con credenciales incorrectas, correo inexistente o cuenta desactivada se responde **el mismo mensaje**, para no revelar qué correos existen | PR-06, PR-07, PR-08 |
| RF-03 | Cierre de sesión | La sesión se destruye en el servidor y la cookie se borra. Después, ninguna ruta protegida vuelve a responder | PR-38, PR-39 |
| RF-04 | Control de sesión | La sesión se regenera al autenticarse (contra fijación de sesión), caduca a las 2 horas y su cookie es `httpOnly` y `SameSite=Lax` | PR-36, PR-37 |

### Catálogo

| ID | Requisito | Criterio de aceptación | Prueba |
|---|---|---|---|
| RF-05 | Búsqueda por ISBN y título | Un solo campo resuelve los tres casos: ISBN exacto ignorando guiones, título parcial ignorando mayúsculas y nombre de autor. La búsqueda es `GET`, para que el resultado se pueda compartir por URL | PR-15 |
| RF-06 | CRUD de libros | Alta, consulta, edición y borrado con formulario web, validación en el servidor y mensaje de resultado. ISBN único; precio y stock no negativos | PR-20 … PR-27 |
| RF-07 | Varios autores y géneros por libro | Un libro admite N autores (con orden de portada) y N géneros; un autor y un género participan en N libros. Un libro sin autor se rechaza | PR-20, PR-22 |
| RF-08 | Conceptos y definiciones por libro | El término se registra una vez en el catálogo; la **definición es propia de cada libro**, con capítulo y página opcionales. El mismo término puede tener textos distintos en libros distintos | manual, ver §6 |
| RF-09 | Gestión de imágenes | Carga, listado y borrado de imágenes por libro. Una puede marcarse como portada; sólo una a la vez. Texto alternativo obligatorio | PR-40 … PR-46 |
| RF-10 | Control de stock y precio | El Administrador ajusta existencias con incrementos y decrementos. El sistema impide dejar el stock negativo | PR-24 |
| RF-11 | Administración restringida | Toda ruta de gestión exige rol `admin`. Un lector recibe 403. No se puede crear un segundo Administrador ni dejar el sistema sin ninguno | PR-13, PR-14, PR-28, PR-29 |
| RF-12 | CRUD de catálogos | Autores, géneros, categorías, formatos y conceptos tienen su propio CRUD. Un registro en uso no se puede borrar, y la interfaz lo advierte antes de intentarlo | PR-09 |
| RF-13 | Panel de administración | Vista con conteos por tabla, inventario por categoría y libros con datos incompletos | PR-09 |

---

## 4. Requisitos no funcionales

| ID | Categoría | Requisito | Cómo se comprueba |
|---|---|---|---|
| RNF-01 | **Seguridad** | Contraseñas con hash bcrypt; sesiones con cookie `httpOnly`/`SameSite`; autorización por rol en cada ruta; token anti-CSRF en todo formulario que escribe; validación de archivos por extensión, MIME, tamaño **y firma binaria**; cabeceras `nosniff`, `X-Frame-Options`, CSP | PR-05, PR-13, PR-32 … PR-37, PR-40 … PR-45 |
| RNF-02 | **Integridad de datos** | Todo SQL parametrizado. Las reglas críticas (unicidad de ISBN, stock ≥ 0, precio ≥ 0, un solo Administrador, una sola portada) están declaradas en PostgreSQL, no sólo en Node | `db/03`, C19 … C25 |
| RNF-03 | **Validación** | Todo campo se valida en el servidor aunque exista validación HTML. Un `POST` hecho con curl saltándose el navegador debe ser rechazado igual | PR-18, PR-21 … PR-27, PR-30, PR-31 |
| RNF-04 | **Mantenibilidad** | Separación estricta model / vista / controller / rutas. Ningún archivo de vista contiene SQL; ningún model conoce HTTP. Un módulo nuevo se agrega sin tocar los existentes | revisión de código |
| RNF-05 | **Trazabilidad de errores** | Los errores quedan en el log del servidor con código y contexto. El usuario final nunca ve un stack trace, un nombre de tabla ni un fragmento de SQL | PR-04, ver §6 |
| RNF-06 | **Rendimiento básico** | El catálogo de 30 libros con sus autores, géneros y portadas se resuelve en **una** consulta (vista con subconsultas laterales), no en N+1. Índices en las FK y en las columnas de búsqueda | `EXPLAIN` sobre `v_libros_detalle` |
| RNF-07 | **Disponibilidad** | El proceso corre bajo systemd (`deploy/libreria.service`), no atado a una sesión SSH, y se reinicia solo si muere. Cierre ordenado del pool de conexiones ante `SIGTERM`. **El arranque automático al encender la VM está deliberadamente desactivado** (`systemctl start`, sin `enable`): es un entorno de ejercicio que se apaga para no generar costo, y se levanta a mano cuando se necesita | `systemctl status libreria` |
| RNF-08 | **Despliegue** | Node escucha sólo en `127.0.0.1:3000`. La cara pública es Apache/NGINX bajo el prefijo `/library`. Cambiar de prefijo es cambiar una variable de entorno, no editar vistas | PR-01, ver `deploy/` |
| RNF-09 | **Secretos** | Ninguna credencial en el repositorio: ni en código, ni en documentación, ni en `.sql`, ni en comentarios. La aplicación **no arranca** si falta un secreto obligatorio | `.env.example`, `config/env.js` |
| RNF-10 | **Usabilidad** | Formularios con etiquetas asociadas, errores agrupados y anunciados con `role="alert"`, imágenes con texto alternativo obligatorio, diseño utilizable en pantalla angosta | revisión manual |
| RNF-11 | **Mínimo privilegio** | La aplicación se conecta con `libreria_app`, que sólo puede leer y escribir filas. No es superusuario ni dueño de las tablas: no puede ejecutar `DROP` ni `ALTER` | `db/00_create_database.sql` |

---

## 5. Supuestos y restricciones

**Supuestos**

1. Un solo servidor y una sola instancia de la aplicación. La sesión vive en
   memoria del proceso; con dos instancias detrás del proxy habría que mover el
   almacén de sesiones a PostgreSQL o Redis.
2. El volumen es de decenas o cientos de libros, no millones. No hay paginación
   en el catálogo porque a esta escala no se justifica; a partir de unos cientos
   de títulos sí haría falta.
3. Un solo idioma (español) y una sola moneda. No hay internacionalización.
4. Las imágenes viven en el disco de la VM. Si la VM se recrea sin conservar el
   disco, se pierden.
5. Los usuarios acceden desde un navegador moderno con cookies habilitadas.

**Restricciones impuestas por el ejercicio**

| Restricción | Dónde se cumple |
|---|---|
| Monolítica y server-side con Node.js, Express y EJS | `app.js`, `views/` |
| Acceso directo a PostgreSQL con el controlador `pg` y consultas parametrizadas | `src/modules/*/*.model.js` |
| Sin API REST, GraphQL, SOAP ni microservicios | no existe ninguna ruta que devuelva datos en vez de HTML |
| Sin JSON ni XML entre navegador y servidor | `app.js` no monta `express.json()` |
| Vistas generadas en el servidor; los formularios envían al monolito | `views/**/*.ejs` |
| Sólo usuarios registrados pueden entrar; como máximo un Administrador | `middleware/auth.js`, `ux_usuarios_admin_unico` |

---

## 6. Riesgos identificados antes de programar

| Riesgo | Escenario concreto | Mitigación aplicada | Riesgo residual |
|---|---|---|---|
| **Acceso no autorizado** | Un lector escribe `/usuarios` a mano, o envía un `POST` de borrado con curl | `requireAdmin` en cada ruta de gestión; la interfaz también oculta los enlaces, pero eso es cosmético | Ninguno relevante mientras el middleware esté en la ruta. Cubierto por PR-13/PR-14 |
| **SQL Injection** | Un título de libro con `'; DROP TABLE libros; --` | 100 % de las consultas parametrizadas; el usuario de BD ni siquiera puede ejecutar `DROP` | Muy bajo. Requeriría introducir una consulta concatenada nueva |
| **Subida de archivo peligroso** | Un `.php` renombrado a `.png` para lograr ejecución remota | Lista blanca de MIME y extensión, límite de tamaño, verificación de la firma binaria, nombre generado por el servidor, y el proxy niega servir ejecutables desde `uploads/` | Bajo. Queda el caso de una vulnerabilidad en el propio decodificador de imágenes del navegador |
| **Exposición de credenciales** | Publicar el `.env` o un hash con la contraseña en un comentario | `.env` en `.gitignore`, `.env.example` sin valores, prohibición explícita en `CLAUDE.md`, arranque abortado si falta un secreto | **Riesgo materializado en el historial de git**: ver [SECURITY_REVIEW.md](SECURITY_REVIEW.md) §Hallazgos |
| **Eliminación accidental** | Borrar una categoría y dejar libros huérfanos | `ON DELETE RESTRICT` en los catálogos; confirmación en la interfaz; la lista marca los registros en uso | Bajo. El `CASCADE` de libro hacia sus imágenes sí es destructivo, pero es el comportamiento deseado |
| **Publicación de datos sensibles** | Mostrar el correo o el hash de un usuario en una vista pública | Los modelos de usuario nunca devuelven `password_hash` a una vista; la lista de usuarios es sólo para el Administrador | Bajo |
| **Fijación / robo de sesión** | Robar la cookie con XSS, o fijar una cookie antes del login | Cookie `httpOnly` (inalcanzable desde JS), regeneración de sesión al autenticar, CSP que bloquea scripts en línea | Bajo. Sube si algún día se sirve por HTTP sin TLS |
| **Fuerza bruta sobre el login** | Probar contraseñas contra `admin@…` | Límite de 5 intentos por IP + correo en 15 minutos; mismo mensaje para todos los fallos; bcrypt hace cara cada prueba | Medio: el contador vive en memoria y se reinicia al reiniciar el proceso |
| **Pérdida de imágenes** | Recrear la VM sin conservar el disco | Documentado; las imágenes son reproducibles desde `db/seed_uploads/` para los datos de prueba | Asumido. Mitigarlo exigiría Cloud Storage, fuera del alcance del ejercicio |
