"""Convierte los resúmenes JSON de k6 en RESULTADOS.md y dos gráficas SVG.

Toma la mediana de las repeticiones de cada escenario. Sólo biblioteca estándar.
"""
import json
import re
import statistics
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RES = AQUI / "resultados"
GRAF = AQUI / "graficas"

CATEGORIAS = {"rp": "Proxy inverso (1 backend)", "lb": "Balanceador (3 backends)", "gw": "API gateway (JWT + límite)"}


def leer(archivo: Path) -> dict:
    m = json.loads(archivo.read_text())["metrics"]
    cuenta = lambda n: m.get(n, {}).get("values", {}).get("count", 0)
    d = m["http_req_duration"]["values"]
    total = m["http_reqs"]["values"]["count"]
    return {
        "rps": m["http_reqs"]["values"]["rate"],
        "p50": d["med"], "p95": d["p(95)"], "p99": d["p(99)"],
        "total": total,
        "errores": total - cuenta("st_2xx"),
        "inst": [cuenta(f"inst_b{i}") for i in (1, 2, 3)],
    }


def mediana(corridas: list[dict]) -> dict:
    r = {k: statistics.median(c[k] for c in corridas) for k in ("rps", "p50", "p95", "p99", "errores", "total")}
    r["inst"] = [sum(c["inst"][i] for c in corridas) for i in range(3)]
    return r


def recursos(cat: str, nombre: str) -> str:
    f = RES / f"{cat}_{nombre}_recursos.txt"
    if not f.exists():
        return "—"
    filas = []
    for linea in f.read_text().split("\n"):
        if linea.strip():
            cont, cpu, mem = linea.split(";")
            filas.append(f"{cont.removeprefix('bench-')} {cpu} · {mem.split('/')[0].strip()}")
    return "<br>".join(filas)


def barras_svg(titulo: str, datos: list[tuple[str, float]], unidad: str, archivo: Path) -> None:
    alto_fila, izq, ancho_barra = 26, 230, 420
    maximo = max(v for _, v in datos) or 1
    alto = 50 + alto_fila * len(datos)
    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{izq + ancho_barra + 110}" height="{alto}" font-family="sans-serif" font-size="13">',
        f'<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="12" y="24" font-size="15" font-weight="bold" fill="#222">{titulo}</text>',
    ]
    for i, (etiqueta, valor) in enumerate(datos):
        y = 40 + i * alto_fila
        w = max(1, ancho_barra * valor / maximo)
        partes += [
            f'<text x="{izq - 8}" y="{y + 15}" text-anchor="end" fill="#333">{etiqueta}</text>',
            f'<rect x="{izq}" y="{y + 3}" width="{w:.1f}" height="17" rx="3" fill="#2f6f5e"/>',
            f'<text x="{izq + w + 6:.1f}" y="{y + 16}" fill="#333">{valor:,.1f} {unidad}</text>',
        ]
    partes.append("</svg>")
    archivo.write_text("\n".join(partes))


def main() -> None:
    GRAF.mkdir(exist_ok=True)
    grupos: dict[tuple[str, str], list[dict]] = {}
    for f in sorted(RES.glob("*_r*.json")):
        m = re.fullmatch(r"(rp|lb|gw)_(.+)_r\d+\.json", f.name)
        if m:
            grupos.setdefault((m[1], m[2]), []).append(leer(f))
    med = {k: mediana(v) for k, v in grupos.items()}
    base = med.get(("rp", "directo"))

    out = ["# Resultados del benchmark", "",
           "Generado por `analizar.py`. Mediana de las repeticiones; latencias en ms; "
           "CPU y memoria muestreadas a media corrida con `docker stats` (100 % = un núcleo).", ""]
    rps_graf, p95_graf = [], []

    for cat, titulo in CATEGORIAS.items():
        filas = [(n, v) for (c, n), v in med.items() if c == cat]
        if not filas:
            continue
        filas.sort(key=lambda x: -x[1]["rps"])
        out += [f"## {titulo}", ""]
        cab = "| Herramienta | RPS | p50 | p95 | p99 | Errores |"
        sep = "|---|---:|---:|---:|---:|---:|"
        if cat == "rp" and base:
            cab += " RPS vs. directo | +p50 vs. directo |"; sep += "---:|---:|"
        if cat == "lb":
            cab += " Reparto b1 / b2 / b3 |"; sep += "---|"
        cab += " CPU · memoria |"; sep += "---|"
        out += [cab, sep]
        for n, v in filas:
            fila = f"| {n} | {v['rps']:,.0f} | {v['p50']:.2f} | {v['p95']:.2f} | {v['p99']:.2f} | {v['errores']:.0f} |"
            if cat == "rp" and base:
                fila += f" {100 * v['rps'] / base['rps']:.0f} % | {v['p50'] - base['p50']:+.2f} |"
            if cat == "lb":
                t = sum(v["inst"]) or 1
                fila += " " + " / ".join(f"{100 * x / t:.1f} %" for x in v["inst"]) + " |"
            fila += f" {recursos(cat, n)} |"
            out.append(fila)
            rps_graf.append((f"[{cat}] {n}", v["rps"]))
            p95_graf.append((f"[{cat}] {n}", v["p95"]))
        out.append("")

    fo = sorted(RES.glob("fo_*.json"))
    if fo:
        out += ["## Conmutación por error (b3 cae a los 10 s y vuelve a los 20 s, 30 s de carga)", "",
                "| Balanceador | Peticiones | Fallidas | % fallidas | p99 | Reparto b1 / b2 / b3 |",
                "|---|---:|---:|---:|---:|---|"]
        for f in fo:
            v = leer(f)
            t = sum(v["inst"]) or 1
            out.append(f"| {f.stem[3:]} | {v['total']:,} | {v['errores']:,} | "
                       f"{100 * v['errores'] / max(v['total'], 1):.3f} % | {v['p99']:.1f} | "
                       + " / ".join(f"{100 * x / t:.1f} %" for x in v["inst"]) + " |")
        out.append("")

    mem = RES / "memoria_reposo.txt"
    if mem.exists():
        out += ["## Memoria en reposo", "", "| Contenedor | Memoria |", "|---|---:|"]
        for linea in mem.read_text().split("\n"):
            if linea.strip():
                cont, _, uso = linea.split(";")
                out.append(f"| {cont.removeprefix('bench-')} | {uso.split('/')[0].strip()} |")
        out.append("")

    fun = RES / "funcional.txt"
    if fun.exists():
        out += ["## Pruebas funcionales de seguridad de los gateways", "", "```", fun.read_text().strip(), "```", ""]

    if rps_graf:
        barras_svg("Peticiones por segundo (más es mejor)", rps_graf, "rps", GRAF / "rps.svg")
        barras_svg("Latencia p95 en ms (menos es mejor)", p95_graf, "ms", GRAF / "p95.svg")
        out += ["## Gráficas", "", "![RPS](graficas/rps.svg)", "", "![p95](graficas/p95.svg)", ""]

    (AQUI / "RESULTADOS.md").write_text("\n".join(out))
    print("RESULTADOS.md escrito")


if __name__ == "__main__":
    main()
