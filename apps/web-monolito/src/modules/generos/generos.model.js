// SQL del catálogo de géneros.
const db = require('../../../config/db');

// El conteo de libros permite avisar en la interfaz antes de intentar un
// borrado que la FK va a rechazar (ON DELETE RESTRICT).
async function getAll() {
    const { rows } = await db.query(`
        SELECT g.*, count(lg.libro_id)::int AS libros
        FROM generos g
        LEFT JOIN libros_generos lg ON lg.genero_id = g.id
        GROUP BY g.id
        ORDER BY g.nombre`);
    return rows;
}

async function getById(id) {
    const { rows } = await db.query('SELECT * FROM generos WHERE id = $1', [id]);
    return rows[0] || null;
}

async function create({ nombre, descripcion }) {
    const { rows } = await db.query(
        'INSERT INTO generos (nombre, descripcion) VALUES ($1,$2) RETURNING id',
        [nombre, descripcion]);
    return rows[0].id;
}

async function update(id, { nombre, descripcion }) {
    const { rowCount } = await db.query(
        'UPDATE generos SET nombre=$1, descripcion=$2 WHERE id=$3',
        [nombre, descripcion, id]);
    return rowCount;
}

async function remove(id) {
    const { rowCount } = await db.query('DELETE FROM generos WHERE id=$1', [id]);
    return rowCount;
}

module.exports = { getAll, getById, create, update, remove };
