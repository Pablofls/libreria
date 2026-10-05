# -*- coding: utf-8 -*-
"""Flujo completo de los servicios Users, Authors, Pedidos y Pagos contra la VM.

Solo biblioteca estandar. Requiere las cuatro unidades arriba, las tablas de
db/pending/20261004-pedidos-pagos.sql aplicadas y credenciales por entorno:

    HOST=34.51.108.167 \\
    ADMIN_EMAIL=... ADMIN_PASS=... LECTOR_EMAIL=... LECTOR_PASS=... \\
    python3 tests/pruebas_servicios.py

Por HTTPS (nginx en el 443, ver deploy/nginx-api-tls.conf): CA_CERT=<ruta al
.crt autofirmado>. Con eso todo va a https://HOST sin puertos y el certificado
SE VERIFICA contra esa copia (nunca se desactiva la verificacion).

Opcional: LIBRO_ID (un libro con stock), LOGIN_PORT/USERS_PORT/AUTHORS_PORT/
PEDIDOS_PORT/PAGOS_PORT. Las credenciales NUNCA van en el codigo.

Deja como rastro un pedido cancelado y un pago reembolsado: los pagos no se
borran (son registro contable). Limpia lo demas (autor y usuario de prueba).
"""
import json
import os
import secrets
import ssl
import sys
import urllib.error
import urllib.request

HOST = os.environ.get('HOST', '127.0.0.1')
PUERTOS = {n: os.environ.get(n.upper() + '_PORT', p) for n, p in
           (('login', '5000'), ('users', '5003'), ('authors', '5004'),
            ('pedidos', '5005'), ('pagos', '5006'))}
CA_CERT = os.environ.get('CA_CERT')
CONTEXTO = ssl.create_default_context(cafile=CA_CERT) if CA_CERT else None
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


def llamar(servicio, metodo, ruta, cuerpo=None, token=None):
    """(estado, json|None). Nunca imprime tokens ni contrasenas."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cabeceras = {'Content-Type': 'application/json'}
    if token:
        cabeceras['Authorization'] = 'Bearer ' + token
    # Por HTTPS, nginx reparte por ruta (/login, /users, ...): sin puertos.
    base = ('https://{}'.format(HOST) if CONTEXTO
            else 'http://{}:{}'.format(HOST, PUERTOS[servicio]))
    peticion = urllib.request.Request(
        base + ruta,
        data=datos, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(peticion, timeout=15, context=CONTEXTO) as r:
            crudo = r.read()
            return r.status, (json.loads(crudo) if crudo else None)
    except urllib.error.HTTPError as e:
        crudo = e.read()
        try:
            return e.code, json.loads(crudo)
        except ValueError:
            return e.code, None


def iniciar(email_var, pass_var):
    estado, cuerpo = llamar('login', 'POST', '/login?format=json', {
        'email': os.environ[email_var], 'password': os.environ[pass_var]})
    if estado != 200 or not cuerpo.get('token'):
        sys.exit('No se pudo iniciar sesion con {} (estado {})'.format(email_var, estado))
    return cuerpo['token'], cuerpo['usuario']['id'], cuerpo.get('refresh_token')


print('1. Login, claims y renovacion')
ADMIN, ADMIN_ID, _ = iniciar('ADMIN_EMAIL', 'ADMIN_PASS')
LECTOR, LECTOR_ID, LECTOR_REFRESH = iniciar('LECTOR_EMAIL', 'LECTOR_PASS')
estado, nuevo = llamar('login', 'POST', '/token/refresh?format=json',
                       {'refresh_token': LECTOR_REFRESH})
revisar(estado == 200 and nuevo and nuevo.get('token') and nuevo.get('refresh_token'),
        'POST /token/refresh con refresh_token, 200 (JWT y refresh nuevos)', estado)
if estado == 200:
    LECTOR = nuevo['token']   # el JWT anterior de la sesion queda revocado
estado, _ = llamar('login', 'POST', '/token/refresh?format=json', {'refresh_token': LECTOR_REFRESH})
revisar(estado == 401, 'el refresh_token ya usado no sirve, 401', estado)
estado, _ = llamar('login', 'POST', '/token/refresh?format=json')
revisar(estado == 400, 'refresh sin refresh_token, 400', estado)

print('2. Authors')
estado, autores = llamar('authors', 'GET', '/authors')
revisar(estado == 200 and isinstance(autores, list), 'GET /authors es publico', estado)
estado, _ = llamar('authors', 'POST', '/authors', {'nombre': 'Autor de prueba'})
revisar(estado == 401, 'POST sin token, 401', estado)
estado, _ = llamar('authors', 'POST', '/authors', {'nombre': 'Autor de prueba'}, LECTOR)
revisar(estado == 403, 'POST con token de lector, 403', estado)
estado, autor = llamar('authors', 'POST', '/authors',
                       {'nombre': 'Autor de prueba JWT', 'nacionalidad': 'Pruebas'}, ADMIN)
revisar(estado == 201 and autor.get('id'), 'POST con admin, 201', estado)
AUTOR = autor['id'] if estado == 201 else None
if AUTOR:
    estado, _ = llamar('authors', 'PATCH', '/authors/%d' % AUTOR, {'biografia': 'x'}, ADMIN)
    revisar(estado == 200, 'PATCH con admin, 200', estado)
    estado, _ = llamar('authors', 'DELETE', '/authors/%d' % AUTOR, token=ADMIN)
    revisar(estado == 204, 'DELETE con admin, 204', estado)
    estado, _ = llamar('authors', 'GET', '/authors/%d' % AUTOR)
    revisar(estado == 404, 'el autor borrado ya no existe, 404', estado)

print('3. Users')
estado, _ = llamar('users', 'GET', '/users')
revisar(estado == 401, 'GET /users sin token, 401', estado)
estado, _ = llamar('users', 'GET', '/users', token=LECTOR)
revisar(estado == 403, 'GET /users con lector, 403', estado)
estado, lista = llamar('users', 'GET', '/users', token=ADMIN)
revisar(estado == 200 and all('password_hash' not in u for u in lista),
        'GET /users con admin, 200 y sin hashes', estado)
estado, _ = llamar('users', 'GET', '/users/%d' % LECTOR_ID, token=LECTOR)
revisar(estado == 200, 'un lector ve su propia cuenta', estado)
estado, _ = llamar('users', 'GET', '/users/%d' % ADMIN_ID, token=LECTOR)
revisar(estado == 403, 'y no la de otro, 403', estado)
estado, _ = llamar('users', 'PATCH', '/users/%d' % LECTOR_ID, {'rol': 'admin'}, LECTOR)
revisar(estado == 403, 'un lector no se asciende a admin, 403', estado)
correo = 'prueba.jwt.servicios@example.com'
estado, usuario = llamar('users', 'POST', '/users', {
    'nombre': 'Prueba', 'apellido_paterno': 'Servicios', 'apellido_materno': 'Jwt',
    'email': correo, 'password': secrets.token_urlsafe(16)}, ADMIN)  # clave desechable, no se guarda
revisar(estado in (201, 409), 'POST /users con admin crea la cuenta de prueba', estado)
if estado == 201:
    estado, _ = llamar('users', 'PATCH', '/users/%d' % usuario['id'], {'nombre': 'Prueba2'}, ADMIN)
    revisar(estado == 200, 'PATCH con admin, 200', estado)
    estado, baja = llamar('users', 'DELETE', '/users/%d' % usuario['id'], token=ADMIN)
    revisar(estado == 200 and baja['activo'] is False, 'DELETE es baja logica', estado)

print('4. Pedidos y Pagos')
estado, _ = llamar('pedidos', 'GET', '/orders')
revisar(estado == 401, 'GET /orders sin token, 401', estado)
libro = os.environ.get('LIBRO_ID')
if not libro and isinstance(autores, list) and autores:
    for a in autores:
        _, libros = llamar('authors', 'GET', '/authors/%d/books' % a['id'])
        if libros:
            libro = libros[0]['id']
            break
if not libro:
    sys.exit('Sin libro para probar pedidos: define LIBRO_ID')
libro = int(libro)
estado, _ = llamar('pedidos', 'POST', '/orders', {'lineas': [{'libro_id': libro, 'cantidad': 999}]}, LECTOR)
revisar(estado == 409, 'pedir mas que el stock, 409', estado)
estado, pedido = llamar('pedidos', 'POST', '/orders', {'lineas': [{'libro_id': libro, 'cantidad': 1}]}, LECTOR)
revisar(estado == 201 and pedido['estado'] == 'pendiente', 'un lector crea su pedido, 201', estado)
if estado == 201:
    PEDIDO = pedido['id']
    estado, _ = llamar('pedidos', 'GET', '/orders/%d' % PEDIDO, token=ADMIN)
    revisar(estado == 200, 'el admin ve el pedido', estado)
    estado, _ = llamar('pedidos', 'PATCH', '/orders/%d/status' % PEDIDO, {'estado': 'enviado'}, LECTOR)
    revisar(estado == 403, 'un lector no cambia estados, 403', estado)
    estado, _ = llamar('pedidos', 'PATCH', '/orders/%d/status' % PEDIDO, {'estado': 'enviado'}, ADMIN)
    revisar(estado == 409, 'pendiente -> enviado no es una transicion valida, 409', estado)
    total = pedido['total']
    estado, _ = llamar('pagos', 'POST', '/payments',
                       {'pedido_id': PEDIDO, 'monto': round(total + 1, 2), 'metodo': 'tarjeta'}, LECTOR)
    revisar(estado == 409, 'pagar de mas, 409', estado)
    estado, pago = llamar('pagos', 'POST', '/payments',
                          {'pedido_id': PEDIDO, 'monto': total, 'metodo': 'tarjeta'}, LECTOR)
    revisar(estado == 201 and pago['pedido_estado'] == 'pagado',
            'pago completo, 201 y el pedido pasa a pagado', estado)
    estado, _ = llamar('pagos', 'POST', '/payments',
                       {'pedido_id': PEDIDO, 'monto': 1, 'metodo': 'tarjeta'}, LECTOR)
    revisar(estado == 409, 'un pedido pagado no admite otro pago, 409', estado)
    estado, _ = llamar('pagos', 'GET', '/payments', token=ADMIN)
    revisar(estado == 200, 'el admin lista pagos', estado)
    if estado == 200 and pago:
        estado, _ = llamar('pagos', 'PATCH', '/payments/%d/status' % pago['id'],
                           {'estado': 'reembolsado'}, ADMIN)
        revisar(estado == 409, 'reembolsar con el pedido vigente, 409', estado)
        estado, cancelado = llamar('pedidos', 'PATCH', '/orders/%d/status' % PEDIDO,
                                   {'estado': 'cancelado'}, ADMIN)
        revisar(estado == 200 and cancelado['estado'] == 'cancelado',
                'el admin cancela el pedido pagado (devuelve stock)', estado)
        estado, _ = llamar('pagos', 'PATCH', '/payments/%d/status' % pago['id'],
                           {'estado': 'reembolsado'}, ADMIN)
        revisar(estado == 200, 'ahora si se reembolsa el pago', estado)

print('\n{} comprobaciones, {} fallos'.format(hechas, len(fallos)))
sys.exit(1 if fallos else 0)
