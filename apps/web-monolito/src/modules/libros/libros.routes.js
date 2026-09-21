const express = require('express');
const router = express.Router();
const controller = require('./libros.controller');
const { requireLogin, requireAdmin } = require('../../../middleware/auth');
const { asyncH } = require('../../../middleware/errores');

// Consulta: cualquier usuario autenticado. Gestión: sólo el Administrador.
// El orden importa: '/nuevo' debe declararse antes que '/:id', o Express
// intentaría resolver '/libros/nuevo' como el detalle del libro con id 'nuevo'.
router.get('/', requireLogin, asyncH(controller.getLista));
router.get('/nuevo', requireAdmin, asyncH(controller.getNuevo));
router.post('/', requireAdmin, asyncH(controller.postCrear));
router.get('/:id', requireLogin, asyncH(controller.getDetalle));
router.get('/:id/editar', requireAdmin, asyncH(controller.getEditar));
router.post('/:id/editar', requireAdmin, asyncH(controller.postActualizar));
router.post('/:id/stock', requireAdmin, asyncH(controller.postStock));
router.post('/:id/eliminar', requireAdmin, asyncH(controller.postEliminar));

module.exports = router;
