# -*- coding: utf-8 -*-
"""Evidencia en vivo de la proteccion JWT entre login y catalogo (book).

    LOGIN_URL=http://IP:5000 CATALOGO_URL=http://IP:5002 \
    ADMIN_EMAIL=... ADMIN_PASS=... LECTOR_EMAIL=... LECTOR_PASS=... \
    python3 tests/pruebas_jwt.py

No corre contra un doble ni contra el test_client de Flask: pega por HTTP de
verdad contra los dos microservicios ya levantados (en local o, lo mas
habitual, en la VM), igual que tests/pruebas.sh hace con el monolito. Por eso
usa solo la biblioteca estandar (urllib), sin agregar una dependencia nueva
solo para un script de evidencia -- el mismo criterio que ya siguen
clients/clasificador_python/soap_cliente.py y
apps/services/soap/tests/pruebas_soap.py.

Que prueba, en orden (ids JWT-01 .. JWT-13):

    JWT-01/02  /login emite un JWT tanto para el admin como para el lector.
    JWT-03/04  GET /books y GET /books/<isbn> siguen publicos, sin token.
    JWT-05     POST /books/insert sin token -> 401.
    JWT-06     POST /books/insert con JWT de lector (rol valido pero no admin) -> 403.
    JWT-07     POST /books/insert con JWT de admin -> 201.
    JWT-08     PATCH /books/update/<isbn> con JWT de admin -> 200.
    JWT-09     PUT /books/update/<isbn> sin token -> 401.
    JWT-10     DELETE /books/delete/<isbn> con JWT de lector -> 403.
    JWT-11     DELETE /books/delete/<isbn> con JWT de admin -> 200 (limpia el libro de prueba).
    JWT-12     Un JWT forjado con {"alg":"none"} y sin firma -> 401, nunca se acepta.
    JWT-13     Un Authorization: Bearer con basura, ni JSON, ni JWT -> 401, no revienta.

El libro que crean JWT-07..JWT-11 tiene un ISBN de prueba, claramente
identificable, y JWT-11 lo borra al final: el script no deja basura en el
catalogo si todo sale bien. Si algo falla a medio camino, el ISBN de prueba
queda en la salida para poder borrarlo a mano.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

LOGIN_URL = os.environ.get('LOGIN_URL', 'http://127.0.0.1:5000').rstrip('/')
CATALOGO_URL = os.environ.get('CATALOGO_URL', 'http://127.0.0.1:5002').rstrip('/')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '')
ADMIN_PASS = os.environ.get('ADMIN_PASS', '')
LECTOR_EMAIL = os.environ.get('LECTOR_EMAIL', '')
LECTOR_PASS = os.environ.get('LECTOR_PASS', '')

# Ids sembrados por db/02_seed_30_per_table.sql: 'Universitario' es la primera
# fila de categorias y 'Pasta dura' la primera de formatos, asi que en una
# base con el seed intacto son 1 y 1. Se pueden pisar por variable de entorno
# si la base de destino los tiene distintos.
CATEGORIA_ID = int(os.environ.get('CATEGORIA_ID', '1'))
FORMATO_ID = int(os.environ.get('FORMATO_ID', '1'))

# ISBN que no deberia colisionar con el catalogo real: 13 nueves no es un ISBN
# valido de verdad, pero pasa el CHECK del esquema (solo exige digitos/guiones
# y 11-18 caracteres), que es lo unico que valida el servicio.
ISBN_PRUEBA = os.environ.get('ISBN_PRUEBA', '9999999999999')

if not (ADMIN_EMAIL and ADMIN_PASS and LECTOR_EMAIL and LECTOR_PASS):
    print('Faltan ADMIN_EMAIL / ADMIN_PASS / LECTOR_EMAIL / LECTOR_PASS.', file=sys.stderr)
    print('Ver la cabecera de este archivo.', file=sys.stderr)
    sys.exit(2)

hechas = 0
fallos = []


def revisar(id_, descripcion, condicion, extra=''):
    global hechas
    hechas += 1
    if condicion:
        print('  {:<8} ok    {}'.format(id_, descripcion))
    else:
        print('  {:<8} FALLA {} {}'.format(id_, descripcion, extra))
        fallos.append('{} {}'.format(id_, descripcion))


def peticion(metodo, url, datos=None, token=None, cabecera_auth=None):
    """POST/PUT/PATCH/DELETE/GET contra el servicio. Devuelve (status, dict).

    Siempre pide JSON (?format=json) para no tener que parsear XML aqui. Nunca
    lanza por un 4xx/5xx: HTTPError trae el cuerpo igual que una respuesta
    normal, que es lo que este script necesita leer.
    """
    if '?' in url:
        url = url + '&format=json'
    else:
        url = url + '?format=json'

    cuerpo = None
    cabeceras = {'Accept': 'application/json'}
    if datos is not None:
        cuerpo = json.dumps(datos).encode('utf-8')
        cabeceras['Content-Type'] = 'application/json'
    if token:
        cabeceras['Authorization'] = 'Bearer {}'.format(token)
    elif cabecera_auth is not None:
        cabeceras['Authorization'] = cabecera_auth

    req = urllib.request.Request(url, data=cuerpo, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            crudo = resp.read()
            return resp.status, (json.loads(crudo) if crudo else {})
    except urllib.error.HTTPError as error:
        crudo = error.read()
        try:
            return error.code, json.loads(crudo)
        except ValueError:
            return error.code, {'mensaje_crudo': crudo.decode('utf-8', 'replace')}
    except urllib.error.URLError as error:
        return 0, {'error_conexion': str(error)}


def iniciar_sesion(email, password):
    estado, cuerpo = peticion('POST', LOGIN_URL + '/login',
                              {'email': email, 'password': password})
    return estado, cuerpo


def parece_jwt(token):
    """Tres tramos separados por punto, cada uno Base64URL. No verifica firma
    -- este script es un cliente, no tiene (ni deberia tener) JWT_SECRET."""
    if not isinstance(token, str):
        return False
    partes = token.split('.')
    if len(partes) != 3:
        return False
    try:
        for parte in partes[:2]:
            base64.urlsafe_b64decode(parte + '=' * (-len(parte) % 4))
        return True
    except (ValueError, TypeError):
        return False


def jwt_forjado_alg_none():
    """Arma a mano {"alg":"none"} sin firma: el ataque clasico que JWT-12
    comprueba que el catalogo rechaza. No usa PyJWT a proposito -- justamente
    porque PyJWT nunca dejaria fabricar un token asi sin pedirlo con rodeos, lo
    que ya es una senal de que el ataque no es trivial contra una libreria
    seria. Aqui se construye a pulso para probar el servidor, no la libreria.
    """
    def b64url(d):
        cruda = json.dumps(d).encode('utf-8')
        return base64.urlsafe_b64encode(cruda).rstrip(b'=').decode('ascii')

    encabezado = b64url({'alg': 'none', 'typ': 'JWT'})
    carga = b64url({'sub': '1', 'email': 'atacante@evil.com', 'rol': 'admin',
                    'iss': 'login-libreria'})
    return '{}.{}.'.format(encabezado, carga)


print('== Libreria * evidencia de proteccion JWT (login -> book) ==')
print('   login:    {}'.format(LOGIN_URL))
print('   catalogo: {}'.format(CATALOGO_URL))
print()

# --- 1. login emite el JWT para los dos roles -----------------------------------
print('1. POST /login emite un JWT')
estado, cuerpo = iniciar_sesion(ADMIN_EMAIL, ADMIN_PASS)
revisar('JWT-01', 'login del admin, 200', estado == 200, estado)
token_admin = cuerpo.get('token')
revisar('JWT-01b', 'la respuesta trae un JWT con forma de JWT', parece_jwt(token_admin))

estado, cuerpo = iniciar_sesion(LECTOR_EMAIL, LECTOR_PASS)
revisar('JWT-02', 'login del lector, 200', estado == 200, estado)
token_lector = cuerpo.get('token')
revisar('JWT-02b', 'tambien trae un JWT con forma de JWT', parece_jwt(token_lector))

if not (token_admin and token_lector):
    print('\nSin los dos tokens no se puede seguir: revisa LOGIN_URL y las credenciales.')
    print('{} comprobaciones, {} fallos'.format(hechas, len(fallos)))
    sys.exit(1)

# --- 2. las lecturas del catalogo siguen publicas --------------------------------
print('\n2. Las lecturas siguen publicas, sin token')
estado, _ = peticion('GET', CATALOGO_URL + '/books')
revisar('JWT-03', 'GET /books sin token nunca es 401', estado != 401, estado)

estado, _ = peticion('GET', CATALOGO_URL + '/books/0000000000000')
revisar('JWT-04', 'GET /books/<isbn> sin token nunca es 401', estado != 401, estado)

# --- 3. las escrituras exigen JWT de admin ---------------------------------------
print('\n3. Las escrituras exigen un JWT de rol admin')
libro_prueba = {'isbn': ISBN_PRUEBA, 'titulo': 'Libro de evidencia JWT (borrar)',
                'categoria_id': CATEGORIA_ID, 'formato_id': FORMATO_ID,
                'precio': '1.00', 'stock': 0}

estado, cuerpo = peticion('POST', CATALOGO_URL + '/books/insert', libro_prueba)
revisar('JWT-05', 'POST /books/insert sin token -> 401', estado == 401, estado)

estado, cuerpo = peticion('POST', CATALOGO_URL + '/books/insert', libro_prueba,
                          token=token_lector)
revisar('JWT-06', 'POST /books/insert con JWT de lector -> 403 (token valido, rol insuficiente)',
        estado == 403, estado)

estado, cuerpo = peticion('POST', CATALOGO_URL + '/books/insert', libro_prueba,
                          token=token_admin)
revisar('JWT-07', 'POST /books/insert con JWT de admin -> 201', estado == 201, estado)
libro_creado = estado == 201

if libro_creado:
    estado, cuerpo = peticion(
        'PATCH', CATALOGO_URL + '/books/update/' + ISBN_PRUEBA,
        {'stock': 5}, token=token_admin)
    revisar('JWT-08', 'PATCH /books/update/<isbn> con JWT de admin -> 200',
            estado == 200, estado)

    estado, cuerpo = peticion(
        'PUT', CATALOGO_URL + '/books/update/' + ISBN_PRUEBA, {'stock': 9})
    revisar('JWT-09', 'PUT /books/update/<isbn> sin token -> 401', estado == 401, estado)

    estado, cuerpo = peticion(
        'DELETE', CATALOGO_URL + '/books/delete/' + ISBN_PRUEBA, token=token_lector)
    revisar('JWT-10', 'DELETE /books/delete/<isbn> con JWT de lector -> 403',
            estado == 403, estado)

    estado, cuerpo = peticion(
        'DELETE', CATALOGO_URL + '/books/delete/' + ISBN_PRUEBA, token=token_admin)
    revisar('JWT-11', 'DELETE /books/delete/<isbn> con JWT de admin -> 200 (limpieza)',
            estado == 200, estado)
    if estado != 200:
        print('  !! El libro de prueba {} pudo haber quedado en el catalogo: '
              'borralo a mano si hace falta.'.format(ISBN_PRUEBA))
else:
    print('  (JWT-08..JWT-11 se omiten: no se pudo crear el libro de prueba)')

# --- 4. el ataque clasico: alg:none ------------------------------------------------
print('\n4. Un JWT sin firma nunca se acepta')
estado, cuerpo = peticion('POST', CATALOGO_URL + '/books/insert', libro_prueba,
                          token=jwt_forjado_alg_none())
revisar('JWT-12', 'JWT forjado con {"alg":"none"} -> 401, no 201', estado == 401, estado)

estado, cuerpo = peticion('POST', CATALOGO_URL + '/books/insert', libro_prueba,
                          cabecera_auth='Bearer esto-no-es-un-jwt')
revisar('JWT-13', 'Authorization con basura -> 401, sin reventar', estado == 401, estado)


print('\n{} comprobaciones, {} fallos'.format(hechas, len(fallos)))
if fallos:
    for f in fallos:
        print('  - ' + f)
sys.exit(1 if fallos else 0)
