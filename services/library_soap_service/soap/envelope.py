# =============================================================================
# soap/envelope.py
# Lectura y construccion del SOAP Envelope a mano, con xml.etree.ElementTree.
#
# El enunciado prohibe frameworks que generen el sobre automaticamente, y esa
# restriccion es didactica: obliga a distinguir Envelope, Header y Body, a
# manejar los namespaces de forma explicita y a ver donde esta el trabajo que
# normalmente hace la biblioteca.
#
# Todo valor que sale se escribe con ElementTree, que escapa &, <, > y comillas.
# En este archivo no hay una sola cadena de XML concatenada.
# =============================================================================

from xml.etree import ElementTree as ET

from soap.faults import XmlInvalido

NS_SOAP = 'http://schemas.xmlsoap.org/soap/envelope/'
NS_WSSE = ('http://docs.oasis-open.org/wss/2004/01/'
           'oasis-200401-wss-wssecurity-secext-1.0.xsd')
NS_WSU = ('http://docs.oasis-open.org/wss/2004/01/'
          'oasis-200401-wss-wssecurity-utility-1.0.xsd')


def registrar_prefijos(ns_servicio):
    """Prefijos legibles en la salida. Sin esto ElementTree inventa ns0, ns1..."""
    ET.register_namespace('soap', NS_SOAP)
    ET.register_namespace('wsse', NS_WSSE)
    ET.register_namespace('tns', ns_servicio)


def leer_sobre(datos):
    """Analiza el sobre recibido y devuelve (header, body_hijo).

    body_hijo es el primer elemento dentro de <Body>: en document/literal ese
    elemento ES la operacion solicitada, asi que su nombre local basta para
    despachar. No se confia en el encabezado SOAPAction, que el cliente puede
    omitir o falsear.
    """
    try:
        sobre = ET.fromstring(datos)
    except ET.ParseError as error:
        # El texto del parser dice linea y columna, util para el cliente y sin
        # riesgo: no revela nada del servidor.
        raise XmlInvalido('El XML de la peticion no se pudo analizar.',
                          detalle_interno=str(error))

    if sobre.tag != '{%s}Envelope' % NS_SOAP:
        raise XmlInvalido('El elemento raiz no es un soap:Envelope.')

    encabezado = sobre.find('{%s}Header' % NS_SOAP)
    cuerpo = sobre.find('{%s}Body' % NS_SOAP)
    if cuerpo is None:
        raise XmlInvalido('El sobre no trae soap:Body.')

    hijos = list(cuerpo)
    if len(hijos) != 1:
        raise XmlInvalido('El soap:Body debe contener exactamente una operacion.')

    return encabezado, hijos[0]


def nombre_local(elemento):
    etiqueta = elemento.tag
    return etiqueta.rsplit('}', 1)[-1] if '}' in etiqueta else etiqueta


def hijo(padre, nombre):
    """Busca un hijo por nombre local, sea cual sea su namespace.

    Un cliente generado por wsimport califica los hijos con el namespace del
    servicio; uno escrito a mano a veces no. Aceptar ambos es interoperabilidad
    barata y no relaja ninguna validacion: el valor se valida igual despues.
    """
    if padre is None:
        return None
    for elemento in padre:
        if nombre_local(elemento) == nombre:
            return elemento
    return None


def texto_de(padre, nombre, defecto=None):
    elemento = hijo(padre, nombre)
    if elemento is None or elemento.text is None:
        return defecto
    valor = elemento.text.strip()
    return valor if valor else defecto


def construir_respuesta(ns_servicio, nombre_operacion):
    """Crea el sobre de respuesta y devuelve (sobre, elemento_de_la_operacion)."""
    registrar_prefijos(ns_servicio)
    sobre = ET.Element('{%s}Envelope' % NS_SOAP)
    cuerpo = ET.SubElement(sobre, '{%s}Body' % NS_SOAP)
    operacion = ET.SubElement(cuerpo, '{%s}%sResponse' % (ns_servicio,
                                                          nombre_operacion))
    return sobre, operacion


def campo(padre, ns_servicio, nombre, valor):
    """Agrega un elemento hijo con su valor ya convertido a texto."""
    elemento = ET.SubElement(padre, '{%s}%s' % (ns_servicio, nombre))
    if valor is not None:
        elemento.text = str(valor)
    return elemento


def serializar(sobre):
    if hasattr(ET, 'indent'):
        ET.indent(sobre, space='  ')
    cuerpo = ET.tostring(sobre, encoding='utf-8', xml_declaration=True)
    return cuerpo + b'\n'
