"""Validador de JWT para el patrón auth_request de nginx.

Reproduce la verificación de reclamos_jwt() de los servicios de la VM: HS256
fijo, firma, exp, iss y claims obligatorios. NO consulta Redis (la revocación
por jti añadiría un viaje de ida y vuelta más en la VM).
"""
import os

import jwt
from flask import Flask, request

SECRETO = os.environ["BENCH_JWT_SECRET"]
EMISOR = "login-libreria"

app = Flask(__name__)


@app.get("/verificar")
def verificar():
    cabecera = request.headers.get("Authorization", "")
    if not cabecera.startswith("Bearer "):
        return "", 401
    try:
        jwt.decode(
            cabecera[7:],
            SECRETO,
            algorithms=["HS256"],
            issuer=EMISOR,
            options={"require": ["exp", "iss", "sub", "jti"]},
        )
    except jwt.PyJWTError:
        return "", 401
    return "", 204
