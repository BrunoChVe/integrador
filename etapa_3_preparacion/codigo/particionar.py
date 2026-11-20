"""Particion anti-fuga — PARTICIONAR: asigna cada bloque a train, valid o test.

POR QUE NO POR ESCANEO (docs/decisiones/0024, que sustituye a 0007). La 0007
partia por escaneo cuando habia tres escaneos de ate que no se tocaban. Ya no es
asi: las pasadas del vehiculo se solapan, y el mismo id de bloque —el mismo
suelo, los mismos postes— aparece en varios escaneos (en ate, 24 de 106). Partir
por escaneo pondria ese poste en train desde una pasada y en test desde otra, y
la metrica mediria memoria de geometria, no generalizacion.

LA UNIDAD ES EL SUELO, NO LA PASADA. Los bloques se agrupan en superceldas de
`particion.supercelda_m` sobre la misma rejilla UTM absoluta, y cada supercelda
va ENTERA a una particion, con todos los escaneos que la cubren. Asi ningun
punto del terreno puede estar en dos particiones. El orden de las superceldas
se baraja con `project.random_seed` y se reparten por puntos de nucleo hasta
acercarse a `particion.proporciones`.

LO QUE QUEDA. Dos bloques vecinos de superceldas distintas comparten el anillo
de contexto de `tiling.buffer_m`. El anillo se excluye de la perdida y de toda
metrica (0007), y la etapa cuenta cuantos pares de borde hay para que el numero
este a la vista.

Salidas:
  datos/final/particion.csv     la tabla final: una fila por bloque y su particion
  reportes/particion.json       tamano de cada particion y las comprobaciones

Ejecutar: python codigo/particionar.py   (desde etapa_3_preparacion/)
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.config import PATHS, param  # noqa: E402

PARTICIONES = ("train", "valid", "test")


def main() -> int:
    sc = float(param("particion.supercelda_m"))
    prop = {k: float(param(f"particion.proporciones.{k}")) for k in PARTICIONES}
    if abs(sum(prop.values()) - 1.0) > 1e-9:
        print(f"[X] particion.proporciones suma {sum(prop.values())}, no 1")
        return 1
    bloque_m = float(param("tiling.bloque_m"))
    por_lado = sc / bloque_m
    if abs(por_lado - round(por_lado)) > 1e-9:
        print(f"[X] particion.supercelda_m ({sc}) no es multiplo de tiling.bloque_m "
              f"({bloque_m}): un bloque quedaria partido entre dos superceldas")
        return 1
    por_lado = int(round(por_lado))

    with open(PATHS.bloques / "bloque_index.csv", encoding="utf-8") as fh:
        filas = sorted(csv.DictReader(fh), key=lambda r: r["path"])

    # Supercelda por indice entero de bloque, no por coordenada en coma flotante.
    def supercelda(r) -> str:
        return (f"s_{int(r['bloque_ix']) // por_lado}_"
                f"{int(r['bloque_iy']) // por_lado}")

    peso = defaultdict(int)
    for r in filas:
        peso[supercelda(r)] += int(r["points_core"])
    total = sum(peso.values())

    rng = np.random.default_rng(int(param("project.random_seed")))
    orden = [sorted(peso)[i] for i in rng.permutation(len(peso))]
    asignada, acumulado = {}, {k: 0 for k in PARTICIONES}
    for s in orden:
        # A la particion que mas lejos esta de su objetivo, en fraccion de puntos.
        k = max(PARTICIONES, key=lambda p: prop[p] - acumulado[p] / total)
        asignada[s] = k
        acumulado[k] += peso[s]

    salida = [{"path": r["path"], "scan": r["scan"], "distrito": r["distrito"],
               "bloque_ix": r["bloque_ix"], "bloque_iy": r["bloque_iy"],
               "supercelda": supercelda(r), "points_core": r["points_core"],
               "particion": asignada[supercelda(r)]} for r in filas]
    PATHS.final.mkdir(parents=True, exist_ok=True)
    with open(PATHS.final / "particion.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(salida[0].keys()))
        w.writeheader()
        w.writerows(salida)

    # --- comprobaciones ------------------------------------------------------
    # 1. Ningun suelo en dos particiones: un id de bloque, una particion.
    por_celda = defaultdict(set)
    for r in salida:
        por_celda[(int(r["bloque_ix"]), int(r["bloque_iy"]))].add(r["particion"])
    celdas_en_varias = sum(1 for v in por_celda.values() if len(v) > 1)
    # 2. Pares de bloques vecinos (8-vecindad) en particiones distintas: solo
    #    comparten el anillo de contexto, que no entra en perdida ni metrica.
    celda_part = {c: next(iter(v)) for c, v in por_celda.items()}
    borde = 0
    for (ix, iy), p in celda_part.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                q = celda_part.get((ix + dx, iy + dy))
                if (dx, dy) > (0, 0) and q is not None and q != p:
                    borde += 1

    resumen = {}
    for k in PARTICIONES:
        sel = [r for r in salida if r["particion"] == k]
        pts = sum(int(r["points_core"]) for r in sel)
        resumen[k] = {
            "superceldas": sum(1 for v in asignada.values() if v == k),
            "bloques": len(sel),
            "points_core": pts,
            "fraccion_puntos": round(pts / total, 4),
            "escaneos": len({r["scan"] for r in sel}),
            "distritos": sorted({r["distrito"] for r in sel}),
        }
    informe = {
        "estrategia": "superceldas espaciales sobre la rejilla UTM absoluta",
        "supercelda_m": sc,
        "proporciones_objetivo": prop,
        "particiones": resumen,
        "comprobaciones": {
            "ids_de_bloque_en_varias_particiones": celdas_en_varias,
            "pares_vecinos_en_particiones_distintas": borde,
            "sin_fuga_de_suelo": celdas_en_varias == 0,
        },
    }
    (PATHS.reports / "particion.json").write_text(
        json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")

    for k, v in resumen.items():
        print(f"  {k:<6}{v['superceldas']:>4} superceldas {v['bloques']:>5} bloques "
              f"{v['fraccion_puntos']:>7.1%} de los puntos  {v['distritos']}")
    print(f"  ids de bloque en varias particiones: {celdas_en_varias}  ·  "
          f"pares de borde: {borde}")
    return 0 if celdas_en_varias == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
