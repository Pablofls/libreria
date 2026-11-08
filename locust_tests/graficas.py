"""
locust_tests/graficas.py — graficas y tabla de resultados a partir de los CSV
que deja ejecutar.sh en evidencias/<perfil>/.

    .venv/bin/python graficas.py            # todos los perfiles que tengan CSV
    .venv/bin/python graficas.py stress     # solo uno

Por perfil escribe en evidencias/<perfil>/:
    <perfil>_carga.png     usuarios, RPS y % de errores en el tiempo
    <perfil>_p95.png       p95 (ventana de ~10 s) de cada ruta de negocio
    <perfil>_salud.png     p95 de las rutas de salud
y en evidencias/:
    comparativa_p95.png    p95 final por destino y perfil (rutas de negocio)
    tabla_resultados.md    una fila por perfil x solicitud, con los numeros
                           tal cual salen de <perfil>_stats.csv

No inventa datos: si falta un CSV, el perfil se marca como no disponible.
"""

import csv
import os
import sys
from collections import defaultdict

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
EVID = os.path.join(AQUI, 'evidencias')
# spike_1: primera corrida del spike (con 3 errores de conexion), conservada.
PERFILES = ['smoke', 'load', 'stress', 'spike_1', 'spike', 'soak', 'quiebre']
UMBRAL_P95 = 1000.0
UMBRAL_ERR = 5.0


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def leer(ruta):
    with open(ruta, newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def es_salud(nombre):
    return '/health' in nombre or nombre.endswith('/library/login')


def graficar_perfil(perfil):
    base = os.path.join(EVID, perfil, perfil)
    hist = base + '_stats_history.csv'
    if not os.path.isfile(hist):
        print('{}: sin {}'.format(perfil, os.path.basename(hist)))
        return
    filas = leer(hist)
    if not filas:
        return
    t0 = int(filas[0]['Timestamp'])

    agg = [f for f in filas if f['Name'] == 'Aggregated']
    t = [int(f['Timestamp']) - t0 for f in agg]
    usuarios = [int(f['User Count']) for f in agg]
    rps = [_f(f['Requests/s']) or 0 for f in agg]
    fps = [_f(f['Failures/s']) or 0 for f in agg]
    err = [100 * b / a if a else 0 for a, b in zip(rps, fps)]

    fig, ejes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    ejes[0].step(t, usuarios, where='post', color='#2a6f4e')
    ejes[0].set_ylabel('usuarios')
    ejes[1].plot(t, rps, color='#1f4e79', label='RPS total')
    ejes[1].plot(t, fps, color='#a3283a', label='fallos/s')
    ejes[1].set_ylabel('peticiones/s')
    ejes[1].legend(loc='upper left')
    ejes[2].plot(t, err, color='#a3283a')
    ejes[2].axhline(UMBRAL_ERR, ls='--', color='gray', lw=1)
    ejes[2].set_ylabel('% errores (ventana)')
    ejes[2].set_xlabel('segundos desde el inicio')
    fig.suptitle('Perfil {}: carga, RPS y errores'.format(perfil))
    fig.tight_layout()
    fig.savefig(base + '_carga.png', dpi=110)
    plt.close(fig)

    series = defaultdict(lambda: ([], []))
    for f in filas:
        if f['Name'] == 'Aggregated':
            continue
        p95 = _f(f['95%'])
        if p95 is None:
            continue
        xs, ys = series[f['Name']]
        xs.append(int(f['Timestamp']) - t0)
        ys.append(p95)

    for sufijo, filtro, titulo in (
            ('p95', lambda n: not es_salud(n), 'rutas de negocio'),
            ('salud', es_salud, 'rutas de salud')):
        nombres = sorted(n for n in series if filtro(n))
        if not nombres:
            continue
        fig, eje = plt.subplots(figsize=(10, 5.5))
        for n in nombres:
            xs, ys = series[n]
            eje.plot(xs, ys, label=n, lw=1.4,
                     ls='--' if n.startswith('[monolito]') else '-')
        eje.axhline(UMBRAL_P95, ls=':', color='gray', lw=1, label='umbral 1000 ms')
        eje.set_ylabel('p95 ventana ~10 s (ms)')
        eje.set_xlabel('segundos desde el inicio')
        eje.set_title('Perfil {}: p95 de {}'.format(perfil, titulo))
        eje.legend(fontsize=7, loc='upper left')
        fig.tight_layout()
        fig.savefig('{}_{}.png'.format(base, sufijo), dpi=110)
        plt.close(fig)
    print('{}: graficas escritas'.format(perfil))


def resumen(perfil):
    ruta = os.path.join(EVID, perfil, perfil + '_stats.csv')
    return leer(ruta) if os.path.isfile(ruta) else None


def tabla_y_comparativa(perfiles):
    lineas = ['| Perfil | Solicitud | Peticiones | RPS | p50 ms | p95 ms | Errores % | Umbral |',
              '|---|---|---|---|---|---|---|---|']
    comparativa = defaultdict(dict)
    for p in perfiles:
        filas = resumen(p)
        if filas is None:
            lineas.append('| {} | — | no disponible: no hay CSV | | | | | |'.format(p))
            continue
        for f in filas:
            n = int(f['Request Count'] or 0)
            fallos = int(f['Failure Count'] or 0)
            errores = 100 * fallos / n if n else 0
            p95 = _f(f['95%'])
            ok = (p95 is not None and p95 <= UMBRAL_P95 and errores <= UMBRAL_ERR)
            lineas.append('| {} | {} | {} | {:.2f} | {} | {} | {:.1f} | {} |'.format(
                p, f['Name'], n, _f(f['Requests/s']) or 0, f['50%'], f['95%'],
                errores, 'cumple' if ok else 'INCUMPLE'))
            if f['Name'] != 'Aggregated' and not es_salud(f['Name']) and p95 is not None:
                comparativa[f['Name']][p] = p95
    with open(os.path.join(EVID, 'tabla_resultados.md'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lineas) + '\n')

    if comparativa:
        nombres = sorted(comparativa)
        presentes = [p for p in perfiles if any(p in comparativa[n] for n in nombres)]
        ancho = 0.8 / max(len(presentes), 1)
        fig, eje = plt.subplots(figsize=(11, 5.5))
        for i, p in enumerate(presentes):
            xs = [k + i * ancho for k in range(len(nombres))]
            eje.bar(xs, [comparativa[n].get(p, 0) for n in nombres], ancho, label=p)
        eje.axhline(UMBRAL_P95, ls=':', color='gray', lw=1)
        eje.set_xticks([k + ancho * (len(presentes) - 1) / 2 for k in range(len(nombres))])
        eje.set_xticklabels(nombres, rotation=25, ha='right', fontsize=7)
        eje.set_ylabel('p95 de toda la ejecucion (ms)')
        eje.set_title('p95 por destino y perfil (rutas de negocio)')
        eje.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(EVID, 'comparativa_p95.png'), dpi=110)
        plt.close(fig)
    print('tabla_resultados.md y comparativa_p95.png escritas')


if __name__ == '__main__':
    elegidos = sys.argv[1:] or PERFILES
    for p in elegidos:
        graficar_perfil(p)
    tabla_y_comparativa(PERFILES)
