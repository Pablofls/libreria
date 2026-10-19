"""Simula un vehículo que se mueve por Monterrey y envía su posición por WebSocket.

Uso:  python gps_app.py --url ws://127.0.0.1:5900/ws/gps --id auto-1
Para varios vehículos, lanza varias instancias con distinto --id.
"""
import argparse
import json
import math
import random
import time

import websocket  # websocket-client

# Misma caja que valida el microservicio (se queda un poco dentro del borde).
LAT_MIN, LAT_MAX = 25.52, 25.83
LON_MIN, LON_MAX = -100.48, -100.17
GRADOS_POR_M = 1 / 111_000  # aprox. de metros a grados de latitud


class Vehiculo:
    def __init__(self):
        self.lat = random.uniform(25.60, 25.75)   # centro de la ciudad
        self.lon = random.uniform(-100.40, -100.25)
        self.rumbo = random.uniform(0, 360)       # grados, 0 = norte
        self.velocidad = random.uniform(8, 16)    # m/s (~30–60 km/h)

    def avanzar(self, dt):
        # Rumbo y velocidad cambian poco por tick, como un auto real.
        self.rumbo = (self.rumbo + random.uniform(-15, 15)) % 360
        self.velocidad = min(22, max(4, self.velocidad + random.uniform(-1.5, 1.5)))
        d = self.velocidad * dt * GRADOS_POR_M
        nlat = self.lat + d * math.cos(math.radians(self.rumbo))
        nlon = self.lon + d * math.sin(math.radians(self.rumbo)) / math.cos(math.radians(self.lat))
        # Al llegar al borde, da la vuelta en vez de salirse de Monterrey.
        if not LAT_MIN <= nlat <= LAT_MAX or not LON_MIN <= nlon <= LON_MAX:
            self.rumbo = (self.rumbo + 180) % 360
            return
        self.lat, self.lon = nlat, nlon


def main():
    p = argparse.ArgumentParser(description="Simulador de GPS de un vehículo en Monterrey")
    p.add_argument("--url", default="ws://127.0.0.1:5900/ws/gps")
    p.add_argument("--id", default=f"auto-{random.randint(100, 999)}")
    p.add_argument("--intervalo", type=float, default=1.0, help="segundos entre envíos")
    args = p.parse_args()

    auto = Vehiculo()
    print(f"[{args.id}] enviando a {args.url} cada {args.intervalo}s (Ctrl+C para salir)")
    while True:
        try:
            ws = websocket.create_connection(args.url, timeout=10)
            print(f"[{args.id}] conectado")
            while True:
                auto.avanzar(args.intervalo)
                ws.send(json.dumps({"id": args.id, "lat": round(auto.lat, 6), "lon": round(auto.lon, 6)}))
                time.sleep(args.intervalo)
        except KeyboardInterrupt:
            print(f"[{args.id}] detenido")
            return
        except Exception as e:
            print(f"[{args.id}] conexión perdida ({e}); reintentando en 3 s")
            time.sleep(3)


if __name__ == "__main__":
    main()
