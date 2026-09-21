// SQL de autenticación. El hash se calcula y compara aquí; la base de datos
// nunca ve la contraseña en claro (ni siquiera para compararla).
const db = require('../../../config/db');
const bcrypt = require('bcrypt');

// Coste 10: ~100 ms por hash en la VM del ejercicio. Suficiente para que un
// ataque por fuerza bruta sobre la base filtrada sea caro, y bajo para que el
// login no se sienta lento. Si se sube, hay que resembrar los hashes existentes.
const RONDAS = 10;

async function findByEmail(email) {
    const { rows } = await db.query(
        `SELECT id, nombre, email, password_hash, rol, activo
         FROM usuarios WHERE email = lower(btrim($1))`, [email]);
    return rows[0] || null;
}

async function createUser({ nombre, email, password }) {
    const hash = await bcrypt.hash(password, RONDAS);
    // rol no se toma del formulario: siempre 'lector'. Si viniera de req.body,
    // cualquiera podría registrarse como admin enviando rol=admin en el POST.
    const { rows } = await db.query(
        `INSERT INTO usuarios (nombre, email, password_hash, rol)
         VALUES ($1, $2, $3, 'lector') RETURNING id`,
        [nombre, email, hash]);
    return rows[0].id;
}

async function verifyPassword(password, hash) {
    return bcrypt.compare(password, hash);
}

// Compara contra un hash ficticio cuando el correo no existe. Sin esto, la
// respuesta a un correo inexistente sería notablemente más rápida que la de una
// contraseña incorrecta, y esa diferencia de tiempo revela qué correos están
// registrados (enumeración de usuarios).
const HASH_SENUELO = '$2b$10$CwTycUXWue0Thq9StjUM0uJ8.7pO/1234567890abcdefghijklmn';
async function gastarTiempoDeComparacion(password) {
    try { await bcrypt.compare(password || '', HASH_SENUELO); } catch { /* ignorado */ }
}

module.exports = { findByEmail, createUser, verifyPassword, gastarTiempoDeComparacion, RONDAS };
