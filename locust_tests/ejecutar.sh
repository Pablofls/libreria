#!/usr/bin/env bash
# =============================================================================
# locust_tests/ejecutar.sh — corre UN perfil de carga sin GUI y guarda la
# evidencia en evidencias/<perfil>/:
#     <perfil>_stats.csv            resumen por solicitud (RPS, p50, p95, fallos)
#     <perfil>_stats_history.csv    serie temporal (base de las graficas)
#     <perfil>_failures.csv         motivo de cada fallo
#     <perfil>_exceptions.csv       excepciones del cliente
#     <perfil>.html                 reporte HTML de Locust con graficas
#     consola.txt                   lo que imprimio Locust (login, avisos, resumen)
#
#     bash ejecutar.sh smoke | load | stress | spike | soak | quiebre
#
# Credenciales por variable de entorno (ver README); nunca en este archivo.
# =============================================================================
set -euo pipefail

PERFIL="${1:-}"
case "$PERFIL" in
    smoke|load|stress|spike|soak|quiebre) ;;
    *) echo "Uso: bash ejecutar.sh smoke|load|stress|spike|soak|quiebre" >&2; exit 2 ;;
esac

cd "$(dirname "$0")"
LOCUST="${LOCUST:-.venv/bin/locust}"
SALIDA="evidencias/$PERFIL"
mkdir -p "$SALIDA"

# Locust sale con codigo 1 si hubo AL MENOS un fallo. Eso es un resultado de la
# prueba, no un error del script: se anota y se sigue (para que una cadena
# "a && b && c" no se corte). Cualquier otro codigo si detiene.
set +e
PERFIL="$PERFIL" "$LOCUST" -f locustfile.py --headless \
    --csv "$SALIDA/$PERFIL" --csv-full-history \
    --html "$SALIDA/$PERFIL.html" \
    --only-summary 2>&1 | tee "$SALIDA/consola.txt"
CODIGO=${PIPESTATUS[0]}
set -e
if [ "$CODIGO" -eq 1 ]; then
    echo "Locust termino con fallos (ver $SALIDA/${PERFIL}_failures.csv)."
elif [ "$CODIGO" -ne 0 ]; then
    echo "Locust fallo con codigo $CODIGO" >&2
    exit "$CODIGO"
fi

echo
echo "Evidencia guardada en $SALIDA/"
