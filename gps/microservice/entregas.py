"""Rastreo de entregas: un vehículo de reparto por pedido, transmitido por WebSocket.

Lo usa la app de escritorio Java (apps/JavaDesktop_app). Va aparte de los
vehículos libres de role=gps/role=map: aquí cada simulación pertenece a UN
pedido real del servicio de pedidos y sólo la ve su dueño (o un admin).

  ws://host:5900/track/ws?code=LIB-MTY-2026-000125
      cabecera Authorization: Bearer <JWT emitido por login>

Código de rastreo: LIB-MTY-<año en que se creó el pedido>-<id del pedido en 6
dígitos>. Es determinista, así que se recupera en cualquier momento sin guardar
nada: no hay tabla nueva.

Autorización DELEGADA al servicio de pedidos: el JWT del usuario se reenvía a
GET /orders/<id>. Ese servicio ya verifica firma, expiración, revocación en
Redis y propiedad (un pedido ajeno responde 404). Así este servicio no conoce
el secreto JWT ni la base de datos.

Simulación en función del tiempo transcurrido desde el pago (momento en que el
historial del pedido registra el estado 'pagado'): tras reiniciar el servicio
el vehículo aparece donde debe, y un pedido pagado hace rato sale Entregado con
la ruta completa. 'Entregado' es exactamente el último punto de la ruta.

Mensajes al cliente:
  {"type": "snapshot", ...estado, "ruta": [[lat, lon], ...], "recorrido": [[lat, lon], ...]}
  {"type": "update",   ...estado}                 cada segundo hasta Entregado
  {"type": "error", "message": "..."}             y se cierra la conexión
"""
import json
import math
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

PEDIDOS_URL = os.environ.get("PEDIDOS_URL", "http://127.0.0.1:5005").rstrip("/")
OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org").rstrip("/")
# Duración total de la entrega simulada, del pago a Entregado (acelerada para la demo).
ENTREGA_SEGUNDOS = max(60, int(os.environ.get("ENTREGA_SEGUNDOS", "180")))
REVALIDAR_SEGUNDOS = 60    # cada cuánto se vuelve a preguntar a pedidos (logout, token vencido)

# Fases antes de que el vehículo se mueva (segundos desde el pago).
FIN_CONFIRMADO = 10
FIN_PREPARANDO = 30
FRACCION_ENVIADO = 0.08    # primer tramo de la ruta: "Pedido enviado"; luego "En ruta"
# La entrega va acelerada (unos km en un par de minutos). Lo que se reporta es la
# velocidad de un reparto urbano real y el factor de aceleración, no los cientos
# de km/h que saldrían de dividir la ruta entre la duración de la demo.
VELOCIDAD_CIUDAD_KMH = 35

CONFIRMADO = "Pedido confirmado"
PREPARANDO = "Preparando pedido"
ENVIADO = "Pedido enviado"
EN_RUTA = "En ruta de entrega"
ENTREGADO = "Entregado"
ESTADOS = (CONFIRMADO, PREPARANDO, ENVIADO, EN_RUTA, ENTREGADO)

# Almacén de la librería (centro de Monterrey) y zona urbana de destinos.
ALMACEN = (25.6714, -100.3093)
ZONA = (25.63, 25.74, -100.39, -100.25)    # lat_min, lat_max, lon_min, lon_max
# Misma caja que valida el microservicio para los vehículos libres.
LAT_MIN, LAT_MAX = 25.50, 25.85
LON_MIN, LON_MAX = -100.50, -100.15

CODIGO = re.compile(r"^LIB-MTY-(\d{4})-(\d{6})$")


class RastreoError(Exception):
    """Motivo legible para el usuario; se le envía tal cual y se cierra."""


# -----------------------------------------------------------------------------
# Código de rastreo
# -----------------------------------------------------------------------------
def codigo_para(pedido_id, anio):
    return "LIB-MTY-{:04d}-{:06d}".format(anio, pedido_id)


def parsear_codigo(codigo):
    """(año, pedido_id) o RastreoError."""
    m = CODIGO.match((codigo or "").strip().upper())
    if not m or int(m.group(2)) == 0:
        raise RastreoError("Código de rastreo inválido (formato LIB-MTY-AAAA-NNNNNN).")
    return int(m.group(1)), int(m.group(2))


# -----------------------------------------------------------------------------
# Autorización: el servicio de pedidos decide
# -----------------------------------------------------------------------------
def consultar_pedido(pedido_id, autorizacion, abrir=urllib.request.urlopen):
    """El pedido tal como lo ve su dueño, o RastreoError. `abrir` se cambia en las pruebas."""
    if not autorizacion or not autorizacion.startswith("Bearer "):
        raise RastreoError("Falta el token: inicia sesión para rastrear tu pedido.")
    req = urllib.request.Request(
        "{}/orders/{}".format(PEDIDOS_URL, pedido_id),
        headers={"Authorization": autorizacion, "Accept": "application/json"})
    try:
        with abrir(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RastreoError("Tu sesión no es válida o venció: vuelve a iniciar sesión.")
        if e.code == 404:
            # Ajeno o inexistente: el mismo mensaje, como hace pedidos.
            raise RastreoError("No hay ningún pedido tuyo con ese código.")
        raise RastreoError("El servicio de pedidos respondió {}.".format(e.code))
    except (urllib.error.URLError, OSError, ValueError):
        raise RastreoError("El servicio de pedidos no está disponible.")


def _fecha(texto):
    return datetime.fromisoformat(str(texto).replace("Z", "+00:00"))


def momento_de_pago(pedido, anio):
    """Epoch del pago, validando que el código corresponda a este pedido y que esté pagado."""
    if _fecha(pedido["creado_en"]).year != anio:
        raise RastreoError("No hay ningún pedido tuyo con ese código.")
    estado = pedido.get("estado")
    if estado == "pendiente":
        raise RastreoError("El pedido aún no está pagado: no hay envío que rastrear.")
    if estado == "cancelado":
        raise RastreoError("El pedido fue cancelado: no hay envío que rastrear.")
    if estado not in ("pagado", "enviado"):
        raise RastreoError("El pedido está {}: no hay envío que rastrear.".format(estado))
    pagos = [h["cambiado_en"] for h in pedido.get("historial", []) if h.get("estado") == "pagado"]
    return _fecha(pagos[-1] if pagos else pedido["creado_en"]).timestamp()


# -----------------------------------------------------------------------------
# Ruta por calles (funciones copiadas de gps/GPSapp/gps_app.py)
# -----------------------------------------------------------------------------
def metros(a, b):
    """Distancia entre dos (lat, lon) por haversine."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def rumbo(a, b):
    """Rumbo en grados (0 = norte) de a hacia b."""
    p1, p2, dl = math.radians(a[0]), math.radians(b[0]), math.radians(b[1] - a[1])
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def pedir_ruta(origen, destino):
    """Ruta por calles [(lat, lon), ...] entre dos puntos, según OSRM."""
    url = (f"{OSRM_URL}/route/v1/driving/{origen[1]},{origen[0]};{destino[1]},{destino[0]}"
           "?overview=full&geometries=geojson")
    req = urllib.request.Request(url, headers={"User-Agent": "libreria-gps-entregas"})
    with urllib.request.urlopen(req, timeout=10) as r:
        datos = json.load(r)
    puntos = [(lat, lon) for lon, lat in datos["routes"][0]["geometry"]["coordinates"]]
    return [p for i, p in enumerate(puntos) if i == 0 or p != puntos[i - 1]]


_rutas = {}
_candado_rutas = threading.Lock()


def ruta_del_pedido(pedido_id, pedir=pedir_ruta):
    """Ruta almacén → destino del pedido. El destino sale de una semilla con el id:
    el mismo pedido siempre va al mismo lugar. Se calcula una vez por pedido."""
    with _candado_rutas:
        if pedido_id in _rutas:
            return _rutas[pedido_id]
    azar = random.Random(pedido_id)
    for _ in range(5):
        destino = (azar.uniform(ZONA[0], ZONA[1]), azar.uniform(ZONA[2], ZONA[3]))
        try:
            ruta = pedir(ALMACEN, destino)
        except Exception:
            raise RastreoError("No se pudo calcular la ruta de entrega (OSRM no responde).")
        if len(ruta) >= 2 and all(LAT_MIN <= la <= LAT_MAX and LON_MIN <= lo <= LON_MAX for la, lo in ruta):
            break
    else:
        raise RastreoError("No se encontró una ruta de entrega válida.")
    with _candado_rutas:
        _rutas[pedido_id] = ruta
    return ruta


# -----------------------------------------------------------------------------
# Simulación: estado en función del tiempo
# -----------------------------------------------------------------------------
def acumulados(ruta):
    """Distancia recorrida hasta cada punto de la ruta."""
    total, salida = 0.0, [0.0]
    for a, b in zip(ruta, ruta[1:]):
        total += metros(a, b)
        salida.append(total)
    return salida


def estado_en(ruta, acum, transcurrido, duracion=ENTREGA_SEGUNDOS):
    """Estado del envío `transcurrido` segundos después del pago."""
    largo = acum[-1]
    mov = duracion - FIN_PREPARANDO                     # segundos en movimiento
    fraccion = min(1.0, max(0.0, (transcurrido - FIN_PREPARANDO) / mov))
    if transcurrido < FIN_CONFIRMADO:
        estado = CONFIRMADO
    elif transcurrido < FIN_PREPARANDO:
        estado = PREPARANDO
    elif fraccion >= 1.0:
        estado = ENTREGADO
    elif fraccion < FRACCION_ENVIADO:
        estado = ENVIADO
    else:
        estado = EN_RUTA

    # Punto de la ruta a la distancia recorrida.
    meta = fraccion * largo
    i = 0
    while i < len(ruta) - 2 and acum[i + 1] < meta:
        i += 1
    if estado == ENTREGADO:
        pos, i = ruta[-1], len(ruta) - 1
        heading = rumbo(ruta[-2], ruta[-1])
    else:
        tramo = acum[i + 1] - acum[i]
        t = 0.0 if tramo == 0 else (meta - acum[i]) / tramo
        a, b = ruta[i], ruta[i + 1]
        pos = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        heading = rumbo(a, b)

    en_movimiento = estado in (ENVIADO, EN_RUTA)
    # Variación suave (semáforos, avenidas) alrededor de la velocidad de ciudad.
    velocidad = VELOCIDAD_CIUDAD_KMH + 10 * math.sin(transcurrido / 7) if en_movimiento else 0.0
    return {
        "estado": estado,
        "paso": ESTADOS.index(estado) + 1,
        "lat": round(pos[0], 6),
        "lon": round(pos[1], 6),
        "heading": round(heading) % 360,
        "speed": round(velocidad, 1),
        # Cuántas veces más rápido que un reparto real a VELOCIDAD_CIUDAD_KMH.
        "aceleracion": round(largo / (VELOCIDAD_CIUDAD_KMH / 3.6) / mov, 1),
        "progreso": round(fraccion, 4),
        "distancia_m": round(largo),
        "restante_m": round(largo - meta),
        "eta_s": max(0, round(duracion - transcurrido)),
        "indice": i,
    }


def recorrido_hasta(ruta, estado):
    """Puntos ya recorridos, terminando en la posición actual."""
    if estado["estado"] in (CONFIRMADO, PREPARANDO):
        return [list(ruta[0])]
    puntos = [list(p) for p in ruta[:estado["indice"] + 1]]
    puntos.append([estado["lat"], estado["lon"]])
    return puntos


# -----------------------------------------------------------------------------
# Conexión WebSocket
# -----------------------------------------------------------------------------
activos = set()
_candado_activos = threading.Lock()


def atender(ws, codigo, autorizacion, ahora=time.time):
    """Vida completa de un cliente de rastreo."""
    with _candado_activos:
        activos.add(ws)
    try:
        try:
            anio, pedido_id = parsear_codigo(codigo)
            pedido = consultar_pedido(pedido_id, autorizacion)
            pagado_en = momento_de_pago(pedido, anio)
            ruta = ruta_del_pedido(pedido_id)
        except RastreoError as e:
            ws.send(json.dumps({"type": "error", "message": str(e)}))
            ws.close()
            return
        acum = acumulados(ruta)
        base = {"code": codigo_para(pedido_id, anio), "pedido_id": pedido_id,
                "pedido_estado": pedido.get("estado"), "duracion_s": ENTREGA_SEGUNDOS}
        estado = estado_en(ruta, acum, ahora() - pagado_en)
        ws.send(json.dumps({"type": "snapshot", **base, **estado,
                            "ruta": [list(p) for p in ruta],
                            "recorrido": recorrido_hasta(ruta, estado)}))
        validado = ahora()
        while True:
            # receive con timeout hace de reloj y detecta el cierre del cliente.
            ws.receive(timeout=1 if estado["estado"] != ENTREGADO else REVALIDAR_SEGUNDOS)
            if ahora() - validado >= REVALIDAR_SEGUNDOS:
                try:
                    consultar_pedido(pedido_id, autorizacion)
                except RastreoError as e:
                    ws.send(json.dumps({"type": "error", "message": str(e)}))
                    ws.close()
                    return
                validado = ahora()
            if estado["estado"] == ENTREGADO:
                continue
            estado = estado_en(ruta, acum, ahora() - pagado_en)
            ws.send(json.dumps({"type": "update", **base, **estado}))
    except Exception:
        pass    # el cliente cerró
    finally:
        with _candado_activos:
            activos.discard(ws)
