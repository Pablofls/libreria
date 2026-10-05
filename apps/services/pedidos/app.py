# -*- coding: utf-8 -*-
"""Microservicio de pedidos de la Libreria Online.

    POST   /orders                 crea un pedido y descuenta stock
    GET    /orders, /orders/<id>   los propios (admin: todos)
    PUT    /orders/<id>            cambia las lineas de un pedido pendiente
    POST   /orders/<id>/cancel     cancela y devuelve stock
    PATCH  /orders/<id>/status     cambia el estado (admin)
    DELETE /orders/<id>            borra un pedido cancelado (admin)
    GET    /health

Servicio, no aplicacion web: solo JSON. Comparte la base PostgreSQL con el
monolito y los demas servicios y se conecta como libreria_app.

Autenticacion: JWT HS256 emitido por apps/services/login (20 minutos, claims
user_id y role_id), verificado aqui con JWT_SECRET_KEY, el mismo valor en todos
los .env. 401 sin token valido; 403 con rol insuficiente.

    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    python3 app.py                    # -> http://127.0.0.1:5005/health
"""
import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation  # noqa: F401
from functools import wraps

import jwt
import psycopg
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout
from werkzeug.exceptions import HTTPException

load_dotenv()

logging.basicConfig(
    level=os.getenv('LOG_NIVEL', 'INFO').upper(),
    format='%(asctime)s %(levelname)s [pedidos] %(message)s')
log = logging.getLogger('pedidos')

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

APP_HOST = os.getenv('PEDIDOS_HOST', '0.0.0.0')
APP_PORT = int(os.getenv('PEDIDOS_PORT', '5005'))

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
            options={'require': ['exp', 'iss', 'user_id', 'role_id']})
    except jwt.PyJWTError:
        return None
    user_id, role_id = reclamos['user_id'], reclamos['role_id']
    if (isinstance(user_id, bool) or not isinstance(user_id, int)
            or role_id not in (ROL_ADMIN, ROL_LECTOR)):
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
    try:
        with conexion() as con:
            con.execute('SELECT 1')
        return jsonify({'servicio': 'pedidos', 'version': VERSION, 'estado': 'ok'})
    except psycopg.Error:
        return jsonify({'servicio': 'pedidos', 'version': VERSION,
                        'estado': 'sin base de datos'}), 503


# =============================================================================
# Pedidos
#
# Todas las rutas exigen JWT: un pedido no es informacion publica. Un lector
# crea y ve SUS pedidos; un administrador ve y gestiona todos.
#
# Tablas: pedidos, pedidos_lineas, pedidos_estados_historial, v_pedidos_total
# (db/pending/20261004-pedidos-pagos.sql). El total NO se guarda: lo calcula la
# vista. El precio de cada linea se toma de libros.precio EN LA BASE, nunca del
# cuerpo de la peticion.
#
# Stock: se ajusta con sp_ajustar_stock, dentro de la MISMA transaccion que
# crea, modifica o cancela el pedido. ck_libros_stock impide dejarlo negativo:
# si una linea no alcanza, la transaccion entera se revierte y la respuesta es
# 409.
# =============================================================================
MAX_LINEAS = 50
MAX_CANTIDAD = 1000

# estado actual -> estados a los que puede pasar
TRANSICIONES = {
    'pendiente': ('pagado', 'cancelado'),
    'pagado':    ('enviado', 'cancelado'),
    'enviado':   (),
    'cancelado': (),
}


def _lineas_validas(datos):
    """Valida el cuerpo y junta libros repetidos. Orden fijo por libro_id."""
    crudas = datos.get('lineas')
    if not isinstance(crudas, list) or not crudas:
        raise DatosInvalidos(['lineas debe ser una lista con al menos un libro.'])
    if len(crudas) > MAX_LINEAS:
        raise DatosInvalidos(['Un pedido no puede pasar de {} lineas.'.format(MAX_LINEAS)])
    juntas, errores = {}, []
    for i, linea in enumerate(crudas, 1):
        libro_id = entero_positivo(linea.get('libro_id')) if isinstance(linea, dict) else None
        cantidad = entero_positivo(linea.get('cantidad')) if isinstance(linea, dict) else None
        if libro_id is None or cantidad is None or cantidad > MAX_CANTIDAD:
            errores.append('Linea {}: libro_id y cantidad (1 a {}) son obligatorios.'
                           .format(i, MAX_CANTIDAD))
            continue
        juntas[libro_id] = juntas.get(libro_id, 0) + cantidad
    if errores:
        raise DatosInvalidos(errores)
    # Siempre en el mismo orden: dos pedidos simultaneos que comparten libros
    # bloquean las filas en el mismo orden y no se interbloquean.
    return sorted(juntas.items())


def _marcar_actor(con):
    """Para que trg_pedido_historial registre quien cambio el estado."""
    con.execute("SELECT set_config('app.usuario_id', %s, true)", (str(g.user_id),))


def _estado_id(con, nombre):
    return con.execute('SELECT id FROM estados_pedido WHERE nombre = %s',
                       (nombre,)).fetchone()['id']


def _tomar_lineas(con, pedido_id, lineas):
    for libro_id, cantidad in lineas:
        libro = con.execute('SELECT precio FROM libros WHERE id = %s',
                            (libro_id,)).fetchone()
        if not libro:
            raise DatosInvalidos(['El libro {} no existe.'.format(libro_id)])
        con.execute(
            """INSERT INTO pedidos_lineas (pedido_id, libro_id, cantidad, precio_unitario)
               VALUES (%s, %s, %s, %s)""",
            (pedido_id, libro_id, cantidad, libro['precio']))
        try:
            con.execute('SELECT sp_ajustar_stock(%s, %s)', (libro_id, -cantidad))
        except psycopg.errors.CheckViolation as error:
            if error.diag.constraint_name != 'ck_libros_stock':
                raise
            raise Conflicto('No hay existencias suficientes del libro {}.'
                            .format(libro_id))


def _devolver_stock(con, pedido_id):
    filas = con.execute(
        'SELECT libro_id, cantidad FROM pedidos_lineas WHERE pedido_id = %s '
        'ORDER BY libro_id', (pedido_id,)).fetchall()
    for fila in filas:
        con.execute('SELECT sp_ajustar_stock(%s, %s)',
                    (fila['libro_id'], fila['cantidad']))


def _detalle(con, pedido_id):
    cabecera = con.execute('SELECT * FROM v_pedidos_total WHERE id = %s',
                           (pedido_id,)).fetchone()
    if not cabecera:
        return None
    cabecera['lineas'] = con.execute(
        """SELECT pl.libro_id, l.titulo, pl.cantidad, pl.precio_unitario,
                  pl.cantidad * pl.precio_unitario AS subtotal
           FROM pedidos_lineas pl JOIN libros l ON l.id = pl.libro_id
           WHERE pl.pedido_id = %s ORDER BY pl.libro_id""", (pedido_id,)).fetchall()
    cabecera['historial'] = con.execute(
        """SELECT e.nombre AS estado, h.cambiado_en, h.cambiado_por
           FROM pedidos_estados_historial h JOIN estados_pedido e ON e.id = h.estado_id
           WHERE h.pedido_id = %s ORDER BY h.cambiado_en""", (pedido_id,)).fetchall()
    return cabecera


def _acceso(con, pedido_id):
    """(pedido, error). Existencia y propiedad; bloquea la fila para escribir."""
    fila = con.execute(
        """SELECT p.id, p.usuario_id, e.nombre AS estado
           FROM pedidos p JOIN estados_pedido e ON e.id = p.estado_id
           WHERE p.id = %s FOR UPDATE OF p""", (pedido_id,)).fetchone()
    if not fila:
        return None, error_respuesta(404, 'El pedido no existe.')
    # 404 y no 403 para el pedido ajeno: no confirmar que existe.
    if not es_admin() and fila['usuario_id'] != g.user_id:
        return None, error_respuesta(404, 'El pedido no existe.')
    return fila, None


@app.route('/orders', methods=['POST'])
@requiere_jwt()
def crear_pedido():
    lineas = _lineas_validas(cuerpo_json())
    with conexion() as con:
        _marcar_actor(con)
        pedido_id = con.execute(
            'INSERT INTO pedidos (usuario_id, estado_id) VALUES (%s, %s) RETURNING id',
            (g.user_id, _estado_id(con, 'pendiente'))).fetchone()['id']
        _tomar_lineas(con, pedido_id, lineas)
        detalle = _detalle(con, pedido_id)
    log.info('Pedido %s creado por el usuario %s', pedido_id, g.user_id)
    return jsonify(detalle), 201


@app.route('/orders', methods=['GET'])
@requiere_jwt()
def listar_pedidos():
    condiciones, parametros = [], []
    if not es_admin():
        condiciones.append('usuario_id = %s')
        parametros.append(g.user_id)
    estado = texto(request.args.get('estado'))
    if estado:
        condiciones.append('estado = %s')
        parametros.append(estado)
    donde = (' WHERE ' + ' AND '.join(condiciones)) if condiciones else ''
    with conexion() as con:
        filas = con.execute('SELECT * FROM v_pedidos_total' + donde +
                            ' ORDER BY id DESC', parametros).fetchall()
    return jsonify(filas)


@app.route('/orders/<int:pedido_id>', methods=['GET'])
@requiere_jwt()
def ver_pedido(pedido_id):
    with conexion() as con:
        detalle = _detalle(con, pedido_id)
    if not detalle or (not es_admin() and detalle['usuario_id'] != g.user_id):
        return error_respuesta(404, 'El pedido no existe.')
    return jsonify(detalle)


@app.route('/orders/<int:pedido_id>', methods=['PUT'])
@requiere_jwt()
def reemplazar_lineas(pedido_id):
    """Cambia el contenido de un pedido pendiente: devuelve el stock de las
    lineas viejas y toma el de las nuevas, todo en una transaccion."""
    lineas = _lineas_validas(cuerpo_json())
    with conexion() as con:
        _marcar_actor(con)
        pedido, denegado = _acceso(con, pedido_id)
        if denegado:
            return denegado
        if pedido['estado'] != 'pendiente':
            raise Conflicto('Solo se puede modificar un pedido pendiente.')
        _devolver_stock(con, pedido_id)
        con.execute('DELETE FROM pedidos_lineas WHERE pedido_id = %s', (pedido_id,))
        _tomar_lineas(con, pedido_id, lineas)
        detalle = _detalle(con, pedido_id)
    log.info('Pedido %s modificado por el usuario %s', pedido_id, g.user_id)
    return jsonify(detalle)


def _cambiar_estado(con, pedido, nuevo):
    if nuevo not in TRANSICIONES[pedido['estado']]:
        raise Conflicto('Un pedido {} no puede pasar a {}.'
                        .format(pedido['estado'], nuevo))
    if nuevo == 'cancelado':
        _devolver_stock(con, pedido['id'])
    con.execute('UPDATE pedidos SET estado_id = %s WHERE id = %s',
                (_estado_id(con, nuevo), pedido['id']))


@app.route('/orders/<int:pedido_id>/status', methods=['PATCH'])
@requiere_jwt(ROL_ADMIN)
def cambiar_estado(pedido_id):
    nuevo = texto(cuerpo_json().get('estado'))
    if nuevo not in TRANSICIONES:
        raise DatosInvalidos(['estado debe ser uno de: {}.'.format(', '.join(TRANSICIONES))])
    with conexion() as con:
        _marcar_actor(con)
        pedido, denegado = _acceso(con, pedido_id)
        if denegado:
            return denegado
        _cambiar_estado(con, pedido, nuevo)
        detalle = _detalle(con, pedido_id)
    log.info('Pedido %s paso a %s por el usuario %s', pedido_id, nuevo, g.user_id)
    return jsonify(detalle)


@app.route('/orders/<int:pedido_id>/cancel', methods=['POST'])
@requiere_jwt()
def cancelar_pedido(pedido_id):
    """El dueno cancela su pedido mientras este pendiente; el administrador
    puede cancelar tambien uno ya pagado (por /status)."""
    with conexion() as con:
        _marcar_actor(con)
        pedido, denegado = _acceso(con, pedido_id)
        if denegado:
            return denegado
        if not es_admin() and pedido['estado'] != 'pendiente':
            raise Conflicto('Solo se puede cancelar un pedido pendiente.')
        _cambiar_estado(con, pedido, 'cancelado')
        detalle = _detalle(con, pedido_id)
    log.info('Pedido %s cancelado por el usuario %s', pedido_id, g.user_id)
    return jsonify(detalle)


@app.route('/orders/<int:pedido_id>', methods=['DELETE'])
@requiere_jwt(ROL_ADMIN)
def borrar_pedido(pedido_id):
    """Solo un pedido ya cancelado (su stock ya volvio). Con pagos, la base lo
    impide (fk_pagos_pedido es RESTRICT) y responde 409."""
    with conexion() as con:
        pedido, denegado = _acceso(con, pedido_id)
        if denegado:
            return denegado
        if pedido['estado'] != 'cancelado':
            raise Conflicto('Solo se puede borrar un pedido cancelado.')
        con.execute('DELETE FROM pedidos WHERE id = %s', (pedido_id,))
    log.info('Pedido %s borrado por el usuario %s', pedido_id, g.user_id)
    return '', 204


if __name__ == '__main__':
    app.run(host=APP_HOST, port=APP_PORT)
