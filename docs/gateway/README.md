# API Gateway con nginx: entrega

Las tres aplicaciones de escritorio del monorepo (Electron, Python Tk y Java)
dejaron de llamar a cada microservicio por su ruta o su puerto: ahora todo pasa
por el **API Gateway** (nginx), con la tabla de rutas `/api/*` vista en clase.

```
 Electron ─┐                                     ┌─▶ login     5000   /api/login
 Python Tk ┼─HTTPS─▶ Apache :443 ─▶ nginx gateway ┼─▶ catálogo  5002   /api/books
 Java FX  ─┘  (TLS, cert.          127.0.0.1:8443 ├─▶ authors   5004   /api/autores
               autofirmado)        │              ├─▶ pedidos   5005   /api/pedidos
                                   │ ¿JWT válido? ├─▶ pagos     5006   /api/pagos
                                   │ (auth_request├─▶ users     5003   /api/users
                                   │  a pedidos)  └─▶ monolito  3000   /  → /library/
                                   └─ no → 401 {"origen":"gateway"}
```

## 1. Monorepo con las aplicaciones modificadas

| App | Qué cambió | Archivos |
|---|---|---|
| **Electron** | Antes iba **directo** a `http://IP:5002/books`, sin proxy. Ahora pide `https://34.51.108.167/api/books` y las portadas a `https://…/uploads/`. Confía **sólo** en el certificado de la VM (`~/libreria-api.crt` o `CA_CERT`): Node lo recibe como `ca` y Chromium lo acepta en las `<img>` únicamente si es idéntico a esa copia. La configuración guardada pasa a una clave nueva para que tome los valores del gateway. | [main.js](../../apps/electron-app/main.js), [renderer.js](../../apps/electron-app/renderer/renderer.js), [asistente.js](../../apps/electron-app/renderer/asistente.js), [index.html](../../apps/electron-app/renderer/index.html) |
| **Python Tk** | `ruta_gateway()` traduce cada ruta propia del servicio a la del gateway justo antes de enviarla (`/orders/7` → `/api/pedidos/7`). Las pantallas no cambian. | [api_rest.py](../../apps/services/soap/cliente/api_rest.py), [pruebas_cliente_rest.py](../../apps/services/soap/tests/pruebas_cliente_rest.py) |
| **Java (JavaFX)** | Lo mismo con `ApiClient.rutaGateway()`, más una prueba con la tabla completa. | [ApiClient.java](../../apps/JavaDesktop_app/src/main/java/mx/udem/libreria/api/ApiClient.java), [RutaGatewayTest.java](../../apps/JavaDesktop_app/src/test/java/mx/udem/libreria/RutaGatewayTest.java) |

Traducción que aplican Tk y Java (Electron ya escribe la ruta `/api/books`):

| Ruta del servicio | Ruta en el gateway |
|---|---|
| `/login`, `/logout`, `/session`, `/token/refresh` | `/api/login`, `/api/login/logout`, `/api/login/session`, `/api/login/token/refresh` |
| `/books…` | `/api/books…` |
| `/authors…` | `/api/autores…` |
| `/orders…` | `/api/pedidos…` |
| `/payments…` | `/api/pagos…` |
| `/users…` | `/api/users…` |
| `/uploads`, `/health`, `/metrics`, `/soap`, `/track/ws` | sin cambio (no están en la tabla del gateway; nginx los sigue publicando) |

Cómo arrancar cada una contra la VM (todas necesitan `~/libreria-api.crt`):

```bash
cd apps/electron-app && npm install && npm start
```

```bash
cd apps/services/soap && API_BASE=https://34.51.108.167 CA_CERT=~/libreria-api.crt python3 cliente/cliente_escritorio.py
```

```bash
cd apps/JavaDesktop_app && bash ejecutar.sh
```

## 2. Evidencias

**Registros (texto):**

| Archivo | Qué demuestra |
|---|---|
| [docs/evidencias/pruebas_gateway.txt](../evidencias/pruebas_gateway.txt) | 23 pruebas contra la VM por HTTPS, 0 fallos: rutas `/api/*`, rechazo temprano (401 del gateway), 403 del servicio, rutas viejas intactas |
| [docs/evidencias/pruebas_clientes_gateway.txt](../evidencias/pruebas_clientes_gateway.txt) | Las tres apps: Tk 42/0 y su capa de red contra la VM; Java 32/0 (`RutaGatewayTest`); Electron contra la VM (XML, portadas, JSON del asistente) y la regla de certificado de Chromium |

**Capturas** en `evidencias/api gateway/`, numeradas:

| # | Captura |
|---|---|
| 01 | `sudo nginx -t` y `systemctl status nginx` en la VM |
| 02 | `curl` sin token a `/api/pedidos` → 401 `"origen":"gateway"` |
| 03 | Electron con el catálogo y las portadas; el pie muestra `https://34.51.108.167/api/books?format=xml` |
| 04 | Electron, popup *Configurar servicio* con la URL efectiva del gateway |
| 05 | Tk: tienda con portadas, sesión iniciada y semáforos en verde |
| 06 | Tk: una compra (pedido + pago) |
| 07 | Java: catálogo con sesión iniciada |
| 08 | Java: compra y *Mis compras* |
| 09 | `access.log` de nginx con las peticiones `/api/*` hechas por las tres apps (ver abajo) |
| 10 | `tests/pruebas_gateway.py` con 0 fallos |

Para la 09, en la VM (borra la IP del cliente: el repositorio es público):

```bash
sudo tail -n 300 /var/log/nginx/library-api.access.log | grep ' /api/' | awk '{$1="<ip>"; print}' | tail -n 40
```

## 3. Archivos de configuración de nginx

| Archivo | En la VM | Papel |
|---|---|---|
| [deploy/nginx-api-tls.conf](../../deploy/nginx-api-tls.conf) | `/etc/nginx/conf.d/library-api-tls.conf` | **El gateway**: tabla `/api/*`, `auth_request` para el JWT, limitador de `/api/login`, `X-Request-ID`, errores en JSON. También las rutas sin prefijo, portadas, `/soap`, `/track/ws`, `/health` y `/metrics` |
| [deploy/nginx-library.conf](../../deploy/nginx-library.conf) | `/etc/nginx/conf.d/library.conf` | Reverse proxy del monolito (`/library` → Node 3000), estáticos y subidas desde disco. El gateway le reenvía `/` |
| [deploy/apache-libreria.conf](../../deploy/apache-libreria.conf) | `/etc/httpd/conf.d/01-libreria.conf` | Apache termina TLS en el 443 (lo comparte con otro proyecto) y pasa todo a nginx en loopback |

Detalle técnico (decisiones, falla cerrada, despliegue): sección
[API Gateway](../../MANUAL_TECNICO.md#api-gateway-nginx-rutas-api) del manual técnico.
