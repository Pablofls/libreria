# -*- coding: utf-8 -*-
"""Pruebas del API Gateway (nginx, rutas /api/*) contra la VM, por HTTPS.

Solo biblioteca estandar. Ver deploy/nginx-api-tls.conf. Credenciales por
entorno, nunca en el codigo:

    CA_CERT=~/libreria-api.crt HOST=34.51.108.167 \\
    ADMIN_EMAIL=... ADMIN_PASS=... LECTOR_EMAIL=... LECTOR_PASS=... \\
    python3 tests/pruebas_gateway.py

Opcional: LIMITE=1 prueba el limitador de /api/login con una rafaga de logins
fallidos a un correo inexistente. Va al final y es opcional porque el servicio
de login tiene ademas su propio limitador por IP: tras la rafaga, los logins
desde tu IP pueden quedar bloqueados unos minutos.

No escribe nada en la base: solo lecturas y peticiones que el gateway rechaza.
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

HOST = os.environ.get('HOST', '127.0.0.1')
CA_CERT = os.environ.get('CA_CERT')
if not CA_CERT:
    sys.exit('Falta CA_CERT (copia del certificado autofirmado de la VM)')
CONTEXTO = ssl.create_default_context(cafile=os.path.expanduser(CA_CERT))
FALTAN = [v for v in ('ADMIN_EMAIL', 'ADMIN_PASS', 'LECTOR_EMAIL', 'LECTOR_PASS')
          if not os.environ.get(v)]
if FALTAN:
    sys.exit('Faltan variables de entorno: ' + ', '.join(FALTAN))

BASE = 'https://' + HOST
fallos, hechas = [], 0


class SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


ABRIDOR = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=CONTEXTO), SinRedireccion)


def revisar(condicion, descripcion, extra=''):
    global hechas
    hechas += 1
    print('  {} {} {}'.format('ok  ' if condicion else 'FALLA', descripcion,
                              '' if condicion else extra))
    if not condicion:
        fallos.append(descripcion)


def llamar(metodo, ruta, cuerpo=None, token=None):
    """(estado, json|None, cabeceras). Nunca imprime tokens ni contrasenas."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cabeceras = {'Content-Type': 'application/json'}
    if token:
        cabeceras['Authorization'] = 'Bearer ' + token
    peticion = urllib.request.Request(BASE + ruta, data=datos,
                                      headers=cabeceras, method=metodo)
    try:
        with ABRIDOR.open(peticion, timeout=15) as r:
            crudo, estado, encabezados = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        crudo, estado, encabezados = e.read(), e.code, e.headers
    try:
        return estado, json.loads(crudo) if crudo else None, encabezados
    except ValueError:
        return estado, None, encabezados


def del_gateway(cuerpo):
    return isinstance(cuerpo, dict) and cuerpo.get('origen') == 'gateway'


def iniciar(email_var, pass_var):
    estado, cuerpo, _ = llamar('POST', '/api/login?format=json', {
        'email': os.environ[email_var], 'password': os.environ[pass_var]})
    if estado != 200 or not (cuerpo or {}).get('token'):
        sys.exit('No se pudo iniciar sesion por /api/login con {} (estado {})'
                 .format(email_var, estado))
    return cuerpo['token']


print('1. Monolito en /')
estado, _, cab = llamar('GET', '/')
revisar(estado == 302 and cab.get('Location') == '/library/',
        'GET / redirige a /library/', '{} {}'.format(estado, cab.get('Location')))
estado, _, cab = llamar('GET', '/library/login')
revisar(estado == 200 and 'text/html' in (cab.get('Content-Type') or ''),
        'GET /library/login sirve el monolito (HTML)', estado)
revisar(bool(cab.get('X-Request-ID')), 'la respuesta lleva X-Request-ID')

print('2. Lecturas publicas')
estado, libros, _ = llamar('GET', '/api/books?format=json')
revisar(estado == 200 and libros is not None, 'GET /api/books sin token, 200', estado)
estado, autores, _ = llamar('GET', '/api/autores')
revisar(estado == 200 and isinstance(autores, list), 'GET /api/autores sin token, 200', estado)

print('3. El gateway rechaza antes (sin token)')
for metodo, ruta in (('POST', '/api/autores'), ('POST', '/api/books/insert'),
                     ('GET', '/api/pedidos'), ('GET', '/api/pagos'),
                     ('GET', '/api/users'), ('GET', '/api/pedidos/1')):
    estado, cuerpo, _ = llamar(metodo, ruta, {} if metodo == 'POST' else None)
    revisar(estado == 401 and del_gateway(cuerpo),
            '{} {} sin token, 401 del gateway'.format(metodo, ruta), estado)
estado, cuerpo, _ = llamar('GET', '/api/pedidos', token='no.es.un.jwt')
revisar(estado == 401 and del_gateway(cuerpo), 'token basura, 401 del gateway', estado)
estado, _, _ = llamar('OPTIONS', '/api/pedidos')
revisar(estado != 401, 'OPTIONS (preflight CORS) no exige token', estado)
estado, cuerpo, _ = llamar('GET', '/api/nada')
revisar(estado == 404 and del_gateway(cuerpo), '/api/nada, 404 JSON del gateway', estado)

print('4. Con JWT obtenido por /api/login')
ADMIN = iniciar('ADMIN_EMAIL', 'ADMIN_PASS')
LECTOR = iniciar('LECTOR_EMAIL', 'LECTOR_PASS')
revisar(True, 'POST /api/login con admin y con lector, 200 y token')
estado, _, _ = llamar('GET', '/api/login/session')
revisar(estado != 404, 'GET /api/login/session llega a login', estado)
estado, pedidos, _ = llamar('GET', '/api/pedidos', token=ADMIN)
revisar(estado == 200, 'GET /api/pedidos con admin, 200', estado)
estado, _, _ = llamar('GET', '/api/pagos', token=ADMIN)
revisar(estado == 200, 'GET /api/pagos con admin, 200', estado)
estado, _, _ = llamar('GET', '/api/users', token=ADMIN)
revisar(estado == 200, 'GET /api/users con admin, 200', estado)
estado, cuerpo, _ = llamar('GET', '/api/users', token=LECTOR)
revisar(estado == 403 and not del_gateway(cuerpo),
        'GET /api/users con lector: pasa el gateway y el servicio responde 403', estado)
estado, cuerpo, _ = llamar('POST', '/api/autores', {'nombre': 'x'}, LECTOR)
revisar(estado == 403 and not del_gateway(cuerpo),
        'POST /api/autores con lector: 403 del servicio', estado)

print('5. Las rutas sin prefijo siguen')
estado, _, _ = llamar('GET', '/books?format=json')
revisar(estado == 200, 'GET /books, 200', estado)
estado, _, _ = llamar('GET', '/orders', token=ADMIN)
revisar(estado == 200, 'GET /orders con admin, 200', estado)

if os.environ.get('LIMITE') == '1':
    print('6. Limitador de /api/login')
    vistos = set()
    for _ in range(25):
        estado, cuerpo, _ = llamar('POST', '/api/login?format=json', {
            'email': 'nadie.gateway@example.com', 'password': 'incorrecta'})
        vistos.add((estado, del_gateway(cuerpo)))
    revisar((429, True) in vistos, 'una rafaga de 25 logins recibe 429 del gateway',
            sorted(vistos))

print('\n{} pruebas, {} fallos'.format(hechas, len(fallos)))
sys.exit(1 if fallos else 0)
