# Revisión de seguridad

> **Rutas.** El repositorio es un monorepo. Las rutas de código del monolito
> que aparecen aquí (`app.js`, `src/`, `views/`, `middleware/`, `config/`,
> `services/`, `public/`, `uploads/`) son **relativas a `apps/web-monolito/`**.
> Lo compartido —`db/`, `deploy/`, `docs/`, `tests/`— sigue en la raíz.

Para cada control: **amenaza** que atiende, **control aplicado** (con el archivo
donde vive) y **evidencia** de que funciona. Al final, los hallazgos abiertos y
los riesgos residuales aceptados.

Las pruebas `PR-nn` se ejecutan con `tests/pruebas.sh`; las `C-nn` con
`db/03_all_quieries_before_stored_procedures.sql`. Ambas dejan su salida en
`docs/evidencias/`.

---

## Hallazgos de esta revisión

### H-01 · Contraseñas en claro en el historial de git — ABIERTO, requiere rotación

Al revisar el repositorio se encontraron dos contraseñas escritas en claro, en
comentarios, ya versionadas:

| Archivo | Qué expone |
|---|---|
| `db/applied/20260830-reset-password-admin.sql` | La contraseña de `admin@libreria.com`, dicha en el comentario |
| `demo.sql` | La contraseña de los dos usuarios sembrados, dicha en el comentario |

Ambos archivos se eliminaron al reconstruir el proyecto, **y eso no resuelve
nada**. El repositorio es público y el historial de git conserva cada versión:
cualquiera puede recuperar el contenido de un commit anterior. Borrar el archivo
sólo lo quita de la copia de trabajo.

**Lo único que resuelve una credencial publicada es rotarla.** Concretamente:

1. Las cuentas `admin@libreria.com` y `juan@ejemplo.com` desaparecen con el
   nuevo esquema. El administrador actual es `admin@libreria.com`, con una
   contraseña distinta que nunca se escribió en el repositorio y que además se
   rotó desde la interfaz una vez terminado el despliegue, porque la del seed se
   había comunicado por un canal de chat.
2. Si esa misma contraseña se reutilizó en cualquier otro sitio —la VM, la base
   de datos, una cuenta personal— hay que cambiarla ahí también.
3. Si se quiere limpiar el historial, se puede reescribir con `git filter-repo`,
   pero eso reescribe todos los hashes de commit y sólo tiene sentido si el
   repositorio aún no se compartió. **No sustituye a rotar.**

**Prevención aplicada:** la regla está en `CLAUDE.md`; `db/02_seed_30_per_table.sql`
guarda sólo hashes y dice explícitamente que el valor se comunica fuera del
repositorio; `.env.example` no lleva ningún valor real; y la restricción
`ck_usuarios_hash_bcrypt` impide que la propia base de datos acepte una
contraseña sin hashear.

### H-02 · `SESSION_SECRET` estaba escrito en el código — CORREGIDO

`index.js` traía `secret: 'libreria_secret_key'` en claro. Con ese valor público,
cualquiera puede firmar una cookie de sesión válida y hacerse pasar por el
Administrador sin conocer ninguna contraseña.

Corregido: el secreto se lee de `.env` y **la aplicación no arranca sin él**
(`config/env.js`), con un mínimo de 32 caracteres. No hay valor por omisión, a
propósito: un valor por omisión inseguro es peor que un fallo al arrancar,
porque pasa desapercibido.

### H-03 · `\prompt` de psql mostraba la contraseña al teclearla — CORREGIDO

Los scripts que fijan la contraseña de los roles de PostgreSQL usaban `\prompt`,
que **hace eco** de lo que se escribe. La contraseña quedaba visible en pantalla
y en el scrollback de la terminal, y viajaba en texto plano dentro de la
sentencia `ALTER ROLE`, con lo que podía acabar en los logs del servidor si
estaba activado `log_statement`.

Se detectó al ejecutarlo en la VM: la contraseña recién generada apareció impresa
en la sesión.

Corregido: ambos scripts (`db/00_create_database.sql` y el de `db/pending/`) usan
`\password`, que oculta la entrada, pide confirmación y envía la contraseña ya
cifrada con SCRAM, de modo que el texto plano nunca sale del cliente.

La contraseña que se expuso durante ese primer intento fue rotada.

### H-04 · Sin límite de tamaño en las subidas — CORREGIDO

El `multer()` original no definía `limits`. Cualquiera con sesión de
administrador podía llenar el disco de la VM. Ahora hay límite de 2 MB en Multer,
la restricción `ck_imagenes_tamano` en la base de datos y `client_max_body_size`
en el proxy.

---

### H-05 · Regla de firewall `allow-3000` innecesaria — PENDIENTE DE CERRAR

El proyecto de GCP tiene una regla heredada, `allow-3000`, que abre el puerto
3000 a `0.0.0.0/0` **sin etiqueta de destino**, es decir, aplicada a todas las
instancias del proyecto.

Se comprobó desde fuera de la VM que el puerto **no responde** pese a esa regla,
porque Node escucha sólo en `127.0.0.1`. Es una buena demostración de defensa en
profundidad: la protección real no la da el firewall, sino la interfaz de
escucha. Pero la regla sigue siendo superficie de ataque innecesaria — bastaría
que alguien cambiara `APP_HOST` a `0.0.0.0` para exponer la aplicación sin
proxy, sin TLS y sin las restricciones del `location` de NGINX.

Cierre recomendado:

```bash
gcloud compute firewall-rules delete allow-3000
```

Antes de borrarla conviene conservar la captura de que el puerto no respondía
aun estando abierta: es la evidencia de MN-06.

## Controles aplicados

### 1. Contraseñas

| | |
|---|---|
| **Amenaza** | Filtración de la base de datos que deje las contraseñas legibles; reutilización de contraseñas triviales |
| **Control** | bcrypt con coste 10 (`src/modules/auth/auth.model.js`). Política mínima: 8 caracteres, al menos una letra y un número, máximo 72 (límite real de bcrypt), en `services/validacion.js`. La base de datos rechaza cualquier `password_hash` que no tenga forma de bcrypt (`ck_usuarios_hash_bcrypt`) |
| **Evidencia** | PR-30 (contraseña débil rechazada); C25 (la BD rechaza texto plano) |
| **Por qué así** | Coste 10 tarda ~100 ms en la VM: suficiente para encarecer un ataque por diccionario sobre la base filtrada, y bajo para que el login no se sienta lento. Reglas más exóticas (símbolos obligatorios) empujan a patrones predecibles y no aportan entropía real |

### 2. Secretos y variables de entorno

| | |
|---|---|
| **Amenaza** | Publicar credenciales en el repositorio o en la página de evidencias |
| **Control** | Todo secreto en `.env`, que está en `.gitignore` y nunca se sube. `.env.example` documenta los **nombres** sin ningún valor. `config/env.js` es el único archivo que lee `process.env` y aborta el arranque si falta algo. Prohibición explícita en `CLAUDE.md`, extendida a los comentarios |
| **Evidencia** | `git check-ignore .env`; arrancar sin `.env` termina con código 1 y un mensaje claro |
| **Riesgo residual** | H-01: el historial ya publicado. Se resuelve rotando, no borrando |

### 3. SQL Injection

| | |
|---|---|
| **Amenaza** | Un valor del usuario que cierre la cadena y ejecute SQL propio |
| **Control** | El 100 % de las consultas usa marcadores de posición (`$1`, `$2`…). No existe una sola concatenación de valores en `src/modules/*/*.model.js`. Como segunda capa, `libreria_app` no puede ejecutar `DROP` ni `ALTER` (DEC-12) |
| **Evidencia** | PR-18: se envía `' OR 1=1; DROP TABLE libros; --` por el buscador; responde 200, devuelve cero coincidencias y la tabla sigue con sus 30 filas (PR-19). C03 hace la misma prueba directamente en psql |
| **Verificación** | `grep -rn "query(\`" src/` no arroja ninguna consulta con interpolación de variables |

### 4. XSS

| | |
|---|---|
| **Amenaza** | Un título de libro o un texto alternativo con `<script>` que se ejecute en el navegador de quien abra el catálogo |
| **Control** | EJS escapa por omisión con su etiqueta de salida escapada; la salida cruda se usa **sólo** para incluir parciales, nunca para datos. Además, CSP con `script-src 'self'`: un script en línea inyectado no se ejecutaría aunque el escapado fallara |
| **Evidencia** | PR-16 y PR-17: el `<script>` del buscador aparece como `&lt;script&gt;` y no como etiqueta ejecutable |

### 5. Autenticación y manejo de sesión

| | |
|---|---|
| **Amenaza** | Robo de cookie, fijación de sesión, enumeración de usuarios, fuerza bruta |
| **Control** | Cookie `httpOnly` (inalcanzable desde JavaScript), `SameSite=Lax`, `secure` cuando hay HTTPS, caducidad de 2 horas con renovación. **Regeneración de la sesión al autenticar**, que descarta el identificador previo. Mismo mensaje para correo inexistente, contraseña incorrecta y cuenta desactivada, y comparación contra un hash señuelo cuando el correo no existe, para que el tiempo de respuesta no delate qué correos están registrados. Límite de 5 intentos por IP + correo en 15 minutos. El nombre de la cookie es `libreria.sid`, no `connect.sid`, para no anunciar el framework |
| **Evidencia** | PR-06 y PR-07 (mismo 401 en ambos casos), PR-36, PR-37, PR-38, PR-39 |
| **Riesgo residual** | El contador de intentos vive en memoria: se reinicia al reiniciar el proceso y no se comparte entre instancias |

### 6. Autorización por rol

| | |
|---|---|
| **Amenaza** | Un lector que alcanza funciones administrativas escribiendo la URL o enviando un POST directo |
| **Control** | `requireAdmin` en **cada** ruta de gestión (`*.routes.js`), no en la vista. Autenticación y autorización están en funciones separadas a propósito: tener sesión no implica permiso. Un lector recibe **403 con página explicativa**, no un redirect silencioso. La interfaz además oculta los enlaces, pero eso es comodidad visual, no protección |
| **Evidencia** | PR-13 (403 en cinco rutas distintas) y PR-14 (POST de borrado directo, rechazado y el registro intacto) |

### 7. CSRF

| | |
|---|---|
| **Amenaza** | Un formulario alojado en otro sitio que haga que el navegador del Administrador —que ya tiene sesión— envíe un POST de borrado |
| **Control** | Token de 32 bytes aleatorios por sesión, campo oculto en todos los formularios que escriben, comparación en tiempo constante con `timingSafeEqual`. Ver DEC-09 para el caso de los formularios multipart |
| **Evidencia** | PR-05 (login sin token) y PR-45 (subida sin token): ambos 403 |

### 8. Validación de entrada

| | |
|---|---|
| **Amenaza** | Datos inválidos que corrompan el estado, saltándose el navegador |
| **Control** | `services/validacion.js` valida tipo, longitud, rango y formato de cada campo. Los enteros se validan con expresión regular, no con `parseInt` (que aceptaría `'12abc'`). Los formularios llevan `novalidate` para que la validación del navegador no oculte a la del servidor durante las pruebas |
| **Evidencia** | PR-21 a PR-27, PR-30, PR-31 — todos son POST hechos con curl |

### 9. Subida de archivos

| | |
|---|---|
| **Amenaza** | Subir código ejecutable y lograr que el servidor lo sirva o lo ejecute; llenar el disco; escribir fuera de `uploads/` con `../` |
| **Control** | Cinco capas: lista blanca de MIME, lista blanca de extensión, límite de 2 MB, verificación de la **firma binaria** del archivo ya escrito, y nombre generado por el servidor (UUID + extensión). El nombre que envió el usuario nunca toca el sistema de archivos. Si cualquier comprobación falla, el archivo se borra del disco. `uploads/` está fuera de `public/` y se sirve con `nosniff` y `Content-Disposition: inline`; el proxy además niega las extensiones ejecutables. La restricción `ck_imagenes_nombre` valida el formato del nombre también en la base de datos |
| **Evidencia** | PR-40 a PR-46. El conteo de archivos en `uploads/` sube exactamente en 1 tras los siete intentos: sólo el PNG válido sobrevive |

### 10. Mensajes de error

| | |
|---|---|
| **Amenaza** | Un stack trace o un fragmento de SQL que le diga a un atacante cómo está construido el sistema |
| **Control** | `middleware/errores.js` traduce los códigos de PostgreSQL a mensajes en español y responde con una página genérica. El detalle completo —código, consulta, traza— va al log del servidor. Los errores de usuario (23505, 23503, 23514) dan 400, no 500 |
| **Evidencia** | PR-04; una consulta a un id inexistente devuelve 404 sin ninguna cadena técnica en el HTML |

### 11. Mínimo privilegio en PostgreSQL

| | |
|---|---|
| **Amenaza** | Que un fallo en la aplicación se convierta en pérdida del esquema |
| **Control** | `libreria_app` sólo tiene `SELECT/INSERT/UPDATE/DELETE`. No es superusuario, no crea bases ni roles, no es dueño de las tablas. PostgreSQL escucha sólo en `localhost` |
| **Evidencia** | `db/00_create_database.sql` termina consultando `pg_roles` para comprobarlo |

### 12. Cabeceras y superficie expuesta

| | |
|---|---|
| **Amenaza** | Clickjacking, interpretación errónea del tipo de contenido, fugas por `Referer`, huella del framework |
| **Control** | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, CSP restrictiva, `x-powered-by` desactivado. Node escucha sólo en loopback |
| **Evidencia** | PR-32 a PR-35 |

### 13. Endurecimiento del proceso en la VM

| | |
|---|---|
| **Amenaza** | Que una ejecución de código dentro de la aplicación alcance el resto del sistema |
| **Control** | `deploy/libreria.service`: usuario sin privilegios, `NoNewPrivileges`, `ProtectSystem=strict` con `ReadWritePaths` limitado a `uploads/`, `PrivateTmp`, familias de sockets restringidas |
| **Evidencia** | `systemd-analyze security libreria` en la VM |

---

## Riesgos residuales aceptados

| Riesgo | Por qué se acepta en este alcance | Qué lo cerraría |
|---|---|---|
| Sesiones en memoria del proceso | Una sola instancia; añadir Redis sería infraestructura sin uso | `connect-pg-simple` sobre la base que ya existe |
| Límite de intentos de login en memoria | Mismo motivo; se reinicia con el proceso | Tabla de intentos en PostgreSQL |
| Sin HTTPS todavía | El ejercicio se valida en la red del curso; la configuración TLS está escrita y comentada en `deploy/nginx-library.conf` | Certificado + `COOKIE_SECURE=true` |
| Sin recuperación de contraseña | Fuera del alcance declarado; requeriría envío de correo | El Administrador puede reasignar la contraseña desde `/usuarios` |
| Sin bitácora de auditoría | No se pide en el enunciado | Tabla de eventos con usuario, acción y momento |
| `style-src 'unsafe-inline'` en la CSP | Algunas vistas usan atributos `style` puntuales. `script-src` **no** lo permite, que es lo que importa para XSS | Mover esos estilos a la hoja y endurecer la directiva |
| Imágenes en el disco de la VM | Reproducibles desde `db/seed_uploads/`; migrar a Cloud Storage está fuera del alcance | Cambiar sólo `middleware/subidas.js` |

---

## Lista de verificación antes de publicar

- [ ] `.env` **no** está en el `.tar.gz` ni en el servidor de evidencias
- [ ] `node_modules/` excluido del paquete
- [ ] Ninguna llave SSH, token ni cadena de conexión en el repositorio ni en la página
- [ ] Las capturas de pantalla no muestran contraseñas, cookies de sesión ni la IP interna de la VM
- [ ] Las salidas de `psql` publicadas no incluyen hashes de contraseña
- [ ] `.env.example` presente, con los nombres de variable y **sin** valores
- [ ] Contraseñas de H-01 rotadas en todo sitio donde se hubieran reutilizado
