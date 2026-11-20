"""Rasgos por voxel con Sonata (PointTransformerV3) congelado.

Lo unico de esta carpeta que necesita el entorno `F:\\venvs\\sonata` (torch con
CUDA, spconv, el repo de Sonata en F:\\venvs\\sonata_repo y CUDA_PATH apuntando a
F:\\venvs\\cuda_shim). Lo usa `preparar_sonata.py` para llenar `datos/intermedio/cache/sonata/`;
el cuaderno `cuadernos/sonata_mlp.ipynb` ya no toca el backbone, lee la cache.

Como se obtienen los rasgos (31-oct-2026, igual que en la prueba de concepto
`la prueba de concepto de oct-2026`):

  * La nube se reduce a voxeles de `GRID` = 0,08 m (un punto real por celda).
  * Sonata ve teselas de `TESELA` = 40 m con un anillo de `ANILLO` = 4 m, para
    que un poste en el borde tenga su contexto; solo se guardan los voxeles del
    nucleo de cada tesela.
  * Se concatenan los tres niveles mas profundos del codificador (1088
    dimensiones) y se normalizan; `preparar_sonata.py` los proyecta a 256 con
    una PCA ajustada sobre b_1464_43339.

Los pesos de Sonata son CC-BY-NC 4.0: uso academico, no comercial. Para el
producto habra que reentrenar o cambiar de backbone.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch
from scipy.spatial import cKDTree

sys.path.insert(0, r"F:\venvs\sonata_repo")
import sonata  # noqa: E402

GRID = 0.08      # m, voxel de entrada a Sonata
TESELA = 40.0    # m, lado de la tesela que ve el modelo de una vez
ANILLO = 4.0     # m, contexto alrededor de la tesela que no se guarda
# Una tesela con mas voxeles que esto se parte en cuatro. Medido el 5-nov-2026: la
# mas densa que cupo en la GPU de 8 GB tenia ~800 000 (b_1495_43240); una de
# b_1489_43236 (escaneo ...02, 72 M de puntos) tenia 1,18 M y pidio 9,6 GB. Con este
# valor ninguna tesela de los bloques ya en cache cambia.
MAX_VOX_TESELA = 800_000


def cargar_modelo():
    cfg = dict(enc_patch_size=[1024 for _ in range(5)], enable_flash=False)
    return sonata.load("sonata", repo_id="facebook/sonata", custom_config=cfg).cuda().eval()


def normales(P: np.ndarray, k: int = 16) -> np.ndarray:
    """Normal por PCA de los k vecinos, orientada hacia arriba."""
    arbol = cKDTree(P)
    out = np.zeros_like(P, dtype="f4")
    for a in range(0, len(P), 200_000):
        b = min(a + 200_000, len(P))
        _, idx = arbol.query(P[a:b], k=k, workers=-1)
        v = P[idx] - P[idx].mean(axis=1, keepdims=True)
        _, vec = np.linalg.eigh(np.matmul(v.transpose(0, 2, 1), v))
        n = vec[:, :, 0]
        n[n[:, 2] < 0] *= -1
        out[a:b] = n
    return out


def voxelizar(xyz: np.ndarray, rgb: np.ndarray):
    """Un punto real por celda de GRID (no un centroide: no se inventan coordenadas)."""
    ij = np.floor(xyz / GRID).astype(np.int64)
    _, inv, cnt = np.unique(ij, axis=0, return_inverse=True, return_counts=True)
    orden = np.argsort(inv.ravel(), kind="stable")
    rep = orden[np.concatenate([[0], np.cumsum(cnt)[:-1]])]
    return xyz[rep], rgb[rep]


@torch.inference_mode()
def rasgos_tesela(modelo, P: np.ndarray, C: np.ndarray, N: np.ndarray) -> torch.Tensor:
    """Rasgos (n, 1088) de una tesela: los tres niveles mas profundos concatenados."""
    centro = P.mean(axis=0)
    punto = {"coord": (P - centro).astype("f4"), "color": C.astype("f4"), "normal": N.astype("f4")}
    tr = sonata.transform.Compose([
        dict(type="GridSample", grid_size=GRID, hash_type="fnv", mode="train",
             return_grid_coord=True, return_inverse=True),
        dict(type="NormalizeColor"),
        dict(type="ToTensor"),
        dict(type="Collect", keys=("coord", "grid_coord", "color", "inverse"),
             feat_keys=("coord", "color", "normal")),
    ])
    d = tr(punto)
    for k in d:
        if isinstance(d[k], torch.Tensor):
            d[k] = d[k].cuda(non_blocking=True)
    with torch.autocast("cuda", dtype=torch.float16):
        p = modelo(d)
    for _ in range(2):
        parent, inverse = p.pop("pooling_parent"), p.pop("pooling_inverse")
        parent.feat = torch.cat([parent.feat, p.feat[inverse]], dim=-1)
        p = parent
    while "pooling_parent" in p.keys():
        parent, inverse = p.pop("pooling_parent"), p.pop("pooling_inverse")
        parent.feat = p.feat[inverse]
        p = parent
    f = p.feat[p.inverse].float()
    return torch.nn.functional.normalize(f, dim=-1)


def _tesela(modelo, P, C, N, fn, x0, y0, lado) -> None:
    """Una tesela [x0, x0+lado) x [y0, y0+lado) con su anillo. Si tiene mas de
    MAX_VOX_TESELA voxeles se parte en cuatro, cada una con su propio anillo."""
    caja = ((P[:, 0] >= x0 - ANILLO) & (P[:, 0] < x0 + lado + ANILLO) &
            (P[:, 1] >= y0 - ANILLO) & (P[:, 1] < y0 + lado + ANILLO))
    idx = np.flatnonzero(caja)
    if len(idx) < 100:
        return
    if len(idx) > MAX_VOX_TESELA and lado > 2 * ANILLO:
        m = lado / 2
        for dx in (0.0, m):
            for dy in (0.0, m):
                _tesela(modelo, P, C, N, fn, x0 + dx, y0 + dy, m)
        return
    q = P[idx]
    nucleo = (q[:, 0] >= x0) & (q[:, 0] < x0 + lado) & (q[:, 1] >= y0) & (q[:, 1] < y0 + lado)
    if not nucleo.any():
        return
    f = rasgos_tesela(modelo, q, C[idx], N[idx])
    fn(idx[nucleo], f[torch.from_numpy(np.flatnonzero(nucleo)).cuda()])
    del f
    torch.cuda.empty_cache()


def recorrer(modelo, P: np.ndarray, C: np.ndarray, N: np.ndarray, fn) -> None:
    """Recorre el bloque por teselas y llama fn(indices_del_nucleo, rasgos) en cada una."""
    lo = P[:, :2].min(axis=0)
    ij = np.floor((P[:, :2] - lo) / TESELA).astype(int)
    for cx, cy in np.unique(ij, axis=0):
        x0, y0 = lo + np.array([cx, cy]) * TESELA
        _tesela(modelo, P, C, N, fn, x0, y0, TESELA)
