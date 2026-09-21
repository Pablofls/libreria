respuestas bilingües (XML + JSON) en apps/services/catalogo

Trabaja EXCLUSIVAMENTE dentro de `apps/services/catalogo/`, sobre el microservicio Flask
`apps/services/catalogo/app.py`. No toques el monolito Node (`app.js`, `src/`, `views/`,
`middleware/`), ni `apps/services/soap/`, ni nada en `db/`. No se
agregan dependencias nuevas: `jsonify` ya se importa.

## Lo que pide el enunciado, literal

    http://host:5001/books?format=json
    http://host:5001/books/9780451524935?format=json
    …y así con el resto de endpoints

De ahí salen cuatro requisitos:

1. El servicio es `apps/services/catalogo/app.py`, el Flask de una sola aplicación sin
   Blueprints. Se modifica ese, no se crea uno nuevo.
2. El formato de la respuesta lo elige el parámetro de query `format`.
3. **Todos** los endpoints deben poder contestar en JSON y en XML
   indistintamente — ninguno queda fuera.
4. **Sin el parámetro `format`, la respuesta es siempre XML.** Ese es el
   comportamiento por defecto y no debe cambiar para ningún cliente existente.

## Rutas: el enunciado y el código no coinciden hoy

El enunciado usa `/books` y `/books/{isbn}`. El código expone `/api/books`,
`/api/books/search`, `/api/book/{isbn}` (singular), `/api/book/author/{id}`,
`/api/book/insert`, `/api/book/update[/{isbn}]`, `/api/book/delete[/{isbn}]`,
`/api/health`.

Registra las rutas del enunciado **como alias, sin el prefijo `/api`, apuntando
a la misma función de vista** (Flask admite varios `@app.route` sobre un mismo
`def`; ya se hace con `/api/book/update` y `/api/book/update/<isbn>`). Las rutas
`/api/...` actuales **se conservan todas**: hay clientes y documentación que ya
las usan, y romperlas no es parte del encargo.

Para la ficha de un libro, el alias es `/books/{isbn}` (plural, como el
enunciado), aunque la ruta existente sea `/api/book/{isbn}`. Nombra los alias de
forma coherente para el resto: `/books/search`, `/books/author/{id}`,
`/books/insert`, `/books/update[/{isbn}]`, `/books/delete[/{isbn}]`, `/health`.
Si algún alias colisiona con otra regla —`/books/search` contra
`/books/{isbn}`—, resuélvelo con el orden de declaración o un converter, y deja
el motivo en un comentario.

Actualiza también la lista de endpoints que devuelve la ruta `/` para que
incluya ambas familias.

## Puerto

El enunciado dice 5001; `app.py` lee `SOAP_PORT` con default **5000** (el 5001
es de `apps/services/soap`, un servicio distinto). Cambia el default
a 5001 sólo si confirmas que los dos no se levantan a la vez en la misma VM; si
pueden convivir, **deja el default como está** y documenta que en la VM se
arranca con `SOAP_PORT=5001`. Elijas lo que elijas, dilo explícitamente en tu
respuesta final — no lo cambies en silencio.

## Contrato del parámetro `format`

- `?format=xml` o ausente → XML, exactamente el de hoy (byte por byte, incluida
  la cabecera `<?xml-stylesheet?>` que hace que `library.css` pinte el catálogo
  en el navegador).
- `?format=json` → `application/json; charset=utf-8`.
- Valor distinto de esos dos → error 400 explicado, servido en XML (el formato
  por defecto), listando los valores admitidos.
- El valor se compara sin distinguir mayúsculas y sin espacios alrededor.
- Como respaldo secundario, si NO viene `format` pero el `Accept` pide
  `application/json`, responde JSON. El parámetro siempre gana sobre `Accept`.
  Un `Accept: */*` (lo que manda `curl` por defecto) es XML, no JSON.
- El parámetro funciona igual en GET y en las escrituras (POST/PUT/DELETE): un
  cliente que da de alta un libro con `?format=json` recibe la confirmación en
  JSON.

Aplica a **todas** las rutas que hoy devuelven XML, sin excepción, y también a
los **manejadores de error**: 404, 405, 503, el `Exception` genérico y los 400
de validación. Un cliente JSON que pide un ISBN inexistente debe recibir un
error en JSON, no un XML. Ojo con el 404: se dispara sobre rutas que no
existen, así que el despachador de formato tiene que leer el query string aun
cuando no haya vista asociada.

`/library.css`, `/docs` y `/apispec.json` conservan su tipo actual.

## Cómo hacerlo (esto es lo importante)

El problema real no es agregar `jsonify`, es que hoy `libro_a_xml` construye
nodos de ElementTree directamente desde la fila de la base. Si escribes un
serializador JSON en paralelo, los dos formatos se separan al primer cambio de
esquema.

Refactoriza a un solo punto de verdad:

1. Una función neutra —`libro_a_dict(libro)`— que produzca la representación del
   libro como dict/list de Python puro, con **los mismos nombres en inglés que
   ya usan las etiquetas XML** (`title`, `authors`, `year`, `genres`, `price`,
   `stock`, `format`, `images`, `concepts`, y `isbn`, que hoy es atributo).
   Mantén el detalle de que `description` pertenece al par (libro, concepto).
2. Un renderizador XML que parta de esa estructura y produzca **el XML actual
   sin cambios** — atributos donde hoy hay atributos (`isbn`, `order`,
   `nationality`, `cover`, `type`, `term`, `chapter`, `page`), elementos donde
   hoy hay elementos.
3. Un único despachador de salida —algo como `responder(datos, estado=200)`—
   que mire el formato pedido y elija renderizador. Que `responder_xml` y
   `error_xml` queden expresados en términos de él, o se reemplacen por
   `responder` / `error_respuesta`; ninguna vista debería seguir llamando
   directamente a la construcción de XML.

Cuidado con un campo que se llama igual que el parámetro: el libro tiene
`format` (el formato editorial: pasta dura, digital…) y ahora la query trae
`format` (xml/json). Que no se pisen — sobre todo en `datos_entrantes()`, que
mezcla `request.form` con `request.args`: el `format` de la query **no debe
acabar como dato del libro** en un alta o una modificación. Verifícalo y
arréglalo.

Decisiones de tipos en JSON, tómalas explícitas:
- `price`: número JSON con dos decimales de precisión (`Decimal` no es
  serializable por `json`; conviértelo, no lo dejes explotar en runtime).
- `cover`: booleano real (`true`), no la cadena `"true"` del XML.
- `page`, `year`, `stock`, `order`: enteros o `null`, nunca cadenas.
- Campos que en XML se omiten cuando son nulos (`nationality`, `alt`,
  `chapter`): decide una regla única —omitirlos también en JSON es lo
  consistente— y déjala escrita en un comentario.
- El listado lleva el `count` que hoy vive en `<books count="...">`.
- Acentos y ñ: `ensure_ascii=False`, para que el JSON se lea igual que el XML.
- Los errores en JSON: `{"code": …, "message": …, "details": [...]}`, espejo de
  `<error code><message><detail>`. Sigue sin filtrarse SQL, nombres de tabla ni
  trazas — esa regla no se relaja.

## Documentación, en el mismo cambio

- Actualiza `ESPECIFICACION` (el OpenAPI de `/apispec.json`): declara el
  parámetro `format` en cada operación, añade `application/json` junto a
  `application/xml` en las respuestas, y documenta las rutas nuevas sin `/api`.
  Ajusta la descripción que hoy afirma "Todas las respuestas son
  `application/xml`".
- Si `apps/services/catalogo` tiene README o la página `/docs` describe el contrato,
  actualízalos con la convención y un ejemplo de cada formato.

## Restricciones del entorno

- **La base de datos vive en una VM de GCP y no es alcanzable desde aquí.** No
  intentes conectarte, ni levantar el servicio contra PostgreSQL, ni "verificar"
  respuestas reales.
- Este cambio no toca el esquema, así que no debe generar nada en `db/pending/`.
  Si crees que sí lo necesita, párate y explícame por qué antes de escribir SQL.
- Ninguna credencial en claro, en código ni en comentarios.
- Código y comentarios en español, siguiendo el estilo del archivo (comentarios
  que explican el porqué, no el qué).
- Como verificación, `python3 -m py_compile app.py` y una revisión a mano de que
  el XML generado es idéntico al anterior. Dime qué NO pudiste comprobar.

Al terminar, dame los `curl` para probar en la VM: cada endpoint en sus dos
formatos, con las rutas del enunciado (`/books?format=json`,
`/books/9780451524935?format=json`) y la comprobación de que sin `format` sigue
saliendo XML.


# Tarea: dos endpoints nuevos en apps/services/catalogo + evidencias

Trabaja EXCLUSIVAMENTE dentro de `apps/services/catalogo/` y en `docs/`. No toques el
monolito Node, ni `apps/services/soap/`, ni `db/`. Sin dependencias
nuevas.

Todo lo que agregues hereda el contrato que ya existe: responde en XML y en
JSON segun `?format=`, y sin el parametro responde XML.

## 1. Endpoint de conceptos con sus libros

Debe permitir obtener los conceptos de Cloud Computing —IaaS, PaaS, SaaS,
FaaS…— junto con los datos de los libros donde estan definidos.

Ruta: `/concepts` (+ el alias historico `/api/concepts`, como el resto).

**El problema de fondo, y no lo resuelvas a la ligera:** la tabla `conceptos`
tiene sólo `id` y `termino` (ver `db/01_schema.sql`). **No existe ninguna
columna que marque un concepto como "de Cloud Computing".** Así que:

- **No hardcodees** una lista `('IaaS', 'PaaS', 'SaaS', 'FaaS')` en el código.
  Eso es meter datos disfrazados de código: el día que se siembre "Serverless"
  o "Edge computing", el endpoint miente y nadie sabe por qué.
- **No agregues una columna** para clasificarlos. Eso toca el esquema, y el
  esquema no se cambia en esta tarea. Si al final crees que es la única salida,
  párate y explícamelo antes de escribir SQL.
- La salida correcta es **todos los conceptos del catálogo con los libros que
  los definen**, más un filtro opcional `?termino=` (parcial, sin distinguir
  mayúsculas, como los filtros de `/books/search`). Los de Cloud Computing
  salen porque son los que hay sembrados, no porque el código los conozca.

La estructura invierte el pivote del catálogo: donde `/books` va de libro a
conceptos, éste va de concepto a libros. Y hay un detalle del modelo que no se
puede perder: **la definición vive en `libros_conceptos`, no en `conceptos`** —
el mismo término se define distinto en cada libro. Así que la definición, el
capítulo y la página cuelgan del par (concepto, libro), nunca del concepto.

De cada libro basta con lo que identifica y ubica: ISBN, título, autores y año.
No repitas el libro entero; para eso ya está `/books/{isbn}`.

Un concepto sin libros no puede existir (la FK lo impide), pero el `count` del
contenedor sí importa: úsalo igual que en `<books count="...">`.

## 2. Endpoint de datos mínimos con imágenes

Ruta: `/books/summary` (+ `/api/books/summary`).

Datos mínimos del libro más sus imágenes: ISBN, título y las imágenes con los
mismos campos que ya expone el catálogo (`cover`, `type`, `file`, y `alt`
cuando lo haya). Nada de autores, géneros, conceptos ni sinopsis: el sentido de
este endpoint es ser barato.

Y que lo sea de verdad: hoy `leer_libros()` dispara cuatro consultas de
relaciones N:M además del SELECT principal. **No lo reutilices tal cual para
luego tirar los campos que sobran** — eso paga el coste completo y no ahorra
nada. Escribe la lectura mínima que necesita: el SELECT de libros y el de
imágenes, y ya. Deja en un comentario por qué no se reutiliza `leer_libros`.

Acepta `limite` y `desplazamiento` como `/books`, con el mismo tope de 500.

## 3. Cómo encajarlo, sin romper lo que ya funciona

Hay tres sitios que **hay que tocar juntos** o algo se rompe en silencio:

1. **`RENDERIZADORES_XML`**: cada tipo de carga nueva necesita su renderizador
   XML registrado ahí. `responder(tipo, ...)` lo busca por clave.
2. **La tabla `ALIAS`**: `_publicar_rutas()` hace `ALIAS[historica]` para cada
   ruta de la especificación. Si declaras un path nuevo en `ESPECIFICACION` y
   no lo declaras en `ALIAS`, **`/apispec.json` revienta con `KeyError` al
   importar el módulo** — el servicio ni arranca. Declara ambos.
3. **`library.css`**: la hoja dibuja el XML en el navegador por nombre de
   elemento (`library`, `books`, `book`, `concepts`…). Un elemento raíz nuevo
   sin estilos sale como un chorro de texto plano. Extiéndela para los dos
   endpoints nuevos, siguiendo el estilo que ya tiene (incluidos los `::before`
   con las etiquetas en español). De esto dependen las capturas del punto 4.

Mantén la disciplina que ya sigue el archivo: la vista no construye XML, arma
la estructura neutra y `responder` elige serializador. Los nombres de las
claves, en inglés, como el resto del contrato. SQL parametrizado siempre; los
nombres de tabla y columna son constantes del código, nunca entrada del
usuario.

## 4. Swagger

En el mismo cambio, no después:

- Declara las cuatro rutas nuevas (las dos del enunciado y sus dos alias) en
  `ESPECIFICACION['paths']`, con su `summary`, sus parámetros (`termino`,
  `limite`, `desplazamiento`) y las respuestas en `application/xml` y
  `application/json`. El parámetro `format` lo inyecta `_publicar_rutas`; no lo
  repitas a mano.
- Actualiza la lista de endpoints de la ruta `/`, que sirve de índice.
- Sube la versión del servicio si te parece que lo amerita, y dilo.

## 5. Evidencias y reflexión

**Las capturas las tomo yo, no tú:** no tienes acceso a la VM ni al navegador.
Lo que tú haces es preparar el documento y decirme exactamente qué capturar.

- Crea la carpeta siguiendo el patrón de `docs/ejercicio03/` (que tiene
  `docs/`, `evidencias/` e `img/`). **Pregúntame el número de ejercicio antes
  de crearla**; no lo adivines.
- Escribe el documento con: qué hace cada endpoint, la URL exacta de cada
  captura, los huecos donde irán las imágenes con el nombre de archivo que debo
  usar, y la reflexión.
- Dame al final la lista numerada de URLs a capturar, en XML y en JSON, listas
  para pegar en el navegador contra `http://34.51.28.102:5001`.

La reflexión —**por qué se tiene que hacer así**— es lo que de verdad se
califica. No la rellenes con generalidades sobre REST. Habla de lo que decidió
este código:

- Por qué el "cuáles son de Cloud Computing" no se resuelve con una lista en el
  código sino con los datos, y qué se rompería con la lista.
- Por qué la definición cuelga del par (libro, concepto) y no del concepto: es
  la 4FN del esquema, y es la razón de que el catálogo no pueda tener un
  diccionario global de términos.
- Por qué el endpoint de datos mínimos necesita su propia lectura y no puede
  reutilizar la del catálogo completo.
- Por qué la estructura neutra es un solo punto de verdad, y qué pasaría si XML
  y JSON se serializaran por caminos separados.
- Por qué la respuesta por defecto sigue siendo XML aunque JSON sea más cómodo.

## Restricciones del entorno

- **La base de datos vive en una VM de GCP y no es alcanzable desde aquí.** No
  intentes conectarte ni ejecutar SQL. La verificación se hace en proceso, con
  filas fabricadas y el `test_client` de Flask, y `python3 -m py_compile app.py`.
- Comprueba explícitamente que el XML de los endpoints que YA existían sigue
  siendo idéntico byte por byte al de `HEAD`. Es la regresión más fácil de
  introducir al refactorizar la capa de lectura.
- Ninguna credencial en claro, en código ni en comentarios.
- Código y comentarios en español, siguiendo el estilo del archivo: comentarios
  que explican el porqué, no el qué.
- Dime al terminar qué NO pudiste comprobar.