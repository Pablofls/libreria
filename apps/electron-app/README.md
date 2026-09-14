# Cliente de escritorio Electron — catálogo en XML

Aplicación de escritorio (Electron) que consume **exclusivamente en XML** el
microservicio del catálogo de la librería y muestra los libros en tarjetas
Material Design: portada, título, autores, ISBN y precio.

- Endpoint por defecto: `http://34.51.80.53:5001/books?format=xml`
- **6 tarjetas por página** al arrancar, con paginación.
- Botón **Configurar servicio**: popup que pide IP, puerto y endpoint y los
  persiste en `localStorage`.
- Sin dependencias de terceros más allá de Electron: el XML se parsea con
  `DOMParser` y el estilo Material Design 3 está escrito a mano en CSS (no hay
  CDNs, la interfaz carga sin red).

---

## 1. Requisitos previos

| Requisito | Versión mínima | Cómo comprobarlo |
|---|---|---|
| Node.js | 18 (recomendado 20 o superior) | `node -v` |
| npm | 9 | `npm -v` |

Electron **no se instala globalmente**: se instala como dependencia de este
proyecto con `npm install` (paso 2). Eso descarga el binario de Electron dentro
de `node_modules/` (~200 MB la primera vez).

### Instalar Node.js si no lo tienes

**macOS** (con [Homebrew](https://brew.sh)):

```bash
brew install node
```

**macOS / Linux** (con nvm, si prefieres manejar varias versiones):

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
```

Después, en una terminal nueva:

```bash
nvm install 20
```

**Windows**: descarga el instalador LTS desde <https://nodejs.org> y ejecútalo.

---

## 2. Instalar la aplicación

Desde la raíz del repositorio:

```bash
cd apps/electron-app
```

```bash
npm install
```

Esto instala Electron (declarado en `package.json` como `devDependency`) y
descarga su binario. Si la descarga del binario falla por un proxy corporativo,
reintenta con:

```bash
npm install --verbose
```

---

## 3. Ejecutar la aplicación

```bash
npm start
```

Equivale a `npx electron .`. Se abre la ventana del catálogo y la aplicación
descarga el XML del servicio configurado.

Para cerrarla: cierra la ventana (en macOS, además `Cmd+Q`).

---

## 4. Uso

- **Recargar** vuelve a pedir el XML al servicio.
- **Configurar servicio** abre el popup con cuatro campos:
  - *IP o host* — por ejemplo `34.51.80.53` o `localhost`.
  - *Puerto* — `5001` por defecto; déjalo vacío para usar el puerto 80.
  - *Endpoint* — `/books`. Si escribes `books`, se le añade la barra inicial.
  - *Base de las portadas* (opcional) — el XML sólo trae el **nombre** del
    archivo de la imagen, así que hace falta la ruta pública que la sirve. Si lo
    dejas vacío se usa `http://<IP>/library/uploads`, que es donde el monolito
    publica las portadas en la VM.

  El popup muestra la **URL efectiva** mientras escribes, valida los datos antes
  de guardar y, al pulsar *Guardar y recargar*, escribe la configuración en
  `localStorage` (clave `libreria.electron.config`) y vuelve a cargar el
  catálogo. La configuración sobrevive al cierre de la aplicación.
- **Restablecer** deja los valores por defecto en el formulario (no guarda hasta
  que pulses *Guardar y recargar*).
- La paginación muestra 6 tarjetas por página; los botones *Anterior* /
  *Siguiente* y los números navegan entre páginas.

---

## 5. Cómo se consume el servicio (sólo XML)

1. La petición se hace desde el **proceso principal** (`main.js`), no desde la
   ventana: con la página cargada por `file://`, el navegador bloquearía el
   `fetch` al microservicio por CORS. El XML viaja al renderer por IPC.
2. Se pide XML por partida doble: cabecera `Accept: application/xml` y
   `?format=xml` añadido siempre a la URL.
3. Si el `Content-Type` de la respuesta no es XML, la aplicación lo rechaza con
   un mensaje explícito en lugar de intentar interpretarlo.
4. El XML se parsea con `DOMParser` y todo lo que viene del servicio se inserta
   con `textContent` — nunca con `innerHTML`.

Estructura del XML que se consume (recortada):

```xml
<library>
  <books count="31">
    <book isbn="978-1-942788-33-1">
      <title>Accelerate</title>
      <authors>
        <author order="1" nationality="Estadounidense">Nicole Forsgren</author>
      </authors>
      <price>780.00</price>
      <images>
        <image cover="true" type="image/png">
          <file>495a220b-….png</file>
          <alt>Portada del libro Accelerate</alt>
        </image>
      </images>
    </book>
  </books>
</library>
```

---

## 6. Archivos

| Archivo | Responsabilidad |
|---|---|
| `main.js` | Proceso principal: ventana, descarga HTTP del XML, IPC |
| `preload.js` | Puente aislado: expone una única función al renderer |
| `renderer/index.html` | Estructura de la interfaz y popup de configuración |
| `renderer/estilos.css` | Material Design 3 escrito a mano (claro y oscuro) |
| `renderer/renderer.js` | Configuración, parseo del XML, tarjetas y paginación |

La ventana corre con `contextIsolation`, `sandbox` y sin integración de Node, y
la página declara una CSP que sólo permite cargar imágenes remotas.

---

## 7. Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| «El servicio rechazó la conexión» | IP o puerto mal escritos, o el microservicio apagado. Compruébalo con `curl http://<IP>:5001/books`. |
| «El servicio no respondió en 15 s» | El host no es alcanzable desde tu red (firewall de la VM). |
| «Portada no disponible» en las tarjetas | La base de las portadas no apunta a donde se sirven las imágenes; ajústala en el popup. |
| `npm start` no encuentra Electron | Falta el paso 2: ejecuta `npm install` dentro de `apps/electron-app`. |
