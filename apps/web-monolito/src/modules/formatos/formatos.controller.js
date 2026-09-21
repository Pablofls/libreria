const FormatosModel = require('./formatos.model');
const { crearControlador } = require('../../../services/crudCatalogo');
const { validarCatalogo } = require('../../../services/validacion');

module.exports = crearControlador({
    modelo: FormatosModel, ruta: 'formatos',
    plural: 'Formatos', singular: 'formato',
    validar: body => validarCatalogo(body, 'El nombre del formato'),
    vistaLista: 'catalogo/lista', vistaForm: 'catalogo/formulario'
});
