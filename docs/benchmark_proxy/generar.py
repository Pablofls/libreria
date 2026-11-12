"""Genera el secreto JWT efímero del banco de pruebas, los tokens y las
configuraciones que lo necesitan (Kong, Envoy, validador).

Todo va a generado/, que está en .gitignore: el secreto vive sólo mientras
dura la corrida y nunca se versiona. Sólo biblioteca estándar.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from pathlib import Path

AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "generado"
EMISOR = "login-libreria"


def b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def firmar(cabecera: dict, cuerpo: dict, secreto: bytes) -> str:
    partes = b64url(json.dumps(cabecera).encode()) + "." + b64url(json.dumps(cuerpo).encode())
    if cabecera.get("alg") == "none":
        return partes + "."
    firma = hmac.new(secreto, partes.encode(), hashlib.sha256).digest()
    return partes + "." + b64url(firma)


def reclamos(exp_en: int) -> dict:
    ahora = int(time.time())
    return {
        "sub": "lector-bench", "user_id": 2, "role_id": 2, "rol": "lector",
        "iss": EMISOR, "iat": ahora, "exp": ahora + exp_en, "jti": uuid.uuid4().hex,
    }


def main() -> None:
    SALIDA.mkdir(exist_ok=True)
    secreto = secrets.token_urlsafe(48)
    clave = secreto.encode()
    hs256 = {"alg": "HS256", "typ": "JWT"}

    tokens = {
        "TOKEN_VALIDO": firmar(hs256, reclamos(6 * 3600), clave),
        "TOKEN_EXPIRADO": firmar(hs256, reclamos(-60), clave),
        "TOKEN_MALA_FIRMA": firmar(hs256, reclamos(3600), b"otro-secreto-que-no-es"),
        "TOKEN_ALG_NONE": firmar({"alg": "none", "typ": "JWT"}, reclamos(3600), clave),
    }
    (SALIDA / "tokens.env").write_text("".join(f"{k}={v}\n" for k, v in tokens.items()))
    (SALIDA / "auth.env").write_text(f"BENCH_JWT_SECRET={secreto}\n")

    plantillas = AQUI / "config"
    (SALIDA / "kong.yml").write_text(
        (plantillas / "kong.plantilla.yml").read_text().replace("__SECRETO__", secreto))
    (SALIDA / "envoy.yaml").write_text(
        (plantillas / "envoy.plantilla.yaml").read_text().replace("__JWK_K__", b64url(clave)))
    for f in SALIDA.iterdir():
        f.chmod(0o644)  # los contenedores leen como otro usuario; el secreto es efímero
    print("generado/ listo (secreto efímero, no versionado)")


if __name__ == "__main__":
    main()
