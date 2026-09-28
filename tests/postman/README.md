# Colección Postman — protección JWT (login → book)

`libreria-jwt.postman_collection.json` trae los 13 casos (`JWT-01`..`JWT-13`)
que demuestran que `/books/insert`, `/books/update` y `/books/delete` del
microservicio de catálogo exigen un JWT válido **con rol `admin`** emitido por
`/login`, y que las lecturas (`GET /books`, `GET /books/{isbn}`) siguen
públicas. Es el mismo contrato que verifica
[`tests/pruebas_jwt.py`](../pruebas_jwt.py), request por request — usa esa
colección para las capturas de Postman y el script de Python para la
evidencia de texto.

## Cómo correrla

1. Importar `libreria-jwt.postman_collection.json` en Postman (**File → Import**).
2. Completar las variables de la colección (ícono `⋯` de la colección →
   **Edit** → pestaña **Variables**): `login_url`, `catalogo_url`,
   `admin_email`, `admin_pass`, `lector_email`, `lector_pass`. Contra la VM,
   `login_url` es `http://IP:5000` y `catalogo_url` es `http://IP:5002`.
3. Correr las peticiones **en orden**. La 1 y la 2 (login del admin y del
   lector) guardan el token en variables de colección (`token_admin`,
   `token_lector`) que las peticiones 6 a 11 reutilizan — si se saltan o se
   corren fuera de orden, esas peticiones fallan por falta de token, no por un
   error real de la API.
4. Cada petición trae en su pestaña **Tests** la comprobación del código de
   estado esperado; el panel de resultados de Postman (✓/✗) es en sí mismo
   una buena captura de evidencia.

La petición 12 no depende de ningún login: el `Authorization` ya lleva
escrito a mano un JWT con encabezado `{"alg":"none"}` y sin firma — el ataque
clásico contra una verificación que confía en el `alg` que declara el propio
token. Se rechaza siempre con 401, nunca con 201.

## Antes de publicar las capturas

- **Corre la colección contra la VM**, no solo en local: las capturas deben
  mostrar el sistema real, con `login_url`/`catalogo_url` apuntando a la IP
  pública.
- **Recorta o tapa el valor de los tokens y las contraseñas** en las capturas
  antes de subirlas — el repositorio es público. El código de estado y el
  panel de Tests ya prueban lo que hace falta probar; el valor del JWT no
  aporta nada y si se publica, alguien podría reutilizarlo hasta que expire.
- Guarda las capturas en [`evidencias/jwt/`](../../evidencias/jwt/), con un
  nombre que diga qué caso es (por ejemplo `06-insert-lector-403.png`).
