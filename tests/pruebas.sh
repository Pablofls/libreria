#!/usr/bin/env bash
# =============================================================================
# tests/pruebas.sh — ejecuta la matriz de pruebas de docs/TEST_PLAN.md contra
# una instancia de la aplicación ya levantada.
#
#     BASE_URL=http://127.0.0.1:3000 \
#     ADMIN_EMAIL=... ADMIN_PASS=... LECTOR_EMAIL=... LECTOR_PASS=... \
#     bash tests/pruebas.sh
#
# BASE_URL LLEVA EL PREFIJO PUBLICO. El script concatena "$BASE_URL/login" sin
# saber nada de BASE_PATH, asi que en la VM, donde la app publica bajo /library,
# va http://127.0.0.1:3000/library. Sin el prefijo todo da 404 y, como el script
# no alcanza a leer el token CSRF de la pagina de login, los POST salen luego
# con 403: parece un fallo de seguridad y es una URL mal armada.
#
# El lector de prueba de los datos de siembra es ana.ruiz@libreria.udem.mx. Las
# contrasenas no estan en el repositorio; si no se recuerdan, se cambian desde
# /usuarios como Administrador.
#
# Cada prueba imprime ID, descripción, resultado esperado y observado. El script
# termina con código 1 si alguna falla, para poder encadenarlo.
#
# Las credenciales se pasan por variable de entorno, nunca escritas en el
# archivo: el repositorio es público. Para no dejarlas en ~/.bash_history:
#
#     read -sp "admin pass: " A_PASS; echo
#
# Ojo con el limitador de intentos de login (auth.controller.js): varias
# corridas fallidas seguidas acaban en 429 durante 15 minutos. Vive en memoria
# del proceso, asi que un `systemctl restart libreria` lo borra.
# =============================================================================
set -uo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:3000}"
ADMIN_EMAIL="${ADMIN_EMAIL:-}"
ADMIN_PASS="${ADMIN_PASS:-}"
LECTOR_EMAIL="${LECTOR_EMAIL:-}"
LECTOR_PASS="${LECTOR_PASS:-}"

if [ -z "$ADMIN_EMAIL" ] || [ -z "$ADMIN_PASS" ]; then
    echo "Faltan ADMIN_EMAIL / ADMIN_PASS. Ver la cabecera de este archivo." >&2
    exit 2
fi

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
JA="$TMP/admin.jar"; JL="$TMP/lector.jar"
PASADAS=0; FALLIDAS=0

verde()  { printf '\033[32m%s\033[0m' "$1"; }
rojo()   { printf '\033[31m%s\033[0m' "$1"; }

# probar <id> <descripcion> <esperado> <observado>
probar() {
    local id="$1" desc="$2" esp="$3" obs="$4"
    if [ "$esp" = "$obs" ]; then
        PASADAS=$((PASADAS+1)); printf '  %-8s %-52s %s\n' "$id" "$desc" "$(verde "OK  ($obs)")"
    else
        FALLIDAS=$((FALLIDAS+1)); printf '  %-8s %-52s %s\n' "$id" "$desc" "$(rojo "FALLA esperado=$esp observado=$obs")"
    fi
}

codigo()  { curl -s -o /dev/null -w '%{http_code}' "$@"; }
# Extrae el token anti-CSRF del formulario de una página.
token()   { curl -s -b "$1" -c "$1" "$2" | grep -o 'value="[a-f0-9]\{64\}"' | head -1 | sed 's/value="//;s/"//'; }
contiene(){ if curl -s "$@" | grep -qF "$TEXTO"; then echo si; else echo no; fi; }

echo "== Librería · matriz de pruebas =="
echo "   destino: $BASE_URL"
echo

echo "-- Autenticación y sesión (RF-01, RF-02) --"
probar PR-01 "Visitante en /libros es redirigido a login" 302 "$(codigo "$BASE_URL/libros")"
probar PR-02 "GET /login responde" 200 "$(codigo "$BASE_URL/login")"
probar PR-03 "GET /registro responde" 200 "$(codigo "$BASE_URL/registro")"
probar PR-04 "Ruta inexistente da 404, no 500" 404 "$(codigo "$BASE_URL/no-existe")"

TA=$(curl -s -c "$JA" "$BASE_URL/login" | grep -o 'value="[a-f0-9]\{64\}"' | head -1 | sed 's/value="//;s/"//')
probar PR-05 "POST /login sin token CSRF es rechazado" 403 \
    "$(codigo -X POST -d "email=$ADMIN_EMAIL&password=$ADMIN_PASS" "$BASE_URL/login")"
probar PR-06 "Contraseña incorrecta devuelve 401" 401 \
    "$(codigo -b "$JA" -c "$JA" -X POST -d "_csrf=$TA&email=$ADMIN_EMAIL&password=contrasena-incorrecta" "$BASE_URL/login")"
probar PR-07 "Correo inexistente devuelve 401 (mismo mensaje)" 401 \
    "$(codigo -b "$JA" -c "$JA" -X POST -d "_csrf=$TA&email=no.existe@ejemplo.com&password=$ADMIN_PASS" "$BASE_URL/login")"
probar PR-08 "Login del Administrador (302)" 302 \
    "$(codigo -b "$JA" -c "$JA" -X POST -d "_csrf=$TA&email=$ADMIN_EMAIL&password=$ADMIN_PASS" "$BASE_URL/login")"

echo
echo "-- Autorización por rol (RF-11, RNF-01) --"
for ruta in /panel /usuarios /autores /generos /categorias /formatos /conceptos /libros/nuevo; do
    probar PR-09 "Admin accede a $ruta" 200 "$(codigo -b "$JA" "$BASE_URL$ruta")"
done

if [ -n "$LECTOR_EMAIL" ] && [ -n "$LECTOR_PASS" ]; then
    TL=$(curl -s -c "$JL" "$BASE_URL/login" | grep -o 'value="[a-f0-9]\{64\}"' | head -1 | sed 's/value="//;s/"//')
    probar PR-10 "Login del lector (302)" 302 \
        "$(codigo -b "$JL" -c "$JL" -X POST -d "_csrf=$TL&email=$LECTOR_EMAIL&password=$LECTOR_PASS" "$BASE_URL/login")"
    probar PR-11 "Lector ve el catálogo" 200 "$(codigo -b "$JL" "$BASE_URL/libros")"
    probar PR-12 "Lector ve el detalle de un libro" 200 "$(codigo -b "$JL" "$BASE_URL/libros/1")"
    for ruta in /usuarios /panel /libros/nuevo /autores /generos; do
        probar PR-13 "Lector recibe 403 en $ruta" 403 "$(codigo -b "$JL" "$BASE_URL$ruta")"
    done
    TL2=$(token "$JL" "$BASE_URL/libros")
    probar PR-14 "Lector no puede borrar por POST directo" 403 \
        "$(codigo -b "$JL" -X POST -d "_csrf=$TL2" "$BASE_URL/libros/1/eliminar")"
else
    echo "  (PR-10..14 omitidas: falta LECTOR_EMAIL / LECTOR_PASS)"
fi

echo
echo "-- Búsqueda y parametrización (RF-05, RNF-02) --"
TEXTO="Normalizacion practica"
probar PR-15 "Búsqueda por ISBN exacto encuentra el libro" si \
    "$(contiene -b "$JA" "$BASE_URL/libros?q=978-607-32-2345-6")"
TEXTO="&lt;script&gt;"
probar PR-16 "Un <script> en la búsqueda se muestra escapado" si \
    "$(contiene -b "$JA" --get --data-urlencode 'q=<script>alert(1)</script>' "$BASE_URL/libros")"
TEXTO="<script>alert"
probar PR-17 "…y no aparece como script ejecutable" no \
    "$(contiene -b "$JA" --get --data-urlencode 'q=<script>alert(1)</script>' "$BASE_URL/libros")"
probar PR-18 "Carga de inyección SQL no rompe la consulta" 200 \
    "$(codigo -b "$JA" --get --data-urlencode "q=' OR 1=1; DROP TABLE libros; --" "$BASE_URL/libros")"
probar PR-19 "El catálogo sigue respondiendo después" 200 "$(codigo -b "$JA" "$BASE_URL/libros")"

echo
echo "-- Validación server-side del CRUD de libros (RF-06, RNF-03) --"
TF=$(token "$JA" "$BASE_URL/libros/nuevo")
ISBN="979-8-$(date +%s | tail -c 7)-1"
probar PR-20 "Alta válida con dos autores y un género" 302 \
    "$(codigo -b "$JA" -X POST -d "_csrf=$TF&isbn=$ISBN&titulo=Libro de prueba automatizada&anio_publicacion=2026&precio=123.45&stock=3&categoria_id=1&formato_id=1&autores=1&autores=2&generos=1" "$BASE_URL/libros")"
probar PR-21 "ISBN duplicado es rechazado" 400 \
    "$(codigo -b "$JA" -X POST -d "_csrf=$TF&isbn=$ISBN&titulo=Duplicado&precio=1&stock=1&categoria_id=1&formato_id=1&autores=1" "$BASE_URL/libros")"
probar PR-22 "Libro sin autor es rechazado" 400 \
    "$(codigo -b "$JA" -X POST -d "_csrf=$TF&isbn=979-8-000-0001-1&titulo=Sin autor&precio=1&stock=1&categoria_id=1&formato_id=1" "$BASE_URL/libros")"
probar PR-23 "Precio negativo es rechazado" 400 \
    "$(codigo -b "$JA" -X POST -d "_csrf=$TF&isbn=979-8-000-0002-1&titulo=Precio malo&precio=-10&stock=1&categoria_id=1&formato_id=1&autores=1" "$BASE_URL/libros")"
probar PR-24 "Stock negativo es rechazado" 400 \
    "$(codigo -b "$JA" -X POST -d "_csrf=$TF&isbn=979-8-000-0003-1&titulo=Stock malo&precio=1&stock=-4&categoria_id=1&formato_id=1&autores=1" "$BASE_URL/libros")"
probar PR-25 "ISBN con formato inválido es rechazado" 400 \
    "$(codigo -b "$JA" -X POST -d "_csrf=$TF&isbn=no-es-un-isbn&titulo=ISBN malo&precio=1&stock=1&categoria_id=1&formato_id=1&autores=1" "$BASE_URL/libros")"
probar PR-26 "Año fuera de rango es rechazado" 400 \
    "$(codigo -b "$JA" -X POST -d "_csrf=$TF&isbn=979-8-000-0004-1&titulo=Anio malo&anio_publicacion=99&precio=1&stock=1&categoria_id=1&formato_id=1&autores=1" "$BASE_URL/libros")"
probar PR-27 "Categoría inexistente es rechazada por la FK" 400 \
    "$(codigo -b "$JA" -X POST -d "_csrf=$TF&isbn=979-8-000-0005-1&titulo=FK mala&precio=1&stock=1&categoria_id=999999&formato_id=1&autores=1" "$BASE_URL/libros")"

echo
echo "-- Administrador único (RF-11) --"
TU=$(token "$JA" "$BASE_URL/usuarios/nuevo")
probar PR-28 "Crear un segundo Administrador es rechazado" 409 \
    "$(codigo -b "$JA" -X POST -d "_csrf=$TU&nombre=Segundo Admin&email=segundo.admin.prueba@ejemplo.com&password=Prueba1234&rol=admin" "$BASE_URL/usuarios")"
TEXTO="Ya existe un Administrador"
probar PR-29 "…con un mensaje explicativo" si \
    "$(contiene -b "$JA" -X POST -d "_csrf=$TU&nombre=Otro&email=otro.admin.prueba@ejemplo.com&password=Prueba1234&rol=admin" "$BASE_URL/usuarios")"
probar PR-30 "Contraseña débil es rechazada" 400 \
    "$(codigo -b "$JA" -X POST -d "_csrf=$TU&nombre=Debil&email=debil.prueba@ejemplo.com&password=abc&rol=lector" "$BASE_URL/usuarios")"
probar PR-31 "Correo mal formado es rechazado" 400 \
    "$(codigo -b "$JA" -X POST -d "_csrf=$TU&nombre=Correo&email=esto-no-es-correo&password=Prueba1234&rol=lector" "$BASE_URL/usuarios")"

echo
echo "-- Cabeceras y sesión (RNF-01) --"
CAB=$(curl -s -D- -o /dev/null -b "$JA" "$BASE_URL/libros")
probar PR-32 "Cabecera X-Content-Type-Options: nosniff" si "$(echo "$CAB" | grep -qi 'nosniff' && echo si || echo no)"
probar PR-33 "Cabecera X-Frame-Options: DENY" si "$(echo "$CAB" | grep -qi 'X-Frame-Options: DENY' && echo si || echo no)"
probar PR-34 "Content-Security-Policy presente" si "$(echo "$CAB" | grep -qi 'Content-Security-Policy' && echo si || echo no)"
probar PR-35 "No se anuncia X-Powered-By" no "$(echo "$CAB" | grep -qi 'X-Powered-By' && echo si || echo no)"
COOKIE=$(curl -s -D- -o /dev/null "$BASE_URL/login" | grep -i 'set-cookie')
probar PR-36 "Cookie de sesión HttpOnly" si "$(echo "$COOKIE" | grep -qi 'HttpOnly' && echo si || echo no)"
probar PR-37 "Cookie de sesión SameSite=Lax" si "$(echo "$COOKIE" | grep -qi 'SameSite=Lax' && echo si || echo no)"

echo
echo "-- Subida de imágenes (RF-09, RNF-01) --"
# Fixtures generados al vuelo: no se versionan archivos de prueba maliciosos.
printf '<?php system($_GET["c"]); ?>'          > "$TMP/falsa.png"   # PHP con nombre .png
printf '#!/bin/sh\necho hola\n'               > "$TMP/script.sh"   # ejecutable
printf '%%PDF-1.4 documento'                   > "$TMP/doc.pdf"     # PDF
head -c 3145728 /dev/urandom                   > "$TMP/enorme.png"  # 3 MB
# PNG real mínimo (1x1 px) construido a partir de su representación en base64.
printf 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==' \
    | base64 --decode > "$TMP/real.png"

TIMG=$(token "$JA" "$BASE_URL/imagenes/nuevo/1")
subir() { curl -s -b "$JA" -X POST -F "_csrf=$TIMG" -F "imagen=@$1;type=$2" \
              -F "texto_alternativo=${3:-Imagen de prueba}" -o /dev/null -w '%{http_code}' \
              "$BASE_URL/imagenes/1"; }

probar PR-40 "PHP renombrado a .png: rechazado por la firma" 400 "$(subir "$TMP/falsa.png" image/png)"
probar PR-41 "Ejecutable .sh con MIME falseado: rechazado"    400 "$(subir "$TMP/script.sh" image/png)"
probar PR-42 "PDF: tipo no permitido"                          400 "$(subir "$TMP/doc.pdf" application/pdf)"
probar PR-43 "Archivo de 3 MB: supera el límite de 2 MB"      400 "$(subir "$TMP/enorme.png" image/png)"
probar PR-44 "Sin texto alternativo: rechazado"                400 \
    "$(curl -s -b "$JA" -X POST -F "_csrf=$TIMG" -F "imagen=@$TMP/real.png;type=image/png" \
           -o /dev/null -w '%{http_code}' "$BASE_URL/imagenes/1")"
probar PR-45 "Subida sin token CSRF: rechazada"                403 \
    "$(curl -s -b "$JA" -X POST -F "imagen=@$TMP/real.png;type=image/png" -F "texto_alternativo=x" \
           -o /dev/null -w '%{http_code}' "$BASE_URL/imagenes/1")"
probar PR-46 "PNG válido con texto alternativo: aceptado"     302 "$(subir "$TMP/real.png" image/png)"

echo
echo "-- HTML bien formado (RNF-10) --"
# Estas pruebas existen porque un comentario de plantilla mal cerrado llegó a
# imprimirse como HTML, con una etiqueta script sin cerrar que dejaba la página
# en blanco. El servidor devolvía 200 y la página contenía los textos esperados,
# así que ninguna prueba de código de estado lo detectó: sólo se vio al abrirla
# en un navegador. Se comprueba la FORMA del documento, no sólo su contenido.
#
# Las públicas se piden SIN sesión: con sesión de admin, /login redirige y
# devolvería un cuerpo vacío.
publicas="/login /registro"
privadas="/libros /libros/1 /panel /usuarios /autores /conceptos"

# Imprime la primera línea que no esté en blanco.
primera_linea() { grep -m1 -v '^[[:space:]]*$'; }

malas_doctype=""
malas_cierre=""
malas_script=""

revisar_pagina() {   # $1 = ruta, $2 = jar o vacío
    local cuerpo
    if [ -n "$2" ]; then cuerpo=$(curl -s -b "$2" "$BASE_URL$1"); else cuerpo=$(curl -s "$BASE_URL$1"); fi

    [ "$(printf '%s\n' "$cuerpo" | primera_linea)" = "<!DOCTYPE html>" ] \
        || malas_doctype="$malas_doctype $1"

    printf '%s' "$cuerpo" | tail -c 40 | grep -q '</html>' \
        || malas_cierre="$malas_cierre $1"

    local abiertos cerrados
    abiertos=$(printf '%s' "$cuerpo" | grep -o '<script' | wc -l | tr -d ' ')
    cerrados=$(printf '%s' "$cuerpo" | grep -o '</script>' | wc -l | tr -d ' ')
    [ "$abiertos" = "$cerrados" ] || malas_script="$malas_script $1($abiertos/$cerrados)"
}

for pagina in $publicas; do revisar_pagina "$pagina" ""; done
for pagina in $privadas; do revisar_pagina "$pagina" "$JA"; done

probar PR-47 "Toda página empieza por <!DOCTYPE html>"        "" "$malas_doctype"
probar PR-48 "Etiquetas <script> balanceadas"                 "" "$malas_script"
probar PR-49 "Toda página cierra con </html>"                 "" "$malas_cierre"

echo
echo "-- Cierre de sesión (RF-03) --"
probar PR-38 "GET /logout redirige" 302 "$(codigo -b "$JA" -c "$JA" "$BASE_URL/logout")"
probar PR-39 "Tras cerrar sesión, /usuarios ya no es accesible" 302 "$(codigo -b "$JA" "$BASE_URL/usuarios")"

echo
echo "======================================================================"
printf 'Pruebas ejecutadas: %s · %s · %s\n' \
    "$((PASADAS+FALLIDAS))" "$(verde "$PASADAS pasadas")" \
    "$([ "$FALLIDAS" -eq 0 ] && verde '0 fallidas' || rojo "$FALLIDAS fallidas")"
echo "======================================================================"
[ "$FALLIDAS" -eq 0 ]
