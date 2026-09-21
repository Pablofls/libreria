// SQL de usuarios. password_hash nunca sale de aquí hacia una vista.
const db = require('../../../config/db');
const bcrypt = require('bcrypt');
const { RONDAS } = require('../auth/auth.model');

async function getAll() {
    const { rows } = await db.query(
        `SELECT id, nombre, email, rol, activo, creado_en
         FROM usuarios ORDER BY rol, nombre`);
    return rows;
}

async function getById(id) {
    const { rows } = await db.query(
        'SELECT id, nombre, email, rol, activo FROM usuarios WHERE id = $1', [id]);
    return rows[0] || null;
}

async function contarAdmins() {
    const { rows } = await db.query("SELECT count(*)::int AS n FROM usuarios WHERE rol = 'admin'");
    return rows[0].n;
}

async function create({ nombre, email, password, rol, activo }) {
    const hash = await bcrypt.hash(password, RONDAS);
    const { rows } = await db.query(
        `INSERT INTO usuarios (nombre, email, password_hash, rol, activo)
         VALUES ($1,$2,$3,$4,$5) RETURNING id`,
        [nombre, email, hash, rol, activo]);
    return rows[0].id;
}

// Contraseña vacía en edición = "no cambiar". Se resuelve con COALESCE en una
// sola sentencia en vez de dos UPDATE distintos.
async function update(id, { nombre, email, password, rol, activo }) {
    const hash = password ? await bcrypt.hash(password, RONDAS) : null;
    const { rowCount } = await db.query(
        `UPDATE usuarios
         SET nombre = $1, email = $2, rol = $3, activo = $4,
             password_hash = COALESCE($5, password_hash)
         WHERE id = $6`,
        [nombre, email, rol, activo, hash, id]);
    return rowCount;
}

async function remove(id) {
    const { rowCount } = await db.query('DELETE FROM usuarios WHERE id=$1', [id]);
    return rowCount;
}

module.exports = { getAll, getById, contarAdmins, create, update, remove };
