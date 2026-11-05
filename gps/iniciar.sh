#!/usr/bin/env bash
# Levanta todo: el microservicio (systemd) y el simulador con N vehículos.
# Uso: bash iniciar.sh [N]      (N = número de vehículos, 3 por omisión)
set -u
N="${1:-3}"
DIR="$(cd "$(dirname "$0")" && pwd)"

sudo systemctl start libreria-gps || { echo "No se pudo arrancar libreria-gps"; exit 1; }

# Espera a que el microservicio responda (máx. ~10 s).
for _ in $(seq 1 20); do
  curl -sf http://127.0.0.1:5900/health > /dev/null && break
  sleep 0.5
done
curl -sf http://127.0.0.1:5900/health > /dev/null || { echo "El microservicio no responde en :5900"; exit 1; }

# Un solo proceso simula los N vehículos (V001 … VN).
if pgrep -f gps_app.py > /dev/null; then
  echo "El simulador ya estaba corriendo (bash detener.sh para reiniciarlo con otro N)"
else
  nohup "$DIR/GPSapp/.venv/bin/python" "$DIR/GPSapp/gps_app.py" --vehiculos "$N" > /tmp/gps_app.log 2>&1 &
  echo "Simulador lanzado con $N vehículos (log en /tmp/gps_app.log)"
fi

sleep 3
curl -s http://127.0.0.1:5900/health; echo
