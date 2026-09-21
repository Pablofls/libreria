// SQL del catálogo de formatos (pasta dura, EPUB, audiolibro…).
const db = require('../../../config/db');

async function getAll() {
    const { rows } = await db.query(`
        SELECT f.*, count(l.id)::int AS libros
        FROM formatos f
        LEFT JOIN libros l ON l.formato_id = f.id
        GROUP BY f.id
        ORDER BY f.nombre`);
    return rows;
}

async function getById(id) {
    const { rows } = await db.query('SELECT * FROM formatos WHERE id = $1', [id]);
    return rows[0] || null;
}

async function create({ nombre, descripcion }) {
    const { rows } = await db.query(
        'INSERT INTO formatos (nombre, descripcion) VALUES ($1,$2) RETURNING id',
        [nombre, descripcion]);
    return rows[0].id;
}

async function update(id, { nombre, descripcion }) {
    const { rowCount } = await db.query(
        'UPDATE formatos SET nombre=$1, descripcion=$2 WHERE id=$3',
        [nombre, descripcion, id]);
    return rowCount;
}

async function remove(id) {
    const { rowCount } = await db.query('DELETE FROM formatos WHERE id=$1', [id]);
    return rowCount;
}

module.exports = { getAll, getById, create, update, remove };
