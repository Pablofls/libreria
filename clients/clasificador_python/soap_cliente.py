"""
Capa cliente SOAP del Clasificador Cloud.

Es el "modo cliente SOAP" que pide la Parte 8 del Ejercicio Guiado 3: la
aplicacion de escritorio del EG1 deja de ser solo un clasificador local y pasa a
consumir el modulo SOAP que publica el catalogo real de la libreria.

REGLA DEL EJERCICIO QUE ESTE ARCHIVO RESPETA
    Aqui no hay una cadena de conexion, ni SQL, ni un nombre de tabla. La unica
    puerta al sistema es el endpoint SOAP. Si el modulo cambiara de motor de base
    de datos, este archivo no se toca.

Se separa de la GUI a proposito: la ventana importa estas funciones y no sabe
nada de XML, y este modulo no sabe nada de widgets. Asi el mismo cliente sirve
para la GUI, para la CLI y para una prueba automatizada.

El sobre se construye con xml.etree, que escapa los valores. No se concatena XML.
"""

import os
import urllib.error
import urllib.request
from xml.etree import ElementTree as ET

ENDPOINT = os.getenv("SOAP_ENDPOINT", "http://127.0.0.1:5001/soap")
TIPO_CLIENTE = "escritorio-eg1-python"
ID_CLIENTE = os.getenv("SOAP_ID_CLIENTE", "estacion-01")

NS = "http://udem.edu/iac/libreria/clasificador"
NS_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
MODELOS = ("IaaS", "PaaS", "SaaS", "FaaS")

# Mensajes por codigo de Fault. La GUI traduce el codigo estable del contrato a
# algo que una persona entiende; NUNCA muestra el faultstring crudo.
MENSAJES = {
    "CLASIFICACION_DUPLICADA": "Ya clasificaste ese concepto antes. "
                               "Elige otro de la lista.",
    "CONCEPTO_INEXISTENTE":    "Ese concepto ya no esta disponible. "
                               "Actualiza la lista.",
    "LIBRO_INEXISTENTE":       "El libro asociado ya no esta en el catalogo. "
                               "Actualiza la lista.",
    "MODELO_INVALIDO":         "Selecciona uno de los cuatro modelos de la lista.",
    "DATO_INVALIDO":           "Revisa los datos capturados: hay un campo "
                               "incompleto o mal escrito.",
    "CLASIFICADOR_INEXISTENTE": "Todavia no tienes clasificaciones registradas "
                                "con ese correo.",
    "NO_AUTORIZADO":           "No tienes permiso para esta operacion.",
    "XML_INVALIDO":            "La aplicacion envio una peticion mal formada. "
                               "Reporta este error.",
    "OPERACION_DESCONOCIDA":   "Esta version de la aplicacion no coincide con el "
                               "servidor. Actualizala.",
    "ERROR_SERVIDOR":          "El servicio no esta disponible en este momento. "
                               "Intenta mas tarde.",
}

# Codigos que NO son fallas: para quien estrena la aplicacion son el estado
# normal y la GUI no debe pintarlos de rojo.
ESPERADOS = {"CLASIFICADOR_INEXISTENTE"}


class ErrorServicio(Exception):
    """Un SOAP Fault ya traducido a algo que se le puede mostrar a una persona."""

    def __init__(self, codigo, campo=None):
        self.codigo = codigo
        self.campo = campo
        self.esperado = codigo in ESPERADOS
        super().__init__(MENSAJES.get(
            codigo, "Ocurrio un problema al contactar el servicio."))


# ── Construccion y envio del sobre ────────────────────────────────────────────

def _campo(padre, nombre, valor):
    elemento = ET.SubElement(padre, "{%s}%s" % (NS, nombre))
    elemento.text = str(valor)
    return elemento


def _llamar(operacion, construir=None, endpoint=None):
    """Arma el Envelope, lo envia por HTTP POST y devuelve el elemento de
    respuesta. Traduce cualquier Fault a ErrorServicio."""
    ET.register_namespace("soap", NS_SOAP)
    ET.register_namespace("tns", NS)

    sobre = ET.Element("{%s}Envelope" % NS_SOAP)
    cuerpo = ET.SubElement(sobre, "{%s}Body" % NS_SOAP)
    nodo = ET.SubElement(cuerpo, "{%s}%s" % (NS, operacion))
    if construir:
        construir(nodo)

    datos = ET.tostring(sobre, encoding="utf-8", xml_declaration=True)
    peticion = urllib.request.Request(
        endpoint or ENDPOINT, data=datos,
        headers={"Content-Type": "text/xml; charset=utf-8",
                 "SOAPAction": "{}/{}".format(NS, operacion)})
    try:
        with urllib.request.urlopen(peticion, timeout=20) as respuesta:
            crudo = respuesta.read()
    except urllib.error.HTTPError as error:
        crudo = error.read()
    except urllib.error.URLError:
        raise ErrorServicio("ERROR_SERVIDOR")

    try:
        raiz = ET.fromstring(crudo)
    except ET.ParseError:
        raise ErrorServicio("ERROR_SERVIDOR")

    cuerpo_resp = raiz.find("{%s}Body" % NS_SOAP)
    fault = cuerpo_resp.find("{%s}Fault" % NS_SOAP)
    if fault is not None:
        codigo = fault.find(".//{%s}codigo" % NS)
        campo = fault.find(".//{%s}campo" % NS)
        raise ErrorServicio(codigo.text if codigo is not None else "ERROR_SERVIDOR",
                            campo.text if campo is not None else None)
    return list(cuerpo_resp)[0]


# ── Las tres operaciones del contrato ─────────────────────────────────────────

def conceptos_pendientes(correo=None, limite=50, endpoint=None):
    """Devuelve (total, lista de conceptos aun sin clasificar)."""
    def construir(nodo):
        if correo:
            _campo(nodo, "correo", correo)
        _campo(nodo, "limite", limite)

    respuesta = _llamar("ObtenerConceptosPendientes", construir, endpoint)
    conceptos = [{
        "id":         nodo.findtext("{%s}conceptoId" % NS),
        "termino":    nodo.findtext("{%s}termino" % NS),
        "definicion": nodo.findtext("{%s}definicion" % NS),
        "isbn":       nodo.findtext("{%s}isbn" % NS),
        "libro":      nodo.findtext("{%s}libro" % NS),
        "categoria":  nodo.findtext("{%s}categoria" % NS),
    } for nodo in respuesta.findall("{%s}concepto" % NS)]
    return respuesta.findtext("{%s}total" % NS), conceptos


def registrar_clasificacion(clasificador, concepto, modelo, endpoint=None):
    """clasificador: dict con nombre, apellidos y correo."""
    def construir(nodo):
        bloque = ET.SubElement(nodo, "{%s}clasificador" % NS)
        _campo(bloque, "nombre", clasificador["nombre"])
        _campo(bloque, "apellidos", clasificador["apellidos"])
        _campo(bloque, "correo", clasificador["correo"])
        _campo(nodo, "conceptoId", concepto["id"])
        _campo(nodo, "isbn", concepto["isbn"])
        _campo(nodo, "modelo", modelo)
        cliente = ET.SubElement(nodo, "{%s}cliente" % NS)
        _campo(cliente, "tipo", TIPO_CLIENTE)
        _campo(cliente, "identificador", ID_CLIENTE)

    respuesta = _llamar("RegistrarClasificacion", construir, endpoint)
    return {
        "id":          respuesta.findtext("{%s}clasificacionId" % NS),
        "termino":     respuesta.findtext("{%s}termino" % NS),
        "libro":       respuesta.findtext("{%s}libro" % NS),
        "modelo":      respuesta.findtext("{%s}modelo" % NS),
        "registrado":  respuesta.findtext("{%s}registradoEn" % NS),
        "peticiones":  respuesta.findtext("{%s}peticionesAtendidas" % NS),
    }


def progreso(correo, endpoint=None):
    respuesta = _llamar("ObtenerProgresoUsuario",
                        lambda nodo: _campo(nodo, "correo", correo), endpoint)
    return {
        "nombre":       respuesta.findtext("{%s}nombre" % NS),
        "clasificados": respuesta.findtext("{%s}totalClasificados" % NS),
        "pendientes":   respuesta.findtext("{%s}totalPendientes" % NS),
        "modelos":      [(m.findtext("{%s}modelo" % NS),
                          m.findtext("{%s}total" % NS))
                         for m in respuesta.findall("{%s}porModelo" % NS)],
    }
