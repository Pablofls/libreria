# =============================================================================
# soap/security.py
# WS-Security UsernameToken con PasswordDigest (Tarea 1).
#
# POR QUE DIGEST Y NO PasswordText
#   Con PasswordText la contrasena viaja en claro dentro del sobre: cualquiera
#   que vea el trafico o un log de proxy se la queda. Con PasswordDigest viaja
#       Base64( SHA1( nonce + created + secreto ) )
#   que no es reutilizable fuera de esa ventana de tiempo y no revela el
#   secreto. Es lo maximo que se puede hacer sin TLS, que es lo que de verdad
#   corresponde en produccion.
#
# CONTRAPARTIDA HONESTA
#   PasswordDigest obliga al servidor a conocer el secreto en claro para
#   recalcular el digest, asi que NO se puede guardar hasheado con bcrypt. Por
#   eso vive en el .env de la VM: fuera del repositorio, fuera de la base de
#   datos y fuera del WSDL. Si algun dia hay TLS, lo correcto es cambiar a
#   PasswordText + bcrypt en base de datos.
#
# REPLAY
#   El digest solo por si mismo se puede reenviar. Se rechaza si el Created cae
#   fuera de la ventana configurada o si el nonce ya se uso dentro de ella.
# =============================================================================

import base64
import hashlib
import hmac
import time
from datetime import datetime, timezone

from config import ajustes
from soap.envelope import NS_WSSE, hijo, nombre_local
from soap.faults import NoAutorizado

# Nonces vistos -> momento en que se vieron. Se purga con la misma ventana.
# Es memoria del proceso: suficiente para un servicio de un solo worker, que es
# como se despliega este modulo. Con varios workers habria que moverlo a Redis
# o a una tabla; queda anotado como limitacion.
_nonces_vistos = {}


def _purgar(ahora):
    limite = ahora - ajustes.WSSE_VENTANA
    for nonce, visto in list(_nonces_vistos.items()):
        if visto < limite:
            del _nonces_vistos[nonce]


def _leer_created(texto):
    """Acepta los formatos que emiten los stacks WS-Security habituales."""
    if not texto:
        raise NoAutorizado('El UsernameToken no trae Created.')
    limpio = texto.strip().replace('Z', '+00:00')
    try:
        momento = datetime.fromisoformat(limpio)
    except ValueError:
        raise NoAutorizado('El Created del UsernameToken no es una fecha ISO 8601.')
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento


def verificar(encabezado):
    """Valida el UsernameToken del soap:Header. Lanza NoAutorizado si algo falla.

    Nunca se dice CUAL de las comprobaciones fallo: distinguir 'usuario
    incorrecto' de 'contrasena incorrecta' le regala a quien prueba credenciales
    la mitad del trabajo.
    """
    if not ajustes.WSSE_USUARIO or not ajustes.WSSE_SECRETO:
        # Sin secreto configurado la operacion queda cerrada, no abierta.
        raise NoAutorizado('La operacion requiere autenticacion y el servicio '
                           'no tiene credenciales configuradas.')

    if encabezado is None:
        raise NoAutorizado('Falta el encabezado WS-Security.')

    seguridad = None
    for elemento in encabezado:
        if nombre_local(elemento) == 'Security':
            seguridad = elemento
            break
    if seguridad is None:
        raise NoAutorizado('Falta el elemento wsse:Security en el encabezado.')

    token = hijo(seguridad, 'UsernameToken')
    if token is None:
        raise NoAutorizado('Falta el UsernameToken.')

    usuario = hijo(token, 'Username')
    clave = hijo(token, 'Password')
    nonce = hijo(token, 'Nonce')
    creado = hijo(token, 'Created')

    if usuario is None or clave is None or nonce is None or creado is None:
        raise NoAutorizado('El UsernameToken esta incompleto: se requieren '
                           'Username, Password, Nonce y Created.')

    tipo = (clave.get('Type') or '').strip()
    if tipo and not tipo.endswith('#PasswordDigest'):
        raise NoAutorizado('Solo se acepta PasswordDigest; PasswordText enviaria '
                           'el secreto en claro.')

    momento = _leer_created(creado.text)
    ahora_utc = datetime.now(timezone.utc)
    if abs((ahora_utc - momento).total_seconds()) > ajustes.WSSE_VENTANA:
        raise NoAutorizado('El token esta fuera de la ventana de validez.')

    texto_nonce = (nonce.text or '').strip()
    ahora = time.time()
    _purgar(ahora)
    if texto_nonce in _nonces_vistos:
        raise NoAutorizado('El token ya se habia usado.')

    try:
        nonce_bytes = base64.b64decode(texto_nonce, validate=True)
    except Exception:
        raise NoAutorizado('El Nonce no es Base64 valido.')

    esperado = base64.b64encode(hashlib.sha1(
        nonce_bytes
        + (creado.text or '').strip().encode('utf-8')
        + ajustes.WSSE_SECRETO.encode('utf-8')
    ).digest()).decode('ascii')

    recibido = (clave.text or '').strip()

    # compare_digest en las DOS comparaciones: el nombre de usuario tambien se
    # compara en tiempo constante para no filtrar cual existe.
    usuario_ok = hmac.compare_digest((usuario.text or '').strip(),
                                     ajustes.WSSE_USUARIO)
    clave_ok = hmac.compare_digest(recibido, esperado)
    if not (usuario_ok and clave_ok):
        raise NoAutorizado('Credenciales invalidas.')

    _nonces_vistos[texto_nonce] = ahora
    return (usuario.text or '').strip()


def construir_token(usuario, secreto):
    """Genera un UsernameToken valido. Lo usan el cliente de escritorio y las
    pruebas; vive aqui para que cliente y servidor no se desincronicen."""
    import os
    nonce_bytes = os.urandom(16)
    creado = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    digest = base64.b64encode(hashlib.sha1(
        nonce_bytes + creado.encode('utf-8') + secreto.encode('utf-8')
    ).digest()).decode('ascii')
    return {
        'usuario': usuario,
        'digest': digest,
        'nonce': base64.b64encode(nonce_bytes).decode('ascii'),
        'creado': creado,
    }
