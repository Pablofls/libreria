# =============================================================================
# soap/service.py
# Logica del servicio: despacho de operaciones, validacion de entrada y armado
# de las respuestas.
#
# El despacho se hace por el nombre local del primer hijo de <soap:Body>, que
# en document/literal ES la operacion. No se usa el encabezado SOAPAction:
# es informativo, el cliente puede omitirlo y confiar en el permitiria pedir una
# operacion distinta de la que trae el cuerpo.
#
# La validacion se repite aqui aunque el XSD ya la exprese. El XSD lo aplica el
# cliente si quiere; el servidor no puede suponer que alguien valido por el.
# =============================================================================

import logging
import re
from datetime import datetime, timezone

from config import ajustes
from db import acceso
from soap import security
from soap.envelope import (campo, construir_respuesta, hijo, nombre_local,
                           texto_de)
from soap.faults import DatoInvalido, ModeloInvalido, OperacionDesconocida

log = logging.getLogger('soap.servicio')

NS = ajustes.NS_SERVICIO

MODELOS = ('IaaS', 'PaaS', 'SaaS', 'FaaS')
RE_CORREO = re.compile(r'^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$')
RE_ISBN = re.compile(r'^[0-9-]{10,16}[0-9X]$')


# -----------------------------------------------------------------------------
# Validacion de entrada. Cada funcion devuelve el valor limpio o lanza un fault
# de cliente con el campo senalado, para que la GUI pueda resaltarlo.
# -----------------------------------------------------------------------------
def _obligatorio(valor, nombre_campo, maximo=None):
    if not valor:
        raise DatoInvalido('Falta el campo obligatorio "{}".'.format(nombre_campo),
                           campo=nombre_campo)
    limpio = valor.strip()
    if maximo and len(limpio) > maximo:
        raise DatoInvalido(
            'El campo "{}" excede {} caracteres.'.format(nombre_campo, maximo),
            campo=nombre_campo)
    return limpio


def _correo(valor, nombre_campo='correo'):
    limpio = _obligatorio(valor, nombre_campo, 150)
    if not RE_CORREO.match(limpio):
        raise DatoInvalido('El correo no tiene un formato valido.',
                           campo=nombre_campo)
    return limpio.lower()


def _isbn(valor):
    limpio = _obligatorio(valor, 'isbn', 17)
    if not RE_ISBN.match(limpio):
        raise DatoInvalido('El ISBN no tiene un formato valido.', campo='isbn')
    return limpio


def _entero_positivo(valor, nombre_campo):
    limpio = _obligatorio(valor, nombre_campo)
    try:
        numero = int(limpio)
    except ValueError:
        raise DatoInvalido('El campo "{}" debe ser un numero entero.'
                           .format(nombre_campo), campo=nombre_campo)
    if numero < 1:
        raise DatoInvalido('El campo "{}" debe ser mayor que cero.'
                           .format(nombre_campo), campo=nombre_campo)
    return numero


def _modelo(valor):
    limpio = _obligatorio(valor, 'modelo')
    if limpio not in MODELOS:
        # Fault propio, distinto de DATO_INVALIDO: el enunciado lo pide como
        # caso de error separado y el cliente lo trata distinto (es un menu
        # cerrado, no un texto que el usuario escribio mal).
        raise ModeloInvalido(
            'El modelo debe ser uno de: {}.'.format(', '.join(MODELOS)),
            campo='modelo')
    return limpio


def _iso(momento):
    if momento is None:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.isoformat()


# =============================================================================
# Operaciones
# =============================================================================
def _obtener_conceptos_pendientes(peticion, encabezado):
    correo = texto_de(peticion, 'correo')
    if correo:
        correo = _correo(correo)
    limite = texto_de(peticion, 'limite')
    limite = _entero_positivo(limite, 'limite') if limite else None

    total, conceptos = acceso.conceptos_pendientes(correo, limite)

    sobre, salida = construir_respuesta(NS, 'ObtenerConceptosPendientes')
    campo(salida, NS, 'total', total)
    for fila in conceptos:
        nodo = campo(salida, NS, 'concepto', None)
        campo(nodo, NS, 'conceptoId', fila['concepto_id'])
        campo(nodo, NS, 'termino', fila['termino'])
        campo(nodo, NS, 'definicion', fila['definicion'])
        campo(nodo, NS, 'isbn', fila['isbn'])
        campo(nodo, NS, 'libro', fila['libro'])
        campo(nodo, NS, 'categoria', fila['categoria'])
        if fila.get('capitulo'):
            campo(nodo, NS, 'capitulo', fila['capitulo'])
        if fila.get('pagina') is not None:
            campo(nodo, NS, 'pagina', fila['pagina'])
    return sobre


def _registrar_clasificacion(peticion, encabezado):
    clasificador = hijo(peticion, 'clasificador')
    if clasificador is None:
        raise DatoInvalido('Falta el bloque "clasificador".', campo='clasificador')

    nombre = _obligatorio(texto_de(clasificador, 'nombre'), 'nombre', 80)
    apellidos = _obligatorio(texto_de(clasificador, 'apellidos'), 'apellidos', 120)
    correo = _correo(texto_de(clasificador, 'correo'))

    concepto_id = _entero_positivo(texto_de(peticion, 'conceptoId'), 'conceptoId')
    isbn = _isbn(texto_de(peticion, 'isbn'))
    modelo = _modelo(texto_de(peticion, 'modelo'))

    # El bloque cliente es opcional: sirve para la telemetria de
    # clientes_servidos, no para la clasificacion.
    cliente = hijo(peticion, 'cliente')
    tipo_cliente = id_cliente = None
    if cliente is not None:
        tipo_cliente = texto_de(cliente, 'tipo')
        id_cliente = texto_de(cliente, 'identificador')
        if bool(tipo_cliente) != bool(id_cliente):
            raise DatoInvalido('El bloque "cliente" requiere tipo e identificador.',
                               campo='cliente')

    fila = acceso.registrar_clasificacion(nombre, apellidos, correo, concepto_id,
                                          isbn, modelo, tipo_cliente, id_cliente)

    sobre, salida = construir_respuesta(NS, 'RegistrarClasificacion')
    campo(salida, NS, 'clasificacionId', fila['clasificacion_id'])
    campo(salida, NS, 'termino', fila['termino'])
    campo(salida, NS, 'libro', fila['libro'])
    campo(salida, NS, 'modelo', modelo)
    campo(salida, NS, 'registradoEn', _iso(fila['clasificado_en']))
    campo(salida, NS, 'peticionesAtendidas', fila['peticiones_atendidas'])
    return sobre


def _obtener_progreso_usuario(peticion, encabezado):
    correo = _correo(texto_de(peticion, 'correo'))
    fila, modelos = acceso.progreso_usuario(correo)

    sobre, salida = construir_respuesta(NS, 'ObtenerProgresoUsuario')
    campo(salida, NS, 'correo', fila['correo'])
    campo(salida, NS, 'nombre', '{} {}'.format(fila['nombre'], fila['apellidos']))
    campo(salida, NS, 'totalClasificados', fila['total_clasificados'])
    campo(salida, NS, 'totalPendientes', fila['total_pendientes'])
    for modelo in modelos:
        nodo = campo(salida, NS, 'porModelo', None)
        campo(nodo, NS, 'modelo', modelo['modelo'])
        campo(nodo, NS, 'total', modelo['total'])
    return sobre


def _obtener_estadisticas_por_modelo(peticion, encabezado):
    # La unica operacion protegida. La comprobacion va ANTES de tocar la base:
    # una peticion no autenticada no debe costar una consulta.
    usuario = security.verificar(encabezado)
    log.info('ObtenerEstadisticasPorModelo autorizada para %s', usuario)

    filas = acceso.estadisticas_por_modelo()

    sobre, salida = construir_respuesta(NS, 'ObtenerEstadisticasPorModelo')
    campo(salida, NS, 'generadoEn', datetime.now(timezone.utc).isoformat())
    for fila in filas:
        nodo = campo(salida, NS, 'estadistica', None)
        campo(nodo, NS, 'modelo', fila['modelo'])
        campo(nodo, NS, 'total', fila['total'])
        campo(nodo, NS, 'clasificadores', fila['clasificadores'])
    return sobre


OPERACIONES = {
    'ObtenerConceptosPendientes': _obtener_conceptos_pendientes,
    'RegistrarClasificacion': _registrar_clasificacion,
    'ObtenerProgresoUsuario': _obtener_progreso_usuario,
    'ObtenerEstadisticasPorModelo': _obtener_estadisticas_por_modelo,
}


def atender(encabezado, cuerpo):
    """Despacha la operacion que trae el Body y devuelve el sobre de respuesta."""
    operacion = nombre_local(cuerpo)
    manejador = OPERACIONES.get(operacion)
    if manejador is None:
        raise OperacionDesconocida(
            'La operacion "{}" no existe en el contrato.'.format(operacion),
            campo='operacion')
    log.info('Operacion solicitada: %s', operacion)
    return manejador(cuerpo, encabezado)


# -----------------------------------------------------------------------------
# Publicacion del contrato.
# La direccion del <soap:address> se reescribe con el host real de la peticion:
# asi el WSDL que descarga un cliente desde la VM apunta a la VM y no a
# localhost, sin tener que editar el archivo en cada despliegue.
# -----------------------------------------------------------------------------
def wsdl(url_endpoint):
    """Devuelve el contrato con la direccion del endpoint puesta al vuelo.

    La sustitucion es textual, no por ElementTree, y la razon importa: en un
    WSDL los prefijos (tns:ObtenerConceptosPendientes) viven dentro de VALORES
    de atributo. ElementTree solo conserva las declaraciones de namespace que ve
    usadas en nombres de elemento, asi que al reserializar borraba xmlns:tns y
    publicaba un contrato roto para wsimport, svcutil y zeep.

    Solo se reemplaza el valor de location, que lo construye el servidor a
    partir del host de la peticion, y se escapa antes de insertarlo.
    """
    from xml.sax.saxutils import quoteattr

    contrato = ajustes.RUTA_WSDL.read_text(encoding='utf-8')
    return re.sub(
        r'(<soap:address\s+location=)("[^"]*"|\'[^\']*\')',
        lambda coincidencia: coincidencia.group(1) + quoteattr(url_endpoint),
        contrato, count=1).encode('utf-8')
