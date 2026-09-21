// SQL de imágenes. Guarda metadatos y el nombre de archivo generado por el
// servidor; nunca una ruta absoluta del sistema de archivos de la VM.
const db = require('../../../config/db');

async function getById(id) {
    const { rows } = await db.query('SELECT * FROM imagenes_libros WHERE id = $1', [id]);
    return rows[0] || null;
}

async function create(libroId, archivo, { texto_alternativo, es_portada }) {
    // Si es la primera imagen del libro, se marca portada automáticamente:
    // un libro con imágenes pero sin portada no tiene sentido en el catálogo.
    const { rows: previas } = await db.query(
        'SELECT count(*)::int AS n FROM imagenes_libros WHERE libro_id = $1', [libroId]);
    const portada = es_portada || previas[0].n === 0;

    const { rows } = await db.query(
        `INSERT INTO imagenes_libros
             (libro_id, nombre_archivo, nombre_original, tipo_mime,
              tamano_bytes, texto_alternativo, es_portada)
         VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id`,
        [libroId, archivo.filename, archivo.originalname, archivo.mimetype,
         archivo.size, texto_alternativo, portada]);
    return rows[0].id;
}

// El trigger trg_portada_unica apaga la portada anterior.
async function marcarPortada(id) {
    const { rows } = await db.query('SELECT sp_marcar_portada($1) AS libro_id', [id]);
    return rows[0].libro_id;
}

async function actualizarAlt(id, texto_alternativo) {
    const { rows } = await db.query(
        'UPDATE imagenes_libros SET texto_alternativo=$1 WHERE id=$2 RETURNING libro_id',
        [texto_alternativo, id]);
    return rows[0] || null;
}

// Devuelve el nombre del archivo para que el controller lo borre del disco.
// El trigger trg_promover_portada asciende otra imagen si esta era la portada.
async function remove(id) {
    const { rows } = await db.query(
        'DELETE FROM imagenes_libros WHERE id=$1 RETURNING libro_id, nombre_archivo', [id]);
    return rows[0] || null;
}

module.exports = { getById, create, marcarPortada, actualizarAlt, remove };
