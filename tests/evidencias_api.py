# -*- coding: utf-8 -*-
"""Peticiones y respuestas de los microservicios, listas para capturar en pantalla.

    CA_CERT=~/libreria-api.crt HOST=34.51.108.167 \\
    ADMIN_EMAIL=... ADMIN_PASS=... LECTOR_EMAIL=... LECTOR_PASS=... \\
    python3 tests/evidencias_api.py <seccion>

Secciones (cada una cabe en una captura de terminal):

    jwt      login, claims del JWT, renovacion con refresh token, 401 y 403
    redis    logout revoca el JWT en users, pedidos y catalogo; refresh cerrado
    cache    GET /books: MISS y luego HIT (X-Cache), invalidacion y /metrics
    crud     Authors, Users, Pedidos y Pagos: POST, GET, PUT/PATCH y DELETE
    caida    con Redis PARADO: login 503, GET /books 200, semaforos (/health)

Cada intercambio muestra el comando `curl` equivalente, la peticion y la
respuesta (estado, tiempo y cuerpo). Los secretos NUNCA se imprimen completos:
contrasenas, tokens y refresh tokens salen tapados (primeros caracteres y
longitud). Ademas, todo lo impreso se guarda en
docs/evidencias/peticiones_<seccion>.txt.

Solo biblioteca estandar. Las credenciales llegan por variable de entorno.
"""
import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

HOST = os.environ.get('HOST', '127.0.0.1')
CA_CERT = os.environ.get('CA_CERT')
CONTEXTO = ssl.create_default_context(cafile=CA_CERT) if CA_CERT else None
BASE = ('https://' if CONTEXTO else 'http://') + HOST
SECRETOS = {'password', 'token', 'refresh_token', 'password_hash'}
SALIDA = []
NUMERO = [0]


def imprimir(texto=''):
    print(texto)
    SALIDA.append(texto)


def tapar(valor):
    texto = str(valor)
    return '{}…({} caracteres)'.format(texto[:10], len(texto)) if len(texto) > 12 else '********'


def limpio(dato):
    """Copia del JSON con los secretos tapados."""
    if isinstance(dato, dict):
        return {k: (tapar(v) if k in SECRETOS and isinstance(v, str) else limpio(v)) for k, v in dato.items()}
    if isinstance(dato, list):
        return [limpio(x) for x in dato]
    return dato


def mostrar_cuerpo(dato, maximo=18):
    if dato is None:
        return
    if isinstance(dato, list) and len(dato) > 2:
        dato = dato[:2] + ['… ({} elementos mas)'.format(len(dato) - 2)]
    if isinstance(dato, dict) and isinstance(dato.get('books'), list) and len(dato['books']) > 1:
        dato = dict(dato, books=dato['books'][:1] + ['… ({} libros mas)'.format(len(dato['books']) - 1)])
    lineas = json.dumps(limpio(dato), ensure_ascii=False, indent=2).split('\n')
    for linea in lineas[:maximo]:
        imprimir('    ' + linea)
    if len(lineas) > maximo:
        imprimir('    …')


def llamar(titulo, metodo, ruta, cuerpo=None, token=None, esperado=None, cabeceras_a_mostrar=()):
    """Hace la peticion, la imprime con el curl equivalente y devuelve (estado, json, cabeceras)."""
    NUMERO[0] += 1
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cabeceras = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if token:
        cabeceras['Authorization'] = 'Bearer ' + token
    url = BASE + ruta
    imprimir('')
    imprimir('━━ {}. {}'.format(NUMERO[0], titulo))
    curl = 'curl -s -X {} {}{}'.format(metodo, '--cacert $CA_CERT ' if CONTEXTO else '', "'" + url + "'")
    if token:
        curl += " -H 'Authorization: Bearer <JWT {}>'".format(tapar(token).split('…')[0])
    if cuerpo is not None:
        curl += " -H 'Content-Type: application/json' -d '{}'".format(json.dumps(limpio(cuerpo), ensure_ascii=False))
    imprimir('  $ ' + curl)
    inicio = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=datos, headers=cabeceras, method=metodo),
                                    timeout=15, context=CONTEXTO) as r:
            crudo, estado, razon, cab = r.read(), r.status, r.reason, r.headers
    except urllib.error.HTTPError as e:
        crudo, estado, razon, cab = e.read(), e.code, e.reason, e.headers
    except (urllib.error.URLError, OSError) as e:
        imprimir('  ← SIN RESPUESTA: {}'.format(getattr(e, 'reason', e)))
        return 0, None, {}
    ms = int((time.time() - inicio) * 1000)
    try:
        dato = json.loads(crudo) if crudo else None
    except ValueError:
        dato = None
    marca = '' if esperado is None else ('  ✓ esperado' if estado == esperado else '  ✗ ESPERABA {}'.format(esperado))
    imprimir('  ← {} {}  ({} ms){}'.format(estado, razon, ms, marca))
    for nombre in cabeceras_a_mostrar:
        if cab.get(nombre):
            imprimir('    {}: {}'.format(nombre, cab[nombre]))
    mostrar_cuerpo(dato)
    return estado, dato, cab


def claims(token):
    cuerpo = token.split('.')[1]
    return json.loads(base64.urlsafe_b64decode(cuerpo + '=' * (-len(cuerpo) % 4)))


def entrar(correo_var, pass_var, titulo):
    estado, d, _ = llamar(titulo, 'POST', '/login?format=json',
                          {'email': os.environ[correo_var], 'password': os.environ[pass_var]}, esperado=200)
    if estado != 200:
        sys.exit('No se pudo iniciar sesion ({}).'.format(estado))
    return d['token'], d['refresh_token'], d['usuario']['id']


# =============================================================================
def seccion_jwt():
    imprimir('SECCION jwt — login, claims, renovacion y control de acceso')
    token, refresh, _ = entrar('LECTOR_EMAIL', 'LECTOR_PASS', 'Login del lector: devuelve JWT (20 min) y refresh token')
    c = claims(token)
    imprimir('  claims del JWT: user_id={}  role_id={}  rol={}  iss={}  jti={}…  vigencia={} s'.format(
        c['user_id'], c['role_id'], c['rol'], c['iss'], c['jti'][:8], c['exp'] - c['iat']))
    _, nuevo, _ = llamar('Renovar ANTES de caducar: el refresh token da JWT y refresh nuevos',
                         'POST', '/token/refresh?format=json', {'refresh_token': refresh}, esperado=200)
    llamar('El refresh token ya usado se rechaza (un solo uso)', 'POST', '/token/refresh?format=json',
           {'refresh_token': refresh}, esperado=401)
    llamar('Sin token: 401', 'GET', '/users', esperado=401)
    llamar('Token de lector en una ruta de admin: 403', 'GET', '/users', token=nuevo['token'], esperado=403)
    llamar('Token de lector en lo suyo: 200', 'GET', '/orders', token=nuevo['token'], esperado=200)
    llamar('Cierre de sesion (limpia lo creado)', 'POST', '/logout?format=json',
           {'refresh_token': nuevo['refresh_token']}, token=nuevo['token'], esperado=200)


def seccion_redis():
    imprimir('SECCION redis — el logout revoca el JWT en todos los servicios')
    token, refresh, _ = entrar('ADMIN_EMAIL', 'ADMIN_PASS', 'Login del admin')
    llamar('Antes del logout: el JWT entra a Users', 'GET', '/users', token=token, esperado=200)
    llamar('POST /logout: revoca el JWT (jwt:revoked:<jti>) y borra sesion y refresh', 'POST', '/logout?format=json',
           {'refresh_token': refresh}, token=token, esperado=200)
    llamar('El MISMO JWT ya no entra a Users', 'GET', '/users', token=token, esperado=401)
    llamar('Ni a Pedidos', 'GET', '/orders', token=token, esperado=401)
    llamar('Ni a las escrituras del catalogo', 'DELETE', '/books/delete/0000000000000', token=token, esperado=401)
    llamar('Ni a las metricas', 'GET', '/metrics/catalogo', token=token, esperado=401)
    llamar('El refresh token de esa sesion tampoco sirve', 'POST', '/token/refresh?format=json',
           {'refresh_token': refresh}, esperado=401)


def seccion_cache():
    imprimir('SECCION cache — GET /books cacheado en Redis (TTL 60 s) y su invalidacion')
    token, _refresh, _ = entrar('ADMIN_EMAIL', 'ADMIN_PASS', 'Login del admin')
    # Para que la primera lectura sea MISS de verdad, se vacia la cache con una
    # escritura previa (crear y borrar un autor invalida books:*).
    e0, previo, _ = llamar('Escritura previa: deja la cache vacia (invalida books:*)', 'POST', '/authors',
                           {'nombre': 'Autor limpieza cache'}, token=token, esperado=201)
    if e0 == 201:
        llamar('Se borra el autor de la escritura previa', 'DELETE', '/authors/{}'.format(previo['id']),
               token=token, esperado=204)
    llamar('GET /books (primera lectura: MISS, va a PostgreSQL)', 'GET', '/books?limite=3&format=json',
           esperado=200, cabeceras_a_mostrar=('X-Cache',))
    llamar('GET /books (2a lectura: HIT, sale de Redis)', 'GET', '/books?limite=3&format=json',
           esperado=200, cabeceras_a_mostrar=('X-Cache',))
    _, d, _ = llamar('GET /books/<isbn> (se cachea como books:<isbn>)', 'GET',
                     '/books/978-0-13-235088-4?format=json', esperado=200, cabeceras_a_mostrar=('X-Cache',))
    llamar('GET /books/<isbn> otra vez: HIT', 'GET', '/books/978-0-13-235088-4?format=json',
           esperado=200, cabeceras_a_mostrar=('X-Cache',))
    estado, autor, _ = llamar('Una escritura de Authors invalida books:*', 'POST', '/authors',
                              {'nombre': 'Autor evidencia cache'}, token=token, esperado=201)
    llamar('GET /books justo despues: MISS (la cache se borro)', 'GET', '/books?limite=3&format=json',
           esperado=200, cabeceras_a_mostrar=('X-Cache',))
    if estado == 201:
        llamar('Limpieza: se borra el autor de prueba', 'DELETE', '/authors/{}'.format(autor['id']),
               token=token, esperado=204)
    llamar('Metricas del catalogo (solo admin): aciertos, fallos, invalidaciones', 'GET', '/metrics/catalogo',
           token=token, esperado=200)
    llamar('Metricas del login: inicios de sesion, refresh, logout', 'GET', '/metrics/login',
           token=token, esperado=200)
    llamar('Cierre de sesion', 'POST', '/logout?format=json', token=token, esperado=200)


def seccion_crud():
    imprimir('SECCION crud — Authors, Users, Pedidos y Pagos')
    token, _r, _ = entrar('ADMIN_EMAIL', 'ADMIN_PASS', 'Login del admin')
    e, autor, _ = llamar('AUTHORS  POST /authors', 'POST', '/authors',
                         {'nombre': 'Autor evidencia', 'nacionalidad': 'Pruebas'}, token=token, esperado=201)
    aid = autor['id'] if e == 201 else 0
    llamar('AUTHORS  PUT /authors/{id}', 'PUT', '/authors/%d' % aid,
           {'nombre': 'Autor evidencia', 'nacionalidad': 'Mexicana', 'biografia': 'Autor de prueba'}, token=token, esperado=200)
    llamar('AUTHORS  PATCH /authors/{id}', 'PATCH', '/authors/%d' % aid, {'biografia': 'Editada'}, token=token, esperado=200)
    llamar('AUTHORS  GET /authors/{id} (publico)', 'GET', '/authors/%d' % aid, esperado=200)
    llamar('AUTHORS  DELETE /authors/{id}', 'DELETE', '/authors/%d' % aid, token=token, esperado=204)
    llamar('USERS    GET /users (admin)', 'GET', '/users', token=token, esperado=200)
    _, libros, _ = llamar('PEDIDOS  GET /orders/books (ids, precio y stock)', 'GET', '/orders/books', token=token, esperado=200)
    libro = next((l for l in libros if l['stock'] > 2), libros[0])
    e, pedido, _ = llamar('PEDIDOS  POST /orders (descuenta stock)', 'POST', '/orders',
                          {'lineas': [{'libro_id': libro['id'], 'cantidad': 1}]}, token=token, esperado=201)
    pid = pedido['id'] if e == 201 else 0
    llamar('PEDIDOS  PUT /orders/{id} (cambia las lineas)', 'PUT', '/orders/%d' % pid,
           {'lineas': [{'libro_id': libro['id'], 'cantidad': 2}]}, token=token, esperado=200)
    e, ped, _ = llamar('PEDIDOS  GET /orders/{id} (lineas e historial)', 'GET', '/orders/%d' % pid, token=token, esperado=200)
    e, pago, _ = llamar('PAGOS    POST /payments (pedido pasa a pagado)', 'POST', '/payments',
                        {'pedido_id': pid, 'monto': ped['total'], 'metodo': 'tarjeta', 'referencia': 'EVID-REDIS'},
                        token=token, esperado=201)
    llamar('PAGOS    GET /payments', 'GET', '/payments', token=token, esperado=200)
    llamar('PEDIDOS  PATCH /orders/{id}/status = cancelado (devuelve stock)', 'PATCH', '/orders/%d/status' % pid,
           {'estado': 'cancelado'}, token=token, esperado=200)
    if e == 200 and isinstance(pago, dict):
        llamar('PAGOS    PATCH /payments/{id}/status = reembolsado', 'PATCH',
               '/payments/%d/status' % pago['id'], {'estado': 'reembolsado'}, token=token, esperado=200)
    llamar('Cierre de sesion', 'POST', '/logout?format=json', token=token, esperado=200)


def seccion_caida():
    imprimir('SECCION caida — Redis PARADO (sudo systemctl stop redis)')
    llamar('Login con Redis caido: 503 (no se abre sesion sin Redis)', 'POST', '/login?format=json',
           {'email': os.environ['LECTOR_EMAIL'], 'password': os.environ['LECTOR_PASS']}, esperado=503,
           cabeceras_a_mostrar=('Retry-After',))
    llamar('Ruta protegida sin token: sigue siendo 401', 'GET', '/orders', esperado=401)
    llamar('GET /books: sigue sirviendo desde PostgreSQL (la cache falla abierto)', 'GET', '/books?limite=2&format=json',
           esperado=200, cabeceras_a_mostrar=('X-Cache',))
    for servicio in ('login', 'catalogo', 'users', 'authors', 'pedidos', 'pagos'):
        llamar('Semaforo {}: responde y marca Redis caido (amarillo)'.format(servicio), 'GET',
               '/health/{}?format=json'.format(servicio), esperado=200)


SECCIONES = {'jwt': seccion_jwt, 'redis': seccion_redis, 'cache': seccion_cache,
             'crud': seccion_crud, 'caida': seccion_caida}

if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in SECCIONES:
        sys.exit(__doc__)
    necesarias = ('LECTOR_EMAIL', 'LECTOR_PASS') if sys.argv[1] == 'caida' else \
        ('ADMIN_EMAIL', 'ADMIN_PASS', 'LECTOR_EMAIL', 'LECTOR_PASS')
    faltan = [v for v in necesarias if not os.environ.get(v)]
    if faltan:
        sys.exit('Faltan variables de entorno: ' + ', '.join(faltan))
    SECCIONES[sys.argv[1]]()
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'evidencias',
                        'peticiones_{}.txt'.format(sys.argv[1]))
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write('\n'.join(SALIDA) + '\n')
    print('\n(guardado en docs/evidencias/peticiones_{}.txt)'.format(sys.argv[1]))
