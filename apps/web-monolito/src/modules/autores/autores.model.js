// SQL de autores.
const db = require('../../../config/db');

async function getAll() {
    const { rows } = await db.query(`
        SELECT a.*, count(la.libro_id)::int AS libros
        FROM autores a
        LEFT JOIN libros_autores la ON la.autor_id = a.id
        GROUP BY a.id
        ORDER BY a.nombre`);
    return rows;
}

async function getById(id) {
    const { rows } = await db.query('SELECT * FROM autores WHERE id = $1', [id]);
    return rows[0] || null;
}

// Libros en los que participa un autor: se muestra al intentar borrarlo, para
// que el mensaje diga por qué la BD lo va a impedir.
async function getLibros(id) {
    const { rows } = await db.query(`
        SELECT l.id, l.titulo
        FROM libros_autores la JOIN libros l ON l.id = la.libro_id
        WHERE la.autor_id = $1 ORDER BY l.titulo`, [id]);
    return rows;
}

async function create({ nombre, biografia, nacionalidad }) {
    const { rows } = await db.query(
        'INSERT INTO autores (nombre, biografia, nacionalidad) VALUES ($1,$2,$3) RETURNING id',
        [nombre, biografia, nacionalidad]);
    return rows[0].id;
}

async function update(id, { nombre, biografia, nacionalidad }) {
    const { rowCount } = await db.query(
        'UPDATE autores SET nombre=$1, biografia=$2, nacionalidad=$3 WHERE id=$4',
        [nombre, biografia, nacionalidad, id]);
    return rowCount;
}

async function remove(id) {
    const { rowCount } = await db.query('DELETE FROM autores WHERE id=$1', [id]);
    return rowCount;
}

module.exports = { getAll, getById, getLibros, create, update, remove };
