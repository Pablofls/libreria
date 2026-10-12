// Puente minimo entre el renderer aislado y el proceso principal. Nada de Node
// en el renderer: solo estas funciones, cada una atada a un canal IPC.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('servicioXml', {
    obtener: (url) => ipcRenderer.invoke('catalogo:xml', url),
});

contextBridge.exposeInMainWorld('asistenteApi', {
    catalogoJson: (url) => ipcRenderer.invoke('catalogo:json', url),
    chat: (carga) => ipcRenderer.invoke('ollama:chat', carga),
    cancelar: () => ipcRenderer.invoke('ollama:cancelar'),
    // El evento de Electron no se expone: el renderer solo recibe los datos.
    alFragmento: (callback) => ipcRenderer.on('ollama:fragmento', (_evento, dato) => callback(dato)),
});
