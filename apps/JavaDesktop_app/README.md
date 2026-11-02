# Librería Online — cliente de escritorio Java

Aplicación de escritorio **JavaFX** que actúa como cliente del proyecto Library:
inicia sesión con JWT, muestra el catálogo con portadas, maneja una cesta, simula
la compra (pedido + pago reales), lista "Mis compras" y **rastrea la entrega en un
mapa de Monterrey actualizado por WebSockets**. No se conecta a PostgreSQL: todo
pasa por los microservicios de la VM en GCP.

```
                         HTTPS 443 (nginx, certificado autofirmado)
 App JavaFX ───────────────────────────────────────────────────────────────┐
  │ REST/JSON + Authorization: Bearer <JWT>                                  │
  │   /login /token/refresh /logout ─► login    (5000)                       │
  │   /users/{id}                   ─► users    (5003)                       │
  │   /books, /books/search         ─► catalogo (5002)   ─┐                  │
  │   /authors…                     ─► authors  (5004)    │                  │
  │   /orders…                      ─► pedidos  (5005)    ├─► PostgreSQL     │
  │   /payments…                    ─► pagos    (5006)    │                  │
  │   /uploads/<uuid>.png           ─► portadas           │                  │
  │ SOAP/XML  /soap (JWT por auth_request) ─► soap (5001) ─┘                  │
  │ WebSocket /track/ws?code=…      ─► gps (5900) ── GET /orders/{id} con el │
  │                                     mismo JWT ─► pedidos (¿es suyo?)     │
  └► WebView: Leaflet + OpenStreetMap (sólo dibuja lo que Java le pasa) ─────┘
```

## Requisitos y arranque

- JDK 21 (`brew install openjdk@21`) y Maven (`brew install maven`).
- La copia del certificado de la VM en `~/libreria-api.crt`.
- Internet en el Mac (tiles de OpenStreetMap y Leaflet desde unpkg).

```bash
cd apps/JavaDesktop_app
bash ejecutar.sh
```

`ejecutar.sh` fija `JAVA_HOME` al JDK 21 y corre `mvn javafx:run`. Hace falta
porque el Maven de Homebrew trae un JDK más nuevo y JavaFX 21 necesita el módulo
`jdk.jsobject`, que los JDK 24+ ya no incluyen.

Pruebas (sin red): `mvn test`.

### Configuración

Por variable de entorno o en `config.properties` (copiar de
`config.properties.example`; no se versiona):

| Clave | Por omisión | Qué es |
|---|---|---|
| `API_BASE` | `https://34.51.108.167` | nginx de la VM |
| `CA_CERT` | `~/libreria-api.crt` | Certificado autofirmado en el que se confía (además de los del sistema) |
| `METODO_PAGO` | `tarjeta` | Método simulado preseleccionado |

No hay ninguna credencial en la configuración: correo y contraseña se escriben
en la pantalla de login y sólo viven en memoria.

## Estructura

| Paquete | Qué hace |
|---|---|
| `config` | `Config`: lee `API_BASE`, `CA_CERT` |
| `api` | `ApiClient` (HTTPS, JWT, renovación, errores) · `Sesion` · `LibreriaApi` (una operación por endpoint) · `SoapService` |
| `model` | Records `Libro`, `Autor`, `LibroPedible`, `Pedido`, `Pago`, `Usuario`; `Dinero` (BigDecimal) |
| `cesta` | `Cesta`: en memoria, validación contra `/orders/books` |
| `rastreo` | `CodigoRastreo` (LIB-MTY-AAAA-NNNNNN) · `RastreoClient` (WebSocket del JDK) |
| `ui` | Vistas JavaFX: login, catálogo, detalle, cesta, compra, Mis compras, rastreo, perfil, SOAP |
| `resources/mapa/mapa.html` | Mapa Leaflet con `iniciar()`, `actualizar()`, `limpiar()` |

## Cómo funciona cada módulo

**Autenticación.** `POST /login?format=json` devuelve JWT (20 min) y un refresh
token de un solo uso. `ApiClient` manda `Authorization: Bearer` en cada ruta
protegida, renueva el JWT con `POST /token/refresh` cuando le queda menos de un
minuto y, si un servicio responde 401, intenta una renovación y un reintento. Si
tampoco, la sesión se da por perdida y la app vuelve al login con un aviso.
"Cerrar sesión" llama a `POST /logout` (revoca JWT y refresh en Redis). El rol
sale del JWT (`role_id` 1 = admin): sólo el admin ve la sección SOAP. El perfil
viene de `GET /users/{id}` con el id del JWT.

**Catálogo.** `GET /books` y `GET /books/search?titulo=` (catálogo, público).
Portada = imagen con `cover=true` en `images[]`, bajada de `/uploads/<archivo>`;
si no hay o falla, se dibuja "Portada no disponible". La ficha pide
`GET /books/{isbn}` y cruza los autores con `GET /authors` (nacionalidad,
biografía) y `GET /authors/{id}/books`. La descripción es la `synopsis` que el
catálogo expone desde esta entrega (ver "Adaptaciones").

**Cesta.** En memoria (`Cesta`, `BigDecimal`). Antes de comprar, `validar()`
compara con `GET /orders/books` (id, precio y stock vigentes): asigna el id
numérico que piden las líneas, actualiza precios cambiados y ajusta o quita lo
que no tiene stock, avisando de cada cambio.

**Compra simulada.** `POST /orders {lineas:[{libro_id, cantidad}]}` (el servidor
pone los precios y descuenta stock en la misma transacción) → `POST /payments
{pedido_id, monto: total, metodo, referencia: "SIM-…"}` (nace `aprobado` y el
pedido pasa a `pagado`) → `GET /orders/{id}` y `GET /payments?pedido_id=` para
mostrar lo que dicen los servicios. Sin datos bancarios. Si el pago falla, el
pedido queda pendiente y se puede pagar o cancelar desde "Mis compras".

**Mis compras.** `GET /orders` (el servicio filtra por el usuario del JWT),
detalle con líneas, total, historial y pagos, y el código de rastreo.

**Rastreo.** Ver la sección siguiente.

## Rastreo por WebSocket

- **Código:** `LIB-MTY-<año de creación>-<id del pedido en 6 dígitos>`. Sale del
  pedido real, así que se recupera siempre sin guardarlo.
- **Conexión:** `RastreoClient` abre `wss://<VM>/track/ws?code=…` con
  `Authorization: Bearer <JWT>` en la cabecera. nginx la reenvía al microservicio
  GPS (`gps/microservice/entregas.py`).
- **Autorización:** el servidor GPS reenvía ese JWT a `GET /orders/{id}` del
  servicio de pedidos. Si el token no vale → error; si el pedido es ajeno o no
  existe → "No hay ningún pedido tuyo con ese código" (404, igual que pedidos).
  El pedido debe estar `pagado` o `enviado`. Cada 60 s se vuelve a comprobar: un
  logout corta el rastreo.
- **Simulación:** ruta por calles reales (OSRM) del almacén a un destino que
  depende del id del pedido. El estado se calcula con el tiempo transcurrido
  desde el pago: Pedido confirmado → Preparando pedido → Pedido enviado → En ruta
  de entrega → **Entregado, justo en el último punto de la ruta**. Dura 180 s
  (`ENTREGA_SEGUNDOS`).
- **Mensajes:** `snapshot` (ruta, recorrido, estado) al conectar y `update` cada
  segundo. Java los pasa al mapa con `webEngine.executeScript("actualizar(…)")`;
  el mapa nunca ve el JWT ni abre conexiones. Si la red se cae, `RastreoClient`
  reconecta y el siguiente snapshot repone el recorrido.

## Adaptaciones mínimas al backend

| Dónde | Qué | Por qué |
|---|---|---|
| `apps/services/catalogo/app.py` | `synopsis` en el JSON/XML del libro (de `libros.sinopsis`) | El catálogo no exponía ninguna descripción del libro |
| `gps/microservice/entregas.py` + `app.py` | `ws /track/ws` | Ningún servicio daba seguimiento de envíos; el GPS existente sólo transmitía vehículos libres |
| `deploy/nginx-api-tls.conf` | `/track/ws` (WebSocket) y `/soap` protegido con `auth_request` | Exponer ambos por el 443 con TLS; el SOAP tiene una operación de escritura sin autenticación propia |

Ningún contrato existente cambió: `synopsis` es una clave nueva y opcional, y
`role=gps|map` siguen igual.

## Limitaciones conocidas

- La simulación de la entrega va acelerada (unos minutos en vez de una hora); la
  pantalla muestra la velocidad de un reparto urbano y el factor de aceleración.
- La dirección de entrega no existe en la base: el destino es un punto
  determinista dentro de Monterrey.
- El estado "Entregado" es de la simulación; el servicio de pedidos no tiene ese
  estado (sus estados son pendiente, pagado, enviado, cancelado) y sólo un admin
  podría cambiarlos.
- JavaFX no decodifica WebP: una portada `.webp` se ve como genérica.
