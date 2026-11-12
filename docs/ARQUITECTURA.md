# Arquitectura de la Librería Online (con nginx como reverse proxy)

> **Escenario simulado.** Este documento supone que **nginx es el único reverse
> proxy en el borde**: termina TLS en 80/443 y reparte el tráfico a cada
> aplicación. En la VM real, Apache entra primero y nginx escucha detrás, en
> loopback (ver [Cómo es hoy en la VM](#cómo-es-hoy-en-la-vm)). Las rutas y los
> puertos internos salen de `deploy/nginx-api-tls.conf` y
> `deploy/nginx-library.conf`, que son los archivos reales.
>
> Las rutas de código del monolito se escriben completas
> (`apps/web-monolito/...`), porque este documento vive en `docs/`.

---

## 1. Resumen

La Librería Online es un **monorepo** con tres partes:

- un monolito web Node.js + Express + EJS;
- ocho servicios Python: siete microservicios Flask y el servicio de rastreo GPS;
- cuatro clientes de escritorio.

Las aplicaciones no comparten código. Sólo comparten la base PostgreSQL y, en el
caso de los servicios Python, una capa Redis auxiliar. Desde fuera, todo entra
por un único nginx, que publica dos superficies:

- **`/library/…`**: el sitio web (monolito, HTML renderizado en el servidor).
- **API (`/login`, `/books`, `/orders`, …)**: la consumen los clientes de
  escritorio, con JWT.

| Componente | Carpeta | Tecnología | Puerto interno | Unidad systemd |
|---|---|---|---|---|
| Monolito web | `apps/web-monolito/` | Node + Express + EJS + `pg` | 3000 | `libreria.service` |
| Login / sesiones / JWT | `apps/services/login/` | Flask + psycopg3 + Redis | 5000 | `libreria-login.service` |
| Clasificador SOAP (WSDL) | `apps/services/soap/` | Python SOAP | 5001 | `libreria-soap.service` |
| Catálogo XML/JSON | `apps/services/catalogo/` | Flask | 5002 | `libreria-catalogo.service` |
| Users | `apps/services/users/` | Flask + JWT | 5003 | `libreria-users.service` |
| Authors | `apps/services/authors/` | Flask + JWT | 5004 | `libreria-authors.service` |
| Pedidos | `apps/services/pedidos/` | Flask + JWT | 5005 | `libreria-pedidos.service` |
| Pagos (simulados) | `apps/services/pagos/` | Flask + JWT | 5006 | `libreria-pagos.service` |
| GPS / entregas (WebSocket) | `gps/microservice/` | Flask + flask-sock | 5900 | `libreria-gps.service` |
| PostgreSQL | `db/` (scripts) | PostgreSQL, base `libreria_db` | 5432 | servicio del sistema |
| Redis | — | Redis (`bind 127.0.0.1`, `requirepass`) | 6379 | `redis.service` |
| **nginx** | `deploy/` | Reverse proxy, terminación TLS | **80 / 443** | `nginx.service` |

Clientes:

| Cliente | Carpeta | Qué consume |
|---|---|---|
| Navegador | — | `/library/…` (HTML del monolito) |
| Electron | `apps/electron-app/` | Catálogo en **XML** (`/books?format=xml`) |
| JavaFX | `apps/JavaDesktop_app/` | REST + JWT, compra, rastreo por **WSS**, SOAP |
| Tkinter (tienda) | `apps/services/soap/cliente/` | REST + JWT, portadas, semáforos `/health/*` |
| Clientes SOAP | `clients/clasificador_java`, `clients/clasificador_python` | `/soap` y el WSDL |
| GPSapp y mapa | `gps/GPSapp/`, `gps/Map/` | WebSocket del GPS (simulador y visor) |

---

## 2. Diagrama general

```mermaid
flowchart LR
    %% ---------- Clientes ----------
    subgraph CLIENTES["Clientes"]
        NAV["Navegador<br/>(HTML/EJS)"]
        ELE["Electron<br/>(catálogo XML)"]
        JFX["JavaFX<br/>(REST + WSS + SOAP)"]
        TK["Tkinter tienda<br/>(REST + portadas)"]
        CSOAP["Clientes SOAP<br/>Java / Python"]
        GPSAPP["GPSapp<br/>(simulador)"]
        MAPA["Mapa Leaflet"]
    end

    %% ---------- Borde ----------
    subgraph BORDE["Borde · VM GCP"]
        NGINX{{"nginx<br/>:80 → 301 HTTPS<br/>:443 TLS"}}
    end

    %% ---------- Aplicaciones ----------
    subgraph APPS["Aplicaciones (sólo 127.0.0.1)"]
        MONO["Monolito web<br/>Express + EJS<br/>:3000"]
        LOGIN["login<br/>:5000"]
        SOAP["soap (WSDL)<br/>:5001"]
        CAT["catálogo<br/>:5002"]
        USERS["users<br/>:5003"]
        AUTH["authors<br/>:5004"]
        PED["pedidos<br/>:5005"]
        PAG["pagos<br/>:5006"]
        GPS["gps / entregas<br/>WebSocket :5900"]
    end

    %% ---------- Datos ----------
    subgraph DATOS["Datos"]
        PG[("PostgreSQL<br/>libreria_db")]
        REDIS[("Redis<br/>127.0.0.1:6379")]
        UPL[["uploads/<br/>portadas en disco"]]
    end

    OSRM(["OSRM<br/>router.project-osrm.org"])

    %% Clientes → nginx
    NAV  -- "HTTPS /library" --> NGINX
    ELE  -- "HTTPS /books?format=xml" --> NGINX
    JFX  -- "HTTPS + JWT / WSS /track/ws / SOAP" --> NGINX
    TK   -- "HTTPS + JWT" --> NGINX
    CSOAP -- "SOAP /soap" --> NGINX
    GPSAPP -- "WSS /gps/ws?role=gps" --> NGINX
    MAPA -- "WSS /gps/ws?role=map" --> NGINX

    %% nginx → aplicaciones
    NGINX -- "/library" --> MONO
    NGINX -- "/login /register /logout<br/>/session /token/*" --> LOGIN
    NGINX -- "/soap /wsdl/*<br/>(auth_request)" --> SOAP
    NGINX -- "/books /concepts" --> CAT
    NGINX -- "/users" --> USERS
    NGINX -- "/authors" --> AUTH
    NGINX -- "/orders" --> PED
    NGINX -- "/payments" --> PAG
    NGINX -- "/track/ws /gps/*" --> GPS
    NGINX -. "/uploads/&lt;uuid&gt;<br/>/library/uploads" .-> UPL
    NGINX -. "auth_request<br/>GET /orders/books" .-> PED

    %% aplicaciones → datos
    MONO -- SQL --> PG
    MONO -- "escribe portadas" --> UPL
    LOGIN & CAT & USERS & AUTH & PED & PAG -- SQL --> PG
    LOGIN & CAT & USERS & AUTH & PED & PAG -- RESP --> REDIS
    SOAP -- SQL --> PG
    GPS -- "valida JWT:<br/>GET /orders/&lt;id&gt;" --> PED
    GPSAPP -. "rutas" .-> OSRM

    classDef borde fill:#1f6f43,stroke:#0b3d22,color:#fff
    classDef datos fill:#f3ead7,stroke:#8a6d3b,color:#000
    classDef app fill:#e8f0fe,stroke:#3b5b8a,color:#000
    class NGINX borde
    class PG,REDIS,UPL datos
    class MONO,LOGIN,SOAP,CAT,USERS,AUTH,PED,PAG,GPS app
```

**Cómo leerlo:**

- Ningún puerto interno (3000, 5000–5006, 5900, 5432, 6379) se publica fuera de la
  VM. Sólo nginx escucha en una interfaz pública.
- Las líneas punteadas no son tráfico de usuario. Representan la verificación
  `auth_request`, los estáticos servidos desde disco y la llamada a OSRM.
- En la VM real, el simulador GPS y el mapa hablan directo con `:5900`. Aquí pasan
  por nginx bajo `/gps/…` para completar el escenario de un solo punto de entrada.

---

## 3. Enrutamiento de nginx

| `location` | Upstream | Notas |
|---|---|---|
| `/library/uploads/` | disco: `apps/web-monolito/uploads/` | `alias`. `nosniff`, `Content-Disposition: inline` y se niegan las extensiones ejecutables |
| `/library/css/`, `/library/js/` | disco: `apps/web-monolito/public/` | Caché de 7 días |
| `/library` | `127.0.0.1:3000` | Conserva el prefijo (`proxy_pass` sin barra final; la app usa `BASE_PATH`). Pasa `X-Forwarded-*` y no guarda en búfer las páginas con sesión |
| `~ ^/(login\|register\|logout\|session\|token)` | `127.0.0.1:5000` | Login, sesión, JWT y refresh |
| `~ ^/users` | `127.0.0.1:5003` | JWT |
| `~ ^/authors` | `127.0.0.1:5004` | GET público, escritura sólo admin |
| `~ ^/orders` | `127.0.0.1:5005` | JWT |
| `~ ^/payments` | `127.0.0.1:5006` | JWT |
| `~ ^/(books\|concepts)` | `127.0.0.1:5002` | XML o JSON. Caché Redis de 60 s |
| `= /track/ws` | `127.0.0.1:5900` | **WebSocket** (`Upgrade`/`Connection`, timeout de 1 h) |
| `/gps/` *(simulado)* | `127.0.0.1:5900/` | Mapa y `/ws?role=gps\|map` por WebSocket |
| `= /soap`, `= /wsdl/library-classifier.wsdl` | `127.0.0.1:5001` | `auth_request /_jwt_valido` |
| `= /_jwt_valido` (`internal`) | `127.0.0.1:5005/orders/books` | nginx no verifica JWT: le pregunta a pedidos. 2xx deja pasar y 401 se devuelve tal cual |
| `~* ^/uploads/<uuid>.(png\|jpg\|webp)` | disco: `apps/web-monolito/uploads/` | Portadas para los clientes de escritorio |
| `= /health/<servicio>` | `:<puerto>/health` | Semáforos de los clientes |
| `= /metrics/<servicio>` | `:<puerto>/metrics` | Contadores en Redis (JWT de admin) |
| `/` | — | `return 404`: nada más se publica |

### Bloque de referencia (simulado, no está en `deploy/`)

Esta es la condensación de los dos `.conf` reales en un único servidor de borde:

```nginx
# Redirección: todo HTTP pasa a HTTPS
server {
    listen 80 default_server;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2 default_server;
    ssl_certificate     /etc/pki/tls/certs/libreria-api.crt;
    ssl_certificate_key /etc/pki/tls/private/libreria-api.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    client_max_body_size 5m;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # --- Sitio web (monolito) ---
    location /library/uploads/ { alias /opt/udem/libreria/apps/web-monolito/uploads/; }
    location /library/css/     { alias /opt/udem/libreria/apps/web-monolito/public/css/; }
    location /library/js/      { alias /opt/udem/libreria/apps/web-monolito/public/js/; }
    location /library          { proxy_pass http://127.0.0.1:3000; proxy_buffering off; }

    # --- API ---
    location ~ ^/(login|register|logout|session|token)(/|$) { proxy_pass http://127.0.0.1:5000; }
    location ~ ^/users(/|$)    { proxy_pass http://127.0.0.1:5003; }
    location ~ ^/authors(/|$)  { proxy_pass http://127.0.0.1:5004; }
    location ~ ^/orders(/|$)   { proxy_pass http://127.0.0.1:5005; }
    location ~ ^/payments(/|$) { proxy_pass http://127.0.0.1:5006; }
    location ~ ^/(books|concepts)(/|$) { proxy_pass http://127.0.0.1:5002; }

    # --- WebSockets ---
    location = /track/ws {
        proxy_pass http://127.0.0.1:5900;
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 1h;
    }
    location /gps/ {
        proxy_pass http://127.0.0.1:5900/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # --- SOAP protegido con JWT ---
    location = /soap                          { auth_request /_jwt_valido; proxy_pass http://127.0.0.1:5001; }
    location = /wsdl/library-classifier.wsdl  { auth_request /_jwt_valido; proxy_pass http://127.0.0.1:5001; }
    location = /_jwt_valido {
        internal;
        proxy_pass http://127.0.0.1:5005/orders/books;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header Authorization $http_authorization;
    }

    # --- Portadas para escritorio ---
    location ~* "^/uploads/([0-9a-f-]{36}\.(png|jpe?g|webp))$" {
        alias /opt/udem/libreria/apps/web-monolito/uploads/$1;
    }

    # --- Salud y métricas (un location por servicio) ---
    location = /health/login   { proxy_pass http://127.0.0.1:5000/health; }
    location = /metrics/login  { proxy_pass http://127.0.0.1:5000/metrics; }
    # … igual para catalogo, users, authors, pedidos y pagos

    location / { return 404; }
}
```

---

## 4. Flujos principales

### 4.1 Login, JWT y una petición autenticada

```mermaid
sequenceDiagram
    autonumber
    participant C as Cliente (JavaFX / Tkinter)
    participant N as nginx :443
    participant L as login :5000
    participant P as pedidos :5005
    participant R as Redis
    participant DB as PostgreSQL

    C->>N: POST /login (email, contraseña)
    N->>L: proxy
    L->>R: ratelimit:login:<ip>:<correo>
    L->>DB: usuario + hash de contraseña
    L->>R: session:<sid>, refresh:<sha256>
    L-->>C: JWT (HS256, 20 min, jti) + refresh_token
    C->>N: GET /orders (Authorization: Bearer)
    N->>P: proxy
    P->>P: verifica firma, exp, iss y claims
    P->>R: ¿jwt:revoked:<jti>?
    alt Redis caído
        P-->>C: 503 (falla cerrado)
    else no revocado
        P->>DB: pedidos del usuario
        P-->>C: 200 JSON
    end
    Note over C,L: Al vencer: POST /token/refresh, rotación de un solo uso
```

### 4.2 Compra (pedido + pago simulado)

```mermaid
sequenceDiagram
    autonumber
    participant C as Cliente
    participant N as nginx
    participant P as pedidos :5005
    participant G as pagos :5006
    participant R as Redis
    participant DB as PostgreSQL

    C->>N: GET /orders/books (ISBN → id)
    N->>P: proxy
    C->>N: POST /orders {líneas}
    N->>P: proxy
    P->>DB: BEGIN, INSERT pedidos + pedidos_lineas<br/>sp_ajustar_stock(...), COMMIT
    Note right of DB: trg_pedido_historial llena<br/>pedidos_estados_historial
    P->>R: borra books:* (el stock cambió)
    P-->>C: 201 pedido
    C->>N: POST /payments {pedido, método}
    N->>G: proxy
    G->>DB: INSERT pagos (dueño del pedido o admin)
    G-->>C: 201 pago (simulado)
```

### 4.3 Rastreo del pedido por WebSocket

```mermaid
sequenceDiagram
    autonumber
    participant J as JavaFX
    participant N as nginx
    participant E as gps/entregas :5900
    participant P as pedidos :5005

    J->>N: WSS /track/ws?code=LIB-MTY-<año>-<id> (Authorization)
    N->>E: Upgrade: websocket
    E->>P: GET /orders/<id> reenviando el JWT
    alt 200
        P-->>E: pedido del usuario
        loop cada segundo
            E-->>J: posición del repartidor
        end
    else 401 / 403 / 404
        E-->>J: cierra la conexión con error
    end
```

---

## 5. El monolito por dentro (MVC por módulos)

```mermaid
flowchart TB
    REQ["Petición /library/..."] --> APP["apps/web-monolito/app.js<br/>Express + BASE_PATH"]
    APP --> MW["middleware/<br/>auth.js · locals.js (CSRF)<br/>subidas.js (Multer) · errores.js"]
    MW --> RT["src/modules/&lt;n&gt;/&lt;n&gt;.routes.js<br/>método + URL → controller"]
    RT --> CT["&lt;n&gt;.controller.js<br/>valida con services/validacion.js"]
    CT --> MD["&lt;n&gt;.model.js<br/>SQL parametrizado"]
    MD --> POOL["config/db.js<br/>Pool único de pg"]
    POOL --> PG[("PostgreSQL")]
    CT --> VW["views/&lt;n&gt;/*.ejs<br/>+ views/parciales/"]
    VW --> RES["HTML escapado con &lt;%= %&gt;"]
    CFG["config/env.js<br/>(único que lee process.env)"] -.-> APP
    CRUD["services/crudCatalogo.js"] -.-> CT
```

Módulos de dominio (`apps/web-monolito/src/modules/`): `auth`, `autores`,
`categorias`, `conceptos`, `formatos`, `generos`, `imagenes`, `libros`, `panel`,
`usuarios`. Los catálogos simples (`nombre` + `descripcion`) reutilizan
`services/crudCatalogo.js` y `views/catalogo/`.

---

## 6. Seguridad por capas

| Capa | Mecanismo |
|---|---|
| Borde (nginx) | TLS 1.2/1.3 con certificado autofirmado (no hay dominio, sólo la IP). Redirección 80 → 443. Todo lo no listado devuelve 404 |
| Red | Apps, PostgreSQL y Redis sólo en `127.0.0.1`. Firewall con 80 y 443 abiertos |
| Identidad (API) | JWT HS256 de **20 min** emitido por login. Claims `sub`, `user_id`, `role_id`, `rol`, `email`, `iss`, `jti`. Algoritmo fijo |
| Revocación | `jwt:revoked:<jti>` en Redis. Refresh opaco de un solo uso, guardado como `sha256` |
| Autorización | 401 sin token y 403 con rol insuficiente. Cada servicio verifica por su cuenta |
| SOAP | `auth_request` de nginx delegado a pedidos |
| Rastreo | entregas reenvía el JWT a `GET /orders/<id>` |
| Monolito | Sesión con cookie, CSRF en todo formulario, validación server-side, escapado EJS y queries parametrizadas |
| Abuso | Limitador de login: 5 intentos en 15 min → 429 |
| CORS | `CORS_ORIGENES` explícito, nunca `*` |
| Secretos | Sólo en el `.env` de cada servicio en la VM (600, no versionado) |

---

## 7. Redis (capa auxiliar de los servicios Python)

| Clave | Escribe | TTL |
|---|---|---|
| `session:<sid>` | login | 8 h |
| `refresh:<sha256>` | login | igual que la sesión |
| `jwt:revoked:<jti>` | login (`/logout`, `/token/refresh`) | lo que le quede al JWT (≤ 20 min) |
| `ratelimit:login:<ip>:<correo>` | login | 15 min |
| `books:list:<filtros>`, `books:<isbn>` | catálogo (los borran authors y pedidos) | 60 s |
| `metrics:<servicio>:<contador>` | los seis | sin TTL |

**Política ante una caída de Redis:**

- Sesión, refresh, logout y toda ruta con JWT **fallan cerrado** y responden 503.
- `GET /books` y `GET /books/<isbn>` **fallan abierto** y leen de PostgreSQL.
- `/health` sigue en 200, pero con `redis: caido`, y el semáforo de los clientes
  se pone en amarillo.

---

## 8. Base de datos (resumen)

El esquema completo está en `db/01_schema.sql`. El diagrama detallado está en
[MANUAL_TECNICO.md](../MANUAL_TECNICO.md), sección "Base de datos". El modelo
está normalizado hasta 4FN. El total del pedido no se guarda: se calcula en
`v_pedidos_total`.

```mermaid
erDiagram
    personas ||--o| usuarios : "es"
    libros ||--o{ libros_autores : ""
    autores ||--o{ libros_autores : ""
    libros ||--o{ libros_generos : ""
    generos ||--o{ libros_generos : ""
    libros ||--o{ libros_conceptos : ""
    conceptos ||--o{ libros_conceptos : ""
    categorias ||--o{ libros : "clasifica"
    formatos ||--o{ libros : "formato"
    libros ||--o{ imagenes_libros : "portadas"
    usuarios ||--o{ pedidos : "hace"
    estados_pedido ||--o{ pedidos : "estado"
    pedidos ||--|{ pedidos_lineas : "contiene"
    libros ||--o{ pedidos_lineas : "se vende en"
    pedidos ||--o{ pedidos_estados_historial : "historial"
    pedidos ||--o{ pagos : "se paga con"
    metodos_pago ||--o{ pagos : ""
    estados_pago ||--o{ pagos : ""
```

Los scripts `db/00…06_*.sql` reconstruyen la base y se ejecutan en orden. Los
cambios nuevos van en `db/pending/`, y en `db/applied/` sólo entran los que ya
corrieron en la VM.

---

## 9. Despliegue

```mermaid
flowchart TB
    subgraph VM["VM GCP (repo en /opt/udem/libreria)"]
        direction TB
        NG["nginx.service<br/>:80 / :443"]
        subgraph SYSTEMD["Unidades systemd (deploy/*.service, gps/deploy/)"]
            S1["libreria (node app.js)"]
            S2["libreria-login · -soap · -catalogo"]
            S3["libreria-users · -authors · -pedidos · -pagos"]
            S4["libreria-gps (gunicorn, 1 worker, 100 hilos)"]
        end
        RD["redis.service"]
        PGS["postgresql"]
        NG --> SYSTEMD
        SYSTEMD --> RD
        SYSTEMD --> PGS
    end
```

- Cada servicio tiene su propio `.venv`, `requirements.txt`, `.env` y unidad. La
  Node app usa `npm ci --omit=dev` dentro de `apps/web-monolito/`.
- Para actualizar: `git pull`, luego `sudo systemctl restart libreria-<n>` en
  cada servicio que haya cambiado.

### Cómo es hoy en la VM

En la VM real, el borde no es nginx sino **Apache (`httpd`)**. Tiene el 80 y el
443 porque comparte la máquina con otro proyecto (Waylo). Apache termina TLS en
la IP y reenvía a nginx, que sólo escucha en loopback:

```mermaid
flowchart LR
    I["Internet"] --> A["Apache :80 / :443<br/>(TLS, deploy/apache-libreria.conf)"]
    A -- "HTTP :80" --> N1["nginx 127.0.0.1:8009<br/>(nginx-library.conf)"]
    A -- "HTTPS :443 y WSS /track/ws" --> N2["nginx 127.0.0.1:8443<br/>(nginx-api-tls.conf)"]
    N1 --> M["monolito :3000"]
    N2 --> S["servicios 5000–5006, 5900"]
```

Pasar al escenario de este documento consistiría en dos cambios:

1. Unir los dos `server` de nginx en uno que escuche en 80 y 443.
2. Quitar `01-libreria.conf` de Apache. Eso sólo es posible si Waylo deja de
   necesitar esos puertos, o si se le da su propio `server_name` en nginx.
