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
 * GET de un recurso (XML por defecto). Resuelve siempre (no lanza): el
 * renderer decide que mensaje pintar a partir del objeto devuelto.
 */
function descargar(urlTexto, accept = 'application/xml, text/xml;q=0.9') {
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
                // La vista del catalogo pide XML (y refuerza con ?format=xml);
                // el asistente pide JSON con ?format=json.
                headers: {
                    Accept: accept,
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

/* ------------------------------------------------------------- Ollama */

// Ollama corre en el contenedor Docker `ollama` y publica el 11434 en el
// equipo. La direccion es fija: el renderer no elige a donde se conecta.
const OLLAMA_HOST = '127.0.0.1';
const OLLAMA_PUERTO = 11434;
const OLLAMA_TIEMPO_LIMITE_MS = 120000; // la primera respuesta carga el modelo
const ROLES_VALIDOS = new Set(['system', 'user', 'assistant']);

let peticionOllama = null;

function validarPeticionChat(carga) {
    if (!carga || typeof carga !== 'object') return 'Peticion invalida.';
    if (typeof carga.modelo !== 'string' || !/^[\w.\-:/]{1,100}$/.test(carga.modelo)) {
        return 'El nombre del modelo no es valido.';
    }
    if (!Array.isArray(carga.mensajes) || carga.mensajes.length === 0 || carga.mensajes.length > 100) {
        return 'No hay mensajes que enviar.';
    }
    const mal = carga.mensajes.some(
        (m) => !m || !ROLES_VALIDOS.has(m.role) || typeof m.content !== 'string' || m.content.length > 60000,
    );
    return mal ? 'Los mensajes no tienen el formato esperado.' : null;
}

/**
 * POST a /api/chat de Ollama con streaming (NDJSON). Cada fragmento viaja al
 * renderer por 'ollama:fragmento'; la promesa resuelve al terminar. No lanza.
 */
function chatOllama(evento, carga) {
    return new Promise((resolve) => {
        const problema = validarPeticionChat(carga);
        if (problema) return resolve({ ok: false, error: problema });
        if (peticionOllama) peticionOllama.destroy();

        const cuerpo = JSON.stringify({
            model: carga.modelo,
            messages: carga.mensajes.map(({ role, content }) => ({ role, content })),
            stream: true,
            options: { num_ctx: 4096, temperature: 0.2, repeat_penalty: 1.1, num_predict: 400 },
        });
        const id = carga.id;
        let cancelada = false;
        let terminado = false;
        const terminar = (resultado) => {
            if (terminado) return;
            terminado = true;
            peticionOllama = null;
            resolve(resultado);
        };

        const peticion = http.request(
            {
                host: OLLAMA_HOST,
                port: OLLAMA_PUERTO,
                path: '/api/chat',
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(cuerpo) },
                timeout: OLLAMA_TIEMPO_LIMITE_MS,
            },
            (respuesta) => {
                respuesta.setEncoding('utf8');

                if (respuesta.statusCode !== 200) {
                    let texto = '';
                    respuesta.on('data', (t) => { texto += t; });
                    respuesta.on('end', () => {
                        let detalle = '';
                        try { detalle = JSON.parse(texto).error || ''; } catch { /* cuerpo no JSON */ }
                        if (/not found/i.test(detalle)) {
                            return terminar({
                                ok: false,
                                error: `El modelo "${carga.modelo}" no esta instalado. Instalalo con: docker exec -it ollama ollama pull ${carga.modelo}`,
                            });
                        }
                        terminar({ ok: false, error: 'Ollama respondio con un error. Revisa los registros del contenedor.' });
                    });
                    return;
                }

                let pendiente = '';
                const procesar = (linea) => {
                    if (!linea.trim()) return;
                    let dato;
                    try { dato = JSON.parse(linea); } catch { return; }
                    if (dato.error) return terminar({ ok: false, error: 'Ollama devolvio un error durante la respuesta.' });
                    const texto = dato.message && dato.message.content;
                    if (texto && !evento.sender.isDestroyed()) evento.sender.send('ollama:fragmento', { id, texto });
                    if (dato.done && !evento.sender.isDestroyed()) evento.sender.send('ollama:fragmento', { id, fin: true });
                };
                respuesta.on('data', (trozo) => {
                    pendiente += trozo;
                    const lineas = pendiente.split('\n');
                    pendiente = lineas.pop();
                    lineas.forEach(procesar);
                });
                respuesta.on('end', () => {
                    procesar(pendiente);
                    terminar({ ok: true, cancelada });
                });
                respuesta.on('close', () => terminar({ ok: true, cancelada }));
            },
        );

        peticion.on('timeout', () => {
            peticion.destroy();
            terminar({ ok: false, error: `Ollama no respondio en ${OLLAMA_TIEMPO_LIMITE_MS / 1000} s.` });
        });
        peticion.on('error', (error) => {
            if (cancelada) return terminar({ ok: true, cancelada: true });
            const causas = {
                ECONNREFUSED: 'Ollama no responde. Inicia el contenedor con: docker start ollama',
                ECONNRESET: 'Se corto la conexion con Ollama.',
            };
            terminar({ ok: false, error: causas[error.code] || 'No se pudo contactar con Ollama en localhost:11434.' });
        });
        peticion.cancelar = () => {
            cancelada = true;
            peticion.destroy();
        };

        peticionOllama = peticion;
        peticion.write(cuerpo);
        peticion.end();
    });
}

ipcMain.handle('catalogo:xml', (_evento, url) => descargar(String(url || '')));
ipcMain.handle('catalogo:json', (_evento, url) => descargar(String(url || ''), 'application/json'));
ipcMain.handle('ollama:chat', chatOllama);
ipcMain.handle('ollama:cancelar', () => {
    if (peticionOllama) peticionOllama.cancelar();
});

app.whenReady().then(() => {
    crearVentana();
    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) crearVentana();
    });
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
});
