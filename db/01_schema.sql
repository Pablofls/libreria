-- =============================================================================
-- 01_schema.sql
-- Esquema normalizado hasta 4FN de la Librería Online.
--
-- Se ejecuta como libreria_owner sobre libreria_db:
--     psql -U libreria_owner -d libreria_db -f db/01_schema.sql
--
-- Orden: catálogos → entidad central (libros) → tablas puente → dependientes.
-- Cada tabla documenta por qué tiene su PK, sus FK y sus restricciones.
-- Las acciones ON DELETE/ON UPDATE se declaran SOLO donde tienen sentido de
-- negocio; el resto se deja en NO ACTION para que la BD frene el borrado.
-- =============================================================================

BEGIN;

DROP VIEW  IF EXISTS v_inventario_por_categoria CASCADE;
DROP VIEW  IF EXISTS v_libros_conceptos         CASCADE;
DROP VIEW  IF EXISTS v_catalogo                 CASCADE;
DROP VIEW  IF EXISTS v_libros_detalle           CASCADE;

DROP TABLE IF EXISTS libros_conceptos  CASCADE;
DROP TABLE IF EXISTS libros_generos    CASCADE;
DROP TABLE IF EXISTS libros_autores    CASCADE;
DROP TABLE IF EXISTS imagenes_libros   CASCADE;
DROP TABLE IF EXISTS conceptos         CASCADE;
DROP TABLE IF EXISTS libros            CASCADE;
DROP TABLE IF EXISTS formatos          CASCADE;
DROP TABLE IF EXISTS categorias        CASCADE;
DROP TABLE IF EXISTS generos           CASCADE;
DROP TABLE IF EXISTS autores           CASCADE;
DROP TABLE IF EXISTS usuarios          CASCADE;

-- -----------------------------------------------------------------------------
-- usuarios
-- PK: id sustituto (SERIAL). Clave candidata natural: email.
-- UNIQUE(email): el login busca por correo; dos cuentas con el mismo correo
--   harían ambiguo el inicio de sesión.
-- CHECK(rol): la aplicación solo entiende dos roles. "Visitante" NO es un rol
--   almacenado: es la ausencia de sesión, por eso no aparece aquí.
-- CHECK(email): validación mínima de formato, además de la del servidor.
-- La regla de "un solo Administrador" se implementa más abajo con un índice
--   único parcial + un trigger (05_triggers.sql). Ver ux_usuarios_admin_unico.
-- -----------------------------------------------------------------------------
CREATE TABLE usuarios (
    id             SERIAL       PRIMARY KEY,
    nombre         VARCHAR(100) NOT NULL,
    email          VARCHAR(150) NOT NULL,
    password_hash  TEXT         NOT NULL,
    rol            VARCHAR(20)  NOT NULL DEFAULT 'lector',
    activo         BOOLEAN      NOT NULL DEFAULT TRUE,
    creado_en      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_usuarios_email      UNIQUE (email),
    CONSTRAINT ck_usuarios_rol        CHECK (rol IN ('lector', 'admin')),
    CONSTRAINT ck_usuarios_email      CHECK (email ~* '^[^@[:space:]]+@[^@[:space:]]+\.[a-z]{2,}$'),
    CONSTRAINT ck_usuarios_nombre     CHECK (btrim(nombre) <> ''),
    -- Un hash bcrypt siempre empieza con $2a$/$2b$/$2y$ y mide 60 caracteres.
    -- Esta restricción impide, a nivel de BD, guardar una contraseña en claro.
    CONSTRAINT ck_usuarios_hash_bcrypt CHECK (password_hash ~ '^\$2[aby]\$\d{2}\$.{53}$')
);

-- Defensa en base de datos de "como máximo un Administrador".
-- Índice único parcial: solo indexa las filas con rol='admin', así que permite
-- N lectores pero una única fila admin. Es la defensa dura (no se puede evadir
-- ni con un INSERT concurrente); el trigger de 05_triggers.sql solo añade un
-- mensaje de error legible.
CREATE UNIQUE INDEX ux_usuarios_admin_unico
    ON usuarios ((rol)) WHERE rol = 'admin';

CREATE INDEX ix_usuarios_email ON usuarios (lower(email));

-- -----------------------------------------------------------------------------
-- autores
-- UNIQUE(nombre, nacionalidad): evita duplicar el mismo autor al capturarlo dos
--   veces. No se usa el nombre solo como PK porque puede repetirse entre países
--   y porque un nombre es un dato editable (mala clave primaria).
-- -----------------------------------------------------------------------------
CREATE TABLE autores (
    id           SERIAL       PRIMARY KEY,
    nombre       VARCHAR(120) NOT NULL,
    biografia    TEXT,
    nacionalidad VARCHAR(80),

    CONSTRAINT uq_autores_nombre  UNIQUE (nombre, nacionalidad),
    CONSTRAINT ck_autores_nombre  CHECK (btrim(nombre) <> '')
);

-- -----------------------------------------------------------------------------
-- generos  (catálogo independiente)
-- Un libro puede pertenecer a varios géneros → la relación vive en
-- libros_generos, nunca como columna repetitiva dentro de libros.
-- -----------------------------------------------------------------------------
CREATE TABLE generos (
    id          SERIAL      PRIMARY KEY,
    nombre      VARCHAR(80) NOT NULL,
    descripcion TEXT,

    CONSTRAINT uq_generos_nombre UNIQUE (nombre),
    CONSTRAINT ck_generos_nombre CHECK (btrim(nombre) <> '')
);

-- -----------------------------------------------------------------------------
-- categorias  (catálogo independiente)
-- Clasificación comercial del libro (Computación, Infantil, Universitario…).
-- Un libro tiene exactamente una categoría → FK simple en libros, no tabla puente.
-- -----------------------------------------------------------------------------
CREATE TABLE categorias (
    id          SERIAL      PRIMARY KEY,
    nombre      VARCHAR(80) NOT NULL,
    descripcion TEXT,

    CONSTRAINT uq_categorias_nombre UNIQUE (nombre),
    CONSTRAINT ck_categorias_nombre CHECK (btrim(nombre) <> '')
);

-- -----------------------------------------------------------------------------
-- formatos  (catálogo independiente)
-- Pasta dura, rústica, EPUB, PDF, audiolibro… Un ejemplar tiene un formato.
-- -----------------------------------------------------------------------------
CREATE TABLE formatos (
    id          SERIAL      PRIMARY KEY,
    nombre      VARCHAR(60) NOT NULL,
    descripcion TEXT,

    CONSTRAINT uq_formatos_nombre UNIQUE (nombre),
    CONSTRAINT ck_formatos_nombre CHECK (btrim(nombre) <> '')
);

-- -----------------------------------------------------------------------------
-- libros  (entidad central)
-- PK: id sustituto. Clave candidata natural: isbn.
-- UNIQUE(isbn): un ISBN identifica una edición concreta en todo el mundo; dos
--   filas con el mismo ISBN serían el mismo libro capturado dos veces.
-- CHECK(precio >= 0) y CHECK(stock >= 0): reglas de negocio que no deben
--   depender de que la aplicación se acuerde de validarlas.
-- CHECK(anio_publicacion): descarta capturas absurdas (año 0, año 3000).
-- FK categoria_id / formato_id: ON DELETE RESTRICT (implícito, NO ACTION). Se
--   deja así a propósito: borrar una categoría que tiene libros debe fallar, no
--   dejar libros huérfanos en silencio. ON UPDATE CASCADE porque las PK son
--   SERIAL y no cambian, pero si alguna vez se renumeraran, las FK siguen.
-- NO existen columnas autor_id ni genero_id: son dependencias multivaluadas y
--   viven en libros_autores / libros_generos (ver docs/NORMALIZATION_4FN.xlsx).
-- -----------------------------------------------------------------------------
CREATE TABLE libros (
    id               SERIAL        PRIMARY KEY,
    isbn             VARCHAR(17)   NOT NULL,
    titulo           VARCHAR(200)  NOT NULL,
    anio_publicacion SMALLINT,
    sinopsis         TEXT,
    precio           NUMERIC(10,2) NOT NULL DEFAULT 0,
    stock            INTEGER       NOT NULL DEFAULT 0,
    categoria_id     INTEGER       NOT NULL,
    formato_id       INTEGER       NOT NULL,
    creado_en        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    actualizado_en   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_libros_isbn      UNIQUE (isbn),
    CONSTRAINT ck_libros_titulo    CHECK (btrim(titulo) <> ''),
    -- ISBN-10 o ISBN-13, con o sin guiones. Solo dígitos, guiones y X final.
    CONSTRAINT ck_libros_isbn      CHECK (isbn ~ '^[0-9-]{10,17}[0-9X]$'),
    CONSTRAINT ck_libros_precio    CHECK (precio >= 0),
    CONSTRAINT ck_libros_stock     CHECK (stock  >= 0),
    CONSTRAINT ck_libros_anio      CHECK (anio_publicacion IS NULL
                                          OR anio_publicacion BETWEEN 1450 AND 2100),

    CONSTRAINT fk_libros_categoria FOREIGN KEY (categoria_id)
        REFERENCES categorias (id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_libros_formato   FOREIGN KEY (formato_id)
        REFERENCES formatos (id)   ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX ix_libros_titulo    ON libros (lower(titulo));
CREATE INDEX ix_libros_categoria ON libros (categoria_id);
CREATE INDEX ix_libros_formato   ON libros (formato_id);

-- -----------------------------------------------------------------------------
-- libros_autores  (tabla puente N:M)
-- PK compuesta (libro_id, autor_id): la relación misma es la clave; impide
--   registrar dos veces al mismo autor en el mismo libro.
-- orden: posición en la portada ("Autor 1, Autor 2"). Es un atributo DE LA
--   RELACIÓN, no del libro ni del autor: por eso vive aquí.
-- ON DELETE CASCADE hacia libros: al borrar un libro, sus vínculos dejan de
--   tener sentido. Hacia autores es RESTRICT: no se borra un autor que sigue
--   acreditado en un libro; primero se desvincula.
-- -----------------------------------------------------------------------------
CREATE TABLE libros_autores (
    libro_id INTEGER  NOT NULL,
    autor_id INTEGER  NOT NULL,
    orden    SMALLINT NOT NULL DEFAULT 1,

    CONSTRAINT pk_libros_autores    PRIMARY KEY (libro_id, autor_id),
    CONSTRAINT ck_libros_autores_orden CHECK (orden >= 1),
    CONSTRAINT fk_la_libro FOREIGN KEY (libro_id)
        REFERENCES libros (id)  ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_la_autor FOREIGN KEY (autor_id)
        REFERENCES autores (id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX ix_libros_autores_autor ON libros_autores (autor_id);

-- -----------------------------------------------------------------------------
-- libros_generos  (tabla puente N:M)
-- Misma lógica que libros_autores. Es la tabla que hace que el modelo esté en
-- 4FN: autores y géneros son dos DMV independientes sobre libro; guardarlas
-- juntas en una sola tabla produciría el producto cartesiano de ambas.
-- -----------------------------------------------------------------------------
CREATE TABLE libros_generos (
    libro_id  INTEGER NOT NULL,
    genero_id INTEGER NOT NULL,

    CONSTRAINT pk_libros_generos PRIMARY KEY (libro_id, genero_id),
    CONSTRAINT fk_lg_libro  FOREIGN KEY (libro_id)
        REFERENCES libros (id)  ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_lg_genero FOREIGN KEY (genero_id)
        REFERENCES generos (id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX ix_libros_generos_genero ON libros_generos (genero_id);

-- -----------------------------------------------------------------------------
-- conceptos  (catálogo independiente de términos)
-- "IaaS", "PaaS", "Bucket"… El término existe por sí mismo y puede aparecer en
-- muchos libros. Lo que cambia entre libros es la DEFINICIÓN, no el término:
-- por eso el término va aquí y la definición en libros_conceptos.
-- -----------------------------------------------------------------------------
CREATE TABLE conceptos (
    id      SERIAL       PRIMARY KEY,
    termino VARCHAR(150) NOT NULL,

    CONSTRAINT uq_conceptos_termino UNIQUE (termino),
    CONSTRAINT ck_conceptos_termino CHECK (btrim(termino) <> '')
);

-- -----------------------------------------------------------------------------
-- libros_conceptos  (tabla puente N:M con atributos propios)
-- PK compuesta (libro_id, concepto_id): un libro define un concepto una vez.
-- definicion: pertenece a la RELACIÓN libro-concepto. El mismo término
--   "Bucket" se define distinto en un libro de Cloud Computing y en uno de
--   estadística; guardar la definición en `conceptos` sería una dependencia
--   funcional mal ubicada (violación de 3FN/BCNF).
-- capitulo / pagina: referencia opcional dentro del libro.
-- -----------------------------------------------------------------------------
CREATE TABLE libros_conceptos (
    libro_id    INTEGER     NOT NULL,
    concepto_id INTEGER     NOT NULL,
    definicion  TEXT        NOT NULL,
    capitulo    VARCHAR(80),
    pagina      INTEGER,

    CONSTRAINT pk_libros_conceptos PRIMARY KEY (libro_id, concepto_id),
    CONSTRAINT ck_lc_definicion CHECK (btrim(definicion) <> ''),
    CONSTRAINT ck_lc_pagina     CHECK (pagina IS NULL OR pagina > 0),
    CONSTRAINT fk_lc_libro    FOREIGN KEY (libro_id)
        REFERENCES libros (id)    ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_lc_concepto FOREIGN KEY (concepto_id)
        REFERENCES conceptos (id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX ix_libros_conceptos_concepto ON libros_conceptos (concepto_id);

-- -----------------------------------------------------------------------------
-- imagenes_libros
-- Un libro puede tener varias imágenes → tabla propia (cuarta DMV sobre libro).
-- nombre_archivo: nombre GENERADO por el servidor (uuid + extensión). Nunca el
--   nombre que envió el usuario, que va en nombre_original solo como metadato.
--   UNIQUE porque es la ruta física dentro de uploads/.
-- tipo_mime / tamano_bytes: metadatos de la validación de subida, para poder
--   auditar qué se aceptó. CHECK sobre ambos: la BD no confía en que la
--   aplicación haya validado.
-- texto_alternativo: accesibilidad (atributo alt de la etiqueta img).
-- es_portada: solo UNA imagen por libro puede serlo → índice único parcial.
-- La tabla NO guarda rutas absolutas del servidor: solo el nombre de archivo.
--   La ruta base es configuración de la aplicación, no un dato público.
-- -----------------------------------------------------------------------------
CREATE TABLE imagenes_libros (
    id                SERIAL       PRIMARY KEY,
    libro_id          INTEGER      NOT NULL,
    nombre_archivo    VARCHAR(120) NOT NULL,
    nombre_original   VARCHAR(255),
    tipo_mime         VARCHAR(60)  NOT NULL,
    tamano_bytes      INTEGER      NOT NULL,
    texto_alternativo VARCHAR(200),
    es_portada        BOOLEAN      NOT NULL DEFAULT FALSE,
    creado_en         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_imagenes_archivo UNIQUE (nombre_archivo),
    CONSTRAINT ck_imagenes_mime    CHECK (tipo_mime IN ('image/jpeg', 'image/png', 'image/webp')),
    CONSTRAINT ck_imagenes_tamano  CHECK (tamano_bytes > 0 AND tamano_bytes <= 2097152),
    -- El nombre lo genera el servidor: uuid v4 + extensión permitida. Este CHECK
    -- impide que se cuele un nombre con rutas ("../") o con doble extensión.
    CONSTRAINT ck_imagenes_nombre  CHECK (nombre_archivo ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(jpg|png|webp)$'),
    CONSTRAINT fk_img_libro FOREIGN KEY (libro_id)
        REFERENCES libros (id) ON UPDATE CASCADE ON DELETE CASCADE
);

-- Una sola portada por libro, garantizado por la BD.
CREATE UNIQUE INDEX ux_imagenes_portada_unica
    ON imagenes_libros (libro_id) WHERE es_portada;

CREATE INDEX ix_imagenes_libro ON imagenes_libros (libro_id);

-- -----------------------------------------------------------------------------
-- Tablas del modulo SOAP: NO se definen aqui.
--
-- El modulo de clasificacion Cloud (services/library_soap_service) agrega tres
-- tablas propias a esta misma base: clasificadores, clasificaciones_cloud y
-- clientes_servidos, mas cuatro vistas, una funcion y el rol libreria_soap.
--
-- Se definen en services/library_soap_service/sql/soap_module.sql y no aqui, a
-- proposito: este archivo es el esquema del monolito y un entregable cerrado del
-- ejercicio anterior. Duplicar el DDL en dos lugares garantizaria que un dia se
-- separen. El diagrama de relaciones del README documenta ambas partes.
--
-- Ese script solo AGREGA objetos: no modifica ninguna tabla de este archivo.
-- Referencia a libros_conceptos con una clave foranea compuesta, asi que debe
-- ejecutarse despues de este.
-- -----------------------------------------------------------------------------

COMMIT;
