"""Microservicio GPS: recibe coordenadas por WebSocket y las retransmite al mapa.

  /ws/gps  <- aplicaciones GPS (productores): {"id": "auto-1", "lat": 25.67, "lon": -100.31}
  /ws/map  -> páginas web (visores): snapshot, posicion y baja
  /        -> sirve ../Map/index.html
  /health  -> estado
"""
import json
import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from flask_sock import Sock

# Caja que delimita Monterrey y su área metropolitana. Todo lo de fuera se rechaza.
LAT_MIN, LAT_MAX = 25.50, 25.85
LON_MIN, LON_MAX = -100.50, -100.15

DIR_MAPA = Path(__file__).resolve().parent.parent / "Map"

app = Flask(__name__)
sock = Sock(app)

vehiculos = {}        # id -> {"id", "lat", "lon", "ts"}
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


def _validar(dato):
    """Devuelve (registro, None) o (None, motivo)."""
    if not isinstance(dato, dict):
        return None, "se esperaba un objeto JSON"
    vid = dato.get("id")
    if not isinstance(vid, str) or not vid.strip() or len(vid) > 40:
        return None, "id inválido (texto de 1 a 40 caracteres)"
    lat, lon = dato.get("lat"), dato.get("lon")
    for v in (lat, lon):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None, "lat y lon deben ser números"
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        return None, "coordenadas fuera de Monterrey"
    return {"id": vid.strip(), "lat": float(lat), "lon": float(lon), "ts": time.time()}, None


@sock.route("/ws/gps")
def ws_gps(ws):
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
                ws.send(json.dumps({"tipo": "error", "mensaje": motivo}))
                continue
            ids_propios.add(registro["id"])
            with candado:
                vehiculos[registro["id"]] = registro
            _difundir({"tipo": "posicion", **registro})
    except Exception:
        pass
    finally:
        for vid in ids_propios:
            with candado:
                vehiculos.pop(vid, None)
            _difundir({"tipo": "baja", "id": vid})


@sock.route("/ws/map")
def ws_map(ws):
    with candado:
        snapshot = list(vehiculos.values())
        visores.add(ws)
    try:
        ws.send(json.dumps({"tipo": "snapshot", "vehiculos": snapshot}))
        while ws.receive() is not None:   # el visor no manda nada; sólo detectamos el cierre
            pass
    except Exception:
        pass
    finally:
        with candado:
            visores.discard(ws)


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
