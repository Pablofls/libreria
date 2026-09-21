// Subida de imágenes con Multer, endurecida.
//
// Amenazas que se atienden aquí:
//   1. Subir un .php/.js/.sh y lograr que el servidor lo ejecute.
//   2. Nombres con "../" para escribir fuera de uploads/ (path traversal).
//   3. Archivos enormes que llenen el disco de la VM.
//   4. Un archivo que dice ser .png en el nombre pero no lo es.
//
// Controles, en orden:
//   - El nombre lo GENERA el servidor (uuid v4 + extensión de la lista blanca).
//     El nombre que envió el usuario nunca toca el sistema de archivos; se
//     guarda sólo como metadato en la columna nombre_original.
//   - Lista blanca de extensiones Y de tipos MIME. Ambas, porque cada una se
//     puede falsificar por separado.
//   - Límite de tamaño en Multer (rechaza antes de escribir en disco) y también
//     en la BD (ck_imagenes_tamano), por si alguien inserta por otra vía.
//   - Verificación de los bytes iniciales del archivo ya escrito: si la firma
//     no corresponde a JPEG/PNG/WebP, se borra. Un .php renombrado a .png pasa
//     el filtro de extensión y el de MIME (el navegador lo declara), pero no
//     esta comprobación.

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const multer = require('multer');
const config = require('../config/env');

const DIRECTORIO = path.resolve(__dirname, '..', config.subidas.directorio);
fs.mkdirSync(DIRECTORIO, { recursive: true });

// Lista blanca: MIME declarado -> extensión que usará el servidor.
const TIPOS_PERMITIDOS = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp'
};
const EXTENSIONES_PERMITIDAS = ['.jpg', '.jpeg', '.png', '.webp'];

// Firmas (magic numbers) de los formatos aceptados.
const FIRMAS = [
    { mime: 'image/jpeg', bytes: [0xFF, 0xD8, 0xFF] },
    { mime: 'image/png', bytes: [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A] },
    // WebP: "RIFF" .... "WEBP"; se comprueba en dos tramos.
    { mime: 'image/webp', bytes: [0x52, 0x49, 0x46, 0x46], desplazado: { pos: 8, bytes: [0x57, 0x45, 0x42, 0x50] } }
];

const almacenamiento = multer.diskStorage({
    destination: (req, file, cb) => cb(null, DIRECTORIO),
    filename: (req, file, cb) => {
        // uuid v4 + extensión de la lista blanca. Sin rastro del nombre original,
        // así que no hay forma de inyectar "../" ni una doble extensión.
        const extension = TIPOS_PERMITIDOS[file.mimetype] || '.png';
        cb(null, `${crypto.randomUUID()}${extension}`);
    }
});

function filtro(req, file, cb) {
    const extension = path.extname(file.originalname || '').toLowerCase();
    if (!TIPOS_PERMITIDOS[file.mimetype]) {
        return cb(Object.assign(new Error('TIPO_NO_PERMITIDO'), { code: 'TIPO_NO_PERMITIDO' }));
    }
    if (!EXTENSIONES_PERMITIDAS.includes(extension)) {
        return cb(Object.assign(new Error('EXTENSION_NO_PERMITIDA'), { code: 'EXTENSION_NO_PERMITIDA' }));
    }
    cb(null, true);
}

const subir = multer({
    storage: almacenamiento,
    fileFilter: filtro,
    limits: {
        fileSize: config.subidas.tamanoMaximo,
        files: 1,
        fields: 12,
        fieldSize: 100 * 1024
    }
});

// Lee la cabecera del archivo ya escrito y confirma que los bytes correspondan
// a una imagen real de los formatos aceptados.
function firmaValida(rutaAbsoluta) {
    let fd;
    try {
        fd = fs.openSync(rutaAbsoluta, 'r');
        const buffer = Buffer.alloc(12);
        const leidos = fs.readSync(fd, buffer, 0, 12, 0);
        if (leidos < 4) return null;

        for (const firma of FIRMAS) {
            const coincideInicio = firma.bytes.every((b, i) => buffer[i] === b);
            if (!coincideInicio) continue;
            if (firma.desplazado) {
                const ok = firma.desplazado.bytes.every((b, i) => buffer[firma.desplazado.pos + i] === b);
                if (!ok) continue;
            }
            return firma.mime;
        }
        return null;
    } catch {
        return null;
    } finally {
        if (fd !== undefined) fs.closeSync(fd);
    }
}

function borrarArchivo(nombre) {
    if (!nombre) return;
    // Defensa adicional: se resuelve la ruta y se confirma que sigue dentro de
    // uploads/. Si algún día el nombre viniera de otro lado, no se borra fuera.
    const destino = path.resolve(DIRECTORIO, nombre);
    if (!destino.startsWith(DIRECTORIO + path.sep)) return;
    fs.promises.unlink(destino).catch(() => { /* ya no existía */ });
}

// Envuelve upload.single() para traducir los errores de Multer a mensajes que
// el controller pueda mostrar, y para ejecutar la comprobación de firma.
function subirImagen(campo) {
    const middlewareMulter = subir.single(campo);

    return function (req, res, next) {
        middlewareMulter(req, res, err => {
            if (err) {
                const mensajes = {
                    LIMIT_FILE_SIZE: `La imagen supera el máximo de ${Math.round(config.subidas.tamanoMaximo / 1024 / 1024)} MB.`,
                    TIPO_NO_PERMITIDO: 'Sólo se aceptan imágenes JPG, PNG o WebP.',
                    EXTENSION_NO_PERMITIDA: 'La extensión del archivo no está permitida.',
                    LIMIT_FILE_COUNT: 'Sólo se puede subir una imagen a la vez.'
                };
                req.errorSubida = mensajes[err.code] || 'No se pudo procesar el archivo.';
                if (req.file) borrarArchivo(req.file.filename);
                return next();
            }

            if (req.file) {
                const mimeReal = firmaValida(req.file.path);
                if (!mimeReal || mimeReal !== req.file.mimetype) {
                    // El contenido no es la imagen que decía ser: se borra.
                    console.warn(`[subida] firma inválida: declarado=${req.file.mimetype} real=${mimeReal || 'desconocido'}`);
                    borrarArchivo(req.file.filename);
                    req.file = undefined;
                    req.errorSubida = 'El archivo no es una imagen JPG, PNG o WebP válida.';
                }
            }
            next();
        });
    };
}

module.exports = { subirImagen, borrarArchivo, DIRECTORIO, TIPOS_PERMITIDOS };
