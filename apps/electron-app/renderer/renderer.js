'use strict';

/* Renderer: configuracion en localStorage, descarga por IPC y pintado de las
   tarjetas. El XML se parsea con DOMParser y todo lo que viene del servicio se
   inserta con textContent — nunca con innerHTML. */

const CLAVE_CONFIG = 'libreria.electron.config';
const POR_PAGINA = 6;

const CONFIG_DEFECTO = Object.freeze({
    ip: '34.51.80.53',
    puerto: '5001',
    endpoint: '/books',
    imagenes: '',
});

const dinero = new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN' });

const el = (id) => document.getElementById(id);
const nodos = {
    origen: el('origen'),
    rejilla: el('rejilla'),
    resumen: el('resumen'),
    chipTotal: el('chip-total'),
    chipPagina: el('chip-pagina'),
    paginacion: el('paginacion'),
    numeros: el('paginacion-numeros'),
    anterior: el('btn-anterior'),
    siguiente: el('btn-siguiente'),
    cargando: el('estado-cargando'),
    error: el('estado-error'),
    errorTexto: el('estado-error-texto'),
    dialogo: el('dialogo-config'),
    dialogoError: el('dialogo-error'),
    vistaPrevia: el('vista-previa-url'),
    campoIp: el('campo-ip'),
    campoPuerto: el('campo-puerto'),
    campoEndpoint: el('campo-endpoint'),
    campoImagenes: el('campo-imagenes'),
};

let libros = [];
let pagina = 1;

/* ---------------------------------------------------------------- Config */

function leerConfig() {
    try {
        const guardado = JSON.parse(window.localStorage.getItem(CLAVE_CONFIG) || '{}');
        return { ...CONFIG_DEFECTO, ...(guardado && typeof guardado === 'object' ? guardado : {}) };
    } catch {
        // localStorage corrupto o inaccesible: se sigue con los valores por defecto.
        return { ...CONFIG_DEFECTO };
    }
}

function guardarConfig(config) {
    try {
        window.localStorage.setItem(CLAVE_CONFIG, JSON.stringify(config));
        return true;
    } catch {
        return false;
    }
}

function construirUrl(config) {
    const host = String(config.ip || '').trim().replace(/^https?:\/\//i, '').replace(/\/+$/, '');
    const puerto = String(config.puerto || '').trim();
    let endpoint = String(config.endpoint || '').trim() || '/';
    if (!endpoint.startsWith('/')) endpoint = `/${endpoint}`;
    const base = `http://${host}${puerto ? `:${puerto}` : ''}${endpoint}`;
    // El cliente es XML y nada mas: el parametro se fuerza siempre, aunque el
    // servicio ya responda XML por defecto.
    const url = new URL(base);
    url.searchParams.set('format', 'xml');
    return url.toString();
}

function baseImagenes(config) {
    const propia = String(config.imagenes || '').trim();
    if (propia) return propia.replace(/\/+$/, '');
    // El XML solo trae el nombre del archivo; el monolito las publica bajo
    // /library/uploads en el mismo host del microservicio.
    const host = String(config.ip || '').trim().replace(/^https?:\/\//i, '').replace(/\/+$/, '');
    return `http://${host}/library/uploads`;
}

/* ----------------------------------------------------------------- XML */

function texto(padre, selector) {
    const encontrado = padre.querySelector(selector);
    return encontrado ? encontrado.textContent.trim() : '';
}

function librosDesdeXml(cadena) {
    const doc = new DOMParser().parseFromString(cadena, 'application/xml');
    if (doc.querySelector('parsererror')) {
        throw new Error('La respuesta no es XML bien formado.');
    }

    const error = doc.querySelector('error');
    if (error && !doc.querySelector('book')) {
        throw new Error(texto(error, 'message') || 'El servicio devolvio un error en XML.');
    }

    return Array.from(doc.querySelectorAll('book')).map((libro) => {
        const autores = Array.from(libro.querySelectorAll('authors > author'))
            .sort((a, b) => Number(a.getAttribute('order') || 0) - Number(b.getAttribute('order') || 0))
            .map((autor) => autor.textContent.trim())
            .filter(Boolean);

        const imagenes = Array.from(libro.querySelectorAll('images > image'));
        const portada = imagenes.find((img) => img.getAttribute('cover') === 'true') || imagenes[0] || null;

        const precio = Number.parseFloat(texto(libro, 'price'));

        return {
            isbn: libro.getAttribute('isbn') || texto(libro, 'isbn') || 'Sin ISBN',
            titulo: texto(libro, 'title') || 'Sin titulo',
            autores,
            precio: Number.isFinite(precio) ? precio : null,
            archivo: portada ? texto(portada, 'file') : '',
            alt: portada ? (portada.querySelector('alt')?.textContent.trim() || '') : '',
        };
    });
}

/* -------------------------------------------------------------- Pintado */

function mostrar(estado) {
    nodos.cargando.hidden = estado !== 'cargando';
    nodos.error.hidden = estado !== 'error';
    const hayDatos = estado === 'datos';
    nodos.rejilla.hidden = !hayDatos;
    nodos.resumen.hidden = !hayDatos;
    nodos.paginacion.hidden = !hayDatos;
}

function crearTarjeta(libro, base) {
    const tarjeta = document.createElement('article');
    tarjeta.className = 'tarjeta';

    const media = document.createElement('div');
    media.className = 'tarjeta__media';

    if (libro.archivo) {
        const imagen = document.createElement('img');
        imagen.className = 'tarjeta__imagen';
        imagen.loading = 'lazy';
        imagen.alt = libro.alt || `Portada de ${libro.titulo}`;
        imagen.src = `${base}/${encodeURIComponent(libro.archivo)}`;
        imagen.addEventListener('error', () => {
            imagen.replaceWith(marcadorSinImagen());
        });
        media.appendChild(imagen);
    } else {
        media.appendChild(marcadorSinImagen());
    }

    if (libro.precio !== null) {
        const precio = document.createElement('span');
        precio.className = 'tarjeta__precio';
        precio.textContent = dinero.format(libro.precio);
        media.appendChild(precio);
    }

    const cuerpo = document.createElement('div');
    cuerpo.className = 'tarjeta__cuerpo';

    const titulo = document.createElement('h2');
    titulo.className = 'tarjeta__titulo';
    titulo.textContent = libro.titulo;

    const autores = document.createElement('p');
    autores.className = 'tarjeta__autores';
    autores.textContent = libro.autores.length ? libro.autores.join(' · ') : 'Autor no registrado';

    const isbn = document.createElement('p');
    isbn.className = 'tarjeta__isbn';
    const etiqueta = document.createElement('strong');
    etiqueta.textContent = 'ISBN ';
    isbn.append(etiqueta, document.createTextNode(libro.isbn));

    cuerpo.append(titulo, autores, isbn);
    tarjeta.append(media, cuerpo);
    return tarjeta;
}

function marcadorSinImagen() {
    const hueco = document.createElement('div');
    hueco.className = 'tarjeta__sin-imagen';
    const icono = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    icono.setAttribute('viewBox', '0 0 24 24');
    icono.setAttribute('width', '40');
    icono.setAttribute('height', '40');
    const trazo = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    trazo.setAttribute('fill', 'currentColor');
    trazo.setAttribute('d', 'M21 19V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2M8.5 13.5l2.5 3 3.5-4.5 4.5 6H5z');
    icono.appendChild(trazo);
    hueco.append(icono, document.createTextNode('Portada no disponible'));
    return hueco;
}

function totalPaginas() {
    return Math.max(1, Math.ceil(libros.length / POR_PAGINA));
}

function pintarPagina() {
    const total = totalPaginas();
    pagina = Math.min(Math.max(1, pagina), total);

    const desde = (pagina - 1) * POR_PAGINA;
    const visibles = libros.slice(desde, desde + POR_PAGINA);
    const base = baseImagenes(leerConfig());

    nodos.rejilla.replaceChildren(...visibles.map((libro) => crearTarjeta(libro, base)));

    nodos.chipTotal.textContent = `${libros.length} ${libros.length === 1 ? 'libro' : 'libros'} en el catalogo`;
    nodos.chipPagina.textContent = `Pagina ${pagina} de ${total} · ${POR_PAGINA} por pagina`;

    pintarPaginacion(total);
    nodos.rejilla.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

function pintarPaginacion(total) {
    nodos.anterior.disabled = pagina === 1;
    nodos.siguiente.disabled = pagina === total;

    // Ventana de numeros: primera, ultima, la actual y sus vecinas; el resto,
    // puntos suspensivos.
    const mostrarNumero = (n) => n === 1 || n === total || Math.abs(n - pagina) <= 1;
    const botones = [];
    let hueco = false;

    for (let n = 1; n <= total; n += 1) {
        if (!mostrarNumero(n)) {
            if (!hueco) {
                const puntos = document.createElement('span');
                puntos.className = 'pagina pagina--hueco';
                puntos.textContent = '…';
                botones.push(puntos);
                hueco = true;
            }
            continue;
        }
        hueco = false;
        const boton = document.createElement('button');
        boton.type = 'button';
        boton.className = 'pagina';
        boton.textContent = String(n);
        if (n === pagina) boton.setAttribute('aria-current', 'page');
        boton.addEventListener('click', () => {
            pagina = n;
            pintarPagina();
        });
        botones.push(boton);
    }

    nodos.numeros.replaceChildren(...botones);
}

/* ---------------------------------------------------------------- Carga */

async function cargarCatalogo() {
    const config = leerConfig();
    const url = construirUrl(config);
    nodos.origen.textContent = url;
    mostrar('cargando');

    const respuesta = await window.servicioXml.obtener(url);

    if (!respuesta.ok) return fallar(respuesta.error);
    if (respuesta.estado !== 200) {
        return fallar(`El servicio respondio con el codigo HTTP ${respuesta.estado}.`);
    }
    if (respuesta.tipo && !/xml/i.test(respuesta.tipo)) {
        return fallar(`El servicio respondio "${respuesta.tipo}" y esta aplicacion solo consume XML.`);
    }

    try {
        libros = librosDesdeXml(respuesta.cuerpo);
    } catch (error) {
        return fallar(error.message);
    }

    if (libros.length === 0) return fallar('El XML se leyo correctamente pero no contiene libros.');

    pagina = 1;
    mostrar('datos');
    pintarPagina();
}

function fallar(mensaje) {
    libros = [];
    nodos.errorTexto.textContent = mensaje;
    mostrar('error');
}

/* ------------------------------------------------------------- Dialogo */

function urlDeFormulario() {
    return construirUrl({
        ip: nodos.campoIp.value,
        puerto: nodos.campoPuerto.value,
        endpoint: nodos.campoEndpoint.value,
    });
}

function refrescarVistaPrevia() {
    try {
        nodos.vistaPrevia.textContent = urlDeFormulario();
    } catch {
        nodos.vistaPrevia.textContent = 'La combinacion de IP, puerto y endpoint no forma una URL valida.';
    }
}

function abrirDialogo() {
    const config = leerConfig();
    nodos.campoIp.value = config.ip;
    nodos.campoPuerto.value = config.puerto;
    nodos.campoEndpoint.value = config.endpoint;
    nodos.campoImagenes.value = config.imagenes;
    nodos.dialogoError.hidden = true;
    refrescarVistaPrevia();
    nodos.dialogo.showModal();
}

function validar() {
    const ip = nodos.campoIp.value.trim();
    const puerto = nodos.campoPuerto.value.trim();
    const endpoint = nodos.campoEndpoint.value.trim();

    if (!ip) return 'Escribe la IP o el host del microservicio.';
    if (/\s/.test(ip)) return 'La IP o el host no puede contener espacios.';
    if (puerto && !/^\d{1,5}$/.test(puerto)) return 'El puerto debe ser un numero.';
    if (puerto && (Number(puerto) < 1 || Number(puerto) > 65535)) return 'El puerto debe estar entre 1 y 65535.';
    if (!endpoint) return 'Escribe el endpoint, por ejemplo /books.';
    try {
        urlDeFormulario();
    } catch {
        return 'La combinacion de IP, puerto y endpoint no forma una URL valida.';
    }
    return null;
}

function guardarYRecargar() {
    const problema = validar();
    if (problema) {
        nodos.dialogoError.textContent = problema;
        nodos.dialogoError.hidden = false;
        return;
    }
    const guardado = guardarConfig({
        ip: nodos.campoIp.value.trim(),
        puerto: nodos.campoPuerto.value.trim(),
        endpoint: nodos.campoEndpoint.value.trim(),
        imagenes: nodos.campoImagenes.value.trim(),
    });
    if (!guardado) {
        nodos.dialogoError.textContent = 'No se pudo escribir en localStorage; la configuracion no quedara guardada.';
        nodos.dialogoError.hidden = false;
        return;
    }
    nodos.dialogo.close();
    cargarCatalogo();
}

/* ---------------------------------------------------------------- Eventos */

el('btn-config').addEventListener('click', abrirDialogo);
el('btn-error-config').addEventListener('click', abrirDialogo);
el('btn-recargar').addEventListener('click', cargarCatalogo);
el('btn-cancelar').addEventListener('click', () => nodos.dialogo.close());
el('btn-guardar').addEventListener('click', guardarYRecargar);
el('btn-restablecer').addEventListener('click', () => {
    nodos.campoIp.value = CONFIG_DEFECTO.ip;
    nodos.campoPuerto.value = CONFIG_DEFECTO.puerto;
    nodos.campoEndpoint.value = CONFIG_DEFECTO.endpoint;
    nodos.campoImagenes.value = CONFIG_DEFECTO.imagenes;
    nodos.dialogoError.hidden = true;
    refrescarVistaPrevia();
});

[nodos.campoIp, nodos.campoPuerto, nodos.campoEndpoint].forEach((campo) =>
    campo.addEventListener('input', refrescarVistaPrevia),
);

nodos.anterior.addEventListener('click', () => {
    pagina -= 1;
    pintarPagina();
});
nodos.siguiente.addEventListener('click', () => {
    pagina += 1;
    pintarPagina();
});

el('form-config').addEventListener('submit', (evento) => {
    evento.preventDefault();
    guardarYRecargar();
});

cargarCatalogo();
