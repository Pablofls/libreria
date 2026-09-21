// SQL de conceptos. Dos niveles:
//   - `conceptos`         : catálogo de términos (CRUD propio, /conceptos)
//   - `libros_conceptos`  : la definición que un libro concreto da a un término
const db = require('../../../config/db');

async function getAll() {
    const { rows } = await db.query(`
        SELECT c.*, count(lc.libro_id)::int AS libros
        FROM conceptos c
        LEFT JOIN libros_conceptos lc ON lc.concepto_id = c.id
        GROUP BY c.id
        ORDER BY c.termino`);
    return rows;
}

async function getById(id) {
    const { rows } = await db.query('SELECT * FROM conceptos WHERE id = $1', [id]);
    return rows[0] || null;
}

// Todas las definiciones de un término. Es la evidencia de por qué la
// definición no puede vivir en el catálogo: cambia según el libro.
async function getDefiniciones(conceptoId) {
    const { rows } = await db.query(`
        SELECT libro_id, libro, isbn, definicion, capitulo, pagina
        FROM v_libros_conceptos WHERE concepto_id = $1 ORDER BY libro`, [conceptoId]);
    return rows;
}

async function create({ nombre }) {
    const { rows } = await db.query(
        'INSERT INTO conceptos (termino) VALUES ($1) RETURNING id', [nombre]);
    return rows[0].id;
}

async function update(id, { nombre }) {
    const { rowCount } = await db.query(
        'UPDATE conceptos SET termino=$1 WHERE id=$2', [nombre, id]);
    return rowCount;
}

async function remove(id) {
    const { rowCount } = await db.query('DELETE FROM conceptos WHERE id=$1', [id]);
    return rowCount;
}

// --- Relación libro ↔ concepto ----------------------------------------------

// sp_guardar_concepto_libro crea el término si no existe y lo reutiliza si sí,
// en una sola sentencia (sin condición de carrera entre SELECT e INSERT).
async function guardarEnLibro(libroId, { termino, definicion, capitulo, pagina }) {
    const { rows } = await db.query(
        'SELECT sp_guardar_concepto_libro($1,$2,$3,$4,$5) AS concepto_id',
        [libroId, termino, definicion, capitulo, pagina]);
    return rows[0].concepto_id;
}

async function getDeLibro(libroId, conceptoId) {
    const { rows } = await db.query(
        `SELECT * FROM v_libros_conceptos WHERE libro_id = $1 AND concepto_id = $2`,
        [libroId, conceptoId]);
    return rows[0] || null;
}

async function quitarDeLibro(libroId, conceptoId) {
    const { rowCount } = await db.query(
        'DELETE FROM libros_conceptos WHERE libro_id=$1 AND concepto_id=$2',
        [libroId, conceptoId]);
    return rowCount;
}

module.exports = {
    getAll, getById, getDefiniciones, create, update, remove,
    guardarEnLibro, getDeLibro, quitarDeLibro
};
