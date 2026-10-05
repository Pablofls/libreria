# -*- coding: utf-8 -*-
"""Microservicio de usuarios de la Libreria Online.

    GET    /users, /users/<id>     consulta (admin; un lector solo la suya)
    POST   /users                  alta (admin)
    PUT    /users/<id>             reemplaza datos (admin, o el propio usuario)
    PATCH  /users/<id>             modifica parcial (idem; rol y activo solo admin)
    DELETE /users/<id>             baja logica (activo = false)
    GET    /health

Servicio, no aplicacion web: solo JSON. Comparte la base PostgreSQL con el
monolito y los demas servicios y se conecta como libreria_app.

Autenticacion: JWT HS256 emitido por apps/services/login (20 minutos, claims
user_id y role_id), verificado aqui con JWT_SECRET_KEY, el mismo valor en todos
los .env. 401 sin token valido; 403 con rol insuficiente.

    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    python3 app.py                    # -> http://127.0.0.1:5003/health
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
    format='%(asctime)s %(levelname)s [users] %(message)s')
log = logging.getLogger('users')

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

APP_HOST = os.getenv('USERS_HOST', '0.0.0.0')
APP_PORT = int(os.getenv('USERS_PORT', '5003'))

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
        return jsonify({'servicio': 'users', 'version': VERSION, 'estado': 'ok'})
    except psycopg.Error:
        return jsonify({'servicio': 'users', 'version': VERSION,
                        'estado': 'sin base de datos'}), 503


# =============================================================================
# Usuarios
#
# Lecturas: JWT; administrador ve todo, un lector solo su propia cuenta.
# Escrituras: JWT; administrador sobre cualquiera, un lector solo sobre si
# mismo y sin poder tocar `rol` ni `activo`.
#
# El nombre vive en `personas`; usuarios.nombre lo compone un disparador
# (db/05_triggers.sql), asi que aqui solo se escribe en personas.
# Contrasenas: bcrypt con el mismo coste que el monolito y el login; la base
# rechaza cualquier otro formato (ck_usuarios_hash_bcrypt). Nunca se devuelve
# ni se registra en logs.
# =============================================================================
import bcrypt  # noqa: E402

RONDAS_BCRYPT = int(os.getenv('BCRYPT_RONDAS', '10'))
RE_EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$')
LARGO_MAXIMO = 100
LARGO_MAXIMO_EMAIL = 150
LARGO_MINIMO_PASSWORD = 8
LARGO_MAXIMO_PASSWORD = 72      # bcrypt ignora lo que pase de 72 bytes
ROLES = ('lector', 'admin')

SELECT_USUARIO = """
    SELECT u.id, u.email, u.rol, u.activo, u.creado_en,
           p.nombre, p.apellido_paterno, p.apellido_materno
    FROM usuarios u JOIN personas p ON p.id = u.persona_id
"""


def _buscar(con, usuario_id):
    # El parametro es una CONEXION, no un cursor: en Psycopg 3,
    # Connection.execute() devuelve un cursor nuevo y es de ahi de donde se lee.
    # Llamar con.fetchone() lanza AttributeError y acaba en un 500.
    return con.execute(SELECT_USUARIO + ' WHERE u.id = %s', (usuario_id,)).fetchone()


def _hash(password):
    return bcrypt.hashpw(password.encode('utf-8'),
                         bcrypt.gensalt(rounds=RONDAS_BCRYPT)).decode('ascii')


def _validar(datos, parcial):
    """(campos, errores). Con parcial=True solo valida lo que viene."""
    errores, campos = [], {}

    for clave, etiqueta in (('nombre', 'El nombre'),
                            ('apellido_paterno', 'El apellido paterno'),
                            ('apellido_materno', 'El apellido materno')):
        if clave not in datos and parcial:
            continue
        valor = texto(datos.get(clave))
        if not valor:
            errores.append('{} es obligatorio.'.format(etiqueta))
        elif len(valor) > LARGO_MAXIMO:
            errores.append('{} no puede pasar de {} caracteres.'.format(
                etiqueta, LARGO_MAXIMO))
        campos[clave] = valor
    # ck_personas_largo_compuesto: el nombre completo se copia a VARCHAR(100).
    if not parcial and len(' '.join(campos.get(k, '') for k in (
            'nombre', 'apellido_paterno', 'apellido_materno'))) > LARGO_MAXIMO:
        errores.append('El nombre completo no puede pasar de {} caracteres.'
                       .format(LARGO_MAXIMO))

    if 'email' in datos or not parcial:
        email = texto(datos.get('email')).lower()
        if not email:
            errores.append('El correo es obligatorio.')
        elif len(email) > LARGO_MAXIMO_EMAIL or not RE_EMAIL.match(email):
            errores.append('El correo no tiene un formato valido.')
        campos['email'] = email

    if 'password' in datos:
        password = datos.get('password')
        if (not isinstance(password, str)
                or len(password) < LARGO_MINIMO_PASSWORD):
            errores.append('La contrasena debe tener al menos {} caracteres.'
                           .format(LARGO_MINIMO_PASSWORD))
        elif len(password.encode('utf-8')) > LARGO_MAXIMO_PASSWORD:
            errores.append('La contrasena no puede pasar de {} bytes.'
                           .format(LARGO_MAXIMO_PASSWORD))
        else:
            campos['password'] = password
    elif not parcial:
        errores.append('La contrasena es obligatoria.')

    if 'rol' in datos:
        if datos['rol'] not in ROLES:
            errores.append('El rol debe ser uno de: {}.'.format(', '.join(ROLES)))
        else:
            campos['rol'] = datos['rol']
    if 'activo' in datos:
        if not isinstance(datos['activo'], bool):
            errores.append('activo debe ser verdadero o falso.')
        else:
            campos['activo'] = datos['activo']
    return campos, errores


def _autorizar_sobre(usuario_id, campos):
    """None si procede; si no, la respuesta de error. Un lector: solo lo suyo."""
    if es_admin():
        return None
    if usuario_id != g.user_id:
        return error_respuesta(403, 'Solo puedes operar sobre tu propia cuenta.')
    if 'rol' in campos or 'activo' in campos:
        return error_respuesta(403, 'Solo un administrador cambia el rol o el estado.')
    return None


@app.route('/users', methods=['GET'])
@requiere_jwt(ROL_ADMIN)
def listar_usuarios():
    with conexion() as con:
        filas = con.execute(SELECT_USUARIO + ' ORDER BY u.rol, p.nombre, u.id').fetchall()
    return jsonify(filas)


@app.route('/users/<int:usuario_id>', methods=['GET'])
@requiere_jwt()
def ver_usuario(usuario_id):
    if not es_admin() and usuario_id != g.user_id:
        return error_respuesta(403, 'Solo puedes consultar tu propia cuenta.')
    with conexion() as con:
        fila = _buscar(con, usuario_id)
    if not fila:
        return error_respuesta(404, 'El usuario no existe.')
    return jsonify(fila)


@app.route('/users', methods=['POST'])
@requiere_jwt(ROL_ADMIN)
def crear_usuario():
    campos, errores = _validar(cuerpo_json(), parcial=False)
    if errores:
        raise DatosInvalidos(errores)
    rol = campos.get('rol', 'lector')
    with conexion() as con:
        persona_id = con.execute(
            """INSERT INTO personas (nombre, apellido_paterno, apellido_materno)
               VALUES (%s, %s, %s) RETURNING id""",
            (campos['nombre'], campos['apellido_paterno'],
             campos['apellido_materno'])).fetchone()['id']
        usuario_id = con.execute(
            """INSERT INTO usuarios (persona_id, email, password_hash, rol, activo)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (persona_id, campos['email'], _hash(campos['password']), rol,
             campos.get('activo', True))).fetchone()['id']
        fila = _buscar(con, usuario_id)
    log.info('Usuario %s creado por el usuario %s', usuario_id, g.user_id)
    return jsonify(fila), 201


def _actualizar(usuario_id, campos):
    with conexion() as con:
        actual = _buscar(con, usuario_id)
        if not actual:
            return error_respuesta(404, 'El usuario no existe.')
        if campos.get('activo') is False and actual['rol'] == 'admin':
            return error_respuesta(409, 'No se puede desactivar al administrador.')

        personas = {k: campos[k] for k in
                    ('nombre', 'apellido_paterno', 'apellido_materno') if k in campos}
        if personas:
            con.execute(
                'UPDATE personas SET {} WHERE id = (SELECT persona_id FROM usuarios WHERE id = %s)'
                .format(', '.join('{} = %s'.format(k) for k in personas)),
                list(personas.values()) + [usuario_id])

        cuentas = {k: campos[k] for k in ('email', 'rol', 'activo') if k in campos}
        if 'password' in campos:
            cuentas['password_hash'] = _hash(campos['password'])
        if cuentas:
            con.execute(
                'UPDATE usuarios SET {} WHERE id = %s'
                .format(', '.join('{} = %s'.format(k) for k in cuentas)),
                list(cuentas.values()) + [usuario_id])
        fila = _buscar(con, usuario_id)
    log.info('Usuario %s modificado por el usuario %s', usuario_id, g.user_id)
    return jsonify(fila)


@app.route('/users/<int:usuario_id>', methods=['PUT'])
@requiere_jwt()
def reemplazar_usuario(usuario_id):
    # PUT es completo: nombre, apellidos y correo siempre; contrasena, rol y
    # activo solo si se quieren cambiar.
    datos = cuerpo_json()
    # Primero la autorizacion: a quien no le toca no se le explica el cuerpo.
    denegado = _autorizar_sobre(usuario_id, datos)
    if denegado:
        return denegado
    campos, errores = _validar_put(datos)
    if errores:
        raise DatosInvalidos(errores)
    return _actualizar(usuario_id, campos)


def _validar_put(datos):
    """PUT: como el alta, pero la contrasena es opcional."""
    campos, errores = _validar(datos, parcial=False)
    errores = [e for e in errores if e != 'La contrasena es obligatoria.']
    return campos, errores


@app.route('/users/<int:usuario_id>', methods=['PATCH'])
@requiere_jwt()
def modificar_usuario(usuario_id):
    datos = cuerpo_json()
    denegado = _autorizar_sobre(usuario_id, datos)
    if denegado:
        return denegado
    campos, errores = _validar(datos, parcial=True)
    if errores:
        raise DatosInvalidos(errores)
    if not campos:
        raise DatosInvalidos(['No se envio ningun campo para modificar.'])
    return _actualizar(usuario_id, campos)


@app.route('/users/<int:usuario_id>', methods=['DELETE'])
@requiere_jwt()
def desactivar_usuario(usuario_id):
    """Baja logica (activo = false): un usuario con pedidos no se puede borrar."""
    denegado = _autorizar_sobre(usuario_id, {})
    return denegado or _actualizar(usuario_id, {'activo': False})


if __name__ == '__main__':
    app.run(host=APP_HOST, port=APP_PORT)
