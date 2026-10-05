# -*- coding: utf-8 -*-
"""Pruebas de la capa de seguridad de authors, SIN base de datos ni red.

    python3 pruebas.py

Cubren lo que decide el servicio antes de tocar un dato: 401 sin token o con
token malo (firma, algoritmo, expiracion, emisor, claims), 403 con rol
insuficiente, CORS restringido y errores sin detalles internos. La logica con
SQL se prueba contra la VM con tests/pruebas_jwt.py.
"""
import os
import sys
import json
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault('JWT_SECRET_KEY', 'clave-solo-para-las-pruebas-en-proceso')
os.environ['CORS_ORIGENES'] = 'https://cliente.example.com'
os.environ['DB_HOST'] = '127.0.0.1'
os.environ['DB_PORT'] = '1'          # nada escucha: simula la base caida
os.environ['DB_TIMEOUT'] = '1'
os.environ['LOG_NIVEL'] = 'CRITICAL'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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

fallos, hechas = [], 0


def revisar(condicion, descripcion, extra=''):
    global hechas
    hechas += 1
    print('  {} {} {}'.format('ok  ' if condicion else 'FALLA', descripcion,
                                 '' if condicion else extra))
    if not condicion:
        fallos.append(descripcion)


def token(user_id=1, role_id=servicio.ROL_LECTOR, **cambios):
    ahora = datetime.now(timezone.utc)
    reclamos = {'sub': str(user_id), 'user_id': user_id, 'role_id': role_id,
                'jti': uuid.uuid4().hex, 'iss': 'login-libreria', 'iat': ahora,
                'exp': ahora + timedelta(minutes=20)}
    reclamos.update(cambios)
    reclamos = {k: v for k, v in reclamos.items() if v is not None}
    return jwt.encode(reclamos, servicio.JWT_SECRET, algorithm='HS256')


def con(t):
    return {'Authorization': 'Bearer ' + t}


cliente = servicio.app.test_client()
LECTOR, ADMIN = token(1, servicio.ROL_LECTOR), token(2, servicio.ROL_ADMIN)
RUTA, METODO, CUERPO = '/authors', 'POST', {}

print('1. 401: sin token o con token malo')
r = cliente.open(RUTA, method=METODO, json=CUERPO)
revisar(r.status_code == 401, 'sin Authorization, 401', r.status_code)
revisar(r.headers.get('WWW-Authenticate') == 'Bearer', 'y avisa WWW-Authenticate: Bearer')
revisar(b'Traceback' not in r.data and b'psycopg' not in r.data, 'sin detalles internos')
malos = {
    'firma de otra clave': jwt.encode({'user_id': 1, 'role_id': 2, 'iss': 'login-libreria',
        'exp': datetime.now(timezone.utc) + timedelta(minutes=5)}, 'otra-clave-cualquiera-de-32-bytes!!', algorithm='HS256'),
    'token vencido': token(exp=datetime.now(timezone.utc) - timedelta(seconds=5)),
    'emisor ajeno': token(iss='otro-emisor'),
    'sin role_id': token(role_id=None),
    'sin user_id': token(user_id=None),
    'role_id inexistente': token(role_id=99),
    'sin exp': token(exp=None),
    'sin jti': token(jti=None),
    'alg none': jwt.encode({'user_id': 2, 'role_id': 1, 'iss': 'login-libreria'}, None, algorithm='none'),
    'basura': 'no.es.un.jwt',
}
for nombre, t in malos.items():
    r = cliente.open(RUTA, method=METODO, json=CUERPO, headers=con(t))
    revisar(r.status_code == 401, 'token con {}, 401'.format(nombre), r.status_code)
r = cliente.open(RUTA, method=METODO, json=CUERPO, headers={'Authorization': 'Basic abc'})
revisar(r.status_code == 401, 'esquema distinto de Bearer, 401', r.status_code)

print('2. 403: token valido, rol insuficiente')
for metodo, ruta, cuerpo in [('POST', '/authors', {}), ('PUT', '/authors/1', {}), ('PATCH', '/authors/1', {'nombre': 'X'}), ('DELETE', '/authors/1', None), ('POST', '/authors/1/books/1', {}), ('DELETE', '/authors/1/books/1', None)]:
    r = cliente.open(ruta, method=metodo, json=cuerpo, headers=con(LECTOR))
    revisar(r.status_code == 403, 'lector en {} {}, 403'.format(metodo, ruta), r.status_code)
    r = cliente.open(ruta, method=metodo, json=cuerpo, headers=con(ADMIN))
    revisar(r.status_code not in (401, 403), 'admin en {} {} pasa la autorizacion'.format(metodo, ruta), r.status_code)

print('3. Las lecturas son publicas')
for ruta in ('/authors', '/authors/1', '/authors/1/books', '/authors/books'):
    r = cliente.get(ruta)
    revisar(r.status_code not in (401, 403), 'GET {} sin token no pide autenticacion'.format(ruta), r.status_code)

print('4. Redis: revocacion, caida y metricas')
t_ok = token(1)
r = cliente.open(RUTA, method=METODO, json=CUERPO, headers=con(t_ok))
revisar(r.status_code != 401, 'un token con jti no revocado pasa a la autorizacion', r.status_code)
jti = jwt.decode(t_ok, options={'verify_signature': False})['jti']
FALSO.setex('jwt:revoked:' + jti, 1200, '1')
r = cliente.open(RUTA, method=METODO, json=CUERPO, headers=con(t_ok))
revisar(r.status_code == 401, 'el mismo token, ya revocado en Redis, 401', r.status_code)
revisar(FALSO.ttl('jwt:revoked:' + jti) == 1200, 'la clave de revocacion lleva TTL')
FALSO.caido = True
r = cliente.open(RUTA, method=METODO, json=CUERPO, headers=con(token(1)))
revisar(r.status_code == 503, 'con Redis caido, un token valido da 503 (falla cerrado)', r.status_code)
revisar(r.headers.get('Retry-After') is not None, 'y pide reintentar', r.headers)
revisar(b'redis' not in r.data.lower() and b'Traceback' not in r.data, 'sin detalles internos en el 503')
r = cliente.open(RUTA, method=METODO, json=CUERPO)
revisar(r.status_code == 401, 'sin token sigue siendo 401 aunque Redis este caido', r.status_code)
r = cliente.get('/health')
revisar(json.loads(r.data)['redis'] == 'caido', '/health informa redis: caido')
FALSO.caido = False
r = cliente.get('/health')
revisar(json.loads(r.data)['redis'] == 'ok', 'y redis: ok cuando vuelve')
r = cliente.get('/metrics', headers=con(token(1, servicio.ROL_LECTOR)))
revisar(r.status_code == 403, '/metrics con lector, 403', r.status_code)
r = cliente.get('/metrics', headers=con(token(2, servicio.ROL_ADMIN)))
cuerpo_m = json.loads(r.data)
revisar(r.status_code == 200 and cuerpo_m['contadores'].get('revocaciones_consultadas', 0) >= 1
        and cuerpo_m['contadores'].get('tokens_revocados_rechazados', 0) >= 1,
        '/metrics con admin, 200 y con contadores', r.status_code)
revisar('falsa' not in r.get_data(as_text=True), 'las metricas no exponen la contrasena de Redis')
FALSO.caido = True
r = cliente.get('/metrics', headers=con(token(2, servicio.ROL_ADMIN)))
revisar(r.status_code == 503, '/metrics con Redis caido, 503', r.status_code)
FALSO.caido = False
FALSO.set('books:list:x', '[]', ex=60)
FALSO.set('books:978', '{}', ex=60)
servicio.invalidar_catalogo()
revisar(not FALSO.datos.get('books:list:x') and not FALSO.datos.get('books:978'),
        'invalidar_catalogo borra books:*')
FALSO.caido = True
try:
    servicio.invalidar_catalogo()
    revisar(True, 'con Redis caido, invalidar_catalogo no rompe la escritura (falla abierto)')
except Exception as e:
    revisar(False, 'invalidar_catalogo no debe propagar errores', e)
FALSO.caido = False


print('5. CORS, errores y salud')
r = cliente.options(RUTA, headers={'Origin': 'https://cliente.example.com',
                                   'Access-Control-Request-Method': METODO})
revisar(r.headers.get('Access-Control-Allow-Origin') == 'https://cliente.example.com',
        'CORS permite el origen configurado')
r = cliente.options(RUTA, headers={'Origin': 'https://intruso.example.net',
                                   'Access-Control-Request-Method': METODO})
revisar('Access-Control-Allow-Origin' not in r.headers, 'y no permite ningun otro origen')
revisar('*' not in servicio.CORS_ORIGENES, 'nunca "*"')
r = cliente.get('/no-existe')
revisar(r.status_code == 404 and json.loads(r.data)['codigo'] == 404, 'ruta desconocida, 404 en JSON')
r = cliente.get('/health')
revisar(r.status_code == 503 and json.loads(r.data)['estado'] == 'sin base de datos',
        'sin base, /health responde 503 sin colgarse', r.status_code)

print('\n{} comprobaciones, {} fallos'.format(hechas, len(fallos)))
sys.exit(1 if fallos else 0)
