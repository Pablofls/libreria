# Reporte técnico — Librería Online

> **Rutas.** El repositorio es un monorepo. Las rutas de código del monolito
> que aparecen aquí (`app.js`, `src/`, `views/`, `middleware/`, `config/`,
> `services/`, `public/`, `uploads/`) son **relativas a `apps/web-monolito/`**.
> Lo compartido —`db/`, `deploy/`, `docs/`, `tests/`— sigue en la raíz.

Ejercicio guiado 02 · Integración de Aplicaciones Computacionales · UDEM

Este reporte no describe únicamente lo que se hizo: justifica por qué se decidió
así y qué consecuencias tiene. Donde una afirmación se puede comprobar, se dice
con qué.

| | |
|---|---|
| Repositorio | este mismo |
| Aplicación | Node.js 20 + Express 5 + EJS · PostgreSQL 14+ |
| Despliegue | Compute Engine (CentOS Stream 10), Node en `127.0.0.1:3000` tras reverse proxy en `/library` |
| Estado de las pruebas | 57/57 de aplicación · 7/7 negativas de base de datos |

---

## 1. Problema y alcance

Una librería necesita administrar su catálogo: libros con sus autores, géneros,
categorías, formatos, precio, existencias, imágenes y un glosario de conceptos
propio de cada título. Los usuarios registrados consultan; un único
Administrador mantiene los datos.

El problema interesante no es el CRUD. Son tres cosas:

1. **Un libro tiene varios autores, varios géneros, varios conceptos y varias
   imágenes, y esos cuatro conjuntos son independientes entre sí.** Modelarlo mal
   produce datos que afirman combinaciones que nadie capturó.
2. **La definición de un concepto no pertenece al concepto**, sino al par
   (libro, concepto): «Bucket» significa una cosa en un libro de Cloud Computing
   y otra en uno de estadística.
3. **La regla de un solo Administrador tiene que ser verdad**, no una convención
   de la interfaz que dos peticiones simultáneas puedan romper.

Lo que queda fuera, deliberadamente: carrito, pagos, envíos, reseñas,
recuperación de contraseña por correo, API para terceros. Ver
[REQUIREMENTS.md](REQUIREMENTS.md) §1.

---

## 2. Requisitos

13 requisitos funcionales (`RF-01` … `RF-13`) y 11 no funcionales
(`RNF-01` … `RNF-11`), cada uno con criterio de aceptación y la prueba que lo
verifica. Los actores son tres —Visitante, Usuario Registrado y Administrador— y
para cada uno se documenta tanto lo que puede hacer como **lo que debe
rechazársele**, que es la parte que se suele olvidar.

Los riesgos se identificaron antes de programar, no después: acceso no
autorizado, inyección SQL, subida de archivos peligrosos, exposición de
credenciales, eliminación accidental y publicación de datos sensibles. Cada uno
tiene mitigación aplicada y riesgo residual declarado
([REQUIREMENTS.md](REQUIREMENTS.md) §6).

Uno de esos riesgos **se materializó**: al revisar el repositorio se encontraron
contraseñas escritas en claro en comentarios ya versionados. Está documentado
como hallazgo abierto en [SECURITY_REVIEW.md](SECURITY_REVIEW.md) H-01, con la
única solución real, que es rotarlas.

---

## 3. Macro-arquitectura

![Arquitectura](ARCHITECTURE_MONOLITHIC.png)

El flujo es: navegador → Apache/NGINX → Node/Express → módulos internos →
PostgreSQL. Interfaz, lógica de negocio y acceso a datos viven en **una sola
unidad desplegable**.

**Por qué sigue siendo un monolito aunque el código esté organizado en módulos.**
La palabra clave es *desplegable*. Los nueve módulos se comunican con llamadas de
función dentro del mismo proceso, no por red. No hay contratos entre ellos, ni
versionado, ni posibilidad de desplegar `libros` sin desplegar `usuarios`. Un
sistema es distribuido cuando sus partes pueden fallar por separado; aquí no
pueden. La modularización sirve para encontrar el código y para limitar el
alcance de un cambio, no para separar el despliegue.

La consecuencia práctica que más se nota: guardar un libro con sus autores y sus
géneros es **una transacción de PostgreSQL**. Repartido en tres servicios sería
una saga con compensaciones, y habría que decidir qué hacer si el segundo paso
falla. Ese costo no compra nada en este contexto (DEC-01).

---

## 4. Organización del código

```
app.js              Arranque, middleware general, montaje de rutas
config/             env.js (lee y valida .env) · db.js (Pool único de pg)
middleware/         auth.js · locals.js (CSRF) · subidas.js (Multer) · errores.js
services/           validacion.js · crudCatalogo.js
src/modules/<n>/    <n>.model.js · <n>.controller.js · <n>.routes.js
views/              30 plantillas EJS + parciales
public/             CSS y JavaScript de interfaz
uploads/            Imágenes subidas, fuera de public/
db/                 00…06 scripts + pending/ y applied/
docs/ · deploy/ · tests/
```

| Capa | Responsabilidad | Regla que no se rompe |
|---|---|---|
| `*.model.js` | Todo el SQL, parametrizado | No conoce `req`, `res` ni HTML |
| `views/*.ejs` | Generar HTML | No hace consultas ni contiene lógica de negocio |
| `*.controller.js` | Orquestar: validar, llamar al model, elegir vista | No contiene SQL ni arma HTML |
| `*.routes.js` | Mapear método + URL → controller | No contiene lógica |
| `middleware/` | Preocupaciones transversales | No conoce ningún dominio |
| `services/` | Reglas reutilizables entre módulos | No conoce HTTP |

La organización es **por dominio**, no por tipo de archivo, porque un cambio real
casi nunca es «todos los modelos»: es «algo de libros». La correspondencia con la
estructura sugerida en el enunciado se mantiene una a una (DEC-10).

Un detalle que merece explicación: los cinco catálogos —autores, géneros,
categorías, formatos y conceptos— hacen lo mismo sobre tablas de la misma forma.
En vez de cinco controllers casi idénticos, `services/crudCatalogo.js` concentra
la lógica común y cada módulo declara sus diferencias. Cada módulo conserva su
propio `*.controller.js` como punto de entrada; lo que no se repite cinco veces
es el cuerpo, para no tener que corregir cinco veces cada error.

---

## 5. Modelo de datos y normalización hasta 4FN

![Modelo ER](DB_DESIGN_ER_4FN.png)

11 relaciones: 7 entidades (`usuarios`, `autores`, `generos`, `categorias`,
`formatos`, `libros`, `conceptos`) y 4 tablas puente (`libros_autores`,
`libros_generos`, `libros_conceptos`, `imagenes_libros`).

El recorrido completo desde la relación no normalizada está en
[NORMALIZATION_4FN.xlsx](NORMALIZATION_4FN.xlsx), con la tabla intermedia de cada
paso. El resumen:

- **1FN.** Los grupos repetitivos (`autores` como texto separado por comas) pasan
  a filas. El remedio destapa el problema real: con 3 autores × 3 géneros × 3
  conceptos hacen falta 27 filas para un solo libro.
- **2FN.** El título y el precio dependían sólo de `isbn`, una parte de la clave
  compuesta. Se extraen a `libros`.
- **3FN.** El nombre de la categoría dependía de la categoría, no del libro:
  dependencia transitiva. Se convierten en catálogos `categorias` y `formatos`.
- **BCNF.** `termino` es UNIQUE en `conceptos` y por tanto clave candidata; no
  queda ningún determinante que no sea clave.
- **4FN.** El paso decisivo. Autores, géneros, conceptos e imágenes son cuatro
  dependencias multivaluadas **independientes** sobre libro.

**La demostración de por qué 4FN importa aquí.** Con una sola tabla
`libro_autor_genero`, un libro con 3 autores y 2 géneros necesita 6 filas:

| libro | autor | genero |
|---|---|---|
| 1 | Erl | Cómputo en la nube |
| 1 | Erl | Arquitectura de software |
| 1 | Puttini | Cómputo en la nube |
| 1 | Puttini | Arquitectura de software |
| 1 | Mahmood | Cómputo en la nube |
| 1 | Mahmood | Arquitectura de software |

Cuatro de esas seis filas están inventadas: existen sólo para no perder
información, y sugieren una asociación entre «Puttini» y «Arquitectura de
software» que nadie capturó. Agregar un cuarto género obligaría a insertar tres
filas más, una por autor; olvidar una deja la tabla inconsistente. Separadas en
`libros_autores` (3 filas) y `libros_generos` (2 filas) se expresa lo mismo con 5
filas, ninguna falsa, y la descomposición es sin pérdida: el `JOIN` reconstruye
el original.

**El caso de los conceptos** es el más interesante del modelo. La definición NO
está en `conceptos` sino en `libros_conceptos`, porque depende del par completo.
`v_libros_conceptos` lo hace visible: «IaaS» aparece definido en cuatro libros
con cuatro textos distintos, y ninguno es «el correcto».

---

## 6. Integridad y restricciones en PostgreSQL

La regla que se siguió: **una regla de negocio que la aplicación pueda olvidar
debe estar declarada en la base de datos.**

| Restricción | Qué garantiza |
|---|---|
| `uq_libros_isbn` | Un ISBN identifica una edición; dos filas serían el mismo libro capturado dos veces |
| `ck_libros_precio`, `ck_libros_stock` | Nunca un precio ni un stock negativos, venga la escritura de donde venga |
| `ck_usuarios_hash_bcrypt` | El campo debe tener forma de hash bcrypt: la base de datos rechaza una contraseña en claro |
| `ux_usuarios_admin_unico` | Índice único parcial: como máximo un Administrador, incluso ante altas simultáneas |
| `ux_imagenes_portada_unica` | Una sola portada por libro |
| `ck_imagenes_nombre` | El nombre debe ser UUID + extensión permitida: bloquea `../` y dobles extensiones |
| `ON DELETE CASCADE` | Sólo de libro hacia sus puentes e imágenes, donde el borrado en cadena es lo deseado |
| `ON DELETE RESTRICT` | De los catálogos hacia libros: borrar una categoría en uso debe fallar, no dejar huérfanos |

**Sobre el Administrador único.** Comprobarlo en el controller antes de insertar
es una condición de carrera: dos peticiones simultáneas leen «hay 1», ambas
concluyen que pueden insertar, quedan 2. El índice único parcial lo resuelve en
el motor. El disparador `trg_un_solo_admin` sólo existe para convertir
«duplicate key value violates unique constraint» en una frase legible; y
`trg_conservar_admin`, su simétrico, impide borrar o degradar al único
Administrador y dejar el sistema sin gobierno (DEC-05).

**Procedimientos almacenados.** Cinco, y cada uno documenta en su cabecera *por
qué existe*. `sp_guardar_libro` porque un libro con sus autores es una unidad
atómica; `sp_ajustar_stock` porque leer-calcular-escribir desde Node permite que
dos peticiones se pisen. No se bajó a la base de datos nada que no compre
atomicidad o una garantía que ninguna capa superior pueda dar (DEC-11).

**Pruebas negativas.** Siete sentencias que **deben fallar**, con el error real
de PostgreSQL conservado como evidencia: ISBN duplicado (`23505`), stock negativo
(`23514`), precio inválido (`23514`), FK inexistente (`23503`), borrado que viola
una relación (`23503`), segundo administrador (`23505`) y contraseña sin hashear
(`23514`). Salida en
[`evidencias/pruebas_integridad_sql.txt`](evidencias/pruebas_integridad_sql.txt).

---

## 7. Funcionalidades y flujo navegador → aplicación → base de datos

Ejemplo completo: **guardar un libro**.

1. El Administrador envía `POST /library/libros` con los campos del formulario,
   incluidos varios `autores` y varios `generos` de sendos `<select multiple>`.
2. `verificarCsrf` compara el token del cuerpo con el de la sesión, en tiempo
   constante. Sin coincidencia, 403.
3. `requireAdmin` comprueba el rol. Un lector recibe 403 con página explicativa.
4. `validarLibro` valida tipo, longitud, rango y formato de cada campo, y
   normaliza la selección múltiple (Express entrega una cadena si viene un solo
   valor y un arreglo si vienen varios). Si hay errores, se devuelve el
   formulario con lo capturado y la lista de problemas.
5. El model llama a `sp_guardar_libro`, que en **una transacción** inserta el
   libro y reemplaza por completo sus vínculos N:M.
6. Si PostgreSQL rechaza algo, `middleware/errores.js` traduce el código a un
   mensaje en español y responde 400. El detalle técnico va al log, no al HTML.
7. Con éxito, se guarda un aviso de un solo uso en la sesión y se redirige al
   detalle del libro. El patrón POST-redirect-GET evita que recargar la página
   vuelva a enviar el formulario.

La **búsqueda** merece una nota: es `GET`, no `POST`, para que el resultado se
pueda marcar y compartir por URL, y la regla de coincidencia (ISBN exacto
ignorando guiones, o título parcial, o autor) vive en `fn_buscar_libros`, de modo
que la interfaz y una consulta desde `psql` buscan igual.

---

## 8. Seguridad

Trece controles documentados en [SECURITY_REVIEW.md](SECURITY_REVIEW.md), cada
uno con amenaza, control y evidencia. Los que más definen el diseño:

- **Autenticación y autorización separadas.** `requireLogin` responde «¿quién
  eres?»; `requireAdmin`, «¿puedes hacer esto?». Están en funciones distintas
  porque son decisiones distintas, y confundirlas es como se cuelan los fallos de
  control de acceso.
- **La protección está en la ruta, no en la vista.** Ocultar el botón de borrar
  es comodidad visual. PR-14 lo demuestra: se envía el `POST` de borrado
  directamente, con un token CSRF legítimo de un lector, y se rechaza igual.
- **Validación server-side como única que cuenta.** Los formularios llevan
  `novalidate` a propósito, para que durante las pruebas se vea actuar a la del
  servidor. Todas las pruebas de validación se ejecutan con `curl`.
- **Subidas con cinco capas.** MIME, extensión, tamaño, **firma binaria** del
  archivo ya escrito, y nombre generado por el servidor. Un PHP renombrado a
  `.png` con MIME falseado pasa las dos primeras y muere en la tercera. Tras los
  siete intentos de PR-40 a PR-46, `uploads/` crece exactamente en 1.
- **No se filtra información por el tiempo de respuesta.** Si el correo no
  existe, se compara igualmente contra un hash señuelo, para que la respuesta
  tarde lo mismo que con una contraseña incorrecta y no se pueda enumerar qué
  correos están registrados.
- **Mínimo privilegio.** `libreria_app` sólo puede leer y escribir filas. Aunque
  una inyección llegara a ejecutarse, el motor rechazaría un `DROP`.
- **Secretos.** La aplicación **no arranca** sin `SESSION_SECRET`. Un valor por
  omisión inseguro sería peor que un fallo al arrancar, porque pasa
  desapercibido.

---

## 9. Estrategia de pruebas y resultados

Las pruebas son un script ejecutable, no una lista de capturas:
[`tests/pruebas.sh`](../tests/pruebas.sh) recorre 57 casos e imprime esperado
contra observado. Se puede volver a correr después de cada cambio.

| Bloque | Casos | Resultado |
|---|---|---|
| Autenticación y sesión | 10 | 10/10 |
| Autorización por rol | 14 | 14/14 |
| Búsqueda, XSS e inyección | 5 | 5/5 |
| CRUD y validación server-side | 10 | 10/10 |
| Administrador único | 4 | 4/4 |
| Cabeceras y cookies | 6 | 6/6 |
| Subida de imágenes | 7 | 7/7 |
| Cierre de sesión | 2 | 2/2 |
| Integridad en PostgreSQL (`db/03`) | 7 | 7/7 |

Ocho pruebas manuales (MN-01 … MN-08) cubren lo que no se puede automatizar sin
navegador: verificación visual del glosario, cambio de portada, panel, acceso
desde un equipo externo bajo `/library` y comprobación de que el puerto 3000 no
responde desde fuera.

**Un fallo real encontrado por las pruebas.** Las subidas devolvían 403 siempre.
La causa: el chequeo global de CSRF corre antes de que Multer parsee el cuerpo
`multipart/form-data`, así que `req.body` estaba vacío. Se corrigió aplazando el
chequeo para multipart y volviéndolo a invocar después de Multer, con una
comprobación adicional en el controller por si alguien reordena los middleware.
Sin las pruebas, el error habría llegado a la demostración.

---

## 10. Despliegue

Node escucha en `127.0.0.1:3000`. La cara pública es Apache o NGINX bajo el
prefijo `/library` (`deploy/`), y systemd mantiene el proceso vivo entre
reinicios con el usuario sin privilegios y el sistema de archivos en sólo
lectura salvo `uploads/`.

**Por qué el reverse proxy no es un trámite.** Aunque alguien abriera el puerto
3000 en el firewall de GCP, no habría nada escuchando en la interfaz pública. El
proxy además termina TLS —Node nunca ve una clave privada—, sirve los estáticos
sin despertar al proceso y permite reiniciar la aplicación sin cambiar la URL.

**El prefijo se resuelve con una variable de entorno**, no reescribiendo rutas en
el proxy. Todas las plantillas construyen sus enlaces como `<%= base %>/libros`,
así que el mismo código corre en la raíz durante el desarrollo y bajo `/library`
en la VM. La alternativa —que el proxy quite el prefijo— rompe los `redirect` de
Express, que salen con ruta absoluta.

Los comandos completos, con la justificación del dimensionamiento y de cada
regla de firewall, están en [GCP_COMMANDS.md](GCP_COMMANDS.md).

---

## 11. Limitaciones actuales y riesgos técnicos

| Limitación | Consecuencia | Cuándo habría que atenderla |
|---|---|---|
| Sesiones en memoria del proceso | Reiniciar cierra la sesión de todos; **no se puede correr una segunda instancia** | En cuanto se necesite escalar horizontalmente. `connect-pg-simple` sobre la base que ya existe |
| Límite de intentos de login en memoria | Se reinicia con el proceso y no se comparte entre instancias | Junto con lo anterior |
| Sin paginación en el catálogo | Con 30 libros es correcto; con miles, la página crecería sin control | A partir de unos cientos de títulos |
| Imágenes en el disco de la VM | Se pierden si la VM se recrea sin el disco | Al pasar a más de una instancia, o si se necesita respaldo real |
| Sin HTTPS todavía | Las credenciales viajan en claro dentro de la red | Antes de cualquier uso fuera de la red del curso. La configuración TLS ya está escrita y comentada |
| Sin bitácora de auditoría | No hay registro de quién borró qué | Si el sistema pasara a tener más de un operador |
| `style-src 'unsafe-inline'` en la CSP | Debilita la CSP para estilos; `script-src` sigue estricto | Al mover los `style` puntuales a la hoja |
| Sin recuperación de contraseña | Depende del Administrador para reasignarla | Requeriría envío de correo, fuera del alcance |

---

## 12. Qué cambiaría si el sistema evolucionara a componentes desacoplados

Un ejercicio de análisis, no una propuesta: **hoy el monolito es la decisión
correcta** y desacoplar sin una razón de negocio sería empeorar el sistema.

Si aun así hiciera falta —por ejemplo, porque la gestión de imágenes creciera
hasta necesitar procesamiento pesado y escalado propio—, el orden sensato sería:

1. **Primero, no desacoplar.** Mover las sesiones a PostgreSQL y correr N
   instancias del mismo monolito detrás del proxy. Eso da escalado horizontal sin
   ninguno de los costos de un sistema distribuido, y resuelve la limitación real
   que hoy existe.
2. **Extraer el primer servicio sólo si un módulo tiene un perfil de carga
   genuinamente distinto.** El candidato natural es imágenes: es el único con
   estado en disco y el único cuyo trabajo (validar, redimensionar) es intensivo
   en CPU.
3. **Lo que cambiaría en el código.** Los `*.model.js` seguirían iguales; la
   frontera se rompe en los controllers, que pasarían de llamar a una función a
   hacer una petición de red. Todo lo que hoy es una transacción de PostgreSQL
   —guardar libro + autores + géneros— tendría que reescribirse como una
   secuencia con compensaciones, y habría que decidir qué hacer cuando el segundo
   paso falle.
4. **Lo que se perdería.** Consistencia inmediata, una sola traza por petición,
   despliegue atómico, y la posibilidad de leer todo el sistema en un solo
   repositorio. Lo que se ganaría: escalado y despliegue independientes de una
   parte concreta.
5. **Lo que ya está preparado.** La separación estricta de capas y el hecho de
   que sólo `middleware/subidas.js` toque el sistema de archivos hacen que mover
   las imágenes a un almacenamiento de objetos sea un cambio localizado. Que el
   acceso a datos esté encerrado en `*.model.js` significa que la superficie a
   revisar en una extracción está acotada y es identificable.

La conclusión honesta: la arquitectura actual no impide evolucionar, y el primer
paso de esa evolución no es partir el sistema, sino quitarle el estado en memoria.

---

## 13. Conclusiones

- El trabajo de fondo estuvo en el **modelo de datos**. Las cuatro tablas puente
  no son un adorno académico: son lo que evita que la base afirme cosas falsas.
- **Las reglas críticas viven en la base de datos.** Un `CHECK` o un índice único
  parcial siguen ahí cuando el código cambia, cuando alguien escribe desde
  `psql`, y cuando dos peticiones llegan a la vez.
- **La protección está en la ruta, no en la vista.** Ocultar botones es
  comodidad; la prueba que importa es la que envía el `POST` directamente.
- **Las pruebas encontraron un fallo real** que la revisión de código no vio. Ese
  es el argumento para escribirlas.
- El monolito es la decisión correcta a esta escala, y su límite está
  identificado con precisión: el estado en memoria del proceso. Saber exactamente
  dónde está el techo vale más que fingir que no existe.

---

## Documentos relacionados

| Documento | Contenido |
|---|---|
| [REQUIREMENTS.md](REQUIREMENTS.md) | Requisitos, actores, supuestos y riesgos |
| [ENGINEERING_DECISIONS.md](ENGINEERING_DECISIONS.md) | 13 decisiones con alternativas, riesgo y condición de reversa |
| [SECURITY_REVIEW.md](SECURITY_REVIEW.md) | Controles, hallazgos y riesgos residuales |
| [TEST_PLAN.md](TEST_PLAN.md) | Matriz de pruebas y cobertura por requisito |
| [GCP_COMMANDS.md](GCP_COMMANDS.md) | Infraestructura, PostgreSQL y despliegue |
| [NORMALIZATION_4FN.xlsx](NORMALIZATION_4FN.xlsx) | Proceso de normalización paso a paso |
| [ARCHITECTURE_MONOLITHIC.png](ARCHITECTURE_MONOLITHIC.png) | Diagrama de macro-arquitectura |
| [DB_DESIGN_ER_4FN.png](DB_DESIGN_ER_4FN.png) | Diagrama entidad-relación final |
