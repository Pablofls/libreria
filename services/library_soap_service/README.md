# Módulo SOAP — Clasificador Cloud

Módulo SOAP independiente que clasifica los conceptos del catálogo de la
Librería Online en modelos de servicio en la nube (IaaS, PaaS, SaaS, FaaS).
Ejercicio 03 de Integración de Aplicaciones Computacionales.

El monolito Node.js **no se modifica**. Este módulo corre en otro proceso, en
otro puerto, con otro rol de PostgreSQL, y sólo comparte con él la base de datos.

```
Aplicación de escritorio → Cliente SOAP → HTTP POST/XML → Módulo SOAP Flask → psycopg2 → PostgreSQL
                                                                                            ↑
                                                          Monolito Node.js ─────────────────┘
```

## Estructura

| Ruta | Responsabilidad |
|---|---|
| `app.py` | Flask sin Blueprints. Sólo traduce entre HTTP y el módulo SOAP |
| `config/ajustes.py` | Único punto que lee variables de entorno |
| `db/acceso.py` | Todo el SQL. Consultas parametrizadas, vistas y un procedimiento |
| `soap/envelope.py` | Lectura y construcción del Envelope con `xml.etree` |
| `soap/service.py` | Despacho de operaciones, validación y armado de respuestas |
| `soap/faults.py` | Vocabulario de errores y serialización a SOAP Fault |
| `soap/security.py` | WS-Security UsernameToken con PasswordDigest |
| `wsdl/library-classifier.wsdl` | El contrato: tipos XSD, portType, binding y endpoint |
| `sql/soap_module.sql` | Tablas propias, vistas, procedimiento y rol de mínimo privilegio |
| `cliente/cliente_escritorio.py` | Aplicación de escritorio (Tkinter) como cliente SOAP |
| `tests/pruebas_soap.py` | Plan de pruebas ejecutable: sobres armados a mano |
| `tests/cliente_zeep.py` | Tarea 4: cliente generado desde el WSDL, otro stack |
| `docs/` | Documentación técnica, auditoría del contrato, métricas y evidencias |

## Operaciones

| Operación | Qué hace | Protegida |
|---|---|---|
| `ObtenerConceptosPendientes` | Conceptos aún sin clasificar, con libro y categoría | No |
| `RegistrarClasificacion` | Registra concepto + modelo Cloud para un clasificador | No |
| `ObtenerProgresoUsuario` | Totales clasificados y pendientes, por modelo | No |
| `ObtenerEstadisticasPorModelo` | Conteo global por modelo | **Sí**, WS-Security |

## Puesta en marcha

### 1. Base de datos (una sola vez, en la VM)

```bash
psql -U libreria_owner -d libreria_db -f services/library_soap_service/sql/soap_module.sql
```

Crea las tres tablas propias, cuatro vistas, el procedimiento y el rol
`libreria_soap`. Después, asigna su contraseña **sin dejarla en ningún archivo**:

```bash
psql -U postgres -d libreria_db -c "\password libreria_soap"
```

### 2. Servicio

```bash
cd services/library_soap_service
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # y completar DB_PASSWORD y WSSE_SECRETO
python app.py
```

El contrato queda en `http://<host>:5001/soap?wsdl` y el endpoint en
`http://<host>:5001/soap`. `GET /health` responde el estado de la conexión.

### 3. Pruebas

```bash
ENDPOINT=http://127.0.0.1:5001/soap WSSE_SECRETO=... python3 tests/pruebas_soap.py --markdown
```

18 pruebas: 7 positivas y 11 negativas. Escribe `tests/resultados.md`.

### 4. Cliente de escritorio

```bash
ENDPOINT=http://<host>:5001/soap python3 cliente/cliente_escritorio.py
```

Tkinter viene con Python: no instala nada. La GUI **no conoce PostgreSQL**; su
única puerta al sistema es el endpoint SOAP.

### 5. Interoperabilidad (Tarea 4)

```bash
pip install -r requirements-interop.txt
WSSE_SECRETO=... python3 tests/cliente_zeep.py http://<host>:5001/soap?wsdl
```

## Seguridad

- El rol `libreria_soap` sólo puede **leer** las columnas del monolito que el
  contrato expone y **escribir** en sus tres tablas propias. No tiene `DELETE`
  en ninguna tabla, y sobre `usuarios` no tiene ni `SELECT`.
- `ObtenerEstadisticasPorModelo` exige WS-Security UsernameToken con
  PasswordDigest, con ventana de frescura y rechazo de reenvíos.
- Ningún Fault que sale a la red lleva SQL, rutas, trazas ni credenciales.
- Ninguna credencial vive en el repositorio. Todas están en el `.env` de la VM,
  que no se versiona.

## Documentación

- [Documentación técnica](docs/documentacion-tecnica.md) — decisiones de ingeniería
- [Auditoría del contrato](docs/auditoria-contrato.md) — qué se expone y por qué
- [Plan de pruebas](docs/plan-de-pruebas.md)
- [Métricas](docs/metricas.md) — para comparar con REST después
- [Evidencias](docs/evidencias/) — sobres de petición, respuesta y Fault reales
