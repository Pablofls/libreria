# =============================================================================
# tests/cliente_zeep.py — Tarea 4: interoperabilidad.
#
# Este cliente NO conoce el codigo del servidor. Recibe una URL de WSDL y genera
# los stubs solo: si el contrato esta bien escrito, esto funciona; si el
# contrato miente sobre lo que el servidor hace, revienta aqui.
#
#     pip install -r requirements-interop.txt
#     python3 tests/cliente_zeep.py http://VM:5001/soap?wsdl
#
# Compara con tests/pruebas_soap.py, que arma el sobre a mano: mismas
# operaciones, cero XML escrito por el programador.
# =============================================================================

import os
import sys
from datetime import datetime

from zeep import Client
from zeep.exceptions import Fault
from zeep.wsse.username import UsernameToken

WSDL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5001/soap?wsdl'
CORREO = os.getenv('CORREO_PRUEBA',
                   'interop.{}@libreria.udem.mx'.format(int(datetime.now().timestamp())))


def titulo(texto):
    print('\n' + texto)
    print('-' * len(texto))


def main():
    titulo('1. Generar el cliente a partir del contrato')
    cliente = Client(WSDL)
    servicio = cliente.service
    enlace = list(cliente.wsdl.bindings.values())[0]
    operaciones = sorted(enlace.all().keys())
    print('WSDL: {}'.format(WSDL))
    print('Operaciones descubiertas sin ver el servidor: {}'
          .format(', '.join(operaciones)))

    titulo('2. ObtenerConceptosPendientes')
    respuesta = servicio.ObtenerConceptosPendientes(limite=3)
    print('Pendientes totales: {}'.format(respuesta.total))
    for concepto in respuesta.concepto:
        print('  [{}] {:<22} {}  ({})'.format(
            concepto.conceptoId, concepto.termino, concepto.libro,
            concepto.categoria))

    if not respuesta.concepto:
        print('No hay conceptos pendientes; no se puede continuar.')
        return 1
    primero = respuesta.concepto[0]

    titulo('3. RegistrarClasificacion')
    # zeep valida contra el XSD ANTES de salir a la red: si el modelo no esta en
    # la enumeracion, ni siquiera se envia la peticion.
    resultado = servicio.RegistrarClasificacion(
        clasificador={'nombre': 'Cliente', 'apellidos': 'Zeep',
                      'correo': CORREO},
        conceptoId=primero.conceptoId,
        isbn=primero.isbn,
        modelo='PaaS',
        cliente={'tipo': 'zeep-interop', 'identificador': 'tarea-04'})
    print('Registrado id={} termino={} modelo={} en {}'.format(
        resultado.clasificacionId, resultado.termino, resultado.modelo,
        resultado.registradoEn))

    titulo('4. El mismo registro otra vez: SOAP Fault de conflicto')
    try:
        servicio.RegistrarClasificacion(
            clasificador={'nombre': 'Cliente', 'apellidos': 'Zeep',
                          'correo': CORREO},
            conceptoId=primero.conceptoId, isbn=primero.isbn, modelo='SaaS')
        print('FALLA: se esperaba un Fault y no llego')
        return 1
    except Fault as fault:
        print('Fault recibido y entendido por zeep: {}'.format(fault.message))

    titulo('5. Validacion del XSD del lado del CLIENTE')
    try:
        servicio.RegistrarClasificacion(
            clasificador={'nombre': 'Cliente', 'apellidos': 'Zeep',
                          'correo': CORREO},
            conceptoId=primero.conceptoId, isbn=primero.isbn, modelo='XaaS')
        print('FALLA: el XSD debio rechazar el modelo XaaS')
        return 1
    except Exception as error:
        print('El stub rechazo "XaaS" sin gastar una llamada de red:')
        print('  {}'.format(str(error).splitlines()[0]))

    titulo('6. ObtenerProgresoUsuario')
    progreso = servicio.ObtenerProgresoUsuario(correo=CORREO)
    print('{}: {} clasificados, {} pendientes'.format(
        progreso.nombre, progreso.totalClasificados, progreso.totalPendientes))

    titulo('7. ObtenerEstadisticasPorModelo con WS-Security')
    usuario = os.getenv('WSSE_USUARIO', 'reportes')
    secreto = os.getenv('WSSE_SECRETO', '')
    if not secreto:
        print('WSSE_SECRETO sin definir: se omite la operacion protegida.')
    else:
        # UsernameToken con PasswordDigest: zeep lo arma segun el mismo perfil
        # OASIS que implementa soap/security.py. Ninguno de los dos lados
        # conoce el codigo del otro.
        seguro = Client(WSDL, wsse=UsernameToken(usuario, secreto,
                                                 use_digest=True))
        estadisticas = seguro.service.ObtenerEstadisticasPorModelo()
        for fila in estadisticas.estadistica:
            print('  {:<5} {:>3} clasificaciones de {} clasificadores'.format(
                fila.modelo, fila.total, fila.clasificadores))

    titulo('Conclusion')
    print('El contrato basto para consumir el servicio desde otro stack.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
