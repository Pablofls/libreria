// Manejo centralizado de errores.
//
// Regla: el usuario final nunca ve un stack trace, un nombre de tabla ni un
// fragmento de SQL. Eso le dice a un atacante cómo está construido el sistema.
// El detalle completo va al log del servidor, que sí es privado.

// Códigos de PostgreSQL que corresponden a un error del usuario, no del
// sistema: se traducen a un mensaje entendible y a un 400, no a un 500.
const MENSAJES_PG = {
    '23505': 'Ya existe un registro con ese valor único (por ejemplo, un ISBN o un correo repetido).',
    '23503': 'No se puede completar: el registro está relacionado con otros datos.',
    '23514': 'Alguno de los valores no cumple las reglas de la base de datos.',
    '22001': 'Uno de los campos excede la longitud permitida.',
    '22P02': 'Uno de los valores no tiene el tipo esperado.',
    '23502': 'Falta un campo obligatorio.',
    '2F002': 'La operación no está permitida.'
};

function noEncontrado(req, res) {
    res.status(404).render('errores/404', { titulo: 'Página no encontrada' });
}

// eslint-disable-next-line no-unused-vars -- Express identifica el manejador de
// errores por su aridad de 4 argumentos; quitar `next` lo rompe.
function manejadorErrores(err, req, res, next) {
    const esErrorDeUsuario = Boolean(MENSAJES_PG[err.code]);
    const estado = err.status || (esErrorDeUsuario ? 400 : 500);

    // El log del servidor guarda todo. La respuesta HTTP, no.
    console.error(`[error] ${estado} ${req.method} ${req.originalUrl}`,
        err.code ? `pg=${err.code}` : '', err.message);
    if (!esErrorDeUsuario) console.error(err.stack);

    if (res.headersSent) return;

    res.status(estado).render('errores/error', {
        titulo: estado === 400 ? 'No se pudo completar' : 'Error del servidor',
        mensaje: MENSAJES_PG[err.code]
            || 'Ocurrió un error al procesar la solicitud. Inténtalo de nuevo.'
    });
}

// Envuelve un controller async para que un rechazo llegue al manejador de
// errores en vez de quedar como promesa sin capturar (que en Node 15+ tumba
// el proceso). Se aplica en las rutas: asyncH(controller.getLista).
function asyncH(fn) {
    return (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);
}

module.exports = { noEncontrado, manejadorErrores, asyncH, MENSAJES_PG };
