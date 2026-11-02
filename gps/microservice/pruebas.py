# -*- coding: utf-8 -*-
"""Pruebas del rastreo de entregas (entregas.py), SIN red ni servicios.

    python3 pruebas.py

El servicio de pedidos y OSRM se sustituyen por falsos: lo que se prueba es lo
que decide este servicio — código de rastreo, autorización delegada, fases de
la entrega en función del tiempo y la conversación por WebSocket.
"""
import io
import json
import os
import sys
import urllib.error
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import entregas as e                                              # noqa: E402

fallos = 0
total = 0


def comprobar(nombre, condicion, detalle=""):
    global fallos, total
    total += 1
    if not condicion:
        fallos += 1
    print("  {}  {} {}".format("ok  " if condicion else "FALLO", nombre, detalle))


def lanza(funcion, *args):
    try:
        funcion(*args)
    except e.RastreoError as error:
        return str(error)
    return None


# Ruta recta de ~2 km por el centro, en lugar de pedirla a OSRM.
RUTA = [(25.6714, -100.3093), (25.6800, -100.3093), (25.6800, -100.3000), (25.6890, -100.3000)]


def pedido(estado="pagado", hace=0, anio=None):
    momento = datetime.now(timezone.utc) - timedelta(seconds=hace)
    creado = momento.replace(year=anio) if anio else momento
    historial = [{"estado": "pendiente", "cambiado_en": creado.isoformat()}]
    if estado in ("pagado", "enviado"):
        historial.append({"estado": "pagado", "cambiado_en": momento.isoformat()})
    return {"id": 125, "usuario_id": 7, "estado": estado, "creado_en": creado.isoformat(),
            "historial": historial, "lineas": []}


print("1. Código de rastreo")
comprobar("formato", e.codigo_para(125, 2026) == "LIB-MTY-2026-000125")
comprobar("ida y vuelta", e.parsear_codigo("LIB-MTY-2026-000125") == (2026, 125))
comprobar("minúsculas y espacios", e.parsear_codigo("  lib-mty-2026-000125 ") == (2026, 125))
for malo in ("", None, "LIB-MTY-2026-125", "LIB-GDL-2026-000125", "LIB-MTY-2026-000000",
             "LIB-MTY-2026-000125; DROP", "../orders/1"):
    comprobar("rechaza {!r}".format(malo), lanza(e.parsear_codigo, malo) is not None)


print("2. Autorización delegada en pedidos")


class Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def abridor(codigo=200, cuerpo=None, error=None):
    vistos = []

    def abrir(req, timeout):
        vistos.append(req)
        if error:
            raise error
        if codigo != 200:
            raise urllib.error.HTTPError(req.full_url, codigo, "x", {}, None)
        return Respuesta(json.dumps(cuerpo).encode())
    abrir.vistos = vistos
    return abrir


ab = abridor(cuerpo=pedido())
datos = e.consultar_pedido(125, "Bearer abc.def.ghi", ab)
comprobar("200 devuelve el pedido", datos["id"] == 125)
comprobar("reenvía el JWT tal cual", ab.vistos[0].get_header("Authorization") == "Bearer abc.def.ghi")
comprobar("pide GET /orders/<id>", ab.vistos[0].full_url.endswith("/orders/125"))
comprobar("sin token no llama a pedidos", lanza(e.consultar_pedido, 125, "", abridor()) is not None)
comprobar("401 -> pide iniciar sesión", "sesión" in lanza(e.consultar_pedido, 125, "Bearer x", abridor(401)))
ajeno = lanza(e.consultar_pedido, 125, "Bearer x", abridor(404))
comprobar("404 (ajeno o inexistente) -> mismo mensaje", "ningún pedido tuyo" in ajeno)
comprobar("pedidos caído -> no disponible",
          "no está disponible" in lanza(e.consultar_pedido, 125, "Bearer x",
                                        abridor(error=urllib.error.URLError("x"))))


print("3. Estado del pedido y momento del pago")
anio = datetime.now(timezone.utc).year
comprobar("pagado -> epoch del pago", abs(e.momento_de_pago(pedido(hace=50), anio) -
                                          (datetime.now(timezone.utc).timestamp() - 50)) < 2)
comprobar("enviado también se rastrea", lanza(e.momento_de_pago, pedido("enviado"), anio) is None)
comprobar("pendiente -> sin envío", "no está pagado" in lanza(e.momento_de_pago, pedido("pendiente"), anio))
comprobar("cancelado -> sin envío", "cancelado" in lanza(e.momento_de_pago, pedido("cancelado"), anio))
comprobar("año del código distinto -> no es ese pedido",
          lanza(e.momento_de_pago, pedido(), anio - 1) is not None)


print("4. Fases de la entrega en el tiempo")
acum = e.acumulados(RUTA)
D = 180
fases = [(0, e.CONFIRMADO), (9, e.CONFIRMADO), (15, e.PREPARANDO), (31, e.ENVIADO),
         (100, e.EN_RUTA), (179, e.EN_RUTA), (180, e.ENTREGADO), (5000, e.ENTREGADO)]
for t, esperado in fases:
    comprobar("t={:>4}s -> {}".format(t, esperado), e.estado_en(RUTA, acum, t, D)["estado"] == esperado)
quieto = e.estado_en(RUTA, acum, 20, D)
comprobar("preparando: en el almacén y parado",
          (quieto["lat"], quieto["lon"]) == RUTA[0] and quieto["speed"] == 0)
final = e.estado_en(RUTA, acum, D, D)
comprobar("Entregado = último punto de la ruta", (final["lat"], final["lon"]) == RUTA[-1])
comprobar("Entregado: progreso 1 y nada restante", final["progreso"] == 1 and final["restante_m"] == 0)
previos = [e.estado_en(RUTA, acum, t, D)["progreso"] for t in range(0, 200, 5)]
comprobar("el progreso nunca retrocede", previos == sorted(previos))
medio = e.estado_en(RUTA, acum, 105, D)
comprobar("a medio camino ~50 %", 0.45 < medio["progreso"] < 0.55, str(medio["progreso"]))
comprobar("recorrido termina en la posición actual",
          e.recorrido_hasta(RUTA, medio)[-1] == [medio["lat"], medio["lon"]])
comprobar("ETA baja con el tiempo", e.estado_en(RUTA, acum, 60, D)["eta_s"] == 120)


print("5. Ruta por pedido")
llamadas = []


def osrm_falso(origen, destino):
    llamadas.append(destino)
    return [origen, destino]


r1 = e.ruta_del_pedido(9001, osrm_falso)
r2 = e.ruta_del_pedido(9001, osrm_falso)
comprobar("sale del almacén", r1[0] == e.ALMACEN)
comprobar("se calcula una sola vez por pedido", r1 is r2 and len(llamadas) == 1)
e.ruta_del_pedido(9002, osrm_falso)
comprobar("otro pedido, otro destino", llamadas[0] != llamadas[1])
e._rutas.clear()
comprobar("mismo pedido, mismo destino tras reiniciar",
          e.ruta_del_pedido(9001, osrm_falso)[-1] == llamadas[0])


def osrm_caido(origen, destino):
    raise OSError("sin red")


comprobar("OSRM caído -> error legible", "OSRM" in lanza(e.ruta_del_pedido, 9999, osrm_caido))


print("6. Conversación por WebSocket")


class WsFalso:
    def __init__(self, vueltas):
        self.enviados, self.cerrado, self.vueltas = [], False, vueltas

    def send(self, texto):
        self.enviados.append(json.loads(texto))

    def receive(self, timeout=None):
        self.vueltas -= 1
        if self.vueltas < 0:
            raise ConnectionError("el cliente cerró")
        return None

    def close(self):
        self.cerrado = True


original_consultar, original_ruta = e.consultar_pedido, e.ruta_del_pedido
e.ruta_del_pedido = lambda pid: RUTA

e.consultar_pedido = lambda pid, auth: pedido(hace=100)
ws = WsFalso(3)
e.atender(ws, "LIB-MTY-{}-000125".format(anio), "Bearer x")
tipos = [m["type"] for m in ws.enviados]
comprobar("snapshot y luego updates", tipos == ["snapshot", "update", "update", "update"], str(tipos))
comprobar("snapshot trae la ruta y lo recorrido",
          len(ws.enviados[0]["ruta"]) == len(RUTA) and len(ws.enviados[0]["recorrido"]) >= 2)
comprobar("snapshot con código y pedido",
          ws.enviados[0]["code"] == "LIB-MTY-{}-000125".format(anio) and ws.enviados[0]["pedido_id"] == 125)
comprobar("el cliente se quita de activos al cerrar", ws not in e.activos)

e.consultar_pedido = lambda pid, auth: pedido(hace=10_000)
ws = WsFalso(3)
e.atender(ws, "LIB-MTY-{}-000125".format(anio), "Bearer x")
comprobar("pedido viejo: Entregado sin más updates",
          ws.enviados[0]["estado"] == e.ENTREGADO and len(ws.enviados) == 1)


def denegar(pid, auth):
    raise e.RastreoError("No hay ningún pedido tuyo con ese código.")


e.consultar_pedido = denegar
ws = WsFalso(3)
e.atender(ws, "LIB-MTY-{}-000126".format(anio), "Bearer x")
comprobar("pedido ajeno: error y cierre, sin ruta",
          ws.enviados == [{"type": "error", "message": "No hay ningún pedido tuyo con ese código."}]
          and ws.cerrado)

ws = WsFalso(3)
e.atender(ws, "cualquier-cosa", "Bearer x")
comprobar("código inválido: error y cierre", ws.enviados[0]["type"] == "error" and ws.cerrado)

# Revalidación: a los 60 s pedidos dice 401 (logout) y se corta.
reloj = [1000.0]
respuestas = [pedido(hace=40)]


def consultar_y_luego_401(pid, auth):
    if respuestas:
        return respuestas.pop()
    raise e.RastreoError("Tu sesión no es válida o venció: vuelve a iniciar sesión.")


class WsConReloj(WsFalso):
    def receive(self, timeout=None):
        reloj[0] += 30
        return super().receive(timeout)


e.consultar_pedido = consultar_y_luego_401
ws = WsConReloj(10)
e.atender(ws, "LIB-MTY-{}-000125".format(anio), "Bearer x",
          ahora=lambda: reloj[0])
comprobar("revalida y corta si la sesión se cerró",
          ws.enviados[-1]["type"] == "error" and ws.cerrado)

e.consultar_pedido, e.ruta_del_pedido = original_consultar, original_ruta

print("\n{} comprobaciones, {} fallos".format(total, fallos))
sys.exit(1 if fallos else 0)
