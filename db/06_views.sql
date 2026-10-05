-- =============================================================================
-- 06_views.sql
-- Vistas de lectura.
--
--     psql -U libreria_owner -d libreria_db -f db/06_views.sql
--
-- Las vistas existen para que la consulta de catalogo (la mas usada y la mas
-- facil de escribir mal) este definida UNA vez. Los modelos de la aplicacion
-- leen de aqui en lugar de repetir los LATERAL de 03_all_quieries.
-- Son de solo lectura: toda escritura pasa por tablas o por 04.
-- =============================================================================

DROP VIEW IF EXISTS v_inventario_por_categoria CASCADE;
DROP VIEW IF EXISTS v_libros_conceptos         CASCADE;
DROP VIEW IF EXISTS v_catalogo                 CASCADE;
DROP VIEW IF EXISTS v_libros_detalle           CASCADE;

-- -----------------------------------------------------------------------------
-- v_libros_detalle
-- Un renglon por libro, con autores y generos ya agregados en texto y con la
-- portada resuelta. Se usan subconsultas LATERAL en lugar de JOIN + GROUP BY:
-- unir libros_autores y libros_generos a la vez multiplicaria las filas
-- (producto cartesiano de dos DMV independientes) y los conteos saldrian mal.
-- Ese producto cartesiano es exactamente lo que 4FN evita en el diseno; aqui
-- se evita tambien en la consulta.
-- -----------------------------------------------------------------------------
CREATE VIEW v_libros_detalle AS
SELECT
    l.id,
    l.isbn,
    l.titulo,
    l.anio_publicacion,
    l.sinopsis,
    l.precio,
    l.stock,
    l.creado_en,
    l.actualizado_en,
    l.categoria_id,
    c.nombre AS categoria,
    l.formato_id,
    f.nombre AS formato,
    coalesce(aut.autores, '')          AS autores,
    coalesce(gen.generos, '')          AS generos,
    coalesce(cnt.conceptos, 0)         AS total_conceptos,
    coalesce(imgs.total_imagenes, 0)   AS total_imagenes,
    img.nombre_archivo                 AS portada,
    img.texto_alternativo              AS portada_alt
FROM libros l
JOIN categorias c ON c.id = l.categoria_id
JOIN formatos   f ON f.id = l.formato_id
LEFT JOIN LATERAL (
    SELECT string_agg(a.nombre, ', ' ORDER BY la.orden)::text AS autores
    FROM libros_autores la JOIN autores a ON a.id = la.autor_id
    WHERE la.libro_id = l.id
) aut ON TRUE
LEFT JOIN LATERAL (
    SELECT string_agg(g.nombre, ', ' ORDER BY g.nombre)::text AS generos
    FROM libros_generos lg JOIN generos g ON g.id = lg.genero_id
    WHERE lg.libro_id = l.id
) gen ON TRUE
LEFT JOIN LATERAL (
    SELECT count(*)::int AS conceptos
    FROM libros_conceptos lc WHERE lc.libro_id = l.id
) cnt ON TRUE
LEFT JOIN LATERAL (
    SELECT count(*)::int AS total_imagenes
    FROM imagenes_libros i WHERE i.libro_id = l.id
) imgs ON TRUE
LEFT JOIN LATERAL (
    SELECT i.nombre_archivo, i.texto_alternativo
    FROM imagenes_libros i
    WHERE i.libro_id = l.id
    ORDER BY i.es_portada DESC, i.id
    LIMIT 1
) img ON TRUE;

COMMENT ON VIEW v_libros_detalle IS
    'Un renglon por libro con autores, generos, conteos y portada resueltos.';

-- -----------------------------------------------------------------------------
-- v_catalogo
-- Lo que ve un Usuario Registrado: sin campos de gestion interna.
-- No expone creado_en/actualizado_en ni los id de catalogo.
-- -----------------------------------------------------------------------------
CREATE VIEW v_catalogo AS
SELECT id, isbn, titulo, anio_publicacion, sinopsis, precio,
       (stock > 0) AS disponible,
       categoria, formato, autores, generos, portada, portada_alt
FROM v_libros_detalle;

COMMENT ON VIEW v_catalogo IS
    'Proyeccion para el lector: sustituye el stock exacto por un booleano.';

-- -----------------------------------------------------------------------------
-- v_libros_conceptos
-- Glosario aplanado libro-termino-definicion. Deja a la vista que la definicion
-- pertenece al par y no al termino.
-- -----------------------------------------------------------------------------
CREATE VIEW v_libros_conceptos AS
SELECT lc.libro_id, l.titulo AS libro, l.isbn,
       co.id AS concepto_id, co.termino,
       lc.definicion, lc.capitulo, lc.pagina
FROM libros_conceptos lc
JOIN conceptos co ON co.id = lc.concepto_id
JOIN libros    l  ON l.id  = lc.libro_id;

COMMENT ON VIEW v_libros_conceptos IS
    'Glosario por libro: el mismo termino puede tener definicion distinta en cada uno.';

-- -----------------------------------------------------------------------------
-- v_inventario_por_categoria
-- Resumen para el panel del Administrador.
-- -----------------------------------------------------------------------------
CREATE VIEW v_inventario_por_categoria AS
SELECT c.id AS categoria_id,
       c.nombre AS categoria,
       count(l.id)::int                        AS titulos,
       coalesce(sum(l.stock), 0)::int          AS ejemplares,
       coalesce(round(avg(l.precio), 2), 0)    AS precio_promedio,
       coalesce(sum(l.precio * l.stock), 0)    AS valor_inventario
FROM categorias c
LEFT JOIN libros l ON l.categoria_id = c.id
GROUP BY c.id, c.nombre;

COMMENT ON VIEW v_inventario_por_categoria IS
    'Titulos, ejemplares y valor de inventario agrupados por categoria.';

-- El GRANT sólo se aplica si el rol de aplicación ya existe. Así este script
-- se puede ejecutar tanto en una instalación nueva (donde 00_create_database.sql
-- ya creó libreria_app) como sobre una base que todavía usa el usuario anterior,
-- sin abortar por un rol inexistente.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'libreria_app') THEN
        GRANT SELECT ON v_libros_detalle, v_catalogo,
                        v_libros_conceptos, v_inventario_por_categoria
            TO libreria_app;
        RAISE NOTICE 'Permisos de lectura otorgados a libreria_app.';
    ELSE
        RAISE NOTICE 'El rol libreria_app no existe todavia: se omite el GRANT. '
                     'Crealo con db/00_create_database.sql o con el archivo de '
                     'db/pending/ correspondiente.';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Vista: total y pagado de cada pedido (derivados, nunca almacenados)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_pedidos_total AS
SELECT p.id,
       p.usuario_id,
       ep.nombre AS estado,
       p.creado_en,
       COALESCE(l.total, 0)  AS total,
       COALESCE(g.pagado, 0) AS pagado
FROM pedidos p
JOIN estados_pedido ep ON ep.id = p.estado_id
LEFT JOIN (SELECT pedido_id, SUM(cantidad * precio_unitario) AS total
           FROM pedidos_lineas GROUP BY pedido_id) l ON l.pedido_id = p.id
LEFT JOIN (SELECT pg.pedido_id, SUM(pg.monto) AS pagado
           FROM pagos pg
           JOIN estados_pago es ON es.id = pg.estado_pago_id
           WHERE es.nombre = 'aprobado'
           GROUP BY pg.pedido_id) g ON g.pedido_id = p.id;


-- Inventario de vistas creadas y conteo de filas de control.
SELECT table_name FROM information_schema.views
WHERE table_schema = 'public' ORDER BY 1;

SELECT (SELECT count(*) FROM v_libros_detalle)           AS libros_detalle,
       (SELECT count(*) FROM v_catalogo)                 AS catalogo,
       (SELECT count(*) FROM v_libros_conceptos)         AS libros_conceptos,
       (SELECT count(*) FROM v_inventario_por_categoria) AS inventario;
