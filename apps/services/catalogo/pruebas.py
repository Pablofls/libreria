# -*- coding: utf-8 -*-
"""Pruebas de Redis en el catalogo (cache, invalidacion, revocacion), SIN base
de datos ni red: PostgreSQL y Redis se sustituyen por dobles en memoria.

    python3 pruebas.py
"""
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault('JWT_SECRET_KEY', 'clave-solo-para-las-pruebas-en-proceso')
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

fallos, hechas = [], 0


def revisar(condicion, descripcion, extra=''):
    global hechas
    hechas += 1
    print('  {} {} {}'.format('ok  ' if condicion else 'FALLA', descripcion,
                              '' if condicion else extra))
    if not condicion:
        fallos.append(descripcion)


LIBRO = {'isbn': '9780132350884', 'titulo': 'Clean Code', 'anio_publicacion': 2008,
         'generos': ['Programacion'], 'precio': Decimal('49.90'), 'stock': 7,
         'formato': 'Pasta dura', 'autores': [], 'imagenes': [], 'conceptos': []}
llamadas_bd = {'n': 0}


class CursorFalso:
    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return {'isbn': LIBRO['isbn'], 'titulo': LIBRO['titulo'], 'total': 1}


@contextmanager
def cursor_falso(escribe=False):
    llamadas_bd['n'] += 1
    yield CursorFalso()


servicio.cursor_bd = cursor_falso
servicio.leer_libros = lambda cur, *a, **k: [dict(LIBRO)]
servicio.buscar_por_isbn = lambda cur, isbn: dict(LIBRO) if isbn == LIBRO['isbn'] else None
cliente = servicio.app.test_client()


def token(rol='admin', **cambios):
    ahora = datetime.now(timezone.utc)
    reclamos = {'sub': '1', 'user_id': 1, 'role_id': 1 if rol == 'admin' else 2,
                'rol': rol, 'jti': uuid.uuid4().hex, 'iss': 'login-libreria',
                'iat': ahora, 'exp': ahora + timedelta(minutes=20)}
    reclamos.update(cambios)
    reclamos = {k: v for k, v in reclamos.items() if v is not None}
    return jwt.encode(reclamos, servicio.JWT_SECRET, algorithm='HS256')


def con(t):
    return {'Authorization': 'Bearer ' + t}


print('1. Cache de GET /books y GET /books/<isbn>')
r = cliente.get('/books?format=json')
revisar(r.status_code == 200 and r.headers['X-Cache'] == 'MISS', 'primera lectura: MISS, va a PostgreSQL', r.headers)
revisar(llamadas_bd['n'] == 1, 'una consulta a la base', llamadas_bd)
cuerpo1 = r.data
r = cliente.get('/books?format=json')
revisar(r.headers['X-Cache'] == 'HIT' and llamadas_bd['n'] == 1, 'segunda lectura: HIT, sin tocar la base')
revisar(r.data == cuerpo1, 'el cuerpo cacheado es identico al de la base')
r = cliente.get('/books?format=xml')
revisar(r.headers['X-Cache'] == 'HIT' and b'<price>49.90</price>' in r.data and r.mimetype == 'application/xml',
        'la misma entrada sirve XML (un solo cache para los dos formatos)')
revisar('books:list:todos:0:l.titulo:ASC' in FALSO.datos, 'clave books:list:<filtros>')
revisar(FALSO.ttls['books:list:todos:0:l.titulo:ASC'] == servicio.CACHE_TTL <= 300, 'con TTL corto')
cliente.get('/books?limite=5&orden=precio&dir=desc&format=json')
revisar('books:list:5:0:l.precio:DESC' in FALSO.datos, 'otros filtros, otra clave')
r = cliente.get('/books/' + LIBRO['isbn'] + '?format=json')
revisar(r.headers['X-Cache'] == 'MISS' and ('books:' + LIBRO['isbn']) in FALSO.datos, 'GET /books/<isbn>: MISS y clave books:<isbn>')
r = cliente.get('/books/' + LIBRO['isbn'] + '?format=json')
revisar(r.headers['X-Cache'] == 'HIT', 'y luego HIT')
r = cliente.get('/books/0000000000000?format=json')
revisar(r.status_code == 404 and 'books:0000000000000' not in FALSO.datos, 'un 404 no se cachea')

print('2. Invalidacion tras escribir')
llamadas_bd['n'] = 0
admin = token('admin')
r = cliente.delete('/books/delete/' + LIBRO['isbn'], headers=con(admin))
revisar(r.status_code == 200, 'DELETE con admin, 200', r.status_code)
revisar(not [k for k in FALSO.datos if k.startswith('books:')], 'se borran books:list:* y books:<isbn>')
r = cliente.get('/books?format=json')
revisar(r.headers['X-Cache'] == 'MISS', 'la siguiente lectura vuelve a PostgreSQL')
r = cliente.delete('/books/delete/' + LIBRO['isbn'], headers=con(token('lector')))
revisar(r.status_code == 403, 'un lector no escribe, 403', r.status_code)
revisar(any(k.startswith('books:') for k in FALSO.datos), 'y un intento rechazado no invalida nada')

print('3. Revocacion de JWT en las escrituras')
t = token('admin')
jti = jwt.decode(t, options={'verify_signature': False})['jti']
FALSO.setex('jwt:revoked:' + jti, 1200, '1')
r = cliente.delete('/books/delete/' + LIBRO['isbn'], headers=con(t))
revisar(r.status_code == 401, 'token revocado, 401', r.status_code)
r = cliente.delete('/books/delete/' + LIBRO['isbn'], headers=con(token('admin', jti=None)))
revisar(r.status_code == 401, 'token sin jti, 401', r.status_code)
r = cliente.delete('/books/delete/' + LIBRO['isbn'])
revisar(r.status_code == 401, 'sin token, 401', r.status_code)

print('4. Caida de Redis')
FALSO.caido = True
r = cliente.get('/books?format=json')
revisar(r.status_code == 200 and r.headers['X-Cache'] == 'MISS',
        'lecturas: siguen sirviendose desde PostgreSQL (fallan abierto)', r.status_code)
r = cliente.get('/books/' + LIBRO['isbn'] + '?format=json')
revisar(r.status_code == 200, 'tambien GET /books/<isbn>', r.status_code)
revisar(servicio._errores_locales >= 1, 'y se cuenta el error de Redis')
r = cliente.delete('/books/delete/' + LIBRO['isbn'], headers=con(token('admin')))
revisar(r.status_code == 503 and r.headers.get('Retry-After'),
        'escrituras: sin poder comprobar la revocacion, 503 (fallan cerrado)', r.status_code)
r = cliente.get('/health?format=json')
revisar(json.loads(r.data)['redis'] == 'caido', '/health informa redis: caido')
FALSO.caido = False
r = cliente.get('/health?format=xml')
revisar(b'<redis>ok</redis>' in r.data, '/health en XML informa redis: ok al volver')

print('5. Metricas')
r = cliente.get('/metrics')
revisar(r.status_code == 401, '/metrics sin token, 401', r.status_code)
r = cliente.get('/metrics', headers=con(token('lector')))
revisar(r.status_code == 403, '/metrics con lector, 403', r.status_code)
r = cliente.get('/metrics', headers=con(token('admin')))
m = json.loads(r.data)['contadores']
revisar(r.status_code == 200 and m.get('cache_aciertos', 0) >= 3 and m.get('cache_fallos', 0) >= 3
        and m.get('revocaciones_consultadas', 0) >= 1 and m.get('invalidaciones_catalogo', 0) >= 1,
        '/metrics admin: aciertos, fallos, revocaciones e invalidaciones', m)

print('\n{} comprobaciones, {} fallos'.format(hechas, len(fallos)))
sys.exit(1 if fallos else 0)
