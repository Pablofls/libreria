const CategoriasModel = require('./categorias.model');
const { crearControlador } = require('../../../services/crudCatalogo');
const { validarCatalogo } = require('../../../services/validacion');

module.exports = crearControlador({
    modelo: CategoriasModel, ruta: 'categorias',
    plural: 'Categorías', singular: 'categoría',
    validar: body => validarCatalogo(body, 'El nombre de la categoría'),
    vistaLista: 'catalogo/lista', vistaForm: 'catalogo/formulario'
});
