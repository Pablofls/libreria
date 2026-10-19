"""Simula un vehículo que recorre las calles de Monterrey y envía su posición por WebSocket.

El recorrido es una ruta real por calles que pide a OSRM (ruteo sobre OpenStreetMap):
se elige un destino al azar, se avanza por la ruta a la velocidad simulada y, al llegar,
se pide otra ruta desde ahí.

Uso:  python gps_app.py --url "ws://127.0.0.1:5900/ws?role=gps" --id V001
Para varios vehículos, lanza varias instancias con distinto --id.
"""
import argparse
import json
import math
import random
import time
import urllib.request

import websocket  # websocket-client

# Misma caja que valida el microservicio (se queda un poco dentro del borde).
LAT_MIN, LAT_MAX = 25.52, 25.83
LON_MIN, LON_MAX = -100.48, -100.17
# Zona urbana donde se eligen orígenes y destinos.
ZONA = (25.62, 25.75, -100.40, -100.24)   # lat_min, lat_max, lon_min, lon_max

OSRM_POR_OMISION = "https://router.project-osrm.org"


def punto_al_azar():
    return random.uniform(ZONA[0], ZONA[1]), random.uniform(ZONA[2], ZONA[3])


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


def pedir_ruta(base, origen, destino):
    """Ruta por calles [(lat, lon), ...] entre dos puntos, según OSRM."""
    url = (f"{base}/route/v1/driving/{origen[1]},{origen[0]};{destino[1]},{destino[0]}"
           "?overview=full&geometries=geojson")
    req = urllib.request.Request(url, headers={"User-Agent": "libreria-gps-simulador"})
    with urllib.request.urlopen(req, timeout=10) as r:
        datos = json.load(r)
    puntos = [(lat, lon) for lon, lat in datos["routes"][0]["geometry"]["coordinates"]]
    return [p for i, p in enumerate(puntos) if i == 0 or p != puntos[i - 1]]   # sin puntos repetidos


class Vehiculo:
    def __init__(self, osrm):
        self.osrm = osrm
        self.velocidad = random.uniform(8, 16)    # m/s (~30–60 km/h)
        self.ruta = []
        self.i = 0                                # avanzando de ruta[i] a ruta[i+1]
        self.lat = self.lon = None
        self.rumbo = 0.0

    def nueva_ruta(self):
        """Pide rutas hasta conseguir una válida (dentro de Monterrey)."""
        origen = (self.lat, self.lon) if self.lat is not None else punto_al_azar()
        while True:
            try:
                ruta = pedir_ruta(self.osrm, origen, punto_al_azar())
            except Exception as e:
                print(f"no se pudo obtener ruta de OSRM ({e}); reintentando en 3 s")
                time.sleep(3)
                continue
            if len(ruta) >= 2 and all(LAT_MIN <= la <= LAT_MAX and LON_MIN <= lo <= LON_MAX for la, lo in ruta):
                self.ruta, self.i = ruta, 0
                self.lat, self.lon = ruta[0]
                return
            time.sleep(1)   # no saturar el servidor público

    def avanzar(self, dt):
        # La velocidad cambia poco por tick, como un auto real.
        self.velocidad = min(22, max(4, self.velocidad + random.uniform(-1.5, 1.5)))
        if not self.ruta:
            self.nueva_ruta()
        resta = self.velocidad * dt
        while resta > 0:
            if self.i >= len(self.ruta) - 1:
                self.nueva_ruta()   # llegó al destino: otra ruta desde aquí
                return
            destino = self.ruta[self.i + 1]
            self.rumbo = rumbo((self.lat, self.lon), destino)
            d = metros((self.lat, self.lon), destino)
            if d > resta:
                t = resta / d
                self.lat += (destino[0] - self.lat) * t
                self.lon += (destino[1] - self.lon) * t
                resta = 0
            else:
                self.lat, self.lon = destino
                resta -= d
                self.i += 1


def main():
    p = argparse.ArgumentParser(description="Simulador de GPS de un vehículo en Monterrey")
    p.add_argument("--url", default="ws://127.0.0.1:5900/ws?role=gps")
    p.add_argument("--id", default=f"V{random.randint(1, 999):03d}", help="vehicle_id, p. ej. V001")
    p.add_argument("--intervalo", type=float, default=1.0, help="segundos entre envíos")
    p.add_argument("--osrm", default=OSRM_POR_OMISION, help="URL base del servidor OSRM")
    args = p.parse_args()

    auto = Vehiculo(args.osrm.rstrip("/"))
    print(f"[{args.id}] enviando a {args.url} cada {args.intervalo}s (Ctrl+C para salir)")
    while True:
        try:
            ws = websocket.create_connection(args.url, timeout=10)
            print(f"[{args.id}] conectado")
            while True:
                auto.avanzar(args.intervalo)
                ws.send(json.dumps({
                    "vehicle_id": args.id,
                    "latitude": round(auto.lat, 6),
                    "longitude": round(auto.lon, 6),
                    "speed": round(auto.velocidad * 3.6, 1),   # m/s -> km/h
                    "heading": round(auto.rumbo) % 360,
                }))
                time.sleep(args.intervalo)
        except KeyboardInterrupt:
            print(f"[{args.id}] detenido")
            return
        except Exception as e:
            print(f"[{args.id}] conexión perdida ({e}); reintentando en 3 s")
            time.sleep(3)


if __name__ == "__main__":
    main()
