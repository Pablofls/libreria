#!/usr/bin/env bash
# =============================================================================
# Benchmark de proxy inverso, balanceador de carga y API gateway.
# Corre todo en Docker, en la máquina local (no toca la VM):
#
#     bash docs/benchmark_proxy/ejecutar.sh
#
# Variables opcionales: REPS (3), DURACION (20s), VUS (50), CONSERVAR=1 (no
# apaga los contenedores al terminar), SOLO=rp|lb|gw|fo (una sola parte).
# Resultado: docs/benchmark_proxy/resultados/ y RESULTADOS.md.
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")"
REPS="${REPS:-3}"
DURACION="${DURACION:-20s}"
VUS="${VUS:-50}"
SOLO="${SOLO:-}"
DC="docker compose"

python3 generar.py
set -a; . generado/tokens.env; set +a

mkdir -p resultados
# --force-recreate: el secreto es nuevo en cada corrida y Kong/Envoy lo leen de
# un archivo montado; sin recrearlos se quedarían con el de la corrida anterior.
$DC up -d --build --quiet-pull --force-recreate
echo "Esperando a que arranquen los contenedores…"
sleep 8

# --- Cargar con k6 -----------------------------------------------------------
k6() {   # k6 <url> <salida.json> <token|-> <duracion>
    local token="$3"; [ "$token" = "-" ] && token=""
    $DC run --rm -e URL="$1" -e SALIDA="/resultados/$2" -e TOKEN="$token" \
        -e VUS="$VUS" -e DURACION="$4" k6 run --quiet /scripts/carga.js >/dev/null 2>&1
}

muestrear() {   # muestrear <archivo> <contenedores…>  (a media corrida)
    local archivo="$1"; shift
    docker stats --no-stream --format '{{.Name}};{{.CPUPerc}};{{.MemUsage}}' "$@" > "$archivo"
}

# --- Comprobaciones previas --------------------------------------------------
echo "== Pruebas funcionales de seguridad de los gateways"
docker exec bench-auth python /app/verificar.py | tee resultados/funcional.txt

echo "== Memoria en reposo"
docker stats --no-stream --format '{{.Name}};{{.CPUPerc}};{{.MemUsage}}' \
    bench-nginx bench-haproxy bench-traefik bench-envoy bench-apache bench-kong bench-auth \
    | tee resultados/memoria_reposo.txt

# nombre | categoría | url | token (0/1) | contenedores a muestrear
ESCENARIOS=(
  "directo|rp|http://172.28.0.11/|0|bench-b1"
  "nginx|rp|http://172.28.0.20:80/|0|bench-nginx"
  "nginx-sin-keepalive|rp|http://172.28.0.20:84/|0|bench-nginx"
  "haproxy|rp|http://172.28.0.21:80/|0|bench-haproxy"
  "traefik|rp|http://172.28.0.22:80/|0|bench-traefik"
  "envoy|rp|http://172.28.0.23:8080/|0|bench-envoy"
  "apache|rp|http://172.28.0.24:80/|0|bench-apache"
  "apache-nginx|rp|http://172.28.0.24:81/|0|bench-apache bench-nginx"
  "nginx|lb|http://172.28.0.20:81/|0|bench-nginx"
  "haproxy|lb|http://172.28.0.21:81/|0|bench-haproxy"
  "traefik|lb|http://172.28.0.22:81/|0|bench-traefik"
  "envoy|lb|http://172.28.0.23:8081/|0|bench-envoy"
  "nginx-auth-request|gw|http://172.28.0.20:82/|1|bench-nginx bench-auth"
  "nginx-auth-cache|gw|http://172.28.0.20:83/|1|bench-nginx bench-auth"
  "kong|gw|http://172.28.0.25:8000/|1|bench-kong"
  "envoy-jwt|gw|http://172.28.0.23:8082/|1|bench-envoy"
)

segundos="${DURACION%s}"
for e in "${ESCENARIOS[@]}"; do
    IFS='|' read -r nombre cat url usa_token conts <<< "$e"
    [ -n "$SOLO" ] && [ "$SOLO" != "$cat" ] && continue
    token="-"; [ "$usa_token" = "1" ] && token="$TOKEN_VALIDO"
    echo "== [$cat] $nombre"
    k6 "$url" "calentamiento.json" "$token" 3s
    for i in $(seq 1 "$REPS"); do
        if [ "$i" = "1" ]; then
            # shellcheck disable=SC2086
            ( sleep $(( segundos / 2 )); muestrear "resultados/${cat}_${nombre}_recursos.txt" $conts ) &
        fi
        k6 "$url" "${cat}_${nombre}_r${i}.json" "$token" "$DURACION"
        wait
        echo "   repetición $i lista"
    done
done
rm -f resultados/calentamiento.json

# --- Conmutación por error: b3 muere a los 10 s y vuelve a los 20 s ----------
if [ -z "$SOLO" ] || [ "$SOLO" = "fo" ]; then
    for e in "nginx|http://172.28.0.20:81/" "haproxy|http://172.28.0.21:81/" \
             "traefik|http://172.28.0.22:81/" "envoy|http://172.28.0.23:8081/"; do
        IFS='|' read -r nombre url <<< "$e"
        echo "== [conmutación] $nombre"
        $DC start b3 >/dev/null 2>&1; sleep 3
        k6 "$url" "fo_${nombre}.json" "-" 30s &
        sleep 10; docker kill bench-b3 >/dev/null
        sleep 10; $DC start b3 >/dev/null 2>&1
        wait
    done
fi

python3 analizar.py
[ "${CONSERVAR:-0}" = "1" ] || $DC down --remove-orphans >/dev/null 2>&1
echo "Listo: docs/benchmark_proxy/RESULTADOS.md"
