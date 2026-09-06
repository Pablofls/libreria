# Plan de pruebas — Módulo SOAP

Ejecutable: `python3 tests/pruebas_soap.py --markdown`.

Cada corrida usa un correo de clasificador distinto (`prueba.<timestamp>@…`),
así que las pruebas son repetibles sin limpiar la base entre ejecuciones.

## Resultados de la corrida local

Base desechable reconstruida con `db/01…06` más `sql/soap_module.sql`,
conectando con el rol `libreria_soap` (no con un superusuario), lo que además
verifica que los `GRANT` de mínimo privilegio alcanzan para todas las
operaciones. **Falta ejecutarlo en la VM contra la base real.**

| ID | Prueba | Resultado esperado | Resultado obtenido (local) | Estado |
|---|---|---|---|---|
| P01 | Obtener conceptos pendientes | Lista válida con libro y categoría | 5 conceptos de 44 pendientes | PASA |
| P02.1 | Registrar clasificación IaaS | Registro exitoso | id=1, peticiones=1 | PASA |
| P02.2 | Registrar clasificación PaaS | Registro exitoso | id=2, peticiones=2 | PASA |
| P02.3 | Registrar clasificación SaaS | Registro exitoso | id=3, peticiones=3 | PASA |
| P02.4 | Registrar clasificación FaaS | Registro exitoso | id=4, peticiones=4 | PASA |
| P03 | Consultar progreso del clasificador | 4 clasificados y desglose | 4 clasificados, 26 pendientes, 4 modelos | PASA |
| P04 | Estadísticas con WS-Security válido | Conteo de los 4 modelos | IaaS=1, PaaS=1, SaaS=1, FaaS=1 | PASA |
| N01 | Repetir la misma clasificación | SOAP Fault 409 | `CLASIFICACION_DUPLICADA` / HTTP 409 | PASA |
| N02 | Concepto inexistente | SOAP Fault | `CONCEPTO_INEXISTENTE` / HTTP 404 | PASA |
| N03 | Modelo Cloud inválido | SOAP Fault de validación | `MODELO_INVALIDO` / HTTP 400 | PASA |
| N04 | XML mal formado | SOAP Fault de cliente, sin ejecutar SQL | `XML_INVALIDO` / HTTP 400 | PASA |
| N05 | Estadísticas sin WS-Security | SOAP Fault | `NO_AUTORIZADO` / HTTP 401 | PASA |
| N06 | Estadísticas con contraseña incorrecta | SOAP Fault | `NO_AUTORIZADO` / HTTP 401 | PASA |
| N07 | Operación fuera del contrato | SOAP Fault | `OPERACION_DESCONOCIDA` / HTTP 400 | PASA |
| N08 | Correo con formato inválido | SOAP Fault | `DATO_INVALIDO` / HTTP 400 | PASA |
| N09 | ISBN que no existe | SOAP Fault | `LIBRO_INEXISTENTE` / HTTP 404 | PASA |
| N10 | Progreso de un correo no registrado | SOAP Fault | `CLASIFICADOR_INEXISTENTE` / HTTP 404 | PASA |
| N11 | Reenvío del mismo token (replay) | SOAP Fault | `NO_AUTORIZADO` / HTTP 401 | PASA |

**18 pruebas, 0 fallidas.**

## Pruebas de interoperabilidad (Tarea 4)

`tests/cliente_zeep.py`, con un cliente generado desde el WSDL por `zeep`, que
no conoce el código del servidor:

| Paso | Resultado |
|---|---|
| Leer el WSDL y descubrir operaciones | 4 operaciones descubiertas sin ver el servidor |
| `ObtenerConceptosPendientes` | Lista recibida y tipada |
| `RegistrarClasificacion` | Registro exitoso |
| Repetir el registro | `Fault` recibido y entendido por zeep |
| Enviar `modelo="XaaS"` | **El stub lo rechazó sin salir a la red**: el XSD valida en el cliente |
| `ObtenerEstadisticasPorModelo` con UsernameToken de zeep | Autenticación aceptada por `soap/security.py` |

Esta prueba encontró un defecto real del contrato: el `binding` declaraba
`<soap:header part="parameters">` en la operación protegida, lo que movía el
cuerpo del mensaje al encabezado y dejaba el `Body` vacío. El cliente manual no
lo detectaba porque construía el sobre a mano. Corregido.

## Verificación en PostgreSQL (Parte 9, punto 16)

Después de correr las pruebas en la VM, comprobar directamente en la base:

```sql
-- Las clasificaciones llegaron, con su modelo y su clasificador
SELECT cc.id, c.correo, co.termino, l.isbn, cc.modelo, cc.clasificado_en
FROM clasificaciones_cloud cc
JOIN clasificadores c ON c.id = cc.clasificador_id
JOIN conceptos co     ON co.id = cc.concepto_id
JOIN libros l         ON l.id = cc.libro_id
ORDER BY cc.id DESC LIMIT 20;

-- clientes_servidos refleja el tipo de cliente y las peticiones atendidas
SELECT tipo_cliente, identificador, peticiones_atendidas,
       primera_peticion, ultima_peticion
FROM clientes_servidos ORDER BY peticiones_atendidas DESC;

-- Conteo por modelo
SELECT * FROM v_estadisticas_modelo ORDER BY modelo;

-- La restricción de no repetir sigue en pie
SELECT clasificador_id, concepto_id, count(*)
FROM clasificaciones_cloud GROUP BY 1, 2 HAVING count(*) > 1;   -- debe ir vacío
```
