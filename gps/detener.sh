#!/usr/bin/env bash
# Apaga todo: los vehículos y el microservicio.
# Uso: bash detener.sh
pkill -f gps_app.py && echo "Vehículos detenidos" || echo "No había vehículos corriendo"
sudo systemctl stop libreria-gps && echo "Microservicio detenido"
