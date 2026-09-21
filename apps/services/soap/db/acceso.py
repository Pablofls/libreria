# =============================================================================
# db/acceso.py
# Capa de acceso a datos del modulo SOAP. Aqui vive TODO el SQL; ni el sobre ni
# el despacho saben que hay PostgreSQL detras.
#
# Reglas que se cumplen sin excepcion en este archivo:
#   * Consultas parametrizadas (%s). Ningun valor del cliente se concatena.
#   * Se lee de vistas y se escribe con un procedimiento almacenado, no con
#     INSERT sueltos: la operacion que toca tres tablas es una transaccion del
#     lado del servidor y no puede quedar a medias.
#   * Los errores de PostgreSQL se traducen al vocabulario de faults del modulo.
#     El texto original de psycopg2 nunca sale de aqui: se adjunta como
#     detalle_interno, que solo va al log.
# =============================================================================

import logging
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from config import ajustes
from soap.faults import (ClasificacionDuplicada, ClasificadorInexistente,
                         ConceptoInexistente, ErrorServidor, LibroInexistente,
                         ModeloInvalido)

log = logging.getLogger('soap.db')

_pool = None


def _obtener_pool():
    global _pool
    if _pool is None:
        try:
            _pool = ThreadedConnectionPool(1, ajustes.POOL_MAX, **ajustes.BD)
        except psycopg2.OperationalError as error:
            raise ErrorServidor(
                'El servicio no puede conectarse a su base de datos.',
                detalle_interno=str(error))
        log.info('Pool creado contra %s:%s/%s como %s',
                 ajustes.BD['host'], ajustes.BD['port'],
                 ajustes.BD['dbname'], ajustes.BD['user'])
    return _pool


@contextmanager
def transaccion(escribe=False):
    pool = _obtener_pool()
    conexion = pool.getconn()
    try:
        with conexion.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conexion.commit() if escribe else conexion.rollback()
    except Exception:
        # Rollback explicito: si una operacion de escritura fallo a la mitad,
        # la conexion vuelve al pool limpia y no arrastra la transaccion rota.
        conexion.rollback()
        raise
    finally:
        pool.putconn(conexion)


def _traducir(error):
    """Convierte un error de PostgreSQL en el fault que le corresponde.

    Se usa el prefijo que levanta fn_registrar_clasificacion (CONCEPTO_
    INEXISTENTE:, MODELO_INVALIDO:, ...) en lugar de interpretar el texto libre:
    el prefijo es parte del contrato interno entre el procedimiento y esta capa.
    """
    mensaje = ''
    if getattr(error, 'diag', None) is not None:
        mensaje = error.diag.message_primary or ''
    etiqueta = mensaje.split(':', 1)[0].strip()

    interno = str(error)
    if etiqueta == 'CLASIFICACION_DUPLICADA':
        return ClasificacionDuplicada(
            'Ese concepto ya fue clasificado por este clasificador.',
            campo='conceptoId', detalle_interno=interno)
    if etiqueta == 'CONCEPTO_INEXISTENTE':
        return ConceptoInexistente(
            'El concepto indicado no esta definido en ese libro.',
            campo='conceptoId', detalle_interno=interno)
    if etiqueta == 'LIBRO_INEXISTENTE':
        return LibroInexistente('No existe un libro con ese ISBN.',
                                campo='isbn', detalle_interno=interno)
    if etiqueta == 'MODELO_INVALIDO':
        return ModeloInvalido('El modelo debe ser IaaS, PaaS, SaaS o FaaS.',
                              campo='modelo', detalle_interno=interno)

    if isinstance(error, psycopg2.errors.UniqueViolation):
        return ClasificacionDuplicada('Ese registro ya existe.',
                                      detalle_interno=interno)
    if isinstance(error, psycopg2.errors.InsufficientPrivilege):
        # Sintoma tipico de un despliegue mal configurado: el rol del modulo no
        # tiene el GRANT. Al cliente no se le explica la topologia de permisos.
        return ErrorServidor('El servicio no pudo completar la operacion.',
                             detalle_interno=interno)
    return ErrorServidor('El servicio no pudo completar la operacion.',
                         detalle_interno=interno)


# -----------------------------------------------------------------------------
# ObtenerConceptosPendientes
# -----------------------------------------------------------------------------
SQL_PENDIENTES_GLOBAL = """
    SELECT concepto_id, termino, definicion, isbn, libro, categoria,
           capitulo, pagina
      FROM v_conceptos_pendientes
     ORDER BY termino, isbn
     LIMIT %s
"""

SQL_PENDIENTES_GLOBAL_TOTAL = "SELECT count(*)::int AS total FROM v_conceptos_pendientes"

# Pendientes PARA UN CLASIFICADOR: lo que el todavia no ha registrado, aunque
# otro ya lo haya hecho. La restriccion de no repetir es por concepto, asi que
# el filtro tambien lo es.
SQL_PENDIENTES_USUARIO = """
    SELECT v.concepto_id, v.termino, v.definicion, v.isbn, v.libro, v.categoria,
           v.capitulo, v.pagina
      FROM v_conceptos_clasificables v
     WHERE NOT EXISTS (
               SELECT 1
                 FROM clasificaciones_cloud cc
                 JOIN clasificadores c ON c.id = cc.clasificador_id
                WHERE cc.concepto_id = v.concepto_id
                  AND lower(c.correo) = lower(%s))
     ORDER BY v.termino, v.isbn
     LIMIT %s
"""

SQL_PENDIENTES_USUARIO_TOTAL = """
    SELECT count(*)::int AS total
      FROM v_conceptos_clasificables v
     WHERE NOT EXISTS (
               SELECT 1
                 FROM clasificaciones_cloud cc
                 JOIN clasificadores c ON c.id = cc.clasificador_id
                WHERE cc.concepto_id = v.concepto_id
                  AND lower(c.correo) = lower(%s))
"""


def conceptos_pendientes(correo=None, limite=None):
    limite = min(limite or ajustes.LIMITE_POR_DEFECTO, ajustes.LIMITE_MAXIMO)
    try:
        with transaccion() as cur:
            if correo:
                cur.execute(SQL_PENDIENTES_USUARIO_TOTAL, (correo,))
                total = cur.fetchone()['total']
                cur.execute(SQL_PENDIENTES_USUARIO, (correo, limite))
            else:
                cur.execute(SQL_PENDIENTES_GLOBAL_TOTAL)
                total = cur.fetchone()['total']
                cur.execute(SQL_PENDIENTES_GLOBAL, (limite,))
            return total, [dict(fila) for fila in cur.fetchall()]
    except psycopg2.Error as error:
        raise _traducir(error)


# -----------------------------------------------------------------------------
# RegistrarClasificacion
# -----------------------------------------------------------------------------
SQL_REGISTRAR = """
    SELECT clasificacion_id, clasificador_id, libro_id, termino, libro,
           clasificado_en, peticiones_atendidas
      FROM fn_registrar_clasificacion(%s, %s, %s, %s, %s, %s, %s, %s)
"""


def registrar_clasificacion(nombre, apellidos, correo, concepto_id, isbn,
                            modelo, tipo_cliente=None, id_cliente=None):
    """Una sola llamada: el procedimiento hace el alta del clasificador, el
    contador del cliente y el registro dentro de la misma transaccion."""
    try:
        with transaccion(escribe=True) as cur:
            cur.execute(SQL_REGISTRAR, (nombre, apellidos, correo, concepto_id,
                                        isbn, modelo, tipo_cliente, id_cliente))
            fila = cur.fetchone()
            if fila is None:
                raise ErrorServidor('El registro no devolvio resultado.')
            return dict(fila)
    except psycopg2.Error as error:
        raise _traducir(error)


# -----------------------------------------------------------------------------
# ObtenerProgresoUsuario
# -----------------------------------------------------------------------------
SQL_PROGRESO = """
    SELECT clasificador_id, correo, nombre, apellidos,
           total_clasificados, total_pendientes
      FROM v_progreso_clasificadores
     WHERE lower(correo) = lower(%s)
"""

SQL_PROGRESO_MODELOS = """
    SELECT m.modelo, count(cc.id)::int AS total
      FROM (VALUES ('IaaS'), ('PaaS'), ('SaaS'), ('FaaS')) AS m(modelo)
      LEFT JOIN clasificaciones_cloud cc
             ON cc.modelo = m.modelo AND cc.clasificador_id = %s
     GROUP BY m.modelo
     ORDER BY m.modelo
"""


def progreso_usuario(correo):
    try:
        with transaccion() as cur:
            cur.execute(SQL_PROGRESO, (correo,))
            fila = cur.fetchone()
            if fila is None:
                # Se avisa en vez de responder ceros: un correo mal escrito en
                # la GUI daria un "0 de 30" que parece un dato y es un error.
                raise ClasificadorInexistente(
                    'No hay ningun clasificador registrado con ese correo.',
                    campo='correo')
            cur.execute(SQL_PROGRESO_MODELOS, (fila['clasificador_id'],))
            modelos = [dict(m) for m in cur.fetchall()]
            return dict(fila), modelos
    except psycopg2.Error as error:
        raise _traducir(error)


# -----------------------------------------------------------------------------
# ObtenerEstadisticasPorModelo  (Tarea 1)
# -----------------------------------------------------------------------------
SQL_ESTADISTICAS = """
    SELECT modelo, total, clasificadores
      FROM v_estadisticas_modelo
     ORDER BY modelo
"""


def estadisticas_por_modelo():
    try:
        with transaccion() as cur:
            cur.execute(SQL_ESTADISTICAS)
            return [dict(fila) for fila in cur.fetchall()]
    except psycopg2.Error as error:
        raise _traducir(error)


def comprobar_conexion():
    """Para /health. Devuelve (ok, detalle_para_el_log)."""
    try:
        with transaccion() as cur:
            cur.execute('SELECT count(*)::int AS total FROM v_conceptos_clasificables')
            return True, cur.fetchone()['total']
    except Exception as error:
        return False, str(error)
