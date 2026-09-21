// Lectura y validación de la configuración. Un solo lugar que toca process.env.
//
// La aplicación falla al arrancar si falta un secreto obligatorio, en vez de
// arrancar con un valor por defecto inseguro. Un SESSION_SECRET con valor por
// omisión en el repositorio permitiría a cualquiera firmar cookies de sesión
// válidas, así que preferimos no arrancar.
const resultado = require('dotenv').config({ quiet: true });

// dotenv NO sobrescribe una variable que ya exista en el entorno del proceso.
// Es su comportamiento documentado y tiene sentido —permite fijar un valor al
// lanzar el proceso— pero produce un fallo desconcertante: la aplicación acaba
// usando un valor que no está en el .env y que nadie ve.
//
// Caso real: un `export DB_USER=...` que quedó vivo en la sesión de shell hizo
// que la aplicación se conectara con el usuario anterior de PostgreSQL y la
// contraseña nueva del .env. El error que llegaba era "password authentication
// failed", que apunta a la contraseña y no a la causa.
//
// Este aviso hace visible la discrepancia en el arranque.
const delArchivo = resultado.parsed || {};
const tapadas = Object.keys(delArchivo).filter(k => process.env[k] !== delArchivo[k]);
if (tapadas.length) {
    console.warn(
        `[config] AVISO: el entorno del proceso tiene un valor distinto al del .env ` +
        `para: ${tapadas.join(', ')}.\n` +
        `          Se usará el del entorno, NO el del .env. Si no es lo que quieres, ` +
        `ejecuta: unset ${tapadas.join(' ')}`
    );
}

const OBLIGATORIAS = ['DB_USER', 'DB_HOST', 'DB_NAME', 'DB_PASSWORD', 'DB_PORT', 'SESSION_SECRET'];

const faltantes = OBLIGATORIAS.filter(v => !process.env[v]);
if (faltantes.length) {
    console.error(
        `Falta configuración obligatoria en .env: ${faltantes.join(', ')}.\n` +
        `Copia .env.example a .env y complétalo. Ver README, "Variables de entorno".`
    );
    process.exit(1);
}

if (process.env.SESSION_SECRET.length < 32) {
    console.error('SESSION_SECRET debe tener al menos 32 caracteres.');
    process.exit(1);
}

// basePath: prefijo bajo el que publica el reverse proxy ('/library' en la VM).
// Vacío en local. Se normaliza para que nunca termine en '/'.
const basePath = (process.env.BASE_PATH || '').replace(/\/+$/, '');

module.exports = {
    entorno: process.env.NODE_ENV || 'development',
    // 127.0.0.1 por defecto: Node no se expone a internet, solo el proxy lo alcanza.
    host: process.env.APP_HOST || '127.0.0.1',
    puerto: parseInt(process.env.APP_PORT || '3000', 10),
    basePath,
    sessionSecret: process.env.SESSION_SECRET,
    // true solo detrás de HTTPS; con http la cookie secure nunca se enviaría.
    cookieSegura: process.env.COOKIE_SECURE === 'true',
    db: {
        user: process.env.DB_USER,
        host: process.env.DB_HOST,
        database: process.env.DB_NAME,
        password: process.env.DB_PASSWORD,
        port: parseInt(process.env.DB_PORT, 10)
    },
    subidas: {
        directorio: process.env.UPLOAD_DIR || 'uploads',
        // 2 MB. El mismo límite está replicado en ck_imagenes_tamano (BD).
        tamanoMaximo: parseInt(process.env.UPLOAD_MAX_BYTES || '2097152', 10)
    }
};
