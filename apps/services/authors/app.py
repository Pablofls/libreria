# -*- coding: utf-8 -*-
"""Microservicio de autores de la Libreria Online.

    GET    /authors, /authors/<id>, /authors/<id>/books, /authors/books  publicos
    POST   /authors                                          (admin)
    PUT | PATCH | DELETE /authors/<id>                       (admin)
    POST | PUT | DELETE /authors/<id>/books/<libro_id>       (admin) relacion
    GET    /health

Servicio, no aplicacion web: solo JSON. Comparte la base PostgreSQL con el
monolito y los demas servicios y se conecta como libreria_app.

Autenticacion: JWT HS256 emitido por apps/services/login (20 minutos, claims
user_id y role_id), verificado aqui con JWT_SECRET_KEY, el mismo valor en todos
los .env. 401 sin token valido; 403 con rol insuficiente.

    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    python3 app.py                    # -> http://127.0.0.1:5004/health
"""
import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation  # noqa: F401
from functools import wraps

import jwt
import psycopg
import redis
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout
from werkzeug.exceptions import HTTPException

load_dotenv()

logging.basicConfig(
    level=os.getenv('LOG_NIVEL', 'INFO').upper(),
    format='%(asctime)s %(levelname)s [authors] %(message)s')
log = logging.getLogger('authors')

VERSION = '1.0.0'

# -----------------------------------------------------------------------------
# Configuracion. Todo sale del entorno; ningun valor sensible tiene default.
# -----------------------------------------------------------------------------
BD = {
    'host':    os.getenv('DB_HOST', '127.0.0.1'),
    'port':    os.getenv('DB_PORT', '5432'),
    'dbname':  os.getenv('DB_NAME', 'libreria_db'),
    'user':    os.getenv('DB_USER', 'libreria_app'),
    'password': os.getenv('DB_PASSWORD', ''),
}
BD_TIMEOUT = int(os.getenv('DB_TIMEOUT', '5'))

APP_HOST = os.getenv('AUTHORS_HOST', '0.0.0.0')
APP_PORT = int(os.getenv('AUTHORS_PORT', '5004'))

# Secreto COMPARTIDO con login y con el resto de servicios: es el que firma y
# el que verifica. Sin valor por omision: un default en un repositorio publico
# dejaria falsificar tokens de cualquier usuario, administrador incluido.
JWT_SECRET = (os.getenv('JWT_SECRET_KEY') or os.getenv('JWT_SECRET') or '').strip()
if not JWT_SECRET:
    raise RuntimeError(
        'Falta JWT_SECRET_KEY. Debe ser el mismo valor que en el .env de login '
        '(python3 -c "import secrets; print(secrets.token_urlsafe(48))"). '
        'El servicio no arranca sin el.')
# La lista va fija: el algoritmo NUNCA se toma del token. Es lo que impide que
# un token con "alg":"none" se cuele.
JWT_ALGORITMOS = ['HS256']
JWT_EMISOR = 'login-libreria'

# role_id del JWT, igual que ROLES_ID de apps/services/login.
ROL_ADMIN = 1
ROL_LECTOR = 2

# Origenes de las aplicaciones cliente en produccion, separados por comas.
# Vacio = ningun origen cruzado permitido. Nunca "*".
CORS_ORIGENES = [o.strip() for o in os.getenv('CORS_ORIGENES', '').split(',')
                 if o.strip() and o.strip() != '*']

app = Flask(__name__)
app.json.ensure_ascii = False
app.json.sort_keys = False


def _a_json(valor):
    # Fechas en ISO 8601 y dinero como numero, no como cadena HTTP ni texto.
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return float(valor)
    raise TypeError(type(valor).__name__)


app.json.default = _a_json
CORS(app, origins=CORS_ORIGENES,
     methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
     allow_headers=['Content-Type', 'Authorization'], max_age=86400)

_pool = None


def _obtener_pool():
    """Pool perezoso: /health debe responder aunque PostgreSQL no este."""
    global _pool
    if _pool is None:
        conninfo = ' '.join(
            '{}={}'.format(clave, valor) for clave, valor in BD.items() if valor)
        _pool = ConnectionPool(
            conninfo + ' connect_timeout={}'.format(BD_TIMEOUT),
            min_size=1, max_size=int(os.getenv('DB_POOL_MAX', '8')),
            kwargs={'row_factory': dict_row}, open=True, timeout=BD_TIMEOUT)
        log.info('Pool creado contra %s:%s/%s', BD['host'], BD['port'], BD['dbname'])
    return _pool


def conexion():
    """`with conexion() as con:` -> transaccion; confirma al salir, revierte si falla."""
    return _obtener_pool().connection()


# -----------------------------------------------------------------------------
# Respuestas y errores. Salida siempre JSON. Nunca sale de aqui el texto de una
# excepcion: puede llevar SQL, nombres de tabla o datos de otra persona.
# -----------------------------------------------------------------------------
def error_respuesta(codigo, mensaje, detalles=None):
    cuerpo = jsonify({'codigo': codigo, 'mensaje': mensaje, 'detalles': detalles or []})
    cuerpo.status_code = codigo
    if codigo == 401:
        cuerpo.headers['WWW-Authenticate'] = 'Bearer'
    return cuerpo


@app.errorhandler(404)
def _no_encontrado(_error):
    return error_respuesta(404, 'El recurso solicitado no existe.')


@app.errorhandler(405)
def _metodo_no_permitido(_error):
    return error_respuesta(405, 'Ese metodo HTTP no esta permitido en esta ruta.')


@app.errorhandler(PoolTimeout)
@app.errorhandler(psycopg.OperationalError)
def _sin_base(error):
    log.error('Sin conexion con PostgreSQL: %s', error)
    return error_respuesta(503, 'El servicio no puede conectarse a su base de datos.')


@app.errorhandler(psycopg.errors.UniqueViolation)
def _duplicado(error):
    log.info('Violacion de unicidad: %s', error.diag.constraint_name)
    return error_respuesta(409, 'Ya existe un registro con esos datos.')


@app.errorhandler(psycopg.errors.ForeignKeyViolation)
def _llave_foranea(error):
    log.info('Violacion de llave foranea: %s', error.diag.constraint_name)
    return error_respuesta(409, 'La operacion choca con registros relacionados.')


@app.errorhandler(psycopg.errors.CheckViolation)
def _restriccion(error):
    log.info('Restriccion rechazo un dato: %s', error.diag.constraint_name)
    return error_respuesta(400, 'Los datos enviados no son validos.')


@app.errorhandler(Exception)
def _fallo_inesperado(error):
    if isinstance(error, HTTPException):
        return error_respuesta(error.code or 500, 'La solicitud no se pudo atender.')
    log.exception('Fallo no controlado: %s', type(error).__name__)
    return error_respuesta(500, 'Ocurrio un error al procesar la solicitud.')


# -----------------------------------------------------------------------------
# Redis: capa compartida (revocacion de JWT, cache, metricas). PostgreSQL sigue
# siendo la fuente de datos; Redis nunca guarda nada que no pueda perderse.
#
# POLITICA ANTE UNA CAIDA, que es lo que pide el ejercicio:
#   - Revocacion y autorizacion FALLAN CERRADO: si no se puede comprobar que un
#     token no esta revocado, no se acepta (503). Nunca "por si acaso".
#   - Las lecturas cacheadas FALLAN ABIERTO: se sirven desde PostgreSQL.
# La URL (con la contrasena) sale de REDIS_URL, del .env; en los logs se enmascara.
# -----------------------------------------------------------------------------
REDIS_URL = os.getenv('REDIS_URL', '').strip()
REDIS_TIMEOUT = float(os.getenv('REDIS_TIMEOUT', '1.5'))
CACHE_TTL = int(os.getenv('CACHE_TTL_SEGUNDOS', '60'))
SERVICIO = 'authors'


class RedisNoDisponible(Exception):
    """Redis no esta configurado o no responde a tiempo."""


_redis = None
_errores_locales = 0     # por proceso: sigue contando aunque Redis este caido


def _url_enmascarada(url):
    return re.sub(r'(://[^:@/]*:)[^@]*@', r'\1***@', url)


def redis_cliente():
    global _redis
    if not REDIS_URL:
        raise RedisNoDisponible('REDIS_URL no esta configurada')
    if _redis is None:
        _redis = redis.Redis.from_url(
            REDIS_URL, socket_timeout=REDIS_TIMEOUT,
            socket_connect_timeout=REDIS_TIMEOUT, health_check_interval=30,
            decode_responses=True)
        log.info('Cliente Redis creado (%s)', _url_enmascarada(REDIS_URL))
    return _redis


def redis_op(funcion):
    """Ejecuta funcion(cliente). Cualquier fallo de Redis -> RedisNoDisponible."""
    global _errores_locales
    try:
        return funcion(redis_cliente())
    except redis.RedisError as error:
        _errores_locales += 1
        log.error('Redis no disponible: %s', type(error).__name__)
        raise RedisNoDisponible() from error


def metrica(nombre, cantidad=1):
    """Contador compartido entre workers. Si Redis falla, no pasa nada."""
    try:
        redis_cliente().incrby('metrics:{}:{}'.format(SERVICIO, nombre), cantidad)
    except (redis.RedisError, RedisNoDisponible):
        pass


@app.errorhandler(RedisNoDisponible)
def _redis_caido(_error):
    respuesta = error_respuesta(
        503, 'No se puede verificar la sesion en este momento. Intenta de nuevo.')
    respuesta.headers['Retry-After'] = '5'
    return respuesta


def revocado(jti):
    """True si el jti esta en la lista de revocacion jwt:revoked:<jti>."""
    metrica('revocaciones_consultadas')
    if redis_op(lambda c: c.exists('jwt:revoked:' + jti)):
        metrica('tokens_revocados_rechazados')
        return True
    return False


def estado_redis():
    if not REDIS_URL:
        return 'no configurado'
    try:
        redis_cliente().ping()
        return 'ok'
    except redis.RedisError:
        return 'caido'


def invalidar_catalogo():
    """Borra books:* tras escribir algo que se ve en el catalogo. Falla abierto:
    si Redis no responde, lo viejo caduca solo en CACHE_TTL_SEGUNDOS."""
    if not REDIS_URL:
        return
    try:
        cliente = redis_cliente()
        claves = list(cliente.scan_iter(match='books:*', count=200))
        if claves:
            cliente.unlink(*claves)
        metrica('invalidaciones_catalogo')
    except redis.RedisError as error:
        log.warning('No se pudo invalidar la cache del catalogo: %s',
                    type(error).__name__)


# -----------------------------------------------------------------------------
# Autenticacion y autorizacion con el JWT que emite apps/services/login.
#   401: token ausente, mal firmado, vencido o sin los claims esperados.
#   403: token valido, pero el rol no alcanza.
# El token se verifica entero ANTES de tocar datos: firma, algoritmo,
# expiracion, emisor y claims. Nunca se escribe el token en los logs.
# -----------------------------------------------------------------------------
def reclamos_jwt():
    cabecera = request.headers.get('Authorization', '')
    if not cabecera.startswith('Bearer '):
        return None
    token = cabecera[7:].strip()
    if not token:
        return None
    try:
        reclamos = jwt.decode(
            token, JWT_SECRET, algorithms=JWT_ALGORITMOS, issuer=JWT_EMISOR,
            options={'require': ['exp', 'iss', 'user_id', 'role_id', 'jti']})
    except jwt.PyJWTError:
        return None
    user_id, role_id, jti = reclamos['user_id'], reclamos['role_id'], reclamos['jti']
    if (isinstance(user_id, bool) or not isinstance(user_id, int)
            or role_id not in (ROL_ADMIN, ROL_LECTOR)
            or not isinstance(jti, str) or not 8 <= len(jti) <= 64):
        return None
    # Ultimo control: que el token no haya sido revocado (logout). Si Redis no
    # responde, RedisNoDisponible sube hasta el handler y responde 503.
    if revocado(jti):
        return None
    return reclamos


def requiere_jwt(*roles):
    """Exige un JWT valido; con `roles`, ademas que role_id este entre ellos.

    Deja `g.user_id` y `g.role_id` para el handler.
    """
    def decorador(funcion):
        @wraps(funcion)
        def interno(*args, **kwargs):
            reclamos = reclamos_jwt()
            if reclamos is None:
                return error_respuesta(
                    401, 'Esta operacion requiere un token valido.',
                    ['Authorization: Bearer <JWT>'])
            if roles and reclamos['role_id'] not in roles:
                return error_respuesta(
                    403, 'Tu rol no permite esta operacion.')
            g.user_id = reclamos['user_id']
            g.role_id = reclamos['role_id']
            return funcion(*args, **kwargs)
        return interno
    return decorador


def es_admin():
    return g.role_id == ROL_ADMIN


# -----------------------------------------------------------------------------
# Entrada
# -----------------------------------------------------------------------------
class DatosInvalidos(Exception):
    def __init__(self, errores):
        super().__init__('datos invalidos')
        self.errores = errores


@app.errorhandler(DatosInvalidos)
def _datos_invalidos(error):
    return error_respuesta(400, 'Los datos enviados no son validos.', error.errores)


class Conflicto(Exception):
    """La peticion es valida pero choca con el estado actual: 409."""
    def __init__(self, mensaje):
        super().__init__(mensaje)
        self.mensaje = mensaje


@app.errorhandler(Conflicto)
def _conflicto(error):
    return error_respuesta(409, error.mensaje)


def cuerpo_json():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        raise DatosInvalidos(['El cuerpo debe ser un objeto JSON.'])
    return datos


def texto(valor):
    return valor.strip() if isinstance(valor, str) else ''


def entero_positivo(valor):
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
        return None
    return valor


@app.route('/health', methods=['GET'])
def salud():
    # Redis no es dependencia dura de la salud: caido, el servicio sigue "ok"
    # pero degradado (la app de escritorio lo pinta en amarillo).
    cuerpo = {'servicio': 'authors', 'version': VERSION, 'estado': 'ok',
              'redis': estado_redis()}
    try:
        with conexion() as con:
            con.execute('SELECT 1')
    except psycopg.Error:
        cuerpo['estado'] = 'sin base de datos'
        return jsonify(cuerpo), 503
    return jsonify(cuerpo)


@app.route('/metrics', methods=['GET'])
@requiere_jwt(ROL_ADMIN)
def metricas():
    """Contadores compartidos entre workers (en Redis) y estado de Redis."""
    prefijo = 'metrics:{}:'.format(SERVICIO)
    contadores = {}

    def leer(cliente):
        for clave in cliente.scan_iter(match=prefijo + '*'):
            contadores[clave[len(prefijo):]] = int(cliente.get(clave) or 0)

    redis_op(leer)
    return jsonify({'servicio': SERVICIO, 'redis': estado_redis(),
                    'errores_redis_en_este_proceso': _errores_locales,
                    'contadores': contadores})


@app.after_request
def _invalidar_cache_catalogo(respuesta):
    """Lo que escribe este servicio se ve en el catalogo (autores, stock): tras
    cualquier escritura correcta se borra books:* para no servir datos viejos."""
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and respuesta.status_code < 400:
        invalidar_catalogo()
    return respuesta


# =============================================================================
# Autores y su relacion con libros
#
# Lecturas: publicas (solo consultan informacion del catalogo).
# Escrituras (POST, PUT, PATCH, DELETE): JWT de administrador.
# SQL tomado de apps/web-monolito/src/modules/autores/autores.model.js.
# =============================================================================
LIMITE_NOMBRE = 120
LIMITE_NACIONALIDAD = 80
LIMITE_BIOGRAFIA = 5000


def _validar_autor(datos, parcial):
    errores, campos = [], {}
    if 'nombre' in datos or not parcial:
        nombre = texto(datos.get('nombre'))
        if not nombre:
            errores.append('El nombre es obligatorio.')
        elif len(nombre) > LIMITE_NOMBRE:
            errores.append('El nombre no puede pasar de {} caracteres.'
                           .format(LIMITE_NOMBRE))
        campos['nombre'] = nombre
    for clave, etiqueta, limite in (
            ('biografia', 'La biografia', LIMITE_BIOGRAFIA),
            ('nacionalidad', 'La nacionalidad', LIMITE_NACIONALIDAD)):
        if clave in datos or not parcial:
            valor = datos.get(clave)
            if valor is not None and not isinstance(valor, str):
                errores.append('{} debe ser texto.'.format(etiqueta))
            else:
                valor = texto(valor) or None
                if valor and len(valor) > limite:
                    errores.append('{} no puede pasar de {} caracteres.'
                                   .format(etiqueta, limite))
                campos[clave] = valor
    return campos, errores


@app.route('/authors', methods=['GET'])
def listar_autores():
    with conexion() as con:
        filas = con.execute("""
            SELECT a.id, a.nombre, a.nacionalidad, a.biografia,
                   count(la.libro_id)::int AS libros
            FROM autores a LEFT JOIN libros_autores la ON la.autor_id = a.id
            GROUP BY a.id ORDER BY a.nombre""").fetchall()
    return jsonify(filas)


@app.route('/authors/books', methods=['GET'])
def libros_vinculables():
    """Libros (id, isbn, titulo) a los que se puede acreditar un autor. El
    catalogo no expone el id numerico; el vinculo lo pide."""
    with conexion() as con:
        filas = con.execute(
            'SELECT id, isbn, titulo FROM libros ORDER BY titulo, id').fetchall()
    return jsonify(filas)


@app.route('/authors/<int:autor_id>', methods=['GET'])
def ver_autor(autor_id):
    with conexion() as con:
        fila = con.execute(
            'SELECT id, nombre, nacionalidad, biografia FROM autores WHERE id = %s',
            (autor_id,)).fetchone()
    if not fila:
        return error_respuesta(404, 'El autor no existe.')
    return jsonify(fila)


@app.route('/authors/<int:autor_id>/books', methods=['GET'])
def libros_de_autor(autor_id):
    with conexion() as con:
        if not con.execute('SELECT 1 FROM autores WHERE id = %s', (autor_id,)).fetchone():
            return error_respuesta(404, 'El autor no existe.')
        filas = con.execute("""
            SELECT l.id, l.isbn, l.titulo, la.orden
            FROM libros_autores la JOIN libros l ON l.id = la.libro_id
            WHERE la.autor_id = %s ORDER BY l.titulo""", (autor_id,)).fetchall()
    return jsonify(filas)


@app.route('/authors', methods=['POST'])
@requiere_jwt(ROL_ADMIN)
def crear_autor():
    campos, errores = _validar_autor(cuerpo_json(), parcial=False)
    if errores:
        raise DatosInvalidos(errores)
    with conexion() as con:
        fila = con.execute(
            """INSERT INTO autores (nombre, biografia, nacionalidad)
               VALUES (%(nombre)s, %(biografia)s, %(nacionalidad)s)
               RETURNING id, nombre, nacionalidad, biografia""", campos).fetchone()
    log.info('Autor %s creado por el usuario %s', fila['id'], g.user_id)
    return jsonify(fila), 201


def _modificar(autor_id, campos):
    with conexion() as con:
        # Los nombres de columna salen de _validar_autor, nunca del cliente.
        fila = con.execute(
            'UPDATE autores SET {} WHERE id = %s '
            'RETURNING id, nombre, nacionalidad, biografia'
            .format(', '.join('{} = %s'.format(k) for k in campos)),
            list(campos.values()) + [autor_id]).fetchone()
    if not fila:
        return error_respuesta(404, 'El autor no existe.')
    log.info('Autor %s modificado por el usuario %s', autor_id, g.user_id)
    return jsonify(fila)


@app.route('/authors/<int:autor_id>', methods=['PUT'])
@requiere_jwt(ROL_ADMIN)
def reemplazar_autor(autor_id):
    campos, errores = _validar_autor(cuerpo_json(), parcial=False)
    if errores:
        raise DatosInvalidos(errores)
    return _modificar(autor_id, campos)


@app.route('/authors/<int:autor_id>', methods=['PATCH'])
@requiere_jwt(ROL_ADMIN)
def modificar_autor(autor_id):
    campos, errores = _validar_autor(cuerpo_json(), parcial=True)
    if errores:
        raise DatosInvalidos(errores)
    if not campos:
        raise DatosInvalidos(['No se envio ningun campo para modificar.'])
    return _modificar(autor_id, campos)


@app.route('/authors/<int:autor_id>', methods=['DELETE'])
@requiere_jwt(ROL_ADMIN)
def borrar_autor(autor_id):
    # fk_la_autor es RESTRICT: la base impide borrar un autor acreditado en un
    # libro, y _llave_foranea lo convierte en 409.
    with conexion() as con:
        borrados = con.execute('DELETE FROM autores WHERE id = %s',
                               (autor_id,)).rowcount
    if not borrados:
        return error_respuesta(404, 'El autor no existe.')
    log.info('Autor %s borrado por el usuario %s', autor_id, g.user_id)
    return '', 204


@app.route('/authors/<int:autor_id>/books/<int:libro_id>', methods=['POST', 'PUT'])
@requiere_jwt(ROL_ADMIN)
def vincular_libro(autor_id, libro_id):
    """Acredita al autor en el libro. Con PUT/POST se puede fijar `orden`."""
    datos = request.get_json(silent=True) or {}
    orden = datos.get('orden', 1) if isinstance(datos, dict) else 1
    if isinstance(orden, bool) or not isinstance(orden, int) or not 1 <= orden <= 32767:
        raise DatosInvalidos(['orden debe ser un entero mayor que cero.'])
    with conexion() as con:
        if not con.execute('SELECT 1 FROM autores WHERE id = %s', (autor_id,)).fetchone():
            return error_respuesta(404, 'El autor no existe.')
        if not con.execute('SELECT 1 FROM libros WHERE id = %s', (libro_id,)).fetchone():
            return error_respuesta(404, 'El libro no existe.')
        con.execute(
            """INSERT INTO libros_autores (libro_id, autor_id, orden)
               VALUES (%s, %s, %s)
               ON CONFLICT (libro_id, autor_id) DO UPDATE SET orden = EXCLUDED.orden""",
            (libro_id, autor_id, orden))
    log.info('Autor %s vinculado al libro %s por el usuario %s',
             autor_id, libro_id, g.user_id)
    return jsonify({'autor_id': autor_id, 'libro_id': libro_id, 'orden': orden}), 200


@app.route('/authors/<int:autor_id>/books/<int:libro_id>', methods=['DELETE'])
@requiere_jwt(ROL_ADMIN)
def desvincular_libro(autor_id, libro_id):
    with conexion() as con:
        autores = con.execute(
            'SELECT autor_id FROM libros_autores WHERE libro_id = %s FOR UPDATE',
            (libro_id,)).fetchall()
        if autor_id not in [f['autor_id'] for f in autores]:
            return error_respuesta(404, 'Ese autor no figura en ese libro.')
        # Regla del monolito (validacion.js): un libro siempre tiene un autor.
        if len(autores) == 1:
            return error_respuesta(409, 'Un libro debe conservar al menos un autor.')
        con.execute('DELETE FROM libros_autores WHERE libro_id = %s AND autor_id = %s',
                    (libro_id, autor_id))
    log.info('Autor %s desvinculado del libro %s por el usuario %s',
             autor_id, libro_id, g.user_id)
    return '', 204


if __name__ == '__main__':
    app.run(host=APP_HOST, port=APP_PORT)
