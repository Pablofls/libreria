# =============================================================================
# tests/pruebas_soap.py
# Plan de pruebas ejecutable del modulo SOAP (Parte 9 del enunciado).
#
#     python3 tests/pruebas_soap.py                       # contra localhost
#     ENDPOINT=http://VM:5001/soap python3 tests/pruebas_soap.py
#
# Cada prueba declara entrada, resultado esperado y resultado obtenido, e
# imprime la tabla del enunciado. Con --markdown escribe la tabla en un archivo
# para adjuntarla como evidencia.
#
# Se usa urllib de la biblioteca estandar a proposito: las pruebas no deben
# depender de la misma biblioteca que el cliente que prueban.
# =============================================================================

import os
import sys
import time
import urllib.error
import urllib.request
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from soap.security import construir_token  # noqa: E402

# Las credenciales se leen del .env del modulo, no de la linea de comandos:
# pasarlas como variables al invocar el script las dejaria en el historial del
# shell. python-dotenv es opcional aqui, para que las pruebas sigan corriendo en
# un entorno que solo tenga la biblioteca estandar.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), '.env'))
except ImportError:
    pass


ENDPOINT = os.getenv('ENDPOINT', 'http://127.0.0.1:5001/soap')
WSSE_USUARIO = os.getenv('WSSE_USUARIO', 'reportes')
WSSE_SECRETO = os.getenv('WSSE_SECRETO', '')

NS = 'http://udem.edu/iac/libreria/clasificador'
NS_SOAP = 'http://schemas.xmlsoap.org/soap/envelope/'
NS_WSSE = ('http://docs.oasis-open.org/wss/2004/01/'
           'oasis-200401-wss-wssecurity-secext-1.0.xsd')

# Correo distinto en cada corrida: asi las pruebas son repetibles sin tener que
# limpiar la base entre ejecuciones.
CORREO = 'prueba.{}@libreria.udem.mx'.format(int(time.time()))

resultados = []


# -----------------------------------------------------------------------------
# Construccion y envio de sobres
# -----------------------------------------------------------------------------
def sobre(operacion, contenido=None, token=None):
    ET.register_namespace('soap', NS_SOAP)
    ET.register_namespace('tns', NS)
    ET.register_namespace('wsse', NS_WSSE)

    raiz = ET.Element('{%s}Envelope' % NS_SOAP)
    if token:
        encabezado = ET.SubElement(raiz, '{%s}Header' % NS_SOAP)
        seguridad = ET.SubElement(encabezado, '{%s}Security' % NS_WSSE)
        ut = ET.SubElement(seguridad, '{%s}UsernameToken' % NS_WSSE)
        ET.SubElement(ut, '{%s}Username' % NS_WSSE).text = token['usuario']
        clave = ET.SubElement(ut, '{%s}Password' % NS_WSSE)
        clave.set('Type', 'http://docs.oasis-open.org/wss/2004/01/'
                          'oasis-200401-wss-username-token-profile-1.0#PasswordDigest')
        clave.text = token['digest']
        ET.SubElement(ut, '{%s}Nonce' % NS_WSSE).text = token['nonce']
        ET.SubElement(ut, '{%s}Created' % NS_WSSE).text = token['creado']

    cuerpo = ET.SubElement(raiz, '{%s}Body' % NS_SOAP)
    operacion_elem = ET.SubElement(cuerpo, '{%s}%s' % (NS, operacion))
    if contenido:
        contenido(operacion_elem)
    return ET.tostring(raiz, encoding='utf-8', xml_declaration=True)


def campo(padre, nombre, valor):
    elemento = ET.SubElement(padre, '{%s}%s' % (NS, nombre))
    elemento.text = str(valor)
    return elemento


def enviar(cuerpo, accion=''):
    peticion = urllib.request.Request(
        ENDPOINT, data=cuerpo,
        headers={'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': accion})
    try:
        with urllib.request.urlopen(peticion, timeout=15) as respuesta:
            return respuesta.status, respuesta.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def analizar(datos):
    raiz = ET.fromstring(datos)
    cuerpo = raiz.find('{%s}Body' % NS_SOAP)
    fault = cuerpo.find('{%s}Fault' % NS_SOAP)
    if fault is not None:
        codigo = fault.find('.//{%s}codigo' % NS)
        mensaje = fault.find('faultstring')
        return ('fault',
                codigo.text if codigo is not None else '?',
                mensaje.text if mensaje is not None else '')
    return ('ok', list(cuerpo)[0], None)


def registrar(id_prueba, descripcion, esperado, obtenido, aprueba):
    resultados.append({'id': id_prueba, 'prueba': descripcion,
                       'esperado': esperado, 'obtenido': obtenido,
                       'estado': 'PASA' if aprueba else 'FALLA'})
    marca = ' OK ' if aprueba else 'FALLA'
    print('  {}  {:<5} {:<44} {}'.format(marca, id_prueba, descripcion, obtenido))


# -----------------------------------------------------------------------------
# Pruebas positivas
# -----------------------------------------------------------------------------
def p01_conceptos_pendientes():
    estado, datos = enviar(sobre('ObtenerConceptosPendientes',
                                 lambda e: campo(e, 'limite', 5)))
    tipo, contenido, _ = analizar(datos)
    if tipo == 'fault':
        registrar('P01', 'Obtener conceptos pendientes', 'Lista valida',
                  'Fault {}'.format(contenido), False)
        return None
    conceptos = contenido.findall('{%s}concepto' % NS)
    total = contenido.findtext('{%s}total' % NS)
    completo = all(c.findtext('{%s}%s' % (NS, campo_req))
                   for c in conceptos
                   for campo_req in ('conceptoId', 'termino', 'isbn', 'libro',
                                     'categoria'))
    aprueba = estado == 200 and len(conceptos) == 5 and completo
    registrar('P01', 'Obtener conceptos pendientes', 'Lista valida',
              '{} conceptos de {} pendientes, con libro y categoria'
              .format(len(conceptos), total), aprueba)
    return conceptos


def p02_registrar(conceptos):
    modelos = ['IaaS', 'PaaS', 'SaaS', 'FaaS']
    usados = []
    for indice, modelo in enumerate(modelos):
        concepto = conceptos[indice]
        concepto_id = concepto.findtext('{%s}conceptoId' % NS)
        isbn = concepto.findtext('{%s}isbn' % NS)
        usados.append((concepto_id, isbn))

        def contenido(elemento, cid=concepto_id, i=isbn, m=modelo):
            clasificador = ET.SubElement(elemento, '{%s}clasificador' % NS)
            campo(clasificador, 'nombre', 'Pablo')
            campo(clasificador, 'apellidos', 'Prueba Automatizada')
            campo(clasificador, 'correo', CORREO)
            campo(elemento, 'conceptoId', cid)
            campo(elemento, 'isbn', i)
            campo(elemento, 'modelo', m)
            cliente = ET.SubElement(elemento, '{%s}cliente' % NS)
            campo(cliente, 'tipo', 'pruebas-automatizadas')
            campo(cliente, 'identificador', 'suite-01')

        estado, datos = enviar(sobre('RegistrarClasificacion', contenido))
        tipo, respuesta, _ = analizar(datos)
        aprueba = estado == 200 and tipo == 'ok'
        detalle = ('id={} peticiones={}'.format(
            respuesta.findtext('{%s}clasificacionId' % NS),
            respuesta.findtext('{%s}peticionesAtendidas' % NS))
            if aprueba else 'Fault {}'.format(respuesta))
        registrar('P02{}'.format(indice + 1),
                  'Registrar clasificacion {}'.format(modelo),
                  'Registro exitoso', detalle, aprueba)
    return usados


def p03_progreso():
    estado, datos = enviar(sobre('ObtenerProgresoUsuario',
                                 lambda e: campo(e, 'correo', CORREO)))
    tipo, respuesta, _ = analizar(datos)
    aprueba = False
    detalle = 'Fault {}'.format(respuesta)
    if tipo == 'ok':
        clasificados = respuesta.findtext('{%s}totalClasificados' % NS)
        pendientes = respuesta.findtext('{%s}totalPendientes' % NS)
        modelos = respuesta.findall('{%s}porModelo' % NS)
        aprueba = estado == 200 and clasificados == '4' and len(modelos) == 4
        detalle = '{} clasificados, {} pendientes, {} modelos'.format(
            clasificados, pendientes, len(modelos))
    registrar('P03', 'Consultar progreso del clasificador',
              '4 clasificados y desglose por modelo', detalle, aprueba)


def p04_estadisticas_autenticadas():
    token = construir_token(WSSE_USUARIO, WSSE_SECRETO)
    estado, datos = enviar(sobre('ObtenerEstadisticasPorModelo', None, token))
    tipo, respuesta, _ = analizar(datos)
    aprueba = False
    detalle = 'Fault {}'.format(respuesta)
    if tipo == 'ok':
        estadisticas = respuesta.findall('{%s}estadistica' % NS)
        aprueba = estado == 200 and len(estadisticas) == 4
        detalle = ', '.join('{}={}'.format(e.findtext('{%s}modelo' % NS),
                                           e.findtext('{%s}total' % NS))
                            for e in estadisticas)
    registrar('P04', 'Estadisticas con WS-Security valido',
              'Conteo de los 4 modelos', detalle, aprueba)
    return token


# -----------------------------------------------------------------------------
# Pruebas negativas
# -----------------------------------------------------------------------------
def negativa(id_prueba, descripcion, esperado_codigo, esperado_estado,
             operacion, contenido=None, token=None, datos_crudos=None):
    if datos_crudos is not None:
        estado, datos = enviar(datos_crudos)
    else:
        estado, datos = enviar(sobre(operacion, contenido, token))
    try:
        tipo, codigo, _ = analizar(datos)
    except ET.ParseError:
        registrar(id_prueba, descripcion, esperado_codigo,
                  'respuesta no analizable', False)
        return
    aprueba = tipo == 'fault' and codigo == esperado_codigo and estado == esperado_estado
    registrar(id_prueba, descripcion,
              'SOAP Fault {} / HTTP {}'.format(esperado_codigo, esperado_estado),
              'Fault {} / HTTP {}'.format(codigo if tipo == 'fault' else 'ninguno',
                                          estado),
              aprueba)


def n01_duplicada(usados):
    concepto_id, isbn = usados[0]

    def contenido(elemento):
        clasificador = ET.SubElement(elemento, '{%s}clasificador' % NS)
        campo(clasificador, 'nombre', 'Pablo')
        campo(clasificador, 'apellidos', 'Prueba Automatizada')
        campo(clasificador, 'correo', CORREO)
        campo(elemento, 'conceptoId', concepto_id)
        campo(elemento, 'isbn', isbn)
        campo(elemento, 'modelo', 'SaaS')

    negativa('N01', 'Repetir la misma clasificacion',
             'CLASIFICACION_DUPLICADA', 409, 'RegistrarClasificacion', contenido)


def n02_concepto_inexistente(usados):
    _, isbn = usados[0]

    def contenido(elemento):
        clasificador = ET.SubElement(elemento, '{%s}clasificador' % NS)
        campo(clasificador, 'nombre', 'Pablo')
        campo(clasificador, 'apellidos', 'Prueba Automatizada')
        campo(clasificador, 'correo', CORREO)
        campo(elemento, 'conceptoId', 99999)
        campo(elemento, 'isbn', isbn)
        campo(elemento, 'modelo', 'IaaS')

    negativa('N02', 'Concepto inexistente', 'CONCEPTO_INEXISTENTE', 404,
             'RegistrarClasificacion', contenido)


def n03_modelo_invalido(usados):
    concepto_id, isbn = usados[1]

    def contenido(elemento):
        clasificador = ET.SubElement(elemento, '{%s}clasificador' % NS)
        campo(clasificador, 'nombre', 'Pablo')
        campo(clasificador, 'apellidos', 'Prueba Automatizada')
        campo(clasificador, 'correo', CORREO)
        campo(elemento, 'conceptoId', concepto_id)
        campo(elemento, 'isbn', isbn)
        campo(elemento, 'modelo', 'XaaS')

    negativa('N03', 'Modelo Cloud invalido', 'MODELO_INVALIDO', 400,
             'RegistrarClasificacion', contenido)


def n04_xml_invalido():
    negativa('N04', 'XML mal formado', 'XML_INVALIDO', 400, None,
             datos_crudos=b'<soap:Envelope><soap:Body><sin cerrar>')


def n05_sin_credenciales():
    negativa('N05', 'Estadisticas sin WS-Security', 'NO_AUTORIZADO', 401,
             'ObtenerEstadisticasPorModelo')


def n06_credenciales_incorrectas():
    token = construir_token(WSSE_USUARIO, 'secreto-equivocado')
    negativa('N06', 'Estadisticas con contrasena incorrecta', 'NO_AUTORIZADO',
             401, 'ObtenerEstadisticasPorModelo', None, token)


def n07_operacion_desconocida():
    negativa('N07', 'Operacion fuera del contrato', 'OPERACION_DESCONOCIDA', 400,
             'BorrarTodoElCatalogo')


def n08_correo_invalido():
    negativa('N08', 'Correo con formato invalido', 'DATO_INVALIDO', 400,
             'ObtenerProgresoUsuario',
             lambda e: campo(e, 'correo', 'esto-no-es-un-correo'))


def n09_libro_inexistente(usados):
    concepto_id, _ = usados[2]

    def contenido(elemento):
        clasificador = ET.SubElement(elemento, '{%s}clasificador' % NS)
        campo(clasificador, 'nombre', 'Pablo')
        campo(clasificador, 'apellidos', 'Prueba Automatizada')
        campo(clasificador, 'correo', CORREO)
        campo(elemento, 'conceptoId', concepto_id)
        campo(elemento, 'isbn', '978-0-00-000000-0')
        campo(elemento, 'modelo', 'PaaS')

    negativa('N09', 'ISBN que no existe', 'LIBRO_INEXISTENTE', 404,
             'RegistrarClasificacion', contenido)


def n10_clasificador_inexistente():
    negativa('N10', 'Progreso de un correo no registrado',
             'CLASIFICADOR_INEXISTENTE', 404, 'ObtenerProgresoUsuario',
             lambda e: campo(e, 'correo', 'nadie.jamas@libreria.udem.mx'))


def n11_replay(token):
    # El MISMO token de P04, reenviado: el nonce ya se uso.
    negativa('N11', 'Reenvio del mismo token (replay)', 'NO_AUTORIZADO', 401,
             'ObtenerEstadisticasPorModelo', None, token)


# -----------------------------------------------------------------------------
def tabla_markdown():
    lineas = ['| ID | Prueba | Resultado esperado | Resultado obtenido | Estado |',
              '|---|---|---|---|---|']
    for r in resultados:
        lineas.append('| {id} | {prueba} | {esperado} | {obtenido} | {estado} |'
                      .format(**r))
    return '\n'.join(lineas)


def main():
    print('Endpoint: {}'.format(ENDPOINT))
    print('Clasificador de prueba: {}\n'.format(CORREO))

    print('--- Pruebas positivas ---------------------------------------------')
    conceptos = p01_conceptos_pendientes()
    if not conceptos or len(conceptos) < 4:
        print('\nNo hay conceptos pendientes suficientes para continuar.')
        return 1
    usados = p02_registrar(conceptos)
    p03_progreso()
    token = p04_estadisticas_autenticadas()

    print('\n--- Pruebas negativas ---------------------------------------------')
    n01_duplicada(usados)
    n02_concepto_inexistente(usados)
    n03_modelo_invalido(usados)
    n04_xml_invalido()
    n05_sin_credenciales()
    n06_credenciales_incorrectas()
    n07_operacion_desconocida()
    n08_correo_invalido()
    n09_libro_inexistente(usados)
    n10_clasificador_inexistente()
    n11_replay(token)

    fallidas = [r for r in resultados if r['estado'] == 'FALLA']
    print('\n{} pruebas, {} fallidas'.format(len(resultados), len(fallidas)))

    if '--markdown' in sys.argv:
        destino = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'resultados.md')
        with open(destino, 'w', encoding='utf-8') as archivo:
            archivo.write('# Resultados de las pruebas del modulo SOAP\n\n')
            archivo.write('Endpoint: `{}`\n\n'.format(ENDPOINT))
            archivo.write(tabla_markdown() + '\n')
        print('Tabla escrita en {}'.format(destino))

    return 1 if fallidas else 0


if __name__ == '__main__':
    sys.exit(main())
