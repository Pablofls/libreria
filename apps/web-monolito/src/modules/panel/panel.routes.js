const express = require('express');
const router = express.Router();
const controller = require('./panel.controller');
const { requireAdmin } = require('../../../middleware/auth');
const { asyncH } = require('../../../middleware/errores');

router.get('/', requireAdmin, asyncH(controller.getPanel));

module.exports = router;
