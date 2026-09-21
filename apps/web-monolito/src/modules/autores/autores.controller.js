const AutoresModel = require('./autores.model');
const { crearControlador } = require('../../../services/crudCatalogo');
const { validarAutor } = require('../../../services/validacion');
const { entero } = require('../../../services/validacion');

const base = crearControlador({
    modelo: AutoresModel, ruta: 'autores',
    plural: 'Autores', singular: 'autor', validar: validarAutor
});

// Los autores tienen además una ficha propia con sus libros: es la única
// diferencia de comportamiento respecto a los demás catálogos.
async function getDetalle(req, res, next) {
    const id = entero(req.params.id);
    if (!id) return next();

    const autor = await AutoresModel.getById(id);
    if (!autor) return next();

    res.render('autores/detalle', {
        titulo: autor.nombre, autor, libros: await AutoresModel.getLibros(id)
    });
}

module.exports = { ...base, getDetalle };
