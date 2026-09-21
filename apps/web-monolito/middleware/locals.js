// Variables disponibles en todas las vistas EJS, más el token anti-CSRF.
const crypto = require('crypto');
const config = require('../config/env');

// `base` es el prefijo público ('/library' en la VM, '' en local). Todas las
// plantillas construyen sus URL como `<%= base %>/libros`, de modo que la
// aplicación funciona igual montada en la raíz o bajo un subdirectorio del
// reverse proxy, sin tocar una sola vista.
function locals(req, res, next) {
    // req.session puede no existir: express-session se salta las peticiones
    // fuera del `path` de su cookie. Con BASE_PATH='/library', una petición a
    // '/libros' (sin prefijo) llega hasta aquí sin sesión. No es un error —
    // esa ruta no existe y terminará en el 404— pero las vistas necesitan que
    // estas variables estén definidas para poder renderizar la página de error.
    const sesion = req.session || {};

    res.locals.base = config.basePath;
    res.locals.usuario = sesion.usuario || null;
    res.locals.esAdmin = Boolean(sesion.usuario && sesion.usuario.rol === 'admin');
    res.locals.rutaActual = req.path;
    res.locals.errores = [];
    res.locals.aviso = null;

    // Aviso de un solo uso: se guarda en la sesión antes de un redirect y se
    // consume aquí. Evita arrastrar el mensaje en la query string.
    if (sesion.aviso) {
        res.locals.aviso = sesion.aviso;
        delete sesion.aviso;
    }
    next();
}

// --- CSRF --------------------------------------------------------------------
// Sin esto, un formulario alojado en otro sitio podría hacer que el navegador
// del Administrador —que ya tiene sesión— envíe un POST de borrado. La cookie
// viaja sola; el token no, porque el atacante no puede leer nuestro HTML.
function tokenCsrf(req, res, next) {
    if (!req.session) { res.locals.csrf = ''; return next(); }
    if (!req.session.csrf) {
        req.session.csrf = crypto.randomBytes(32).toString('hex');
    }
    res.locals.csrf = req.session.csrf;
    next();
}

function verificarCsrf(req, res, next) {
    if (!['POST', 'PUT', 'PATCH', 'DELETE'].includes(req.method)) return next();

    // Los formularios multipart/form-data (subida de imágenes) los parsea
    // Multer, no express.urlencoded, y Multer corre DESPUÉS de este middleware
    // global: aquí req.body todavía está vacío. Por eso se aplaza y esas rutas
    // vuelven a invocar verificarCsrf justo después de subirImagen().
    // Ver src/modules/imagenes/imagenes.routes.js.
    const esMultipart = (req.headers['content-type'] || '').startsWith('multipart/form-data');
    if (esMultipart && !req.file && !req.errorSubida) return next();

    const enviado = req.body && req.body._csrf;
    const esperado = req.session && req.session.csrf;

    // timingSafeEqual exige buffers del mismo largo; se compara sólo si coinciden.
    const valido = typeof enviado === 'string'
        && typeof esperado === 'string'
        && enviado.length === esperado.length
        && crypto.timingSafeEqual(Buffer.from(enviado), Buffer.from(esperado));

    if (!valido) {
        console.warn(`[csrf] token inválido en ${req.method} ${req.originalUrl}`);
        // Si Multer ya escribió el archivo, se borra: una petición sin token no
        // debe dejar basura en el disco de la VM.
        if (req.file) require('./subidas').borrarArchivo(req.file.filename);
        return res.status(403).render('errores/403', {
            titulo: 'Solicitud rechazada',
            mensaje: 'La solicitud no incluyó un token válido. Vuelve a cargar el formulario e inténtalo de nuevo.'
        });
    }

    // Marca para que un controller de subida pueda comprobar que la validación
    // sí ocurrió, y no dependa de que alguien recuerde ponerla en la ruta.
    req.csrfVerificado = true;
    next();
}

module.exports = { locals, tokenCsrf, verificarCsrf };
