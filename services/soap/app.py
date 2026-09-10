# =============================================================================
# app.py — microservicio de catalogo de la Libreria Online.
#
#     cd services/soap
#     python3 -m venv .venv && . .venv/bin/activate
#     pip install -r requirements.txt
#     cp .env.example .env          # y completa las credenciales EN LA VM
#     python app.py                 # -> http://127.0.0.1:5000/docs
#                                   #    (SOAP_PORT=5001 en la VM)
#
# Una sola aplicacion Flask, SIN Blueprints, como pide el enunciado. Lee de la
# misma base PostgreSQL que el monolito Node (ver db/01_schema.sql) y responde
# XML con la misma estructura que library.xml, de modo que library.css sirve
# para las dos: el catalogo se ve en el navegador sin HTML intermedio.
#
# Todos los endpoints responden en XML o en JSON, indistintamente, segun el
# parametro ?format=:
#
#     /books                        -> XML  (sin format, siempre XML)
#     /books?format=json            -> JSON
#     /books/9780451524935?format=json
#
# Las rutas historicas con prefijo /api siguen atendiendo igual: /books es un
# alias de /api/books, no un reemplazo.
#
# Ninguna credencial vive en este archivo. Todas se leen del .env, que no se
# versiona (.gitignore). El repositorio es publico.
# =============================================================================

import copy
import hmac
import json
import logging
import os
import re
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

import psycopg2
from psycopg2 import errors as pgerrors
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory, url_for
from werkzeug.exceptions import HTTPException
from flask_cors import CORS

RAIZ = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(RAIZ, '.env'))

logging.basicConfig(
    level=os.getenv('LOG_NIVEL', 'INFO').upper(),
    format='%(asctime)s %(levelname)s %(message)s',
)
log = logging.getLogger('catalogo')

# -----------------------------------------------------------------------------
# Configuracion. Los mismos nombres de variable que usa el monolito Node
# (config/env.js), para que un solo .env pueda servir a los dos servicios.
# -----------------------------------------------------------------------------
BD = {
    'host':     os.getenv('DB_HOST', '127.0.0.1'),
    'port':     int(os.getenv('DB_PORT', '5432')),
    'dbname':   os.getenv('DB_NAME', 'libreria_db'),
    'user':     os.getenv('DB_USER', 'libreria_app'),
    'password': os.getenv('DB_PASSWORD', ''),
    'connect_timeout': int(os.getenv('DB_TIMEOUT', '5')),
}

APP_HOST = os.getenv('SOAP_HOST', '0.0.0.0')
APP_PORT = int(os.getenv('SOAP_PORT', '5000'))

# Origenes permitidos, separados por coma. '*' porque el enunciado pide que lo
# consuman clientes de otro dominio y el servicio no usa cookies ni sesion: no
# hay nada que un origen ajeno pueda robar del navegador de un tercero.
ORIGENES = [o.strip() for o in os.getenv('CORS_ORIGENES', '*').split(',') if o.strip()]

# Candado OPCIONAL de escritura. Si API_TOKEN esta vacio, insert/update/delete
# quedan abiertos a cualquiera que alcance el puerto: comodo para la practica,
# inaceptable en un servicio expuesto. Con la variable puesta, las escrituras
# exigen la cabecera X-API-Key. El valor vive en el .env, nunca aqui.
API_TOKEN = os.getenv('API_TOKEN', '').strip()

# Hoja de estilos con la que el navegador dibuja el XML.
HOJA_ESTILOS = os.getenv('SOAP_HOJA_ESTILOS', '/library.css')

app = Flask(__name__)

CORS(
    app,
    resources={r'/api/*': {'origins': ORIGENES},
               r'/books': {'origins': ORIGENES},
               r'/books/*': {'origins': ORIGENES},
               r'/health': {'origins': ORIGENES}},
    methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allow_headers=['Content-Type', 'X-API-Key'],
    max_age=86400,
)

# -----------------------------------------------------------------------------
# Conexion a PostgreSQL. Un unico pool para todo el proceso, igual que el Pool
# de pg en config/db.js. Se crea al primer uso para que /docs siga respondiendo
# aunque la base este caida.
# -----------------------------------------------------------------------------
_pool = None


def _obtener_pool():
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(1, int(os.getenv('DB_POOL_MAX', '10')), **BD)
        log.info('Pool de conexiones creado contra %s:%s/%s',
                 BD['host'], BD['port'], BD['dbname'])
    return _pool


@contextmanager
def cursor_bd(escribe=False):
    """Presta una conexion del pool. Confirma solo si la operacion escribe."""
    pool = _obtener_pool()
    conexion = pool.getconn()
    try:
        with conexion.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conexion.commit() if escribe else conexion.rollback()
    except Exception:
        conexion.rollback()
        raise
    finally:
        pool.putconn(conexion)


# -----------------------------------------------------------------------------
# Respuestas. La estructura del catalogo es la de library.xml:
#   <library><books><book isbn="..."> title, authors, year, genres, price,
#                                     stock, format, images, concepts </book>
#
# Cada endpoint contesta en XML o en JSON, indistintamente, segun el parametro
# ?format=. Para que los dos formatos no se separen al primer cambio de esquema,
# ninguna vista construye XML: arma una estructura neutra de dicts y listas
# —la unica fuente de verdad— y `responder` elige el renderizador. Los nombres
# de esa estructura son los mismos que las etiquetas XML, asi que el JSON se lee
# igual que el XML y un cliente puede cambiar de formato sin cambiar de mapeo.
# -----------------------------------------------------------------------------
CABECERA = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<?xml-stylesheet type="text/css" href="{hoja}"?>\n')

FORMATOS = ('xml', 'json')


def formato_pedido():
    """Formato de salida. El parametro ?format= manda; sin el, XML.

    El respaldo por `Accept` solo entra cuando el cliente pide JSON de forma
    explicita: un `Accept: */*` —lo que envia curl— o el de un navegador siguen
    recibiendo XML, para no cambiarle la respuesta a ningun cliente existente.
    """
    crudo = (request.args.get('format') or '').strip().lower()
    if crudo in FORMATOS:
        return crudo
    if crudo:
        # Valor desconocido: _rechazar_formato_desconocido ya devolvio un 400
        # antes de llegar a la vista. Si aun asi se llega aqui, gana el default.
        return 'xml'
    if request.accept_mimetypes.best_match(
            ('application/xml', 'application/json')) == 'application/json':
        return 'json'
    return 'xml'


@app.before_request
def _rechazar_formato_desconocido():
    """Un ?format= que no existe es un error del cliente, no un XML silencioso.

    Va en before_request para cubrir tambien las rutas inexistentes: el 404 se
    levanta al despachar, es decir despues de este gancho.
    """
    crudo = request.args.get('format')
    if crudo is None or crudo.strip().lower() in FORMATOS:
        return None
    return error_respuesta(
        400, 'El parametro "format" no admite ese valor.',
        ['Valores validos: ' + ', '.join(FORMATOS) + '.',
         'Sin el parametro, la respuesta es XML.'])


def _json_serializable(valor):
    """`Decimal` no es serializable por json: el precio viaja como numero."""
    if isinstance(valor, Decimal):
        return round(float(valor), 2)
    raise TypeError('No se puede serializar un {}.'.format(type(valor).__name__))


def responder_json(datos, estado=200):
    # ensure_ascii=False para que los acentos y la ñ se lean igual que en el XML.
    cuerpo = json.dumps(datos, ensure_ascii=False, indent=2,
                        default=_json_serializable)
    return Response(cuerpo + '\n', status=estado,
                    content_type='application/json; charset=utf-8')


def responder_xml(raiz, estado=200):
    if hasattr(ET, 'indent'):
        ET.indent(raiz, space='  ')
    cuerpo = CABECERA.format(hoja=HOJA_ESTILOS) + ET.tostring(raiz, encoding='unicode')
    return Response(cuerpo + '\n', status=estado,
                    content_type='application/xml; charset=utf-8')


def responder(tipo, datos, estado=200):
    """Unica salida del servicio: misma estructura, dos serializaciones."""
    if formato_pedido() == 'json':
        return responder_json(datos, estado)
    return responder_xml(RENDERIZADORES_XML[tipo](datos), estado)


def _hijo(padre, etiqueta, valor=None, atributos=None):
    elemento = ET.SubElement(padre, etiqueta, atributos or {})
    if valor is not None:
        elemento.text = str(valor)
    return elemento


# --- Estructura neutra -------------------------------------------------------
def _autores_a_dict(autores):
    registros = []
    for autor in autores:
        registro = {'name': autor['nombre'], 'order': autor['orden']}
        if autor.get('nacionalidad'):
            registro['nationality'] = autor['nacionalidad']
        registros.append(registro)
    return registros


def _imagenes_a_dict(imagenes):
    registros = []
    for imagen in imagenes:
        registro = {
            'cover': bool(imagen['es_portada']),
            'type': imagen['tipo_mime'],
            # Solo el nombre de archivo: la ruta base de uploads/ es
            # configuracion de la aplicacion, no un dato publico.
            'file': imagen['nombre_archivo'],
        }
        if imagen.get('texto_alternativo'):
            registro['alt'] = imagen['texto_alternativo']
        registros.append(registro)
    return registros


def glosario_a_dict(conceptos):
    """Conceptos -> representacion neutra, con los libros que los definen.

    Es el pivote inverso del catalogo: /books va del libro a sus conceptos y
    esto va del concepto a sus libros. La definicion, el capitulo y la pagina
    cuelgan del par (concepto, libro) y NO del concepto, porque asi esta el
    esquema: el mismo termino se define distinto en cada libro. Un diccionario
    global de terminos seria una dependencia multivaluada que la 4FN separo a
    proposito.
    """
    entradas = []
    for concepto in conceptos:
        libros = []
        for libro in concepto['libros']:
            registro = {
                'isbn': libro['isbn'],
                'title': libro['titulo'],
                'authors': _autores_a_dict(libro.get('autores', [])),
                'year': libro.get('anio_publicacion'),
            }
            if libro.get('capitulo'):
                registro['chapter'] = libro['capitulo']
            if libro.get('pagina') is not None:
                registro['page'] = libro['pagina']
            registro['description'] = libro['definicion']
            libros.append(registro)
        entradas.append({'term': concepto['termino'],
                         'count': len(libros),
                         'books': libros})
    return {'count': len(entradas), 'concepts': entradas}


def resumen_a_dict(libros):
    """Datos minimos del libro mas sus imagenes. Mismas claves que el catalogo,
    solo que menos: un cliente que ya sabe leer /books lee esto sin cambiar."""
    return {
        'count': len(libros),
        'books': [{'isbn': libro['isbn'],
                   'title': libro['titulo'],
                   'images': _imagenes_a_dict(libro.get('imagenes', []))}
                  for libro in libros],
    }


def libro_a_dict(libro):
    """Fila de la base -> representacion neutra del libro.

    Las claves son las etiquetas del XML, no las columnas en espanol: el
    contrato publico ya estaba en ingles y no cambia por añadir JSON.

    Regla unica para lo opcional: lo que el XML omite cuando no hay dato
    (`nationality`, `alt`, `chapter`, `page`) tampoco aparece en el JSON.
    `year` es la excepcion deliberada —el catalogo lo declara para todo libro—,
    asi que va siempre: vacio en XML, `null` en JSON.
    """
    datos = {
        'isbn': libro['isbn'],
        'title': libro['titulo'],
        'authors': [],
        'year': libro.get('anio_publicacion'),
        'genres': list(libro.get('generos', [])),
        'price': libro['precio'],
        'stock': libro['stock'],
        'format': libro['formato'],
        'images': [],
        'concepts': [],
    }

    datos['authors'] = _autores_a_dict(libro.get('autores', []))
    datos['images'] = _imagenes_a_dict(libro.get('imagenes', []))

    for concepto in libro.get('conceptos', []):
        registro = {'term': concepto['termino']}
        if concepto.get('capitulo'):
            registro['chapter'] = concepto['capitulo']
        if concepto.get('pagina') is not None:
            registro['page'] = concepto['pagina']
        # La definicion pertenece al par (libro, concepto): el mismo termino se
        # define distinto en cada libro. Por eso no vive en el catalogo.
        registro['description'] = concepto['definicion']
        datos['concepts'].append(registro)

    return datos


# --- Renderizadores XML ------------------------------------------------------
# Parten de la estructura neutra, nunca de la fila de la base. Aqui vive lo
# unico que el JSON no tiene: que un dato sea atributo o elemento.
def _imagenes_a_xml(padre, imagenes):
    nodo = ET.SubElement(padre, 'images')
    for imagen in imagenes:
        nodo_img = ET.SubElement(nodo, 'image', {
            'cover': 'true' if imagen['cover'] else 'false',
            'type': imagen['type'],
        })
        _hijo(nodo_img, 'file', imagen['file'])
        if 'alt' in imagen:
            _hijo(nodo_img, 'alt', imagen['alt'])
    return nodo


def _autores_a_xml(padre, autores):
    nodo = ET.SubElement(padre, 'authors')
    for autor in autores:
        atributos = {'order': str(autor['order'])}
        if 'nationality' in autor:
            atributos['nationality'] = autor['nationality']
        _hijo(nodo, 'author', autor['name'], atributos)
    return nodo


def libro_a_xml(padre, datos):
    nodo = ET.SubElement(padre, 'book', {'isbn': datos['isbn']})
    _hijo(nodo, 'title', datos['title'])

    _autores_a_xml(nodo, datos['authors'])

    _hijo(nodo, 'year', datos['year'])

    generos = ET.SubElement(nodo, 'genres')
    for genero in datos['genres']:
        _hijo(generos, 'genre', genero)

    _hijo(nodo, 'price', '{:.2f}'.format(datos['price']))
    _hijo(nodo, 'stock', datos['stock'])
    _hijo(nodo, 'format', datos['format'])

    _imagenes_a_xml(nodo, datos['images'])

    conceptos = ET.SubElement(nodo, 'concepts')
    for concepto in datos['concepts']:
        atributos = {'term': concepto['term']}
        if 'chapter' in concepto:
            atributos['chapter'] = concepto['chapter']
        if 'page' in concepto:
            atributos['page'] = str(concepto['page'])
        nodo_con = ET.SubElement(conceptos, 'concept', atributos)
        _hijo(nodo_con, 'description', concepto['description'])

    return nodo


def catalogo_a_xml(datos):
    raiz = ET.Element('library')
    contenedor = ET.SubElement(raiz, 'books', {'count': str(datos['count'])})
    for libro in datos['books']:
        libro_a_xml(contenedor, libro)
    return raiz


def glosario_a_xml(datos):
    # Raiz propia (<glossary>) y no <concepts>: ese nombre ya lo usa el bloque
    # de conceptos dentro de cada libro, y library.css estiliza por nombre de
    # elemento. Reutilizarlo le pondria a este documento el rotulo "Conceptos
    # definidos en este libro", que aqui seria falso. <concept> si se reutiliza:
    # significa lo mismo y hereda su estilo.
    raiz = ET.Element('glossary', {'count': str(datos['count'])})
    for entrada in datos['concepts']:
        nodo = ET.SubElement(raiz, 'concept', {'term': entrada['term']})
        contenedor = ET.SubElement(nodo, 'books',
                                   {'count': str(entrada['count'])})
        for libro in entrada['books']:
            nodo_libro = ET.SubElement(contenedor, 'book',
                                       {'isbn': libro['isbn']})
            _hijo(nodo_libro, 'title', libro['title'])
            _autores_a_xml(nodo_libro, libro['authors'])
            _hijo(nodo_libro, 'year', libro['year'])
            atributos = {}
            if 'chapter' in libro:
                atributos['chapter'] = libro['chapter']
            if 'page' in libro:
                atributos['page'] = str(libro['page'])
            _hijo(nodo_libro, 'description', libro['description'], atributos)
    return raiz


def resumen_a_xml(datos):
    # Mismos nombres de elemento que el catalogo, con menos hijos: library.css
    # lo dibuja sin una sola regla nueva y el cliente no aprende otro vocabulario.
    raiz = ET.Element('library')
    contenedor = ET.SubElement(raiz, 'books', {'count': str(datos['count'])})
    for libro in datos['books']:
        nodo = ET.SubElement(contenedor, 'book', {'isbn': libro['isbn']})
        _hijo(nodo, 'title', libro['title'])
        _imagenes_a_xml(nodo, libro['images'])
    return raiz


def error_a_xml(datos):
    raiz = ET.Element('error', {'code': str(datos['code'])})
    ET.SubElement(raiz, 'message').text = datos['message']
    for detalle in datos.get('details', []):
        ET.SubElement(raiz, 'detail').text = detalle
    return raiz


def resultado_a_xml(datos):
    raiz = ET.Element('result', {'status': datos['status']})
    ET.SubElement(raiz, 'message').text = datos['message']
    libro = datos.get('book')
    if libro:
        ET.SubElement(raiz, 'book', {'isbn': libro['isbn']}).text = libro['title']
    return raiz


def salud_a_xml(datos):
    raiz = ET.Element('health', {'status': datos['status']})
    ET.SubElement(raiz, 'database').text = datos['database']
    if 'books' in datos:
        ET.SubElement(raiz, 'books').text = str(datos['books'])
    return raiz


def servicio_a_xml(datos):
    raiz = ET.Element('service', {'name': datos['name'],
                                  'version': datos['version']})
    for punto in datos['endpoints']:
        ET.SubElement(raiz, 'endpoint',
                      {'path': punto['path']}).text = punto['description']
    return raiz


RENDERIZADORES_XML = {
    'library': catalogo_a_xml,
    'glossary': glosario_a_xml,
    'summary': resumen_a_xml,
    'error':   error_a_xml,
    'result':  resultado_a_xml,
    'health':  salud_a_xml,
    'service': servicio_a_xml,
}


# --- Atajos que usan las vistas ----------------------------------------------
def responder_catalogo(libros, estado=200):
    datos = {'count': len(libros),
             'books': [libro_a_dict(libro) for libro in libros]}
    return responder('library', datos, estado)


def responder_glosario(conceptos, estado=200):
    return responder('glossary', glosario_a_dict(conceptos), estado)


def responder_resumen(libros, estado=200):
    return responder('summary', resumen_a_dict(libros), estado)


def error_respuesta(codigo, mensaje, detalles=None):
    """Error legible. Nunca expone SQL, nombres de tabla ni trazas."""
    datos = {'code': codigo, 'message': mensaje}
    if detalles:
        datos['details'] = list(detalles)
    return responder('error', datos, codigo)


# -----------------------------------------------------------------------------
# Lectura. Un SELECT para los libros y cuatro para las relaciones N:M, en vez
# de un JOIN unico: unir autores y generos a la vez multiplica las filas
# (producto cartesiano de dos dependencias multivaluadas independientes), que
# es justo lo que evita la 4FN del esquema.
# -----------------------------------------------------------------------------
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

# Pivote inverso: del concepto a los libros que lo definen. La definicion sale
# de libros_conceptos, no de conceptos, porque ahi es donde vive: el mismo
# termino se define distinto en cada libro (4FN del esquema).
SQL_GLOSARIO = """
    SELECT co.id AS concepto_id, co.termino,
           l.id  AS libro_id, l.isbn, l.titulo, l.anio_publicacion,
           lc.definicion, lc.capitulo, lc.pagina
      FROM conceptos co
      JOIN libros_conceptos lc ON lc.concepto_id = co.id
      JOIN libros l            ON l.id = lc.libro_id
"""

# Lectura minima: lo que identifica al libro y nada mas. Va aparte de SQL_LIBROS
# a proposito, sin el JOIN a formatos, que aqui no se usa.
SQL_RESUMEN = """
    SELECT l.id, l.isbn, l.titulo
      FROM libros l
     ORDER BY l.titulo, l.id
"""

# Columnas por las que se puede ordenar. Es una lista blanca: el valor que
# manda el cliente nunca se interpola en el SQL, solo elige una entrada de aqui.
ORDENES = {
    'titulo': 'l.titulo',
    'precio': 'l.precio',
    'anio':   'l.anio_publicacion',
    'stock':  'l.stock',
    'isbn':   'l.isbn',
}


def leer_libros(cur, condicion='', parametros=(), orden='l.titulo',
                direccion='ASC', limite=None, desplazamiento=0):
    sql = SQL_LIBROS
    if condicion:
        sql += ' WHERE ' + condicion
    sql += ' ORDER BY {} {}, l.id'.format(orden, direccion)
    valores = list(parametros)
    if limite is not None:
        sql += ' LIMIT %s OFFSET %s'
        valores += [limite, desplazamiento]

    cur.execute(sql, valores)
    libros = [dict(fila) for fila in cur.fetchall()]
    if not libros:
        return []

    indice = {libro['id']: libro for libro in libros}
    for libro in libros:
        libro['autores'] = []
        libro['generos'] = []
        libro['imagenes'] = []
        libro['conceptos'] = []

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


def leer_glosario(cur, termino=None):
    """Todos los conceptos del catalogo con los libros donde estan definidos.

    Cuales son "de Cloud Computing" no lo decide el codigo: no hay columna que
    lo diga y una lista fija de terminos aqui dentro seria un dato disfrazado de
    codigo, que mentiria en cuanto se sembrara un termino nuevo. Lo decide el
    catalogo, y el filtro opcional `termino` deja acotar la consulta.
    """
    sql = SQL_GLOSARIO
    parametros = []
    if termino:
        sql += ' WHERE co.termino ILIKE %s'
        parametros.append('%{}%'.format(termino))
    sql += ' ORDER BY co.termino, l.titulo, l.id'

    cur.execute(sql, parametros)
    filas = [dict(fila) for fila in cur.fetchall()]
    if not filas:
        return []

    conceptos = {}
    orden = []
    libros = {}
    for fila in filas:
        if fila['concepto_id'] not in conceptos:
            conceptos[fila['concepto_id']] = {'termino': fila['termino'],
                                              'libros': []}
            orden.append(fila['concepto_id'])
        libro = {
            'isbn': fila['isbn'],
            'titulo': fila['titulo'],
            'anio_publicacion': fila['anio_publicacion'],
            'definicion': fila['definicion'],
            'capitulo': fila['capitulo'],
            'pagina': fila['pagina'],
            'autores': [],
        }
        conceptos[fila['concepto_id']]['libros'].append(libro)
        libros.setdefault(fila['libro_id'], []).append(libro)

    # Una sola consulta de autores para todos los libros implicados, no una por
    # concepto: el mismo libro aparece bajo varios terminos.
    cur.execute(SQL_AUTORES, (list(libros.keys()),))
    for fila in cur.fetchall():
        for libro in libros[fila['libro_id']]:
            libro['autores'].append(dict(fila))

    return [conceptos[identificador] for identificador in orden]


def leer_resumen(cur, limite=None, desplazamiento=0):
    """Datos minimos de los libros mas sus imagenes.

    No reutiliza leer_libros porque ese lanza cuatro consultas de relaciones
    N:M —autores, generos, imagenes y conceptos— y aqui sobran tres. Reusarlo
    para despues descartar campos pagaria el costo completo y no ahorraria nada,
    que es justo lo contrario de lo que este endpoint existe para hacer.
    """
    sql = SQL_RESUMEN
    valores = []
    if limite is not None:
        sql += ' LIMIT %s OFFSET %s'
        valores += [limite, desplazamiento]

    cur.execute(sql, valores)
    libros = [dict(fila) for fila in cur.fetchall()]
    if not libros:
        return []

    indice = {libro['id']: libro for libro in libros}
    for libro in libros:
        libro['imagenes'] = []

    cur.execute(SQL_IMAGENES, (list(indice.keys()),))
    for fila in cur.fetchall():
        indice[fila['libro_id']]['imagenes'].append(dict(fila))

    return libros


# -----------------------------------------------------------------------------
# Validacion del lado del servidor. Refleja los CHECK de db/01_schema.sql: la
# base es la ultima defensa, no la primera, y un 400 explicado vale mas que un
# error de restriccion.
# -----------------------------------------------------------------------------
RE_ISBN = re.compile(r'^[0-9-]{10,17}[0-9X]$')


def _a_entero(valor, nombre, errores, minimo=None, maximo=None):
    try:
        numero = int(str(valor).strip())
    except (TypeError, ValueError):
        errores.append('{} debe ser un numero entero.'.format(nombre))
        return None
    if minimo is not None and numero < minimo:
        errores.append('{} no puede ser menor que {}.'.format(nombre, minimo))
        return None
    if maximo is not None and numero > maximo:
        errores.append('{} no puede ser mayor que {}.'.format(nombre, maximo))
        return None
    return numero


def validar_libro(datos, parcial=False):
    """Devuelve (campos_limpios, errores). Con parcial=True solo valida lo que
    venga en la peticion, que es lo que necesita un UPDATE."""
    limpio, errores = {}, []

    def presente(campo):
        return campo in datos and datos[campo] not in (None, '')

    if presente('isbn') or not parcial:
        isbn = str(datos.get('isbn', '')).strip()
        if not RE_ISBN.match(isbn):
            errores.append('El ISBN debe tener de 10 a 17 digitos o guiones y '
                           'terminar en digito o en X.')
        elif len(isbn) > 17:
            errores.append('El ISBN no puede exceder 17 caracteres.')
        else:
            limpio['isbn'] = isbn

    if presente('titulo') or not parcial:
        titulo = str(datos.get('titulo', '')).strip()
        if not titulo:
            errores.append('El titulo no puede ir vacio.')
        elif len(titulo) > 200:
            errores.append('El titulo no puede exceder 200 caracteres.')
        else:
            limpio['titulo'] = titulo

    if presente('anio_publicacion'):
        anio = _a_entero(datos['anio_publicacion'], 'El anio de publicacion',
                         errores, 1450, 2100)
        if anio is not None:
            limpio['anio_publicacion'] = anio
    elif 'anio_publicacion' in datos:
        limpio['anio_publicacion'] = None

    if presente('sinopsis'):
        limpio['sinopsis'] = str(datos['sinopsis']).strip()
    elif 'sinopsis' in datos:
        limpio['sinopsis'] = None

    if presente('precio') or not parcial:
        try:
            precio = Decimal(str(datos.get('precio', '0')).strip())
            if precio < 0:
                errores.append('El precio no puede ser negativo.')
            elif precio >= Decimal('100000000'):
                errores.append('El precio excede el maximo permitido.')
            else:
                limpio['precio'] = precio
        except (InvalidOperation, TypeError):
            errores.append('El precio debe ser un numero.')

    if presente('stock') or not parcial:
        stock = _a_entero(datos.get('stock', 0), 'El stock', errores, 0)
        if stock is not None:
            limpio['stock'] = stock

    if presente('categoria_id') or not parcial:
        categoria = _a_entero(datos.get('categoria_id'), 'La categoria',
                              errores, 1)
        if categoria is not None:
            limpio['categoria_id'] = categoria

    if presente('formato_id') or not parcial:
        formato = _a_entero(datos.get('formato_id'), 'El formato', errores, 1)
        if formato is not None:
            limpio['formato_id'] = formato

    return limpio, errores


def _lista_de_ids(datos, campo, errores):
    """autores y generos llegan como lista (JSON) o repetidos (formulario)."""
    if campo not in datos and campo + '[]' not in datos:
        return None
    crudo = datos.get(campo, datos.get(campo + '[]'))
    if isinstance(crudo, str):
        crudo = [parte for parte in re.split(r'[,\s]+', crudo) if parte]
    if not isinstance(crudo, (list, tuple)):
        crudo = [crudo]
    ids = []
    for elemento in crudo:
        numero = _a_entero(elemento, 'El identificador en "{}"'.format(campo),
                           errores, 1)
        if numero is not None and numero not in ids:
            ids.append(numero)
    return ids


CAMPOS_LISTA = {'autores', 'generos', 'autores[]', 'generos[]'}


def datos_entrantes():
    """Acepta JSON o formulario. No hay express.json() en el monolito, pero un
    cliente externo suele mandar JSON: aqui se admiten los dos."""
    if request.is_json:
        cuerpo = request.get_json(silent=True)
        return cuerpo if isinstance(cuerpo, dict) else {}
    datos = {}
    for clave in request.form:
        valores = request.form.getlist(clave)
        datos[clave] = valores if clave in CAMPOS_LISTA else valores[0]
    for clave in request.args:
        # 'format' elige la serializacion de la respuesta y ademas choca de
        # nombre con el formato editorial del libro: no es un dato del alta.
        if clave == 'format':
            continue
        datos.setdefault(clave, request.args.get(clave))
    return datos


def escritura_autorizada():
    if not API_TOKEN:
        return True
    return hmac.compare_digest(request.headers.get('X-API-Key', ''), API_TOKEN)


def sincronizar_relacion(cur, tabla, columna, libro_id, ids, con_orden=False):
    """Reemplaza los vinculos N:M de un libro. Los nombres de tabla y columna
    son constantes del codigo, jamas entradas del usuario."""
    cur.execute('DELETE FROM {} WHERE libro_id = %s'.format(tabla), (libro_id,))
    for posicion, referencia in enumerate(ids, start=1):
        if con_orden:
            cur.execute(
                'INSERT INTO {} (libro_id, {}, orden) VALUES (%s, %s, %s)'
                .format(tabla, columna), (libro_id, referencia, posicion))
        else:
            cur.execute(
                'INSERT INTO {} (libro_id, {}) VALUES (%s, %s)'
                .format(tabla, columna), (libro_id, referencia))


def buscar_por_isbn(cur, isbn):
    libros = leer_libros(cur, 'l.isbn = %s', (isbn,))
    return libros[0] if libros else None


# =============================================================================
# Endpoints
#
# Cada vista se registra dos veces: la ruta del enunciado (/books...) y la
# historica (/api/books...), que se conserva porque ya hay clientes y
# documentacion apuntando a ella. Flask admite varios @app.route sobre la misma
# funcion, asi que es un alias de verdad y no una copia que pueda divergir.
#
# Werkzeug ordena las reglas por especificidad, de modo que /books/search y
# /books/insert ganan sobre /books/<isbn> sin depender del orden de este
# archivo. La consecuencia es que un ISBN llamado literalmente "search" seria
# inalcanzable por esa ruta; no existe tal ISBN, ni puede existir (el CHECK del
# esquema exige digitos y guiones).
# =============================================================================

@app.route('/books', methods=['GET'])
@app.route('/api/books', methods=['GET'])
def listar_libros():
    limite = request.args.get('limite', type=int)
    desplazamiento = request.args.get('desplazamiento', default=0, type=int)
    orden = ORDENES.get((request.args.get('orden') or 'titulo').lower(), 'l.titulo')
    direccion = 'DESC' if (request.args.get('dir') or '').lower() == 'desc' else 'ASC'
    if limite is not None:
        limite = max(1, min(limite, 500))

    with cursor_bd() as cur:
        libros = leer_libros(cur, orden=orden, direccion=direccion,
                             limite=limite, desplazamiento=max(0, desplazamiento))
    return responder_catalogo(libros)


# Filtros de busqueda. La clave elige un fragmento de SQL escrito aqui; el
# valor del usuario SIEMPRE viaja como parametro (%s), nunca concatenado.
FILTROS = {
    'isbn':       ('l.isbn ILIKE %s', lambda v: '%{}%'.format(v)),
    'titulo':     ('l.titulo ILIKE %s', lambda v: '%{}%'.format(v)),
    'formato':    ('f.nombre ILIKE %s', lambda v: '%{}%'.format(v)),
    'anio':       ('l.anio_publicacion = %s', int),
    'anio_min':   ('l.anio_publicacion >= %s', int),
    'anio_max':   ('l.anio_publicacion <= %s', int),
    'precio_min': ('l.precio >= %s', Decimal),
    'precio_max': ('l.precio <= %s', Decimal),
    'stock_min':  ('l.stock >= %s', int),
    'autor': ('EXISTS (SELECT 1 FROM libros_autores la '
              'JOIN autores a ON a.id = la.autor_id '
              'WHERE la.libro_id = l.id AND a.nombre ILIKE %s)',
              lambda v: '%{}%'.format(v)),
    'genero': ('EXISTS (SELECT 1 FROM libros_generos lg '
               'JOIN generos g ON g.id = lg.genero_id '
               'WHERE lg.libro_id = l.id AND g.nombre ILIKE %s)',
               lambda v: '%{}%'.format(v)),
    'concepto': ('EXISTS (SELECT 1 FROM libros_conceptos lc '
                 'JOIN conceptos co ON co.id = lc.concepto_id '
                 'WHERE lc.libro_id = l.id AND co.termino ILIKE %s)',
                 lambda v: '%{}%'.format(v)),
    'disponible': ('(l.stock > 0) = %s',
                   lambda v: str(v).lower() in ('1', 'true', 'si', 'yes')),
}


# '/books/summary' se declara antes que '/books/<isbn>' por legibilidad; el
# orden no decide nada, Werkzeug prefiere la regla estatica sobre la variable.
@app.route('/books/summary', methods=['GET'])
@app.route('/api/books/summary', methods=['GET'])
def resumen_libros():
    limite = request.args.get('limite', type=int)
    desplazamiento = request.args.get('desplazamiento', default=0, type=int)
    if limite is not None:
        limite = max(1, min(limite, 500))

    with cursor_bd() as cur:
        libros = leer_resumen(cur, limite, max(0, desplazamiento))
    return responder_resumen(libros)


@app.route('/concepts', methods=['GET'])
@app.route('/api/concepts', methods=['GET'])
def listar_conceptos():
    termino = (request.args.get('termino') or '').strip()
    with cursor_bd() as cur:
        conceptos = leer_glosario(cur, termino or None)
    return responder_glosario(conceptos)


@app.route('/books/search', methods=['GET'])
@app.route('/api/books/search', methods=['GET'])
def buscar_libros():
    condiciones, parametros, errores = [], [], []

    for clave, (fragmento, convertir) in FILTROS.items():
        crudo = request.args.get(clave)
        if crudo in (None, ''):
            continue
        try:
            parametros.append(convertir(crudo))
        except (ValueError, TypeError, InvalidOperation):
            errores.append('El filtro "{}" no tiene un valor valido.'.format(clave))
            continue
        condiciones.append(fragmento)

    # Busqueda libre: titulo o ISBN o nombre de autor.
    libre = request.args.get('q')
    if libre:
        condiciones.append(
            '(l.titulo ILIKE %s OR l.isbn ILIKE %s OR EXISTS ('
            'SELECT 1 FROM libros_autores la JOIN autores a ON a.id = la.autor_id '
            'WHERE la.libro_id = l.id AND a.nombre ILIKE %s))')
        parametros.extend(['%{}%'.format(libre)] * 3)

    if errores:
        return error_respuesta(400, 'Los filtros de busqueda no son validos.', errores)
    if not condiciones:
        return error_respuesta(400, 'Indica al menos un filtro de busqueda.',
                         ['Filtros disponibles: q, ' + ', '.join(sorted(FILTROS))])

    orden = ORDENES.get((request.args.get('orden') or 'titulo').lower(), 'l.titulo')
    direccion = 'DESC' if (request.args.get('dir') or '').lower() == 'desc' else 'ASC'

    with cursor_bd() as cur:
        libros = leer_libros(cur, ' AND '.join(condiciones), parametros,
                             orden=orden, direccion=direccion)
    return responder_catalogo(libros)


@app.route('/books/<isbn>', methods=['GET'])
@app.route('/api/book/<isbn>', methods=['GET'])
def obtener_libro(isbn):
    with cursor_bd() as cur:
        libro = buscar_por_isbn(cur, isbn.strip())
    if libro is None:
        return error_respuesta(404, 'No existe un libro con ese ISBN.')
    return responder_catalogo([libro])


@app.route('/books/author/<int:author_id>', methods=['GET'])
@app.route('/api/book/author/<int:author_id>', methods=['GET'])
def libros_por_autor(author_id):
    with cursor_bd() as cur:
        cur.execute('SELECT nombre FROM autores WHERE id = %s', (author_id,))
        autor = cur.fetchone()
        if autor is None:
            return error_respuesta(404, 'No existe un autor con ese identificador.')
        libros = leer_libros(
            cur,
            'EXISTS (SELECT 1 FROM libros_autores la '
            'WHERE la.libro_id = l.id AND la.autor_id = %s)',
            (author_id,))
    return responder_catalogo(libros)


@app.route('/books/insert', methods=['POST'])
@app.route('/api/book/insert', methods=['POST'])
def insertar_libro():
    if not escritura_autorizada():
        return error_respuesta(401, 'Esta operacion requiere una clave de escritura.')

    datos = datos_entrantes()
    limpio, errores = validar_libro(datos, parcial=False)
    autores = _lista_de_ids(datos, 'autores', errores)
    generos = _lista_de_ids(datos, 'generos', errores)
    if errores:
        return error_respuesta(400, 'Los datos del libro no son validos.', errores)

    columnas = ['isbn', 'titulo', 'anio_publicacion', 'sinopsis', 'precio',
                'stock', 'categoria_id', 'formato_id']
    presentes = [c for c in columnas if c in limpio]
    marcadores = ', '.join(['%s'] * len(presentes))
    valores = [limpio[c] for c in presentes]

    try:
        with cursor_bd(escribe=True) as cur:
            cur.execute(
                'INSERT INTO libros ({}) VALUES ({}) RETURNING id'
                .format(', '.join(presentes), marcadores), valores)
            libro_id = cur.fetchone()['id']
            if autores:
                sincronizar_relacion(cur, 'libros_autores', 'autor_id',
                                     libro_id, autores, con_orden=True)
            if generos:
                sincronizar_relacion(cur, 'libros_generos', 'genero_id',
                                     libro_id, generos)
            libro = leer_libros(cur, 'l.id = %s', (libro_id,))[0]
    except pgerrors.UniqueViolation:
        return error_respuesta(409, 'Ya existe un libro registrado con ese ISBN.')
    except pgerrors.ForeignKeyViolation:
        return error_respuesta(400, 'La categoria, el formato, el autor o el genero '
                              'indicado no existe.')
    except pgerrors.CheckViolation:
        return error_respuesta(400, 'Los datos no cumplen una regla del catalogo.')

    return responder_catalogo([libro], estado=201)


@app.route('/books/update', methods=['PUT', 'POST'])
@app.route('/books/update/<isbn>', methods=['PUT', 'POST'])
@app.route('/api/book/update', methods=['PUT', 'POST'])
@app.route('/api/book/update/<isbn>', methods=['PUT', 'POST'])
def actualizar_libro(isbn=None):
    if not escritura_autorizada():
        return error_respuesta(401, 'Esta operacion requiere una clave de escritura.')

    datos = datos_entrantes()
    objetivo = (isbn or datos.get('isbn') or '').strip()
    if not objetivo:
        return error_respuesta(400, 'Indica el ISBN del libro que se va a actualizar.')

    # El isbn de la URL identifica; isbn_nuevo, si viene, lo reemplaza.
    if isbn and 'isbn' in datos:
        datos.pop('isbn')
    if 'isbn_nuevo' in datos:
        datos['isbn'] = datos.pop('isbn_nuevo')
    elif isbn is None:
        datos.pop('isbn', None)

    limpio, errores = validar_libro(datos, parcial=True)
    autores = _lista_de_ids(datos, 'autores', errores)
    generos = _lista_de_ids(datos, 'generos', errores)
    if errores:
        return error_respuesta(400, 'Los datos del libro no son validos.', errores)
    if not limpio and autores is None and generos is None:
        return error_respuesta(400, 'No se envio ningun campo que actualizar.')

    try:
        with cursor_bd(escribe=True) as cur:
            cur.execute('SELECT id FROM libros WHERE isbn = %s', (objetivo,))
            fila = cur.fetchone()
            if fila is None:
                return error_respuesta(404, 'No existe un libro con ese ISBN.')
            libro_id = fila['id']

            if limpio:
                # actualizado_en lo pone el disparador trg_libros_actualizado.
                asignaciones = ', '.join('{} = %s'.format(c) for c in limpio)
                cur.execute('UPDATE libros SET {} WHERE id = %s'.format(asignaciones),
                            list(limpio.values()) + [libro_id])
            if autores is not None:
                sincronizar_relacion(cur, 'libros_autores', 'autor_id',
                                     libro_id, autores, con_orden=True)
            if generos is not None:
                sincronizar_relacion(cur, 'libros_generos', 'genero_id',
                                     libro_id, generos)
            libro = leer_libros(cur, 'l.id = %s', (libro_id,))[0]
    except pgerrors.UniqueViolation:
        return error_respuesta(409, 'Ya existe otro libro registrado con ese ISBN.')
    except pgerrors.ForeignKeyViolation:
        return error_respuesta(400, 'La categoria, el formato, el autor o el genero '
                              'indicado no existe.')
    except pgerrors.CheckViolation:
        return error_respuesta(400, 'Los datos no cumplen una regla del catalogo.')

    return responder_catalogo([libro])


@app.route('/books/delete', methods=['DELETE', 'POST'])
@app.route('/books/delete/<isbn>', methods=['DELETE', 'POST'])
@app.route('/api/book/delete', methods=['DELETE', 'POST'])
@app.route('/api/book/delete/<isbn>', methods=['DELETE', 'POST'])
def borrar_libro(isbn=None):
    if not escritura_autorizada():
        return error_respuesta(401, 'Esta operacion requiere una clave de escritura.')

    datos = datos_entrantes()
    objetivo = (isbn or datos.get('isbn') or request.args.get('isbn') or '').strip()
    if not objetivo:
        return error_respuesta(400, 'Indica el ISBN del libro que se va a borrar.')

    try:
        with cursor_bd(escribe=True) as cur:
            # Las tablas puente y las imagenes caen por ON DELETE CASCADE.
            cur.execute('DELETE FROM libros WHERE isbn = %s RETURNING isbn, titulo',
                        (objetivo,))
            fila = cur.fetchone()
    except pgerrors.ForeignKeyViolation:
        return error_respuesta(409, 'El libro no se puede borrar porque otro registro '
                              'todavia depende de el.')

    if fila is None:
        return error_respuesta(404, 'No existe un libro con ese ISBN.')

    return responder('result', {
        'status': 'ok',
        'message': 'Libro eliminado del catalogo.',
        'book': {'isbn': fila['isbn'], 'title': fila['titulo']},
    })


@app.route('/health', methods=['GET'])
@app.route('/api/health', methods=['GET'])
def salud():
    try:
        with cursor_bd() as cur:
            cur.execute('SELECT count(*)::int AS total FROM libros')
            total = cur.fetchone()['total']
    except psycopg2.Error:
        log.exception('Fallo la verificacion de salud')
        return responder('health',
                         {'status': 'error', 'database': 'sin conexion'}, 503)

    return responder('health',
                     {'status': 'ok', 'database': 'conectada', 'books': total})


@app.route('/library.css', methods=['GET'])
def hoja_de_estilos():
    """Sirve la hoja con la que el navegador dibuja el XML del catalogo."""
    return send_from_directory(RAIZ, 'library.css', mimetype='text/css')


# -----------------------------------------------------------------------------
# Manejo de errores. El cliente recibe XML explicado; la traza va al log.
# -----------------------------------------------------------------------------
@app.errorhandler(404)
def _no_encontrado(_error):
    return error_respuesta(404, 'El recurso solicitado no existe.',
                     ['Consulta la documentacion en /docs'])


@app.errorhandler(405)
def _metodo_no_permitido(_error):
    return error_respuesta(405, 'Ese metodo HTTP no esta permitido en esta ruta.')


@app.errorhandler(psycopg2.OperationalError)
def _sin_base(error):
    log.error('No hay conexion con la base de datos: %s', error)
    return error_respuesta(503, 'El servicio no puede conectarse a su base de datos.')


@app.errorhandler(Exception)
def _fallo_inesperado(error):
    # Los errores HTTP que no tienen manejador propio (400, 415...) conservan su
    # codigo; el resto se convierte en un 500 generico. Nunca se devuelve el
    # mensaje original: puede contener SQL o nombres de tabla. La traza completa
    # queda del lado del servidor.
    if isinstance(error, HTTPException):
        return error_respuesta(error.code or 500, 'La solicitud no se pudo atender.')
    log.exception('Fallo no controlado: %s', error)
    return error_respuesta(500, 'Ocurrio un error al procesar la solicitud.')


# =============================================================================
# Documentacion Swagger (OpenAPI 3). La especificacion se sirve en
# /apispec.json y la interfaz en /docs.
# =============================================================================
RESPUESTA_CATALOGO = {
    'description': ('Catalogo con la estructura de library.xml. XML por '
                    'defecto; JSON con ?format=json.'),
    'content': {'application/xml': {'schema': {'type': 'string'}},
                'application/json': {'schema': {'type': 'object'}}},
}
RESPUESTA_GLOSARIO = {
    'description': ('Conceptos con los libros que los definen. XML por '
                    'defecto; JSON con ?format=json.'),
    'content': {'application/xml': {'schema': {'type': 'string'}},
                'application/json': {'schema': {'type': 'object'}}},
}
RESPUESTA_ERROR = {
    'description': ('Error explicado. XML: <error code="..."><message>... '
                    'JSON: {"code": ..., "message": ..., "details": [...]}.'),
    'content': {'application/xml': {'schema': {'type': 'string'}},
                'application/json': {'schema': {'type': 'object'}}},
}

# Ruta del enunciado por cada ruta historica. Una sola tabla para el indice del
# servicio y para la especificacion: si se agrega un endpoint, se declara aqui.
ALIAS = {
    '/api/books':                    '/books',
    '/api/books/search':             '/books/search',
    '/api/books/summary':            '/books/summary',
    '/api/concepts':                 '/concepts',
    '/api/book/{isbn}':              '/books/{isbn}',
    '/api/book/author/{author_id}':  '/books/author/{author_id}',
    '/api/book/insert':              '/books/insert',
    '/api/book/update':              '/books/update',
    '/api/book/delete':              '/books/delete',
    '/api/health':                   '/health',
}
ALIAS_INVERSO = {nuevo: viejo for viejo, nuevo in ALIAS.items()}


def _param(nombre, descripcion, tipo='string', donde='query', requerido=False):
    return {'name': nombre, 'in': donde, 'required': requerido,
            'description': descripcion, 'schema': {'type': tipo}}


ESQUEMA_LIBRO = {
    'type': 'object',
    'required': ['isbn', 'titulo', 'categoria_id', 'formato_id'],
    'properties': {
        'isbn': {'type': 'string', 'maxLength': 17,
                 'description': '10 a 17 digitos o guiones, terminando en digito o X.'},
        'titulo': {'type': 'string', 'maxLength': 200},
        'anio_publicacion': {'type': 'integer', 'minimum': 1450, 'maximum': 2100},
        'sinopsis': {'type': 'string'},
        'precio': {'type': 'number', 'minimum': 0},
        'stock': {'type': 'integer', 'minimum': 0},
        'categoria_id': {'type': 'integer', 'minimum': 1},
        'formato_id': {'type': 'integer', 'minimum': 1},
        'autores': {'type': 'array', 'items': {'type': 'integer'},
                    'description': 'Ids de autores, en orden de portada.'},
        'generos': {'type': 'array', 'items': {'type': 'integer'},
                    'description': 'Ids de generos.'},
    },
}

ESQUEMA_LIBRO_PARCIAL = {
    'type': 'object',
    'required': ['isbn'],
    'properties': dict(ESQUEMA_LIBRO['properties'],
                       isbn={'type': 'string',
                             'description': 'ISBN del libro que se actualiza.'},
                       isbn_nuevo={'type': 'string',
                                   'description': 'Nuevo ISBN, si se quiere cambiar.'}),
}


def _cuerpo(esquema):
    return {'required': True,
            'content': {'application/json': {'schema': esquema},
                        'application/x-www-form-urlencoded': {'schema': esquema}}}


ESPECIFICACION = {
    'openapi': '3.0.3',
    'info': {
        'title': 'Catalogo de la Libreria Online',
        'version': '1.2.0',
        'description': (
            'Microservicio Flask que expone el catalogo de libros en XML.\n\n'
            'Lee de la misma base PostgreSQL que el monolito (db/01_schema.sql) '
            'y devuelve la misma estructura que services/soap/library.xml: cada '
            '`<book>` lleva el ISBN como atributo e incluye titulo, autores, '
            'anio, generos, precio, stock, formato, imagenes y los conceptos '
            'definidos en ese libro con su descripcion.\n\n'
            'Todos los endpoints responden en XML o en JSON indistintamente, '
            'segun el parametro `format`: `?format=json` devuelve '
            '`application/json` y `?format=xml` —o la ausencia del parametro— '
            'devuelve `application/xml`. Cualquier otro valor es un 400.\n\n'
            'Cada operacion se publica en la ruta del enunciado (`/books...`) y '
            'en la historica con prefijo `/api`, que se conserva y hace '
            'exactamente lo mismo.\n\n'
            'Las escrituras aceptan JSON o formulario en la entrada, con '
            'independencia del formato que pidan para la respuesta.'),
    },
    'servers': [{'url': '/', 'description': 'Este servidor'}],
    'tags': [
        {'name': 'Lectura', 'description': 'Consulta del catalogo'},
        {'name': 'Escritura', 'description': 'Alta, cambio y baja de libros'},
        {'name': 'Servicio', 'description': 'Estado del microservicio'},
    ],
    'paths': {
        '/api/books': {'get': {
            'tags': ['Lectura'],
            'summary': 'Lista todos los libros del catalogo',
            'parameters': [
                _param('orden', 'titulo | precio | anio | stock | isbn'),
                _param('dir', 'asc o desc'),
                _param('limite', 'Maximo de libros a devolver (1-500)', 'integer'),
                _param('desplazamiento', 'Libros a saltar', 'integer'),
            ],
            'responses': {'200': RESPUESTA_CATALOGO, '503': RESPUESTA_ERROR},
        }},
        '/api/books/search': {'get': {
            'tags': ['Lectura'],
            'summary': 'Busca libros por atributos',
            'description': 'Los filtros se combinan con AND. Los de texto son '
                           'parciales y no distinguen mayusculas.',
            'parameters': [
                _param('q', 'Texto libre: titulo, ISBN o autor'),
                _param('titulo', 'Fragmento del titulo'),
                _param('autor', 'Fragmento del nombre del autor'),
                _param('genero', 'Fragmento del nombre del genero'),
                _param('formato', 'Fragmento del nombre del formato'),
                _param('concepto', 'Termino definido en el libro'),
                _param('isbn', 'Fragmento del ISBN'),
                _param('anio', 'Anio exacto de publicacion', 'integer'),
                _param('anio_min', 'Anio minimo', 'integer'),
                _param('anio_max', 'Anio maximo', 'integer'),
                _param('precio_min', 'Precio minimo', 'number'),
                _param('precio_max', 'Precio maximo', 'number'),
                _param('stock_min', 'Existencias minimas', 'integer'),
                _param('disponible', 'true para solo libros con stock', 'boolean'),
                _param('orden', 'titulo | precio | anio | stock | isbn'),
                _param('dir', 'asc o desc'),
            ],
            'responses': {'200': RESPUESTA_CATALOGO, '400': RESPUESTA_ERROR},
        }},
        '/api/books/summary': {'get': {
            'tags': ['Lectura'],
            'summary': 'Datos minimos de los libros con sus imagenes',
            'description': 'Solo ISBN, titulo e imagenes. Lectura propia, mas '
                           'barata que la del catalogo completo: no consulta '
                           'autores, generos ni conceptos.',
            'parameters': [
                _param('limite', 'Maximo de libros a devolver (1-500)', 'integer'),
                _param('desplazamiento', 'Libros a saltar', 'integer'),
            ],
            'responses': {'200': RESPUESTA_CATALOGO, '503': RESPUESTA_ERROR},
        }},
        '/api/concepts': {'get': {
            'tags': ['Lectura'],
            'summary': 'Conceptos del catalogo y los libros que los definen',
            'description': 'Pivote inverso de /books: de cada concepto —IaaS, '
                           'PaaS, SaaS, FaaS y los demas que haya en el '
                           'catalogo— devuelve los libros donde esta definido, '
                           'con su definicion, capitulo y pagina. La definicion '
                           'pertenece al par (libro, concepto): el mismo termino '
                           'se define distinto en cada libro.',
            'parameters': [
                _param('termino', 'Fragmento del termino; sin el, todos los '
                                  'conceptos del catalogo'),
            ],
            'responses': {'200': RESPUESTA_GLOSARIO, '503': RESPUESTA_ERROR},
        }},
        '/api/book/{isbn}': {'get': {
            'tags': ['Lectura'],
            'summary': 'Devuelve un libro por su ISBN',
            'parameters': [_param('isbn', 'ISBN del libro', donde='path',
                                  requerido=True)],
            'responses': {'200': RESPUESTA_CATALOGO, '404': RESPUESTA_ERROR},
        }},
        '/api/book/author/{author_id}': {'get': {
            'tags': ['Lectura'],
            'summary': 'Devuelve los libros de un autor',
            'parameters': [_param('author_id', 'Id del autor', 'integer',
                                  donde='path', requerido=True)],
            'responses': {'200': RESPUESTA_CATALOGO, '404': RESPUESTA_ERROR},
        }},
        '/api/book/insert': {'post': {
            'tags': ['Escritura'],
            'summary': 'Registra un libro nuevo',
            'requestBody': _cuerpo(ESQUEMA_LIBRO),
            'responses': {'201': RESPUESTA_CATALOGO, '400': RESPUESTA_ERROR,
                          '401': RESPUESTA_ERROR, '409': RESPUESTA_ERROR},
        }},
        '/api/book/update': {'put': {
            'tags': ['Escritura'],
            'summary': 'Modifica un libro existente',
            'description': 'Actualiza solo los campos enviados. Si se mandan '
                           '`autores` o `generos`, reemplazan por completo a los '
                           'anteriores. Tambien acepta POST y '
                           '/api/book/update/{isbn}.',
            'requestBody': _cuerpo(ESQUEMA_LIBRO_PARCIAL),
            'responses': {'200': RESPUESTA_CATALOGO, '400': RESPUESTA_ERROR,
                          '401': RESPUESTA_ERROR, '404': RESPUESTA_ERROR,
                          '409': RESPUESTA_ERROR},
        }},
        '/api/book/delete': {'delete': {
            'tags': ['Escritura'],
            'summary': 'Elimina un libro del catalogo',
            'description': 'Sus autores, generos, conceptos e imagenes se van '
                           'con el por ON DELETE CASCADE. Tambien acepta POST y '
                           '/api/book/delete/{isbn}.',
            'parameters': [_param('isbn', 'ISBN del libro a borrar')],
            'requestBody': {'required': False, 'content': {'application/json': {
                'schema': {'type': 'object',
                           'properties': {'isbn': {'type': 'string'}}}}}},
            'responses': {'200': RESPUESTA_CATALOGO, '400': RESPUESTA_ERROR,
                          '401': RESPUESTA_ERROR, '404': RESPUESTA_ERROR},
        }},
        '/api/health': {'get': {
            'tags': ['Servicio'],
            'summary': 'Estado del servicio y de su base de datos',
            'responses': {'200': RESPUESTA_CATALOGO, '503': RESPUESTA_ERROR},
        }},
    },
    'components': {
        'securitySchemes': {
            'ClaveEscritura': {
                'type': 'apiKey', 'in': 'header', 'name': 'X-API-Key',
                'description': 'Solo si el servicio arranco con API_TOKEN '
                               'definido en su .env.',
            },
        },
    },
}


def _publicar_rutas(rutas):
    """Declara cada operacion en sus dos rutas y le agrega el parametro format.

    La copia es profunda para que la nota de la ruta historica no se escriba
    tambien en la del enunciado; el comportamiento del servicio es uno solo.
    """
    publicadas = {}
    for historica, operaciones in rutas.items():
        del_enunciado = ALIAS[historica]
        for operacion in operaciones.values():
            operacion.setdefault('parameters', []).append(PARAM_FORMATO)
        publicadas[del_enunciado] = operaciones

        copia = copy.deepcopy(operaciones)
        nota = 'Ruta historica: hace exactamente lo mismo que {}.'.format(
            del_enunciado)
        for operacion in copia.values():
            descripcion = operacion.get('description')
            operacion['description'] = (descripcion + ' ' + nota
                                        if descripcion else nota)
        publicadas[historica] = copia
    return publicadas


PARAM_FORMATO = _param('format', 'json para JSON; xml o ausente para XML')
ESPECIFICACION['paths'] = _publicar_rutas(ESPECIFICACION['paths'])


@app.route('/apispec.json', methods=['GET'])
def especificacion():
    return jsonify(ESPECIFICACION)


PAGINA_DOCS = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>API del catalogo — Libreria Online</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body style="margin:0">
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: "__SPEC__",
      dom_id: "#swagger-ui",
      deepLinking: true,
      tryItOutEnabled: true
    });
  </script>
</body>
</html>"""


@app.route('/docs', methods=['GET'])
@app.route('/docs/', methods=['GET'])
def documentacion():
    pagina = PAGINA_DOCS.replace('__SPEC__', url_for('especificacion'))
    return Response(pagina, content_type='text/html; charset=utf-8')


@app.route('/', methods=['GET'])
def indice():
    puntos = [
        ('/docs', 'Documentacion Swagger'),
        ('/books', 'Todos los libros'),
        ('/books/search', 'Busqueda por atributos'),
        ('/books/summary', 'Datos minimos de los libros con sus imagenes'),
        ('/concepts', 'Conceptos del catalogo y los libros que los definen'),
        ('/books/{isbn}', 'Un libro'),
        ('/books/author/{author_id}', 'Libros de un autor'),
        ('/books/insert', 'Alta (POST)'),
        ('/books/update', 'Modificacion (PUT)'),
        ('/books/delete', 'Baja (DELETE)'),
        ('/health', 'Estado del servicio'),
    ]
    puntos += [(ALIAS_INVERSO[ruta], descripcion + ' (ruta historica)')
               for ruta, descripcion in puntos if ruta in ALIAS_INVERSO]
    return responder('service', {
        'name': 'catalogo-libreria',
        'version': '1.2.0',
        'endpoints': [{'path': ruta, 'description': descripcion}
                      for ruta, descripcion in puntos],
    })


if __name__ == '__main__':
    if not API_TOKEN and ORIGENES == ['*']:
        log.warning('Las escrituras estan abiertas a cualquier origen y sin '
                    'clave. Define API_TOKEN y CORS_ORIGENES en el .env antes '
                    'de exponer este servicio a internet.')
    if not BD['password']:
        log.warning('DB_PASSWORD viene vacia: revisa services/soap/.env')
    app.run(host=APP_HOST, port=APP_PORT, debug=False)
