# Métricas técnicas y reflexión — Tarea 5

Medidas para comparar contra REST en la sesión siguiente. Todas se tomaron en la
corrida local, contra la base desechable reconstruida con los scripts canónicos.

## 1. Tamaño de los mensajes

`RegistrarClasificacion`, una operación con seis campos de negocio:

| Mensaje | Bytes totales | Datos de negocio | Estructura XML |
|---|---|---|---|
| Petición | 642 B | 99 B | **84.6 %** |
| Respuesta | 629 B | 88 B | **86.0 %** |

Es decir: de cada 100 bytes que viajan, unos 85 son sobre, namespaces y nombres
de elemento. Los sobres reales están en [`evidencias/`](evidencias/).

Para comparar honestamente contra REST habrá que medir la misma operación con la
misma carga útil, no una más simple.

## 2. Líneas de código

Contadas sin líneas en blanco ni comentarios.

| Componente | Total | Sólo código |
|---|---|---|
| `app.py` | 122 | 78 |
| `config/ajustes.py` | 87 | 47 |
| `db/acceso.py` | 254 | 183 |
| `soap/envelope.py` | 113 | 74 |
| `soap/faults.py` | 116 | 69 |
| `soap/security.py` | 154 | 99 |
| `soap/service.py` | 243 | 166 |
| **Servidor completo** | **1089** | **716** |
| Cliente de escritorio (Tkinter) | 323 | 251 |
| Cliente generado desde WSDL (zeep) | 120 | 85 |
| WSDL | 404 | — |
| SQL del módulo | 375 | — |

El dato que importa para la comparación: **el cliente manual necesita 251 líneas
y el generado desde el contrato, 85** — y de esas 85, la mayoría son mensajes en
pantalla. El contrato se paga solo del lado del cliente.

Del servidor, unas 143 líneas de código (`envelope.py` + `faults.py`) existen
sólo para armar y leer sobres: trabajo que un stack SOAP haría solo y que REST
no requeriría en absoluto.

## 3. Tiempo de desarrollo

*(Completar con el tiempo real invertido; incluir el de revisión y pruebas, no
sólo el de escritura.)*

| Actividad | Tiempo |
|---|---|
| Análisis del sistema y diseño del contrato | |
| Script SQL y permisos | |
| Implementación del módulo | |
| Pruebas y correcciones | |
| Cliente de escritorio | |
| Documentación y reporte web | |

## 4. Preguntas de reflexión

**¿Qué pasaría si agregas un campo obligatorio a `RegistrarClasificacion` sin
actualizar a los clientes?** Los clientes generados desde el WSDL viejo seguirían
enviando el sobre sin ese campo; el servidor lo rechazaría con `DATO_INVALIDO` y
la operación dejaría de funcionar para todos. Por eso todo campo nuevo entra como
`minOccurs="0"` y un cambio incompatible exige una segunda versión del contrato.

**¿Qué información del WSDL sería útil para un atacante?** Los nombres exactos de
operación y campo, el patrón del ISBN y la enumeración de modelos: con eso
construye peticiones válidas sin adivinar. No debería exponerse: el `id` interno
de las filas, columnas comerciales, ni nada de `usuarios`.

**¿Por qué el tipado XSD aporta certeza?** Porque mueve la validación al cliente
y la vuelve verificable por máquina: `zeep` rechazó `"XaaS"` sin salir a la red,
con el mismo criterio que el servidor. Sin tipos, esa comprobación existiría dos
veces, escrita a mano, y podría divergir.

**¿Qué partes del Envelope fueron boilerplate y cuáles dependieron de la
operación?** Boilerplate: `Envelope`, `Header`, `Body`, declaraciones de
namespace y la envoltura del Fault — idénticos en las cuatro operaciones, unas
143 líneas de servidor. Dependiente: el elemento raíz de cada operación y sus
hijos, es decir los campos de negocio.

**¿Cuándo se justifica el overhead de XML?** Cuando los consumidores son
heterogéneos y difíciles de actualizar, cuando el contrato debe ser verificable
por máquina, y cuando el volumen es bajo comparado con el costo de un error de
integración. Aquí, ~540 bytes de estructura por operación son irrelevantes; en
un servicio de alto volumen, no.

**¿Por qué un SOAP Fault es parte del contrato y no sólo un error HTTP?** Porque
el WSDL declara qué faults puede devolver cada operación, con su tipo, y el
cliente los recibe como excepciones tipadas. Un 500 con texto libre obliga a cada
cliente a inventar su propia interpretación.

**¿Cómo debe reaccionar una GUI ante un Fault de cliente frente a uno de
servidor?** Ante `soap:Client`, corregir la entrada: señalar el campo y no
reintentar. Ante `soap:Server`, no culpar al usuario: avisar que el servicio no
está disponible y permitir reintentar. `cliente_escritorio.py` traduce cada
código a un mensaje y nunca muestra el detalle técnico.

**¿Qué riesgo existe porque el módulo SOAP y el monolito comparten base?** El
acoplamiento por esquema: un cambio en el monolito puede romper el módulo sin que
nadie toque su código, y la clave foránea compuesta del módulo puede bloquear un
`ALTER` del monolito. Mitigado con vistas y permisos de columna.

**¿Qué ocurriría si el monolito renombra `libros.isbn`?** La vista
`v_conceptos_clasificables` fallaría y con ella todas las lecturas. Se reduce
absorbiendo el renombre dentro de la vista, que es el único lugar que conoce el
nombre real; el código Python no cambia.

**¿Dónde debe aplicarse autenticación y qué problema resuelve WS-Security?**
En toda operación que exponga datos agregados o escriba. Hoy sólo está en
`ObtenerEstadisticasPorModelo`. WS-Security resuelve autenticar **el mensaje**,
no la conexión: el token viaja dentro del sobre, sobrevive a proxies e
intermediarios y no depende de cookies ni de sesión.

**¿Basta con confiar en el correo que envía el cliente?** No. Hoy cualquiera
puede registrar clasificaciones a nombre de otro: el correo es una afirmación sin
prueba. Es el riesgo 2 de la auditoría del contrato y lo primero que cambiaría.

**¿En qué escenarios seguirías eligiendo SOAP en 2026?** Integración con sistemas
empresariales que ya lo hablan (banca, ERP, gobierno); cuando se requiere firma o
cifrado a nivel de mensaje —no sólo de transporte— y transacciones distribuidas;
y cuando el contrato debe ser un artefacto formal, versionado y auditable entre
organizaciones. Para una API pública nueva consumida por navegadores, no.
