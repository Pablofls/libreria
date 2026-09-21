-- =============================================================================
-- 20260830-rediseno-4fn.sql
--
-- QUÉ HACE
-- Reemplaza por completo el esquema anterior por el modelo normalizado hasta
-- 4FN, y carga los datos de prueba, los procedimientos, los disparadores y las
-- vistas nuevos. Es un envoltorio que ejecuta los seis scripts canónicos de
-- db/ en el orden que exige el ejercicio.
--
-- POR QUÉ
-- El esquema anterior no estaba en 4FN: `libros` tenía `autor_id` y
-- `categoria_id` como claves foráneas simples, así que un libro sólo podía
-- tener UN autor y UN género. El ejercicio pide varios autores y varios géneros
-- por libro, catálogos independientes de formato y categoría, precio, y que la
-- definición de un concepto pertenezca a la relación libro-concepto y no al
-- término. Nada de eso se puede expresar sobre las tablas anteriores.
--
-- Faltaban además: la defensa en base de datos de "un solo Administrador", los
-- metadatos de las imágenes (MIME, tamaño, texto alternativo) y las
-- restricciones de integridad (ISBN obligatorio y único, precio y stock no
-- negativos).
--
-- ⚠ ES DESTRUCTIVO
-- db/01_schema.sql hace DROP de todas las tablas antes de crearlas. Se pierden
-- los datos actuales de la VM. Se eligió recrear en vez de migrar con ALTER
-- porque los datos existentes son de demostración, y porque así el resultado es
-- idéntico a db/01_schema.sql: no quedan dos versiones del esquema que
-- mantener sincronizadas.
--
-- RESPALDA ANTES, si quieres conservar algo:
--     pg_dump -U libreria_owner -h 127.0.0.1 libreria_db \
--       | gzip > ~/libreria-antes-de-4fn-$(date +%F).sql.gz
--
-- CÓMO EJECUTARLO EN LA VM
--     cd /opt/libreria
--     psql -U libreria_owner -h 127.0.0.1 -d libreria_db -f db/pending/20260830-rediseno-4fn.sql
--
-- Si los roles libreria_app / libreria_owner todavía no existen, primero:
--     sudo -u postgres psql -f db/00_create_database.sql
--
-- Y después copia las portadas de los datos de prueba al directorio de subidas:
--     cp db/seed_uploads/*.png uploads/
--
-- Las contraseñas de los usuarios sembrados NO están en el repositorio, ni en
-- claro ni en comentarios: sólo el hash bcrypt. Los valores se comunican fuera
-- de git.
--
-- QUÉ CAMBIA RESPECTO AL ESQUEMA ANTERIOR
--     libros.autor_id                 → libros_autores (N:M, con `orden`)
--     (no existía)                    → libros_generos (N:M) + catálogo generos
--     (no existía)                    → catálogo formatos + libros.formato_id
--     (no existía)                    → libros.precio
--     libros.categoria_id             → se conserva, ahora NOT NULL y RESTRICT
--     conceptos.libro_id/definicion   → conceptos (catálogo) + libros_conceptos
--     imagenes_libros.ruta_archivo    → nombre_archivo + nombre_original,
--                                        tipo_mime, tamano_bytes,
--                                        texto_alternativo, es_portada
--     usuarios                        → + activo, CHECK de rol, CHECK de forma
--                                        bcrypt, índice único parcial de admin
-- =============================================================================

\set ON_ERROR_STOP on
\echo '>>> Reconstruyendo el esquema en 4FN. Esto BORRA los datos actuales.'

\i db/01_schema.sql
\i db/02_seed_30_per_table.sql
\i db/03_all_quieries_before_stored_procedures.sql
\i db/04_stored_procedures.sql
\i db/05_triggers.sql
\i db/06_views.sql

\echo '>>> Listo. Verificación:'

SELECT 'usuarios' AS tabla, count(*) FROM usuarios
UNION ALL SELECT 'autores', count(*) FROM autores
UNION ALL SELECT 'generos', count(*) FROM generos
UNION ALL SELECT 'categorias', count(*) FROM categorias
UNION ALL SELECT 'formatos', count(*) FROM formatos
UNION ALL SELECT 'conceptos', count(*) FROM conceptos
UNION ALL SELECT 'libros', count(*) FROM libros
UNION ALL SELECT 'imagenes_libros', count(*) FROM imagenes_libros
UNION ALL SELECT 'libros_autores', count(*) FROM libros_autores
UNION ALL SELECT 'libros_generos', count(*) FROM libros_generos
UNION ALL SELECT 'libros_conceptos', count(*) FROM libros_conceptos
ORDER BY 1;

-- Debe devolver exactamente una fila, con count = 1.
SELECT rol, count(*) AS usuarios FROM usuarios WHERE rol = 'admin' GROUP BY rol;
