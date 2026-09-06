# Uso de Inteligencia Artificial

El enunciado permite y fomenta el uso de IA, y exige documentarlo: qué se pidió,
qué se aceptó, qué se modificó y qué se rechazó. Esta es la bitácora del módulo.

> **Por completar por el estudiante:** las secciones marcadas con ✏️ deben
> reflejar tu propia revisión. La responsabilidad de *comprender → revisar →
> probar → validar → corregir → justificar* no se delega.

## 1. Herramienta y modo de uso

| | |
|---|---|
| Herramienta | Claude (Claude Code), modelo Opus |
| Modo | Sesión interactiva sobre el repositorio local |
| Alcance | Diseño del contrato, implementación, SQL, pruebas y documentación |
| Base de datos | **Nunca** se conectó a la VM. Toda verificación se hizo en una base desechable local reconstruida con los scripts canónicos `db/01…06` |

## 2. Prompts relevantes

1. *"Crea un archivo XML con la lista de libros según el esquema…"* — generó
   `services/soap/library.xml` (ejercicio anterior).
2. *"Genera el CSS para mostrar el catálogo"* — `services/soap/library.css`.
3. *"Escribe un microservicio en Flask (sin Blueprints) con CRUD y Swagger"* —
   `services/soap/app.py` (ejercicio anterior).
4. *"Te paso el PDF del Ejercicio 03; hazlo de la forma en que viene ahí"* —
   este módulo completo.

El prompt 4 es el relevante para esta entrega. El modelo leyó el PDF, señaló que
el ejercicio pedía algo distinto de lo construido antes (SOAP con WSDL para
clasificar conceptos, no un CRUD REST de libros) y propuso el módulo nuevo sin
borrar el trabajo previo.

## 3. Qué se aceptó

- La estructura de carpetas del enunciado y la separación en capas.
- La clave foránea compuesta `(libro_id, concepto_id)` hacia `libros_conceptos`,
  que hace que la base garantice que el concepto esté definido en ese libro.
- Resolver el registro con un procedimiento almacenado en una sola transacción,
  en lugar de tres `INSERT` desde Python.
- WS-Security con PasswordDigest en lugar de PasswordText.
- Devolver códigos HTTP semánticos junto al SOAP Fault.

## 4. Qué se modificó o corrigió durante el trabajo

Errores que la propia IA introdujo y que se detectaron al **probar**, no al leer:

| Error | Cómo se detectó |
|---|---|
| Separadores `<!-- ---- -->` en el WSDL: `--` es ilegal dentro de un comentario XML | `xmllint` |
| El WSDL servido perdía `xmlns:tns` porque se reserializaba con `ElementTree` | Comparar el archivo con lo que devolvía el endpoint |
| El `binding` declaraba `<soap:header part="parameters">`, lo que vaciaba el `Body` | El cliente `zeep` de la Tarea 4 |
| `psycopg2-binary==2.9.9` y `zeep==4.2.1` no funcionan en Python 3.13 | `pip install` e `import` |
| Una expectativa mal calculada en la suite de pruebas (3 libros en lugar de 4) | La propia corrida: el servicio tenía razón, la prueba no |

La lección práctica: **el código generado se veía correcto en los cinco casos.**
Ninguno se detectó leyendo; todos aparecieron al ejecutar, validar y consumir el
contrato desde otro stack.

## 5. Qué se rechazó

- Usar Spyne o Zeep del lado del servidor: lo prohíbe el enunciado y anularía el
  objetivo didáctico de construir el sobre a mano.
- Reutilizar la tabla `usuarios` del monolito para los clasificadores.
- Guardar el secreto de WS-Security en la base de datos o en el repositorio.
- Escribir credenciales en el `.sql` o en el `.env.example`.

## 6. ✏️ Verificación propia del estudiante

*(Completar: qué revisaste línea por línea, qué probaste tú en la VM, qué
cambiaste después de entenderlo, y qué decisión defenderías distinto.)*

- [ ] Leí y entiendo `sql/soap_module.sql`, en particular la FK compuesta y los `GRANT`.
- [ ] Ejecuté las 18 pruebas contra la base real de la VM.
- [ ] Verifiqué en `psql` que las filas llegaron a `clasificaciones_cloud`.
- [ ] Probé el cliente de escritorio y provoqué un Fault a propósito.
- [ ] Puedo explicar por qué PasswordDigest y cuál es su contrapartida.
