# =============================================================================
# app.py — microservicio de catalogo de la Libreria Online.
#
#     cd services/soap
#     python3 -m venv .venv && . .venv/bin/activate
#     pip install -r requirements.txt
#     cp .env.example .env          # y completa las credenciales EN LA VM
#     python app.py                 # -> http://127.0.0.1:5000/docs
#
# Una sola aplicacion Flask, SIN Blueprints, como pide el enunciado. Lee de la
# misma base PostgreSQL que el monolito Node (ver db/01_schema.sql) y responde
# XML con la misma estructura que library.xml, de modo que library.css sirve
# para las dos: el catalogo se ve en el navegador sin HTML intermedio.
#
# Ninguna credencial vive en este archivo. Todas se leen del .env, que no se
# versiona (.gitignore). El repositorio es publico.
# =============================================================================

import hmac
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
    resources={r'/api/*': {'origins': ORIGENES}},
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
# Respuestas XML. La estructura es la de library.xml:
#   <library><books><book isbn="..."> title, authors, year, genres, price,
#                                     stock, format, images, concepts </book>
# -----------------------------------------------------------------------------
CABECERA = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<?xml-stylesheet type="text/css" href="{hoja}"?>\n')


def responder_xml(raiz, estado=200):
    if hasattr(ET, 'indent'):
        ET.indent(raiz, space='  ')
    cuerpo = CABECERA.format(hoja=HOJA_ESTILOS) + ET.tostring(raiz, encoding='unicode')
    return Response(cuerpo + '\n', status=estado,
                    content_type='application/xml; charset=utf-8')


def error_xml(codigo, mensaje, detalles=None):
    """Error legible. Nunca expone SQL, nombres de tabla ni trazas."""
    raiz = ET.Element('error', {'code': str(codigo)})
    ET.SubElement(raiz, 'message').text = mensaje
    for detalle in (detalles or []):
        ET.SubElement(raiz, 'detail').text = detalle
    return responder_xml(raiz, codigo)


def _hijo(padre, etiqueta, valor=None, atributos=None):
    elemento = ET.SubElement(padre, etiqueta, atributos or {})
    if valor is not None:
        elemento.text = str(valor)
    return elemento


def libro_a_xml(padre, libro):
    nodo = ET.SubElement(padre, 'book', {'isbn': libro['isbn']})
    _hijo(nodo, 'title', libro['titulo'])

    autores = ET.SubElement(nodo, 'authors')
    for autor in libro.get('autores', []):
        atributos = {'order': str(autor['orden'])}
        if autor.get('nacionalidad'):
            atributos['nationality'] = autor['nacionalidad']
        _hijo(autores, 'author', autor['nombre'], atributos)

    _hijo(nodo, 'year', libro.get('anio_publicacion'))

    generos = ET.SubElement(nodo, 'genres')
    for genero in libro.get('generos', []):
        _hijo(generos, 'genre', genero)

    _hijo(nodo, 'price', '{:.2f}'.format(libro['precio']))
    _hijo(nodo, 'stock', libro['stock'])
    _hijo(nodo, 'format', libro['formato'])

    imagenes = ET.SubElement(nodo, 'images')
    for imagen in libro.get('imagenes', []):
        nodo_img = ET.SubElement(imagenes, 'image', {
            'cover': 'true' if imagen['es_portada'] else 'false',
            'type': imagen['tipo_mime'],
        })
        # Solo el nombre de archivo: la ruta base de uploads/ es configuracion
        # de la aplicacion, no un dato publico.
        _hijo(nodo_img, 'file', imagen['nombre_archivo'])
        if imagen.get('texto_alternativo'):
            _hijo(nodo_img, 'alt', imagen['texto_alternativo'])

    conceptos = ET.SubElement(nodo, 'concepts')
    for concepto in libro.get('conceptos', []):
        atributos = {'term': concepto['termino']}
        if concepto.get('capitulo'):
            atributos['chapter'] = concepto['capitulo']
        if concepto.get('pagina') is not None:
            atributos['page'] = str(concepto['pagina'])
        nodo_con = ET.SubElement(conceptos, 'concept', atributos)
        # La definicion pertenece al par (libro, concepto): el mismo termino se
        # define distinto en cada libro. Por eso no vive en el catalogo.
        _hijo(nodo_con, 'description', concepto['definicion'])

    return nodo


def catalogo_a_xml(libros, estado=200):
    raiz = ET.Element('library')
    contenedor = ET.SubElement(raiz, 'books', {'count': str(len(libros))})
    for libro in libros:
        libro_a_xml(contenedor, libro)
    return responder_xml(raiz, estado)


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
# =============================================================================

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
    return catalogo_a_xml(libros)


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
        return error_xml(400, 'Los filtros de busqueda no son validos.', errores)
    if not condiciones:
        return error_xml(400, 'Indica al menos un filtro de busqueda.',
                         ['Filtros disponibles: q, ' + ', '.join(sorted(FILTROS))])

    orden = ORDENES.get((request.args.get('orden') or 'titulo').lower(), 'l.titulo')
    direccion = 'DESC' if (request.args.get('dir') or '').lower() == 'desc' else 'ASC'

    with cursor_bd() as cur:
        libros = leer_libros(cur, ' AND '.join(condiciones), parametros,
                             orden=orden, direccion=direccion)
    return catalogo_a_xml(libros)


@app.route('/api/book/<isbn>', methods=['GET'])
def obtener_libro(isbn):
    with cursor_bd() as cur:
        libro = buscar_por_isbn(cur, isbn.strip())
    if libro is None:
        return error_xml(404, 'No existe un libro con ese ISBN.')
    return catalogo_a_xml([libro])


@app.route('/api/book/author/<int:author_id>', methods=['GET'])
def libros_por_autor(author_id):
    with cursor_bd() as cur:
        cur.execute('SELECT nombre FROM autores WHERE id = %s', (author_id,))
        autor = cur.fetchone()
        if autor is None:
            return error_xml(404, 'No existe un autor con ese identificador.')
        libros = leer_libros(
            cur,
            'EXISTS (SELECT 1 FROM libros_autores la '
            'WHERE la.libro_id = l.id AND la.autor_id = %s)',
            (author_id,))
    return catalogo_a_xml(libros)


@app.route('/api/book/insert', methods=['POST'])
def insertar_libro():
    if not escritura_autorizada():
        return error_xml(401, 'Esta operacion requiere una clave de escritura.')

    datos = datos_entrantes()
    limpio, errores = validar_libro(datos, parcial=False)
    autores = _lista_de_ids(datos, 'autores', errores)
    generos = _lista_de_ids(datos, 'generos', errores)
    if errores:
        return error_xml(400, 'Los datos del libro no son validos.', errores)

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
        return error_xml(409, 'Ya existe un libro registrado con ese ISBN.')
    except pgerrors.ForeignKeyViolation:
        return error_xml(400, 'La categoria, el formato, el autor o el genero '
                              'indicado no existe.')
    except pgerrors.CheckViolation:
        return error_xml(400, 'Los datos no cumplen una regla del catalogo.')

    return catalogo_a_xml([libro], estado=201)


@app.route('/api/book/update', methods=['PUT', 'POST'])
@app.route('/api/book/update/<isbn>', methods=['PUT', 'POST'])
def actualizar_libro(isbn=None):
    if not escritura_autorizada():
        return error_xml(401, 'Esta operacion requiere una clave de escritura.')

    datos = datos_entrantes()
    objetivo = (isbn or datos.get('isbn') or '').strip()
    if not objetivo:
        return error_xml(400, 'Indica el ISBN del libro que se va a actualizar.')

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
        return error_xml(400, 'Los datos del libro no son validos.', errores)
    if not limpio and autores is None and generos is None:
        return error_xml(400, 'No se envio ningun campo que actualizar.')

    try:
        with cursor_bd(escribe=True) as cur:
            cur.execute('SELECT id FROM libros WHERE isbn = %s', (objetivo,))
            fila = cur.fetchone()
            if fila is None:
                return error_xml(404, 'No existe un libro con ese ISBN.')
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
        return error_xml(409, 'Ya existe otro libro registrado con ese ISBN.')
    except pgerrors.ForeignKeyViolation:
        return error_xml(400, 'La categoria, el formato, el autor o el genero '
                              'indicado no existe.')
    except pgerrors.CheckViolation:
        return error_xml(400, 'Los datos no cumplen una regla del catalogo.')

    return catalogo_a_xml([libro])


@app.route('/api/book/delete', methods=['DELETE', 'POST'])
@app.route('/api/book/delete/<isbn>', methods=['DELETE', 'POST'])
def borrar_libro(isbn=None):
    if not escritura_autorizada():
        return error_xml(401, 'Esta operacion requiere una clave de escritura.')

    datos = datos_entrantes()
    objetivo = (isbn or datos.get('isbn') or request.args.get('isbn') or '').strip()
    if not objetivo:
        return error_xml(400, 'Indica el ISBN del libro que se va a borrar.')

    try:
        with cursor_bd(escribe=True) as cur:
            # Las tablas puente y las imagenes caen por ON DELETE CASCADE.
            cur.execute('DELETE FROM libros WHERE isbn = %s RETURNING isbn, titulo',
                        (objetivo,))
            fila = cur.fetchone()
    except pgerrors.ForeignKeyViolation:
        return error_xml(409, 'El libro no se puede borrar porque otro registro '
                              'todavia depende de el.')

    if fila is None:
        return error_xml(404, 'No existe un libro con ese ISBN.')

    raiz = ET.Element('result', {'status': 'ok'})
    ET.SubElement(raiz, 'message').text = 'Libro eliminado del catalogo.'
    ET.SubElement(raiz, 'book', {'isbn': fila['isbn']}).text = fila['titulo']
    return responder_xml(raiz)


@app.route('/api/health', methods=['GET'])
def salud():
    try:
        with cursor_bd() as cur:
            cur.execute('SELECT count(*)::int AS total FROM libros')
            total = cur.fetchone()['total']
    except psycopg2.Error:
        log.exception('Fallo la verificacion de salud')
        raiz = ET.Element('health', {'status': 'error'})
        ET.SubElement(raiz, 'database').text = 'sin conexion'
        return responder_xml(raiz, 503)

    raiz = ET.Element('health', {'status': 'ok'})
    ET.SubElement(raiz, 'database').text = 'conectada'
    ET.SubElement(raiz, 'books').text = str(total)
    return responder_xml(raiz)


@app.route('/library.css', methods=['GET'])
def hoja_de_estilos():
    """Sirve la hoja con la que el navegador dibuja el XML del catalogo."""
    return send_from_directory(RAIZ, 'library.css', mimetype='text/css')


# -----------------------------------------------------------------------------
# Manejo de errores. El cliente recibe XML explicado; la traza va al log.
# -----------------------------------------------------------------------------
@app.errorhandler(404)
def _no_encontrado(_error):
    return error_xml(404, 'El recurso solicitado no existe.',
                     ['Consulta la documentacion en /docs'])


@app.errorhandler(405)
def _metodo_no_permitido(_error):
    return error_xml(405, 'Ese metodo HTTP no esta permitido en esta ruta.')


@app.errorhandler(psycopg2.OperationalError)
def _sin_base(error):
    log.error('No hay conexion con la base de datos: %s', error)
    return error_xml(503, 'El servicio no puede conectarse a su base de datos.')


@app.errorhandler(Exception)
def _fallo_inesperado(error):
    # Los errores HTTP que no tienen manejador propio (400, 415...) conservan su
    # codigo; el resto se convierte en un 500 generico. Nunca se devuelve el
    # mensaje original: puede contener SQL o nombres de tabla. La traza completa
    # queda del lado del servidor.
    if isinstance(error, HTTPException):
        return error_xml(error.code or 500, 'La solicitud no se pudo atender.')
    log.exception('Fallo no controlado: %s', error)
    return error_xml(500, 'Ocurrio un error al procesar la solicitud.')


# =============================================================================
# Documentacion Swagger (OpenAPI 3). La especificacion se sirve en
# /apispec.json y la interfaz en /docs.
# =============================================================================
RESPUESTA_XML = {
    'description': 'Catalogo en XML con la misma estructura que library.xml',
    'content': {'application/xml': {'schema': {'type': 'string'}}},
}
RESPUESTA_ERROR = {
    'description': 'Error explicado en XML: <error code="..."><message>...',
    'content': {'application/xml': {'schema': {'type': 'string'}}},
}


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
        'version': '1.0.0',
        'description': (
            'Microservicio Flask que expone el catalogo de libros en XML.\n\n'
            'Lee de la misma base PostgreSQL que el monolito (db/01_schema.sql) '
            'y devuelve la misma estructura que services/soap/library.xml: cada '
            '`<book>` lleva el ISBN como atributo e incluye titulo, autores, '
            'anio, generos, precio, stock, formato, imagenes y los conceptos '
            'definidos en ese libro con su descripcion.\n\n'
            'Todas las respuestas son `application/xml`. Las escrituras aceptan '
            'JSON o formulario.'),
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
            'responses': {'200': RESPUESTA_XML, '503': RESPUESTA_ERROR},
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
            'responses': {'200': RESPUESTA_XML, '400': RESPUESTA_ERROR},
        }},
        '/api/book/{isbn}': {'get': {
            'tags': ['Lectura'],
            'summary': 'Devuelve un libro por su ISBN',
            'parameters': [_param('isbn', 'ISBN del libro', donde='path',
                                  requerido=True)],
            'responses': {'200': RESPUESTA_XML, '404': RESPUESTA_ERROR},
        }},
        '/api/book/author/{author_id}': {'get': {
            'tags': ['Lectura'],
            'summary': 'Devuelve los libros de un autor',
            'parameters': [_param('author_id', 'Id del autor', 'integer',
                                  donde='path', requerido=True)],
            'responses': {'200': RESPUESTA_XML, '404': RESPUESTA_ERROR},
        }},
        '/api/book/insert': {'post': {
            'tags': ['Escritura'],
            'summary': 'Registra un libro nuevo',
            'requestBody': _cuerpo(ESQUEMA_LIBRO),
            'responses': {'201': RESPUESTA_XML, '400': RESPUESTA_ERROR,
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
            'responses': {'200': RESPUESTA_XML, '400': RESPUESTA_ERROR,
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
            'responses': {'200': RESPUESTA_XML, '400': RESPUESTA_ERROR,
                          '401': RESPUESTA_ERROR, '404': RESPUESTA_ERROR},
        }},
        '/api/health': {'get': {
            'tags': ['Servicio'],
            'summary': 'Estado del servicio y de su base de datos',
            'responses': {'200': RESPUESTA_XML, '503': RESPUESTA_ERROR},
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
    raiz = ET.Element('service', {'name': 'catalogo-libreria', 'version': '1.0.0'})
    for ruta, descripcion in [
        ('/docs', 'Documentacion Swagger'),
        ('/api/books', 'Todos los libros'),
        ('/api/books/search', 'Busqueda por atributos'),
        ('/api/book/{isbn}', 'Un libro'),
        ('/api/book/author/{id}', 'Libros de un autor'),
        ('/api/book/insert', 'Alta (POST)'),
        ('/api/book/update', 'Modificacion (PUT)'),
        ('/api/book/delete', 'Baja (DELETE)'),
        ('/api/health', 'Estado del servicio'),
    ]:
        ET.SubElement(raiz, 'endpoint', {'path': ruta}).text = descripcion
    return responder_xml(raiz)


if __name__ == '__main__':
    if not API_TOKEN and ORIGENES == ['*']:
        log.warning('Las escrituras estan abiertas a cualquier origen y sin '
                    'clave. Define API_TOKEN y CORS_ORIGENES en el .env antes '
                    'de exponer este servicio a internet.')
    if not BD['password']:
        log.warning('DB_PASSWORD viene vacia: revisa services/soap/.env')
    app.run(host=APP_HOST, port=APP_PORT, debug=False)
