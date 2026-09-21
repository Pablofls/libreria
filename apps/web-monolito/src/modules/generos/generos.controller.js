const GenerosModel = require('./generos.model');
const { crearControlador } = require('../../../services/crudCatalogo');
const { validarCatalogo } = require('../../../services/validacion');

module.exports = crearControlador({
    modelo: GenerosModel, ruta: 'generos',
    plural: 'Géneros', singular: 'género',
    validar: body => validarCatalogo(body, 'El nombre del género'),
    vistaLista: 'catalogo/lista', vistaForm: 'catalogo/formulario'
});
