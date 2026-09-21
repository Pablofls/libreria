// Orquesta el flujo de sesión. No contiene SQL ni HTML.
const AuthModel = require('./auth.model');
const { validarRegistro, validarPassword, texto } = require('../../../services/validacion');

// Limitador de intentos de login, en memoria del proceso.
// Un monolito de un solo proceso puede permitírselo; si algún día hubiera
// varias instancias detrás del proxy, esto tendría que moverse a la BD o a
// Redis (queda anotado como limitación en docs/SECURITY_REVIEW.md).
const intentos = new Map();
const MAX_INTENTOS = 5;
const VENTANA_MS = 15 * 60 * 1000;

function llave(req) {
    return `${req.ip}|${String(req.body.email || '').toLowerCase().slice(0, 150)}`;
}

function bloqueado(k) {
    const reg = intentos.get(k);
    if (!reg) return false;
    if (Date.now() - reg.desde > VENTANA_MS) { intentos.delete(k); return false; }
    return reg.n >= MAX_INTENTOS;
}

function registrarFallo(k) {
    const reg = intentos.get(k);
    if (!reg || Date.now() - reg.desde > VENTANA_MS) intentos.set(k, { n: 1, desde: Date.now() });
    else reg.n += 1;
}

function getRoot(req, res) {
    res.redirect(res.locals.base + (req.session.usuario ? '/libros' : '/login'));
}

function getLogin(req, res) {
    res.render('auth/login', { titulo: 'Iniciar sesión', datos: {}, errores: [] });
}

async function postLogin(req, res) {
    const email = texto(req.body.email).toLowerCase();
    const password = typeof req.body.password === 'string' ? req.body.password : '';
    const k = llave(req);

    const responder = (mensaje, estado = 401) =>
        res.status(estado).render('auth/login', {
            titulo: 'Iniciar sesión', datos: { email }, errores: [mensaje]
        });

    if (bloqueado(k)) {
        console.warn(`[auth] login bloqueado por intentos: ${req.ip}`);
        return responder('Demasiados intentos fallidos. Espera 15 minutos e inténtalo de nuevo.', 429);
    }

    if (!email || !password) {
        registrarFallo(k);
        return responder('Escribe tu correo y tu contraseña.', 400);
    }

    const usuario = await AuthModel.findByEmail(email);

    // Si el correo no existe se compara igual contra un hash señuelo, para que
    // el tiempo de respuesta no delate qué correos están registrados.
    if (!usuario) {
        await AuthModel.gastarTiempoDeComparacion(password);
        registrarFallo(k);
        return responder('El correo o la contraseña son incorrectos.');
    }

    const valida = await AuthModel.verifyPassword(password, usuario.password_hash);

    // Mismo mensaje para "no existe", "contraseña mala" y "cuenta desactivada":
    // no se le dice a quien prueba credenciales cuál de las tres falló.
    if (!valida || !usuario.activo) {
        registrarFallo(k);
        return responder('El correo o la contraseña son incorrectos.');
    }

    intentos.delete(k);

    // Regeneración de sesión: descarta el id de sesión que el visitante traía
    // antes de autenticarse. Sin esto, un atacante que logre fijar una cookie
    // en el navegador de la víctima seguiría teniendo esa sesión ya con permisos
    // (fijación de sesión).
    const destino = req.session.destino;
    req.session.regenerate(err => {
        if (err) throw err;
        req.session.usuario = { id: usuario.id, nombre: usuario.nombre, rol: usuario.rol };
        // Sólo se acepta un destino interno; una URL absoluta permitiría un
        // redirect abierto hacia un sitio de phishing.
        const seguro = typeof destino === 'string' && /^\/[^/\\]/.test(destino);
        res.redirect(res.locals.base + (seguro ? destino : '/libros'));
    });
}

function getRegistro(req, res) {
    res.render('auth/registro', { titulo: 'Crear cuenta', datos: {}, errores: [] });
}

async function postRegistro(req, res) {
    const { errores, datos } = validarRegistro(req.body);

    if (errores.length) {
        // Se devuelve el formulario con lo capturado, menos la contraseña.
        return res.status(400).render('auth/registro', {
            titulo: 'Crear cuenta',
            datos: { nombre: datos.nombre, email: datos.email },
            errores
        });
    }

    try {
        await AuthModel.createUser(datos);
    } catch (err) {
        // 23505 = correo repetido. Se responde igual que si se hubiera creado,
        // no: aquí sí conviene decirlo, porque el propio formulario de registro
        // ya revela la existencia del correo al intentarlo. Lo que no se hace es
        // filtrar el detalle de PostgreSQL.
        if (err.code === '23505') {
            return res.status(409).render('auth/registro', {
                titulo: 'Crear cuenta',
                datos: { nombre: datos.nombre, email: datos.email },
                errores: ['Ese correo ya está registrado.']
            });
        }
        throw err;
    }

    req.session.aviso = { tipo: 'exito', mensaje: 'Cuenta creada. Ya puedes iniciar sesión.' };
    res.redirect(res.locals.base + '/login');
}

function getLogout(req, res) {
    const base = res.locals.base;
    req.session.destroy(() => {
        res.clearCookie('libreria.sid', { path: base || '/' });
        res.redirect(base + '/login');
    });
}

module.exports = { getRoot, getLogin, postLogin, getRegistro, postRegistro, getLogout };
