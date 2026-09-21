# Resultados de las pruebas del modulo SOAP

Endpoint: `http://127.0.0.1:5001/soap`

| ID | Prueba | Resultado esperado | Resultado obtenido | Estado |
|---|---|---|---|---|
| P01 | Obtener conceptos pendientes | Lista valida | 5 conceptos de 44 pendientes, con libro y categoria | PASA |
| P021 | Registrar clasificacion IaaS | Registro exitoso | id=1 peticiones=1 | PASA |
| P022 | Registrar clasificacion PaaS | Registro exitoso | id=2 peticiones=2 | PASA |
| P023 | Registrar clasificacion SaaS | Registro exitoso | id=3 peticiones=3 | PASA |
| P024 | Registrar clasificacion FaaS | Registro exitoso | id=4 peticiones=4 | PASA |
| P03 | Consultar progreso del clasificador | 4 clasificados y desglose por modelo | 4 clasificados, 26 pendientes, 4 modelos | PASA |
| P04 | Estadisticas con WS-Security valido | Conteo de los 4 modelos | FaaS=1, IaaS=1, PaaS=1, SaaS=1 | PASA |
| N01 | Repetir la misma clasificacion | SOAP Fault CLASIFICACION_DUPLICADA / HTTP 409 | Fault CLASIFICACION_DUPLICADA / HTTP 409 | PASA |
| N02 | Concepto inexistente | SOAP Fault CONCEPTO_INEXISTENTE / HTTP 404 | Fault CONCEPTO_INEXISTENTE / HTTP 404 | PASA |
| N03 | Modelo Cloud invalido | SOAP Fault MODELO_INVALIDO / HTTP 400 | Fault MODELO_INVALIDO / HTTP 400 | PASA |
| N04 | XML mal formado | SOAP Fault XML_INVALIDO / HTTP 400 | Fault XML_INVALIDO / HTTP 400 | PASA |
| N05 | Estadisticas sin WS-Security | SOAP Fault NO_AUTORIZADO / HTTP 401 | Fault NO_AUTORIZADO / HTTP 401 | PASA |
| N06 | Estadisticas con contrasena incorrecta | SOAP Fault NO_AUTORIZADO / HTTP 401 | Fault NO_AUTORIZADO / HTTP 401 | PASA |
| N07 | Operacion fuera del contrato | SOAP Fault OPERACION_DESCONOCIDA / HTTP 400 | Fault OPERACION_DESCONOCIDA / HTTP 400 | PASA |
| N08 | Correo con formato invalido | SOAP Fault DATO_INVALIDO / HTTP 400 | Fault DATO_INVALIDO / HTTP 400 | PASA |
| N09 | ISBN que no existe | SOAP Fault LIBRO_INEXISTENTE / HTTP 404 | Fault LIBRO_INEXISTENTE / HTTP 404 | PASA |
| N10 | Progreso de un correo no registrado | SOAP Fault CLASIFICADOR_INEXISTENTE / HTTP 404 | Fault CLASIFICADOR_INEXISTENTE / HTTP 404 | PASA |
| N11 | Reenvio del mismo token (replay) | SOAP Fault NO_AUTORIZADO / HTTP 401 | Fault NO_AUTORIZADO / HTTP 401 | PASA |
