"""Datos para entrenar y evaluar el detector de postes sobre `datos/crudo/etiquetado/`.

En `datos/crudo/etiquetado/` estan solo los recortes a mano, con la clase en el NOMBRE
del archivo y la carpeta que decide el conjunto:

    datos/crudo/etiquetado/<escaneo>/poste_bt/<train|test>/b_<ix>_<iy>_BT.las|laz   poste_bt (clase 5)
    datos/crudo/etiquetado/<escaneo>/poste_mt/<train|test>/b_<ix>_<iy>_MT.las|laz   poste_mt (clase 12)

La nube entera del bloque, de la que se recortaron, se toma de
`datos/intermedio/01_bloques/` (la salida de la etapa `bloques` del pipeline).

Un recorte es un SUBCONJUNTO de la nube: mismos puntos, misma coordenada. La
etiqueta de un voxel se decide por vecindad (hay un punto del recorte a menos
de 1.5 voxeles), nunca por el campo `classification`, que en estos archivos
vale 0 en todas partes.

Este modulo hace tres cosas, y las comparten `preparar_datos.py`,
`preparar_sonata.py` y los cuadernos de `cuadernos/`:

  1. Descubrir los bloques y sus recortes (`inventario`).
  2. Convertir un bloque en una tabla de voxeles con rasgos geometricos y su
     etiqueta (`preparar_bloque`), y guardarla en `datos/intermedio/cache/geometrica/` para no repetir los
     minutos de KD-tree cada vez que se abre el cuaderno.
  3. Repartir los bloques en entrenamiento / validacion / prueba POR BLOQUE,
     porque dos voxeles del mismo poste en lados distintos de una particion al
     azar inflan cualquier metrica. El reparto lo dicen las CARPETAS, una por clase:
     `<escaneo>/poste_bt/<train|test>/` para el modelo BT y `<escaneo>/poste_mt/...`
     para el MT; la validacion se aparta de train por id de bloque
     (`VAL_DE_TRAIN[clase]`, `particion_por_carpetas`).

Los rasgos son los del baseline (PCA local a varias escalas, altura sobre el
suelo, altura de la columna, densidad, intensidad, color) con dos cambios:
una tercera escala de 3 m, que separa el fuste de la arista de una fachada, y
el numero de voxeles de la columna de 1 m, que distingue una linea vertical
aislada de una pared.
"""
from __future__ import annotations

import json
import re
import os
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import laspy
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
BASE_CACHE = Path(os.environ.get("POSTES_CACHE", RAIZ / "datos" / "intermedio" / "cache"))
DATOS = RAIZ / "datos" / "crudo" / "etiquetado"
INDICE_BLOQUES = RAIZ / "datos" / "intermedio" / "01_bloques" / "bloque_index.csv"
CACHE = BASE_CACHE / "geometrica"                 # rasgos geometricos, un .npz por bloque (preparar_datos.py)
CACHE_SONATA = BASE_CACHE / "sonata"   # rasgos de Sonata, una carpeta por bloque (preparar_sonata.py)
SALIDA = AQUI.parents[1] / "resultados" / "postes"   # una subcarpeta por corrida, ver nueva_corrida()

# Clase por sufijo del archivo de recorte. Los ids son los de params.yaml
# (ontology v7) y NO se cambian: son lo que se escribe en `classification`.
CLASE_POR_SUFIJO = {"BT": 5, "MT": 12}
NOMBRE_CLASE = {0: "fondo", 5: "poste_bt", 12: "poste_mt"}
FONDO = 0

VOXEL = 0.10            # m. Un fuste de 20-30 cm sobrevive de sobra.
RADIOS = (0.4, 1.2, 3.0)  # fuste, entorno inmediato, contexto
K_VEC = 32              # vecinos por punto para el PCA local
TOL_ETIQUETA = VOXEL * 1.5
HAG_MIN, HAG_MAX = 0.3, 40.0   # fuera de esto no hay poste: suelo o ruido lejano
ALTURA_MT = 11.5        # m de columna a partir de los cuales un poste es de MT.
                        # La ontologia dice "BT hasta ~8 m, MT mas de 11 m", pero
                        # MEDIDO sobre los 138 postes de BT etiquetados en datos/crudo/etiquetado/
                        # (30-oct-2026) el poste con su luminaria llega a 10-11 m
                        # de altura de columna (mediana ~9.5, maximo 11.8), y el
                        # unico poste de MT etiquetado mide 11.8. Con un solo MT
                        # el corte es provisional: revisarlo cuando haya mas.

NOMBRES_RASGOS = (
    [f"{n}_{r}" for r in RADIOS for n in ("linealidad", "planaridad", "esfericidad", "verticalidad")]
    + ["hag", "columna_max", "columna_n", "densidad", "intensidad", "rojo", "verde", "azul"]
)

_RE_BLOQUE = re.compile(r"^(b_-?\d+_-?\d+)(?:_(BT|MT))?$", re.IGNORECASE)

# Reparto por bloque, POR CLASE. Desde el 10-nov-2026 cada escaneo tiene una carpeta
# por clase y, dentro, `train/` y `test/`:
#
#     <escaneo>/poste_bt/<train|test>/b_<ix>_<iy>_BT.las     -> particion del modelo BT
#     <escaneo>/poste_mt/<train|test>/b_<ix>_<iy>_MT.las     -> particion del modelo MT
#
# Un bloque puede estar en train para una clase y en test para la otra (p. ej.
# PACHAP01MT0108202501_b_1494_43240: BT en test, MT en train). El modelo de una clase
# solo usa los bloques de la carpeta de esa clase: un bloque con recortes solo de MT
# puede tener postes de BT sin recortar y no sirve para el modelo BT. La etiqueta de
# cada bloque sigue saliendo de TODOS sus recortes, esten en la carpeta que esten.
# El formato anterior, `<escaneo>/<train|test>/`, se sigue leyendo: vale para las
# dos clases a la vez.
#
# La validacion no tiene carpeta: se apartan de train los bloques de `VAL_DE_TRAIN[clase]`.
# 6-nov-2026: BT valida con dos bloques del ...01 y uno del ...02 (b_1489_43238).
# 10-nov-2026: MT valida con un bloque de cada escaneo con MT: b_1463_43339 de Ate (~9
# postes MT) y b_1489_43238 del ...02 (~3). Quedan ~20 MT en train y 8 en test.
# 11-nov-2026: los recortes MT de Pachacamac salen del etiquetado (decision del usuario);
# MT queda solo con Ate y valida con un bloque de cada escaneo: b_1463_43339 de ...01 (~9)
# y b_1458_43344 de ...02 (~4).
VAL_DE_TRAIN: Dict[str, List[str]] = {
    "BT": ["PACHAP01MT0108202501_b_1494_43241", "PACHAP01MT0108202501_b_1497_43238",
           "PACHAP01MT0108202502_b_1489_43238"],
    "MT": ["AVP01MT2611202501_b_1463_43339", "AVP01MT2611202502_b_1458_43344"],
}
CONJUNTOS_CARPETA = ("train", "test")
CARPETA_CLASE = {"poste_bt": "BT", "poste_mt": "MT"}   # carpeta de clase -> sufijo del recorte
SUFIJOS = ("BT", "MT")


def t() -> float:
    return time.perf_counter()


RE_CORRIDA = re.compile(r"^corrida(\d+)_")


def nueva_corrida(modelo: str, base: Path = SALIDA, fija: bool = False) -> Path:
    """Carpeta de salida de una corrida: `<base>/corrida<N>_<AAAA-MM-DD>_<modelo>/`.

    N sigue al mayor de las carpetas `corrida*` que ya hay en `base`, asi las corridas de
    todos los cuadernos quedan en orden y ninguna pisa a otra. Si la ultima carpeta de este
    mismo modelo no tiene `resumen_<modelo>.json` (la corrida se corto antes de terminar), se
    reutiliza en vez de dejar una carpeta a medias. Con `fija=True` (prueba rapida) devuelve
    siempre `<base>/<modelo>/`, que se sobrescribe."""
    base = Path(base)
    if fija:
        carpeta = base / modelo
    else:
        previas = sorted((int(m.group(1)), c) for c in base.glob("corrida*_*")
                         if c.is_dir() and (m := RE_CORRIDA.match(c.name)))
        propias = [c for _, c in previas if c.name.endswith(f"_{modelo}")]
        if propias and propias[-1] == previas[-1][1] and not (propias[-1] / f"resumen_{modelo}.json").exists():
            carpeta = propias[-1]
        else:
            n = previas[-1][0] + 1 if previas else 1
            carpeta = base / f"corrida{n}_{time.strftime('%Y-%m-%d')}_{modelo}"
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def ultima_corrida(modelo: str, base: Path = SALIDA) -> Path:
    """La corrida terminada (con resumen) mas reciente de un modelo."""
    hechas = sorted((int(m.group(1)), c) for c in Path(base).glob(f"corrida*_{modelo}")
                    if (m := RE_CORRIDA.match(c.name)) and (c / f"resumen_{modelo}.json").exists())
    if not hechas:
        raise FileNotFoundError(f"no hay corridas terminadas de {modelo} en {base}")
    return hechas[-1][1]


# --------------------------------------------------------------------------
# 1 · Inventario
# --------------------------------------------------------------------------
def indice_interim() -> Dict[Tuple[str, str], Path]:
    """(escaneo, b_<ix>_<iy>) -> nube del bloque en datos/intermedio/01_bloques, segun el
    indice que escribe la etapa `bloques` del pipeline."""
    if not INDICE_BLOQUES.exists():
        return {}
    ix = pd.read_csv(INDICE_BLOQUES, usecols=["scan", "bloque_ix", "bloque_iy", "path"])
    return {(r.scan, f"b_{r.bloque_ix}_{r.bloque_iy}"): RAIZ / r.path for r in ix.itertuples()}


def id_bloque(escaneo: str, bloque: str) -> str:
    return f"{escaneo}_{bloque}"


def _ubicar(ruta: Path, raiz: Path) -> Tuple[str, Optional[str], Optional[str]]:
    """(escaneo, clase de la carpeta o None, conjunto o None) segun donde este el archivo:
    <esc>/<clase>/<conj>/f, <esc>/<conj>/f (formato anterior, sin clase) o <esc>/f."""
    rel = ruta.relative_to(raiz)
    partes = [p.lower() for p in rel.parts[:-1]]
    escaneo = rel.parts[0]
    if len(partes) == 3 and partes[1] in CARPETA_CLASE and partes[2] in CONJUNTOS_CARPETA:
        return escaneo, CARPETA_CLASE[partes[1]], partes[2]
    if len(partes) == 2 and partes[1] in CONJUNTOS_CARPETA:
        return escaneo, None, partes[1]
    if len(partes) == 1:
        return escaneo, None, None
    raise ValueError(f"{rel.as_posix()}: carpeta no reconocida. Usa "
                     "<escaneo>/poste_bt|poste_mt/train|test/")


def inventario(raiz: Path = DATOS) -> pd.DataFrame:
    """Una fila por bloque etiquetado: id, escaneo, ruta de la nube y de cada recorte, y
    el conjunto de cada clase (`conjunto_BT`, `conjunto_MT`: train, test o None).
    `conjunto` es el comun a sus recortes, o "mixto" si cada clase va a uno distinto.

    En `datos/crudo/etiquetado/<escaneo>/<poste_bt|poste_mt>/<train|test>/` van SOLO los
    recortes `_BT` y `_MT`. La nube del bloque se toma de `datos/intermedio/01_bloques/`
    (`indice_interim`). Una nube que aun este junto a sus recortes se usa si no aparece
    en interim.

    El id es `<escaneo>_<bloque>`: los escaneos se solapan y el mismo bloque, con
    el mismo nombre, existe en varios de ellos."""
    nubes = indice_interim()
    filas: Dict[str, dict] = {}
    problemas: List[str] = []
    for ruta in sorted(Path(raiz).rglob("*")):
        if ruta.suffix.lower() not in (".las", ".laz"):
            continue
        m = _RE_BLOQUE.match(ruta.stem)
        if not m:
            continue
        escaneo, clase_carpeta, conj = _ubicar(ruta, Path(raiz))
        bloque, sufijo = m.group(1), (m.group(2) or "").upper()
        clave = id_bloque(escaneo, bloque)
        fila = filas.setdefault(clave, {"bloque": clave, "rejilla": bloque, "escaneo": escaneo,
                                        "nube": nubes.get((escaneo, bloque)),
                                        "BT": None, "MT": None, "conjunto_BT": None, "conjunto_MT": None})
        donde = ruta.relative_to(raiz).as_posix()
        if not sufijo:                       # una nube junto a los recortes (formato antiguo)
            if fila["nube"] is None:
                fila["nube"] = ruta
            continue
        if clase_carpeta and clase_carpeta != sufijo:
            problemas.append(f"{donde}: recorte _{sufijo} dentro de la carpeta de {clase_carpeta}")
            continue
        if fila[sufijo] is not None:
            problemas.append(f"{donde}: {clave} ya tiene recorte _{sufijo} en "
                             f"{Path(fila[sufijo]).relative_to(raiz).as_posix()}")
            continue
        fila[sufijo], fila[f"conjunto_{sufijo}"] = ruta, conj
    if problemas:
        raise ValueError(f"Recortes mal ubicados en {raiz}:\n  - " + "\n  - ".join(problemas))
    df = pd.DataFrame(list(filas.values()),
                      columns=["bloque", "rejilla", "escaneo", "nube", "BT", "MT", "conjunto_BT", "conjunto_MT"])
    df = df[df["BT"].notna() | df["MT"].notna()].copy()

    def comun(f) -> Optional[str]:
        cs = {f[f"conjunto_{s}"] for s in SUFIJOS if f[s] is not None}
        return cs.pop() if len(cs) == 1 else "mixto"
    df["conjunto"] = [comun(f) for _, f in df.iterrows()]
    sin_nube = df.loc[df["nube"].isna(), "bloque"].tolist()
    if sin_nube:
        print(f"AVISO: sin nube en datos/intermedio/01_bloques, se ignoran: {sin_nube}. "
              "¿Falta correr la etapa `bloques` para ese escaneo?")
    return df[df["nube"].notna()].reset_index(drop=True)


def particion_por_carpetas(clase: Optional[str] = None, val_de_train: Optional[Iterable[str]] = None,
                           raiz: Path = DATOS) -> Dict[str, List[str]]:
    """train / val / test de un modelo a partir de las carpetas.

    `clase` "BT" o "MT": la particion la dice `<escaneo>/poste_<clase>/<train|test>/` y
    solo entran los bloques con recorte de esa clase. `clase=None` (modelo de las dos
    clases, p. ej. el baseline geometrico): entran todos los bloques y cada uno tiene que
    estar en el mismo conjunto para las dos clases; si no, falla y dice cuales.
    Validacion: los bloques de train que esten en `val_de_train` (por defecto
    `VAL_DE_TRAIN[clase]`, o la union de las dos listas con `clase=None`).

    Falla tambien si un mismo bloque de la rejilla (el mismo suelo, los mismos postes,
    visto desde otro escaneo) cae en dos conjuntos: el modelo veria en train los
    postes con que se le mide."""
    if clase is not None and clase not in SUFIJOS:
        raise ValueError(f"clase '{clase}': usa una de {SUFIJOS} o None")
    inv = inventario(raiz)
    if clase is None:
        mixtos = inv[inv["conjunto"] == "mixto"]
        if len(mixtos):
            raise ValueError("Estos bloques estan en train para una clase y en test para la otra; un modelo "
                             "de las dos clases no puede usarlos. Entrena un modelo por clase "
                             "(clase='BT' / 'MT') o muevelos:\n  - " + "\n  - ".join(
                                 f"{r.bloque}: BT en {r.conjunto_BT}, MT en {r.conjunto_MT}" for r in mixtos.itertuples()))
        col = inv["conjunto"]
        val_de_train = list(val_de_train) if val_de_train is not None else sorted(set(sum(VAL_DE_TRAIN.values(), [])))
    else:
        inv = inv[inv[clase].notna()].copy()
        col = inv[f"conjunto_{clase}"]
        val_de_train = list(val_de_train) if val_de_train is not None else list(VAL_DE_TRAIN[clase])
    en_train = set(inv.loc[col == "train", "bloque"])
    val = [b for b in val_de_train if b in en_train]
    faltan = set(val_de_train) - set(val)
    if faltan:
        print(f"AVISO ({clase or 'BT+MT'}): {sorted(faltan)} no estan en train; validacion solo con {val}")
    part = {"train": sorted(b for b in en_train if b not in val), "val": val,
            "test": sorted(inv.loc[col == "test", "bloque"])}
    donde = {b: k for k, bs in part.items() for b in bs}
    inv["particion"] = inv["bloque"].map(donde)
    choques = inv.dropna(subset=["particion"]).groupby("rejilla")["particion"].nunique()
    choques = choques[choques > 1].index.tolist()
    if choques:
        detalle = "\n  - " + "\n  - ".join(", ".join(f"{r.bloque} en {r.particion}" for r in inv[inv["rejilla"] == c].itertuples())
                                           for c in choques)
        raise ValueError(f"El mismo bloque esta en dos conjuntos desde escaneos distintos ({clase or 'BT+MT'}):{detalle}\n"
                         "Pon sus recortes en la misma carpeta (train o test) en todos los escaneos.")
    return part


def particiones() -> Dict[str, Dict[str, List[str]]]:
    """La particion de cada modelo por clase: {"BT": {...}, "MT": {...}}."""
    return {c: particion_por_carpetas(c) for c in SUFIJOS}


try:
    PARTICION: Dict[str, Dict[str, List[str]]] = (particiones() if DATOS.exists()
                                                  else {c: {"train": [], "val": [], "test": []} for c in SUFIJOS})
except ValueError as e:   # que el modulo se pueda importar; el cuaderno vuelve a llamar y ahi si falla
    print(f"AVISO: {e}")
    PARTICION = {c: {"train": [], "val": [], "test": []} for c in SUFIJOS}


def rutas_bloque(bloque: str, raiz: Path = DATOS) -> dict:
    inv = inventario(raiz)
    fila = inv[inv["bloque"] == bloque]
    if fila.empty:
        raise FileNotFoundError(f"no hay bloque {bloque} bajo {raiz}")
    return fila.iloc[0].to_dict()


def huella_etiquetas(bloques: Optional[Iterable[str]] = None, raiz: Path = DATOS) -> dict:
    """MD5 de cada recorte y uno global: la *version de las etiquetas* con la que
    se entreno, para que el resumen de cada corrida diga con que verdad de
    campo se midio (los recortes cambian: el 31-oct entraron 7 postes de MT)."""
    import hashlib
    inv = inventario(raiz)
    if bloques is not None:
        inv = inv[inv["bloque"].isin(list(bloques))]
    out = {}
    for _, f in inv.iterrows():
        for suf in ("BT", "MT"):
            r = f.get(suf)
            if r:
                out[f"{f['bloque']}_{suf}"] = hashlib.md5(Path(r).read_bytes()).hexdigest()
    total = hashlib.md5("".join(f"{k}:{v}" for k, v in sorted(out.items())).encode()).hexdigest()
    return {"n_recortes": len(out), "md5": total, "recortes": out}


def etiquetas_desactualizadas(fila: dict, marca: Path) -> bool:
    """True si algun recorte del bloque es mas nuevo que `marca` (el meta.json o
    el .npz de su cache): la cache lleva las etiquetas viejas y hay que
    reetiquetarla, sin recalcular rasgos."""
    marca = Path(marca)
    if not marca.exists():
        return False
    m = marca.stat().st_mtime
    return any(bool(fila.get(suf)) and Path(fila[suf]).stat().st_mtime > m for suf in ("BT", "MT"))


# --------------------------------------------------------------------------
# 2 · De la nube a la tabla de voxeles
# --------------------------------------------------------------------------
def leer(ruta: Path) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(xyz f8, rgb f4 0-255, intensidad f4). Color 16 bit -> 8 bit."""
    with laspy.open(str(ruta)) as fh:
        d = fh.read()
    xyz = np.stack([np.asarray(d.x), np.asarray(d.y), np.asarray(d.z)], axis=1)
    rgb = np.stack([np.asarray(d.red), np.asarray(d.green), np.asarray(d.blue)],
                   axis=1).astype("f4")
    if rgb.size and rgb.max() > 255:
        rgb /= 256.0
    return xyz, rgb, np.asarray(d.intensity).astype("f4")


def voxelizar(xyz: np.ndarray, voxel: float = VOXEL):
    """Indice del punto representante de cada voxel (un punto REAL, no un
    centroide) y cuantos puntos caian en el. La clave es un entero por voxel,
    que ordena 30 M de puntos en segundos; `np.unique(axis=0)` tardaba minutos."""
    ij = np.floor(xyz / voxel).astype(np.int64)
    ij -= ij.min(axis=0)
    ny, nz = int(ij[:, 1].max()) + 1, int(ij[:, 2].max()) + 1
    clave = (ij[:, 0] * ny + ij[:, 1]) * nz + ij[:, 2]
    _, rep, cuenta = np.unique(clave, return_index=True, return_counts=True)
    return rep, cuenta.astype("f4")


def altura_sobre_suelo(P: np.ndarray, celda: float = 2.0, pct: float = 5.0,
                       suavizados: int = 2) -> np.ndarray:
    """Altura de cada punto sobre un suelo de rejilla (percentil bajo por celda,
    huecos rellenados, mediana movil). Es el del baseline, sin cambios."""
    o = P[:, :2].min(axis=0)
    ij = np.floor((P[:, :2] - o) / celda).astype(np.int64)
    nx, ny = int(ij[:, 0].max()) + 1, int(ij[:, 1].max()) + 1
    plano = ij[:, 1] * nx + ij[:, 0]
    g = np.full(ny * nx, np.nan)
    s = pd.DataFrame({"c": plano, "z": P[:, 2]}).groupby("c")["z"].quantile(pct / 100.0)
    g[s.index.to_numpy()] = s.to_numpy()
    g = g.reshape(ny, nx)
    for _ in range(64):
        hueco = np.isnan(g)
        if not hueco.any():
            break
        vec = np.stack([np.roll(g, d, a) for a in (0, 1) for d in (-1, 1)])
        with np.errstate(invalid="ignore"):
            relleno = np.nanmean(vec, axis=0)
        g[hueco] = relleno[hueco]
    g = np.nan_to_num(g, nan=float(np.nanmedian(g)))
    for _ in range(suavizados):
        g = np.median(np.stack([np.roll(g, d, a) for a in (0, 1)
                                for d in (-2, -1, 0, 1, 2)]), axis=0)
    return (P[:, 2] - g[np.clip(ij[:, 1], 0, ny - 1),
                        np.clip(ij[:, 0], 0, nx - 1)]).astype("f4")


def rasgos_pca(P: np.ndarray, consulta: np.ndarray, radio: float, k: int,
               arbol: cKDTree, lote: int = 200_000) -> np.ndarray:
    """Linealidad, planaridad, esfericidad y verticalidad del vecindario de
    cada punto de `consulta` dentro de la nube `P` (indexada en `arbol`)."""
    n = len(P)
    out = np.zeros((len(consulta), 4), dtype="f4")
    for a in range(0, len(consulta), lote):
        b = min(a + lote, len(consulta))
        dist, idx = arbol.query(P[consulta[a:b]], k=k, distance_upper_bound=radio, workers=-1)
        valido = np.isfinite(dist)
        cnt = valido.sum(axis=1)
        np.clip(idx, 0, n - 1, out=idx)
        vec = P[idx]
        w = valido[:, :, None]
        c = np.maximum(cnt, 1)[:, None, None]
        media = (vec * w).sum(axis=1, keepdims=True) / c
        cen = (vec - media) * w
        cov = np.matmul(cen.transpose(0, 2, 1), cen) / c
        ev, evec = np.linalg.eigh(cov)
        ev = np.clip(ev[:, ::-1], 1e-12, None)
        evec = evec[:, :, ::-1]
        s = ev / ev.sum(axis=1, keepdims=True)
        e1, e2, e3 = s[:, 0], s[:, 1], s[:, 2]
        ok = cnt >= 3
        out[a:b, 0] = np.where(ok, (e1 - e2) / e1, 0)
        out[a:b, 1] = np.where(ok, (e2 - e3) / e1, 0)
        out[a:b, 2] = np.where(ok, e3 / e1, 0)
        out[a:b, 3] = np.where(ok, 1 - np.abs(evec[:, 2, 2]), 0)
    return out


def etiquetar(P: np.ndarray, recortes: Dict[str, Optional[Path]],
              tol: float = TOL_ETIQUETA) -> Tuple[np.ndarray, Dict[str, int]]:
    """Clase de cada voxel por vecindad con los recortes. MT pisa a BT si un
    punto cayera en los dos (no deberia). Devuelve tambien cuantos puntos
    tenia cada recorte, para el informe."""
    Y = np.zeros(len(P), dtype="u1")
    puntos = {}
    for sufijo in ("BT", "MT"):          # orden: el ultimo gana
        ruta = recortes.get(sufijo)
        if not ruta:
            continue
        e, _, _ = leer(Path(ruta))
        puntos[sufijo] = len(e)
        if len(e) == 0:
            continue
        d, _ = cKDTree(e).query(P, distance_upper_bound=tol, workers=-1)
        Y[np.isfinite(d)] = CLASE_POR_SUFIJO[sufijo]
    return Y, puntos


def preparar_bloque(fila: dict, verbose: bool = True) -> dict:
    """Nube entera -> voxeles con rasgos y etiqueta. Solo se conservan los
    voxeles con HAG en [HAG_MIN, HAG_MAX]: el suelo y el ruido lejano no
    pueden ser poste y son la mayoria de los puntos. El KD-tree y la altura
    del suelo se calculan con TODOS los voxeles, para que el vecindario de un
    pie de poste siga viendo el suelo."""
    t0 = t()
    xyz, rgb, inten = leer(Path(fila["nube"]))
    n_crudo = len(xyz)
    rep, dens = voxelizar(xyz)
    P, COL, INT = xyz[rep], rgb[rep], inten[rep]
    del xyz, rgb, inten
    HAG = altura_sobre_suelo(P)
    keep = (HAG >= HAG_MIN) & (HAG <= HAG_MAX)
    # columna de 1 m x 1 m: altura maxima y cuantos voxeles (solo los que quedan)
    cel = np.floor(P[:, :2]).astype(np.int64)
    cel -= cel.min(axis=0)
    ccol = cel[:, 0] * (int(cel[:, 1].max()) + 1) + cel[:, 1]
    serie = pd.Series(np.where(keep, HAG, np.nan))
    col_max = serie.groupby(ccol).transform("max").fillna(0).to_numpy().astype("f4")
    col_n = pd.Series(keep.astype("f4")).groupby(ccol).transform("sum").to_numpy().astype("f4")

    arbol = cKDTree(P, compact_nodes=False, balanced_tree=False)
    idx = np.flatnonzero(keep)
    trozos = [rasgos_pca(P, idx, r, K_VEC, arbol) for r in RADIOS]
    X = np.column_stack(trozos + [HAG[idx], col_max[idx], col_n[idx], dens[idx],
                                  INT[idx], COL[idx]]).astype("f4")
    Y, puntos = etiquetar(P[idx], {"BT": fila.get("BT"), "MT": fila.get("MT")})
    origen = np.floor(P[idx].min(axis=0))
    out = {"bloque": fila["bloque"], "escaneo": fila["escaneo"],
           "origen": origen, "P": (P[idx] - origen).astype("f4"),
           "hag": HAG[idx], "X": X, "Y": Y,
           "meta": {"puntos_crudos": int(n_crudo), "voxeles": int(len(P)),
                    "voxeles_conservados": int(keep.sum()),
                    "puntos_recorte": puntos,
                    "voxeles_por_clase": {NOMBRE_CLASE[int(c)]: int((Y == c).sum())
                                          for c in np.unique(Y)},
                    "segundos": round(t() - t0, 1)}}
    if verbose:
        m = out["meta"]
        print(f"  {fila['bloque']} ({fila['escaneo'][:6]}): {n_crudo:,} puntos -> "
              f"{m['voxeles']:,} voxeles, {m['voxeles_conservados']:,} con HAG util; "
              f"clases {m['voxeles_por_clase']} ({m['segundos']} s)")
    return out


# --------------------------------------------------------------------------
# 3 · Cache en disco
# --------------------------------------------------------------------------
def ruta_cache(bloque: str) -> Path:
    return CACHE / f"{bloque}.npz"


def guardar_cache(d: dict) -> Path:
    CACHE.mkdir(exist_ok=True)
    ruta = ruta_cache(d["bloque"])
    np.savez(ruta, P=d["P"], hag=d["hag"], X=d["X"], Y=d["Y"], origen=d["origen"],
             meta=json.dumps({"bloque": d["bloque"], "escaneo": d["escaneo"],
                              "rasgos": NOMBRES_RASGOS, **d["meta"]}))
    return ruta


def cargar_cache(bloque: str, absoluto: bool = False) -> dict:
    """La tabla de un bloque. `P` vuelve en float32 relativo al origen del
    bloque; con `absoluto=True` vuelve en float64 UTM (para escribir .laz)."""
    with np.load(ruta_cache(bloque)) as z:
        meta = json.loads(str(z["meta"]))
        P = z["P"].astype("f8") + z["origen"] if absoluto else z["P"]
        return {"bloque": bloque, "escaneo": meta["escaneo"], "origen": z["origen"],
                "P": P, "hag": z["hag"], "X": z["X"], "Y": z["Y"], "meta": meta}


def reetiquetar_cache(fila: dict) -> Path:
    """Recalcula solo `Y` de un bloque ya en cache con los recortes actuales.
    Los rasgos no dependen de las etiquetas, asi que no se tocan."""
    d = cargar_cache(fila["bloque"], absoluto=True)
    Y, puntos = etiquetar(d["P"], {"BT": fila.get("BT"), "MT": fila.get("MT")})
    d["Y"] = Y
    d["P"] = (d["P"] - d["origen"]).astype("f4")
    d["meta"].update({"puntos_recorte": puntos,
                      "voxeles_por_clase": {NOMBRE_CLASE[int(c)]: int((Y == c).sum()) for c in np.unique(Y)},
                      "etiquetas_actualizadas": time.strftime("%Y-%m-%d %H:%M")})
    print(f"  {fila['bloque']}: etiquetas nuevas {d['meta']['voxeles_por_clase']}")
    return guardar_cache(d)


def cargar_cache_sonata(bloque: str, absoluto: bool = False, raiz: Path = CACHE_SONATA) -> dict:
    """Un bloque de `datos/intermedio/cache/sonata/`: `F` es un memmap float16 (n, 256) y se lee por
    trozos; el resto son arrays normales. Mismas claves que `cargar_cache` mas `F`."""
    c = Path(raiz) / bloque
    meta = json.loads((c / "meta.json").read_text(encoding="utf-8"))
    origen = np.load(c / "origen.npy")
    P = np.load(c / "P.npy")
    return {"bloque": bloque, "escaneo": meta["escaneo"], "origen": origen,
            "P": P.astype("f8") + origen if absoluto else P,
            "hag": np.load(c / "hag.npy"), "Y": np.load(c / "Y.npy"),
            "F": np.load(c / "F.npy", mmap_mode="r"), "meta": meta}


NOMBRES_RASGOS_ALTURA = ("hag", "altura_columna", "posicion_en_columna")


def rasgos_altura(P: np.ndarray, hag: np.ndarray, celda: float = 0.5) -> np.ndarray:
    """(n, 3) float32 por voxel: altura sobre el suelo, altura de su columna y en que parte
    de la columna esta (hag / altura de la columna, 0 abajo, 1 arriba).

    Son ENTRADAS para la cabeza, no una regla: Sonata ve cada voxel con contexto local y un
    tramo del fuste a 5 m se parece igual en un poste de BT que en uno de MT; con estos tres
    numeros la red puede aprender de las etiquetas que alto tiene el objeto al que pertenece
    el voxel. La columna es el maximo de `hag` en una ventana de 3x3 celdas de `celda` m en
    planta (1,5 m de lado): cubre un fuste inclinado. Un arbol encima de la columna la
    hace mas alta; eso tambien lo ve la red al entrenar."""
    from scipy.ndimage import maximum_filter
    hag = np.asarray(hag, dtype="f4")
    ij = np.floor(np.asarray(P[:, :2], dtype="f8") / celda).astype(np.int64)
    ij -= ij.min(axis=0)
    rej = np.full(ij.max(axis=0) + 1, -np.inf, dtype="f4")
    np.maximum.at(rej, (ij[:, 0], ij[:, 1]), hag)
    rej = maximum_filter(rej, size=3, mode="constant", cval=-np.inf)
    col = np.maximum(rej[ij[:, 0], ij[:, 1]], 0.0)
    pos = np.clip(hag / np.maximum(col, 0.5), 0.0, 1.0)
    return np.stack([hag, col, pos], axis=1).astype("f4")


def contar_postes(P: np.ndarray, Y: np.ndarray, clases: Iterable[int] = (5, 12)) -> Dict[int, int]:
    """Postes etiquetados por clase, contando objetos (componentes a 0,6 m, >= 10 voxeles):
    el mismo criterio con que la metrica forma los postes reales."""
    return {c: len(objetos_columna(P, Y == c, z_escala=1.0, eps=0.6, min_vox=10)) for c in clases if (Y == c).any()}


def bloques_en_cache() -> List[str]:
    return sorted(p.stem for p in CACHE.glob("*b_*.npz")) if CACHE.exists() else []   # <escaneo>_b_<ix>_<iy>.npz


def resumen_cache() -> pd.DataFrame:
    filas = []
    for b in bloques_en_cache():
        with np.load(ruta_cache(b)) as z:
            m = json.loads(str(z["meta"]))
        filas.append({"bloque": b, "escaneo": m["escaneo"],
                      **{f"particion_{c.lower()}": next((k for k, v in PARTICION[c].items() if b in v), None)
                         for c in SUFIJOS},
                      "puntos_crudos": m["puntos_crudos"], "voxeles": m["voxeles_conservados"],
                      "vox_poste_bt": m["voxeles_por_clase"].get("poste_bt", 0),
                      "vox_poste_mt": m["voxeles_por_clase"].get("poste_mt", 0),
                      "pts_recorte_BT": m["puntos_recorte"].get("BT", 0),
                      "pts_recorte_MT": m["puntos_recorte"].get("MT", 0)})
    return pd.DataFrame(filas)


def conjunto(bloques: Iterable[str], max_fondo: Optional[int] = None,
             semilla: int = 0) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Apila varios bloques en (X, Y, id_bloque). `max_fondo` limita los voxeles
    de fondo POR BLOQUE (muestra al azar); los de poste entran siempre."""
    rng = np.random.default_rng(semilla)
    Xs, Ys, Gs = [], [], []
    for g, b in enumerate(bloques):
        d = cargar_cache(b)
        m = np.ones(len(d["Y"]), dtype=bool)
        if max_fondo is not None:
            fondo = np.flatnonzero(d["Y"] == FONDO)
            if len(fondo) > max_fondo:
                m[fondo] = False
                m[rng.choice(fondo, max_fondo, replace=False)] = True
        Xs.append(d["X"][m]); Ys.append(d["Y"][m]); Gs.append(np.full(int(m.sum()), g, "i2"))
    return np.concatenate(Xs), np.concatenate(Ys), np.concatenate(Gs)


# --------------------------------------------------------------------------
# 4 · Clase BT / MT por altura de columna, sobre objetos ya detectados
# --------------------------------------------------------------------------
def clase_por_altura(altura_m: float, umbral: float = ALTURA_MT) -> int:
    return CLASE_POR_SUFIJO["MT"] if altura_m >= umbral else CLASE_POR_SUFIJO["BT"]


# --------------------------------------------------------------------------
# 5 · De voxeles predichos a objetos: agrupar por COLUMNA antes del filtro
# --------------------------------------------------------------------------
# Medido el 30-oct-2026 con la primera cabeza MLP sobre Sonata: el modelo acierta
# los voxeles de un poste a TROZOS (fragmentos de 1-3 m separados por huecos), y
# el filtro de forma del baseline, que forma componentes conexas a 0.5 m en 3D,
# veia cada trozo como un objeto de menos de 3 m y lo tiraba. Sin filtro el
# modelo hallaba 44 de 48 postes de test; con el filtro, 33. Comprimir la z
# antes de formar las componentes (z * Z_ESCALA) une los trozos de una misma
# columna —un hueco vertical de hasta eps/Z_ESCALA m ya no parte el poste— y
# deja que el filtro juzgue el poste entero: 40 de 48 con la misma precision.
Z_ESCALA = 0.1          # 0.1 = la columna manda; 1.0 = el filtro original del baseline
EPS_OBJETO = 0.5        # m, distancia que une dos voxeles en un mismo objeto
MIN_VOX_OBJETO = 40
MIN_ALTO_POSTE = 2.0    # m; era 3.0 en el baseline, pero un poste visto a medias
MIN_CIMA_POSTE = 4.0    # tambien es un poste y la cima lo distingue de un bolardo
MAX_RADIO_POSTE = 0.6   # m, percentil 90 del radio en la mitad baja del objeto
MIN_ESBELTEZ_POSTE = 1.5


def objetos_columna(pts: np.ndarray, mascara: np.ndarray, z_escala: float = Z_ESCALA,
                    eps: float = EPS_OBJETO, min_vox: int = MIN_VOX_OBJETO) -> List[np.ndarray]:
    """Indices (sobre `pts`) de cada objeto formado por los voxeles de `mascara`,
    con la z comprimida para que los trozos de una columna queden juntos."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    idx = np.flatnonzero(mascara)
    if len(idx) < 2:
        return []
    p = pts[idx].astype("f8", copy=True)
    p[:, 2] *= z_escala
    pares = cKDTree(p).query_pairs(eps, output_type="ndarray")
    g = coo_matrix((np.ones(len(pares)), (pares[:, 0], pares[:, 1])), shape=(len(idx),) * 2)
    lab = connected_components(g, directed=False)[1]
    return [idx[lab == k] for k in np.unique(lab) if int((lab == k).sum()) >= min_vox]


def filtrar_columnas(pts: np.ndarray, hag: np.ndarray, mascara: np.ndarray,
                     z_escala: float = Z_ESCALA, min_alto: float = MIN_ALTO_POSTE,
                     min_cima: float = MIN_CIMA_POSTE, max_radio: float = MAX_RADIO_POSTE,
                     min_esbeltez: float = MIN_ESBELTEZ_POSTE) -> np.ndarray:
    """Mascara de los voxeles que pertenecen a un objeto con forma de poste:
    alto, con la cima a mas de `min_cima`, fuste delgado y esbelto."""
    out = np.zeros(len(pts), dtype=bool)
    for g in objetos_columna(pts, mascara, z_escala):
        h, p = hag[g], pts[g]
        alto = float(h.max() - h.min())
        if alto < min_alto or h.max() < min_cima:
            continue
        bajo = h <= h.min() + alto * 0.5
        pb = p[bajo] if bajo.sum() >= 5 else p
        eje = np.median(pb[:, :2], axis=0)
        if np.percentile(np.linalg.norm(pb[:, :2] - eje, axis=1), 90) > max_radio:
            continue
        ancho = max(np.ptp(pb[:, 0]), np.ptp(pb[:, 1]))
        if alto < min_esbeltez * max(ancho, 1e-3):
            continue
        out[g] = True
    return out


def metrica_objetos_columna(pts: np.ndarray, pred: np.ndarray, real: np.ndarray,
                            z_escala: float = Z_ESCALA, tol: float = 1.0,
                            ignorar: Optional[np.ndarray] = None) -> dict:
    """Postes reales hallados y candidatos correctos, a `tol` m. Los postes reales
    se forman con la agrupacion 3D original (los recortes son objetos enteros) y
    los candidatos con la agrupacion por columna, la misma que uso el filtro.

    `ignorar` marca voxeles de una clase que NO se evalua (p. ej. el poste de MT
    cuando se entrena solo BT): un candidato que los toca no cuenta ni como
    correcto ni como inventado, y esos voxeles nunca forman un poste real."""
    reales = objetos_columna(pts, real, z_escala=1.0, eps=0.6, min_vox=10)
    preds = objetos_columna(pts, pred, z_escala)
    if ignorar is not None and ignorar.any():
        a_ign = cKDTree(pts[ignorar])
        preds = [q for q in preds
                 if not np.isfinite(a_ign.query(pts[q], distance_upper_bound=tol)[0]).any()]
    a_pred = cKDTree(pts[pred]) if pred.any() else None
    a_real = cKDTree(pts[real]) if real.any() else None
    hallados = sum(1 for r in reales if a_pred is not None and
                   np.isfinite(a_pred.query(pts[r], distance_upper_bound=tol)[0]).any())
    buenos = sum(1 for q in preds if a_real is not None and
                 np.isfinite(a_real.query(pts[q], distance_upper_bound=tol)[0]).any())
    return {"reales": len(reales), "hallados": hallados, "predichos": len(preds), "correctos": buenos,
            "recuperacion": round(hallados / len(reales), 3) if reales else None,
            "precision": round(buenos / len(preds), 3) if preds else None}


# --------------------------------------------------------------------------
# 6 · Tres clases: detectar el poste y, por objeto, decir si es de BT o de MT
# --------------------------------------------------------------------------
# La cabeza da una probabilidad por voxel para fondo, poste_bt y poste_mt. La
# deteccion es una sola pregunta (poste o no: 1 - p_fondo >= umbral) y se
# agrupa y filtra igual que en el caso binario; la clase se decide por OBJETO,
# sumando las probabilidades de sus voxeles, porque un poste es de BT o de MT
# entero y no voxel a voxel.
def clasificar_objetos(pts: np.ndarray, hag: np.ndarray, probs: np.ndarray, clases: Tuple[int, ...],
                       umbral: float, z_escala: float = Z_ESCALA) -> Tuple[np.ndarray, np.ndarray]:
    """`probs` es (n, 1 + len(clases)) con el fondo en la columna 0. Devuelve la
    clase de cada voxel (0 o una de `clases`) y la puntuacion de poste."""
    s = (1.0 - probs[:, 0]).astype("f4")
    pred = filtrar_columnas(pts, hag, s >= umbral, z_escala)
    clase = np.zeros(len(pts), dtype="u1")
    for g in objetos_columna(pts, pred, z_escala):
        clase[g] = clases[int(probs[g, 1:].sum(axis=0).argmax())]
    return clase, s


def metrica_objetos_clases(pts: np.ndarray, clase_pred: np.ndarray, Y: np.ndarray,
                           clases: Tuple[int, ...], z_escala: float = Z_ESCALA, tol: float = 1.0) -> List[dict]:
    """Una fila por clase: postes reales, hallados por un candidato de la MISMA
    clase, hallados solo por un candidato de otra clase, candidatos predichos,
    correctos (tocan un poste real de su clase), de clase equivocada (tocan un
    poste real de otra clase) e inventados (no tocan ningun poste)."""
    arb_pred = {c: cKDTree(pts[clase_pred == c]) for c in clases if (clase_pred == c).any()}
    arb_real = {c: cKDTree(pts[Y == c]) for c in clases if (Y == c).any()}

    def toca(arbol, g):
        return arbol is not None and bool(np.isfinite(arbol.query(pts[g], distance_upper_bound=tol)[0]).any())

    filas = []
    for c in clases:
        reales = objetos_columna(pts, Y == c, z_escala=1.0, eps=0.6, min_vox=10)
        preds = objetos_columna(pts, clase_pred == c, z_escala)
        hall = sum(1 for r in reales if toca(arb_pred.get(c), r))
        hall_cualquiera = sum(1 for r in reales if any(toca(a, r) for a in arb_pred.values()))
        corr = sum(1 for q in preds if toca(arb_real.get(c), q))
        otra = sum(1 for q in preds if not toca(arb_real.get(c), q)
                   and any(toca(a, q) for k, a in arb_real.items() if k != c))
        filas.append({"clase": NOMBRE_CLASE[c], "reales": len(reales), "hallados": hall,
                      "hallados_otra_clase": hall_cualquiera - hall, "predichos": len(preds),
                      "correctos": corr, "clase_equivocada": otra, "inventados": len(preds) - corr - otra,
                      "recuperacion": round(hall / len(reales), 3) if reales else None,
                      "precision": round(corr / len(preds), 3) if preds else None})
    return filas


# --------------------------------------------------------------------------
# 7 · Salidas para CloudCompare y Street View
# --------------------------------------------------------------------------
def escribir_laz(ruta: Path, pts: np.ndarray, clases: np.ndarray, extra: Dict[str, np.ndarray]) -> None:
    """Puntos UTM (f8) con `classification` y campos extra (f4) a un .laz 1.4."""
    h = laspy.LasHeader(version="1.4", point_format=7)
    for k, v in extra.items():
        h.add_extra_dim(laspy.ExtraBytesParams(name=k, type=v.dtype))
    h.scales = np.array([0.001] * 3)
    h.offsets = np.floor(pts.min(axis=0))
    las = laspy.LasData(h)
    las.x, las.y, las.z = pts[:, 0], pts[:, 1], pts[:, 2]
    las.classification = clases.astype("u1")
    for k, v in extra.items():
        las[k] = v
    las.write(str(ruta))


def utm_a_latlon(x: float, y: float) -> Tuple[float, float]:
    """EPSG:32718 (UTM 18S) -> lat, lon, para el enlace a Street View."""
    from pyproj import Transformer
    lon, lat = Transformer.from_crs(32718, 4326, always_xy=True).transform(x, y)
    return lat, lon


# --------------------------------------------------------------------------
# 8 · Postes compartidos entre bloques vecinos
# --------------------------------------------------------------------------
# Los bloques traen un anillo de contexto de 10 m, asi que un poste junto al borde
# aparece en los dos bloques vecinos. Si uno esta en train y el otro en test, el
# modelo ya vio ese poste y medirlo inflaria la metrica. No se toca el
# entrenamiento: esos postes salen de la evaluacion (medido el 31-oct-2026: 3).
def franja_neutra(P: np.ndarray, Y: np.ndarray, radio: float) -> np.ndarray:
    """Mascara de los voxeles de FONDO a menos de `radio` m en planta (XY) de un voxel de
    poste etiquetado. Sirve para no ensenarle al modelo que son fondo los trozos de poste
    que quedaron fuera del recorte (puntas, caras, abrazaderas pegadas al fuste): se sacan
    del entrenamiento, ni fondo ni poste. No cambia las etiquetas ni la evaluacion por objeto.
    Brazos o crucetas que se alejan mas que `radio` del fuste no los cubre."""
    poste = np.asarray(Y) > 0
    neutro = np.zeros(len(poste), dtype=bool)
    if radio <= 0 or not poste.any():
        return neutro
    fondo = np.flatnonzero(~poste)
    arbol = cKDTree(np.asarray(P[poste][:, :2], dtype="f8"))
    for a in range(0, len(fondo), 2_000_000):
        i = fondo[a:a + 2_000_000]
        d, _ = arbol.query(np.asarray(P[i][:, :2], dtype="f8"), distance_upper_bound=radio, workers=-1)
        neutro[i[np.isfinite(d)]] = True
    return neutro


def marcar_compartidos(datos: Dict[str, dict], bloques_referencia: Iterable[str], cargar, tol: float = 0.5) -> int:
    """Pone en cada `d` de `datos` la mascara `ignorar`: los postes etiquetados que
    tambien estan etiquetados en `bloques_referencia`. Devuelve cuantos postes son."""
    ref = []
    for b in bloques_referencia:
        r = cargar(b)
        ref.append(r["P"][r["Y"] > 0].astype("f8") + r["origen"])
    arbol = cKDTree(np.concatenate(ref))
    total = 0
    for d in datos.values():
        ign = np.zeros(len(d["Y"]), dtype=bool)
        P = d["P"].astype("f8")
        for g in objetos_columna(P, d["Y"] > 0, z_escala=1.0, eps=0.6, min_vox=10):
            if np.isfinite(arbol.query(P[g] + d["origen"], distance_upper_bound=tol)[0]).any():
                ign[g] = True
                total += 1
        d["ignorar"] = ign
    return total
