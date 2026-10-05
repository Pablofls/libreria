# -*- coding: utf-8 -*-
"""Pruebas de cliente/api_rest.py contra un servidor HTTP de mentira, SIN
pantalla, sin red externa y sin dependencias: solo biblioteca estandar.

    python3 tests/pruebas_cliente_rest.py        (desde apps/services/soap)

Cubren lo que decide el cliente: login, renovacion del JWT ANTES de caducar,
un solo reintento ante 401, traduccion de 403/409/503 a mensajes, logout que no
finge exito, y los semaforos (verde / amarillo si Redis cae / rojo).
La parte visual se prueba a mano abriendo la aplicacion.
"""
import base64
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'cliente'))
import api_rest                                                   # noqa: E402

fallos, hechas = [], 0


def revisar(condicion, descripcion, extra=''):
    global hechas
    hechas += 1
    print('  {} {} {}'.format('ok  ' if condicion else 'FALLA', descripcion,
                              '' if condicion else extra))
    if not condicion:
        fallos.append(descripcion)


def jwt_falso(segundos, rol='lector', user_id=7):
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b'=').decode()
    return '{}.{}.firma'.format(b64({'alg': 'HS256'}), b64(
        {'user_id': user_id, 'rol': rol, 'exp': time.time() + segundos,
         'jti': 'jti%08d' % int(time.time() * 1000 % 10**8)}))


ESTADO = {}


def reiniciar(**kw):
    ESTADO.clear()
    ESTADO.update({'vida_jwt': 1200, 'visto': [], 'refresh_llamadas': 0,
                   'revocados': set(), 'refresh_vigente': None, 'respuestas': {},
                   'rol': 'lector', 'logout_status': 200, 'refresh_status': None,
                   'health': {}})
    ESTADO.update(kw)


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _responder(self, estado, cuerpo=None):
        crudo = json.dumps(cuerpo).encode() if cuerpo is not None else b''
        self.send_response(estado)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)

    def _cuerpo(self):
        n = int(self.headers.get('Content-Length') or 0)
        return json.loads(self.rfile.read(n)) if n else {}

    def _emitir(self):
        token = jwt_falso(ESTADO['vida_jwt'], ESTADO['rol'])
        ESTADO['refresh_vigente'] = 'refresh%d' % (ESTADO['refresh_llamadas'] + 1)
        ESTADO['ultimo_token'] = token
        return {'autenticada': True, 'token': token,
                'refresh_token': ESTADO['refresh_vigente'],
                'usuario': {'id': 7, 'nombre': 'Ana', 'email': 'ana@x.mx',
                            'rol': ESTADO['rol']}}

    def atender(self, metodo):
        ruta = self.path
        ESTADO['visto'].append((metodo, ruta, self.headers.get('Authorization')))
        base = ruta.split('?')[0]
        if base == '/login':
            cuerpo = self._cuerpo()
            if cuerpo.get('password') != 'buena':
                return self._responder(401, {'codigo': 401, 'mensaje': 'Correo o contrasena incorrectos.'})
            return self._responder(200, self._emitir())
        if base == '/token/refresh':
            ESTADO['refresh_llamadas'] += 1
            if ESTADO['refresh_status']:
                return self._responder(ESTADO['refresh_status'], {'mensaje': 'x'})
            if self._cuerpo().get('refresh_token') != ESTADO['refresh_vigente']:
                return self._responder(401, {'mensaje': 'Refresh token invalido, usado o vencido.'})
            ESTADO['revocados'].add(ESTADO.get('ultimo_token'))
            return self._responder(200, self._emitir())
        if base == '/logout':
            if ESTADO['logout_status'] != 200:
                return self._responder(ESTADO['logout_status'], {'mensaje': 'sin redis'})
            return self._responder(200, {'ok': True})
        if base.startswith('/health/'):
            servicio = base.split('/')[-1]
            estado, cuerpo = ESTADO['health'].get(servicio, (200, {'estado': 'ok', 'redis': 'ok'}))
            return self._responder(estado, cuerpo)
        if base.startswith('/uploads/'):
            cuerpo = b'\x89PNG' + b'x' * (3_000_000 if 'grande' in base else 20)
            self.send_response(200 if 'falta' not in base else 404)
            self.send_header('Content-Length', str(len(cuerpo)))
            self.end_headers()
            return self.wfile.write(cuerpo)
        # rutas de datos: exigen un JWT no revocado
        token = (self.headers.get('Authorization') or '')[7:]
        if token in ESTADO['revocados'] or not token:
            return self._responder(401, {'codigo': 401, 'mensaje': 'Esta operacion requiere un token valido.'})
        respuesta = ESTADO['respuestas'].get(base)
        if respuesta:
            return self._responder(*respuesta)
        return self._responder(200, [{'id': 1}])

    do_GET = lambda self: self.atender('GET')       # noqa: E731
    do_POST = lambda self: self.atender('POST')     # noqa: E731
    do_PUT = lambda self: self.atender('PUT')       # noqa: E731
    do_PATCH = lambda self: self.atender('PATCH')   # noqa: E731
    do_DELETE = lambda self: self.atender('DELETE') # noqa: E731


servidor = HTTPServer(('127.0.0.1', 0), Manejador)
threading.Thread(target=servidor.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:%d' % servidor.server_port


def nuevo():
    return api_rest.ClienteApi(base=BASE)


print('1. Login y sesion')
reiniciar()
c = nuevo()
revisar(not c.sesion_activa, 'sin login no hay sesion')
usuario = c.iniciar_sesion('ana@x.mx', 'buena')
revisar(c.sesion_activa and usuario['rol'] == 'lector' and usuario['id'] == 7, 'login ok: sesion, rol e id del token')
revisar(not c.es_admin, 'un lector no es admin')
revisar(1100 < c.segundos_restantes() <= 1200, 'sabe cuando vence el JWT (20 min)', c.segundos_restantes())
revisar(any(v[1] == '/login?format=json' for v in ESTADO['visto']), 'pide JSON al login (?format=json)')
c2 = nuevo()
try:
    c2.iniciar_sesion('ana@x.mx', 'mala')
    revisar(False, 'una contrasena mala debe fallar')
except api_rest.ErrorApi as e:
    revisar(e.estado == 401 and 'incorrectos' in e.mensaje and not c2.sesion_activa,
            'contrasena mala: ErrorApi 401 con el mensaje del servidor, sin sesion')

print('2. Peticiones autenticadas')
reiniciar()
c = nuevo(); c.iniciar_sesion('ana@x.mx', 'buena')
datos = c.get('/orders')
revisar(datos == [{'id': 1}] and ESTADO['visto'][-1][2] == 'Bearer ' + c.token, 'GET manda Authorization: Bearer <jwt>')
revisar(ESTADO['visto'][-1][1] == '/orders', 'las rutas que no son login/catalogo no llevan ?format')
c.get('/books?limite=3')
revisar(ESTADO['visto'][-1][1] == '/books?limite=3&format=json', 'el catalogo pide JSON (&format=json)')
try:
    nuevo().get('/orders')
    revisar(False, 'sin sesion no se hace la peticion')
except api_rest.ErrorApi as e:
    revisar(e.estado == 401, 'sin sesion: ErrorApi 401 sin tocar la red')
llamadas = len(ESTADO['visto'])
for estado, texto in ((403, 'permiso'), (404, 'ya no existe'), (503, 'no esta disponible')):
    ESTADO['respuestas']['/orders'] = (estado, {})
    try:
        c.get('/orders')
        revisar(False, 'debe fallar')
    except api_rest.ErrorApi as e:
        revisar(e.estado == estado and texto in e.mensaje, '{} se traduce a un mensaje en castellano'.format(estado), e.mensaje)
ESTADO['respuestas']['/orders'] = (409, {'mensaje': 'El pedido esta cancelado.', 'detalles': ['uno', 'dos']})
try:
    c.get('/orders')
except api_rest.ErrorApi as e:
    revisar(e.mensaje == 'El pedido esta cancelado.' and e.detalles == ['uno', 'dos'] and 'uno' in e.texto(),
            '409 muestra el mensaje y los detalles del servidor')

print('3. Renovacion automatica, antes de caducar')
reiniciar(vida_jwt=30)          # vence en 30 s: dentro del margen de 60 s
c = nuevo(); c.iniciar_sesion('ana@x.mx', 'buena')
primero = c.token
ESTADO['vida_jwt'] = 1200
c.get('/orders')
revisar(ESTADO['refresh_llamadas'] == 1 and c.token != primero,
        'con menos de 60 s de vida, renueva ANTES de la peticion', ESTADO['refresh_llamadas'])
revisar(ESTADO['visto'][-1][2] == 'Bearer ' + c.token, 'y la peticion usa el JWT nuevo')
c.get('/orders')
revisar(ESTADO['refresh_llamadas'] == 1, 'con JWT nuevo (20 min) ya no renueva de mas')
revisar(c.renovar_si_hace_falta() is True and ESTADO['refresh_llamadas'] == 1, 'renovar_si_hace_falta no hace nada si no toca')

print('4. 401 en el camino: una renovacion y un solo reintento')
reiniciar()
c = nuevo(); c.iniciar_sesion('ana@x.mx', 'buena')
ESTADO['revocados'].add(c.token)                 # el servidor lo revoca
antes = ESTADO['refresh_llamadas']
datos = c.get('/orders')
revisar(datos == [{'id': 1}] and ESTADO['refresh_llamadas'] == antes + 1,
        'ante un 401 renueva una vez y reintenta con exito')
reiniciar()
c = nuevo(); c.iniciar_sesion('ana@x.mx', 'buena')
ESTADO['revocados'].add(c.token)
ESTADO['refresh_vigente'] = 'otro'               # el refresh ya no vale
try:
    c.get('/orders')
    revisar(False, 'sin refresh valido debe fallar')
except api_rest.ErrorApi as e:
    revisar(e.estado == 401 and not c.sesion_activa, 'si el refresh tampoco vale: 401 y la sesion se olvida')
reiniciar(refresh_status=503)
c = nuevo(); c.iniciar_sesion('ana@x.mx', 'buena')
ESTADO['revocados'].add(c.token)
try:
    c.get('/orders')
    revisar(False, 'debe fallar')
except api_rest.ErrorApi as e:
    revisar(e.estado == 503 and c.sesion_activa, 'si renovar da 503 (Redis caido) la sesion NO se pierde: se puede reintentar')

print('5. Logout no finge exito')
reiniciar()
c = nuevo(); c.iniciar_sesion('ana@x.mx', 'buena')
c.cerrar_sesion()
revisar(not c.sesion_activa and c.refresh is None and c.usuario is None, 'logout ok: se olvida todo')
reiniciar(logout_status=503)
c = nuevo(); c.iniciar_sesion('ana@x.mx', 'buena')
try:
    c.cerrar_sesion()
    revisar(False, 'con 503 debe avisar')
except api_rest.ErrorApi as e:
    revisar(e.estado == 503 and c.sesion_activa, 'logout con 503: avisa y conserva la sesion (seguiria viva en el servidor)')

print('6. Semaforos')
reiniciar()
c = nuevo()
revisar(c.semaforo('users')[0] == 'verde', 'ok + redis ok = verde')
ESTADO['health']['users'] = (200, {'estado': 'ok', 'redis': 'caido'})
color, detalle, redis = c.semaforo('users')
revisar(color == 'amarillo' and redis == 'caido', 'ok + Redis caido = amarillo (degradado)', color)
ESTADO['health']['pagos'] = (200, {'estado': 'ok', 'redis': 'no configurado'})
revisar(c.semaforo('pagos')[0] == 'amarillo', 'Redis sin configurar tambien es amarillo')
ESTADO['health']['authors'] = (503, {'estado': 'sin base de datos', 'redis': 'ok'})
revisar(c.semaforo('authors')[0] == 'rojo', 'base de datos caida (503) = rojo')
ESTADO['health']['catalogo'] = (200, {'status': 'ok', 'redis': 'ok', 'books': 5})
revisar(c.semaforo('catalogo')[0] == 'verde', 'el catalogo habla de status, no de estado: tambien verde')
ESTADO['health']['login'] = (200, {'estado': 'ok', 'componentes': {'redis': {'estado': 'ok'}}})
revisar(c.semaforo('login')[0] == 'verde', 'login anida redis en componentes: verde')
ESTADO['health']['login'] = (200, {'estado': 'ok', 'componentes': {'redis': {'estado': 'degradado', 'detalle': 'Redis no responde.'}}})
color, _, redis = c.semaforo('login')
revisar(color == 'amarillo' and redis == 'caido', 'login con Redis degradado: amarillo')
muerto = api_rest.ClienteApi(base='http://127.0.0.1:1')
revisar(muerto.semaforo('users')[0] == 'rojo', 'sin respuesta = rojo')
try:
    muerto.get('/orders', autenticada=False)
except api_rest.ErrorApi as e:
    revisar(e.estado == 0 and 'conectar' in e.mensaje and 'Traceback' not in e.mensaje, 'sin red: mensaje claro, no una excepcion de urllib')
revisar(api_rest.probar_tcp(BASE) is True and api_rest.probar_tcp('http://127.0.0.1:1') is False, 'probar_tcp (semaforo del SOAP)')

print('7. Portadas (recursos publicos)')
c = nuevo()
revisar(c.descargar('/uploads/a.png').startswith(b'\x89PNG'), 'descarga una portada sin JWT')
revisar(not [v for v in ESTADO['visto'] if v[1] == '/uploads/a.png' and v[2]], 'y no manda Authorization')
for ruta, texto in (('/uploads/falta.png', 'no se encontro'), ('/uploads/grande.png', 'demasiado grande')):
    try:
        c.descargar(ruta)
        revisar(False, 'debe fallar ' + ruta)
    except api_rest.ErrorApi as e:
        revisar(texto in e.mensaje.lower(), '{}: ErrorApi con mensaje claro'.format(ruta), e.mensaje)
try:
    api_rest.ClienteApi(base='http://127.0.0.1:1').descargar('/uploads/a.png')
except api_rest.ErrorApi as e:
    revisar(e.estado == 0, 'sin red: ErrorApi(0), no una excepcion de urllib')

print('8. Seguridad')
c = nuevo()
revisar(isinstance(c._contexto, type(None)), 'http de prueba: sin contexto TLS')
https = api_rest.ClienteApi(base='https://127.0.0.1:1')
revisar(https._contexto is not None and https._contexto.verify_mode.name == 'CERT_REQUIRED' and https._contexto.check_hostname,
        'con https se VERIFICA el certificado y el nombre')
revisar('CERT_NONE' not in open(api_rest.__file__, encoding='utf-8').read().replace("'CERT_NONE' not in", ''),
        'el codigo nunca desactiva la verificacion')
reiniciar()
c = nuevo(); c.iniciar_sesion('ana@x.mx', 'buena')
revisar(c.token not in repr(vars(api_rest)) and 'buena' not in repr(vars(c)), 'la contrasena no se conserva')

print('\n{} comprobaciones, {} fallos'.format(hechas, len(fallos)))
servidor.shutdown()
sys.exit(1 if fallos else 0)
