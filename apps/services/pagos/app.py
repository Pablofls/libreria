# -*- coding: utf-8 -*-
"""Microservicio de pagos de la Libreria Online.

    POST   /payments               registra un pago (simulado); si cubre el
                                   total, el pedido pasa a 'pagado'
    GET    /payments, /payments/<id>   los propios (admin: todos)
    PUT    /payments/<id>          corrige metodo y referencia (admin)
    PATCH  /payments/<id>/status   reembolsa (admin)
    DELETE /payments/<id>          borra un pago pendiente o rechazado (admin)
    GET    /health

Servicio, no aplicacion web: solo JSON. Comparte la base PostgreSQL con el
monolito y los demas servicios y se conecta como libreria_app.

Autenticacion: JWT HS256 emitido por apps/services/login (20 minutos, claims
user_id y role_id), verificado aqui con JWT_SECRET_KEY, el mismo valor en todos
los .env. 401 sin token valido; 403 con rol insuficiente.

    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    python3 app.py                    # -> http://127.0.0.1:5006/health
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
    format='%(asctime)s %(levelname)s [pagos] %(message)s')
log = logging.getLogger('pagos')

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

APP_HOST = os.getenv('PAGOS_HOST', '0.0.0.0')
APP_PORT = int(os.getenv('PAGOS_PORT', '5006'))

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
SERVICIO = 'pagos'


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
    cuerpo = {'servicio': 'pagos', 'version': VERSION, 'estado': 'ok',
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


# =============================================================================
# Pagos
#
# Todas las rutas exigen JWT. El dueno de un pedido paga y consulta los
# pagos de SUS pedidos; el administrador ve y gestiona todos.
#
# Tablas: pagos, metodos_pago, estados_pago, pedidos, v_pedidos_total
# (db/pending/20261004-pedidos-pagos.sql). Los pagos son SIMULADOS: no hay
# pasarela ni datos de tarjeta; un pago registrado nace 'aprobado'. Nada
# sensible entra, se guarda o se registra en logs.
#
# Registrar un pago y mover el pedido a 'pagado' ocurre en UNA transaccion, con
# la fila del pedido bloqueada: dos pagos simultaneos no pueden pagar dos veces
# el mismo pedido.
# =============================================================================
LIMITE_REFERENCIA = 60

SELECT_PAGO = """
    SELECT pg.id, pg.pedido_id, mp.nombre AS metodo, ep.nombre AS estado,
           pg.monto, pg.referencia, pg.creado_en
    FROM pagos pg
    JOIN metodos_pago mp ON mp.id = pg.metodo_pago_id
    JOIN estados_pago ep ON ep.id = pg.estado_pago_id
    JOIN pedidos pe ON pe.id = pg.pedido_id
"""


def _id_catalogo(con, tabla, nombre):
    # `tabla` es una constante de este modulo, nunca un dato del cliente.
    fila = con.execute('SELECT id FROM {} WHERE nombre = %s'.format(tabla),
                       (nombre,)).fetchone()
    return fila['id'] if fila else None


def _monto_valido(valor):
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        return None
    try:
        monto = Decimal(str(valor))
    except InvalidOperation:
        return None
    if not monto.is_finite() or monto <= 0 or monto != monto.quantize(Decimal('0.01')) \
            or monto >= Decimal('100000000'):
        return None
    return monto


def _referencia(datos):
    if datos.get('referencia') is None:
        return None
    referencia = texto(datos.get('referencia'))
    if not referencia or len(referencia) > LIMITE_REFERENCIA:
        raise DatosInvalidos(['referencia debe ser texto de hasta {} caracteres.'
                              .format(LIMITE_REFERENCIA)])
    return referencia


def _pago_visible(con, pago_id):
    """El pago, o None si no existe o no es del usuario (404 en ambos casos)."""
    condicion, parametros = ' WHERE pg.id = %s', [pago_id]
    if not es_admin():
        condicion += ' AND pe.usuario_id = %s'
        parametros.append(g.user_id)
    return con.execute(SELECT_PAGO + condicion, parametros).fetchone()


@app.route('/payments', methods=['POST'])
@requiere_jwt()
def registrar_pago():
    datos = cuerpo_json()
    pedido_id = entero_positivo(datos.get('pedido_id'))
    monto = _monto_valido(datos.get('monto'))
    metodo = texto(datos.get('metodo'))
    errores = []
    if pedido_id is None:
        errores.append('pedido_id es obligatorio.')
    if monto is None:
        errores.append('monto debe ser un numero mayor que cero con dos decimales.')
    if not metodo:
        errores.append('metodo es obligatorio.')
    referencia = None
    try:
        referencia = _referencia(datos)
    except DatosInvalidos as error:
        errores += error.errores
    if errores:
        raise DatosInvalidos(errores)

    with conexion() as con:
        con.execute("SELECT set_config('app.usuario_id', %s, true)", (str(g.user_id),))
        pedido = con.execute(
            """SELECT p.id, p.usuario_id, e.nombre AS estado
               FROM pedidos p JOIN estados_pedido e ON e.id = p.estado_id
               WHERE p.id = %s FOR UPDATE OF p""", (pedido_id,)).fetchone()
        # 404 tambien para el pedido ajeno: no confirmar que existe.
        if not pedido or (not es_admin() and pedido['usuario_id'] != g.user_id):
            return error_respuesta(404, 'El pedido no existe.')
        if pedido['estado'] != 'pendiente':
            raise Conflicto('El pedido esta {}: no admite pagos.'.format(pedido['estado']))

        metodo_id = _id_catalogo(con, 'metodos_pago', metodo)
        if metodo_id is None:
            raise DatosInvalidos(['metodo no valido.'])
        total = con.execute('SELECT total, pagado FROM v_pedidos_total WHERE id = %s',
                            (pedido_id,)).fetchone()
        restante = total['total'] - total['pagado']
        if monto > restante:
            raise Conflicto('El monto excede lo que falta por pagar ({}).'.format(restante))

        pago_id = con.execute(
            """INSERT INTO pagos (pedido_id, metodo_pago_id, estado_pago_id, monto, referencia)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (pedido_id, metodo_id, _id_catalogo(con, 'estados_pago', 'aprobado'),
             monto, referencia)).fetchone()['id']

        if monto == restante:
            con.execute('UPDATE pedidos SET estado_id = %s WHERE id = %s',
                        (_id_catalogo(con, 'estados_pedido', 'pagado'), pedido_id))
        pago = con.execute(SELECT_PAGO + ' WHERE pg.id = %s', (pago_id,)).fetchone()
        pago['pedido_estado'] = con.execute(
            """SELECT e.nombre FROM pedidos p JOIN estados_pedido e ON e.id = p.estado_id
               WHERE p.id = %s""", (pedido_id,)).fetchone()['nombre']
    log.info('Pago %s registrado para el pedido %s por el usuario %s',
             pago_id, pedido_id, g.user_id)
    return jsonify(pago), 201


@app.route('/payments', methods=['GET'])
@requiere_jwt()
def listar_pagos():
    condiciones, parametros = [], []
    if not es_admin():
        condiciones.append('pe.usuario_id = %s')
        parametros.append(g.user_id)
    if request.args.get('pedido_id'):
        pedido_id = entero_positivo(
            int(request.args['pedido_id']) if request.args['pedido_id'].isdigit() else None)
        if pedido_id is None:
            raise DatosInvalidos(['pedido_id debe ser un entero positivo.'])
        condiciones.append('pg.pedido_id = %s')
        parametros.append(pedido_id)
    donde = (' WHERE ' + ' AND '.join(condiciones)) if condiciones else ''
    with conexion() as con:
        filas = con.execute(SELECT_PAGO + donde + ' ORDER BY pg.id DESC',
                            parametros).fetchall()
    return jsonify(filas)


@app.route('/payments/<int:pago_id>', methods=['GET'])
@requiere_jwt()
def ver_pago(pago_id):
    with conexion() as con:
        pago = _pago_visible(con, pago_id)
    if not pago:
        return error_respuesta(404, 'El pago no existe.')
    return jsonify(pago)


@app.route('/payments/<int:pago_id>', methods=['PUT'])
@requiere_jwt(ROL_ADMIN)
def corregir_pago(pago_id):
    """Corrige metodo y referencia. El monto no se edita: un pago mal
    capturado se reembolsa y se registra de nuevo."""
    datos = cuerpo_json()
    metodo = texto(datos.get('metodo'))
    if not metodo:
        raise DatosInvalidos(['metodo es obligatorio.'])
    referencia = _referencia(datos)
    with conexion() as con:
        metodo_id = _id_catalogo(con, 'metodos_pago', metodo)
        if metodo_id is None:
            raise DatosInvalidos(['metodo no valido.'])
        actualizados = con.execute(
            'UPDATE pagos SET metodo_pago_id = %s, referencia = %s WHERE id = %s',
            (metodo_id, referencia, pago_id)).rowcount
        if not actualizados:
            return error_respuesta(404, 'El pago no existe.')
        pago = con.execute(SELECT_PAGO + ' WHERE pg.id = %s', (pago_id,)).fetchone()
    log.info('Pago %s corregido por el usuario %s', pago_id, g.user_id)
    return jsonify(pago)


@app.route('/payments/<int:pago_id>/status', methods=['PATCH'])
@requiere_jwt(ROL_ADMIN)
def cambiar_estado_pago(pago_id):
    """Solo 'reembolsado', y solo con el pedido ya cancelado (el servicio de
    pedidos devolvio el stock): reembolsar un pedido vigente lo dejaria
    'pagado' sin dinero detras."""
    nuevo = texto(cuerpo_json().get('estado'))
    if nuevo != 'reembolsado':
        raise DatosInvalidos(['estado solo puede ser "reembolsado".'])
    with conexion() as con:
        fila = con.execute(
            """SELECT pg.id, ep.nombre AS estado, e.nombre AS pedido_estado
               FROM pagos pg
               JOIN estados_pago ep ON ep.id = pg.estado_pago_id
               JOIN pedidos pe ON pe.id = pg.pedido_id
               JOIN estados_pedido e ON e.id = pe.estado_id
               WHERE pg.id = %s FOR UPDATE OF pg""", (pago_id,)).fetchone()
        if not fila:
            return error_respuesta(404, 'El pago no existe.')
        if fila['estado'] != 'aprobado':
            raise Conflicto('Solo se reembolsa un pago aprobado.')
        if fila['pedido_estado'] != 'cancelado':
            raise Conflicto('Cancela primero el pedido para reembolsar sus pagos.')
        con.execute('UPDATE pagos SET estado_pago_id = %s WHERE id = %s',
                    (_id_catalogo(con, 'estados_pago', 'reembolsado'), pago_id))
        pago = con.execute(SELECT_PAGO + ' WHERE pg.id = %s', (pago_id,)).fetchone()
    log.info('Pago %s reembolsado por el usuario %s', pago_id, g.user_id)
    return jsonify(pago)


@app.route('/payments/<int:pago_id>', methods=['DELETE'])
@requiere_jwt(ROL_ADMIN)
def borrar_pago(pago_id):
    """Solo pagos rechazados o pendientes: un pago aprobado o reembolsado es
    un registro contable y no se borra."""
    with conexion() as con:
        borrados = con.execute(
            """DELETE FROM pagos WHERE id = %s AND estado_pago_id IN
               (SELECT id FROM estados_pago WHERE nombre IN ('pendiente', 'rechazado'))""",
            (pago_id,)).rowcount
        if not borrados:
            existe = con.execute('SELECT 1 FROM pagos WHERE id = %s', (pago_id,)).fetchone()
            if not existe:
                return error_respuesta(404, 'El pago no existe.')
            raise Conflicto('Solo se borra un pago pendiente o rechazado.')
    log.info('Pago %s borrado por el usuario %s', pago_id, g.user_id)
    return '', 204


if __name__ == '__main__':
    app.run(host=APP_HOST, port=APP_PORT)
