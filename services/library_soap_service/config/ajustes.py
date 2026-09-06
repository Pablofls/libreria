# =============================================================================
# config/ajustes.py
# Unico punto del modulo que lee variables de entorno. El resto del codigo
# importa de aqui, de modo que se sabe de un vistazo que necesita el servicio
# para arrancar y donde buscar cuando falta algo.
#
# Ninguna credencial tiene valor por defecto: si falta, el servicio lo dice al
# arrancar en vez de fallar a mitad de una peticion.
# =============================================================================

import os
import pathlib

from dotenv import load_dotenv

RAIZ = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / '.env')


def _texto(nombre, defecto=None):
    valor = os.getenv(nombre, defecto)
    return valor.strip() if isinstance(valor, str) else valor


def _entero(nombre, defecto):
    try:
        return int(os.getenv(nombre, defecto))
    except (TypeError, ValueError):
        return int(defecto)


# --- PostgreSQL --------------------------------------------------------------
# El usuario por defecto es libreria_soap, el rol de minimo privilegio que crea
# sql/soap_module.sql. NUNCA postgres, y tampoco libreria_app: ese es del
# monolito y puede escribir en todas las tablas.
BD = {
    'host':     _texto('DB_HOST', '127.0.0.1'),
    'port':     _entero('DB_PORT', 5432),
    'dbname':   _texto('DB_NAME', 'libreria_db'),
    'user':     _texto('DB_USER', 'libreria_soap'),
    'password': _texto('DB_PASSWORD', ''),
    'connect_timeout': _entero('DB_TIMEOUT', 5),
    'application_name': 'modulo_soap_clasificador',
}
POOL_MAX = _entero('DB_POOL_MAX', 10)

# --- Servicio ----------------------------------------------------------------
HOST = _texto('SOAP_HOST', '127.0.0.1')
PUERTO = _entero('SOAP_PORT', 5001)
LOG_NIVEL = (_texto('LOG_NIVEL', 'INFO') or 'INFO').upper()

# Tamano maximo del sobre aceptado. Un POST sin limite es una invitacion a
# tumbar el servicio con un XML de gigabytes.
MAX_BYTES_PETICION = _entero('SOAP_MAX_BYTES', 262144)

# Cuantos conceptos devuelve ObtenerConceptosPendientes si el cliente no pide
# un limite, y cuantos como maximo aunque lo pida.
LIMITE_POR_DEFECTO = _entero('SOAP_LIMITE_DEFECTO', 50)
LIMITE_MAXIMO = _entero('SOAP_LIMITE_MAXIMO', 200)

# --- WS-Security (Tarea 1) ---------------------------------------------------
# Secreto compartido del UsernameToken con PasswordDigest. Vive solo en el .env
# de la VM: no esta en el repositorio, ni en la base de datos, ni en el WSDL.
WSSE_USUARIO = _texto('WSSE_USUARIO', '')
WSSE_SECRETO = _texto('WSSE_SECRETO', '')
# Ventana de frescura del token, en segundos. Fuera de ella se rechaza aunque
# el digest sea correcto: es lo que impide reenviar un sobre capturado.
WSSE_VENTANA = _entero('WSSE_VENTANA_SEGUNDOS', 300)

# --- Contrato ----------------------------------------------------------------
NS_SERVICIO = 'http://udem.edu/iac/libreria/clasificador'
RUTA_WSDL = RAIZ / 'wsdl' / 'library-classifier.wsdl'


def revisar():
    """Devuelve la lista de problemas de configuracion. Vacia = todo listo."""
    problemas = []
    if not BD['password']:
        problemas.append('DB_PASSWORD esta vacia: el modulo no podra conectarse.')
    if BD['user'] in ('postgres', 'libreria_owner'):
        problemas.append('DB_USER es un rol privilegiado. Usa libreria_soap.')
    if not WSSE_USUARIO or not WSSE_SECRETO:
        problemas.append('WSSE_USUARIO / WSSE_SECRETO sin definir: '
                         'ObtenerEstadisticasPorModelo rechazara toda peticion.')
    if not RUTA_WSDL.exists():
        problemas.append('No se encuentra el contrato en {}'.format(RUTA_WSDL))
    return problemas
