# -*- coding: utf-8 -*-
"""Benchmark de lectura: PostgreSQL (consultas con JOIN) contra Redis (cache).

    cd /opt/udem/libreria/tests/benchmark_redis
    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    python benchmark.py                       # 1000 repeticiones por escenario
    python benchmark.py -n 5000 | tee ../../evidencias/benchmark_redis.txt

Mide, con los datos reales de la VM, cuanto tarda en llegar el MISMO
resultado a un programa Python por dos caminos:

  - PostgreSQL: ejecutar la consulta con JOIN y convertir las filas a dict.
  - Redis:      leer de Redis ese resultado ya serializado (JSON) y json.loads.

Tres escenarios, de mas simple a mas parecido al uso real:

  1. join      Un unico SELECT: libros JOIN formatos JOIN libros_autores
               JOIN autores. Lo que pide "un query con join".
  2. catalogo  Lo que hace de verdad GET /books del microservicio de catalogo:
               el SELECT de libros y los cuatro de relaciones N:M (autores,
               generos, imagenes, conceptos), armado en dicts anidados.
  3. isbn      Un libro completo por ISBN, elegido al azar en cada vuelta.
               Es el patron de GET /books/<isbn>.

Configuracion, toda por variable de entorno (nunca se escribe una credencial
en este archivo):

  - DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD: los mismos nombres que el
    catalogo. Por omision se cargan de apps/services/catalogo/.env, que en la
    VM ya los tiene; --env apunta a otro archivo.
  - REDIS_URL: redis://127.0.0.1:6379/0 por omision. Si tu Redis tiene
    contrasena: REDIS_URL='redis://:<contrasena>@127.0.0.1:6379/0' en la
    linea de comandos, no en un archivo versionado.

Garantias:

  - PostgreSQL se abre en modo SOLO LECTURA: el script no puede escribir en la
    base aunque tuviera un error.
  - En Redis solo toca claves con prefijo `bench:`, todas con TTL de 10 min, y
    las borra al terminar (salvo --conservar). No usa FLUSHDB ni KEYS.

Que NO mide, y conviene decirlo al presentar los numeros:

  - No compara "una base contra otra": Redis aqui es una cache del resultado
    que PostgreSQL ya calculo. Sin PostgreSQL no habria nada que cachear.
  - PostgreSQL tambien tiene cache (shared_buffers): tras el calentamiento los
    datos ya estan en memoria, asi que la diferencia que se ve es el costo de
    planear y ejecutar los JOIN y de viajar por varias consultas, no de disco.
  - Una conexion persistente por lado: no mide el costo de conectar.
"""
import argparse
import json
import os
import random
import statistics
import sys
import time
from decimal import Decimal

import psycopg2
import redis
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

RAIZ_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
ENV_POR_OMISION = os.path.join(RAIZ_REPO, 'apps', 'services', 'catalogo', '.env')

PREFIJO = 'bench:'
TTL_SEGUNDOS = 600

# -----------------------------------------------------------------------------
# Consultas. SQL_LIBROS y las cuatro de relaciones son copia literal de
# apps/services/catalogo/app.py: los servicios no comparten codigo, e importar
# app.py arrancaria la configuracion de Flask y exigiria JWT_SECRET solo para
# leer unas cadenas. Si alla cambian, hay que copiarlas de nuevo.
# -----------------------------------------------------------------------------
SQL_JOIN = """
    SELECT l.id, l.isbn, l.titulo, l.anio_publicacion, l.precio, l.stock,
           f.nombre AS formato, a.nombre AS autor, la.orden
      FROM libros l
      JOIN formatos f            ON f.id = l.formato_id
      LEFT JOIN libros_autores la ON la.libro_id = l.id
      LEFT JOIN autores a         ON a.id = la.autor_id
     ORDER BY l.titulo, l.id, la.orden
"""

SQL_LIBROS = """
    SELECT l.id, l.isbn, l.titulo, l.anio_publicacion, l.precio, l.stock,
           f.nombre AS formato
      FROM libros l
      JOIN formatos f ON f.id = l.formato_id
"""

SQL_AUTORES = """
    SELECT la.libro_id, a.nombre, a.nacionalidad, la.orden
      FROM libros_autores la
      JOIN autores a ON a.id = la.autor_id
     WHERE la.libro_id = ANY(%s)
     ORDER BY la.libro_id, la.orden
"""

SQL_GENEROS = """
    SELECT lg.libro_id, g.nombre
      FROM libros_generos lg
      JOIN generos g ON g.id = lg.genero_id
     WHERE lg.libro_id = ANY(%s)
     ORDER BY lg.libro_id, g.nombre
"""

SQL_IMAGENES = """
    SELECT libro_id, nombre_archivo, texto_alternativo, tipo_mime, es_portada
      FROM imagenes_libros
     WHERE libro_id = ANY(%s)
     ORDER BY libro_id, es_portada DESC, id
"""

SQL_CONCEPTOS = """
    SELECT lc.libro_id, co.termino, lc.definicion, lc.capitulo, lc.pagina
      FROM libros_conceptos lc
      JOIN conceptos co ON co.id = lc.concepto_id
     WHERE lc.libro_id = ANY(%s)
     ORDER BY lc.libro_id, co.id
"""


def leer_join(cur):
    cur.execute(SQL_JOIN)
    return [dict(fila) for fila in cur.fetchall()]


def leer_libros(cur, isbn=None):
    """El mismo armado que leer_libros() del catalogo: 1 + 4 consultas."""
    if isbn is None:
        cur.execute(SQL_LIBROS + ' ORDER BY l.titulo, l.id')
    else:
        cur.execute(SQL_LIBROS + ' WHERE l.isbn = %s', (isbn,))
    libros = [dict(fila) for fila in cur.fetchall()]
    if not libros:
        return []

    indice = {libro['id']: libro for libro in libros}
    for libro in libros:
        libro.update(autores=[], generos=[], imagenes=[], conceptos=[])
    ids = list(indice.keys())

    cur.execute(SQL_AUTORES, (ids,))
    for fila in cur.fetchall():
        indice[fila['libro_id']]['autores'].append(dict(fila))
    cur.execute(SQL_GENEROS, (ids,))
    for fila in cur.fetchall():
        indice[fila['libro_id']]['generos'].append(fila['nombre'])
    cur.execute(SQL_IMAGENES, (ids,))
    for fila in cur.fetchall():
        indice[fila['libro_id']]['imagenes'].append(dict(fila))
    cur.execute(SQL_CONCEPTOS, (ids,))
    for fila in cur.fetchall():
        indice[fila['libro_id']]['conceptos'].append(dict(fila))
    return libros


def a_json(datos):
    # precio es NUMERIC -> Decimal, que json no sabe serializar. Como texto,
    # igual que lo entrega el catalogo, para no perder precision con float.
    return json.dumps(datos, ensure_ascii=False,
                      default=lambda v: str(v) if isinstance(v, Decimal) else v)


# -----------------------------------------------------------------------------
# Medicion
# -----------------------------------------------------------------------------
def medir(funcion, repeticiones, calentamiento):
    """Ejecuta `funcion` y devuelve la latencia de cada vuelta, en ms.

    El calentamiento no cuenta: deja el plan de PostgreSQL, sus buffers y la
    conexion de Redis en su estado estable, que es el que vive un servicio
    que ya lleva rato atendiendo.
    """
    for _ in range(calentamiento):
        funcion()
    tiempos = []
    for _ in range(repeticiones):
        inicio = time.perf_counter_ns()
        funcion()
        tiempos.append((time.perf_counter_ns() - inicio) / 1e6)
    return tiempos


def resumen(tiempos):
    total_s = sum(tiempos) / 1000
    return {
        'media': statistics.mean(tiempos),
        'mediana': statistics.median(tiempos),
        'p95': statistics.quantiles(tiempos, n=100)[94],
        'p99': statistics.quantiles(tiempos, n=100)[98],
        'min': min(tiempos),
        'max': max(tiempos),
        'ops': len(tiempos) / total_s if total_s else float('inf'),
    }


def imprimir_escenario(nombre, descripcion, pg, rd, bytes_json):
    print()
    print('=' * 78)
    print('Escenario: {}  --  {}'.format(nombre, descripcion))
    print('Resultado serializado: {:,} bytes'.format(bytes_json))
    print('-' * 78)
    print('{:<12}{:>9}{:>9}{:>9}{:>9}{:>9}{:>9}{:>12}'.format(
        'origen', 'media', 'mediana', 'p95', 'p99', 'min', 'max', 'ops/s'))
    for origen, r in (('PostgreSQL', pg), ('Redis', rd)):
        print('{:<12}{:>9.3f}{:>9.3f}{:>9.3f}{:>9.3f}{:>9.3f}{:>9.3f}{:>12,.0f}'
              .format(origen, r['media'], r['mediana'], r['p95'], r['p99'],
                      r['min'], r['max'], r['ops']))
    print('(latencias en milisegundos)')
    if rd['mediana'] > 0:
        factor = pg['mediana'] / rd['mediana']
        if factor >= 1:
            print('-> Redis es {:.1f}x mas rapido (por mediana).'.format(factor))
        else:
            print('-> PostgreSQL es {:.1f}x mas rapido (por mediana).'.format(1 / factor))


# -----------------------------------------------------------------------------
# Conexiones
# -----------------------------------------------------------------------------
def conectar_pg():
    try:
        conexion = psycopg2.connect(
            host=os.getenv('DB_HOST', '127.0.0.1'),
            port=int(os.getenv('DB_PORT', '5432')),
            dbname=os.getenv('DB_NAME', 'libreria_db'),
            user=os.getenv('DB_USER', 'libreria_app'),
            password=os.getenv('DB_PASSWORD', ''),
            connect_timeout=int(os.getenv('DB_TIMEOUT', '5')),
        )
    except psycopg2.OperationalError as error:
        sys.exit('No se pudo conectar a PostgreSQL: {}'.format(
            str(error).strip().splitlines()[0]))
    # Solo lectura y autocommit: cada SELECT es su propia transaccion, como
    # en el servicio real, y cualquier escritura la rechazaria el servidor.
    conexion.set_session(readonly=True, autocommit=True)
    return conexion


def conectar_redis():
    url = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
    cliente = redis.Redis.from_url(url, socket_timeout=5)
    try:
        cliente.ping()
    except redis.exceptions.AuthenticationError:
        sys.exit('Redis pide contrasena: pasala en REDIS_URL '
                 "(redis://:<contrasena>@127.0.0.1:6379/0).")
    except redis.exceptions.RedisError as error:
        sys.exit('No se pudo conectar a Redis: {}'.format(error))
    return cliente


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('-n', '--repeticiones', type=int, default=1000,
                        help='vueltas medidas por escenario (1000)')
    parser.add_argument('--calentamiento', type=int, default=50,
                        help='vueltas previas que no se miden (50)')
    parser.add_argument('--env', default=ENV_POR_OMISION,
                        help='archivo .env con DB_* (el del catalogo)')
    parser.add_argument('--conservar', action='store_true',
                        help='no borrar las claves bench:* al terminar')
    args = parser.parse_args()
    if args.repeticiones < 2:
        parser.error('--repeticiones debe ser al menos 2')

    if os.path.exists(args.env):
        load_dotenv(args.env)

    conexion = conectar_pg()
    cur = conexion.cursor(cursor_factory=RealDictCursor)
    cache = conectar_redis()

    servidor_pg = conexion.server_version
    info_redis = cache.info('server')
    cur.execute('SELECT count(*) AS n FROM libros')
    total_libros = cur.fetchone()['n']
    if not total_libros:
        sys.exit('La tabla libros esta vacia: no hay nada que medir.')

    print('Benchmark de lectura: PostgreSQL vs Redis')
    print('PostgreSQL {}.{} en {}:{} / base {}'.format(
        servidor_pg // 10000, servidor_pg % 10000,
        os.getenv('DB_HOST', '127.0.0.1'), os.getenv('DB_PORT', '5432'),
        os.getenv('DB_NAME', 'libreria_db')))
    print('Redis {} / {}'.format(info_redis.get('redis_version'),
                                 cache.connection_pool.connection_kwargs.get('host')))
    print('Libros en la base: {}'.format(total_libros))
    print('Repeticiones: {} (+{} de calentamiento) por escenario y origen'.format(
        args.repeticiones, args.calentamiento))

    claves = []

    def guardar(clave, datos):
        texto = a_json(datos)
        cache.set(clave, texto, ex=TTL_SEGUNDOS)
        claves.append(clave)
        return len(texto.encode('utf-8'))

    def leer_cache(clave):
        return json.loads(cache.get(clave))

    try:
        # --- 1. JOIN unico ---------------------------------------------------
        clave_join = PREFIJO + 'join'
        inicio = time.perf_counter_ns()
        bytes_join = guardar(clave_join, leer_join(cur))
        miss_join = (time.perf_counter_ns() - inicio) / 1e6
        pg = resumen(medir(lambda: leer_join(cur),
                           args.repeticiones, args.calentamiento))
        rd = resumen(medir(lambda: leer_cache(clave_join),
                           args.repeticiones, args.calentamiento))
        imprimir_escenario('join', 'libros+formatos+autores en un SELECT',
                           pg, rd, bytes_join)
        print('   Primera peticion sin cache (PostgreSQL + SET): {:.3f} ms'
              .format(miss_join))

        # --- 2. Catalogo completo, como GET /books ---------------------------
        clave_cat = PREFIJO + 'catalogo'
        inicio = time.perf_counter_ns()
        catalogo = leer_libros(cur)
        bytes_cat = guardar(clave_cat, catalogo)
        miss_cat = (time.perf_counter_ns() - inicio) / 1e6
        pg = resumen(medir(lambda: leer_libros(cur),
                           args.repeticiones, args.calentamiento))
        rd = resumen(medir(lambda: leer_cache(clave_cat),
                           args.repeticiones, args.calentamiento))
        imprimir_escenario('catalogo', 'GET /books: 1 + 4 consultas con JOIN',
                           pg, rd, bytes_cat)
        print('   Primera peticion sin cache (PostgreSQL + SET): {:.3f} ms'
              .format(miss_cat))

        # --- 3. Un libro por ISBN, como GET /books/<isbn> --------------------
        # Una clave por libro, cargadas de una vez con pipeline. La semilla
        # fija hace que PostgreSQL y Redis pidan la misma secuencia de ISBN.
        tuberia = cache.pipeline(transaction=False)
        for libro in catalogo:
            clave = PREFIJO + 'libro:' + libro['isbn']
            tuberia.set(clave, a_json([libro]), ex=TTL_SEGUNDOS)
            claves.append(clave)
        tuberia.execute()
        isbns = [libro['isbn'] for libro in catalogo]
        bytes_isbn = int(statistics.mean(
            len(a_json([libro]).encode('utf-8')) for libro in catalogo))

        azar = random.Random(42)
        pg = resumen(medir(lambda: leer_libros(cur, azar.choice(isbns)),
                           args.repeticiones, args.calentamiento))
        azar = random.Random(42)
        rd = resumen(medir(
            lambda: leer_cache(PREFIJO + 'libro:' + azar.choice(isbns)),
            args.repeticiones, args.calentamiento))
        imprimir_escenario('isbn', 'GET /books/<isbn>: un libro al azar',
                           pg, rd, bytes_isbn)
        print('   (tamano: promedio por libro)')

        # Ambos caminos deben devolver lo mismo; si no, la comparacion no vale.
        assert leer_cache(clave_cat) == json.loads(a_json(leer_libros(cur))), \
            'Redis y PostgreSQL devolvieron datos distintos'
        print()
        print('Verificado: Redis y PostgreSQL devuelven el mismo catalogo.')
    finally:
        if claves and not args.conservar:
            cache.delete(*claves)
            print('Claves {}* borradas de Redis ({}).'.format(PREFIJO, len(claves)))
        cur.close()
        conexion.close()


if __name__ == '__main__':
    main()
