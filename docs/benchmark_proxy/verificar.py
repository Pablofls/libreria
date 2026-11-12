"""Pruebas funcionales de seguridad de cada API gateway, antes de medir.

Corre dentro del contenedor `auth` (está en la red del banco). Para cada
gateway comprueba: sin token -> 401, token válido -> 200, expirado, firma
ajena y alg=none -> 401, y que /limitado devuelve 429 al pasar de 10 r/s.
Sólo biblioteca estándar.
"""
import concurrent.futures as cf
import urllib.error
import urllib.request
from pathlib import Path

GATEWAYS = {
    "nginx + auth_request": "http://172.28.0.20:82",
    "Kong": "http://172.28.0.25:8000",
    "Envoy (jwt_authn)": "http://172.28.0.23:8082",
}

tokens = dict(
    linea.split("=", 1) for linea in Path("/generado/tokens.env").read_text().split()
)


def estado(url: str, token: str | None = None) -> int:
    peticion = urllib.request.Request(url)
    if token:
        peticion.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(peticion, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return 0


CASOS = [
    ("sin token", None, 401),
    ("token válido", "TOKEN_VALIDO", 200),
    ("token expirado", "TOKEN_EXPIRADO", 401),
    ("firma con otro secreto", "TOKEN_MALA_FIRMA", 401),
    ("alg=none", "TOKEN_ALG_NONE", 401),
]

fallos = 0
for nombre, base in GATEWAYS.items():
    print(f"== {nombre} ({base})")
    for caso, clave, esperado in CASOS:
        obtenido = estado(base + "/", tokens.get(clave) if clave else None)
        ok = obtenido == esperado
        fallos += not ok
        print(f"  {'OK   ' if ok else 'FALLO'} {caso:<24} esperado {esperado}  obtenido {obtenido}")
    with cf.ThreadPoolExecutor(25) as hilos:
        codigos = list(hilos.map(lambda _: estado(base + "/limitado", tokens["TOKEN_VALIDO"]), range(50)))
    n429 = codigos.count(429)
    ok = n429 > 0 and codigos.count(200) > 0
    fallos += not ok
    print(f"  {'OK   ' if ok else 'FALLO'} ráfaga de 50 a /limitado (10 r/s)   200={codigos.count(200)}  429={n429}")

print(f"\nTotal de fallos: {fallos}")
