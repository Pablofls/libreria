# Clientes de escritorio — modo cliente SOAP

Las dos aplicaciones de escritorio del **Ejercicio Guiado 1** —el clasificador
Cloud en Java/Swing y en Python/CustomTkinter— extendidas con el **modo cliente
SOAP** que pide la Parte 8 del Ejercicio Guiado 3.

Las originales del EG1 **no se tocaron**: viven donde siempre y siguen siendo la
entrega de aquel ejercicio. Éstas son copias versionadas junto al contrato que
consumen, porque un cliente y su contrato se mantienen juntos.

| | |
|---|---|
| `clasificador_python/` | Python 3 + CustomTkinter |
| `clasificador_java/` | Java 21 + Swing, sin dependencias externas |

## Qué se añadió, y qué no se tocó

El clasificador NLP local **sigue intacto**: se añadió una segunda pestaña, no se
reemplazó nada. Ambos modos conviven.

| Archivo | Cambio |
|---|---|
| `soap_cliente.py` / `soap/SoapClient.java` | **Nuevo.** Toda la capa SOAP |
| `soap/SoapFault.java`, `soap/Concepto.java` | **Nuevos.** Vocabulario de errores y el tipo de dato |
| `gui/app_window.py` / `src/gui/AppWindow.java` | Pestañas, la pestaña SOAP y sus manejadores |
| `classifier/…` | **Sin cambios.** El pipeline NLP del EG1 se conserva tal cual |

## Dónde se cruzan los dos ejercicios

El botón **«Sugerir con el clasificador local»** es el punto interesante: toma la
definición del concepto que trajo el servicio SOAP, se la pasa al clasificador
NLP del EG1, y preselecciona el modelo que éste propone. **La decisión sigue
siendo del usuario**; el clasificador sólo sugiere, y el panel NLP de la otra
pestaña muestra los tokens y puntajes que llevaron a esa sugerencia.

No siempre acierta, y eso también es información: para la definición de «Bucket»
en el libro infantil, el clasificador local responde *Desconocido* — la
definición es demasiado corta para su pipeline. La aplicación lo dice en vez de
inventar un modelo.

## La regla que estos clientes respetan

**Ninguno de los dos conoce PostgreSQL.** No hay cadena de conexión, ni SQL, ni
un nombre de tabla en todo `clients/`. Su única puerta al sistema es el endpoint
SOAP, y todo el XML vive en la capa cliente. Si el módulo cambiara de motor de
base de datos, aquí no se toca nada.

El sobre se construye con `xml.etree` en Python y con DOM + `Transformer` en
Java. **En ninguno se concatena XML**: los dos escapan los valores, que es la
misma disciplina de las consultas parametrizadas aplicada al otro formato.

## Ejecutar

Ambos leen el endpoint de la variable `SOAP_ENDPOINT`; por defecto
`http://127.0.0.1:5001/soap`.

```bash
# Python
cd clasificador_python
pip install -r requirements.txt
SOAP_ENDPOINT=http://LA-VM:5001/soap python3 main.py

# Java
cd clasificador_java
javac -d out $(find src -name '*.java')
SOAP_ENDPOINT=http://LA-VM:5001/soap java -cp out Main
```

Si el servicio corre en la VM y la aplicación en otra máquina, lo correcto es un
túnel SSH y no abrir el puerto 5001: `RegistrarClasificacion` no está
autenticada, y exponerla sería materializar el riesgo 2 de la auditoría del
contrato para conseguir comodidad.

```bash
gcloud compute ssh maquina01 -- -N -L 5001:127.0.0.1:5001
```

## Verificación

Ambos clientes se ejercitaron contra el servicio real: cargar conceptos,
sugerir con el clasificador local, registrar, provocar el conflicto por
duplicado y consultar el progreso. El de Java, además, demuestra
interoperabilidad por sí mismo — otro lenguaje, otro stack XML, mismo contrato.
