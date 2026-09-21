// Validación server-side. Es la única que cuenta.
//
// Los formularios llevan `required`, `type="number"`, `minlength`… pero eso es
// ayuda visual: cualquiera puede enviar un POST con curl saltándose el
// navegador. Todo lo que entra por req.body pasa por aquí antes de tocar la BD.
//
// Cada validador devuelve un arreglo de mensajes. Vacío = válido.

const LIMITES = {
    nombre: 100, email: 150, titulo: 200, isbn: 17,
    catalogo: 80, termino: 150, alt: 200, biografia: 5000, sinopsis: 5000
};

function texto(valor) {
    return typeof valor === 'string' ? valor.trim() : '';
}

// Entero estricto: '12abc' no es 12. parseInt lo aceptaría.
function entero(valor) {
    const s = texto(valor);
    return /^-?\d+$/.test(s) ? parseInt(s, 10) : null;
}

function decimal(valor) {
    const s = texto(valor);
    return /^\d+(\.\d{1,2})?$/.test(s) ? Number(s) : null;
}

// Lista de ids que llega de un <select multiple>. Express da string si viene un
// solo valor y arreglo si vienen varios; hay que normalizar antes de validar.
function listaIds(valor) {
    const bruto = valor === undefined ? [] : (Array.isArray(valor) ? valor : [valor]);
    const ids = bruto.map(entero).filter(n => n !== null && n > 0);
    return [...new Set(ids)];
}

function requerido(errores, valor, etiqueta, maximo) {
    const v = texto(valor);
    if (!v) errores.push(`${etiqueta} es obligatorio.`);
    else if (maximo && v.length > maximo) errores.push(`${etiqueta} no puede pasar de ${maximo} caracteres.`);
    return v;
}

function opcional(errores, valor, etiqueta, maximo) {
    const v = texto(valor);
    if (v && maximo && v.length > maximo) errores.push(`${etiqueta} no puede pasar de ${maximo} caracteres.`);
    return v || null;
}

// --- Reglas de negocio reutilizables ----------------------------------------

const RE_EMAIL = /^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$/;
// ISBN-10 o ISBN-13, con o sin guiones. Misma regla que ck_libros_isbn.
const RE_ISBN = /^[0-9-]{9,16}[0-9Xx]$/;

// Política de contraseñas: 8+ caracteres, con al menos una letra y un dígito.
// Deliberadamente simple y explicada al usuario en el formulario. Reglas más
// exóticas (símbolos obligatorios) empujan a la gente a patrones predecibles.
function validarPassword(errores, password, obligatoria = true) {
    const p = typeof password === 'string' ? password : '';
    if (!p) {
        if (obligatoria) errores.push('La contraseña es obligatoria.');
        return null;
    }
    if (p.length < 8) errores.push('La contraseña debe tener al menos 8 caracteres.');
    if (p.length > 72) errores.push('La contraseña no puede pasar de 72 caracteres (límite de bcrypt).');
    if (!/[A-Za-zÁÉÍÓÚáéíóúÑñ]/.test(p)) errores.push('La contraseña debe incluir al menos una letra.');
    if (!/\d/.test(p)) errores.push('La contraseña debe incluir al menos un número.');
    return p;
}

function validarEmail(errores, valor) {
    const v = requerido(errores, valor, 'El correo', LIMITES.email);
    if (v && !RE_EMAIL.test(v)) errores.push('El correo no tiene un formato válido.');
    return v.toLowerCase();
}

// --- Validadores por entidad -------------------------------------------------

function validarRegistro(body) {
    const errores = [];
    const datos = {
        nombre: requerido(errores, body.nombre, 'El nombre', LIMITES.nombre),
        email: validarEmail(errores, body.email),
        password: validarPassword(errores, body.password)
    };
    return { errores, datos };
}

function validarUsuario(body, { esEdicion = false } = {}) {
    const errores = [];
    const rol = texto(body.rol) || 'lector';
    if (!['lector', 'admin'].includes(rol)) errores.push('El rol no es válido.');

    const datos = {
        nombre: requerido(errores, body.nombre, 'El nombre', LIMITES.nombre),
        email: validarEmail(errores, body.email),
        rol,
        // En edición, contraseña vacía significa "no cambiar".
        password: validarPassword(errores, body.password, !esEdicion),
        activo: body.activo === 'true' || body.activo === 'on' || body.activo === undefined
    };
    return { errores, datos };
}

function validarLibro(body) {
    const errores = [];

    const isbn = requerido(errores, body.isbn, 'El ISBN', LIMITES.isbn);
    if (isbn && !RE_ISBN.test(isbn)) {
        errores.push('El ISBN debe tener 10 o 13 dígitos, con o sin guiones.');
    }

    const precio = decimal(body.precio);
    if (precio === null) errores.push('El precio debe ser un número con hasta dos decimales.');
    else if (precio < 0) errores.push('El precio no puede ser negativo.');
    else if (precio > 99999999) errores.push('El precio es demasiado grande.');

    const stock = entero(body.stock);
    if (stock === null) errores.push('El stock debe ser un número entero.');
    else if (stock < 0) errores.push('El stock no puede ser negativo.');

    let anio = null;
    if (texto(body.anio_publicacion)) {
        anio = entero(body.anio_publicacion);
        if (anio === null) errores.push('El año de publicación debe ser un número.');
        else if (anio < 1450 || anio > 2100) errores.push('El año de publicación debe estar entre 1450 y 2100.');
    }

    const categoria_id = entero(body.categoria_id);
    if (!categoria_id) errores.push('Debes elegir una categoría.');
    const formato_id = entero(body.formato_id);
    if (!formato_id) errores.push('Debes elegir un formato.');

    const autores = listaIds(body.autores);
    if (!autores.length) errores.push('El libro debe tener al menos un autor.');
    const generos = listaIds(body.generos);

    return {
        errores,
        datos: {
            isbn,
            titulo: requerido(errores, body.titulo, 'El título', LIMITES.titulo),
            anio_publicacion: anio,
            sinopsis: opcional(errores, body.sinopsis, 'La sinopsis', LIMITES.sinopsis),
            precio, stock, categoria_id, formato_id, autores, generos
        }
    };
}

// autores, generos, categorias y formatos comparten forma: nombre + descripción.
function validarCatalogo(body, etiquetaNombre = 'El nombre') {
    const errores = [];
    const datos = {
        nombre: requerido(errores, body.nombre, etiquetaNombre, LIMITES.catalogo),
        descripcion: opcional(errores, body.descripcion, 'La descripción', LIMITES.biografia)
    };
    return { errores, datos };
}

function validarAutor(body) {
    const errores = [];
    const datos = {
        nombre: requerido(errores, body.nombre, 'El nombre', 120),
        biografia: opcional(errores, body.biografia, 'La biografía', LIMITES.biografia),
        nacionalidad: opcional(errores, body.nacionalidad, 'La nacionalidad', LIMITES.catalogo)
    };
    return { errores, datos };
}

function validarConceptoLibro(body) {
    const errores = [];
    let pagina = null;
    if (texto(body.pagina)) {
        pagina = entero(body.pagina);
        if (pagina === null || pagina < 1) errores.push('La página debe ser un número mayor que cero.');
    }
    const datos = {
        termino: requerido(errores, body.termino, 'El término', LIMITES.termino),
        definicion: requerido(errores, body.definicion, 'La definición', LIMITES.biografia),
        capitulo: opcional(errores, body.capitulo, 'El capítulo', LIMITES.catalogo),
        pagina
    };
    return { errores, datos };
}

function validarImagen(body) {
    const errores = [];
    const datos = {
        texto_alternativo: opcional(errores, body.texto_alternativo, 'El texto alternativo', LIMITES.alt),
        es_portada: body.es_portada === 'true' || body.es_portada === 'on'
    };
    if (!datos.texto_alternativo) {
        errores.push('El texto alternativo es obligatorio: describe la imagen para quien usa lector de pantalla.');
    }
    return { errores, datos };
}

module.exports = {
    texto, entero, decimal, listaIds,
    validarRegistro, validarUsuario, validarLibro, validarCatalogo,
    validarAutor, validarConceptoLibro, validarImagen, validarPassword
};
