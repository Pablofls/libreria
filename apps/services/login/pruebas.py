# -*- coding: utf-8 -*-
"""Pruebas en proceso del microservicio de autenticacion.

    python3 pruebas.py

No necesitan PostgreSQL ni Postfix: el acceso a datos y la sonda SMTP se
sustituyen por dobles, y las peticiones van por el `test_client` de Flask. Lo
que se comprueba es el contrato —codigos, formatos, que no se filtre el hash—
no que la base conteste, que eso solo se puede verificar en la VM.
"""
import json
import os
import smtplib
import sys
import xml.etree.ElementTree as ET

os.environ.setdefault('SECRET_KEY', 'clave-solo-para-las-pruebas-en-proceso')
os.environ.setdefault('VERIFICAR_CORREO', '1')

import app as servicio                                            # noqa: E402
import psycopg                                                    # noqa: E402

# sin_efectos() sustituye servicio.verificar_correo por un doble, asi que la
# seccion 4 —la unica que prueba la funcion de verdad— necesita guardarse la
# original antes de que nadie la pise.
VERIFICAR_REAL = servicio.verificar_correo

fallos = []
hechas = 0


def revisar(condicion, descripcion, extra=''):
    global hechas
    hechas += 1
    if condicion:
        print('  ok   {}'.format(descripcion))
    else:
        print('  FALLA {} {}'.format(descripcion, extra))
        fallos.append(descripcion)


USUARIO = {
    'id': 31, 'nombre': 'Ana', 'apellido_paterno': 'Ruiz',
    'apellido_materno': 'Lopez', 'nombre_completo': 'Ana Ruiz Lopez',
    'email': 'ana.ruiz@example.com', 'rol': 'lector',
}
FILA = dict(USUARIO, activo=True)
HASH = servicio.bcrypt.hashpw(b'contrasena-buena',
                              servicio.bcrypt.gensalt(rounds=4)).decode()

servicio.app.config['TESTING'] = True
cliente = servicio.app.test_client()


def sin_efectos():
    """Dobles por omision: base que responde y correo verificado."""
    servicio.crear_usuario = lambda campos: dict(USUARIO, email=campos['email'])
    servicio.buscar_por_email = lambda email: dict(FILA) if email == FILA['email'] else None
    servicio.buscar_hash = lambda email: HASH if email == FILA['email'] else None
    servicio.buscar_por_id = lambda ident: dict(FILA) if ident == FILA['id'] else None
    servicio.verificar_correo = lambda email: {
        'estado': servicio.CORREO_VERIFICADO, 'codigo': 250,
        'mensaje': 'El servidor de correo confirma que la direccion existe.'}


ALTA = {'nombre': 'Ana', 'apellido_paterno': 'Ruiz', 'apellido_materno': 'Lopez',
        'email': 'ana.ruiz@example.com', 'password': 'contrasena-buena'}


# --- 1. El contrato de formato ------------------------------------------------
print('\n1. Formato: XML por omision, JSON a peticion')
sin_efectos()

r = cliente.get('/health')
revisar(r.content_type.startswith('application/xml'),
        'GET /health sin parametro responde XML', r.content_type)
revisar(r.data.startswith(b'<?xml'), 'el XML lleva su declaracion')

r = cliente.get('/health?format=json')
revisar(r.content_type.startswith('application/json'),
        '?format=json responde JSON', r.content_type)

r = cliente.get('/health?format=XML')
revisar(r.content_type.startswith('application/xml'), 'el valor no distingue mayusculas')

r = cliente.get('/health?format=yaml')
revisar(r.status_code == 400, 'un formato desconocido es 400', r.status_code)
revisar(r.content_type.startswith('application/xml'),
        'y ese 400 sale en XML, que es el formato por omision')

r = cliente.get('/health?format=yaml&x=1')
revisar(b'xml, json' in r.data, 'el 400 dice cuales son los valores validos')

r = cliente.get('/no-existe?format=json')
revisar(r.status_code == 404 and r.content_type.startswith('application/json'),
        'un 404 tambien respeta el formato pedido')

r = cliente.get('/no-existe')
revisar(r.status_code == 404 and r.content_type.startswith('application/xml'),
        'y sin parametro sale en XML')

r = cliente.get('/session', headers={'Accept': 'application/json'})
revisar(r.content_type.startswith('application/json'),
        'Accept: application/json basta cuando no hay parametro')

r = cliente.get('/session', headers={'Accept': '*/*'})
revisar(r.content_type.startswith('application/xml'),
        'Accept: */* (curl) sigue recibiendo XML')

r = cliente.post('/login?format=json', data={'email': 'x'})
revisar(r.content_type.startswith('application/json'),
        'el parametro funciona igual en POST')


# --- 2. Registro ---------------------------------------------------------------
print('\n2. POST /register')
sin_efectos()

r = cliente.post('/register', data={})
cuerpo = r.data.decode()
revisar(r.status_code == 400, 'sin datos, 400', r.status_code)
revisar(cuerpo.count('<detalle>') >= 5, 'un detalle por cada campo que falta')

r = cliente.post('/register?format=json',
                 data=dict(ALTA, email='esto-no-es-un-correo'))
datos = json.loads(r.data)
revisar(r.status_code == 400 and 'formato valido' in str(datos['detalles']),
        'un correo mal formado es 400')

r = cliente.post('/register?format=json', data=dict(ALTA, password='corta'))
revisar(r.status_code == 400 and 'al menos 8' in str(json.loads(r.data)['detalles']),
        'una contrasena corta es 400')

r = cliente.post('/register?format=json', data=dict(ALTA, password='x' * 80))
revisar(r.status_code == 400 and '72' in str(json.loads(r.data)['detalles']),
        'una contrasena de mas de 72 bytes es 400, porque bcrypt la truncaria')

r = cliente.post('/register?format=json', data=dict(ALTA, apellido_materno=''))
revisar(r.status_code == 400, 'el apellido materno es obligatorio en el alta')

r = cliente.post('/register?format=json',
                 data=dict(ALTA, nombre='N' * 60, apellido_paterno='P' * 60))
revisar(r.status_code == 400 and 'completo' in str(json.loads(r.data)['detalles']),
        'un nombre completo de mas de 100 caracteres se explica, no revienta')

# El correo no existe: Postfix devolvio un 5xx.
servicio.verificar_correo = lambda email: {
    'estado': servicio.CORREO_INEXISTENTE, 'codigo': 550,
    'mensaje': 'El servidor de correo rechaza esa direccion: no existe el buzon.'}
r = cliente.post('/register?format=json', data=ALTA)
revisar(r.status_code == 400, 'un 5xx de Postfix impide el alta', r.status_code)

# No se pudo comprobar: se registra igual.
servicio.verificar_correo = lambda email: {
    'estado': servicio.CORREO_NO_VERIFICABLE, 'codigo': 450,
    'mensaje': 'No se pudo comprobar la direccion en este momento.'}
r = cliente.post('/register?format=json', data=ALTA)
datos = json.loads(r.data)
revisar(r.status_code == 201, 'un 4xx de Postfix NO impide el alta', r.status_code)
revisar(datos['correo']['estado'] == 'no_verificable',
        'y la respuesta lo dice en vez de fingir que verifico')

sin_efectos()
r = cliente.post('/register', data=ALTA)
revisar(r.status_code == 201, 'alta correcta, 201', r.status_code)
raiz = ET.fromstring(r.data.decode().split('?>', 1)[1].strip())
revisar(raiz.tag == 'registro', 'la raiz XML es <registro>', raiz.tag)
revisar(raiz.find('usuario/apellido_paterno').text == 'Ruiz',
        'el XML trae los apellidos por separado')
revisar(raiz.find('usuario/nombre_completo').text == 'Ana Ruiz Lopez',
        'y el nombre completo que compone el disparador')
revisar(b'password' not in r.data.lower() and b'hash' not in r.data.lower(),
        'la respuesta no menciona la contrasena ni su hash')

r = cliente.post('/register?format=json', json=ALTA)
revisar(r.status_code == 201, 'el cuerpo tambien se acepta como JSON', r.status_code)

# `format` viaja en el query string y no debe acabar siendo un dato del alta.
capturado = {}
servicio.crear_usuario = lambda campos: capturado.update(campos) or dict(USUARIO)
cliente.post('/register?format=json', data=ALTA)
revisar('format' not in capturado, 'el parametro format no se cuela en los datos')
revisar('password' in capturado and capturado['email'] == ALTA['email'],
        'los campos del cuerpo si llegan')


def duplicado(_campos):
    raise psycopg.errors.UniqueViolation('uq_usuarios_email')


servicio.crear_usuario = duplicado
r = cliente.post('/register?format=json', data=ALTA)
revisar(r.status_code == 409, 'un correo repetido es 409, no 500', r.status_code)
revisar('uq_usuarios' not in r.data.decode(),
        'y el mensaje no nombra la restriccion ni la tabla')


# --- 3. Sesion ------------------------------------------------------------------
print('\n3. POST /login, GET /session, POST /logout')
sin_efectos()

r = cliente.post('/login?format=json', data={'email': FILA['email'],
                                             'password': 'la-que-no-es'})
revisar(r.status_code == 401, 'contrasena incorrecta, 401', r.status_code)

r = cliente.post('/login?format=json', data={'email': 'nadie@example.com',
                                             'password': 'lo-que-sea'})
revisar(r.status_code == 401, 'correo inexistente, el mismo 401', r.status_code)
revisar(json.loads(r.data)['mensaje'] == 'Correo o contrasena incorrectos.',
        'con el mismo mensaje: no se puede enumerar quien tiene cuenta')

servicio.buscar_por_email = lambda email: dict(FILA, activo=False)
r = cliente.post('/login?format=json', data={'email': FILA['email'],
                                             'password': 'contrasena-buena'})
revisar(r.status_code == 401, 'cuenta desactivada, tambien 401', r.status_code)

sin_efectos()
r = cliente.get('/session?format=json')
revisar(json.loads(r.data)['autenticada'] is False, 'sin cookie, no hay sesion')

r = cliente.post('/login?format=json', data={'email': FILA['email'],
                                             'password': 'contrasena-buena'})
revisar(r.status_code == 200, 'credenciales correctas, 200', r.status_code)
revisar('libreria_sesion' in r.headers.get('Set-Cookie', ''),
        'se manda la cookie de sesion')
galleta = r.headers.get('Set-Cookie', '')
revisar('HttpOnly' in galleta, 'la cookie es HttpOnly: JavaScript no la lee')
revisar('SameSite=Lax' in galleta, 'y SameSite=Lax: no viaja desde otro sitio')
revisar(b'password_hash' not in r.data, 'el hash no sale en la respuesta')

r = cliente.get('/session?format=json')
datos = json.loads(r.data)
revisar(datos['autenticada'] is True, 'ya con cookie, la sesion se reconoce')
revisar(datos['usuario']['id'] == FILA['id'], 'y dice de quien es')

# La cuenta se borra mientras la cookie sigue firmada y siendo valida.
servicio.buscar_por_id = lambda ident: None
r = cliente.get('/session?format=json')
revisar(r.status_code == 401 and json.loads(r.data)['autenticada'] is False,
        'una cookie de una cuenta que ya no existe no vale')

sin_efectos()
cliente.post('/login', data={'email': FILA['email'], 'password': 'contrasena-buena'})
r = cliente.post('/logout?format=json')
revisar(r.status_code == 200 and json.loads(r.data)['ok'] is True, 'logout, 200')
r = cliente.get('/session?format=json')
revisar(json.loads(r.data)['autenticada'] is False, 'y despues ya no hay sesion')

r = cliente.post('/logout?format=json')
revisar(r.status_code == 200, 'cerrar una sesion que no existe tambien es 200')

r = cliente.get('/login')
revisar(r.status_code == 405, 'GET /login es 405', r.status_code)


# --- 4. La sonda de correo, con un Postfix falso --------------------------------
print('\n4. verificar_correo() contra un Postfix simulado')


class SMTPFalso:
    def __init__(self, respuesta):
        self.respuesta = respuesta

    def __call__(self, host, puerto, timeout=None):
        if isinstance(self.respuesta, Exception):
            raise self.respuesta
        return self

    def ehlo(self, _nombre=None):
        return (250, b'ok')

    def mail(self, _remitente):
        return (250, b'ok')

    def rcpt(self, _destinatario):
        return self.respuesta

    def quit(self):
        return (221, b'bye')


original = smtplib.SMTP
casos = [
    ((250, b'2.1.5 Ok'), servicio.CORREO_VERIFICADO, 'un 250 es verificado'),
    ((550, b'5.1.1 User unknown in local recipient table'),
     servicio.CORREO_INEXISTENTE, 'un 550 es inexistente'),
    ((550, b'5.1.2 Domain not found'), servicio.CORREO_INEXISTENTE,
     'un dominio sin DNS tambien es inexistente'),
    ((450, b'4.1.1 unverified address: Network is unreachable'),
     servicio.CORREO_NO_VERIFICABLE,
     'un 450 es NO VERIFICABLE, nunca inexistente'),
    ((451, b'4.7.1 Greylisted'), servicio.CORREO_NO_VERIFICABLE,
     'un greylisting tampoco se convierte en un rechazo'),
]
for respuesta, esperado, descripcion in casos:
    smtplib.SMTP = SMTPFalso(respuesta)
    obtenido = VERIFICAR_REAL('quien@example.com')
    revisar(obtenido['estado'] == esperado, descripcion, obtenido)

smtplib.SMTP = SMTPFalso(OSError('Connection refused'))
obtenido = VERIFICAR_REAL('quien@example.com')
revisar(obtenido['estado'] == servicio.CORREO_NO_VERIFICABLE,
        'con Postfix caido se registra igual, marcado como no verificable')

smtplib.SMTP = SMTPFalso((550, b'5.1.1 <x@y.z>: Recipient address rejected: '
                               b'unknown user; host mail-13.interno[10.0.0.4]'))
obtenido = VERIFICAR_REAL('x@y.z')
revisar('10.0.0.4' not in obtenido['mensaje'] and 'interno' not in obtenido['mensaje'],
        'el mensaje de Postfix no se reenvia crudo: llevaba una IP interna')
smtplib.SMTP = original


# --- 5. Swagger -------------------------------------------------------------------
print('\n5. Documentacion')
r = cliente.get('/apispec.json')
espec = json.loads(r.data)
rutas = espec['paths']
revisar(set(rutas) >= {'/register', '/login', '/logout', '/session', '/health'},
        'los cinco endpoints del enunciado estan documentados', sorted(rutas))
for ruta, operaciones in rutas.items():
    for metodo, operacion in operaciones.items():
        nombres = [p['name'] for p in operacion.get('parameters', [])]
        revisar('format' in nombres,
                '{} {} declara el parametro format'.format(metodo.upper(), ruta))
        for codigo, respuesta in operacion['responses'].items():
            tipos = set(respuesta['content'])
            revisar(tipos == {'application/xml', 'application/json'},
                    '{} {} {} documenta los dos formatos'.format(
                        metodo.upper(), ruta, codigo), tipos)

r = cliente.get('/docs')
revisar(r.status_code == 200 and b'swagger-ui' in r.data, 'GET /docs sirve Swagger UI')

r = cliente.get('/?format=json')
puntos = {p['ruta'] for p in json.loads(r.data)['endpoints']}
revisar({'/register', '/login', '/logout', '/session', '/health'} <= puntos,
        'el indice de / lista los endpoints')


# --- 6. Todos los renderizadores existen -------------------------------------------
print('\n6. Renderizadores XML')
for tipo in ('registro', 'sesion', 'resultado', 'salud', 'servicio', 'error'):
    revisar(tipo in servicio.RENDERIZADORES_XML,
            'hay renderizador XML para "{}"'.format(tipo))


print('\n{} comprobaciones, {} fallos'.format(hechas, len(fallos)))
if fallos:
    for f in fallos:
        print('  - ' + f)
sys.exit(1 if fallos else 0)
