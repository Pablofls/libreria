#!/usr/bin/env python3
"""Genera docs/javadesktop/ENTREGA.pdf a partir de ENTREGA.md.

Formato de documento de Word: portada con el escudo, índice con números de
página y el cuerpo en Times 12 pt. Se arma en dos pasadas: la primera ubica
cada título en el PDF y la segunda escribe esos números en el índice. La
portada va en un PDF aparte y se une al final, para que el índice sea la
página 1, como en Word.

Requiere pandoc, Google Chrome, pdftotext y pdfunite (poppler). Uso, desde la
raíz del repo:
    python3 docs/javadesktop/pdf/generar.py
"""
import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
DOCS = AQUI.parent
RAIZ = DOCS.parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Datos de la portada.
MATERIA = "Integración de Aplicaciones"
TITULO = "Librería Online: cliente de escritorio en Java con rastreo GPS por WebSockets"
INTEGRANTES = ["Pablo Flores Rodríguez - 611194"]
LUGAR_FECHA = "San Pedro Garza García, 2 de noviembre de 2026"
INTEGRIDAD = "Afirmo que he realizado esta actividad con integridad académica."


def pagina(cuerpo, css):
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<link rel="stylesheet" href="{css.as_uri()}"></head><body>
{cuerpo}
</body></html>"""


def a_pdf(html_txt, destino, tmp):
    fuente = tmp / (destino.stem + ".html")
    fuente.write_text(html_txt, encoding="utf-8")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--allow-file-access-from-files", f"--print-to-pdf={destino}",
                    fuente.as_uri()], check=True, capture_output=True)


def portada():
    nombres = "".join(f"<p>{html.escape(n)}</p>" for n in INTEGRANTES)
    return f"""<section class="portada">
<p>UNIVERSIDAD DE MONTERREY</p>
<p>ESCUELA DE INGENIERÍA Y TECNOLOGÍAS</p>
<p class="bloque">{html.escape(MATERIA)}</p>
<img class="escudo" src="{(AQUI / 'escudo-udem.png').as_uri()}" alt="Escudo de la Universidad de Monterrey">
<p class="titulo">{html.escape(TITULO)}</p>
<div class="espacio"></div>
{nombres}
<p class="bloque">{html.escape(LUGAR_FECHA)}</p>
<p class="bloque">{html.escape(INTEGRIDAD)}</p>
</section>"""


def cuerpo_html():
    """ENTREGA.md a HTML, sin el encabezado (título, subtítulo y nota): va en la portada."""
    salida = subprocess.run(["pandoc", str(DOCS / "ENTREGA.md"), "-f", "gfm", "-t", "html5"],
                            check=True, capture_output=True, text=True).stdout
    salida = salida[salida.index("<h2"):]
    # Las imágenes se referencian desde docs/javadesktop/; el HTML vive en otro lado.
    salida = salida.replace('src="../../', f'src="{RAIZ.as_uri()}/')
    return salida


def titulos(cuerpo):
    return [(int(n), id_, re.sub(r"<[^>]+>", "", t).strip())
            for n, id_, t in re.findall(r'<h([23]) id="([^"]+)">(.*?)</h\1>', cuerpo, flags=re.S)]


def indice(entradas, paginas):
    filas = "".join(
        f'<li class="n{nivel - 1}"><a href="#{id_}">{html.escape(html.unescape(texto))}</a>'
        f'<span class="puntos"></span><span>{paginas.get(id_, "")}</span></li>'
        for nivel, id_, texto in entradas)
    return f'<section class="indice"><h2>Índice</h2><ol>{filas}</ol></section>'


def normal(texto):
    return re.sub(r"\s+", " ", texto).strip().lower()


def ubicar(pdf, entradas):
    """Página de cada título: el primer sitio donde aparece, en orden, a partir de la 2."""
    textos = [normal(t) for t in subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                                                check=True, capture_output=True,
                                                text=True).stdout.split("\f")]
    paginas, desde = {}, 1
    for _, id_, texto in entradas:
        buscado = normal(html.unescape(texto))[:28]
        for i in range(desde, len(textos)):
            if buscado in textos[i]:
                paginas[id_] = i + 1
                desde = i
                break
    return paginas


def main():
    for herramienta in ("pandoc", "pdftotext", "pdfunite"):
        if not shutil.which(herramienta):
            sys.exit(f"Falta {herramienta}")
    css = AQUI / "estilo.css"
    cuerpo = cuerpo_html()
    entradas = titulos(cuerpo)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        a_pdf(pagina(portada(), css), tmp / "portada.pdf", tmp)
        a_pdf(pagina(indice(entradas, {}) + cuerpo, css), tmp / "borrador.pdf", tmp)
        paginas = ubicar(tmp / "borrador.pdf", entradas)
        faltan = [texto for _, id_, texto in entradas if id_ not in paginas]
        if faltan:
            print("Sin página en el índice:", ", ".join(faltan))
        a_pdf(pagina(indice(entradas, paginas) + cuerpo, css), tmp / "cuerpo.pdf", tmp)
        destino = DOCS / "ENTREGA.pdf"
        subprocess.run(["pdfunite", str(tmp / "portada.pdf"), str(tmp / "cuerpo.pdf"),
                        str(destino)], check=True)
    print(f"{destino.relative_to(RAIZ)} listo")


if __name__ == "__main__":
    main()
