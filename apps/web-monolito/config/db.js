// Punto único de conexión a PostgreSQL. Ningún módulo crea su propio Pool.
const { Pool } = require('pg');
const config = require('./env');

const pool = new Pool({
    ...config.db,
    max: 10,                       // suficiente para un monolito de un proceso
    idleTimeoutMillis: 30000,
    connectionTimeoutMillis: 5000
});

// Un error del pool en reposo (la BD se reinició, se cayó la red) llega aquí y
// no a un `await` concreto. Sin este handler, Node terminaría el proceso.
pool.on('error', err => {
    console.error('[db] error en conexión inactiva:', err.message);
});

// Envoltura única de query. Registra la consulta lenta y NUNCA propaga el
// detalle interno al usuario: el controller solo verá un Error con `code`.
async function query(texto, parametros) {
    const inicio = Date.now();
    try {
        const resultado = await pool.query(texto, parametros);
        const ms = Date.now() - inicio;
        if (ms > 500) console.warn(`[db] consulta lenta (${ms} ms): ${texto.slice(0, 90)}`);
        return resultado;
    } catch (err) {
        // El log del servidor sí guarda todo; la respuesta HTTP no (ver middleware/errores.js).
        console.error(`[db] ${err.code || 'ERROR'} ${err.message} | SQL: ${texto.slice(0, 120)}`);
        throw err;
    }
}

module.exports = { query, pool };
