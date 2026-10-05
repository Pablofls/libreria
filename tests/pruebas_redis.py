# -*- coding: utf-8 -*-
"""Evidencia en vivo de la capa Redis: sesiones, refresh tokens, revocacion de
JWT, cache del catalogo y caida de Redis. Contra la VM, por HTTPS.

    CA_CERT=~/libreria-api.crt HOST=34.51.108.167 \\
    ADMIN_EMAIL=... ADMIN_PASS=... LECTOR_EMAIL=... LECTOR_PASS=... \\
    python3 tests/pruebas_redis.py

Opcional: REDIS_CAIDO=1 si Redis esta parado a proposito (prueba de caida): se
ejecutan SOLO las comprobaciones de falla segura. Sin REDIS_CAIDO, las normales.

Solo biblioteca estandar. Las credenciales NUNCA van en el codigo.

Que prueba:
  R-01..R-04  login devuelve JWT con jti + refresh token; el refresh se rota y
              el ya usado se rechaza.
  R-05..R-08  logout revoca el JWT: el mismo token da 401 en users, pedidos y
              el catalogo (escritura), y el refresh de esa sesion ya no sirve.
  R-09..R-12  GET /books: MISS y luego HIT (cabecera X-Cache); GET /books/<isbn>;
              las metricas cuentan los aciertos.
  R-13..R-14  una escritura que cambia el catalogo invalida la cache (autores).
  Caida       con Redis parado: login 503, rutas protegidas 503, GET /books
              sigue 200, los semaforos informan redis: caido.
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

HOST = os.environ.get('HOST', '127.0.0.1')
CA_CERT = os.environ.get('CA_CERT')
CONTEXTO = ssl.create_default_context(cafile=CA_CERT) if CA_CERT else None
CAIDO = os.environ.get('REDIS_CAIDO') == '1'
FALTAN = [v for v in ('ADMIN_EMAIL', 'ADMIN_PASS', 'LECTOR_EMAIL', 'LECTOR_PASS')
          if not os.environ.get(v)]
if FALTAN:
    sys.exit('Faltan variables de entorno: ' + ', '.join(FALTAN))

fallos, hechas = [], 0


def revisar(condicion, descripcion, extra=''):
    global hechas
    hechas += 1
    print('  {} {} {}'.format('ok  ' if condicion else 'FALLA', descripcion,
                              '' if condicion else extra))
    if not condicion:
        fallos.append(descripcion)


def llamar(metodo, ruta, cuerpo=None, token=None):
    """(estado, json|None, cabeceras). Nunca imprime tokens."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cabeceras = {'Content-Type': 'application/json'}
    if token:
        cabeceras['Authorization'] = 'Bearer ' + token
    base = 'https://{}'.format(HOST) if CONTEXTO else 'http://{}'.format(HOST)
    peticion = urllib.request.Request(base + ruta, data=datos, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(peticion, timeout=15, context=CONTEXTO) as r:
            crudo = r.read()
            return r.status, (json.loads(crudo) if crudo else None), r.headers
    except urllib.error.HTTPError as e:
        crudo = e.read()
        try:
            return e.code, json.loads(crudo), e.headers
        except ValueError:
            return e.code, None, e.headers


def entrar(email_var, pass_var):
    estado, cuerpo, _ = llamar('POST', '/login?format=json', {
        'email': os.environ[email_var], 'password': os.environ[pass_var]})
    return estado, cuerpo


if CAIDO:
    print('PRUEBA DE CAIDA: Redis debe estar parado (sudo systemctl stop redis)')
    estado, _ = entrar('LECTOR_EMAIL', 'LECTOR_PASS')
    revisar(estado == 503, 'login con Redis caido, 503 (no se abre sesion sin Redis)', estado)
    estado, _, _ = llamar('GET', '/orders')
    revisar(estado == 401, 'ruta protegida sin token sigue siendo 401', estado)
    estado, cuerpo, cab = llamar('GET', '/books?format=json')
    revisar(estado == 200 and cab.get('X-Cache') == 'MISS',
            'GET /books sigue sirviendo desde PostgreSQL (la cache falla abierto)', estado)
    for servicio in ('login', 'catalogo', 'users', 'authors', 'pedidos', 'pagos'):
        estado, cuerpo, _ = llamar('GET', '/health/{}?format=json'.format(servicio))
        texto = json.dumps(cuerpo)
        revisar(estado == 200 and ('caido' in texto or 'degradado' in texto),
                'semaforo {}: responde y marca Redis caido (amarillo)'.format(servicio), estado)
    print('\n{} comprobaciones, {} fallos'.format(hechas, len(fallos)))
    sys.exit(1 if fallos else 0)

print('1. Login, refresh token y rotacion')
estado, cuerpo = entrar('LECTOR_EMAIL', 'LECTOR_PASS')
revisar(estado == 200 and cuerpo.get('token') and cuerpo.get('refresh_token'),
        'login devuelve JWT y refresh_token', estado)
TOKEN, REFRESH = cuerpo['token'], cuerpo['refresh_token']
estado, nuevo, _ = llamar('POST', '/token/refresh?format=json', {'refresh_token': REFRESH})
revisar(estado == 200 and nuevo['token'] != TOKEN and nuevo['refresh_token'] != REFRESH,
        'el refresh entrega JWT y refresh nuevos (rotacion)', estado)
estado, _, _ = llamar('POST', '/token/refresh?format=json', {'refresh_token': REFRESH})
revisar(estado == 401, 'el refresh ya usado se rechaza', estado)
estado, _, _ = llamar('GET', '/orders', token=TOKEN)
revisar(estado == 401, 'el JWT anterior de la sesion quedo revocado al renovar', estado)
TOKEN, REFRESH = nuevo['token'], nuevo['refresh_token']
estado, _, _ = llamar('GET', '/orders', token=TOKEN)
revisar(estado == 200, 'y el JWT nuevo si funciona', estado)

print('2. Logout revoca el JWT en todos los servicios')
estado, cuerpo = entrar('ADMIN_EMAIL', 'ADMIN_PASS')
ADMIN, ADMIN_REFRESH = cuerpo['token'], cuerpo['refresh_token']
estado, _, _ = llamar('GET', '/users', token=ADMIN)
revisar(estado == 200, 'antes del logout, el admin entra a /users', estado)
estado, _, _ = llamar('POST', '/logout?format=json', {'refresh_token': ADMIN_REFRESH}, token=ADMIN)
revisar(estado == 200, 'POST /logout, 200', estado)
estado, _, _ = llamar('GET', '/users', token=ADMIN)
revisar(estado == 401, 'el mismo JWT ya no entra a users, 401', estado)
estado, _, _ = llamar('GET', '/orders', token=ADMIN)
revisar(estado == 401, 'ni a pedidos, 401', estado)
estado, _, _ = llamar('DELETE', '/books/delete/0000000000000', token=ADMIN)
revisar(estado == 401, 'ni a las escrituras del catalogo, 401', estado)
estado, _, _ = llamar('POST', '/token/refresh?format=json', {'refresh_token': ADMIN_REFRESH})
revisar(estado == 401, 'y el refresh_token de esa sesion tampoco sirve', estado)

print('3. Cache de GET /books')
estado, cuerpo = entrar('ADMIN_EMAIL', 'ADMIN_PASS')
ADMIN = cuerpo['token']
estado, libros, cab = llamar('GET', '/books?limite=3&format=json')
revisar(estado == 200 and cab.get('X-Cache') in ('MISS', 'HIT'), 'GET /books responde con X-Cache', cab.get('X-Cache'))
estado, libros2, cab = llamar('GET', '/books?limite=3&format=json')
revisar(cab.get('X-Cache') == 'HIT' and libros == libros2, 'la segunda lectura es HIT y devuelve lo mismo', cab.get('X-Cache'))
isbn = libros['books'][0]['isbn'] if libros and libros.get('books') else None
if isbn:
    llamar('GET', '/books/{}?format=json'.format(isbn))
    estado, _, cab = llamar('GET', '/books/{}?format=json'.format(isbn))
    revisar(estado == 200 and cab.get('X-Cache') == 'HIT', 'GET /books/<isbn> tambien se cachea', cab.get('X-Cache'))
estado, metricas, _ = llamar('GET', '/metrics', token=ADMIN)
revisar(estado == 200 and metricas['contadores'].get('cache_aciertos', 0) >= 1,
        '/metrics del catalogo cuenta los aciertos', metricas)
estado, _, _ = llamar('GET', '/metrics')
revisar(estado == 401, '/metrics sin token, 401', estado)

print('4. Una escritura de otro servicio invalida la cache del catalogo')
estado, _, cab = llamar('GET', '/books?limite=3&format=json')
revisar(cab.get('X-Cache') == 'HIT', 'antes de escribir, la lectura es HIT', cab.get('X-Cache'))
estado, autor, _ = llamar('POST', '/authors', {'nombre': 'Autor prueba Redis'}, token=ADMIN)
if estado == 201:
    estado, _, cab = llamar('GET', '/books?limite=3&format=json')
    revisar(cab.get('X-Cache') == 'MISS', 'tras crear un autor, books:* se invalido (MISS)', cab.get('X-Cache'))
    estado, _, _ = llamar('DELETE', '/authors/{}'.format(autor['id']), token=ADMIN)
    revisar(estado == 204, 'limpieza: se borra el autor de prueba', estado)
else:
    revisar(False, 'no se pudo crear el autor de prueba', estado)

print('5. Semaforos (/health/<servicio>) informan Redis')
for servicio in ('login', 'catalogo', 'users', 'authors', 'pedidos', 'pagos'):
    estado, cuerpo, _ = llamar('GET', '/health/{}?format=json'.format(servicio))
    revisar(estado == 200 and 'redis' in json.dumps(cuerpo),
            '/health/{} responde e incluye el estado de Redis'.format(servicio), estado)

print('\n{} comprobaciones, {} fallos'.format(hechas, len(fallos)))
sys.exit(1 if fallos else 0)
