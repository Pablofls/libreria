// Puente minimo entre el renderer aislado y el proceso principal: una sola
// funcion, que devuelve el XML como texto. Nada de Node en el renderer.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('servicioXml', {
    obtener: (url) => ipcRenderer.invoke('catalogo:xml', url),
});
