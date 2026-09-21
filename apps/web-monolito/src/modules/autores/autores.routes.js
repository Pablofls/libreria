const express = require('express');
const router = express.Router();
const controller = require('./autores.controller');
const { requireLogin, requireAdmin } = require('../../../middleware/auth');
const { asyncH } = require('../../../middleware/errores');

// La ficha de un autor la puede ver cualquier usuario registrado; la gestión no.
router.get('/', requireAdmin, asyncH(controller.getLista));
router.get('/nuevo', requireAdmin, controller.getNuevo);
router.post('/', requireAdmin, asyncH(controller.postCrear));
router.get('/:id', requireLogin, asyncH(controller.getDetalle));
router.get('/:id/editar', requireAdmin, asyncH(controller.getEditar));
router.post('/:id/editar', requireAdmin, asyncH(controller.postActualizar));
router.post('/:id/eliminar', requireAdmin, asyncH(controller.postEliminar));

module.exports = router;
