#!/usr/bin/env bash
# =============================================================================
# publicar.sh — arma la carpeta publicable del reporte del Ejercicio 03.
#
#     bash docs/ejercicio03/publicar.sh
#
# Copia el contrato, el SQL, la documentación, las evidencias y un tar.gz del
# código fuente dentro de docs/ejercicio03/, con la estructura que pide el
# enunciado. Después, sube esa carpeta a la VM:
#
#     scp -r docs/ejercicio03/* usuario@vm:~/html/ejercicio03/
#
# NO copia .env, .venv, __pycache__ ni nada versionado como secreto.
# =============================================================================
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
MODULO="$RAIZ/services/library_soap_service"

echo "Módulo:  $MODULO"
echo "Destino: $AQUI"

rm -rf "$AQUI/wsdl" "$AQUI/sql" "$AQUI/docs" "$AQUI/evidencias" "$AQUI/descargas"
mkdir -p "$AQUI"/{wsdl,sql,docs,evidencias,descargas,img}

cp "$MODULO/wsdl/library-classifier.wsdl" "$AQUI/wsdl/"
cp "$MODULO/sql/soap_module.sql"          "$AQUI/sql/"
cp "$MODULO/README.md"                    "$AQUI/docs/"
cp "$MODULO/docs"/*.md                    "$AQUI/docs/"
cp "$MODULO/docs/evidencias"/*            "$AQUI/evidencias/"

# Código fuente, sin secretos ni artefactos locales.
tar -czf "$AQUI/descargas/library_soap_service.tar.gz" \
    -C "$RAIZ/services" \
    --exclude='.env' --exclude='.venv' --exclude='venv' \
    --exclude='__pycache__' --exclude='*.pyc' \
    library_soap_service

echo
echo "Contenido publicable:"
find "$AQUI" -type f -not -path '*/.*' | sed "s|$AQUI/|  |" | sort

echo
echo "Revisión de secretos en lo que se va a publicar:"
# El valor debe parecer un secreto de verdad: se ignoran los marcadores de
# posición de la documentación (WSSE_SECRETO=..., DB_PASSWORD=<tu clave>).
if grep -rIlE '(DB_PASSWORD|WSSE_SECRETO|API_TOKEN)=[^[:space:].<]{6,}|BEGIN [A-Z ]*PRIVATE KEY' \
        "$AQUI" 2>/dev/null | grep -v publicar.sh; then
    echo "  ⚠️  REVISA los archivos de arriba antes de publicar."
    exit 1
else
    echo "  Sin credenciales en claro."
fi

echo
echo "Listo. Verifica desde una ventana privada que index.html, css/, wsdl/,"
echo "sql/, docs/, evidencias/ y descargas/ son accesibles."
