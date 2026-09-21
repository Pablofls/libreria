// SQL del panel del Administrador: sólo lecturas agregadas.
const db = require('../../../config/db');

async function resumen() {
    const { rows } = await db.query(`
        SELECT
          (SELECT count(*)::int FROM libros)           AS libros,
          (SELECT count(*)::int FROM autores)          AS autores,
          (SELECT count(*)::int FROM generos)          AS generos,
          (SELECT count(*)::int FROM categorias)       AS categorias,
          (SELECT count(*)::int FROM formatos)         AS formatos,
          (SELECT count(*)::int FROM conceptos)        AS conceptos,
          (SELECT count(*)::int FROM imagenes_libros)  AS imagenes,
          (SELECT count(*)::int FROM usuarios)         AS usuarios,
          (SELECT count(*)::int FROM usuarios WHERE rol='admin') AS administradores,
          (SELECT coalesce(sum(stock),0)::int FROM libros)       AS ejemplares,
          (SELECT count(*)::int FROM libros WHERE stock = 0)     AS sin_existencias`);
    return rows[0];
}

async function inventario() {
    const { rows } = await db.query(`
        SELECT * FROM v_inventario_por_categoria
        WHERE titulos > 0 ORDER BY titulos DESC, categoria`);
    return rows;
}

// Control de calidad de datos: libros a los que les falta algo.
async function pendientes() {
    const { rows } = await db.query(`
        SELECT id, titulo,
               (total_imagenes = 0)  AS sin_imagen,
               (generos = '')        AS sin_genero,
               (total_conceptos = 0) AS sin_conceptos
        FROM v_libros_detalle
        WHERE total_imagenes = 0 OR generos = '' OR total_conceptos = 0
        ORDER BY titulo LIMIT 15`);
    return rows;
}

module.exports = { resumen, inventario, pendientes };
