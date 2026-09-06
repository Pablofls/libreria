# Evidencias

Sobres SOAP reales capturados durante la verificación **local**, contra una base
desechable reconstruida con los scripts canónicos `db/01…06` más
`sql/soap_module.sql`.

| Archivo | Qué muestra |
|---|---|
| `01`, `02` | `ObtenerConceptosPendientes`: petición y respuesta |
| `03`, `04` | `RegistrarClasificacion`: petición y respuesta |
| `05` | SOAP Fault `CLASIFICACION_DUPLICADA` (conflicto 409) |
| `06` | SOAP Fault `NO_AUTORIZADO` (sin WS-Security) |
| `07`, `08` | `ObtenerEstadisticasPorModelo` con `UsernameToken` |

## Antes de publicarlas

1. **Regenera estas evidencias en la VM**, contra la base real. Las de aquí se
   produjeron con un secreto de prueba local y con datos de una base desechable.

   ```bash
   ENDPOINT=http://127.0.0.1:5001/soap WSSE_SECRETO=... python3 tests/pruebas_soap.py --markdown
   ```

2. El `<wsse:Password>` de `07` es un **digest**, no la contraseña: sólo es
   válido con su `Nonce` y su `Created`, y no permite recuperar el secreto. Aun
   así, si prefieres no publicarlo, sustitúyelo por `…` antes de subirlo: el
   enunciado pide explícitamente no publicar credenciales en las evidencias.

3. Revisa que ningún archivo publicado contenga `.env`, contraseñas, tokens,
   cadenas de conexión ni rutas internas del servidor.
