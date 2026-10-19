"""Microservicio GPS: recibe coordenadas por WebSocket y las retransmite al mapa.

Un solo endpoint, el rol va en la URL:

  ws://host:5900/ws?role=gps   <- simuladores GPS (productores)
      {"vehicle_id": "V001", "latitude": 25.6866, "longitude": -100.3161, "speed": 45.5, "heading": 270}
  ws://host:5900/ws?role=map   -> páginas con mapa (visores)
      {"type": "snapshot", "vehicles": [...]}   al conectar
      {"type": "update", ...}                   en cada posición
      {"type": "remove", "vehicle_id": ...}     cuando un vehículo se desconecta

  /        -> sirve ../Map/index.html
  /health  -> estado
"""
import json
import os
import threading
import time
from collections import deque
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_sock import Sock

# Caja que delimita Monterrey y su área metropolitana. Todo lo de fuera se rechaza.
LAT_MIN, LAT_MAX = 25.50, 25.85
LON_MIN, LON_MAX = -100.50, -100.15
VELOCIDAD_MAX = 200        # km/h
HISTORIAL_MAX = 200        # puntos por vehículo

DIR_MAPA = Path(__file__).resolve().parent.parent / "Map"

app = Flask(__name__)
sock = Sock(app)

vehiculos = {}        # vehicle_id -> último registro
historial = {}        # vehicle_id -> deque de [lat, lon]
visores = set()       # websockets de las páginas con mapa
candado = threading.Lock()


def _difundir(mensaje):
    """Envía el mensaje a todos los visores; descarta los que ya se cayeron."""
    texto = json.dumps(mensaje)
    with candado:
        actuales = list(visores)
    for ws in actuales:
        try:
            ws.send(texto)
        except Exception:
            with candado:
                visores.discard(ws)


def _numero(v):
    return not isinstance(v, bool) and isinstance(v, (int, float))


def _validar(dato):
    """Devuelve (registro, None) o (None, motivo)."""
    if not isinstance(dato, dict):
        return None, "se esperaba un objeto JSON"
    vid = dato.get("vehicle_id")
    if not isinstance(vid, str) or not vid.strip() or len(vid) > 40:
        return None, "vehicle_id inválido (texto de 1 a 40 caracteres)"
    lat, lon = dato.get("latitude"), dato.get("longitude")
    if not (_numero(lat) and _numero(lon)):
        return None, "latitude y longitude deben ser números"
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        return None, "coordenadas fuera de Monterrey"
    speed, heading = dato.get("speed", 0), dato.get("heading", 0)
    if not (_numero(speed) and 0 <= speed <= VELOCIDAD_MAX):
        return None, f"speed debe estar entre 0 y {VELOCIDAD_MAX} km/h"
    if not (_numero(heading) and 0 <= heading <= 360):
        return None, "heading debe estar entre 0 y 360"
    return {
        "vehicle_id": vid.strip(),
        "latitude": float(lat),
        "longitude": float(lon),
        "speed": float(speed),
        "heading": float(heading),
        "ts": time.time(),
    }, None


def _rol_gps(ws):
    ids_propios = set()
    try:
        while True:
            crudo = ws.receive()
            if crudo is None:
                break
            try:
                registro, motivo = _validar(json.loads(crudo))
            except ValueError:
                registro, motivo = None, "JSON inválido"
            if motivo:
                ws.send(json.dumps({"type": "error", "message": motivo}))
                continue
            vid = registro["vehicle_id"]
            ids_propios.add(vid)
            with candado:
                vehiculos[vid] = registro
                historial.setdefault(vid, deque(maxlen=HISTORIAL_MAX)).append(
                    [registro["latitude"], registro["longitude"]])
            _difundir({"type": "update", **registro})
    except Exception:
        pass
    finally:
        for vid in ids_propios:
            with candado:
                vehiculos.pop(vid, None)
                historial.pop(vid, None)
            _difundir({"type": "remove", "vehicle_id": vid})


def _rol_map(ws):
    with candado:
        snapshot = [{**v, "history": list(historial.get(vid, []))} for vid, v in vehiculos.items()]
        visores.add(ws)
    try:
        ws.send(json.dumps({"type": "snapshot", "vehicles": snapshot}))
        while ws.receive() is not None:   # el visor no manda nada; sólo detectamos el cierre
            pass
    except Exception:
        pass
    finally:
        with candado:
            visores.discard(ws)


@sock.route("/ws")
def ws_endpoint(ws):
    rol = request.args.get("role")
    if rol == "gps":
        _rol_gps(ws)
    elif rol == "map":
        _rol_map(ws)
    else:
        ws.send(json.dumps({"type": "error", "message": "role debe ser 'gps' o 'map'"}))
        ws.close()


@app.get("/")
def index():
    return send_from_directory(DIR_MAPA, "index.html")


@app.get("/health")
def health():
    with candado:
        return jsonify(estado="ok", vehiculos=len(vehiculos), visores=len(visores))


if __name__ == "__main__":
    app.run(
        host=os.environ.get("GPS_HOST", "0.0.0.0"),
        port=int(os.environ.get("GPS_PORT", "5900")),
        threaded=True,
    )
