# =============================================================================
# locustfile.py — prueba smoke del microservicio de catalogo (books, 5002).
#
#     cd locust_tests
#     locust -f catalogo_escalonado.py   # -> http://localhost:8089 (GUI de Locust)
#
# Instalacion, variables y lectura de resultados: README.md de esta carpeta.
#
# Escalonado (LoadTestShape, al final del archivo):
#
#     etapa 0   100 usuarios leen el catalogo en XML  (GET /books)
#               100 usuarios leen el catalogo en JSON (GET /books?format=json)
#     etapa 1+  se suman 10 usuarios por etapa, cada grupo contra un endpoint
#               nuevo del swagger: search, summary, concepts, /books/<isbn>,
#               /books/author/<id>, health y, opcional, insert/update/delete.
#
# Los endpoints salen de /apispec.json del servicio. Las rutas /api/... son
# alias de las mismas funciones y nginx no las publica: se prueban las /books.
#
# Por que una sola clase de usuario: Locust reinicia su reparto por pesos en
# cada etapa y los 10 usuarios nuevos caerian otra vez en XML/JSON. Aqui cada
# usuario toma su rol por el orden en que nace (1-100 XML, 101-200 JSON, luego
# bloques de 10), y como la carga solo sube, el reparto es exacto.
#
# Ninguna credencial vive en este archivo: la escritura solo se activa con
# ADMIN_EMAIL y ADMIN_PASS por variable de entorno.
# =============================================================================

import itertools
import os
import random
import uuid

from locust import HttpUser, LoadTestShape, between, events, task

# --- Configuracion (todo por variable de entorno) ----------------------------
HOST = os.getenv('HOST', 'https://34.51.108.167').rstrip('/')
CA_CERT = os.path.expanduser(os.getenv('CA_CERT', '~/libreria-api.crt'))
# Por nginx (443) la salud del catalogo es /health/catalogo; directo al 5002, /health.
HEALTH_PATH = os.getenv('HEALTH_PATH', '/health/catalogo')
LOGIN_URL = os.getenv('LOGIN_URL', HOST).rstrip('/')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', '')
ADMIN_PASS = os.getenv('ADMIN_PASS', '')
ESCRITURA = bool(ADMIN_EMAIL and ADMIN_PASS)

ETAPA_SEGUNDOS = int(os.getenv('ETAPA_SEGUNDOS', '60'))
SPAWN_RATE = float(os.getenv('SPAWN_RATE', '20'))
AUTOR_MAX = int(os.getenv('AUTOR_MAX', '30'))     # el seed crea 30 autores

USUARIOS_XML = 100
USUARIOS_JSON = 100
INCREMENTO = 10

# Valores de busqueda reales del seed (db/02_seed_30_per_table.sql).
TERMINOS = ['IaaS', 'PaaS', 'SaaS', 'Serverless', 'Contenedor', 'Cache']
BUSQUEDAS = [
    {'q': 'cloud'}, {'q': 'datos'}, {'titulo': 'sistemas'},
    {'formato': 'pasta'}, {'precio_min': '100', 'precio_max': '900'},
    {'anio_min': '2010'}, {'disponible': 'true'}, {'stock_min': '1'},
]

# ISBN reales: los lee el primer usuario que los necesita, de /books/summary.
_isbns = []
_nacimientos = itertools.count()


def _formato():
    return random.choice(['xml', 'json'])


def _params(formato, extra=None):
    params = dict(extra or {})
    if formato == 'json':
        params['format'] = 'json'
    return params


def _validar(respuesta, formato, aceptar=(200,)):
    """Marca fallo si el codigo o el tipo de contenido no son los esperados."""
    if respuesta.status_code not in aceptar:
        respuesta.failure('HTTP {}'.format(respuesta.status_code))
        return
    tipo = respuesta.headers.get('Content-Type', '')
    esperado = 'json' if formato == 'json' else 'xml'
    if esperado not in tipo:
        respuesta.failure('Content-Type {!r}, se esperaba {}'.format(tipo, esperado))
    else:
        respuesta.success()


class Lector(HttpUser):
    host = HOST
    wait_time = between(1, 3)
    token = None

    def on_start(self):
        # Certificado autofirmado: se confia en el .crt de la VM, no se apaga TLS.
        if HOST.startswith('https://'):
            self.client.verify = CA_CERT if os.path.isfile(CA_CERT) else False

        n = next(_nacimientos)
        if n < USUARIOS_XML:
            self.rol = 'catalogo_xml'
        elif n < USUARIOS_XML + USUARIOS_JSON:
            self.rol = 'catalogo_json'
        else:
            bloque = (n - USUARIOS_XML - USUARIOS_JSON) // INCREMENTO
            self.rol = ETAPAS[min(bloque, len(ETAPAS) - 1)]
        if self.rol == 'escritura':
            self.iniciar_sesion()

    @task
    def accion(self):
        getattr(self, self.rol)()

    # --- utilidades ----------------------------------------------------------

    def get(self, ruta, nombre, formato, extra=None, aceptar=(200,)):
        with self.client.get(ruta, params=_params(formato, extra),
                             name='{} [{}]'.format(nombre, formato),
                             catch_response=True) as r:
            _validar(r, formato, aceptar)

    def isbn(self):
        if not _isbns:
            r = self.client.get('/books/summary', params={'format': 'json'},
                                name='(setup) /books/summary')
            if r.ok:
                _isbns.extend(b['isbn'] for b in r.json().get('books', []))
        return random.choice(_isbns) if _isbns else '978-0-13-609181-2'

    # --- etapa 0: 100 + 100 sobre el catalogo completo -----------------------

    def catalogo_xml(self):
        self.get('/books', '/books', 'xml')

    def catalogo_json(self):
        self.get('/books', '/books', 'json')

    # --- etapas 1+: +10 usuarios por endpoint --------------------------------

    def busqueda(self):
        self.get('/books/search', '/books/search', _formato(),
                 random.choice(BUSQUEDAS))

    def resumen(self):
        self.get('/books/summary', '/books/summary', _formato(),
                 {'limite': random.choice([10, 20, 50])})

    def conceptos(self):
        if random.random() < 0.5:
            self.get('/concepts', '/concepts', _formato())
        else:
            self.get('/concepts', '/concepts?termino', _formato(),
                     {'termino': random.choice(TERMINOS)})

    def libro_por_isbn(self):
        self.get('/books/' + self.isbn(), '/books/[isbn]', _formato())

    def libros_por_autor(self):
        # 404 es una respuesta valida del endpoint (autor dado de baja).
        self.get('/books/author/{}'.format(random.randint(1, AUTOR_MAX)),
                 '/books/author/[id]', _formato(), aceptar=(200, 404))

    def salud(self):
        self.get(HEALTH_PATH, HEALTH_PATH, _formato())

    # --- escritura (opcional): insert -> update -> delete ---------------------

    def iniciar_sesion(self):
        r = self.client.post(LOGIN_URL + '/login', params={'format': 'json'},
                             data={'email': ADMIN_EMAIL, 'password': ADMIN_PASS},
                             name='(setup) /login')
        self.token = r.json().get('token') if r.ok else None

    def escritura(self):
        """Cada iteracion crea un ISBN unico 999-xxxxxxxxxx y lo borra al
        final, asi que el catalogo queda como estaba."""
        if not self.token:
            self.iniciar_sesion()
            return
        cabeceras = {'Authorization': 'Bearer {}'.format(self.token)}
        isbn = '999-' + str(uuid.uuid4().int)[:10]
        alta = {'isbn': isbn, 'titulo': 'Locust smoke ' + isbn, 'precio': '1.00',
                'stock': '1', 'categoria_id': '1', 'formato_id': '1'}

        with self.client.post('/books/insert', params={'format': 'json'},
                              data=alta, headers=cabeceras,
                              name='/books/insert [json]', catch_response=True) as r:
            if r.status_code == 401:            # JWT vencido (20 min) o revocado
                r.success()
                self.token = None
                return
            _validar(r, 'json', aceptar=(201,))
            if r.status_code != 201:
                return

        with self.client.put('/books/update/' + isbn, params={'format': 'json'},
                             data={'stock': '2'}, headers=cabeceras,
                             name='/books/update/[isbn] [json]',
                             catch_response=True) as r:
            _validar(r, 'json')

        with self.client.delete('/books/delete/' + isbn, params={'format': 'json'},
                                headers=cabeceras,
                                name='/books/delete/[isbn] [json]',
                                catch_response=True) as r:
            _validar(r, 'json')


# Orden en que entran los endpoints, uno por etapa.
ETAPAS = ['busqueda', 'resumen', 'conceptos', 'libro_por_isbn',
          'libros_por_autor', 'salud']
if ESCRITURA:
    ETAPAS.append('escritura')


class Escalonado(LoadTestShape):
    """200 usuarios (100 XML + 100 JSON) y luego +10 por endpoint y etapa.

    Despues de la ultima etapa se sostiene la carga completa una etapa mas y
    la prueba termina sola.
    """

    def tick(self):
        etapa = int(self.get_run_time() // ETAPA_SEGUNDOS)
        if etapa > len(ETAPAS) + 1:
            return None
        n = min(etapa, len(ETAPAS))
        return USUARIOS_XML + USUARIOS_JSON + INCREMENTO * n, SPAWN_RATE


@events.test_start.add_listener
def _al_iniciar(environment, **_):
    global _nacimientos
    _nacimientos = itertools.count()       # un "Start" nuevo en la GUI reparte de cero
    _isbns.clear()
    print('Host: {}  |  CA_CERT: {}  |  etapas: {} x {} s  |  escritura: {}'.format(
        HOST, CA_CERT if os.path.isfile(CA_CERT) else 'NO ENCONTRADO (verify=False)',
        len(ETAPAS) + 2, ETAPA_SEGUNDOS, 'si' if ESCRITURA else 'no'))
