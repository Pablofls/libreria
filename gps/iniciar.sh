#!/usr/bin/env bash
# Levanta todo: el microservicio (systemd) y N vehículos simulados.
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

for i in $(seq 1 "$N"); do
  if pgrep -f "gps_app.py --id auto-$i\$" > /dev/null; then
    echo "auto-$i ya estaba corriendo"
  else
    nohup "$DIR/GPSapp/.venv/bin/python" "$DIR/GPSapp/gps_app.py" --id "auto-$i" > "/tmp/auto-$i.log" 2>&1 &
    echo "auto-$i lanzado"
  fi
done

sleep 2
curl -s http://127.0.0.1:5900/health; echo
