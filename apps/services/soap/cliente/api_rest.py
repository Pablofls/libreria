# =============================================================================
# cliente/api_rest.py — cliente HTTP/JWT de los microservicios REST.
#
# Lo usa cliente_escritorio.py (las pestañas de Libros, Autores, Usuarios,
# Pedidos y Pagos). Solo biblioteca estandar, igual que el resto del cliente.
#
# REGLAS QUE ESTE ARCHIVO RESPETA
#   - Nunca desactiva la verificacion del certificado. El servidor usa un
#     certificado autofirmado (no hay dominio): se confia en el, y solo en el,
#     con CA_CERT=<copia del .crt>. Sin CA_CERT se usan las raices del sistema.
#   - Los tokens viven solo en memoria. No se escriben a disco ni a ningun log.
#   - La contrasena se usa en login() y no se conserva.
#   - El JWT se renueva con el refresh_token ANTES de caducar (a menos de
#     MARGEN_RENOVACION segundos). Un 401 provoca un solo reintento renovando.
#   - La GUI no ve excepciones de red ni texto crudo: ErrorApi trae un mensaje
#     en castellano. El texto del servidor solo se muestra si es su campo
#     `mensaje`/`detalles` (el servidor los escribe pensando en el usuario).
# =============================================================================

import base64
import json
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

API_BASE = os.getenv('API_BASE', 'https://127.0.0.1').rstrip('/')
CA_CERT = os.getenv('CA_CERT') or None
MARGEN_RENOVACION = 60          # segundos antes de que venza el JWT
TIMEOUT = 15
TIMEOUT_SEMAFORO = 4

SERVICIOS = ('login', 'users', 'authors', 'pedidos', 'pagos', 'catalogo')

MENSAJES_HTTP = {
    400: 'Revisa los datos capturados.',
    401: 'Tu sesion no es valida o expiro. Inicia sesion de nuevo.',
    403: 'No tienes permiso para esta operacion.',
    404: 'Ese registro ya no existe. Actualiza la lista.',
    409: 'La operacion choca con el estado actual de los datos.',
    429: 'Demasiados intentos. Espera unos minutos.',
    503: 'El servicio no esta disponible en este momento (puede ser Redis o '
         'la base de datos). Intenta de nuevo en unos segundos.',
}


class ErrorApi(Exception):
    """Error ya traducido para una persona. `estado` 0 = no hubo respuesta."""

    def __init__(self, estado, mensaje, detalles=()):
        super().__init__(mensaje)
        self.estado = estado
        self.mensaje = mensaje
        self.detalles = list(detalles)

    def texto(self):
        if self.detalles:
            return '{}\n\n- {}'.format(self.mensaje, '\n- '.join(self.detalles))
        return self.mensaje


def contexto_ssl(ca_cert=None):
    """Contexto que VERIFICA el certificado; con ca_cert confia en ese archivo."""
    return ssl.create_default_context(cafile=ca_cert) if ca_cert \
        else ssl.create_default_context()


def reclamos_sin_verificar(token):
    """Lee el payload del JWT SOLO para saber cuando vence y quien es: la
    verificacion de la firma es cosa de los servicios, no de la GUI."""
    try:
        cuerpo = token.split('.')[1]
        cuerpo += '=' * (-len(cuerpo) % 4)
        return json.loads(base64.urlsafe_b64decode(cuerpo))
    except (IndexError, ValueError):
        return {}


def _necesita_formato(ruta):
    # login y catalogo responden XML por omision: se pide JSON.
    return ruta.split('?')[0].startswith(
        ('/login', '/logout', '/token', '/session', '/books', '/concepts'))


class ClienteApi:
    """Sesion contra los servicios. Seguro para usarse desde varios hilos."""

    def __init__(self, base=None, ca_cert=None):
        self.base = (base or API_BASE).rstrip('/')
        self.ca_cert = ca_cert if ca_cert is not None else CA_CERT
        self._contexto = contexto_ssl(self.ca_cert) \
            if self.base.startswith('https') else None
        self._cerrojo = threading.RLock()
        self._limpiar()

    # --- Estado de la sesion -------------------------------------------------
    def _limpiar(self):
        self.token = None
        self.refresh = None
        self.expira = 0
        self.usuario = None

    @property
    def sesion_activa(self):
        return bool(self.token)

    @property
    def es_admin(self):
        return bool(self.usuario) and self.usuario.get('rol') == 'admin'

    def segundos_restantes(self):
        return int(self.expira - time.time()) if self.token else 0

    def _guardar(self, cuerpo):
        self.token = cuerpo['token']
        self.refresh = cuerpo['refresh_token']
        reclamos = reclamos_sin_verificar(self.token)
        self.expira = reclamos.get('exp', time.time() + 20 * 60)
        usuario = cuerpo.get('usuario') or self.usuario or {}
        self.usuario = dict(usuario, rol=reclamos.get('rol', usuario.get('rol')),
                            id=reclamos.get('user_id', usuario.get('id')))

    # --- Red -----------------------------------------------------------------
    def _enviar(self, metodo, ruta, cuerpo=None, token=None, timeout=TIMEOUT):
        """(estado, datos|None). Traduce los fallos de red a ErrorApi(0, ...)."""
        if _necesita_formato(ruta) and 'format=' not in ruta:
            ruta += ('&' if '?' in ruta else '?') + 'format=json'
        datos = json.dumps(cuerpo).encode('utf-8') if cuerpo is not None else None
        cabeceras = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if token:
            cabeceras['Authorization'] = 'Bearer ' + token
        peticion = urllib.request.Request(self.base + ruta, data=datos,
                                          headers=cabeceras, method=metodo)
        try:
            with urllib.request.urlopen(peticion, timeout=timeout,
                                        context=self._contexto) as r:
                crudo, estado = r.read(), r.status
        except urllib.error.HTTPError as error:
            crudo, estado = error.read(), error.code
        except ssl.SSLError:
            raise ErrorApi(0, 'El certificado del servidor no es de confianza. '
                              'Indica el archivo con CA_CERT.')
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLError):
                raise ErrorApi(0, 'El certificado del servidor no es de '
                                  'confianza. Indica el archivo con CA_CERT.')
            raise ErrorApi(0, 'No se pudo conectar con el servidor.')
        except (socket.timeout, TimeoutError, OSError):
            raise ErrorApi(0, 'El servidor tardo demasiado en responder.')
        try:
            return estado, (json.loads(crudo) if crudo else None)
        except ValueError:
            return estado, None

    def _a_error(self, estado, datos):
        mensaje = MENSAJES_HTTP.get(estado, 'El servicio respondio con un error.')
        detalles = []
        if isinstance(datos, dict):
            # Los servicios escriben estos campos para la persona, sin SQL ni trazas.
            mensaje = datos.get('mensaje') or datos.get('message') or mensaje
            detalles = [str(d) for d in (datos.get('detalles') or datos.get('details') or [])]
        return ErrorApi(estado, mensaje, detalles)

    # --- Sesion --------------------------------------------------------------
    def iniciar_sesion(self, email, password):
        estado, datos = self._enviar('POST', '/login',
                                     {'email': email, 'password': password})
        if estado != 200 or not isinstance(datos, dict) or not datos.get('token'):
            raise self._a_error(estado, datos)
        with self._cerrojo:
            self._guardar(datos)
        return self.usuario

    def cerrar_sesion(self):
        """Revoca el JWT en el servidor. Si no se puede (503, sin red) NO se
        olvida la sesion: seguiria viva, y la GUI debe avisarlo."""
        if not self.sesion_activa:
            return
        estado, datos = self._enviar('POST', '/logout',
                                     {'refresh_token': self.refresh}, token=self.token)
        if estado != 200:
            raise self._a_error(estado, datos)
        with self._cerrojo:
            self._limpiar()

    def olvidar_sesion(self):
        """Solo local: para cuando el servidor ya dio la sesion por perdida."""
        with self._cerrojo:
            self._limpiar()

    def renovar(self):
        """Cambia el refresh_token por JWT + refresh nuevos. False si la sesion
        ya no existe (se limpia); ErrorApi si el servidor no pudo responder."""
        with self._cerrojo:
            if not self.refresh:
                return False
            estado, datos = self._enviar('POST', '/token/refresh',
                                         {'refresh_token': self.refresh})
            if estado == 200 and isinstance(datos, dict) and datos.get('token'):
                self._guardar(datos)
                return True
            if estado == 401:
                self._limpiar()
                return False
            raise self._a_error(estado, datos)

    def renovar_si_hace_falta(self):
        """Llamar a menudo: renueva cuando faltan menos de MARGEN_RENOVACION s."""
        with self._cerrojo:
            if self.sesion_activa and self.segundos_restantes() < MARGEN_RENOVACION:
                return self.renovar()
        return self.sesion_activa

    # --- Peticiones autenticadas ----------------------------------------------
    def peticion(self, metodo, ruta, cuerpo=None, autenticada=True, _reintento=True):
        """Devuelve el JSON de la respuesta (None si no hay cuerpo). Lanza ErrorApi."""
        token = None
        if autenticada:
            if not self.sesion_activa:
                raise ErrorApi(401, MENSAJES_HTTP[401])
            if not self.renovar_si_hace_falta():
                raise ErrorApi(401, MENSAJES_HTTP[401])
            token = self.token
        estado, datos = self._enviar(metodo, ruta, cuerpo, token)
        if estado == 401 and autenticada and _reintento:
            # El token pudo vencer o revocarse en el camino: una renovacion y
            # un solo reintento; si tampoco, la sesion se perdio.
            if self.renovar():
                return self.peticion(metodo, ruta, cuerpo, autenticada, _reintento=False)
        if estado >= 400:
            raise self._a_error(estado, datos)
        return datos

    def get(self, ruta, autenticada=True):
        return self.peticion('GET', ruta, autenticada=autenticada)

    # --- Recursos publicos (portadas) -----------------------------------------
    def descargar(self, ruta, limite=2_000_000):
        """Bytes de un recurso publico, sin JWT (las portadas). Mismo canal TLS
        verificado que el resto; tope de tamano para no leer algo desmedido."""
        peticion = urllib.request.Request(self.base + ruta, headers={'Accept': 'image/*'})
        try:
            with urllib.request.urlopen(peticion, timeout=TIMEOUT,
                                        context=self._contexto) as r:
                datos = r.read(limite + 1)
        except urllib.error.HTTPError as error:
            raise ErrorApi(error.code, 'No se encontro la imagen.')
        except (urllib.error.URLError, ssl.SSLError, socket.timeout, OSError):
            raise ErrorApi(0, 'No se pudo descargar la imagen.')
        if len(datos) > limite:
            raise ErrorApi(0, 'La imagen es demasiado grande.')
        return datos

    # --- Semaforos -----------------------------------------------------------
    def semaforo(self, servicio):
        """(color, detalle, redis) de un servicio, sin autenticacion.

        verde    ok y Redis ok
        amarillo responde, pero Redis caido o no configurado (degradado)
        rojo     no responde, o su base de datos esta caida (503)
        redis: 'ok' | 'caido' | 'no configurado' | None (sin dato)
        """
        try:
            estado, datos = self._enviar('GET', '/health/' + servicio,
                                         timeout=TIMEOUT_SEMAFORO)
        except ErrorApi as error:
            return 'rojo', error.mensaje, None
        if not isinstance(datos, dict):
            return 'rojo', 'Respuesta inesperada ({}).'.format(estado), None
        if servicio == 'login':
            componente = (datos.get('componentes') or {}).get('redis') or {}
            redis = {'ok': 'ok'}.get(componente.get('estado'), 'caido')
            if componente.get('detalle', '').startswith('REDIS_URL'):
                redis = 'no configurado'
            bien = datos.get('estado') == 'ok'
        else:
            redis = datos.get('redis')
            bien = (datos.get('estado') or datos.get('status')) == 'ok'
        if estado >= 500 or not bien:
            return 'rojo', 'El servicio no puede trabajar (base de datos).', redis
        if redis != 'ok':
            return 'amarillo', 'Funciona degradado: Redis {}.'.format(redis or '?'), redis
        return 'verde', 'Todo en orden.', redis


def probar_tcp(url, timeout=2):
    """Semaforo del SOAP: ¿alguien escucha en host:puerto de su endpoint?"""
    partes = urlparse(url)
    try:
        with socket.create_connection(
                (partes.hostname, partes.port or (443 if partes.scheme == 'https' else 80)),
                timeout=timeout):
            return True
    except OSError:
        return False
