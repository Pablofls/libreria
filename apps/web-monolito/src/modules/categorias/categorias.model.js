// SQL del catálogo de categorías comerciales.
const db = require('../../../config/db');

async function getAll() {
    const { rows } = await db.query(`
        SELECT c.*, count(l.id)::int AS libros
        FROM categorias c
        LEFT JOIN libros l ON l.categoria_id = c.id
        GROUP BY c.id
        ORDER BY c.nombre`);
    return rows;
}

async function getById(id) {
    const { rows } = await db.query('SELECT * FROM categorias WHERE id = $1', [id]);
    return rows[0] || null;
}

async function create({ nombre, descripcion }) {
    const { rows } = await db.query(
        'INSERT INTO categorias (nombre, descripcion) VALUES ($1,$2) RETURNING id',
        [nombre, descripcion]);
    return rows[0].id;
}

async function update(id, { nombre, descripcion }) {
    const { rowCount } = await db.query(
        'UPDATE categorias SET nombre=$1, descripcion=$2 WHERE id=$3',
        [nombre, descripcion, id]);
    return rowCount;
}

async function remove(id) {
    const { rowCount } = await db.query('DELETE FROM categorias WHERE id=$1', [id]);
    return rowCount;
}

module.exports = { getAll, getById, create, update, remove };
