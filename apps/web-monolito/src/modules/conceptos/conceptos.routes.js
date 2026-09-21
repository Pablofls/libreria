const express = require('express');
const router = express.Router();
const controller = require('./conceptos.controller');
const { requireLogin, requireAdmin } = require('../../../middleware/auth');
const { asyncH } = require('../../../middleware/errores');

// Las rutas de 'libro/...' van antes que '/:id' para que 'libro' no se
// interprete como el id de un concepto.
router.get('/libro/:libro_id/nuevo', requireAdmin, asyncH(controller.getFormularioLibro));
router.post('/libro/:libro_id', requireAdmin, asyncH(controller.postGuardarEnLibro));
router.post('/libro/:libro_id/:concepto_id/quitar', requireAdmin, asyncH(controller.postQuitarDeLibro));

// CRUD del catálogo de términos.
router.get('/', requireAdmin, asyncH(controller.getLista));
router.get('/nuevo', requireAdmin, controller.getNuevo);
router.post('/', requireAdmin, asyncH(controller.postCrear));
router.get('/:id', requireLogin, asyncH(controller.getDetalle));
router.get('/:id/editar', requireAdmin, asyncH(controller.getEditar));
router.post('/:id/editar', requireAdmin, asyncH(controller.postActualizar));
router.post('/:id/eliminar', requireAdmin, asyncH(controller.postEliminar));

module.exports = router;
