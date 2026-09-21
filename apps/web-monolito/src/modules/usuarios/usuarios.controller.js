const UsuariosModel = require('./usuarios.model');
const { validarUsuario, entero } = require('../../../services/validacion');

async function getLista(req, res) {
    res.render('usuarios/lista', {
        titulo: 'Usuarios',
        usuarios: await UsuariosModel.getAll(),
        administradores: await UsuariosModel.contarAdmins()
    });
}

function getNuevo(req, res) {
    res.render('usuarios/formulario', {
        titulo: 'Nuevo usuario',
        accion: `${res.locals.base}/usuarios`,
        registro: null, errores: []
    });
}

// Traduce los errores que puede levantar la propia base de datos al crear o
// editar un usuario. La regla de "un solo Administrador" se comprueba en la BD
// (índice único parcial + trigger), no aquí: si se comprobara sólo en Node, dos
// peticiones simultáneas podrían crear dos admins.
function mensajeDeError(err) {
    if (err.code === '23505') {
        return err.message.includes('Administrador')
            ? 'Ya existe un Administrador. El sistema admite como máximo uno.'
            : 'Ese correo ya está registrado.';
    }
    if (err.code === '23514') return 'Alguno de los datos no cumple las reglas del sistema.';
    if (err.code === '2BP01' || err.code === '23503') return 'El usuario está relacionado con otros datos.';
    return null;   // no reconocido: que lo maneje el manejador general
}

async function postCrear(req, res) {
    const { errores, datos } = validarUsuario(req.body);

    if (errores.length) {
        return res.status(400).render('usuarios/formulario', {
            titulo: 'Nuevo usuario',
            accion: `${res.locals.base}/usuarios`,
            registro: { ...req.body, password: '' }, errores
        });
    }

    try {
        await UsuariosModel.create(datos);
    } catch (err) {
        const mensaje = mensajeDeError(err);
        if (!mensaje) throw err;
        return res.status(409).render('usuarios/formulario', {
            titulo: 'Nuevo usuario',
            accion: `${res.locals.base}/usuarios`,
            registro: { ...req.body, password: '' }, errores: [mensaje]
        });
    }

    req.session.aviso = { tipo: 'exito', mensaje: 'Usuario creado.' };
    res.redirect(`${res.locals.base}/usuarios`);
}

async function getEditar(req, res, next) {
    const id = entero(req.params.id);
    if (!id) return next();

    const registro = await UsuariosModel.getById(id);
    if (!registro) return next();

    res.render('usuarios/formulario', {
        titulo: 'Editar usuario',
        accion: `${res.locals.base}/usuarios/${id}/editar`,
        registro, errores: []
    });
}

async function postActualizar(req, res, next) {
    const id = entero(req.params.id);
    if (!id) return next();

    const { errores, datos } = validarUsuario(req.body, { esEdicion: true });

    const volverConError = (lista, estado = 400) =>
        res.status(estado).render('usuarios/formulario', {
            titulo: 'Editar usuario',
            accion: `${res.locals.base}/usuarios/${id}/editar`,
            registro: { ...req.body, id, password: '' }, errores: lista
        });

    if (errores.length) return volverConError(errores);

    // El Administrador no puede quitarse a sí mismo el rol ni desactivarse:
    // se quedaría fuera del sistema sin nadie que pueda devolvérselo. El
    // trigger trg_conservar_admin también lo impide; esto sólo da mejor mensaje.
    if (id === req.session.usuario.id) {
        if (datos.rol !== 'admin') return volverConError(['No puedes quitarte a ti mismo el rol de Administrador.']);
        if (!datos.activo) return volverConError(['No puedes desactivar tu propia cuenta.']);
    }

    try {
        const filas = await UsuariosModel.update(id, datos);
        if (!filas) return next();
    } catch (err) {
        const mensaje = mensajeDeError(err);
        if (!mensaje) throw err;
        return volverConError([mensaje], 409);
    }

    req.session.aviso = { tipo: 'exito', mensaje: 'Usuario actualizado.' };
    res.redirect(`${res.locals.base}/usuarios`);
}

async function postEliminar(req, res, next) {
    const id = entero(req.params.id);
    if (!id) return next();

    if (id === req.session.usuario.id) {
        req.session.aviso = { tipo: 'error', mensaje: 'No puedes eliminar tu propia cuenta.' };
        return res.redirect(`${res.locals.base}/usuarios`);
    }

    try {
        const filas = await UsuariosModel.remove(id);
        if (!filas) return next();
        req.session.aviso = { tipo: 'exito', mensaje: 'Usuario eliminado.' };
    } catch (err) {
        // restrict_violation del trigger que impide quedarse sin Administrador.
        if (err.code !== '2BP01' && err.code !== '23001') throw err;
        req.session.aviso = { tipo: 'error', mensaje: 'No se puede dejar el sistema sin Administrador.' };
    }
    res.redirect(`${res.locals.base}/usuarios`);
}

module.exports = { getLista, getNuevo, postCrear, getEditar, postActualizar, postEliminar };
