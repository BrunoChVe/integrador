"""Etapa 3.5 (format) — BLOQUES: corta los escaneos en bloques deterministas.

Por que cortar es la primera transformacion de verdad y no un detalle:

  * Un escaneo llega a 177 M puntos. Como float64 xyz+rgb son ~8 GB contra
    15.6 GB de RAM, antes de que exista ningun KD-tree. Nada de lo que viene
    despues se puede escribir "por escaneo".

DOS REJILLAS, NO UNA (docs/decisiones/0018). Hasta la v5 esta etapa producia
teselas de 40 m y la tesela era a la vez unidad de almacenamiento, de
anotacion y de entrenamiento, con el argumento de que asi las tres no podian
discrepar. Salia caro: un vano de MT mide 50-70 m, asi que a 40 m sale
cortado SIEMPRE y hay que decidir su clase dos o tres veces sin ver nunca la
catenaria entera. Ahora esta etapa produce BLOQUES de `tiling.bloque_m`
(200 m), que son la unidad de almacenamiento y de ANOTACION, y la tesela de
entrenamiento se corta del bloque ya anotado en la etapa dataset, sin
materializarse en disco.

La rejilla se ancla a multiplos de `bloque_m` en UTM absoluto, asi que el
mismo id de bloque cubre siempre el mismo suelo, en todos los escaneos y en
todas las ejecuciones. Cada bloque lleva un anillo de contexto de `buffer_m`:
un rasgo calculado junto al borde veria si no un vecindario truncado y
dejaria costuras visibles. Nucleo y anillo se recalculan del id al cargar,
asi que el anillo no cuesta nada de almacenar.

LA SALIDA ESPEJA A datos/crudo. Cada escaneo escribe en la misma ruta que ocupa
en el crudo, grupo y distrito incluidos, para que interim se navegue igual que
la entrega. Antes era una carpeta plana por escaneo: el nombre basta como
clave —`scan_folders` revienta si dos coinciden— pero eso resuelve la
IDENTIDAD, no la NAVEGACION, y con 16 escaneos y mas distritos por llegar una
lista plana no dice de que distrito es cada uno. Ver `ruta_de_escaneo`.

Salida: datos/intermedio/01_bloques/<grupo>/<distrito>/<escaneo>/b_<ix>_<iy>.laz
        (+ bloque_index.csv, con grupo y distrito por fila)
Ejecutar: python codigo/bloques.py   (desde etapa_3_preparacion/)
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.config import PATHS, param  # noqa: E402
from common.anotacion import nombre_bloque  # noqa: E402
from common.io_cloud import (Cloud, find_laz, read_las_chunks,  # noqa: E402
                            ruta_de_escaneo, scan_of, write_las)

# Registro de paso por disco. Elegido para que un trozo se pueda anadir
# al archivo temporal de un bloque con una escritura y releerse con un
# solo fromfile().
REC = np.dtype([
    ("x", "f8"), ("y", "f8"), ("z", "f8"),
    ("intensity", "u2"), ("red", "u1"), ("green", "u1"), ("blue", "u1"),
    ("ring", "u1"), ("gps_time", "f8"),
])

FLUSH_BUDGET_MB = 512      # buffered points held in RAM before spilling
KEY_STRIDE = 1 << 21       # packs (ix, iy) into one int64 for searchsorted
                           # membership tests; 2^21 cells = 83,000 km per axis
READ_CHUNK = 4_000_000


def bloque_id(xy: np.ndarray, size: float) -> np.ndarray:
    return np.floor(xy / size).astype(np.int64)


def plan_bloques(catalog_rows, size: float, limit: int, selection: str
                 ) -> Dict[str, List[Tuple[int, int]]]:
    """Elige que bloques materializar, por escaneo.

    La seleccion usa solo la extension declarada en la cabecera de cada
    archivo —no se lee ni un punto—, asi que planificar sobre 421 M puntos
    cuesta milisegundos.

    `limit = 0` significa TODOS los bloques, que es el objetivo desde 0018:
    el acelerador existia por falta de disco, y ese motivo ya no esta.
    """
    weight: Dict[str, Dict[Tuple[int, int], float]] = defaultdict(lambda: defaultdict(float))
    for r in catalog_rows:
        scan = r["scan"]
        ix0, iy0 = int(np.floor(r["min_x"] / size)), int(np.floor(r["min_y"] / size))
        ix1, iy1 = int(np.floor(r["max_x"] / size)), int(np.floor(r["max_y"] / size))
        n_cells = max(1, (ix1 - ix0 + 1) * (iy1 - iy0 + 1))
        share = r["point_count"] / n_cells
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                weight[scan][(ix, iy)] += share

    plan: Dict[str, List[Tuple[int, int]]] = {}
    for scan, cells in weight.items():
        items = sorted(cells.items(), key=lambda kv: -kv[1])
        if selection == "first":
            items = sorted(cells.items())
        elif selection == "random":
            rng = np.random.default_rng(param("project.random_seed"))
            order = rng.permutation(len(items))
            items = [sorted(cells.items())[i] for i in order]
        if limit:
            items = items[:limit]
        plan[scan] = [c for c, _ in items]
    return plan


class BloqueSpiller:
    """Acumula puntos por bloque y los vuelca a disco cuando aprieta la RAM."""

    def __init__(self, scratch: Path):
        self.scratch = scratch
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.buf: Dict[Tuple[int, int], List[np.ndarray]] = defaultdict(list)
        self.bytes = 0
        self.counts: Dict[Tuple[int, int], int] = defaultdict(int)

    def add(self, cell: Tuple[int, int], rec: np.ndarray) -> None:
        self.buf[cell].append(rec)
        self.bytes += rec.nbytes
        self.counts[cell] += len(rec)
        if self.bytes > FLUSH_BUDGET_MB * 2 ** 20:
            self.flush()

    def flush(self) -> None:
        for cell, parts in self.buf.items():
            if not parts:
                continue
            path = self.scratch / f"{cell[0]}_{cell[1]}.bin"
            with open(path, "ab") as fh:
                np.concatenate(parts).tofile(fh)
        self.buf.clear()
        self.bytes = 0

    def read(self, cell: Tuple[int, int]) -> np.ndarray:
        path = self.scratch / f"{cell[0]}_{cell[1]}.bin"
        if not path.exists():
            return np.empty(0, dtype=REC)
        return np.fromfile(path, dtype=REC)


def main() -> int:
    t0 = time.time()
    size = float(param("tiling.bloque_m"))
    buffer_m = float(param("tiling.buffer_m"))
    min_points = int(param("tiling.min_points"))
    limit = int(param("tiling.max_bloques_por_escaneo"))
    selection = str(param("tiling.bloque_selection"))
    epsg = int(param("project.crs_epsg"))

    # El bloque tiene que ser multiplo entero de la tesela, o el borde de una
    # tesela cruzaria un bloque y la etapa dataset no podria cortarla. Se
    # comprueba aqui, al principio, y no al final de 4 horas de proceso.
    tesela_m = float(param("tiling.tesela_m"))
    por_lado = size / tesela_m
    if abs(por_lado - round(por_lado)) > 1e-9:
        print(f"[X] tiling.bloque_m ({size}) no es multiplo de "
              f"tiling.tesela_m ({tesela_m}): da {por_lado:.4f} teselas por lado")
        return 1
    if buffer_m <= 0:
        print(f"[X] tiling.buffer_m ({buffer_m}) tiene que ser positivo: sin "
              "anillo, un poste justo en el borde sale partido entre dos "
              "bloques y no se puede anotar entero en ninguno de los dos")
        return 1

    catalog_csv = PATHS.catalogo / "scan_catalog.csv"
    if not catalog_csv.exists():
        print("[X] Ejecuta antes codigo/seleccionar.py")
        return 1
    with open(catalog_csv, encoding="utf-8") as fh:
        catalog = [{k: (float(v) if k.startswith(("min_", "max_", "density", "footprint"))
                        else int(v) if k in ("point_count", "file_size_bytes")
                        else v)
                    for k, v in row.items()} for row in csv.DictReader(fh)]

    plan = plan_bloques(catalog, size, limit, selection)
    # Se procesan en el orden en que `select.scan_groups` declara los grupos.
    # Antes se perdia: `find_laz` acaba con un `sorted()` por ruta, y
    # `Grupo01...` va antes que `Grupo03...` alfabeticamente, asi que el grupo
    # declarado primero salia ultimo. Importa porque esta etapa borra su
    # carpeta al arrancar: el orden decide cuanto hay que esperar para volver a
    # tener disponible lo que ya estaba anotandose.
    orden_grupo = {g: i for i, g in enumerate(param("select.scan_groups"))}

    def prioridad(escaneo: str) -> tuple:
        rel = carpeta_de.get(escaneo)
        return (orden_grupo.get(rel.parts[0], 99) if rel else 99, escaneo)
    total_planned = sum(len(v) for v in plan.values())
    print(f"Rejilla de bloques de {size:.0f} m (+{buffer_m:.0f} m de anillo), "
          f"{int(round(por_lado))}x{int(round(por_lado))} teselas de "
          f"{tesela_m:.0f} m — {total_planned} bloques planificados en "
          f"{len(plan)} escaneos "
          f"[{selection}, limite {limit or 'ninguno'}/escaneo]")

    out_root = PATHS.bloques
    if out_root.exists():
        shutil.rmtree(out_root)     # a stage owns its output directory
    out_root.mkdir(parents=True, exist_ok=True)

    laz_files = find_laz(PATHS.raw, param("select.scan_groups"), param("select.scans"))
    by_scan: Dict[str, List[Path]] = defaultdict(list)
    # Donde va cada escaneo DENTRO de la salida: la misma ruta que ocupa en
    # datos/crudo, grupo y distrito incluidos, para que interim se navegue igual
    # que el crudo. Ver `ruta_de_escaneo`.
    carpeta_de: Dict[str, Path] = {}
    for p in laz_files:
        escaneo = scan_of(p)
        by_scan[escaneo].append(p)
        carpeta_de[escaneo] = ruta_de_escaneo(p, PATHS.raw)

    index_rows = []
    for scan in sorted(plan, key=prioridad):
        cells = plan[scan]
        wanted = set(cells)
        if not wanted:
            continue
        wanted_list = sorted(wanted)
        wanted_keys = np.array([ix * KEY_STRIDE + iy for ix, iy in wanted_list],
                               dtype=np.int64)
        scratch = out_root / f".scratch_{scan}"   # plano: es temporal
        spiller = BloqueSpiller(scratch)
        read_pts = 0
        print(f"\n  {scan}: repartiendo {len(by_scan[scan])} archivos en {len(wanted)} bloques")

        for path in by_scan[scan]:
            for chunk in read_las_chunks(path, READ_CHUNK):
                read_pts += chunk.n
                # Un punto pertenece a un bloque si cae en su nucleo O en su
                # anillo. En vez de probar cada punto contra cada bloque,
                # se desplazan las coordenadas +/- el anillo y se toma
                # la union de los ids resultantes: 4 celdas como maximo.
                base = bloque_id(chunk.xyz[:, :2], size)
                lo = bloque_id(chunk.xyz[:, :2] - buffer_m, size)
                hi = bloque_id(chunk.xyz[:, :2] + buffer_m, size)
                rec = np.empty(chunk.n, dtype=REC)
                rec["x"], rec["y"], rec["z"] = chunk.xyz[:, 0], chunk.xyz[:, 1], chunk.xyz[:, 2]
                for name in ("intensity", "red", "green", "blue", "ring", "gps_time"):
                    rec[name] = chunk.attrs[name]

                # Membership is resolved by packing (ix, iy) into one int64 and
                # binary-searching the sorted set of wanted keys. Looping over
                # bloques instead would cost O(points x bloques): at 421 M points
                # and four corner lookups that is ~2e10 comparisons per scan,
                # which is minutes-to-hours. This is O(points log bloques).
                # A point whose lo and hi cell agree on an axis must only be
                # emitted once for that axis, otherwise every interior point
                # is written four times and deduplicated later: correct, but
                # four times the scratch I/O.
                dx_differs = lo[:, 0] != hi[:, 0]
                dy_differs = lo[:, 1] != hi[:, 1]
                for dx in (0, 1):
                    for dy in (0, 1):
                        eligible = np.ones(chunk.n, dtype=bool)
                        if dx:
                            eligible &= dx_differs
                        if dy:
                            eligible &= dy_differs
                        if not eligible.any():
                            continue
                        cx = np.where(eligible, hi[:, 0] if dx else lo[:, 0], -1 << 40)
                        cy = np.where(eligible, hi[:, 1] if dy else lo[:, 1], 0)
                        keys = cx * KEY_STRIDE + cy
                        pos = np.searchsorted(wanted_keys, keys)
                        np.clip(pos, 0, len(wanted_keys) - 1, out=pos)
                        hit = wanted_keys[pos] == keys
                        if not hit.any():
                            continue
                        # Group the hits by bloque in one pass instead of one
                        # boolean mask per bloque.
                        order = np.argsort(pos[hit], kind="stable")
                        hit_idx = np.flatnonzero(hit)[order]
                        bloque_pos = pos[hit_idx]
                        bounds = np.flatnonzero(np.diff(bloque_pos)) + 1
                        for part in np.split(hit_idx, bounds):
                            if part.size:
                                spiller.add(wanted_list[pos[part[0]]], rec[part])
                del rec, base, lo, hi
        spiller.flush()

        for cell in sorted(wanted):
            rec = spiller.read(cell)
            if len(rec) == 0:
                continue
            # No de-duplication needed. Each corner lookup is gated on the
            # lo/hi cell actually differing on that axis, so a point is emitted
            # exactly once per distinct bloque it belongs to. An np.unique() here
            # would lexsort a 9-field structured array over millions of
            # records, which measured as the dominant cost of the whole stage
            # — far more than reading and routing all 421 M points.
            if len(rec) < min_points:
                continue
            xyz = np.stack([rec["x"], rec["y"], rec["z"]], axis=1)
            cloud = Cloud(xyz, {k: rec[k] for k in
                                ("intensity", "red", "green", "blue", "ring", "gps_time")})
            x0, y0 = cell[0] * size, cell[1] * size
            core = ((xyz[:, 0] >= x0) & (xyz[:, 0] < x0 + size) &
                    (xyz[:, 1] >= y0) & (xyz[:, 1] < y0 + size))
            out = out_root / carpeta_de[scan] / f"{nombre_bloque(*cell)}.laz"
            write_las(out, cloud, epsg=epsg)
            index_rows.append({
                "scan": scan,
                # El grupo y el distrito salen de la ruta, no de un parseo del
                # nombre del escaneo: el prefijo `PACHAP` o `AVP` es una
                # convencion de quien entrega, no una garantia.
                "grupo": carpeta_de[scan].parts[0],
                "distrito": (carpeta_de[scan].parts[1]
                             if len(carpeta_de[scan].parts) >= 3 else ""),
                "bloque_ix": cell[0], "bloque_iy": cell[1],
                "path": out.relative_to(PATHS.root).as_posix(),
                "points_total": len(rec), "points_core": int(core.sum()),
                "min_x": x0, "min_y": y0, "bloque_m": size, "buffer_m": buffer_m,
                "min_z": float(xyz[:, 2].min()), "max_z": float(xyz[:, 2].max()),
                "density_core_pts_m2": round(float(core.sum()) / (size * size), 1),
            })
        shutil.rmtree(scratch, ignore_errors=True)
        print(f"    leidos {read_pts:,} puntos -> "
              f"{sum(1 for r in index_rows if r['scan'] == scan)} bloques escritos")

    if not index_rows:
        print("[X] Ningun bloque alcanzo tiling.min_points")
        return 1

    idx = PATHS.bloques / "bloque_index.csv"
    with open(idx, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(index_rows[0].keys()))
        w.writeheader()
        w.writerows(index_rows)

    stats = {
        "bloques": len(index_rows),
        "points_core": int(sum(r["points_core"] for r in index_rows)),
        "points_with_buffer": int(sum(r["points_total"] for r in index_rows)),
        "mean_core_density_pts_m2": round(
            float(np.mean([r["density_core_pts_m2"] for r in index_rows])), 1),
        "bloque_m": size, "tesela_m": tesela_m, "buffer_m": buffer_m,
    }
    # El tiempo de ejecucion se imprime pero NO se escribe en el json. Estuvo
    # (`elapsed_s`) y hacia que cada ejecucion produjera una huella distinta:
    # repetir la etapa con los mismos datos, codigo y parametros cambiaba el
    # dvc.lock, y la prueba de reproducibilidad —rehacer forzando y comprobar
    # que la anotacion queda identica— fallaba siempre.
    (PATHS.reports / "bloques.json").write_text(
        json.dumps(stats, indent=2), encoding="utf-8")
    print(f"\n  {stats['bloques']} bloques, {stats['points_core']:,} puntos de nucleo "
          f"({stats['points_with_buffer']:,} con anillo) en "
          f"{time.time() - t0:.0f}s")
    print(f"  Indice: {idx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
