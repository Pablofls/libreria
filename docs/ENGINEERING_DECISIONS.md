# Registro de decisiones de ingeniería

> **Rutas.** El repositorio es un monorepo. Las rutas de código del monolito
> que aparecen aquí (`app.js`, `src/`, `views/`, `middleware/`, `config/`,
> `services/`, `public/`, `uploads/`) son **relativas a `apps/web-monolito/`**.
> Lo compartido —`db/`, `deploy/`, `docs/`, `tests/`— sigue en la raíz.

Cada decisión sigue el esquema pedido en el enunciado:

> necesidad o problema → alternativas consideradas → decisión tomada →
> justificación técnica → riesgo o limitación → evidencia de validación

El objetivo no es justificar lo que ya está hecho, sino dejar constancia de qué
se comparó y qué haría cambiar de opinión. Una decisión sin condición de reversa
es una preferencia, no una decisión de ingeniería.

---

## DEC-01 · Monolito, no componentes desacoplados

**Necesidad.** Servir una aplicación de gestión de catálogo, con un solo equipo
(una persona), un solo servidor y un volumen de decenas de libros.

**Alternativas.** (a) Monolito server-side. (b) API REST en Node + cliente SPA.
(c) Microservicios por dominio: catálogo, usuarios, imágenes.

**Decisión.** Monolito server-side, modularizado por dominio.

**Justificación.** El costo de un sistema distribuido se paga en operación, no en
código: despliegue coordinado, consistencia entre servicios, trazabilidad
distribuida, versionado de contratos. Ninguno de esos costos compra nada aquí,
porque no hay varios equipos que necesiten desplegar por separado, ni partes con
perfiles de carga distintos que convenga escalar de forma independiente. Con un
monolito, una operación que toca libro + autores + géneros es **una transacción
de PostgreSQL**; repartida en tres servicios sería una saga con compensaciones.

**Riesgo / limitación.** Todo escala junto: si el catálogo necesitara diez veces
más CPU, habría que replicar también el módulo de usuarios. El estado en memoria
(sesiones, contador de intentos de login) impide correr dos instancias sin
cambios. Un error no controlado en cualquier módulo tumba el proceso entero.

**Qué justificaría cambiarlo.** Que varios equipos deban desplegar por separado;
que un módulo concreto tenga un perfil de carga radicalmente distinto; o que se
necesite disponibilidad por partes. El primer paso no sería microservicios, sino
mover las sesiones fuera del proceso y correr N instancias del mismo monolito
detrás del proxy — eso da escalado horizontal sin ninguno de los costos de
arriba.

**Evidencia.** `docs/ARCHITECTURE_MONOLITHIC.png`; el diagrama marca la frontera
de la unidad desplegable. `tests/pruebas.sh` corre contra un solo proceso.

---

## DEC-02 · Acceso directo a PostgreSQL con `pg`, sin ORM

**Necesidad.** Consultar y escribir datos relacionales con relaciones N:M y
agregaciones.

**Alternativas.** (a) Controlador `pg` con SQL escrito a mano. (b) Sequelize o
TypeORM. (c) Un constructor de consultas como Knex.

**Decisión.** `pg` directo, con SQL parametrizado, concentrado en `*.model.js`.

**Justificación.** El ejercicio evalúa el modelo relacional y la normalización.
Un ORM esconde precisamente lo que hay que demostrar: qué `JOIN` se ejecuta y
por qué. Además, la consulta de catálogo une dos dependencias multivaluadas
independientes; un ORM ingenuo la resolvería con N+1 consultas o con un `JOIN`
que multiplica filas. Con SQL propio se usan subconsultas laterales y sale en
una sola consulta correcta.

**Riesgo / limitación.** Más código repetitivo, y el mapeo fila → objeto queda a
cargo del programador. No hay migraciones automáticas: el esquema se versiona a
mano en `db/`.

**Qué justificaría cambiarlo.** Un modelo con muchas más entidades donde el
repetitivo dominara, o un equipo grande que necesitara una capa uniforme.

**Evidencia.** `db/03_all_quieries_before_stored_procedures.sql` documenta cada
consulta antes de encapsularla. `db/06_views.sql` explica por qué se usan
`LATERAL` en vez de `JOIN` + `GROUP BY`.

---

## DEC-03 · Renderizado en el servidor con EJS

**Necesidad.** Generar la interfaz.

**Alternativas.** (a) EJS. (b) Cadenas de plantilla en JavaScript, sin motor.
(c) Un cliente SPA que consuma una API.

**Decisión.** EJS, con las plantillas en `views/` y parciales compartidos.

**Justificación.** (c) queda descartado por la restricción del ejercicio: exige
server-side y prohíbe JSON como mecanismo de intercambio. Entre (a) y (b), EJS
gana por una razón concreta de seguridad: su etiqueta de salida escapada es el
comportamiento **por omisión**, mientras que con cadenas de plantilla el escapado
depende de que quien escribe la vista se acuerde de llamar a la función de
escape en cada interpolación. Un solo olvido en un atributo `value=` es un XSS
almacenado. Con EJS, el olvido produce texto escapado, que es el fallo seguro.

**Riesgo / limitación.** Un motor de plantillas más. Un `<%- %>` mal usado
reintroduce el riesgo, así que la regla del proyecto es que la salida cruda se
use **sólo** para incluir parciales.

**Qué justificaría cambiarlo.** Que la interfaz necesitara interactividad rica
(arrastrar y soltar, actualizaciones en vivo); ahí un cliente SPA con una API
empezaría a pagarse. Hoy no hay nada de eso.

**Evidencia.** PR-16 y PR-17: un `<script>` escrito en el buscador se muestra
escapado y no se ejecuta.

---

## DEC-04 · Modelo normalizado hasta 4FN, con cuatro tablas puente

**Necesidad.** Representar que un libro tiene varios autores, varios géneros,
varios conceptos y varias imágenes.

**Alternativas.** (a) Columnas repetitivas o listas separadas por comas dentro de
`libros`. (b) Una sola tabla puente `libro_autor_genero`. (c) Una tabla puente
por cada relación.

**Decisión.** (c): `libros_autores`, `libros_generos`, `libros_conceptos`,
`imagenes_libros`.

**Justificación.** Las cuatro son dependencias multivaluadas **independientes**
sobre libro. En (b), un libro con 3 autores y 2 géneros necesitaría 6 filas para
expresar lo que son 5 datos, y esas 6 filas afirman combinaciones que nadie
capturó. Agregar un género obligaría a insertar una fila por autor. En (a) es
imposible buscar por autor sin partir cadenas, y corregir el nombre de un autor
exige editar todos sus libros.

Caso aparte: la **definición** de un concepto no vive en el catálogo de términos
sino en `libros_conceptos`, porque depende del par (libro, concepto). "Bucket"
significa una cosa en un libro de Cloud Computing y otra en uno de estadística.

**Riesgo / limitación.** Más `JOIN` en las lecturas. Se mitiga con vistas
(`v_libros_detalle`) para que la complejidad se escriba una sola vez.

**Qué justificaría cambiarlo.** Nada dentro de este alcance. Desnormalizar sería
razonable sólo con volúmenes donde el costo de los `JOIN` fuera medible, y aun
entonces se haría con una vista materializada, no rompiendo el modelo.

**Evidencia.** `docs/NORMALIZATION_4FN.xlsx` (hoja «6. 4FN» muestra las filas
inventadas del caso (b)); `docs/DB_DESIGN_ER_4FN.png`.

---

## DEC-05 · La regla "un solo Administrador" vive en la base de datos

**Necesidad.** Garantizar que nunca exista un segundo Administrador.

**Alternativas.** (a) Comprobar en el controlador antes de insertar. (b) Un
disparador que valide. (c) Un índice único parcial.

**Decisión.** (c) como defensa dura, más (b) para el mensaje de error, más una
traducción en el controlador para la interfaz.

**Justificación.** (a) es una condición de carrera: dos peticiones simultáneas
leen "hay 1 admin", ambas concluyen que pueden insertar, y quedan 2. (b) por sí
solo también puede sufrirlo bajo ciertos niveles de aislamiento. Un índice único
parcial `ON usuarios (rol) WHERE rol = 'admin'` lo resuelve a nivel de motor:
sólo indexa las filas de administrador, así que admite N lectores y rechaza el
segundo admin incluso ante inserciones concurrentes. El disparador sólo existe
para cambiar «duplicate key value violates unique constraint» por una frase que
un humano entienda.

**Riesgo / limitación.** Dos lugares que expresan la misma regla. Se acepta
porque cumplen papeles distintos: uno garantiza, el otro comunica. Existe además
`trg_conservar_admin`, el simétrico, para que nadie borre o degrade al único
Administrador y deje el sistema sin quien lo gobierne.

**Evidencia.** `db/03`, prueba C24; PR-28 y PR-29.

---

## DEC-06 · Validación server-side como única validación que cuenta

**Necesidad.** Impedir que entren datos inválidos.

**Alternativas.** (a) Confiar en `required`, `type="number"` y `minlength` del
formulario. (b) Validar sólo en la base de datos. (c) Validar en el servidor y
además declarar las reglas críticas en la base de datos.

**Decisión.** (c).

**Justificación.** (a) es cosmética: un `POST` con curl la ignora por completo,
y los formularios del proyecto llevan `novalidate` justamente para que durante
las pruebas se vea actuar a la del servidor. (b) sola da mensajes ilegibles y no
permite devolver el formulario con lo que el usuario ya había escrito. La
combinación da lo mejor de ambas: mensajes útiles arriba, garantía abajo.

**Riesgo / limitación.** La regla se enuncia dos veces (por ejemplo, precio ≥ 0
en `services/validacion.js` y en `ck_libros_precio`). Es duplicación deliberada:
la del servidor explica, la de la base de datos garantiza.

**Evidencia.** PR-21 a PR-27 y PR-30, PR-31: todos son `POST` hechos con curl,
sin pasar por el navegador.

---

## DEC-07 · Node escucha en `127.0.0.1` y publica bajo `/library` vía proxy

**Necesidad.** Publicar la aplicación en internet sin exponer el proceso.

**Alternativas.** (a) Node en `0.0.0.0:3000` con el puerto abierto en el
firewall. (b) Node en `0.0.0.0:80` como root. (c) Node en loopback + reverse
proxy.

**Decisión.** (c), con el prefijo público configurable por variable de entorno.

**Justificación.** (b) exige privilegios de root para un proceso que ejecuta
código de aplicación: es exactamente lo que no se quiere. (a) deja el puerto
expuesto y depende de que el firewall nunca se configure mal. Con (c), aunque
alguien abriera el 3000 en GCP, no habría nada escuchando en la interfaz
pública. Además el proxy termina TLS, sirve los estáticos sin despertar a Node y
permite reiniciar la aplicación sin cambiar la URL.

El prefijo se resuelve con `BASE_PATH`: todas las plantillas construyen sus
enlaces como `<%= base %>/libros`, así que la misma imagen del código funciona en
la raíz durante el desarrollo y bajo `/library` en la VM. La alternativa —que el
proxy reescriba las rutas— rompe los `redirect` de Express, que salen con ruta
absoluta.

**Riesgo / limitación.** Una pieza más que configurar y que puede quedar mal.
Si `BASE_PATH` no coincide con el `location` del proxy, los enlaces apuntan a
donde no es. En SELinux hay que habilitar `httpd_can_network_connect` o Apache
devuelve 503 sin explicar por qué.

**Evidencia.** `deploy/nginx-library.conf`, `deploy/apache-library.conf`,
`config/env.js`.

---

## DEC-08 · Validación de imágenes por firma binaria, no sólo por extensión

**Necesidad.** Aceptar imágenes sin aceptar código ejecutable.

**Alternativas.** (a) Filtrar por extensión. (b) Filtrar por el tipo MIME que
declara el navegador. (c) Ambas más comprobar los primeros bytes del archivo ya
escrito.

**Decisión.** (c), más nombre generado por el servidor y borrado del archivo si
cualquiera de las comprobaciones falla.

**Justificación.** (a) y (b) son datos que envía el cliente y se falsifican
trivialmente: `curl -F "imagen=@shell.php;type=image/png"` pasa las dos. Leer los
primeros bytes del archivo ya escrito y comprobar que son los de un JPEG, PNG o
WebP real cierra ese hueco. El nombre lo genera el servidor (UUID + extensión de
la lista blanca), así que ni siquiera hay superficie para `../` o dobles
extensiones; el nombre original se guarda sólo como metadato.

**Riesgo / limitación.** Un archivo puede tener una cabecera PNG válida y datos
maliciosos después; eso sólo se detectaría reprocesando la imagen con una
biblioteca de tratamiento. Se acepta porque el archivo se sirve con `nosniff` y
`Content-Disposition: inline`, y el proxy además niega servir extensiones
ejecutables desde `uploads/`.

**Evidencia.** PR-40 a PR-46: un PHP renombrado a `.png`, un `.sh` con MIME
falseado, un PDF y un archivo de 3 MB son rechazados; sólo el PNG válido queda
en disco.

---

## DEC-09 · Token anti-CSRF propio, sin dependencia extra

**Necesidad.** Impedir que un sitio ajeno provoque escrituras usando la sesión
del Administrador.

**Alternativas.** (a) Confiar sólo en `SameSite=Lax`. (b) Añadir la dependencia
`csurf`. (c) Implementarlo: 32 bytes aleatorios en la sesión, campo oculto en
cada formulario, comparación en tiempo constante.

**Decisión.** (c).

**Justificación.** `SameSite=Lax` ayuda pero no basta: no protege contra
subdominios y su comportamiento varía entre navegadores. `csurf` está
descontinuado. La implementación son unas 25 líneas, se entiende leyéndolas y
no añade superficie de dependencias a un proyecto que debe poder defenderse
línea por línea.

**Riesgo / limitación.** Criptografía propia, aunque sea sólo comparar dos
cadenas. Se usa `timingSafeEqual` para no filtrar información por tiempo de
respuesta. **Caso descubierto durante las pruebas:** los formularios
`multipart/form-data` los parsea Multer, que corre *después* del chequeo global,
por lo que `req.body` estaba vacío y la subida siempre daba 403. Se resolvió
aplazando el chequeo para multipart y volviéndolo a invocar después de Multer,
con una comprobación adicional en el controller por si alguien reordena los
middleware.

**Evidencia.** PR-05 (login sin token) y PR-45 (subida sin token): ambos 403.

---

## DEC-10 · Estructura por módulos de dominio, no por tipo de archivo

**Necesidad.** Organizar el código.

**Alternativas.** (a) Por tipo: `models/`, `controllers/`, `routes/`. (b) Por
dominio: `src/modules/libros/` con sus cuatro piezas juntas.

**Decisión.** (b) para model, controller y routes; carpetas transversales
(`config/`, `middleware/`, `services/`, `views/`) para lo compartido.

**Justificación.** Un cambio real casi nunca es "todos los modelos": es "algo de
libros". Con (a) ese cambio se reparte en tres carpetas distintas; con (b) está
en una. La correspondencia con la estructura sugerida en el enunciado se
mantiene: `routes/` son los `*.routes.js`, `controllers/` los `*.controller.js`,
`services/` la lógica compartida, `middleware/` y `config/` tal cual.

Las vistas sí están centralizadas en `views/`, porque es donde Express las busca
y porque comparten parciales entre módulos.

**Riesgo / limitación.** Divergencia entre módulos si cada uno se escribe a su
manera. Se mitiga con la regla de seguir el módulo vecino más parecido, y con
`services/crudCatalogo.js`, que concentra la lógica común de los cinco catálogos
en vez de copiarla cinco veces.

**Evidencia.** `README.md` §Estructura de archivos.

---

## DEC-11 · Procedimientos almacenados sólo donde compran atomicidad

**Necesidad.** Decidir qué lógica baja a la base de datos.

**Alternativas.** (a) Toda la lógica de negocio en procedimientos. (b) Ninguna.
(c) Sólo lo que debe ser atómico o lo que ninguna capa superior garantiza.

**Decisión.** (c). Cinco rutinas: `sp_guardar_libro`,
`sp_guardar_concepto_libro`, `sp_ajustar_stock`, `sp_marcar_portada` y
`fn_buscar_libros`.

**Justificación.** (a) parte la verdad en dos lugares y hace la lógica difícil de
versionar y de probar. (b) deja huecos reales: guardar un libro con sus autores
serían tres viajes a la base de datos, y si el segundo falla queda un libro sin
autores. `sp_ajustar_stock` existe por lo mismo: leer el stock en Node, calcular
y volver a escribir permite que dos peticiones simultáneas se pisen; hacer la
aritmética dentro del `UPDATE` no.

**Riesgo / limitación.** Lógica en un lenguaje distinto, sin las mismas
herramientas de depuración, y que se despliega por separado del código. Por eso
la lista es corta y cada rutina documenta en su cabecera *por qué existe*.

**Evidencia.** `db/04_stored_procedures.sql`; verificado en base de datos con
`sp_guardar_libro` sin autores → `check_violation`.

---

## DEC-12 · Usuario de PostgreSQL con privilegios mínimos

**Necesidad.** Limitar el daño si la aplicación fuera comprometida.

**Alternativas.** (a) Conectarse como `postgres`. (b) Un usuario dueño de las
tablas. (c) Un usuario que sólo pueda leer y escribir filas.

**Decisión.** (c). `libreria_app` recibe `SELECT/INSERT/UPDATE/DELETE` y
`USAGE` sobre las secuencias, nada más. Las tablas pertenecen a
`libreria_owner`, que sólo se usa para ejecutar los scripts de `db/`.

**Justificación.** Con (a) o (b), una inyección exitosa —o un error de
programación— podría ejecutar `DROP TABLE`. Con (c) el motor lo rechaza aunque
la sentencia llegue a ejecutarse: el daño máximo posible es sobre los datos, no
sobre el esquema.

**Riesgo / limitación.** Aplicar una migración exige cambiar de usuario, lo que
es incómodo a propósito: obliga a que el cambio de esquema sea un acto
deliberado y no algo que la aplicación pueda hacer sola.

**Evidencia.** `db/00_create_database.sql`, incluida la consulta final que
comprueba que `libreria_app` no tiene ningún atributo de privilegio.

---

## DEC-13 · Sesiones en memoria del proceso

**Necesidad.** Mantener la sesión entre peticiones.

**Alternativas.** (a) Almacén en memoria. (b) `connect-pg-simple` sobre
PostgreSQL. (c) Redis.

**Decisión.** (a), reconociendo explícitamente su límite.

**Justificación.** Con una sola instancia, (a) funciona y no añade
infraestructura. (c) obligaría a instalar y operar otro servicio en la VM sólo
para esto.

**Riesgo / limitación.** Al reiniciar la aplicación, todos los usuarios pierden
la sesión. Y con dos instancias detrás del proxy, un usuario autenticado en una
aparecería como anónimo en la otra: **la aplicación no se puede escalar
horizontalmente tal como está**. El contador de intentos de login tiene el mismo
problema.

**Qué justificaría cambiarlo.** La primera segunda instancia. El cambio sería
mínimo —`connect-pg-simple` con la tabla en la base que ya existe— y es la
opción preferida sobre Redis, por no sumar un servicio más.

**Evidencia.** `app.js`, configuración de `express-session`; anotado también en
[SECURITY_REVIEW.md](SECURITY_REVIEW.md) como riesgo residual aceptado.
