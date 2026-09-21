const PanelModel = require('./panel.model');

// Panel del Administrador: sólo lectura. Sirve como evidencia visual de los
// conteos y de la regla de un solo Administrador.
async function getPanel(req, res) {
    const [resumen, inventario, pendientes] = await Promise.all([
        PanelModel.resumen(), PanelModel.inventario(), PanelModel.pendientes()
    ]);
    res.render('panel/inicio', { titulo: 'Panel de administración', resumen, inventario, pendientes });
}

module.exports = { getPanel };
