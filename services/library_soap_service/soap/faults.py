# =============================================================================
# soap/faults.py
# Vocabulario de errores del modulo y su serializacion a SOAP Fault 1.1.
#
# Un Fault es parte del contrato, no un accidente: el cliente decide que hacer
# leyendo el <codigo>, que es estable, y le muestra a la persona el <mensaje>,
# que puede cambiar. Por eso el codigo NO se traduce ni se reformula.
#
# Regla dura: en el Fault que sale a la red no va nunca un stack trace, una
# consulta SQL, una ruta del servidor ni una credencial. Ese detalle se registra
# en el log del servidor, donde el cliente no llega.
# =============================================================================

from xml.etree import ElementTree as ET

NS_SOAP = 'http://schemas.xmlsoap.org/soap/envelope/'


class FaltaSoap(Exception):
    """Error previsto del servicio. Se traduce a un SOAP Fault.

    tipo:   'Client' si la peticion venia mal, 'Server' si fallamos nosotros.
            Es la distincion que le dice al cliente si reintentar tiene sentido.
    codigo: identificador estable para que el cliente decida sin leer textos.
    estado: codigo HTTP que acompana al Fault. SOAP 1.1 solo contempla 500,
            pero devolver 400/401/409 le da a un cliente HTTP la misma
            informacion sin tener que abrir el sobre, y las bibliotecas SOAP
            siguen encontrando el Fault en el cuerpo.
    """

    tipo = 'Client'
    codigo = 'ERROR'
    estado = 400

    def __init__(self, mensaje, campo=None, detalle_interno=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.campo = campo
        # Solo para el log del servidor. Jamas viaja al cliente.
        self.detalle_interno = detalle_interno


class XmlInvalido(FaltaSoap):
    codigo = 'XML_INVALIDO'
    estado = 400


class OperacionDesconocida(FaltaSoap):
    codigo = 'OPERACION_DESCONOCIDA'
    estado = 400


class DatoInvalido(FaltaSoap):
    codigo = 'DATO_INVALIDO'
    estado = 400


class ModeloInvalido(FaltaSoap):
    codigo = 'MODELO_INVALIDO'
    estado = 400


class ConceptoInexistente(FaltaSoap):
    codigo = 'CONCEPTO_INEXISTENTE'
    estado = 404


class LibroInexistente(FaltaSoap):
    codigo = 'LIBRO_INEXISTENTE'
    estado = 404


class ClasificadorInexistente(FaltaSoap):
    codigo = 'CLASIFICADOR_INEXISTENTE'
    estado = 404


class ClasificacionDuplicada(FaltaSoap):
    """El conflicto que pide el enunciado: mismo clasificador, mismo concepto."""
    codigo = 'CLASIFICACION_DUPLICADA'
    estado = 409


class NoAutorizado(FaltaSoap):
    codigo = 'NO_AUTORIZADO'
    estado = 401


class ErrorServidor(FaltaSoap):
    tipo = 'Server'
    codigo = 'ERROR_SERVIDOR'
    estado = 500


def construir_fault(falta, ns_servicio):
    """Arma el Envelope de Fault. Todo valor pasa por ElementTree, que escapa;
    en ningun punto se concatena XML a mano."""
    ET.register_namespace('soap', NS_SOAP)
    ET.register_namespace('tns', ns_servicio)

    sobre = ET.Element('{%s}Envelope' % NS_SOAP)
    cuerpo = ET.SubElement(sobre, '{%s}Body' % NS_SOAP)
    fault = ET.SubElement(cuerpo, '{%s}Fault' % NS_SOAP)

    # En SOAP 1.1 faultcode es un QName; 'soap' esta ligado por el sobre.
    ET.SubElement(fault, 'faultcode').text = 'soap:{}'.format(falta.tipo)
    ET.SubElement(fault, 'faultstring').text = falta.mensaje

    detalle = ET.SubElement(fault, 'detail')
    propio = ET.SubElement(detalle, '{%s}ClasificadorFault' % ns_servicio)
    ET.SubElement(propio, '{%s}codigo' % ns_servicio).text = falta.codigo
    ET.SubElement(propio, '{%s}mensaje' % ns_servicio).text = falta.mensaje
    if falta.campo:
        ET.SubElement(propio, '{%s}campo' % ns_servicio).text = falta.campo

    return sobre
