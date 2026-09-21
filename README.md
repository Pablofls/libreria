# Librería Online

Aplicación web **monolítica** para gestionar el catálogo de una librería: libros
con varios autores y géneros, categorías, formatos, precio, existencias,
imágenes y un glosario de conceptos propio de cada título.

**Node.js + Express + EJS + PostgreSQL**, renderizado en el servidor, sin APIs
REST ni JSON entre navegador y servidor.

> **La base de datos no es local.** La aplicación y PostgreSQL corren en una VM
> de GCP. Desde este repositorio se **escribe** SQL, no se ejecuta: todo cambio
> va a `db/pending/` y sólo es real cuando alguien lo corre en la VM. Ver
> [Flujo de cambios en la base de datos](#flujo-de-cambios-en-la-base-de-datos).

---

## Contenido

1. [Arranque rápido](#arranque-rápido)
2. [Arquitectura](#arquitectura)
3. [Estructura de archivos](#estructura-de-archivos)
4. [Variables de entorno](#variables-de-entorno)
5. [Base de datos](#base-de-datos)
6. [Flujo de cambios en la base de datos](#flujo-de-cambios-en-la-base-de-datos)
7. [Rutas](#rutas)
8. [Roles y autorización](#roles-y-autorización)
9. [Subida de imágenes](#subida-de-imágenes)
10. [Pruebas](#pruebas)
11. [Despliegue](#despliegue)
12. [Agregar un módulo nuevo](#agregar-un-módulo-nuevo)
13. [Cliente de escritorio en Electron](#cliente-de-escritorio-en-electron)
14. [Documentación del ejercicio](#documentación-del-ejercicio)

---

## Arranque rápido

```bash
cd apps/web-monolito
npm install
cp .env.example .env      # y completar DB_PASSWORD y SESSION_SECRET
npm start                 # → http://127.0.0.1:3000
```

Éste es el monolito, la aplicación principal. Los demás procesos del monorepo
—el cliente Electron y los microservicios de `apps/services/`— se arrancan cada
uno desde su propia carpeta; ver el README de cada uno.

Genera un `SESSION_SECRET` nuevo con:

```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

La aplicación **no arranca** si falta un secreto obligatorio: es deliberado. Un
valor por omisión inseguro pasa desapercibido; un fallo al arrancar, no.

Para montaje desde cero (base de datos incluida), ver
[docs/GCP_COMMANDS.md](docs/GCP_COMMANDS.md).

---

## Arquitectura

![Arquitectura](docs/ARCHITECTURE_MONOLITHIC.png)

Interfaz, lógica de negocio y acceso a datos viven en **una sola unidad
desplegable**: un proceso Node.js. Los módulos dividen el código, no el
despliegue: se llaman entre sí con llamadas de función dentro del mismo proceso,
no por red.

### Flujo de una petición

```
Navegador
  → Apache/NGINX          publica /library, termina TLS, sirve estáticos
  → app.js
      cabeceras de seguridad (CSP, nosniff, X-Frame-Options)
      express.static      /css, /js, /uploads
      express.urlencoded  formularios HTML; NO hay express.json()
      express-session     cookie httpOnly, SameSite=Lax
      locals + CSRF       variables de vista y token anti-CSRF
  → *.routes.js           método + URL → controller
      requireLogin / requireAdmin
  → *.controller.js       valida (services/), llama al model, elige la vista
      → *.model.js        SQL parametrizado → PostgreSQL
      → res.render(...)   plantilla EJS → HTML
  → 404 y manejador de errores
```

### Responsabilidades

Rutas relativas a `apps/web-monolito/`.

| Capa | Archivo | Regla que no se rompe |
|---|---|---|
| **Model** | `src/modules/*/​*.model.js` | Todo el SQL, siempre parametrizado. No conoce `req`, `res` ni HTML |
| **Vista** | `views/**/*.ejs` | Genera HTML. No hace consultas ni contiene lógica de negocio |
| **Controller** | `src/modules/*/​*.controller.js` | Orquesta. No contiene SQL ni arma HTML |
| **Rutas** | `src/modules/*/​*.routes.js` | Sólo mapea método + URL → controller, con su middleware |
| **Middleware** | `middleware/` | Autorización, CSRF, subidas, errores. No conoce ningún dominio |
| **Servicios** | `services/` | Validación y lógica compartida entre módulos. No conoce HTTP |
| **Configuración** | `config/` | Único lugar que lee `process.env` y que crea el Pool de `pg` |

> **Escapado.** EJS escapa por omisión con `<%= %>`. La salida cruda `<%- %>` se
> usa **sólo** para incluir parciales, nunca para datos. Un título de libro que
> contenga `<script>` se imprime como texto.

Las decisiones y sus alternativas están en
[docs/ENGINEERING_DECISIONS.md](docs/ENGINEERING_DECISIONS.md).

---

## Estructura de archivos

El repositorio es un **monorepo**: cada aplicación vive bajo `apps/` con sus
propias dependencias y su propio arranque, y lo que comparten —base de datos,
despliegue, documentación y pruebas— queda en la raíz.

```
libreria/
├── apps/
│   ├── web-monolito/             EL MONOLITO Node + Express + EJS (puerto 3000)
│   │   ├── app.js                Arranque de Express, middleware general, montaje de rutas
│   │   ├── package.json          Dependencias del monolito. `npm install` se corre AQUÍ
│   │   ├── .env.example          Nombres de las variables, sin ningún valor real
│   │   │
│   │   ├── config/
│   │   │   ├── env.js            Lee y valida .env; aborta si falta un secreto
│   │   │   └── db.js             Pool único de PostgreSQL (pg)
│   │   │
│   │   ├── middleware/
│   │   │   ├── auth.js           requireLogin · requireAdmin · requireInvitado
│   │   │   ├── locals.js         Variables de vista + generación y chequeo de CSRF
│   │   │   ├── subidas.js        Multer endurecido: tipo, extensión, tamaño y firma
│   │   │   └── errores.js        404, 500 y traducción de los errores de pg
│   │   │
│   │   ├── services/
│   │   │   ├── validacion.js     Validación server-side de todos los campos
│   │   │   └── crudCatalogo.js   Lógica común de los cinco catálogos
│   │   │
│   │   ├── src/modules/          Un directorio por dominio
│   │   │   ├── auth/             login, registro, logout
│   │   │   ├── libros/           CRUD + búsqueda + relaciones N:M
│   │   │   ├── autores/          CRUD + ficha con sus libros
│   │   │   ├── generos/          CRUD
│   │   │   ├── categorias/       CRUD
│   │   │   ├── formatos/         CRUD
│   │   │   ├── conceptos/        CRUD del catálogo + definición por libro
│   │   │   ├── imagenes/         subida, portada, texto alternativo, borrado
│   │   │   ├── usuarios/         CRUD y roles (sólo Administrador)
│   │   │   └── panel/            resumen e inventario
│   │   │       └── cada uno: <n>.model.js · <n>.controller.js · <n>.routes.js
│   │   │
│   │   ├── views/                30 plantillas EJS
│   │   │   ├── parciales/        cabeza · barra · aviso · errores · csrf · pie · confirmar · buscador
│   │   │   └── auth/ libros/ autores/ catalogo/ conceptos/ imagenes/ usuarios/ panel/ errores/
│   │   │
│   │   ├── public/
│   │   │   ├── css/style.css     Hoja de estilos única
│   │   │   └── js/app.js         JavaScript de interfaz (sólo comodidad)
│   │   │
│   │   └── uploads/              Imágenes subidas. Fuera de public/. No se versiona
│   │
│   ├── electron-app/             Cliente de escritorio (Electron) que consume el XML
│   │   ├── main.js               Proceso principal: ventana y descarga del XML
│   │   ├── preload.js            Puente aislado hacia el renderer
│   │   └── renderer/             index.html · estilos.css · renderer.js
│   │
│   └── services/                 Microservicios Python, uno por carpeta
│       ├── catalogo/             Catálogo bilingüe XML/JSON (Flask, 5002)
│       │   ├── app.py            Servicio completo, una sola app Flask sin Blueprints
│       │   ├── library.xml       Catálogo de ejemplo con la misma estructura
│       │   └── library.css       Hoja que el navegador aplica al XML
│       ├── soap/                 Módulo SOAP de clasificación Cloud (Flask, 5001)
│       │   ├── app.py            Traduce HTTP ↔ SOAP; la lógica está en soap/
│       │   ├── soap/             envelope · faults · security (WS-Security) · service
│       │   ├── wsdl/             Contrato library-classifier.wsdl
│       │   ├── sql/ db/ config/  SQL propio, acceso a datos y ajustes
│       │   └── docs/ tests/      Documentación técnica, evidencias y pruebas
│       └── login/                Autenticación (Flask + Psycopg 3, 5000)
│           ├── app.py            Servicio completo: rutas, SQL, XML/JSON y Swagger
│           ├── pruebas.py        84 comprobaciones en proceso, sin BD ni Postfix
│           └── .env.example      Plantilla de configuración (el .env no se versiona)
│
├── clients/                      Clientes del servicio SOAP
│   ├── clasificador_python/      Cliente y GUI en Python
│   └── clasificador_java/        Cliente y GUI en Java
│
├── db/                           Compartida por todas las apps
│   ├── 00_create_database.sql    Base de datos y roles con privilegios mínimos
│   ├── 01_schema.sql             Tablas, PK, FK, UNIQUE, CHECK, índices
│   ├── 02_seed_30_per_table.sql  30 filas por tabla base
│   ├── 03_all_quieries_...sql    Todas las consultas + 7 pruebas negativas
│   ├── 04_stored_procedures.sql  5 rutinas almacenadas
│   ├── 05_triggers.sql           6 disparadores
│   ├── 06_views.sql              4 vistas
│   ├── seed_uploads/             30 portadas sintéticas para los datos de prueba
│   ├── pending/                  SQL escrito, todavía NO ejecutado en la VM
│   └── applied/                  SQL ya ejecutado en la VM
│
├── deploy/
│   ├── nginx-library.conf        Reverse proxy con NGINX
│   ├── apache-library.conf       Alternativa con Apache
│   ├── libreria.service          Unidad de systemd del monolito, con endurecimiento
│   ├── libreria-catalogo.service Unidad del microservicio de catálogo (5002)
│   ├── libreria-login.service    Unidad del microservicio de autenticación (5000)
│   └── libreria-soap.service     Unidad del módulo SOAP de clasificación (5001)
│
├── tests/pruebas.sh              57 pruebas ejecutables de la matriz
├── evidencias/                   Capturas de las entregas
└── docs/                         ver "Documentación del ejercicio"
```

No hay workspaces de npm ni herramienta de monorepo: cada app se instala y se
arranca desde su propia carpeta. Es deliberado — son cuatro procesos
independientes que sólo comparten la base de datos, no código.

---

## Variables de entorno

Se definen en `.env`, que **no se versiona**. `.env.example` documenta los
nombres, sin valores.

| Variable | Ejemplo | Descripción |
|---|---|---|
| `DB_USER` | `libreria_app` | Usuario de PostgreSQL. Privilegios mínimos: no es superusuario |
| `DB_HOST` | `127.0.0.1` | `localhost` desde la propia VM |
| `DB_NAME` | `libreria_db` | Nombre de la base de datos |
| `DB_PASSWORD` | *(sólo en la VM)* | **Nunca** se documenta ni se versiona |
| `DB_PORT` | `5432` | Puerto de PostgreSQL |
| `NODE_ENV` | `production` | Activa la caché de plantillas |
| `APP_HOST` | `127.0.0.1` | Interfaz de escucha. Loopback: Node no se expone a internet |
| `APP_PORT` | `3000` | Puerto interno |
| `BASE_PATH` | `/library` | Prefijo público del reverse proxy. Vacío en desarrollo local |
| `SESSION_SECRET` | *(32+ caracteres)* | Firma la cookie de sesión. Sin él la aplicación no arranca |
| `COOKIE_SECURE` | `false` | `true` sólo cuando se sirva por HTTPS |
| `UPLOAD_DIR` | `uploads` | Directorio de las imágenes subidas |
| `UPLOAD_MAX_BYTES` | `2097152` | Tamaño máximo por imagen (2 MB) |

`BASE_PATH` es lo que permite que el mismo código corra en la raíz durante el
desarrollo y bajo `/library` en la VM: las plantillas construyen sus enlaces como
`<%= base %>/libros`.

---

## Base de datos

Modelo normalizado hasta **4FN**: 8 entidades y 4 tablas puente.

> **`usuarios.nombre` es redundante a propósito.** El nombre real vive partido
> en `personas` (nombre, apellido paterno, apellido materno), que es lo que
> consume el microservicio de autenticación. La columna plana se conserva
> porque el monolito Node la lee y la escribe, y no se toca; no puede ser
> `GENERATED` justamente porque el monolito la escribe. Dos disparadores de
> [`db/05_triggers.sql`](db/05_triggers.sql) mantienen las dos
> representaciones en sincronía en ambos sentidos.

![Modelo ER](docs/DB_DESIGN_ER_4FN.png)

### Diagrama de relaciones

```
personas                        autores                 generos
  id (PK)                         id (PK)                 id (PK)
  nombre                          nombre       ┐U         nombre (U)
  apellido_paterno                nacionalidad ┘          descripcion
  apellido_materno                biografia
  ▲ los apellidos admiten NULL
  │                             categorias              formatos
  │ 1:1                           id (PK)                 id (PK)
  │                               nombre (U)              nombre (U)
usuarios                          descripcion             descripcion
  id (PK)
  persona_id (U) → personas(id)   ← UNIQUE: una persona, una cuenta
  nombre                          ← copia derivada, la mantiene un trigger
  email (U)
  password_hash  ← bcrypt
  rol            ← lector | admin
  activo
  creado_en
  ▲ índice único parcial
    WHERE rol='admin'
    → como máximo UN admin

libros
  id (PK)
  isbn (U)                    ← CHECK formato ISBN-10/13
  titulo
  anio_publicacion            ← CHECK entre 1450 y 2100
  sinopsis
  precio                      ← CHECK >= 0
  stock                       ← CHECK >= 0
  categoria_id  → categorias(id)  ON DELETE RESTRICT
  formato_id    → formatos(id)    ON DELETE RESTRICT
  creado_en · actualizado_en  ← sello automático por trigger

libros_autores                     libros_generos
  libro_id  → libros    CASCADE      libro_id  → libros   CASCADE
  autor_id  → autores   RESTRICT     genero_id → generos  RESTRICT
  orden          ← posición en portada
  PK (libro_id, autor_id)            PK (libro_id, genero_id)

conceptos                          libros_conceptos
  id (PK)                            libro_id    → libros    CASCADE
  termino (U)                        concepto_id → conceptos RESTRICT
  ← sólo el término:                 definicion   ← propia de ESTE libro
    la definición cambia             capitulo · pagina
    según el libro                   PK (libro_id, concepto_id)

imagenes_libros
  id (PK)
  libro_id           → libros(id)  ON DELETE CASCADE
  nombre_archivo (U) ← UUID + extensión, generado por el servidor
  nombre_original    ← sólo metadato; nunca toca el sistema de archivos
  tipo_mime          ← CHECK: jpeg | png | webp
  tamano_bytes       ← CHECK: > 0 y <= 2 MB
  texto_alternativo  ← accesibilidad
  es_portada         ← índice único parcial: una sola portada por libro


──────────────── Tablas del módulo SOAP (apps/services/soap) ────────
Las crea sql/soap_module.sql, NO db/01_schema.sql. No modifican ninguna tabla
del monolito: sólo la referencian por clave foránea.

clasificadores                     clientes_servidos
  id (PK)                            id (PK)
  nombre · apellidos                 tipo_cliente  ┐U
  correo (U)   ← CHECK formato       identificador ┘
  creado_en                          peticiones_atendidas ← CHECK >= 0
  ← identidad del cliente SOAP;      primera_peticion · ultima_peticion
    NO reutiliza usuarios

clasificaciones_cloud
  id (PK)
  clasificador_id     → clasificadores(id)      ON DELETE RESTRICT
  (libro_id, concepto_id)
                      → libros_conceptos(libro_id, concepto_id)  CASCADE
                        ← FK COMPUESTA: obliga a que el concepto esté
                          DEFINIDO en ese libro, no sólo a que ambos existan.
                          CASCADE y no RESTRICT: con RESTRICT el módulo le
                          impedía al monolito borrar un libro clasificado
  modelo              ← CHECK: IaaS | PaaS | SaaS | FaaS
  cliente_servido_id  → clientes_servidos(id)   ON DELETE SET NULL
  clasificado_en
  U (clasificador_id, concepto_id) ← el mismo clasificador no registra
                                     dos veces el mismo concepto → Fault 409
```

### Por qué cuatro tablas puente

Autores, géneros, conceptos e imágenes son cuatro dependencias multivaluadas
**independientes** sobre libro. Juntar dos de ellas en una sola relación produce
su producto cartesiano: un libro con 3 autores y 2 géneros necesitaría 6 filas
para expresar 5 datos, y 4 de esas filas afirmarían combinaciones que nadie
capturó. Eso es exactamente lo que 4FN prohíbe.

El proceso completo, paso a paso desde la relación no normalizada, está en
[docs/NORMALIZATION_4FN.xlsx](docs/NORMALIZATION_4FN.xlsx).

### Objetos de base de datos

| Tipo | Nombre | Para qué |
|---|---|---|
| Procedimiento | `sp_guardar_libro` | Libro + autores + géneros en una transacción |
| Procedimiento | `sp_guardar_concepto_libro` | Crea o reutiliza el término y guarda la definición del libro |
| Procedimiento | `sp_ajustar_stock` | Ajuste atómico, sin condición de carrera |
| Procedimiento | `sp_marcar_portada` | Marca la portada; el trigger apaga la anterior |
| Función | `fn_buscar_libros` | Búsqueda por ISBN, título o autor |
| Trigger | `trg_un_solo_admin` | Mensaje legible al intentar un segundo Administrador |
| Trigger | `trg_conservar_admin` | Impide dejar el sistema sin Administrador |
| Trigger | `trg_portada_unica` | Apaga la portada anterior al marcar otra |
| Trigger | `trg_promover_portada` | Asciende otra imagen si se borra la portada |
| Trigger | `trg_libros_actualizado` | Sello de última modificación |
| Trigger | `trg_normalizar_email` | Correo en minúsculas y sin espacios |
| Vista | `v_libros_detalle` | Libro con autores, géneros, conteos y portada resueltos |
| Vista | `v_catalogo` | Proyección para el lector: sin el stock exacto |
| Vista | `v_libros_conceptos` | Glosario aplanado libro–término–definición |
| Vista | `v_inventario_por_categoria` | Resumen para el panel |

Objetos del **módulo SOAP**, definidos en
[`apps/services/soap/sql/soap_module.sql`](apps/services/soap/sql/soap_module.sql):

| Tipo | Nombre | Para qué |
|---|---|---|
| Función | `fn_registrar_clasificacion` | Clasificador, contador y registro en una transacción |
| Vista | `v_conceptos_clasificables` | Conceptos por libro, con ISBN y categoría |
| Vista | `v_conceptos_pendientes` | Los que nadie ha clasificado todavía |
| Vista | `v_progreso_clasificadores` | Totales clasificados y pendientes por clasificador |
| Vista | `v_estadisticas_modelo` | Conteo por modelo Cloud |
| Rol | `libreria_soap` | Mínimo privilegio: lectura por columna, sin `DELETE`, sin acceso a `usuarios` |

---

## Flujo de cambios en la base de datos

La base de datos vive en la VM de GCP y **la aplicación nunca modifica el esquema
por su cuenta**. Todo SQL que haya que correr se escribe primero en un archivo
dentro de `db/pending/` y espera ahí hasta que se ejecuta a mano en la VM.

| Carpeta | Contenido |
|---|---|
| `db/00…06_*.sql` | Los scripts canónicos del esquema. Reconstruyen la base desde cero |
| `db/pending/` | Cambios escritos, **todavía no ejecutados** en la VM |
| `db/applied/` | Cambios que **ya se ejecutaron**. Es historial: no se editan ni se vuelven a correr |

### Regla

> Si un cambio toca la base de datos —tabla nueva, columna, índice, `ALTER`,
> corrección de datos—, el `.sql` correspondiente se crea en `db/pending/`. Nada
> se mueve a `db/applied/` hasta confirmar que la consulta corrió sin error.

### Nombre de los archivos

`YYYYMMDD-descripcion-corta.sql`, para que el orden de ejecución sea evidente.
Cada archivo empieza con un comentario que explica **qué hace y por qué**.

### Nunca credenciales en claro

> **Ninguna credencial se escribe en claro en el repositorio.** Ni contraseñas,
> ni tokens, ni claves de API — en código, documentación, archivos `.sql`, y
> **tampoco en los comentarios**.

En un `.sql` que cambie una contraseña va el hash y nada más. El comentario dice
qué hace la consulta, nunca cuál es el valor:

```sql
-- MAL: publica la credencial aunque el UPDATE sólo lleve el hash
-- Cambia la contraseña de admin@ejemplo.com a "…".

-- BIEN
-- Cambia la contraseña de admin@ejemplo.com. Hash bcrypt (coste 10), el mismo
-- factor que usa auth.model.js. El valor se comunica fuera del repositorio.
```

Borrar el archivo después **no deshace nada**: el repositorio es público y el
historial de git conserva cada versión. Lo único que resuelve una credencial
publicada es **rotarla**. Ver [SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) H-01.

### Ciclo completo

1. **Escribir** el `.sql` en `db/pending/`.
2. **Ejecutar** en la VM, en orden de fecha.
3. **Mover** a `db/applied/` con `git mv` en cuanto se confirme que corrió.
4. **Actualizar `db/01_schema.sql`** para que refleje el estado final.
5. **Actualizar el [diagrama de relaciones](#diagrama-de-relaciones)** de este README.
6. **Un solo commit** con las tres cosas.

Los pasos 4 y 5 no son opcionales: nada valida el esquema documentado contra la
VM, así que si se saltan, la documentación empieza a describir una base de datos
que ya no existe.

---

## Rutas

Todas las rutas cuelgan de `BASE_PATH` (`/library` en la VM, vacío en local).

### Autenticación — público

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Redirige a `/libros` o `/login` |
| GET · POST | `/login` | Formulario y validación de credenciales |
| GET · POST | `/registro` | Alta de cuenta. Siempre con rol `lector` |
| GET | `/logout` | Destruye la sesión |

### Libros — consulta `requireLogin`, gestión `requireAdmin`

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| GET | `/libros` · `/libros?q=…` | login | Catálogo (lector) o tabla de gestión (admin), con búsqueda |
| GET | `/libros/:id` | login | Detalle con autores, géneros, imágenes y conceptos |
| GET · POST | `/libros/nuevo` · `/libros` | admin | Alta |
| GET · POST | `/libros/:id/editar` | admin | Edición |
| POST | `/libros/:id/stock` | admin | Ajuste de existencias |
| POST | `/libros/:id/eliminar` | admin | Borrado (cascade a imágenes y conceptos) |

### Catálogos — `requireAdmin`

`/autores`, `/generos`, `/categorias`, `/formatos` y `/conceptos` comparten el
mismo mapa: `GET /`, `GET /nuevo`, `POST /`, `GET /:id/editar`,
`POST /:id/editar`, `POST /:id/eliminar`.

`GET /autores/:id` y `GET /conceptos/:id` son fichas de consulta y admiten
cualquier usuario registrado.

### Conceptos dentro de un libro — `requireAdmin`

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/conceptos/libro/:libro_id/nuevo` | Formulario (con `?concepto_id=` para editar) |
| POST | `/conceptos/libro/:libro_id` | Guarda término + definición del libro |
| POST | `/conceptos/libro/:libro_id/:concepto_id/quitar` | Retira la definición; el término sigue en el catálogo |

### Imágenes y administración — `requireAdmin`

| Método | Ruta | Descripción |
|---|---|---|
| GET · POST | `/imagenes/nuevo/:libro_id` · `/imagenes/:libro_id` | Subida con validación |
| POST | `/imagenes/:id/portada` · `/:id/alt` · `/:id/eliminar` | Portada, texto alternativo, borrado |
| — | `/usuarios/*` | CRUD de usuarios y roles |
| GET | `/panel` | Conteos, inventario y libros incompletos |

---

## Roles y autorización

| Rol | Puede | Se le rechaza |
|---|---|---|
| **Visitante** (sin sesión) | `/login`, `/registro` | Todo lo demás → redirige a `/login` |
| **`lector`** | Catálogo, detalle, búsqueda, fichas de autor y concepto | Toda ruta de gestión → **403 con página explicativa** |
| **`admin`** | Todo lo anterior + CRUD completo, panel y usuarios | Crear un segundo Administrador; quitarse el rol o borrarse a sí mismo |

La restricción se aplica en dos capas, y **sólo una de ellas protege**:

1. **Rutas.** Cada `*.routes.js` protege las operaciones de gestión con
   `requireAdmin`. Esto es lo que realmente impide el acceso.
2. **Interfaz.** `views/parciales/barra.ejs` no dibuja los enlaces de gestión
   para un lector, y las vistas ocultan los botones. Esto es **comodidad
   visual**, no protección: la prueba PR-14 envía el `POST` de borrado
   directamente y se rechaza igual.

**Un solo Administrador.** Impuesto en la base de datos con el índice único
parcial `ux_usuarios_admin_unico`, no en el código: comprobarlo en el controller
sería una condición de carrera. El trigger `trg_un_solo_admin` sólo mejora el
mensaje de error.

---

## Subida de imágenes

Gestionada por `middleware/subidas.js`. Cinco capas de validación:

| Control | Qué impide |
|---|---|
| Lista blanca de MIME (`image/jpeg`, `image/png`, `image/webp`) | Tipos no soportados |
| Lista blanca de extensión | Nombres con extensión ejecutable |
| Límite de 2 MB en Multer y en la base de datos | Llenar el disco de la VM |
| **Verificación de la firma binaria** del archivo escrito | Un `.php` renombrado a `.png` con MIME falseado |
| Nombre generado por el servidor: UUID + extensión | `../` y dobles extensiones |

Si cualquier comprobación falla, el archivo se borra del disco. `uploads/` está
**fuera** de `public/` y se sirve con `nosniff` y `Content-Disposition: inline`;
el reverse proxy además niega servir extensiones ejecutables desde ahí.

El texto alternativo es obligatorio. Una imagen puede marcarse como portada; el
trigger `trg_portada_unica` apaga la anterior automáticamente.

---

## Pruebas

```bash
# Aplicación: 57 casos de la matriz
BASE_URL=http://127.0.0.1:3000 \
ADMIN_EMAIL='admin@libreria.com' ADMIN_PASS='…' \
LECTOR_EMAIL='ana.ruiz@libreria.udem.mx' LECTOR_PASS='…' \
bash tests/pruebas.sh

# Base de datos: consultas + 7 pruebas negativas de integridad
psql -U libreria_owner -d libreria_db -f db/03_all_quieries_before_stored_procedures.sql
```

Las credenciales se pasan por variable de entorno; no están escritas en ningún
archivo. La matriz completa, con cobertura por requisito, está en
[docs/TEST_PLAN.md](docs/TEST_PLAN.md).

---

## Despliegue

Node escucha en `127.0.0.1:3000` y **no se expone a internet**. La cara pública
es Apache o NGINX bajo el prefijo `/library`.

```bash
sudo cp deploy/nginx-library.conf /etc/nginx/conf.d/library.conf
sudo nginx -t && sudo systemctl reload nginx
sudo setsebool -P httpd_can_network_connect 1     # SELinux, o el proxy da 503

sudo cp deploy/libreria.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now libreria
```

Comprobación de que sólo el proxy está publicado:

```bash
curl -I http://IP_DEL_SERVIDOR/library/login      # 200
curl -I --max-time 5 http://IP_DEL_SERVIDOR:3000/ # debe fallar
```

> **Esa segunda comprobación hoy NO falla.** En el proyecto de GCP existe una
> regla `allow-3000` que abre `tcp:3000` a `0.0.0.0/0` sin etiqueta de red, así
> que el monolito es alcanzable directo, saltándose el proxy. Está pendiente de
> borrar; hasta entonces, este párrafo describe la intención, no la realidad.

Los comandos completos están en [docs/GCP_COMMANDS.md](docs/GCP_COMMANDS.md).

### Los cuatro servicios de la VM

Son cuatro aplicaciones independientes, cada una con su unidad de systemd, su
propio `.env` y su propio rol de PostgreSQL. Si una se cae, las otras siguen.

| Servicio | Unidad | Puerto | Expuesto a internet |
|---|---|---|---|
| Monolito Node (Express + EJS) | `libreria.service` | 3000 | No por diseño: sólo por el proxy, bajo `/library` |
| Microservicio de autenticación | `libreria-login.service` | 5000 | Sí |
| Módulo SOAP de clasificación | `libreria-soap.service` | 5001 | No: túnel SSH, ver [clients/README.md](clients/README.md) |
| Microservicio de catálogo (XML/JSON) | `libreria-catalogo.service` | 5002 | Sí: lo consume el cliente Electron |

**El baile de puertos, y por qué el catálogo es el que siempre cede.** El
módulo SOAP tiene el 5001 escrito en el `soap:address` de su WSDL, en sus
evidencias ya capturadas y en sus dos clientes Java y Python. El microservicio
de autenticación tiene el 5000 en su enunciado y no tiene de dónde moverse. El
catálogo es el único de los tres cuyo puerto **no está escrito en ningún
contrato**: al cliente Electron se le indica IP y puerto desde su propio popup
de configuración. Por eso se mudó primero del 5001 al 5000, y ahora del 5000 al
5002. **Al demostrar el Electron hay que escribirle el puerto 5002 en ese
popup**, o pedirá el catálogo a quien no es.

**Cada servicio Python con su propio `.env`, en su propio directorio.** No los
compartas ni los enlaces: el segundo en arrancar moriría con *Address already
in use* o, peor porque no se nota, respondería lo que no es.

### Microservicio de catálogo

```bash
cd /opt/udem/libreria/apps/services/catalogo
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env     # completar DB_PASSWORD y API_TOKEN

sudo restorecon -Rv /opt/udem/libreria/apps/services/catalogo
sudo cp /opt/udem/libreria/deploy/libreria-catalogo.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now libreria-catalogo
systemctl status libreria-catalogo --no-pager -l
```

Tres cosas que cuestan un rato averiguar si no están escritas:

- **El `restorecon` va DESPUÉS del `pip install`**, y hay que repetirlo cada vez
  que se recree el entorno virtual. Los archivos clonados en el directorio
  personal arrastran la etiqueta SELinux `user_home_t`, y systemd no puede
  siquiera leer un enlace simbólico con ese tipo: el servicio falla con
  `203/EXEC` y *Permission denied* aunque el binario corra perfectamente a mano.
- **El `status` recién arrancado engaña.** A los pocos milisegundos muestra
  `active (running)` con `Tasks: 1` y el PID entre paréntesis, antes de saberse
  si el proceso sobrevivió. Espera unos segundos y comprueba que hay `Tasks: 3`
  —el maestro de gunicorn y dos workers— y que `ss -lntp` lo ve en el puerto.
- **Dos workers, al contrario que el módulo SOAP**, que está clavado en uno
  porque guarda en memoria del proceso los nonces de WS-Security. Este servicio
  no retiene nada entre peticiones, así que se puede replicar. Cada worker abre
  su propio pool de hasta `DB_POOL_MAX` conexiones: si se suben los workers, hay
  que bajar esa variable en la misma proporción.

Operación diaria:

```bash
sudo systemctl restart libreria-catalogo
journalctl -u libreria-catalogo -f        # logs en vivo, con cada petición
```

Antes de esto el servicio se lanzaba a mano con `python app.py`, colgando del
shell de la sesión SSH. Al cerrar la terminal quedaba un proceso huérfano
reteniendo el puerto, y el siguiente arranque fallaba con *Address already in
use*. Con systemd el proceso cuelga de PID 1, vuelve solo tras reiniciar la VM
(`enabled`) y se relevanta a los 5 segundos si se cae (`Restart=on-failure`).

### Microservicio de autenticación

```bash
cd /opt/udem/libreria/apps/services/login
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env     # completar DB_PASSWORD y SECRET_KEY

sudo restorecon -Rv /opt/udem/libreria/apps/services/login
sudo cp /opt/udem/libreria/deploy/libreria-login.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now libreria-login
systemctl status libreria-login --no-pager -l
```

Mismas trampas que el catálogo —el `restorecon` después del `pip install`, el
`status` que engaña recién arrancado— más dos propias:

- **Sin `SECRET_KEY` el servicio no arranca**, y es a propósito: es la clave con
  la que se firman las cookies de sesión. Un valor por omisión en un
  repositorio público permitiría a cualquiera fabricarse la sesión de cualquier
  usuario. Genera una con
  `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Cambiarla
  invalida todas las sesiones abiertas, que es justo lo que se quiere si alguna
  vez se sospecha que se filtró.
- **Necesita Postfix levantado** para verificar correos, pero no depende de él
  para arrancar: `Wants=`, no `Requires=`. Sin Postfix el registro sigue
  funcionando y `/health` reporta el correo como `degradado`, no como `error`.

El detalle del contrato XML/JSON, de la verificación del correo y de sus
límites está en
[`apps/services/login/README.md`](apps/services/login/README.md).

### Firewall: son dos, no uno

Para publicar un puerto hay que abrirlo en **los dos**, y olvidar el segundo se
manifiesta como un `curl` que se queda colgado sin responder:

```bash
# 1. GCP. La etiqueta debe coincidir con una que la VM realmente tenga:
#    gcloud compute instances describe maquina01 --zone ZONA #      --format="value(tags.items.list())"
gcloud compute firewall-rules create libreria-permitir-microservicios \
  --direction=INGRESS --action=ALLOW --rules=tcp:5000,tcp:5002 \
  --target-tags=http-server --source-ranges=0.0.0.0/0

# 2. firewalld, dentro de la VM
sudo firewall-cmd --add-port=5000/tcp --add-port=5002/tcp --permanent
sudo firewall-cmd --reload && sudo firewall-cmd --list-ports
```

> El puerto **25 no se abre**, ni de entrada ni de salida. Postfix escucha sólo
> en loopback y existe únicamente para que el microservicio de autenticación le
> pregunte si una dirección existe. Abrirlo lo convertiría en un relay abierto.
> Y la salida por el 25 no se puede abrir aunque se quiera: el bloqueo está en
> la red de Google, aguas arriba del firewall de la VM.

Diagnóstico: `curl` colgado sin respuesta es firewall; *connection refused* es
que el servicio no corre o escucha sólo en loopback.

> **Con el 5002 abierto a `0.0.0.0/0`, `/books/insert`, `/books/update` y
> `/books/delete` quedan al alcance de cualquiera**, porque corren con el rol
> `libreria_app`, que sí escribe. Lo único que los protege es `API_TOKEN`, y
> viene vacío por omisión — el servicio lo avisa en cada arranque. Define uno en
> `apps/services/catalogo/.env`, o estrecha la regla a tu IP con
> `gcloud compute firewall-rules update libreria-permitir-catalogo
> --source-ranges=TU_IP/32`. Lo ideal es lo primero; lo segundo no sobrevive a
> un cambio de red.

### La IP pública es efímera

Si la VM no tiene una IP reservada, GCP se la quita al apagarla y le da otra
distinta al encenderla. Cada apagón rompe la URL de Postman y la configuración
que el cliente Electron guardó en `localStorage`. Para comprobarlo y reservar la
actual sin cortar nada:

```bash
gcloud compute addresses list        # vacío = efímera
gcloud compute addresses create libreria-ip --addresses=LA_IP_ACTUAL --region=REGION
```

Una IP estática **en uso** es gratis; reservada con la VM apagada se cobra por
hora. Si la VM va a quedar apagada mucho tiempo, libérala con
`gcloud compute addresses delete libreria-ip --region=REGION`.

Apagar la VM no deja nada encendido: se detienen los tres servicios. Al
encenderla vuelven solos, porque las tres unidades están `enabled`.

---

## Agregar un módulo nuevo

Los archivos de código de esta sección viven dentro de `apps/web-monolito/`;
`db/` sigue en la raíz del monorepo.

Ejemplo: un módulo `editoriales`.

1. **Base de datos.** Escribir `db/pending/YYYYMMDD-agrega-editoriales.sql`.
   Al confirmarse la ejecución, mover a `db/applied/` y actualizar
   `db/01_schema.sql` y el diagrama de este README.

2. **Crear los tres archivos del módulo:**

```
src/modules/editoriales/
├── editoriales.model.js        SQL parametrizado
├── editoriales.controller.js   orquesta model + vista
└── editoriales.routes.js       método + URL → controller, con middleware
```

3. **Vistas** en `views/editoriales/`, o reutilizar `views/catalogo/` si el
   módulo es un catálogo simple (`nombre` + `descripcion`), en cuyo caso el
   controller se resuelve con `services/crudCatalogo.js` en cinco líneas.

4. **Validación** en `services/validacion.js`.

5. **Registrar en `app.js`:**

```js
app.use('/editoriales', require('./src/modules/editoriales/editoriales.routes'));
```

Sigue el patrón del módulo vecino más parecido en vez de introducir estructuras
nuevas.

---

## Cliente de escritorio en Electron

`apps/electron-app/` es una aplicación de escritorio que consume el catálogo
**exclusivamente en XML** desde el microservicio (`/books?format=xml`) y lo
muestra en tarjetas Material Design con portada, título, autores, ISBN y precio:
6 por página, con paginación.

```bash
cd apps/electron-app
npm install
npm start
```

Tres detalles de diseño que conviene conocer antes de tocarla:

- **La petición HTTP vive en el proceso principal**, no en la ventana. Con la
  página cargada por `file://`, el microservicio bloquearía el `fetch` por CORS;
  el XML viaja al renderer por IPC y allí se parsea con `DOMParser`.
- **Sólo XML.** Se pide con `Accept: application/xml` y con `?format=xml`
  forzado en la URL; si la respuesta no es XML, se rechaza con un mensaje en vez
  de intentar interpretarla.
- **La configuración del servicio (IP, puerto y endpoint) se edita desde un
  popup y se persiste en `localStorage`.** El XML sólo trae el nombre del
  archivo de la portada, así que el popup incluye además la ruta pública que las
  sirve; por defecto `http://<IP>/library/uploads`, que es donde el monolito las
  publica en la VM.

Los pasos completos de instalación —incluido cómo instalar Node.js en una
máquina limpia— están en
[apps/electron-app/README.md](apps/electron-app/README.md).

---

## Documentación del ejercicio

| Documento | Contenido |
|---|---|
| [docs/TECHNICAL_REPORT.md](docs/TECHNICAL_REPORT.md) | Reporte técnico completo |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | Requisitos funcionales y no funcionales, actores, riesgos |
| [docs/ENGINEERING_DECISIONS.md](docs/ENGINEERING_DECISIONS.md) | 13 decisiones con alternativas y condición de reversa |
| [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) | Controles, hallazgos y riesgos residuales |
| [docs/TEST_PLAN.md](docs/TEST_PLAN.md) | Matriz de pruebas y cobertura |
| [docs/GCP_COMMANDS.md](docs/GCP_COMMANDS.md) | Infraestructura, PostgreSQL y despliegue |
| [docs/NORMALIZATION_4FN.xlsx](docs/NORMALIZATION_4FN.xlsx) | Normalización paso a paso hasta 4FN |
| [docs/ARCHITECTURE_MONOLITHIC.png](docs/ARCHITECTURE_MONOLITHIC.png) | Diagrama de macro-arquitectura |
| [docs/DB_DESIGN_ER_4FN.png](docs/DB_DESIGN_ER_4FN.png) | Diagrama entidad-relación |
| [docs/evidencias/](docs/evidencias/) | Salidas de las pruebas ejecutadas |
