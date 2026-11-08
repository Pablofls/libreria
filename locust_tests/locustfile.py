# =============================================================================
# locust_tests/locustfile.py
# Pruebas de rendimiento: monolito web vs. microservicios de la libreria.
#
#     cd locust_tests
#     bash ejecutar.sh smoke        # o load | stress | spike | soak | quiebre
#
# Instalacion, credenciales y lectura de resultados: README.md de esta carpeta.
#
# -----------------------------------------------------------------------------
# QUE SE MIDE
#   El tiempo de respuesta (p50/p95), las solicitudes por segundo (RPS) y el
#   porcentaje de errores de operaciones de LECTURA (todas GET, ninguna escribe)
#   del monolito y de los seis microservicios, vistos desde un cliente externo
#   a traves de la IP publica de la VM de GCP. Nunca localhost.
#
# DESTINOS (el enunciado habla de :3000 y :5000-5005; en nuestra VM esos puertos
# no estan expuestos y los servicios tienen otros numeros, asi que se usa la
# entrada publica que ya existe. Ver la tabla del README):
#   monolito  http://<IP>/library            Apache 80 -> nginx 8009 -> Node 3000
#   API       https://<IP>                   Apache 443 -> nginx 8443 -> Flask
#             /session login(5000)  /books catalogo(5002)  /users users(5003)
#             /authors authors(5004) /orders pedidos(5005)  /payments pagos(5006)
#
# RUTAS ELEGIDAS (comparables cuando se puede)
#   "listado de libros": [monolito] /library/libros (EJS + PostgreSQL)
#                        [catalogo] /books?format=json   [pedidos] /orders/books
#   "autor":             [monolito] /library/autores/<id>  vs  [authors] /authors
#   propias de cada uno: [users] /users/<mi id>  [pagos] /payments
#                        [login] /session (cookie -> Redis + PostgreSQL)
#   salud:               /health/<servicio>?format=json  y  [monolito] /library/login
#   Una respuesta de salud confirma disponibilidad, no que el negocio funcione:
#   por eso salud y negocio aparecen en filas separadas.
#
# -----------------------------------------------------------------------------
# CONCEPTOS DE LOCUST
#   User / HttpUser  Un "usuario virtual": un greenlet que repite tareas en bucle
#                    con su propio cliente HTTP (y su cookie jar).
#   @task            Metodo que el usuario ejecuta en cada vuelta del bucle. Aqui
#                    hay una sola tarea que pide el SIGUIENTE destino de una lista
#                    (round-robin). Motivo: con 1 usuario (smoke) y una clase por
#                    destino, Locust solo crearia una clase y probaria un sistema;
#                    asi todos los destinos reciben el mismo numero de peticiones
#                    en las mismas condiciones.
#   wait_time        Pausa entre tareas de un mismo usuario: between(0.5, 1.5) s,
#                    media 1 s. Simula a alguien que navega, no un bucle cerrado.
#                    Con ella, cada usuario genera ~1 peticion/s: el RPS crece con
#                    los usuarios mientras el servidor aguante.
#   usuarios         Numero de usuarios virtuales concurrentes.
#   spawn_rate       Cuantos usuarios nuevos arrancan por segundo al subir.
#   duracion         La fija cada perfil (clase Perfil, abajo); al acabar, tick()
#                    devuelve None y la prueba se detiene sola.
#   estadisticas     Por nombre de solicitud ("[servicio] GET /ruta"): numero,
#                    fallos, mediana, p95, RPS. --csv las guarda; --html, el
#                    reporte con graficas.
#   LoadTestShape    Define usuarios y spawn_rate segundo a segundo: es el
#                    "perfil de carga".
#
# PERFILES (PERFIL=...)
#   smoke    1 usuario, 30 s                       -> las rutas responden bien
#   load     5 usuarios, spawn 1/s, 120 s          -> carga esperada y estable
#   stress   2 -> 5 -> 10 -> 15 -> 20, 36 s c/u    -> degradacion al pasar la carga
#   spike    2 (30 s) -> 15 de golpe (30 s) -> 2 (60 s) -> efecto y recuperacion
#   soak     3 usuarios, 240 s                     -> degradacion sostenida (miniatura)
#   quiebre  +1 usuario cada 12 s, max 20 y 240 s; al incumplir el umbral se
#            congela la carga 20 s y termina      -> estimar el punto de quiebre
#
# UMBRAL DE SERVICIO (el del enunciado, sin cambios)
#   degradado si p95 > 1000 ms  o  errores > 5 %.
#   En "quiebre" se evalua sobre la ventana de los ultimos ~10 s (no el
#   acumulado), con al menos 20 peticiones en la ventana para no reaccionar a
#   una sola peticion lenta. El punto de quiebre de una prueba corta, desde un
#   solo cliente y por internet, NO es la capacidad maxima real del sistema.
#
# CREDENCIALES: ninguna en este archivo. Se leen de LECTOR_EMAIL/LECTOR_PASS
# (servicios) y MONO_EMAIL/MONO_PASS (monolito). Se hace UN solo login por
# ejecucion, fuera de las estadisticas: asi no se mide bcrypt, no se dispara el
# limitador de intentos y el token/cookie solo viven en memoria.
# =============================================================================

import base64
import json
import os
import re
import time

import requests
from locust import HttpUser, LoadTestShape, between, events, task
from locust.clients import HttpSession

# --- Configuracion -----------------------------------------------------------
IP = os.getenv('VM_IP', '34.51.108.167')
API_HOST = os.getenv('API_HOST', 'https://' + IP).rstrip('/')
MONO_HOST = os.getenv('MONO_HOST', 'http://' + IP).rstrip('/')
MONO_BASE = os.getenv('MONO_BASE', '/library').rstrip('/')
CA_CERT = os.path.expanduser(os.getenv('CA_CERT', '~/libreria-api.crt'))
VERIFY = CA_CERT if os.path.isfile(CA_CERT) else False

PERFIL = os.getenv('PERFIL', 'smoke').lower()
UMBRAL_P95_MS = float(os.getenv('UMBRAL_P95_MS', '1000'))
UMBRAL_ERRORES = float(os.getenv('UMBRAL_ERRORES', '0.05'))
AUTOR_ID = os.getenv('AUTOR_ID', '1')

AQUI = os.path.dirname(os.path.abspath(__file__))
EVIDENCIAS = os.path.join(AQUI, 'evidencias')

COOKIE_LOGIN = 'libreria_sesion'

SERVICIOS = ['login', 'catalogo', 'users', 'authors', 'pedidos', 'pagos']

# Estado compartido por todos los usuarios virtuales (solo en memoria).
SESION = {'token': None, 'user_id': None, 'cookie_login': None, 'cookie_mono': None}


# --- Login unico al iniciar (no cuenta en las estadisticas) -------------------

def _claims(token):
    """Lee el payload del JWT sin verificarlo (solo para saber el user_id)."""
    cuerpo = token.split('.')[1]
    cuerpo += '=' * (-len(cuerpo) % 4)
    return json.loads(base64.urlsafe_b64decode(cuerpo))


def _login_servicios():
    email, clave = os.getenv('LECTOR_EMAIL', ''), os.getenv('LECTOR_PASS', '')
    if not (email and clave):
        print('AVISO: sin LECTOR_EMAIL/LECTOR_PASS -> se omiten /session, /users, '
              '/orders/books y /payments.')
        return
    s = requests.Session()
    try:
        r = s.post(API_HOST + '/login', params={'format': 'json'},
                   data={'email': email, 'password': clave},
                   verify=VERIFY, timeout=15)
    except requests.RequestException as e:
        print('ERROR login servicios: {}'.format(type(e).__name__))
        return
    if not r.ok:
        print('ERROR login servicios: HTTP {}'.format(r.status_code))
        return
    SESION['token'] = r.json().get('token')
    SESION['user_id'] = _claims(SESION['token']).get('user_id')
    # Nombre fijado en apps/services/login/app.py (SESSION_COOKIE_NAME).
    SESION['cookie_login'] = s.cookies.get(COOKIE_LOGIN)
    print('Login servicios OK (user_id {}).'.format(SESION['user_id']))
    if not SESION['cookie_login']:
        print('AVISO: login no devolvio la cookie {} -> se omite /session.'.format(
            COOKIE_LOGIN))


def _login_monolito():
    email, clave = os.getenv('MONO_EMAIL', ''), os.getenv('MONO_PASS', '')
    if not (email and clave):
        print('AVISO: sin MONO_EMAIL/MONO_PASS -> se omiten /library/libros y '
              '/library/autores/<id>.')
        return
    s = requests.Session()
    url = MONO_HOST + MONO_BASE + '/login'
    try:
        r = s.get(url, timeout=15)
        csrf = re.search(r'name="_csrf" value="([^"]+)"', r.text)
        r = s.post(url, data={'email': email, 'password': clave,
                              '_csrf': csrf.group(1) if csrf else ''},
                   allow_redirects=False, timeout=15)
    except requests.RequestException as e:
        print('ERROR login monolito: {}'.format(type(e).__name__))
        return
    if r.status_code != 302 or '/login' in r.headers.get('Location', ''):
        print('ERROR login monolito: HTTP {}'.format(r.status_code))
        return
    SESION['cookie_mono'] = s.cookies.get('libreria.sid')
    print('Login monolito OK.')


@events.test_start.add_listener
def _al_iniciar(environment, **_):
    for k in SESION:
        SESION[k] = None
    _login_servicios()
    _login_monolito()
    print('Perfil: {} | API: {} | monolito: {}{} | CA_CERT: {}'.format(
        PERFIL, API_HOST, MONO_HOST, MONO_BASE,
        CA_CERT if VERIFY else 'NO ENCONTRADO (verify=False)'))


# --- Validacion de respuestas -----------------------------------------------

def _codigo(r):
    """'HTTP 503', o el nombre de la excepcion si no hubo respuesta (codigo 0:
    timeout, conexion rechazada o cortada)."""
    if r.status_code == 0 and r.error is not None:
        return 'sin respuesta: {}'.format(type(r.error).__name__)
    return 'HTTP {}'.format(r.status_code)


def _validar_json(r):
    if r.status_code != 200:
        r.failure(_codigo(r))
    elif 'json' not in r.headers.get('Content-Type', ''):
        r.failure('Content-Type no JSON')
    else:
        r.success()


def _validar_html(r):
    if r.status_code in (301, 302, 303):
        r.failure('HTTP {} a {} (sesion perdida)'.format(
            r.status_code, r.headers.get('Location', '?')))
    elif r.status_code != 200:
        r.failure(_codigo(r))
    elif 'html' not in r.headers.get('Content-Type', ''):
        r.failure('Content-Type no HTML')
    else:
        r.success()


def _validar_sesion(r):
    if r.status_code != 200:
        r.failure(_codigo(r))
        return
    try:
        ok = r.json().get('autenticada') is True
    except ValueError:
        ok = False
    if ok:
        r.success()
    else:
        r.failure('sesion no autenticada')


# --- Usuario virtual ---------------------------------------------------------

_contador = [0]


class Visitante(HttpUser):
    host = API_HOST
    wait_time = between(0.5, 1.5)

    def on_start(self):
        self.client.verify = VERIFY
        # Cliente aparte para el monolito: su propio cookie jar, para que la
        # cookie 'libreria_sesion' de login y 'libreria.sid' del monolito no se mezclen.
        self.mono = HttpSession(MONO_HOST, self.environment.events.request, self)
        self.destinos = self._armar_destinos()
        # Cada usuario empieza en un punto distinto de la lista: asi no golpean
        # todos el mismo destino a la vez.
        self.i = _contador[0] % len(self.destinos)
        _contador[0] += 1

    def _armar_destinos(self):
        d = []
        # Salud (disponibilidad).
        for s in SERVICIOS:
            d.append((self.client, '/health/' + s, {'format': 'json'}, {},
                      '[{}] GET /health'.format(s), _validar_json))
        d.append((self.mono, MONO_BASE + '/login', None, {},
                  '[monolito] GET /library/login', _validar_html))

        # Negocio, publicas.
        d.append((self.client, '/books', {'format': 'json'}, {},
                  '[catalogo] GET /books', _validar_json))
        d.append((self.client, '/authors', None, {},
                  '[authors] GET /authors', _validar_json))

        # Negocio con JWT de lector.
        if SESION['token']:
            jwt = {'Authorization': 'Bearer ' + SESION['token']}
            d.append((self.client, '/users/{}'.format(SESION['user_id']), None, jwt,
                      '[users] GET /users/[id]', _validar_json))
            d.append((self.client, '/orders/books', None, jwt,
                      '[pedidos] GET /orders/books', _validar_json))
            d.append((self.client, '/payments', None, jwt,
                      '[pagos] GET /payments', _validar_json))
        if SESION['cookie_login']:
            d.append((self.client, '/session', {'format': 'json'},
                      {'Cookie': COOKIE_LOGIN + '=' + SESION['cookie_login']},
                      '[login] GET /session', _validar_sesion))

        # Negocio del monolito con sesion de lector.
        if SESION['cookie_mono']:
            galleta = {'Cookie': 'libreria.sid=' + SESION['cookie_mono']}
            d.append((self.mono, MONO_BASE + '/libros', None, galleta,
                      '[monolito] GET /library/libros', _validar_html))
            d.append((self.mono, MONO_BASE + '/autores/' + AUTOR_ID, None, galleta,
                      '[monolito] GET /library/autores/[id]', _validar_html))
        return d

    @task
    def siguiente_destino(self):
        cliente, ruta, params, cabeceras, nombre, validar = self.destinos[self.i]
        self.i = (self.i + 1) % len(self.destinos)
        # Los clientes no guardan cookies entre peticiones: cada una lleva solo
        # la que le corresponde por cabecera.
        cliente.cookies.clear()
        with cliente.get(ruta, params=params, headers=cabeceras, name=nombre,
                         allow_redirects=False, catch_response=True,
                         timeout=30) as r:
            validar(r)


# --- Perfiles de carga -------------------------------------------------------

def _etapas(perfil):
    """Lista de (hasta_segundo, usuarios, spawn_rate)."""
    if perfil == 'smoke':
        return [(30, 1, 1)]
    if perfil == 'load':
        return [(120, 5, 1)]
    if perfil == 'stress':
        return [(36, 2, 2), (72, 5, 2), (108, 10, 2), (144, 15, 2), (180, 20, 2)]
    if perfil == 'spike':
        return [(30, 2, 2), (60, 15, 15), (120, 2, 15)]
    if perfil == 'soak':
        return [(240, 3, 1)]
    raise ValueError('PERFIL desconocido: ' + perfil)


class Perfil(LoadTestShape):
    """Elige la forma de la carga segun PERFIL. Ver la cabecera del archivo."""

    QUIEBRE_PASO_S = 12
    QUIEBRE_MAX_USUARIOS = 20
    QUIEBRE_MAX_S = 240
    QUIEBRE_SOSTENER_S = 20
    QUIEBRE_MIN_PETICIONES = 20

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.ventana = []          # (t, peticiones, fallos) cada tick
        self.quiebre_en = None     # (t, usuarios, p95, errores)

    def tick(self):
        t = self.get_run_time()
        if PERFIL != 'quiebre':
            for hasta, usuarios, tasa in _etapas(PERFIL):
                if t < hasta:
                    return usuarios, tasa
            return None
        return self._quiebre(t)

    def _quiebre(self, t):
        if self.quiebre_en:
            if t - self.quiebre_en[0] >= self.QUIEBRE_SOSTENER_S:
                return None
            return self.quiebre_en[1], 1

        if t >= self.QUIEBRE_MAX_S:
            self._anotar(t, None, None, None)
            return None
        usuarios = min(1 + int(t // self.QUIEBRE_PASO_S), self.QUIEBRE_MAX_USUARIOS)

        total = self.runner.stats.total
        self.ventana.append((t, total.num_requests, total.num_failures))
        self.ventana = [v for v in self.ventana if t - v[0] <= 10]
        t0, n0, f0 = self.ventana[0]
        n, f = total.num_requests - n0, total.num_failures - f0
        if t - t0 >= 9 and n >= self.QUIEBRE_MIN_PETICIONES:
            p95 = total.get_current_response_time_percentile(0.95) or 0
            errores = f / n
            if p95 > UMBRAL_P95_MS or errores > UMBRAL_ERRORES:
                actuales = self.runner.user_count
                self.quiebre_en = (t, actuales, p95, errores)
                self._anotar(t, actuales, p95, errores)
                return actuales, 1
        return usuarios, 1

    def _anotar(self, t, usuarios, p95, errores):
        os.makedirs(os.path.join(EVIDENCIAS, 'quiebre'), exist_ok=True)
        ruta = os.path.join(EVIDENCIAS, 'quiebre', 'quiebre_punto.txt')
        with open(ruta, 'w', encoding='utf-8') as fh:
            fh.write('fecha: {}\n'.format(time.strftime('%Y-%m-%d %H:%M:%S')))
            fh.write('umbral: p95 > {:.0f} ms o errores > {:.0%} (ventana ~10 s)\n'.format(
                UMBRAL_P95_MS, UMBRAL_ERRORES))
            if usuarios is None:
                fh.write('resultado: NO se incumplio el umbral en {:.0f} s '
                         '(maximo {} usuarios).\n'.format(t, self.QUIEBRE_MAX_USUARIOS))
            else:
                fh.write('resultado: umbral incumplido a los {:.0f} s con {} usuarios\n'
                         'p95 ventana: {:.0f} ms | errores ventana: {:.1%}\n'.format(
                             t, usuarios, p95, errores))
        print('Quiebre anotado en ' + ruta)
