"""Rasgos de Sonata (PTv3 congelado) para todos los bloques de `datos/crudo/etiquetado/`, a disco.

El cuaderno `cuadernos/sonata_mlp.ipynb` entrena una cabeza MLP sobre estos rasgos
y no vuelve a tocar ni las nubes ni la GPU del backbone. Por bloque se guarda,
en `datos/intermedio/cache/sonata/<bloque>/`:

    F.npy       (n, D) float16, memmap   rasgos de Sonata proyectados con PCA
    P.npy       (n, 3) float32           coordenada del voxel, relativa a `origen`
    hag.npy     (n,)   float32           altura sobre el suelo
    Y.npy       (n,)   uint8             0 fondo · 5 poste_bt · 12 poste_mt
    origen.npy  (3,)   float64           esquina UTM del bloque
    meta.json

Solo entran los voxeles con HAG en [0.3, 40] m —ni suelo ni ruido lejano
pueden ser poste—, pero Sonata ve la tesela ENTERA, suelo incluido: el
contexto de un pie de poste es el suelo. Los rasgos salen a 1088 dimensiones
(los tres niveles mas profundos del codificador concatenados, ver
`sonata_rasgos.py`) y se proyectan a `DIM_PCA` con una PCA ajustada sobre una
muestra del primer bloque de entrenamiento: sin eso, 12 bloques pesaban mas de
100 GB y no cabian en el cuaderno. La PCA se guarda en `datos/intermedio/cache/sonata/pca.npz`
y es la misma para todos los bloques.

    python codigo/postes/preparar_sonata.py             # los que falten
    python codigo/postes/preparar_sonata.py --forzar
    python codigo/postes/preparar_sonata.py PACHAP01MT0108202501_b_1493_43239
    python codigo/postes/preparar_sonata.py --solo-etiquetas   # Y.npy con los recortes de hoy

Si un recorte es mas nuevo que la cache de su bloque, se recalcula solo Y.npy
(los rasgos no dependen de las etiquetas) sin pasar por la GPU.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from postes_datos import (CACHE_SONATA, HAG_MAX, HAG_MIN, altura_sobre_suelo,  # noqa: E402
                          etiquetar, etiquetas_desactualizadas, inventario, leer, NOMBRE_CLASE)
from sonata_rasgos import GRID, cargar_modelo, normales, recorrer, voxelizar  # noqa: E402

CACHE = CACHE_SONATA
DIM_PCA = 256
MUESTRA_PCA = 200_000
# La PCA se ajusto sobre b_1464_43339 (el mas grande y variado) y TODAS las caches
# estan proyectadas con ella: cambiar este bloque obliga a --forzar sobre todo.
BLOQUE_PCA = "AVP01MT2611202501_b_1464_43339"
SEMILLA = 0


def ruta_bloque(bloque: str) -> Path:
    return CACHE / bloque


def preparar_nube(fila: dict):
    t0 = time.perf_counter()
    xyz, rgb, _ = leer(Path(fila["nube"]))
    n_crudo = len(xyz)
    P, C = voxelizar(xyz, rgb / 255.0)
    del xyz, rgb
    N = normales(P)
    H = altura_sobre_suelo(P)
    print(f"  {fila['bloque']} ({fila['escaneo'][:6]}): {n_crudo:,} puntos -> "
          f"{len(P):,} voxeles de {GRID} m ({time.perf_counter() - t0:.0f} s)")
    return n_crudo, P, C, N, H


def ajustar_pca(modelo, fila: dict) -> dict:
    """PCA sobre una muestra al azar de los voxeles utiles de un bloque."""
    print(f"PCA: muestra de {MUESTRA_PCA:,} voxeles de {fila['bloque']}")
    _, P, C, N, H = preparar_nube(fila)
    keep = (H >= HAG_MIN) & (H <= HAG_MAX)
    rng = np.random.default_rng(SEMILLA)
    quiero = np.zeros(len(P), dtype=bool)
    idx_keep = np.flatnonzero(keep)
    quiero[rng.choice(idx_keep, min(MUESTRA_PCA, len(idx_keep)), replace=False)] = True
    trozos = []

    def guardar(idx, f):
        m = quiero[idx]
        if m.any():
            trozos.append(f[torch.from_numpy(np.flatnonzero(m)).cuda()].cpu())

    recorrer(modelo, P, C, N, guardar)
    F = torch.cat(trozos).float()
    media = F.mean(0)
    U, S, V = torch.pca_lowrank(F - media, q=DIM_PCA, center=False, niter=4)
    var_total = float(((F - media) ** 2).sum() / (len(F) - 1))
    var_expl = float((S ** 2).sum() / (len(F) - 1)) / var_total
    print(f"  {F.shape[1]} -> {DIM_PCA} dimensiones, varianza explicada {var_expl:.3f}")
    pca = {"media": media.numpy(), "componentes": V.numpy(),      # (D_in, DIM_PCA)
           "dim_entrada": int(F.shape[1]), "dim": DIM_PCA, "varianza_explicada": var_expl,
           "bloque": fila["bloque"], "muestra": int(len(F))}
    CACHE.mkdir(exist_ok=True)
    np.savez(CACHE / "pca.npz", **pca)
    return pca


def preparar_bloque(modelo, fila: dict, pca: dict) -> None:
    n_crudo, P, C, N, H = preparar_nube(fila)
    keep = (H >= HAG_MIN) & (H <= HAG_MAX)
    pos = np.full(len(P), -1, dtype=np.int64)       # voxel -> fila en la cache
    pos[keep] = np.arange(int(keep.sum()))
    n = int(keep.sum())
    Y, puntos = etiquetar(P[keep], {"BT": fila.get("BT"), "MT": fila.get("MT")})

    carpeta = ruta_bloque(fila["bloque"])
    carpeta.mkdir(parents=True, exist_ok=True)
    F = np.lib.format.open_memmap(carpeta / "F.npy", mode="w+", dtype="f2", shape=(n, pca["dim"]))
    media = torch.from_numpy(pca["media"]).cuda()
    comp = torch.from_numpy(pca["componentes"]).cuda()
    escritos = np.zeros(n, dtype=bool)

    def guardar(idx, f):
        m = keep[idx]
        if not m.any():
            return
        fila_cache = pos[idx[m]]
        z = ((f[torch.from_numpy(np.flatnonzero(m)).cuda()].float() - media) @ comp).half()
        orden = np.argsort(fila_cache)      # escritura ordenada: el memmap lo agradece
        F[fila_cache[orden]] = z.cpu().numpy()[orden]
        escritos[fila_cache] = True

    t0 = time.perf_counter()
    recorrer(modelo, P, C, N, guardar)
    F.flush()
    del F
    origen = np.floor(P[keep].min(axis=0))
    np.save(carpeta / "P.npy", (P[keep] - origen).astype("f4"))
    np.save(carpeta / "hag.npy", H[keep].astype("f4"))
    np.save(carpeta / "Y.npy", Y)
    np.save(carpeta / "origen.npy", origen)
    meta = {"bloque": fila["bloque"], "escaneo": fila["escaneo"], "grid_m": GRID,
            "puntos_crudos": int(n_crudo), "voxeles": int(len(P)), "voxeles_conservados": n,
            "sin_rasgo": int((~escritos).sum()),
            "puntos_recorte": puntos,
            "voxeles_por_clase": {NOMBRE_CLASE[int(c)]: int((Y == c).sum()) for c in np.unique(Y)},
            "dim": pca["dim"], "segundos_sonata": round(time.perf_counter() - t0, 1)}
    (carpeta / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"     {n:,} voxeles utiles, clases {meta['voxeles_por_clase']}, "
          f"{meta['sin_rasgo']} sin rasgo, Sonata {meta['segundos_sonata']} s "
          f"-> {carpeta} ({n * pca['dim'] * 2 / 1e9:.1f} GB)")


def hecho(bloque: str) -> bool:
    return (ruta_bloque(bloque) / "meta.json").exists()


def reetiquetar(fila: dict) -> None:
    """Solo las etiquetas: Y.npy con los recortes actuales, sin volver a pasar
    Sonata. P.npy esta en metros relativos al origen del bloque."""
    carpeta = ruta_bloque(fila["bloque"])
    P = np.load(carpeta / "P.npy").astype("f8") + np.load(carpeta / "origen.npy")
    Y, puntos = etiquetar(P, {"BT": fila.get("BT"), "MT": fila.get("MT")})
    np.save(carpeta / "Y.npy", Y)
    meta = json.loads((carpeta / "meta.json").read_text(encoding="utf-8"))
    meta.update({"puntos_recorte": puntos,
                 "voxeles_por_clase": {NOMBRE_CLASE[int(c)]: int((Y == c).sum()) for c in np.unique(Y)},
                 "etiquetas_actualizadas": time.strftime("%Y-%m-%d %H:%M")})
    (carpeta / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"  {fila['bloque']}: etiquetas nuevas {meta['voxeles_por_clase']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bloques", nargs="*")
    ap.add_argument("--forzar", action="store_true", help="rehacer rasgos y etiquetas aunque esten")
    ap.add_argument("--solo-etiquetas", action="store_true",
                    help="recalcular solo Y.npy de los bloques ya en cache; no toca la GPU")
    a = ap.parse_args()
    torch.manual_seed(SEMILLA)

    inv = inventario()
    if a.bloques:
        inv = inv[inv["bloque"].isin(a.bloques)]
    ya = inv["bloque"].map(hecho)
    pendientes = inv if a.forzar else inv[~ya]
    # Los que ya estan pero tienen un recorte mas nuevo que su cache: solo etiquetas.
    viejas = inv[ya & (a.solo_etiquetas | inv.apply(
        lambda f: etiquetas_desactualizadas(f.to_dict(), ruta_bloque(f["bloque"]) / "meta.json"), axis=1))]
    if a.forzar:
        viejas = viejas.iloc[0:0]
    if a.solo_etiquetas:
        pendientes = pendientes.iloc[0:0]
    print(f"{len(inv)} bloques, {len(pendientes)} por preparar, {len(viejas)} por reetiquetar -> {CACHE}")
    for _, fila in viejas.iterrows():
        reetiquetar(fila.to_dict())
    if pendientes.empty:
        return

    print("Cargando Sonata...")
    modelo = cargar_modelo()
    ruta_pca = CACHE / "pca.npz"
    if ruta_pca.exists() and not (a.forzar and not a.bloques):
        with np.load(ruta_pca) as z:
            pca = {k: (z[k].item() if z[k].ndim == 0 else z[k]) for k in z.files}
        print(f"PCA ya ajustada: {pca['dim_entrada']} -> {pca['dim']} "
              f"(varianza {pca['varianza_explicada']:.3f}, sobre {pca['bloque']})")
    else:
        todo = inventario()
        fila_pca = todo[todo["bloque"] == BLOQUE_PCA]
        if fila_pca.empty:
            fila_pca = pendientes.iloc[[0]]
        pca = ajustar_pca(modelo, fila_pca.iloc[0].to_dict())

    for _, fila in pendientes.iterrows():
        preparar_bloque(modelo, fila.to_dict(), pca)
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
