const express = require('express');
const router = express.Router();
const controller = require('./imagenes.controller');
const { requireAdmin } = require('../../../middleware/auth');
const { asyncH } = require('../../../middleware/errores');
const { subirImagen } = require('../../../middleware/subidas');
const { verificarCsrf } = require('../../../middleware/locals');

// requireAdmin va ANTES de subirImagen: a un usuario sin permiso no se le
// escribe el archivo en el disco de la VM aunque lo haya enviado.
router.get('/nuevo/:libro_id', requireAdmin, asyncH(controller.getNuevo));
// verificarCsrf va DESPUÉS de subirImagen: el token viaja dentro del cuerpo
// multipart y sólo existe en req.body una vez que Multer lo parseó. El chequeo
// global de app.js aplaza los multipart precisamente para esto.
router.post('/:libro_id', requireAdmin, subirImagen('imagen'), verificarCsrf,
    asyncH(controller.postSubir));
router.post('/:id/portada', requireAdmin, asyncH(controller.postPortada));
router.post('/:id/alt', requireAdmin, asyncH(controller.postAlt));
router.post('/:id/eliminar', requireAdmin, asyncH(controller.postEliminar));

module.exports = router;
