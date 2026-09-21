// Mapea método + URL -> controller. Sin lógica propia.
const express = require('express');
const router = express.Router();
const controller = require('./auth.controller');
const { requireInvitado } = require('../../../middleware/auth');
const { asyncH } = require('../../../middleware/errores');

// Rutas públicas: son las únicas que un Visitante puede alcanzar.
router.get('/', controller.getRoot);
router.get('/login', requireInvitado, controller.getLogin);
router.post('/login', requireInvitado, asyncH(controller.postLogin));
router.get('/registro', requireInvitado, controller.getRegistro);
router.post('/registro', requireInvitado, asyncH(controller.postRegistro));
router.get('/logout', controller.getLogout);

module.exports = router;
