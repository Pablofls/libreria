# =============================================================================
# app.py — modulo SOAP de clasificacion Cloud de la Libreria Online.
#
#     cd services/library_soap_service
#     python3 -m venv .venv && source .venv/bin/activate
#     pip install -r requirements.txt
#     cp .env.example .env        # y completar EN LA VM
#     python app.py               # -> http://127.0.0.1:5001/soap?wsdl
#
# Una sola aplicacion Flask, SIN Blueprints, como pide el enunciado. Este
# archivo es deliberadamente delgado: solo traduce entre HTTP y el modulo SOAP.
# Toda la logica esta en soap/ y todo el SQL en db/.
#
# El monolito Node no se toca. Este proceso escucha en otro puerto, se conecta
# con otro rol de PostgreSQL y no comparte una sola linea de codigo con el.
# =============================================================================

import logging

from flask import Flask, Response, request

from config import ajustes
from db import acceso
from soap import service
from soap.envelope import leer_sobre, serializar
from soap.faults import ErrorServidor, FaltaSoap, construir_fault

logging.basicConfig(
    level=ajustes.LOG_NIVEL,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)
log = logging.getLogger('soap.app')

app = Flask(__name__)

TIPO_SOAP = 'text/xml; charset=utf-8'


def _responder_fault(falta):
    """Un Fault sale con su codigo HTTP semantico y, sobre todo, sin filtrar
    nada del servidor. El detalle tecnico se queda en el log."""
    if falta.detalle_interno:
        log.error('%s: %s', falta.codigo, falta.detalle_interno)
    else:
        log.warning('%s: %s', falta.codigo, falta.mensaje)
    sobre = construir_fault(falta, ajustes.NS_SERVICIO)
    return Response(serializar(sobre), status=falta.estado, content_type=TIPO_SOAP)


@app.route('/soap', methods=['POST'])
def punto_soap():
    # Limite de tamano antes de leer: un sobre de gigabytes no debe llegar
    # siquiera al analizador de XML.
    if request.content_length and request.content_length > ajustes.MAX_BYTES_PETICION:
        return _responder_fault(FaltaSoap(
            'La peticion excede el tamano maximo aceptado.'))

    datos = request.get_data(cache=False)
    try:
        encabezado, cuerpo = leer_sobre(datos)
        sobre = service.atender(encabezado, cuerpo)
    except FaltaSoap as falta:
        return _responder_fault(falta)
    except Exception as error:
        # Cualquier cosa no prevista se convierte en Fault de servidor. La traza
        # completa va al log; al cliente solo el codigo estable.
        log.exception('Fallo no controlado')
        return _responder_fault(ErrorServidor(
            'El servicio no pudo completar la operacion.',
            detalle_interno=str(error)))

    return Response(serializar(sobre), status=200, content_type=TIPO_SOAP)


@app.route('/soap', methods=['GET'])
@app.route('/wsdl/library-classifier.wsdl', methods=['GET'])
def publicar_wsdl():
    """?wsdl es la convencion que esperan wsimport, svcutil, zeep y SoapUI."""
    endpoint = request.url_root.rstrip('/') + '/soap'
    return Response(service.wsdl(endpoint), content_type=TIPO_SOAP)


@app.route('/health', methods=['GET'])
def salud():
    conectada, detalle = acceso.comprobar_conexion()
    if not conectada:
        log.error('Health: sin base de datos: %s', detalle)
        return Response('<health status="error"><database>sin conexion</database>'
                        '</health>', status=503, content_type=TIPO_SOAP)
    return Response('<health status="ok"><database>conectada</database>'
                    '<conceptosClasificables>{}</conceptosClasificables>'
                    '</health>'.format(detalle),
                    content_type=TIPO_SOAP)


@app.route('/', methods=['GET'])
def indice():
    return Response(
        '<service name="library-classifier-soap">'
        '<endpoint>/soap</endpoint>'
        '<contract>/soap?wsdl</contract>'
        '<health>/health</health>'
        '</service>', content_type=TIPO_SOAP)


@app.errorhandler(404)
def _no_encontrado(_error):
    return _responder_fault(FaltaSoap('La ruta solicitada no existe. '
                                      'El endpoint SOAP es /soap.'))


@app.errorhandler(405)
def _metodo(_error):
    return _responder_fault(FaltaSoap('El endpoint SOAP solo acepta POST.'))


if __name__ == '__main__':
    for problema in ajustes.revisar():
        log.warning('Configuracion: %s', problema)
    log.info('Modulo SOAP escuchando en http://%s:%s/soap',
             ajustes.HOST, ajustes.PUERTO)
    app.run(host=ajustes.HOST, port=ajustes.PUERTO, debug=False, threaded=True)
