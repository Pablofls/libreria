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
from datetime import datetime, timedelta, timezone

os.environ.setdefault('SECRET_KEY', 'clave-solo-para-las-pruebas-en-proceso')
os.environ.setdefault('JWT_SECRET', 'otra-clave-solo-para-las-pruebas-en-proceso')
os.environ.setdefault('VERIFICAR_CORREO', '1')

import app as servicio                                            # noqa: E402
import jwt                                                        # noqa: E402
import fnmatch                                                    # noqa: E402
import redis as _redis_lib                                        # noqa: E402


class RedisFalso:
    """Redis en memoria para las pruebas. `caido = True` simula una caida."""

    def __init__(self):
        self.datos, self.ttls, self.caido = {}, {}, False

    def _vivo(self):
        if self.caido:
            raise _redis_lib.ConnectionError('simulado')

    def ping(self):
        self._vivo()
        return True

    def exists(self, *claves):
        self._vivo()
        return sum(1 for k in claves if k in self.datos)

    def get(self, clave):
        self._vivo()
        return self.datos.get(clave)

    def set(self, clave, valor, ex=None):
        self._vivo()
        self.datos[clave] = str(valor)
        self.ttls[clave] = ex
        return True

    def setex(self, clave, segundos, valor):
        return self.set(clave, valor, ex=segundos)

    def incrby(self, clave, cantidad=1):
        self._vivo()
        self.datos[clave] = str(int(self.datos.get(clave, 0)) + cantidad)
        return int(self.datos[clave])

    def expire(self, clave, segundos):
        self._vivo()
        if clave in self.datos:
            self.ttls[clave] = segundos
        return True

    def delete(self, *claves):
        self._vivo()
        return sum(1 for k in claves if self.datos.pop(k, None) is not None)

    unlink = delete

    def ttl(self, clave):
        self._vivo()
        return self.ttls.get(clave, -1) if clave in self.datos else -2

    def scan_iter(self, match='*', count=None):
        self._vivo()
        return iter([k for k in list(self.datos) if fnmatch.fnmatch(k, match)])


FALSO = RedisFalso()
servicio.REDIS_URL = 'redis://:falsa@127.0.0.1:6379/0'
servicio._redis = FALSO
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
    FALSO.datos.clear()
    FALSO.ttls.clear()
    FALSO.caido = False
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

token = json.loads(r.data).get('token')
refresco = json.loads(r.data).get('refresh_token')
revisar(bool(token), 'el login tambien devuelve un JWT')
reclamos = jwt.decode(token, servicio.JWT_SECRET, algorithms=['HS256'],
                      issuer='login-libreria')
revisar(reclamos['sub'] == str(FILA['id']), 'el JWT identifica al usuario', reclamos)
revisar(reclamos['rol'] == FILA['rol'], 'y lleva su rol', reclamos)
try:
    jwt.decode(token, 'una-clave-que-no-es', algorithms=['HS256'])
    revisar(False, 'un JWT firmado con otra clave deberia rechazarse')
except jwt.InvalidSignatureError:
    revisar(True, 'y una firma con otra clave se rechaza')
revisar(reclamos['user_id'] == FILA['id'] and reclamos['role_id'] == servicio.ROLES_ID[FILA['rol']],
        'el JWT lleva user_id y role_id', reclamos)
revisar(reclamos['exp'] - reclamos['iat'] == servicio.JWT_EXPIRA_MINUTOS * 60
        and servicio.JWT_EXPIRA_MINUTOS == 20, 'y caduca a los 20 minutos', reclamos)

revisar('jti' in reclamos and len(reclamos['jti']) >= 8, 'el JWT lleva un jti unico', reclamos)
revisar(bool(refresco), 'y el login devuelve un refresh_token')
claves_sesion = [k for k in FALSO.datos if k.startswith('session:')]
revisar(len(claves_sesion) == 1 and FALSO.ttls[claves_sesion[0]] == servicio.SESION_TTL_SEGUNDOS,
        'la sesion vive en Redis con su TTL')
revisar(all(refresco not in k and refresco not in v for k, v in FALSO.datos.items()),
        'el refresh token NO se guarda en claro en Redis')
revisar(any(k.startswith('refresh:') and FALSO.ttls[k] == servicio.SESION_TTL_SEGUNDOS
            for k in FALSO.datos), 'el refresh (por su hash) tiene el mismo TTL que la sesion')

# Renovacion: el refresh token (de un solo uso) se cambia por JWT + refresh nuevos.
r = cliente.post('/token/refresh?format=json', json={'refresh_token': refresco})
renovado = json.loads(r.data)
revisar(r.status_code == 200 and renovado.get('token') and renovado.get('token') != token,
        'POST /token/refresh con refresh valido, 200 y JWT nuevo', r.status_code)
revisar(renovado.get('refresh_token') and renovado['refresh_token'] != refresco,
        'y un refresh token nuevo (rotacion)')
revisar(FALSO.exists('jwt:revoked:' + reclamos['jti']) == 1,
        'el JWT anterior de la sesion queda revocado')
r = cliente.post('/token/refresh?format=json', json={'refresh_token': refresco})
revisar(r.status_code == 401, 'el refresh ya usado no sirve otra vez (un solo uso), 401', r.status_code)
r = cliente.post('/token/refresh?format=json')
revisar(r.status_code == 400, 'refresh sin refresh_token, 400', r.status_code)
r = cliente.post('/token/refresh?format=json', json={'refresh_token': 'inventado'})
revisar(r.status_code == 401, 'refresh inventado, 401', r.status_code)
# La sesion conserva su vencimiento absoluto: renovar no la alarga.
clave_s = [k for k in FALSO.datos if k.startswith('session:')][0]
FALSO.ttls[clave_s] = 100
r = cliente.post('/token/refresh?format=json', json={'refresh_token': renovado['refresh_token']})
revisar(r.status_code == 200 and FALSO.ttls[clave_s] == 100,
        'renovar no alarga la sesion mas alla de su TTL original', FALSO.ttls[clave_s])

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
print('\n3b. Redis: revocacion al salir, caida y limitador')


def iniciar():
    r = cliente.post('/login?format=json', data={'email': FILA['email'], 'password': 'contrasena-buena'})
    return r, json.loads(r.data)


sin_efectos()
r, cuerpo = iniciar()
T, R = cuerpo['token'], cuerpo['refresh_token']
jti = jwt.decode(T, options={'verify_signature': False})['jti']
r = cliente.post('/logout?format=json', json={'refresh_token': R}, headers={'Authorization': 'Bearer ' + T})
revisar(r.status_code == 200 and json.loads(r.data)['ok'] is True, 'logout, 200')
revisar(FALSO.exists('jwt:revoked:' + jti) == 1, 'el JWT queda en la lista de revocacion jwt:revoked:<jti>')
revisar(0 < FALSO.ttl('jwt:revoked:' + jti) <= servicio.JWT_EXPIRA_MINUTOS * 60 or FALSO.ttls['jwt:revoked:' + jti] <= 1200,
        'con TTL de lo que le quedaba al token, nunca mas')
revisar(not any(k.startswith(('session:', 'refresh:')) for k in FALSO.datos),
        'sesion y refresh token borrados de Redis')
r = cliente.post('/token/refresh?format=json', json={'refresh_token': R})
revisar(r.status_code == 401, 'el refresh de una sesion cerrada no sirve, 401', r.status_code)
r = cliente.get('/session?format=json')
revisar(json.loads(r.data)['autenticada'] is False, 'y /session ya no la reconoce')

# Caida de Redis: sesion, renovacion y cierre fallan cerrado.
sin_efectos()
r, cuerpo = iniciar()
T, R = cuerpo['token'], cuerpo['refresh_token']
FALSO.caido = True
r = cliente.post('/logout?format=json', json={'refresh_token': R}, headers={'Authorization': 'Bearer ' + T})
revisar(r.status_code == 503 and b'Sesion cerrada' not in r.data,
        'logout con Redis caido: 503 y NO finge que cerro la sesion', r.status_code)
r = cliente.post('/token/refresh?format=json', json={'refresh_token': R})
revisar(r.status_code == 503, 'refresh con Redis caido, 503', r.status_code)
r = cliente.get('/session?format=json')
revisar(r.status_code == 503, '/session con Redis caido, 503', r.status_code)
r = cliente.post('/login?format=json', data={'email': FILA['email'], 'password': 'contrasena-buena'})
revisar(r.status_code == 503 and b'"token"' not in r.data, 'login con Redis caido: 503 y sin token', r.status_code)
revisar(r.headers.get('Retry-After') is not None, 'y pide reintentar')
revisar(servicio.estado_redis() == 'caido', 'estado_redis() informa caido')
FALSO.caido = False
revisar(servicio.estado_redis() == 'ok', 'y ok cuando vuelve')
r = cliente.get('/session?format=json')
revisar(json.loads(r.data)['autenticada'] is True, 'al volver Redis, la sesion que no se pudo cerrar sigue ahi (se reintenta)')

# Limitador de intentos (tarea temporal coordinada por Redis).
sin_efectos()
for i in range(servicio.LOGIN_MAX_INTENTOS):
    r = cliente.post('/login?format=json', data={'email': FILA['email'], 'password': 'mala-contrasena'})
    revisar(r.status_code == 401, 'intento fallido {}, 401'.format(i + 1), r.status_code)
r = cliente.post('/login?format=json', data={'email': FILA['email'], 'password': 'contrasena-buena'})
revisar(r.status_code == 429 and r.headers.get('Retry-After'),
        'superado el limite, 429 incluso con la contrasena buena', r.status_code)
clave_i = [k for k in FALSO.datos if k.startswith('ratelimit:login:')][0]
revisar(FALSO.ttls[clave_i] == servicio.LOGIN_VENTANA_SEGUNDOS, 'el contador vence solo (TTL de la ventana)')
FALSO.delete(clave_i)
r, _ = iniciar()
revisar(r.status_code == 200, 'pasada la ventana, entra')
revisar(FALSO.datos.get('metrics:login:login_correctos') is not None, 'las metricas cuentan los logins')

# Metricas (solo admin, con la misma revocacion que el resto).
sin_efectos()
admin = dict(USUARIO, rol='admin')
tok_admin, tok_lector = servicio.generar_jwt(admin), servicio.generar_jwt(USUARIO)
r = cliente.get('/metrics')
revisar(r.status_code == 401, '/metrics sin token, 401', r.status_code)
r = cliente.get('/metrics', headers={'Authorization': 'Bearer ' + tok_lector})
revisar(r.status_code == 403, '/metrics con lector, 403', r.status_code)
servicio.metrica('login_correctos')
r = cliente.get('/metrics', headers={'Authorization': 'Bearer ' + tok_admin})
revisar(r.status_code == 200 and json.loads(r.data)['contadores'].get('login_correctos') == 1
        and 'falsa' not in r.get_data(as_text=True), '/metrics con admin, 200 y con contadores (sin exponer la contrasena)', r.status_code)
jti_a = jwt.decode(tok_admin, options={'verify_signature': False})['jti']
FALSO.setex('jwt:revoked:' + jti_a, 1200, '1')
r = cliente.get('/metrics', headers={'Authorization': 'Bearer ' + tok_admin})
revisar(r.status_code == 401, '/metrics con un JWT revocado, 401', r.status_code)
FALSO.caido = True
r = cliente.get('/metrics', headers={'Authorization': 'Bearer ' + servicio.generar_jwt(admin)})
revisar(r.status_code == 503, '/metrics con Redis caido, 503', r.status_code)
FALSO.caido = False

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
revisar({'/register', '/login', '/logout', '/session', '/health', '/metrics', '/token/refresh'} <= puntos,
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
