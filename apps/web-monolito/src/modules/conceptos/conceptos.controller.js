// Conceptos: dos responsabilidades relacionadas pero distintas.
//   1. CRUD del catálogo de términos            -> /conceptos
//   2. La definición que un libro da a un término -> /conceptos/libro/:libro_id
const ConceptosModel = require('./conceptos.model');
const LibrosModel = require('../libros/libros.model');
const { crearControlador } = require('../../../services/crudCatalogo');
const { validarCatalogo, validarConceptoLibro, entero } = require('../../../services/validacion');

const catalogo = crearControlador({
    modelo: ConceptosModel, ruta: 'conceptos',
    plural: 'Conceptos', singular: 'concepto',
    // El catálogo sólo tiene término; se reutiliza validarCatalogo mapeando
    // `nombre` -> `termino` en el modelo.
    validar: body => validarCatalogo(body, 'El término'),
    vistaLista: 'conceptos/lista', vistaForm: 'conceptos/formulario'
});

// Ficha de un término con todas sus definiciones. Es la evidencia visual de por
// qué la definición pertenece a la relación libro-concepto y no al término.
async function getDetalle(req, res, next) {
    const id = entero(req.params.id);
    if (!id) return next();

    const concepto = await ConceptosModel.getById(id);
    if (!concepto) return next();

    res.render('conceptos/detalle', {
        titulo: concepto.termino, concepto,
        definiciones: await ConceptosModel.getDefiniciones(id)
    });
}

// --- Definición dentro de un libro ------------------------------------------

async function getFormularioLibro(req, res, next) {
    const libroId = entero(req.params.libro_id);
    if (!libroId) return next();

    const libro = await LibrosModel.getById(libroId);
    if (!libro) return next();

    // Si viene concepto_id, es edición de una definición existente.
    const conceptoId = entero(req.query.concepto_id);
    const actual = conceptoId ? await ConceptosModel.getDeLibro(libroId, conceptoId) : null;

    res.render('conceptos/formulario_libro', {
        titulo: actual ? 'Editar concepto del libro' : 'Nuevo concepto del libro',
        libro, actual, errores: []
    });
}

async function postGuardarEnLibro(req, res, next) {
    const libroId = entero(req.params.libro_id);
    if (!libroId) return next();

    const { errores, datos } = validarConceptoLibro(req.body);

    if (errores.length) {
        const libro = await LibrosModel.getById(libroId);
        if (!libro) return next();
        return res.status(400).render('conceptos/formulario_libro', {
            titulo: 'Concepto del libro', libro, actual: req.body, errores
        });
    }

    // sp_guardar_concepto_libro crea el término si hace falta y lo reutiliza si
    // ya existe, en una sola sentencia.
    await ConceptosModel.guardarEnLibro(libroId, datos);
    req.session.aviso = { tipo: 'exito', mensaje: `Concepto "${datos.termino}" guardado.` };
    res.redirect(`${res.locals.base}/libros/${libroId}`);
}

async function postQuitarDeLibro(req, res, next) {
    const libroId = entero(req.params.libro_id);
    const conceptoId = entero(req.params.concepto_id);
    if (!libroId || !conceptoId) return next();

    // Se quita la definición, no el término: el concepto sigue en el catálogo
    // para otros libros.
    await ConceptosModel.quitarDeLibro(libroId, conceptoId);
    req.session.aviso = { tipo: 'exito', mensaje: 'Concepto retirado del libro.' };
    res.redirect(`${res.locals.base}/libros/${libroId}`);
}

module.exports = {
    ...catalogo, getDetalle,
    getFormularioLibro, postGuardarEnLibro, postQuitarDeLibro
};
