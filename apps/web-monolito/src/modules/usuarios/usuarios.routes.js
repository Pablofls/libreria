const express = require('express');
const router = express.Router();
const controller = require('./usuarios.controller');
const { requireAdmin } = require('../../../middleware/auth');
const { asyncH } = require('../../../middleware/errores');

// Administración del sistema: reservada por completo al Administrador.
router.get('/', requireAdmin, asyncH(controller.getLista));
router.get('/nuevo', requireAdmin, controller.getNuevo);
router.post('/', requireAdmin, asyncH(controller.postCrear));
router.get('/:id/editar', requireAdmin, asyncH(controller.getEditar));
router.post('/:id/editar', requireAdmin, asyncH(controller.postActualizar));
router.post('/:id/eliminar', requireAdmin, asyncH(controller.postEliminar));

module.exports = router;
