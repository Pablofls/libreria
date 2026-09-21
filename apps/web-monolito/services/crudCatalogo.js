// Lógica de negocio compartida por los catálogos simples: autores, géneros,
// categorías, formatos y conceptos.
//
// Los cinco hacen exactamente lo mismo (listar, alta, edición, borrado con
// comprobación de uso) sobre tablas con la misma forma. Copiar el controller
// cinco veces significaría corregir cinco veces cada error; en su lugar, cada
// módulo declara aquí sus diferencias —nombre del modelo, textos, plantilla— y
// conserva su propio archivo *.controller.js como punto de entrada.
//
// Lo que NO se generaliza: la validación de cada entidad, que sí es propia
// (un autor tiene nacionalidad y biografía; un formato no).

const { entero } = require('./validacion');

/**
 * @param {object} cfg
 * @param {object} cfg.modelo      Modelo del módulo (getAll, getById, create…)
 * @param {string} cfg.ruta        Segmento de URL: 'autores', 'generos'…
 * @param {string} cfg.plural      'Autores'  — encabezado de la lista
 * @param {string} cfg.singular    'autor'    — usado en los mensajes
 * @param {function} cfg.validar   Devuelve { errores, datos }
 * @param {string} [cfg.vistaLista]  Plantilla de la lista (por defecto <ruta>/lista)
 * @param {string} [cfg.vistaForm]   Plantilla del formulario
 */
function crearControlador(cfg) {
    const vistaLista = cfg.vistaLista || `${cfg.ruta}/lista`;
    const vistaForm = cfg.vistaForm || `${cfg.ruta}/formulario`;
    const base = res => res.locals.base;

    async function getLista(req, res) {
        res.render(vistaLista, {
            titulo: cfg.plural,
            registros: await cfg.modelo.getAll()
        });
    }

    function getNuevo(req, res) {
        res.render(vistaForm, {
            titulo: `Nuevo ${cfg.singular}`,
            accion: `${base(res)}/${cfg.ruta}`,
            registro: null, errores: []
        });
    }

    async function postCrear(req, res) {
        const { errores, datos } = cfg.validar(req.body);

        if (errores.length) {
            return res.status(400).render(vistaForm, {
                titulo: `Nuevo ${cfg.singular}`,
                accion: `${base(res)}/${cfg.ruta}`,
                registro: req.body, errores
            });
        }

        try {
            await cfg.modelo.create(datos);
        } catch (err) {
            // 23505 = ya existe uno con ese nombre. Es un error del usuario, no
            // del sistema: se le devuelve el formulario, no una página de error.
            if (err.code !== '23505') throw err;
            return res.status(409).render(vistaForm, {
                titulo: `Nuevo ${cfg.singular}`,
                accion: `${base(res)}/${cfg.ruta}`,
                registro: req.body,
                errores: [`Ya existe un ${cfg.singular} con ese nombre.`]
            });
        }

        req.session.aviso = { tipo: 'exito', mensaje: `${cfg.plural}: registro creado.` };
        res.redirect(`${base(res)}/${cfg.ruta}`);
    }

    async function getEditar(req, res, next) {
        const id = entero(req.params.id);
        if (!id) return next();

        const registro = await cfg.modelo.getById(id);
        if (!registro) return next();

        res.render(vistaForm, {
            titulo: `Editar ${cfg.singular}`,
            accion: `${base(res)}/${cfg.ruta}/${id}/editar`,
            registro, errores: []
        });
    }

    async function postActualizar(req, res, next) {
        const id = entero(req.params.id);
        if (!id) return next();

        const { errores, datos } = cfg.validar(req.body);

        if (errores.length) {
            return res.status(400).render(vistaForm, {
                titulo: `Editar ${cfg.singular}`,
                accion: `${base(res)}/${cfg.ruta}/${id}/editar`,
                registro: { ...req.body, id }, errores
            });
        }

        try {
            const filas = await cfg.modelo.update(id, datos);
            if (!filas) return next();
        } catch (err) {
            if (err.code !== '23505') throw err;
            return res.status(409).render(vistaForm, {
                titulo: `Editar ${cfg.singular}`,
                accion: `${base(res)}/${cfg.ruta}/${id}/editar`,
                registro: { ...req.body, id },
                errores: [`Ya existe un ${cfg.singular} con ese nombre.`]
            });
        }

        req.session.aviso = { tipo: 'exito', mensaje: `${cfg.plural}: registro actualizado.` };
        res.redirect(`${base(res)}/${cfg.ruta}`);
    }

    async function postEliminar(req, res, next) {
        const id = entero(req.params.id);
        if (!id) return next();

        try {
            const filas = await cfg.modelo.remove(id);
            if (!filas) return next();
            req.session.aviso = { tipo: 'exito', mensaje: `${cfg.plural}: registro eliminado.` };
        } catch (err) {
            // 23503: la FK con ON DELETE RESTRICT lo impidió porque el registro
            // sigue en uso. Se traduce a un mensaje que dice qué hacer.
            if (err.code !== '23503') throw err;
            req.session.aviso = {
                tipo: 'error',
                mensaje: `No se puede eliminar: hay libros que usan este ${cfg.singular}. ` +
                         `Cámbialos primero.`
            };
        }
        res.redirect(`${base(res)}/${cfg.ruta}`);
    }

    return { getLista, getNuevo, postCrear, getEditar, postActualizar, postEliminar };
}

module.exports = { crearControlador };
