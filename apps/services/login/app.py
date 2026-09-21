# -*- coding: utf-8 -*-
"""Microservicio de autenticacion de la Libreria Online.

    POST /register    alta de usuario
    POST /login       autentica y abre sesion
    POST /logout      cierra la sesion
    GET  /session     dice si hay sesion y de quien
    GET  /health      estado del servicio, de PostgreSQL y de Postfix

Todos responden en XML o en JSON segun `?format=`; sin el parametro, XML.

    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    python3 app.py                    # -> http://127.0.0.1:5000/docs

ESTO ES UN SERVICIO, NO UNA APLICACION WEB. No sirve HTML ni formularios: los
cinco endpoints reciben datos y devuelven XML o JSON. Lo unico que renderiza
una pagina es /docs, que es la interfaz de Swagger.

Comparte la base PostgreSQL con el monolito Node y con el microservicio de
catalogo, y se conecta como libreria_app, que solo puede leer y escribir filas.

El nombre NO se guarda en `usuarios`: vive partido en `personas` (nombre,
apellido paterno, apellido materno) y `usuarios.persona_id` apunta alla. La
columna `usuarios.nombre` sigue existiendo como copia derivada porque el
monolito la lee y la escribe; la mantienen los disparadores de
db/05_triggers.sql. Este servicio escribe SOLO en `personas` y deja que el
disparador componga el nombre plano: si lo escribiera el mismo, las dos
representaciones podrian quedar en desacuerdo.
"""
import json
import logging
import os
import re
import smtplib
import socket
import xml.etree.ElementTree as ET

import bcrypt
import psycopg
from dotenv import load_dotenv
from flask import Flask, Response, request, session, url_for
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from werkzeug.exceptions import HTTPException

load_dotenv()

logging.basicConfig(
    level=os.getenv('LOG_NIVEL', 'INFO').upper(),
    format='%(asctime)s %(levelname)s [login] %(message)s')
log = logging.getLogger('login')

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

APP_HOST = os.getenv('LOGIN_HOST', '0.0.0.0')
APP_PORT = int(os.getenv('LOGIN_PORT', '5000'))

# Postfix, para comprobar que el correo existe. Loopback: el Postfix de la VM
# escucha solo en 127.0.0.1 y no debe ser alcanzable desde fuera.
SMTP_HOST = os.getenv('SMTP_HOST', '127.0.0.1')
SMTP_PORT = int(os.getenv('SMTP_PORT', '25'))
SMTP_TIMEOUT = float(os.getenv('SMTP_TIMEOUT', '8'))
SMTP_REMITENTE = os.getenv('SMTP_REMITENTE', 'verificador@localhost')
VERIFICAR_CORREO = os.getenv('VERIFICAR_CORREO', '1') != '0'

# Mismo coste que src/modules/auth/auth.model.js. Si se cambia aqui y no alla,
# los hashes siguen siendo compatibles (bcrypt lleva el coste dentro), pero las
# cuentas nuevas tardarian distinto en verificarse que las viejas.
RONDAS_BCRYPT = int(os.getenv('BCRYPT_RONDAS', '10'))

# La clave de sesion NO tiene valor por omision a proposito. Con un default, el
# servicio arrancaria en la VM firmando cookies con una clave que esta en un
# repositorio publico: cualquiera podria fabricarse una sesion de administrador.
CLAVE_SESION = os.getenv('SECRET_KEY', '').strip()
if not CLAVE_SESION:
    raise RuntimeError(
        'Falta SECRET_KEY. Define una clave larga y aleatoria en el .env de la '
        'VM (python3 -c "import secrets; print(secrets.token_urlsafe(48))"). '
        'El servicio no arranca sin ella: una clave por omision permitiria '
        'falsificar sesiones.')

app = Flask(__name__)
app.secret_key = CLAVE_SESION
app.config.update(
    SESSION_COOKIE_NAME='libreria_sesion',
    SESSION_COOKIE_HTTPONLY=True,      # JavaScript no la puede leer
    SESSION_COOKIE_SAMESITE='Lax',     # no viaja en peticiones de otro sitio
    # En la VM se sirve por HTTP detras del proxy; con HTTPS, poner a 1.
    SESSION_COOKIE_SECURE=os.getenv('COOKIE_SEGURA', '0') == '1',
)

_pool = None


def _obtener_pool():
    """Pool perezoso: /docs y /health deben responder aunque PostgreSQL no este."""
    global _pool
    if _pool is None:
        conninfo = ' '.join(
            '{}={}'.format(clave, valor) for clave, valor in BD.items() if valor)
        _pool = ConnectionPool(
            conninfo + ' connect_timeout={}'.format(BD_TIMEOUT),
            min_size=1, max_size=int(os.getenv('DB_POOL_MAX', '8')),
            kwargs={'row_factory': dict_row}, open=True,
            # Sin esto el pool espera 30 s por omision antes de rendirse, y
            # /health tardaria medio minuto en informar de que la base no
            # responde. Un aviso que llega tarde no es un aviso.
            timeout=BD_TIMEOUT)
        log.info('Pool creado contra %s:%s/%s', BD['host'], BD['port'], BD['dbname'])
    return _pool


# =============================================================================
# Salida: una estructura neutra, dos serializaciones
#
# Ninguna vista construye XML. Arma dicts y listas de Python —la unica fuente de
# verdad— y `responder` elige el renderizador. Si cada formato se serializara
# por su lado, al primer campo nuevo el XML y el JSON dejarian de coincidir y
# nadie se enteraria hasta que un cliente se rompiera.
#
# Las claves van en espanol, al reves que en el microservicio de catalogo. Alli
# el contrato venia heredado de library.xml; aqui los campos SON los del
# enunciado (nombre, apellido paterno, apellido materno), y traducirlos a ingles
# obligaria a que la respuesta usara nombres distintos que la peticion.
# =============================================================================
FORMATOS = ('xml', 'json')
CABECERA_XML = '<?xml version="1.0" encoding="UTF-8"?>\n'


def formato_pedido():
    """El parametro ?format= manda; sin el, XML.

    El respaldo por `Accept` solo entra cuando el cliente pide JSON de forma
    explicita: un `Accept: */*` —lo que manda curl— sigue recibiendo XML.
    """
    crudo = (request.args.get('format') or '').strip().lower()
    if crudo in FORMATOS:
        return crudo
    if not crudo and request.accept_mimetypes.best_match(
            ('application/xml', 'application/json')) == 'application/json':
        return 'json'
    return 'xml'


@app.before_request
def _rechazar_formato_desconocido():
    """Un ?format= invalido es un error del cliente, no un XML silencioso.

    Va en before_request para cubrir tambien las rutas que no existen: el 404
    se levanta al despachar, o sea despues de este gancho.
    """
    crudo = request.args.get('format')
    if crudo is None or crudo.strip().lower() in FORMATOS:
        return None
    return error_respuesta(400, 'El parametro "format" no admite ese valor.',
                           ['Valores validos: ' + ', '.join(FORMATOS) + '.',
                            'Sin el parametro, la respuesta es XML.'])


def _hijo(padre, etiqueta, valor=None, atributos=None):
    elemento = ET.SubElement(padre, etiqueta, atributos or {})
    if valor is not None:
        elemento.text = str(valor)
    return elemento


def _usuario_a_xml(padre, usuario):
    nodo = ET.SubElement(padre, 'usuario', {'id': str(usuario['id'])})
    _hijo(nodo, 'nombre', usuario['nombre'])
    if usuario.get('apellido_paterno'):
        _hijo(nodo, 'apellido_paterno', usuario['apellido_paterno'])
    if usuario.get('apellido_materno'):
        _hijo(nodo, 'apellido_materno', usuario['apellido_materno'])
    _hijo(nodo, 'nombre_completo', usuario['nombre_completo'])
    _hijo(nodo, 'email', usuario['email'])
    _hijo(nodo, 'rol', usuario['rol'])
    return nodo


def _correo_a_xml(padre, correo):
    return _hijo(padre, 'correo', correo['mensaje'],
                 {'estado': correo['estado'], 'codigo': str(correo['codigo'])})


def registro_a_xml(datos):
    raiz = ET.Element('registro')
    _usuario_a_xml(raiz, datos['usuario'])
    _correo_a_xml(raiz, datos['correo'])
    return raiz


def sesion_a_xml(datos):
    raiz = ET.Element('sesion',
                      {'autenticada': 'true' if datos['autenticada'] else 'false'})
    if datos.get('usuario'):
        _usuario_a_xml(raiz, datos['usuario'])
    if datos.get('mensaje'):
        _hijo(raiz, 'mensaje', datos['mensaje'])
    return raiz


def resultado_a_xml(datos):
    raiz = ET.Element('resultado', {'ok': 'true' if datos['ok'] else 'false'})
    _hijo(raiz, 'mensaje', datos['mensaje'])
    return raiz


def salud_a_xml(datos):
    raiz = ET.Element('salud', {'estado': datos['estado']})
    _hijo(raiz, 'servicio', datos['servicio'])
    _hijo(raiz, 'version', datos['version'])
    for nombre, comp in datos['componentes'].items():
        _hijo(raiz, nombre, comp['detalle'], {'estado': comp['estado']})
    return raiz


def servicio_a_xml(datos):
    raiz = ET.Element('servicio')
    _hijo(raiz, 'nombre', datos['nombre'])
    _hijo(raiz, 'version', datos['version'])
    endpoints = ET.SubElement(raiz, 'endpoints')
    for punto in datos['endpoints']:
        _hijo(endpoints, 'endpoint', punto['descripcion'],
              {'ruta': punto['ruta'], 'metodo': punto['metodo']})
    return raiz


def error_a_xml(datos):
    raiz = ET.Element('error', {'codigo': str(datos['codigo'])})
    _hijo(raiz, 'mensaje', datos['mensaje'])
    for detalle in datos.get('detalles') or []:
        _hijo(raiz, 'detalle', detalle)
    return raiz


# Cada tipo de carga necesita su renderizador registrado aqui: `responder` lo
# busca por clave. Anadir un endpoint sin anadir su entrada da un KeyError.
RENDERIZADORES_XML = {
    'registro':  registro_a_xml,
    'sesion':    sesion_a_xml,
    'resultado': resultado_a_xml,
    'salud':     salud_a_xml,
    'servicio':  servicio_a_xml,
    'error':     error_a_xml,
}


def responder(tipo, datos, estado=200):
    """Unica salida del servicio: misma estructura, dos serializaciones."""
    if formato_pedido() == 'json':
        cuerpo = json.dumps(datos, ensure_ascii=False, indent=2)
        return Response(cuerpo + '\n', status=estado,
                        content_type='application/json; charset=utf-8')
    raiz = RENDERIZADORES_XML[tipo](datos)
    if hasattr(ET, 'indent'):
        ET.indent(raiz, space='  ')
    cuerpo = CABECERA_XML + ET.tostring(raiz, encoding='unicode')
    return Response(cuerpo + '\n', status=estado,
                    content_type='application/xml; charset=utf-8')


def error_respuesta(codigo, mensaje, detalles=None):
    """Errores por el mismo camino que los aciertos.

    Un cliente que pide JSON recibe un error en JSON. Nunca sale de aqui el
    texto de una excepcion: puede llevar SQL, nombres de tabla o el correo de
    otra persona. Eso va al log del servidor.
    """
    return responder('error', {'codigo': codigo, 'mensaje': mensaje,
                               'detalles': detalles or []}, codigo)


# =============================================================================
# Entrada y validacion
# =============================================================================
# Deliberadamente permisiva en la forma y estricta en lo que de verdad importa:
# que tenga una arroba, un dominio con punto y ningun espacio. Es la misma regla
# que ck_usuarios_email en la base de datos. Validar el correo "del todo" con
# una expresion regular es un problema conocido por irresoluble; quien decide de
# verdad si existe es Postfix, mas abajo.
RE_EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$')

LARGO_MAXIMO = 100          # VARCHAR(100) de personas
LARGO_MAXIMO_EMAIL = 150    # VARCHAR(150) de usuarios
# bcrypt ignora todo lo que pase de 72 bytes. Si no se rechaza aqui, dos
# contrasenas distintas que compartan los primeros 72 bytes abririan la misma
# cuenta, y el usuario creeria tener una contrasena larguisima.
LARGO_MAXIMO_PASSWORD = 72
LARGO_MINIMO_PASSWORD = 8


def datos_entrantes():
    """Acepta formulario o JSON en la entrada, dando igual el formato de salida.

    `format` se quita a mano: viaja en el query string y nunca es un dato del
    usuario. Sin esto, un `?format=json` podria acabar mezclado con el cuerpo.
    """
    if request.is_json:
        cuerpo = request.get_json(silent=True) or {}
    else:
        cuerpo = request.form.to_dict()
    cuerpo.pop('format', None)
    return cuerpo


def _texto(valor):
    return (valor or '').strip() if isinstance(valor, str) else ''


def validar_registro(datos):
    """Devuelve (campos_limpios, errores). No toca la base ni la red."""
    errores = []
    campos = {}

    for clave, etiqueta, obligatorio in (
            ('nombre', 'El nombre', True),
            ('apellido_paterno', 'El apellido paterno', True),
            ('apellido_materno', 'El apellido materno', True)):
        valor = _texto(datos.get(clave))
        if obligatorio and not valor:
            errores.append('{} es obligatorio.'.format(etiqueta))
        elif len(valor) > LARGO_MAXIMO:
            errores.append('{} no puede pasar de {} caracteres.'.format(
                etiqueta, LARGO_MAXIMO))
        campos[clave] = valor or None

    # El CHECK ck_personas_largo_compuesto de la base impide que el nombre
    # completo pase de 100 caracteres, porque se copia a usuarios.nombre, que es
    # VARCHAR(100). Se comprueba aqui tambien para explicarlo en castellano en
    # vez de devolver un 500 con un error de restriccion.
    completo = ' '.join(v for v in (campos.get('nombre'),
                                    campos.get('apellido_paterno'),
                                    campos.get('apellido_materno')) if v)
    if len(completo) > LARGO_MAXIMO:
        errores.append('El nombre completo no puede pasar de {} caracteres.'
                       .format(LARGO_MAXIMO))

    email = _texto(datos.get('email')).lower()
    if not email:
        errores.append('El correo es obligatorio.')
    elif len(email) > LARGO_MAXIMO_EMAIL:
        errores.append('El correo no puede pasar de {} caracteres.'
                       .format(LARGO_MAXIMO_EMAIL))
    elif not RE_EMAIL.match(email):
        errores.append('El correo no tiene un formato valido.')
    campos['email'] = email

    password = datos.get('password') or ''
    if not password:
        errores.append('La contrasena es obligatoria.')
    elif len(password) < LARGO_MINIMO_PASSWORD:
        errores.append('La contrasena debe tener al menos {} caracteres.'
                       .format(LARGO_MINIMO_PASSWORD))
    elif len(password.encode('utf-8')) > LARGO_MAXIMO_PASSWORD:
        errores.append('La contrasena no puede pasar de {} bytes.'
                       .format(LARGO_MAXIMO_PASSWORD))
    campos['password'] = password

    return campos, errores


# =============================================================================
# Verificacion del correo contra Postfix
#
# Tres capas, de la mas barata a la mas cara:
#   1. Sintaxis           -> validar_registro, arriba
#   2. El dominio existe  -> lo hace Postfix (reject_unknown_recipient_domain)
#   3. El buzon existe    -> sonda RCPT TO contra Postfix en 127.0.0.1:25
#
# El paso 2 no se duplica aqui con una consulta MX propia: Postfix ya la hace,
# la cachea y distingue un dominio inexistente (5.1.2) de un fallo transitorio
# de DNS. Repetirla en Python anadiria una dependencia (dnspython), una segunda
# consulta y dos respuestas que podrian no coincidir.
#
# La sonda NUNCA envia correo: abre el dialogo, dice MAIL FROM y RCPT TO, lee el
# codigo y cuelga. No llega a DATA.
#
# Como se interpreta la respuesta —esto es lo importante—:
#
#   250  el buzon existe                    -> se registra, verificado
#   5xx  no existe (buzon o dominio)        -> 400, rechazo explicado
#   4xx  no se pudo comprobar               -> se registra, NO verificado
#   sin Postfix / timeout                   -> se registra, NO verificado
#
# Un 4xx NO es un "no existe". Convertir un "no se" en un rechazo dejaria fuera
# a usuarios legitimos cada vez que el otro extremo aplica greylisting, tarda o
# —como en esta VM— no se puede alcanzar. En esta instalacion concreta TODO
# dominio externo cae en ese caso: GCP bloquea la salida por el puerto 25, asi
# que Postfix contesta "Network is unreachable" y devuelve 450. La verificacion
# real de terceros no es posible aqui, y el servicio lo dice en vez de fingir.
#
# Y aunque el 25 estuviera abierto, la verificacion por SMTP tendria techo: un
# dominio "catch-all" acepta cualquier direccion, asi que un 250 tampoco
# probaria que el buzon existe. Por eso el unico resultado en el que se confia
# para RECHAZAR es el 5xx.
# =============================================================================
CORREO_VERIFICADO = 'verificado'
CORREO_INEXISTENTE = 'inexistente'
CORREO_NO_VERIFICABLE = 'no_verificable'


def verificar_correo(email):
    """Devuelve {'estado', 'codigo', 'mensaje'}. No lanza excepciones."""
    if not VERIFICAR_CORREO:
        return {'estado': CORREO_NO_VERIFICABLE, 'codigo': 0,
                'mensaje': 'La verificacion por SMTP esta desactivada.'}

    servidor = None
    try:
        servidor = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT)
        servidor.ehlo('libreria.local')
        servidor.mail(SMTP_REMITENTE)
        codigo, respuesta = servidor.rcpt(email)
        detalle = respuesta.decode('utf-8', 'replace') if isinstance(
            respuesta, bytes) else str(respuesta)
    except (smtplib.SMTPException, socket.error, OSError) as error:
        # Postfix caido o inalcanzable. No se puede comprobar, pero tampoco es
        # motivo para negarle el registro a nadie: el correo no es el sistema
        # de autenticacion, solo un dato de la cuenta.
        log.warning('No se pudo consultar a Postfix en %s:%s: %s',
                    SMTP_HOST, SMTP_PORT, error)
        return {'estado': CORREO_NO_VERIFICABLE, 'codigo': 0,
                'mensaje': 'El verificador de correo no esta disponible.'}
    finally:
        if servidor is not None:
            try:
                servidor.quit()
            except smtplib.SMTPException:
                pass

    if 200 <= codigo < 300:
        return {'estado': CORREO_VERIFICADO, 'codigo': codigo,
                'mensaje': 'El servidor de correo confirma que la direccion existe.'}
    if 500 <= codigo < 600:
        return {'estado': CORREO_INEXISTENTE, 'codigo': codigo,
                'mensaje': _motivo_rechazo(detalle)}
    return {'estado': CORREO_NO_VERIFICABLE, 'codigo': codigo,
            'mensaje': 'No se pudo comprobar la direccion en este momento.'}


def _motivo_rechazo(detalle):
    """Traduce el rechazo de Postfix sin devolverle al cliente su texto crudo.

    El mensaje de Postfix lleva el nombre del host, la IP del destino y a veces
    la topologia de la red. Nada de eso le sirve a quien se esta registrando, y
    si le sirve a alguien, es a quien esta explorando la instalacion.
    """
    plano = (detalle or '').lower()
    if 'domain not found' in plano or 'domain' in plano and 'not found' in plano:
        return 'El dominio del correo no existe.'
    return 'El servidor de correo rechaza esa direccion: no existe el buzon.'


# =============================================================================
# Acceso a datos. Todo el SQL vive aqui y va siempre parametrizado.
# =============================================================================
SELECT_USUARIO = """
    SELECT u.id, u.email, u.rol, u.activo, u.nombre AS nombre_completo,
           p.nombre, p.apellido_paterno, p.apellido_materno
    FROM usuarios u JOIN personas p ON p.id = u.persona_id
"""


def _a_usuario(fila):
    """Fila de la base -> estructura neutra. password_hash nunca llega aqui."""
    return {
        'id': fila['id'],
        'nombre': fila['nombre'],
        'apellido_paterno': fila['apellido_paterno'],
        'apellido_materno': fila['apellido_materno'],
        'nombre_completo': fila['nombre_completo'],
        'email': fila['email'],
        'rol': fila['rol'],
    }


def crear_usuario(campos):
    """Alta en una sola transaccion: primero la persona, luego la cuenta.

    `usuarios.nombre` NO se escribe. Lo compone el disparador
    trg_usuario_sincroniza_alta a partir de la persona; si lo escribiera este
    servicio, habria dos fuentes para el mismo dato y podrian discrepar.

    El rol tampoco se toma de la peticion: siempre 'lector'. Si viniera del
    cuerpo, cualquiera podria registrarse como administrador mandando
    rol=admin, igual que ya evita src/modules/auth/auth.model.js.
    """
    hash_bcrypt = bcrypt.hashpw(
        campos['password'].encode('utf-8'),
        bcrypt.gensalt(rounds=RONDAS_BCRYPT)).decode('ascii')

    with _obtener_pool().connection() as conexion:
        with conexion.cursor() as cur:
            cur.execute(
                """INSERT INTO personas (nombre, apellido_paterno, apellido_materno)
                   VALUES (%s, %s, %s) RETURNING id""",
                (campos['nombre'], campos['apellido_paterno'],
                 campos['apellido_materno']))
            persona_id = cur.fetchone()['id']

            cur.execute(
                """INSERT INTO usuarios (persona_id, email, password_hash, rol)
                   VALUES (%s, %s, %s, 'lector') RETURNING id""",
                (persona_id, campos['email'], hash_bcrypt))
            usuario_id = cur.fetchone()['id']

            cur.execute(SELECT_USUARIO + ' WHERE u.id = %s', (usuario_id,))
            return _a_usuario(cur.fetchone())


def buscar_por_email(email):
    with _obtener_pool().connection() as conexion:
        with conexion.cursor() as cur:
            cur.execute(SELECT_USUARIO + ' WHERE u.email = lower(btrim(%s))',
                        (email,))
            return cur.fetchone()


def buscar_hash(email):
    with _obtener_pool().connection() as conexion:
        with conexion.cursor() as cur:
            cur.execute(
                'SELECT password_hash FROM usuarios WHERE email = lower(btrim(%s))',
                (email,))
            fila = cur.fetchone()
            return fila['password_hash'] if fila else None


def buscar_por_id(usuario_id):
    with _obtener_pool().connection() as conexion:
        with conexion.cursor() as cur:
            cur.execute(SELECT_USUARIO + ' WHERE u.id = %s', (usuario_id,))
            return cur.fetchone()


# Hash de descarte con el que se compara cuando el correo no existe. Sin esto,
# responder a un correo inexistente seria notablemente mas rapido que responder
# a una contrasena incorrecta, y esa diferencia de tiempo revela que correos
# estan registrados. Es la misma defensa que gastarTiempoDeComparacion() del
# monolito. No es la contrasena de nadie: es un hash de un valor aleatorio
# generado al arrancar, que nunca sale del proceso.
HASH_SENUELO = bcrypt.hashpw(os.urandom(32), bcrypt.gensalt(rounds=RONDAS_BCRYPT))


def contrasena_correcta(password, hash_guardado):
    objetivo = hash_guardado.encode('ascii') if hash_guardado else HASH_SENUELO
    try:
        return bcrypt.checkpw(password.encode('utf-8'), objetivo) and bool(hash_guardado)
    except ValueError:
        # Hash con un formato que bcrypt no entiende. No se cuela nadie.
        log.error('Hash almacenado ilegible para un inicio de sesion.')
        return False


# =============================================================================
# Endpoints
# =============================================================================
@app.route('/register', methods=['POST'])
def registrar():
    campos, errores = validar_registro(datos_entrantes())
    if errores:
        return error_respuesta(400, 'Los datos del registro no son validos.', errores)

    # El correo se comprueba ANTES de tocar la base: no tiene sentido abrir una
    # transaccion para una direccion que vamos a rechazar.
    correo = verificar_correo(campos['email'])
    if correo['estado'] == CORREO_INEXISTENTE:
        return error_respuesta(400, 'El correo no existe.', [correo['mensaje']])

    try:
        usuario = crear_usuario(campos)
    except psycopg.errors.UniqueViolation:
        # 409 y no 400: la peticion es valida, choca con el estado del servidor.
        # El mensaje no dice cual de las dos cuentas es, solo que ya existe.
        return error_respuesta(409, 'Ese correo ya tiene una cuenta.')
    except psycopg.errors.CheckViolation as error:
        log.warning('Restriccion de la base rechazo un alta: %s', error)
        return error_respuesta(400, 'Los datos del registro no son validos.')

    log.info('Alta de usuario %s (correo %s)', usuario['id'], correo['estado'])
    return responder('registro', {'usuario': usuario, 'correo': correo}, 201)


@app.route('/login', methods=['POST'])
def iniciar_sesion():
    datos = datos_entrantes()
    email = _texto(datos.get('email')).lower()
    password = datos.get('password') or ''

    if not email or not password:
        return error_respuesta(400, 'Faltan el correo o la contrasena.')

    fila = buscar_por_email(email)
    guardado = buscar_hash(email) if fila else None

    # Se compara siempre, exista o no la cuenta, para que el tiempo de respuesta
    # no revele que correos estan registrados.
    valida = contrasena_correcta(password, guardado)

    # Un solo mensaje para las tres causas —correo desconocido, contrasena mala,
    # cuenta desactivada—. Distinguirlas seria mas amable y convertiria el
    # endpoint en un comprobador de que correos tienen cuenta aqui.
    if not fila or not valida or not fila['activo']:
        log.info('Inicio de sesion fallido para %r', email)
        return error_respuesta(401, 'Correo o contrasena incorrectos.')

    usuario = _a_usuario(fila)
    session.clear()
    # Renovar el identificador de sesion al autenticar evita la fijacion de
    # sesion: una cookie obtenida antes del login no sirve despues.
    session['usuario_id'] = usuario['id']
    session['rol'] = usuario['rol']
    session.permanent = False

    log.info('Sesion iniciada para el usuario %s', usuario['id'])
    return responder('sesion', {'autenticada': True, 'usuario': usuario,
                                'mensaje': 'Sesion iniciada.'})


@app.route('/logout', methods=['POST'])
def cerrar_sesion():
    habia = 'usuario_id' in session
    session.clear()
    # 200 tanto si habia sesion como si no: cerrar una sesion que no existe deja
    # el sistema en el estado pedido, que es la definicion de exito.
    return responder('resultado', {
        'ok': True,
        'mensaje': 'Sesion cerrada.' if habia else 'No habia ninguna sesion abierta.'})


@app.route('/session', methods=['GET'])
def consultar_sesion():
    usuario_id = session.get('usuario_id')
    if not usuario_id:
        return responder('sesion', {'autenticada': False,
                                    'mensaje': 'No hay ninguna sesion abierta.'})

    # No basta con creer a la cookie: la cuenta pudo borrarse o desactivarse
    # despues de firmarla. La cookie dice quien dijo ser, no quien sigue siendo.
    fila = buscar_por_id(usuario_id)
    if not fila or not fila['activo']:
        session.clear()
        return responder('sesion', {
            'autenticada': False,
            'mensaje': 'La sesion ya no es valida.'}, 401)

    return responder('sesion', {'autenticada': True, 'usuario': _a_usuario(fila)})


@app.route('/health', methods=['GET'])
def salud():
    componentes = {}

    try:
        with _obtener_pool().connection() as conexion:
            with conexion.cursor() as cur:
                cur.execute('SELECT count(*) AS n FROM usuarios')
                cur.fetchone()
        componentes['base_de_datos'] = {'estado': 'ok', 'detalle': 'Conexion establecida.'}
    except Exception as error:                       # noqa: BLE001 - se reporta, no se propaga
        log.error('Health: PostgreSQL no responde: %s', error)
        componentes['base_de_datos'] = {'estado': 'error',
                                        'detalle': 'Sin conexion con PostgreSQL.'}

    if VERIFICAR_CORREO:
        try:
            smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT).quit()
            componentes['correo'] = {'estado': 'ok', 'detalle': 'Postfix responde.'}
        except (smtplib.SMTPException, socket.error, OSError):
            # Degradado y no error: sin Postfix el registro sigue funcionando,
            # solo deja de poder verificar la direccion.
            componentes['correo'] = {'estado': 'degradado',
                                     'detalle': 'Postfix no responde.'}
    else:
        componentes['correo'] = {'estado': 'desactivado',
                                 'detalle': 'Verificacion por SMTP desactivada.'}

    hay_error = any(c['estado'] == 'error' for c in componentes.values())
    datos = {
        'estado': 'error' if hay_error else 'ok',
        'servicio': 'login-libreria',
        'version': VERSION,
        'componentes': componentes,
    }
    # 503 cuando algo esencial esta caido: un monitor no deberia tener que leer
    # el cuerpo para enterarse de que el servicio no puede trabajar.
    return responder('salud', datos, 503 if hay_error else 200)


@app.route('/', methods=['GET'])
def indice():
    return responder('servicio', {
        'nombre': 'login-libreria',
        'version': VERSION,
        'endpoints': [
            {'ruta': '/register', 'metodo': 'POST', 'descripcion': 'Alta de usuario'},
            {'ruta': '/login', 'metodo': 'POST', 'descripcion': 'Autenticar y abrir sesion'},
            {'ruta': '/logout', 'metodo': 'POST', 'descripcion': 'Cerrar la sesion'},
            {'ruta': '/session', 'metodo': 'GET', 'descripcion': 'Consultar la sesion'},
            {'ruta': '/health', 'metodo': 'GET', 'descripcion': 'Estado del servicio'},
            {'ruta': '/docs', 'metodo': 'GET', 'descripcion': 'Documentacion Swagger'},
        ],
    })


# =============================================================================
# Errores. El cliente recibe el formato que pidio; la traza se queda en el log.
# =============================================================================
@app.errorhandler(404)
def _no_encontrado(_error):
    return error_respuesta(404, 'El recurso solicitado no existe.',
                           ['Consulta la documentacion en /docs.'])


@app.errorhandler(405)
def _metodo_no_permitido(_error):
    return error_respuesta(405, 'Ese metodo HTTP no esta permitido en esta ruta.')


@app.errorhandler(psycopg.OperationalError)
def _sin_base(error):
    log.error('Sin conexion con PostgreSQL: %s', error)
    return error_respuesta(503, 'El servicio no puede conectarse a su base de datos.')


@app.errorhandler(Exception)
def _fallo_inesperado(error):
    if isinstance(error, HTTPException):
        return error_respuesta(error.code or 500, 'La solicitud no se pudo atender.')
    log.exception('Fallo no controlado: %s', error)
    return error_respuesta(500, 'Ocurrio un error al procesar la solicitud.')


# =============================================================================
# Documentacion Swagger (OpenAPI 3): la especificacion en /apispec.json y la
# interfaz en /docs. Se escribe a mano en vez de generarla con flasgger para no
# anadir una dependencia que hay que mantener alineada con la version de Flask;
# la interfaz se carga de un CDN.
#
# Cada operacion declara sus DOS respuestas, application/xml y
# application/json. El parametro `format` no se repite operacion por operacion:
# lo inyecta _documentar() al final, porque olvidarlo en una sola la dejaria
# documentada como si no admitiera JSON.
# =============================================================================
def _respuesta(descripcion, ejemplo_xml, ejemplo_json):
    return {
        'description': descripcion,
        'content': {
            'application/xml': {'schema': {'type': 'string'},
                                'example': ejemplo_xml},
            'application/json': {'schema': {'type': 'object'},
                                 'example': ejemplo_json},
        },
    }


EJEMPLO_USUARIO_JSON = {
    'id': 31, 'nombre': 'Ana', 'apellido_paterno': 'Ruiz',
    'apellido_materno': 'Lopez', 'nombre_completo': 'Ana Ruiz Lopez',
    'email': 'ana.ruiz@example.com', 'rol': 'lector',
}
EJEMPLO_USUARIO_XML = (
    '<usuario id="31">\n'
    '  <nombre>Ana</nombre>\n'
    '  <apellido_paterno>Ruiz</apellido_paterno>\n'
    '  <apellido_materno>Lopez</apellido_materno>\n'
    '  <nombre_completo>Ana Ruiz Lopez</nombre_completo>\n'
    '  <email>ana.ruiz@example.com</email>\n'
    '  <rol>lector</rol>\n'
    '</usuario>')

EJEMPLO_ERROR_XML = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                     '<error codigo="400">\n'
                     '  <mensaje>Los datos del registro no son validos.</mensaje>\n'
                     '  <detalle>El apellido paterno es obligatorio.</detalle>\n'
                     '</error>')
EJEMPLO_ERROR_JSON = {'codigo': 400,
                      'mensaje': 'Los datos del registro no son validos.',
                      'detalles': ['El apellido paterno es obligatorio.']}


def _error(descripcion, codigo=400, mensaje=None):
    xml = EJEMPLO_ERROR_XML.replace('400', str(codigo))
    js = dict(EJEMPLO_ERROR_JSON, codigo=codigo)
    if mensaje:
        js = {'codigo': codigo, 'mensaje': mensaje, 'detalles': []}
        xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<error codigo="{}">\n  <mensaje>{}</mensaje>\n</error>'
               .format(codigo, mensaje))
    return _respuesta(descripcion, xml, js)


CUERPO_REGISTRO = {
    'required': True,
    'description': ('Los cinco campos del enunciado. Se aceptan como '
                    'formulario (application/x-www-form-urlencoded) o como '
                    'JSON, con independencia del formato que se pida para la '
                    'respuesta.'),
    'content': {
        'application/x-www-form-urlencoded': {'schema': {
            'type': 'object',
            'required': ['nombre', 'apellido_paterno', 'apellido_materno',
                         'email', 'password'],
            'properties': {
                'nombre': {'type': 'string', 'maxLength': 100, 'example': 'Ana'},
                'apellido_paterno': {'type': 'string', 'maxLength': 100, 'example': 'Ruiz'},
                'apellido_materno': {'type': 'string', 'maxLength': 100, 'example': 'Lopez'},
                'email': {'type': 'string', 'maxLength': 150,
                          'example': 'ana.ruiz@example.com'},
                'password': {'type': 'string', 'format': 'password',
                             'minLength': 8, 'maxLength': 72},
            }}},
        'application/json': {'schema': {'type': 'object'}},
    },
}

CUERPO_LOGIN = {
    'required': True,
    'content': {
        'application/x-www-form-urlencoded': {'schema': {
            'type': 'object',
            'required': ['email', 'password'],
            'properties': {
                'email': {'type': 'string', 'example': 'ana.ruiz@example.com'},
                'password': {'type': 'string', 'format': 'password'},
            }}},
        'application/json': {'schema': {'type': 'object'}},
    },
}

ESPECIFICACION = {
    'openapi': '3.0.3',
    'info': {
        'title': 'Autenticacion de la Libreria Online',
        'version': VERSION,
        'description': (
            'Microservicio Flask de registro y sesion, sobre la misma base '
            'PostgreSQL que el monolito.\n\n'
            '**Formato.** Todos los endpoints responden en XML o en JSON '
            'indistintamente, segun el parametro `format`: `?format=json` '
            'devuelve `application/json`, y `?format=xml` —o la ausencia del '
            'parametro— devuelve `application/xml`. Cualquier otro valor es un '
            '400. Los errores viajan en el mismo formato que se pidio.\n\n'
            '**El nombre.** El alta pide nombre y los dos apellidos por '
            'separado, y asi se guardan, en la tabla `personas`. La tabla '
            '`usuarios` conserva una columna `nombre` con el nombre completo '
            'porque el monolito la lee y la escribe; la mantiene al dia un '
            'disparador, no este servicio.\n\n'
            '**La contrasena** nunca se almacena ni se registra en claro: solo '
            'su hash bcrypt, el mismo formato que usa el monolito, de modo que '
            'una cuenta creada aqui puede iniciar sesion alla.\n\n'
            '**El correo** se comprueba contra el Postfix local antes de dar '
            'de alta. Un rechazo firme (5xx) es un 400; un "no se pudo '
            'comprobar" (4xx) deja registrar y se reporta como '
            '`no_verificable`. En esta instalacion GCP bloquea la salida por '
            'el puerto 25, asi que todo dominio externo cae en ese segundo '
            'caso: el servicio lo dice en lugar de fingir que verifico.'),
    },
    'servers': [{'url': '/', 'description': 'Este servidor'}],
    'tags': [
        {'name': 'Cuentas', 'description': 'Alta de usuarios'},
        {'name': 'Sesion', 'description': 'Entrar, salir y consultar'},
        {'name': 'Servicio', 'description': 'Estado del microservicio'},
    ],
    'paths': {
        '/register': {'post': {
            'tags': ['Cuentas'],
            'summary': 'Registrar un nuevo usuario',
            'description': (
                'Valida los datos, comprueba el correo contra Postfix y crea '
                'la persona y la cuenta en una sola transaccion. El rol es '
                'siempre `lector`: no se toma de la peticion.'),
            'requestBody': CUERPO_REGISTRO,
            'responses': {
                '201': _respuesta(
                    'Usuario creado. `correo.estado` vale `verificado`, '
                    '`no_verificable` o —si fuera `inexistente`— no se llega aqui.',
                    '<?xml version="1.0" encoding="UTF-8"?>\n<registro>\n'
                    + '\n'.join('  ' + l for l in EJEMPLO_USUARIO_XML.split('\n'))
                    + '\n  <correo estado="no_verificable" codigo="450">'
                      'No se pudo comprobar la direccion en este momento.</correo>\n'
                      '</registro>',
                    {'usuario': EJEMPLO_USUARIO_JSON,
                     'correo': {'estado': 'no_verificable', 'codigo': 450,
                                'mensaje': 'No se pudo comprobar la direccion '
                                           'en este momento.'}}),
                '400': _error('Datos invalidos, o el correo no existe (5xx de Postfix).'),
                '409': _error('Ese correo ya tiene una cuenta.', 409,
                              'Ese correo ya tiene una cuenta.'),
                '503': _error('Sin conexion con PostgreSQL.', 503,
                              'El servicio no puede conectarse a su base de datos.'),
            }}},
        '/login': {'post': {
            'tags': ['Sesion'],
            'summary': 'Autenticar al usuario e iniciar sesion',
            'description': (
                'Compara la contrasena contra el hash bcrypt guardado y, si '
                'coincide, abre una sesion del lado de Flask: una cookie '
                'firmada, HttpOnly y SameSite=Lax. Correo desconocido, '
                'contrasena incorrecta y cuenta desactivada devuelven el mismo '
                '401, para no convertir el endpoint en un comprobador de que '
                'correos tienen cuenta.'),
            'requestBody': CUERPO_LOGIN,
            'responses': {
                '200': _respuesta(
                    'Sesion iniciada. La cookie de sesion viaja en Set-Cookie.',
                    '<?xml version="1.0" encoding="UTF-8"?>\n<sesion autenticada="true">\n'
                    + '\n'.join('  ' + l for l in EJEMPLO_USUARIO_XML.split('\n'))
                    + '\n  <mensaje>Sesion iniciada.</mensaje>\n</sesion>',
                    {'autenticada': True, 'usuario': EJEMPLO_USUARIO_JSON,
                     'mensaje': 'Sesion iniciada.'}),
                '400': _error('Faltan el correo o la contrasena.', 400,
                              'Faltan el correo o la contrasena.'),
                '401': _error('Credenciales incorrectas.', 401,
                              'Correo o contrasena incorrectos.'),
            }}},
        '/logout': {'post': {
            'tags': ['Sesion'],
            'summary': 'Cerrar la sesion',
            'description': (
                'Vacia la sesion. Devuelve 200 aunque no hubiera ninguna '
                'abierta: el estado pedido queda alcanzado igual.'),
            'responses': {
                '200': _respuesta(
                    'Sesion cerrada.',
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<resultado ok="true">\n  <mensaje>Sesion cerrada.</mensaje>\n'
                    '</resultado>',
                    {'ok': True, 'mensaje': 'Sesion cerrada.'}),
            }}},
        '/session': {'get': {
            'tags': ['Sesion'],
            'summary': 'Consultar si existe una sesion autenticada',
            'description': (
                'No se limita a leer la cookie: vuelve a consultar la cuenta, '
                'porque pudo borrarse o desactivarse despues de firmarla.'),
            'responses': {
                '200': _respuesta(
                    'Hay sesion, o no la hay (`autenticada` lo dice).',
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<sesion autenticada="false">\n'
                    '  <mensaje>No hay ninguna sesion abierta.</mensaje>\n</sesion>',
                    {'autenticada': False,
                     'mensaje': 'No hay ninguna sesion abierta.'}),
                '401': _respuesta(
                    'La cookie era valida pero la cuenta ya no lo es.',
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<sesion autenticada="false">\n'
                    '  <mensaje>La sesion ya no es valida.</mensaje>\n</sesion>',
                    {'autenticada': False, 'mensaje': 'La sesion ya no es valida.'}),
            }}},
        '/health': {'get': {
            'tags': ['Servicio'],
            'summary': 'Verificar el estado del microservicio y PostgreSQL',
            'description': (
                'Comprueba PostgreSQL y Postfix. Postfix caido es `degradado`, '
                'no `error`: sin el, el registro sigue funcionando y solo deja '
                'de poder verificar la direccion. Devuelve 503 cuando algo '
                'esencial esta caido.'),
            'responses': {
                '200': _respuesta(
                    'El servicio puede trabajar.',
                    '<?xml version="1.0" encoding="UTF-8"?>\n<salud estado="ok">\n'
                    '  <servicio>login-libreria</servicio>\n'
                    '  <version>' + VERSION + '</version>\n'
                    '  <base_de_datos estado="ok">Conexion establecida.</base_de_datos>\n'
                    '  <correo estado="ok">Postfix responde.</correo>\n</salud>',
                    {'estado': 'ok', 'servicio': 'login-libreria',
                     'version': VERSION,
                     'componentes': {
                         'base_de_datos': {'estado': 'ok',
                                           'detalle': 'Conexion establecida.'},
                         'correo': {'estado': 'ok', 'detalle': 'Postfix responde.'}}}),
                '503': _error('PostgreSQL no responde.', 503,
                              'El servicio no puede conectarse a su base de datos.'),
            }}},
        '/': {'get': {
            'tags': ['Servicio'],
            'summary': 'Indice de endpoints',
            'responses': {'200': _respuesta(
                'Lista de endpoints.',
                '<?xml version="1.0" encoding="UTF-8"?>\n<servicio>…</servicio>',
                {'nombre': 'login-libreria', 'version': VERSION, 'endpoints': []})},
        }},
    },
}

PARAM_FORMATO = {
    'name': 'format', 'in': 'query', 'required': False,
    'description': 'json para JSON; xml o ausente para XML.',
    'schema': {'type': 'string', 'enum': list(FORMATOS), 'default': 'xml'},
}


def _documentar(rutas):
    """Agrega el parametro `format` a todas las operaciones, sin excepcion."""
    for operaciones in rutas.values():
        for operacion in operaciones.values():
            operacion.setdefault('parameters', []).append(PARAM_FORMATO)
    return rutas


ESPECIFICACION['paths'] = _documentar(ESPECIFICACION['paths'])


@app.route('/apispec.json', methods=['GET'])
def especificacion():
    # Con json.dumps y no con jsonify: la especificacion es documentacion, no
    # una respuesta del contrato, y no debe pasar por el despachador de formato.
    return Response(json.dumps(ESPECIFICACION, ensure_ascii=False, indent=2),
                    content_type='application/json; charset=utf-8')


PAGINA_DOCS = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>API de autenticacion — Libreria Online</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body style="margin:0">
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: "__SPEC__",
      dom_id: "#swagger-ui",
      deepLinking: true,
      tryItOutEnabled: true
    });
  </script>
</body>
</html>"""


@app.route('/docs', methods=['GET'])
@app.route('/docs/', methods=['GET'])
def documentacion():
    return Response(PAGINA_DOCS.replace('__SPEC__', url_for('especificacion')),
                    content_type='text/html; charset=utf-8')


if __name__ == '__main__':
    if not BD['password']:
        log.warning('DB_PASSWORD viene vacia: revisa apps/services/login/.env')
    # Gunicorn en la VM; esto es solo para desarrollo. Ver
    # deploy/libreria-login.service.
    app.run(host=APP_HOST, port=APP_PORT, debug=False)
