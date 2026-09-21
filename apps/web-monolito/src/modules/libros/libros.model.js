// Todo el SQL de libros. Sin HTML, sin req/res.
// Cada valor que viene del usuario viaja como parámetro ($1, $2…); nunca se
// concatena en la cadena de la consulta.
const db = require('../../../config/db');

// Lee de la vista v_libros_detalle (06_views.sql): autores, géneros y portada
// ya vienen resueltos, sin repetir aquí los LATERAL.
async function getAll() {
    const { rows } = await db.query('SELECT * FROM v_libros_detalle ORDER BY titulo');
    return rows;
}

// Búsqueda por ISBN, título o autor (RF-05). La regla vive en la función
// almacenada fn_buscar_libros, así que la interfaz y psql buscan igual.
async function buscar(texto) {
    const { rows } = await db.query('SELECT * FROM fn_buscar_libros($1)', [texto]);
    return rows;
}

async function getById(id) {
    const { rows } = await db.query('SELECT * FROM v_libros_detalle WHERE id = $1', [id]);
    return rows[0] || null;
}

async function getAutores(libroId) {
    const { rows } = await db.query(`
        SELECT a.id, a.nombre, a.nacionalidad, la.orden
        FROM libros_autores la
        JOIN autores a ON a.id = la.autor_id
        WHERE la.libro_id = $1
        ORDER BY la.orden, a.nombre`, [libroId]);
    return rows;
}

async function getGeneros(libroId) {
    const { rows } = await db.query(`
        SELECT g.id, g.nombre
        FROM libros_generos lg
        JOIN generos g ON g.id = lg.genero_id
        WHERE lg.libro_id = $1
        ORDER BY g.nombre`, [libroId]);
    return rows;
}

async function getImagenes(libroId) {
    const { rows } = await db.query(`
        SELECT id, nombre_archivo, nombre_original, tipo_mime, tamano_bytes,
               texto_alternativo, es_portada
        FROM imagenes_libros
        WHERE libro_id = $1
        ORDER BY es_portada DESC, id`, [libroId]);
    return rows;
}

async function getConceptos(libroId) {
    const { rows } = await db.query(`
        SELECT concepto_id, termino, definicion, capitulo, pagina
        FROM v_libros_conceptos
        WHERE libro_id = $1
        ORDER BY termino`, [libroId]);
    return rows;
}

// Alta y actualización pasan por sp_guardar_libro (04_stored_procedures.sql):
// el libro y sus vínculos N:M se escriben en una sola transacción, así que no
// puede quedar un libro sin autores si algo falla a medias.
async function guardar(id, d) {
    const { rows } = await db.query(
        'SELECT sp_guardar_libro($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) AS id',
        [id, d.isbn, d.titulo, d.anio_publicacion, d.sinopsis, d.precio,
         d.stock, d.categoria_id, d.formato_id, d.autores, d.generos]
    );
    return rows[0].id;
}

async function ajustarStock(id, delta) {
    const { rows } = await db.query('SELECT sp_ajustar_stock($1,$2) AS stock', [id, delta]);
    return rows[0].stock;
}

// Devuelve los nombres de archivo para poder borrarlos del disco: el ON DELETE
// CASCADE limpia la BD, pero no toca el sistema de archivos.
async function remove(id) {
    const { rows } = await db.query(
        'SELECT nombre_archivo FROM imagenes_libros WHERE libro_id = $1', [id]);
    await db.query('DELETE FROM libros WHERE id = $1', [id]);
    return rows.map(r => r.nombre_archivo);
}

module.exports = {
    getAll, buscar, getById, getAutores, getGeneros, getImagenes,
    getConceptos, guardar, ajustarStock, remove
};
