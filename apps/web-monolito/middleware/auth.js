// Autenticación (¿quién eres?) y autorización (¿puedes hacer esto?) separadas.
//
// requireLogin resuelve la primera pregunta; requireAdmin la segunda. Están en
// funciones distintas porque son decisiones distintas: una sesión válida no
// implica permiso, y confundirlas es como se cuelan los fallos de control de
// acceso.

function requireLogin(req, res, next) {
    if (!req.session.usuario) {
        // Se recuerda a dónde quería ir para volver ahí después del login.
        req.session.destino = req.originalUrl;
        return res.redirect(res.locals.base + '/login');
    }
    next();
}

// Autorización por rol. Responde 403 con una página propia, no un redirect:
// un lector que intenta /usuarios debe recibir una negativa explícita
// ("respuesta controlada de acceso denegado"), no un rebote silencioso que
// parezca un fallo de sesión.
function requireAdmin(req, res, next) {
    if (!req.session.usuario) {
        req.session.destino = req.originalUrl;
        return res.redirect(res.locals.base + '/login');
    }
    if (req.session.usuario.rol !== 'admin') {
        console.warn(`[autz] 403 usuario=${req.session.usuario.id} ruta=${req.originalUrl}`);
        return res.status(403).render('errores/403', { titulo: 'Acceso denegado' });
    }
    next();
}

// Para /login y /registro: quien ya tiene sesión no debe volver a verlos.
function requireInvitado(req, res, next) {
    if (req.session.usuario) return res.redirect(res.locals.base + '/libros');
    next();
}

module.exports = { requireLogin, requireAdmin, requireInvitado };
