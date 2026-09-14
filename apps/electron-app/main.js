// Proceso principal de Electron.
//
// El renderer corre aislado (contextIsolation, sin Node) y no puede hacer la
// peticion HTTP por su cuenta: desde un origen file:// el microservicio Flask
// bloquearia el fetch por CORS. Por eso la descarga del XML vive aqui y viaja
// al renderer por IPC como texto plano; el parseo se hace alla con DOMParser.

const { app, BrowserWindow, ipcMain, shell } = require('electron');
const path = require('path');
const http = require('http');
const https = require('https');

const TIEMPO_LIMITE_MS = 15000;
const TAMANO_MAXIMO_BYTES = 8 * 1024 * 1024;

let ventana = null;

function crearVentana() {
    ventana = new BrowserWindow({
        width: 1280,
        height: 860,
        minWidth: 420,
        minHeight: 520,
        backgroundColor: '#fef7ff',
        title: 'Libreria Online — Catalogo XML',
        show: false,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: true,
        },
    });

    ventana.loadFile(path.join(__dirname, 'renderer', 'index.html'));
    ventana.once('ready-to-show', () => ventana.show());

    // Cualquier enlace externo se abre en el navegador del sistema, nunca
    // dentro de la ventana de la aplicacion.
    ventana.webContents.setWindowOpenHandler(({ url }) => {
        if (/^https?:\/\//i.test(url)) shell.openExternal(url);
        return { action: 'deny' };
    });
}

/**
 * GET de un recurso XML. Resuelve siempre (no lanza): el renderer decide que
 * mensaje pintar a partir del objeto devuelto.
 */
function descargarXml(urlTexto) {
    return new Promise((resolve) => {
        let url;
        try {
            url = new URL(urlTexto);
        } catch {
            return resolve({ ok: false, error: 'La URL configurada no es valida.' });
        }
        if (url.protocol !== 'http:' && url.protocol !== 'https:') {
            return resolve({ ok: false, error: 'Solo se admiten direcciones http:// o https://.' });
        }

        const cliente = url.protocol === 'https:' ? https : http;
        const peticion = cliente.request(
            url,
            {
                method: 'GET',
                // El cliente es XML y nada mas: se pide XML por cabecera y el
                // parametro ?format=xml lo refuerza en la URL.
                headers: {
                    Accept: 'application/xml, text/xml;q=0.9',
                    'User-Agent': 'LibreriaElectron/1.0 (cliente XML)',
                },
                timeout: TIEMPO_LIMITE_MS,
            },
            (respuesta) => {
                const trozos = [];
                let bytes = 0;
                respuesta.setEncoding('utf8');
                respuesta.on('data', (trozo) => {
                    bytes += Buffer.byteLength(trozo, 'utf8');
                    if (bytes > TAMANO_MAXIMO_BYTES) {
                        respuesta.destroy();
                        return resolve({ ok: false, error: 'La respuesta del servicio es demasiado grande.' });
                    }
                    trozos.push(trozo);
                });
                respuesta.on('end', () =>
                    resolve({
                        ok: true,
                        estado: respuesta.statusCode,
                        tipo: respuesta.headers['content-type'] || '',
                        cuerpo: trozos.join(''),
                    }),
                );
            },
        );

        peticion.on('timeout', () => {
            peticion.destroy();
            resolve({ ok: false, error: `El servicio no respondio en ${TIEMPO_LIMITE_MS / 1000} s.` });
        });
        peticion.on('error', (error) => {
            // Mensaje util para el usuario, sin volcar la traza.
            const causas = {
                ECONNREFUSED: 'El servicio rechazo la conexion. Revisa la IP y el puerto.',
                ENOTFOUND: 'No se pudo resolver el host configurado.',
                EHOSTUNREACH: 'El host configurado no es alcanzable desde esta red.',
                ETIMEDOUT: 'Se agoto el tiempo de espera al conectar con el servicio.',
            };
            resolve({ ok: false, error: causas[error.code] || 'No se pudo contactar con el microservicio.' });
        });
        peticion.end();
    });
}

ipcMain.handle('catalogo:xml', (_evento, url) => descargarXml(String(url || '')));

app.whenReady().then(() => {
    crearVentana();
    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) crearVentana();
    });
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
});
