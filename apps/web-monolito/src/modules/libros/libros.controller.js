const LibrosModel = require('./libros.model');
const AutoresModel = require('../autores/autores.model');
const GenerosModel = require('../generos/generos.model');
const CategoriasModel = require('../categorias/categorias.model');
const FormatosModel = require('../formatos/formatos.model');
const { validarLibro, texto, entero } = require('../../../services/validacion');
const { borrarArchivo } = require('../../../middleware/subidas');

// Catálogos que necesita el formulario de libro. Se piden en paralelo: son
// cuatro consultas independientes y encadenarlas con await sólo suma latencia.
function catalogos() {
    return Promise.all([
        AutoresModel.getAll(), GenerosModel.getAll(),
        CategoriasModel.getAll(), FormatosModel.getAll()
    ]).then(([autores, generos, categorias, formatos]) =>
        ({ autores, generos, categorias, formatos }));
}

async function getLista(req, res) {
    const q = texto(req.query.q);
    const libros = q ? await LibrosModel.buscar(q) : await LibrosModel.getAll();

    // El Administrador ve la tabla de gestión; el lector, la rejilla de portadas.
    // Es sólo presentación: las rutas de gestión están protegidas aparte.
    res.render(res.locals.esAdmin ? 'libros/lista' : 'libros/catalogo', {
        titulo: res.locals.esAdmin ? 'Libros' : 'Catálogo',
        libros, q
    });
}

async function getNuevo(req, res) {
    res.render('libros/formulario', {
        titulo: 'Nuevo libro',
        accion: `${res.locals.base}/libros`,
        libro: null, seleccion: { autores: [], generos: [] },
        ...(await catalogos()), errores: []
    });
}

async function postCrear(req, res) {
    const { errores, datos } = validarLibro(req.body);

    if (errores.length) {
        return res.status(400).render('libros/formulario', {
            titulo: 'Nuevo libro',
            accion: `${res.locals.base}/libros`,
            libro: req.body,
            seleccion: { autores: datos.autores, generos: datos.generos },
            ...(await catalogos()), errores
        });
    }

    const id = await LibrosModel.guardar(null, datos);
    req.session.aviso = { tipo: 'exito', mensaje: `Libro "${datos.titulo}" creado.` };
    res.redirect(`${res.locals.base}/libros/${id}`);
}

async function getDetalle(req, res, next) {
    const id = entero(req.params.id);
    if (!id) return next();

    const libro = await LibrosModel.getById(id);
    if (!libro) return next();   // cae en el 404 general

    const [autores, generos, imagenes, conceptos] = await Promise.all([
        LibrosModel.getAutores(id), LibrosModel.getGeneros(id),
        LibrosModel.getImagenes(id), LibrosModel.getConceptos(id)
    ]);

    res.render('libros/detalle', {
        titulo: libro.titulo, libro, autores, generos, imagenes, conceptos
    });
}

async function getEditar(req, res, next) {
    const id = entero(req.params.id);
    if (!id) return next();

    const [libro, cat] = await Promise.all([LibrosModel.getById(id), catalogos()]);
    if (!libro) return next();

    const [autores, generos] = await Promise.all([
        LibrosModel.getAutores(id), LibrosModel.getGeneros(id)
    ]);

    res.render('libros/formulario', {
        titulo: 'Editar libro',
        accion: `${res.locals.base}/libros/${id}/editar`,
        libro,
        seleccion: { autores: autores.map(a => a.id), generos: generos.map(g => g.id) },
        ...cat, errores: []
    });
}

async function postActualizar(req, res, next) {
    const id = entero(req.params.id);
    if (!id) return next();

    const { errores, datos } = validarLibro(req.body);

    if (errores.length) {
        return res.status(400).render('libros/formulario', {
            titulo: 'Editar libro',
            accion: `${res.locals.base}/libros/${id}/editar`,
            libro: { ...req.body, id },
            seleccion: { autores: datos.autores, generos: datos.generos },
            ...(await catalogos()), errores
        });
    }

    await LibrosModel.guardar(id, datos);
    req.session.aviso = { tipo: 'exito', mensaje: 'Libro actualizado.' };
    res.redirect(`${res.locals.base}/libros/${id}`);
}

async function postEliminar(req, res, next) {
    const id = entero(req.params.id);
    if (!id) return next();

    // remove() devuelve los archivos que quedaron sin registro por el CASCADE.
    // Se borran del disco después de que la transacción confirmó: si se borraran
    // antes y el DELETE fallara, quedarían filas apuntando a archivos que ya no
    // existen.
    const archivos = await LibrosModel.remove(id);
    archivos.forEach(borrarArchivo);

    req.session.aviso = { tipo: 'exito', mensaje: 'Libro eliminado.' };
    res.redirect(`${res.locals.base}/libros`);
}

async function postStock(req, res, next) {
    const id = entero(req.params.id);
    const delta = entero(req.body.delta);
    if (!id || delta === null) return next();

    try {
        const stock = await LibrosModel.ajustarStock(id, delta);
        req.session.aviso = { tipo: 'exito', mensaje: `Existencias actualizadas: ${stock}.` };
    } catch (err) {
        if (err.code !== '23514') throw err;   // 23514 = ck_libros_stock
        req.session.aviso = { tipo: 'error', mensaje: 'No hay suficientes existencias.' };
    }
    res.redirect(`${res.locals.base}/libros/${id}`);
}

module.exports = {
    getLista, getNuevo, postCrear, getDetalle, getEditar,
    postActualizar, postEliminar, postStock
};
