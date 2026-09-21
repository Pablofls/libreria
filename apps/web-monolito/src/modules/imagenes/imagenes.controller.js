const ImagenesModel = require('./imagenes.model');
const LibrosModel = require('../libros/libros.model');
const { borrarArchivo } = require('../../../middleware/subidas');
const { validarImagen, entero } = require('../../../services/validacion');

async function getNuevo(req, res, next) {
    const libroId = entero(req.params.libro_id);
    if (!libroId) return next();

    const libro = await LibrosModel.getById(libroId);
    if (!libro) return next();

    res.render('imagenes/formulario', { titulo: 'Agregar imagen', libro, errores: [] });
}

async function postSubir(req, res, next) {
    // Red de seguridad: si alguien reordenara los middleware de la ruta y el
    // token dejara de comprobarse, aquí se corta en vez de aceptar la subida.
    if (!req.csrfVerificado) {
        if (req.file) borrarArchivo(req.file.filename);
        return res.status(403).render('errores/403', {
            titulo: 'Solicitud rechazada',
            mensaje: 'La solicitud no incluyó un token válido.'
        });
    }

    const libroId = entero(req.params.libro_id);
    if (!libroId) return next();

    const libro = await LibrosModel.getById(libroId);
    if (!libro) {
        // El libro no existe: el archivo ya subido se descarta para no dejar
        // huérfanos en el disco.
        if (req.file) borrarArchivo(req.file.filename);
        return next();
    }

    const { errores, datos } = validarImagen(req.body);

    // El middleware de subida deja aquí el motivo del rechazo (tamaño, tipo,
    // firma que no corresponde) y ya borró el archivo si llegó a escribirse.
    if (req.errorSubida) errores.unshift(req.errorSubida);
    if (!req.file && !req.errorSubida) errores.unshift('Selecciona una imagen.');

    if (errores.length) {
        if (req.file) borrarArchivo(req.file.filename);
        return res.status(400).render('imagenes/formulario', {
            titulo: 'Agregar imagen', libro, errores
        });
    }

    try {
        await ImagenesModel.create(libroId, req.file, datos);
    } catch (err) {
        // Si el registro en BD falla, el archivo en disco no debe quedarse.
        borrarArchivo(req.file.filename);
        throw err;
    }

    req.session.aviso = { tipo: 'exito', mensaje: 'Imagen agregada.' };
    res.redirect(`${res.locals.base}/libros/${libroId}`);
}

async function postPortada(req, res, next) {
    const id = entero(req.params.id);
    if (!id) return next();

    const libroId = await ImagenesModel.marcarPortada(id);
    req.session.aviso = { tipo: 'exito', mensaje: 'Portada actualizada.' };
    res.redirect(`${res.locals.base}/libros/${libroId}`);
}

async function postAlt(req, res, next) {
    const id = entero(req.params.id);
    if (!id) return next();

    const { errores, datos } = validarImagen({ ...req.body, es_portada: 'false' });
    const imagen = await ImagenesModel.getById(id);
    if (!imagen) return next();

    if (errores.length) {
        req.session.aviso = { tipo: 'error', mensaje: errores[0] };
    } else {
        await ImagenesModel.actualizarAlt(id, datos.texto_alternativo);
        req.session.aviso = { tipo: 'exito', mensaje: 'Texto alternativo actualizado.' };
    }
    res.redirect(`${res.locals.base}/libros/${imagen.libro_id}`);
}

async function postEliminar(req, res, next) {
    const id = entero(req.params.id);
    if (!id) return next();

    const borrada = await ImagenesModel.remove(id);
    if (!borrada) return next();

    // Primero la fila, después el archivo: si el DELETE fallara, el archivo
    // seguiría existiendo y la portada no quedaría rota.
    borrarArchivo(borrada.nombre_archivo);

    req.session.aviso = { tipo: 'exito', mensaje: 'Imagen eliminada.' };
    res.redirect(`${res.locals.base}/libros/${borrada.libro_id}`);
}

module.exports = { getNuevo, postSubir, postPortada, postAlt, postEliminar };
