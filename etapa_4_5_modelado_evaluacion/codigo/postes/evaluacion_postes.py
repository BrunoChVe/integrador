"""Evaluacion por OBJETO, comun a todos los cuadernos de modelos.

Un modelo, sea cual sea, entrega para cada bloque una matriz `probs` de
(n_voxeles, 1 + n_clases) con el fondo en la columna 0. A partir de ahi todo
es igual para todos, y por eso vive aqui y no en cada cuaderno:

  * `barrido_umbral`     deteccion (poste o no) en validacion para cada umbral
  * `elegir_umbral`      el umbral que mas postes halla con precision >= 0,5
  * `evaluar_conjunto`   test: deteccion por bloque y tabla por clase
  * `objetos_detectados` cada candidato con altura, confianza, clase y etiqueta
  * `escribir_salidas`   .laz para CloudCompare y CSV con enlace a Street View

Cada bloque `d` es un dict con `bloque`, `escaneo`, `origen`, `P` (f4 relativo
al origen), `hag`, `Y`; lo devuelven `postes_datos.cargar_cache` (rasgos
geometricos) y `postes_datos.cargar_cache_sonata` (rasgos de Sonata).

La metrica es la del inventario: postes reales hallados y candidatos
inventados a 1 m, con la clase decidida por objeto (`postes_datos.
clasificar_objetos`). Lo que se compara entre modelos son estas tablas, no el
AP por voxel.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.metrics import precision_recall_fscore_support

from postes_datos import (NOMBRE_CLASE, clasificar_objetos, escribir_laz, metrica_objetos_clases,
                          metrica_objetos_columna, objetos_columna, utm_a_latlon)

COLS_CLASE = ["reales", "hallados", "hallados_otra_clase", "predichos", "correctos", "clase_equivocada", "inventados"]


def evaluar_bloque(d: dict, probs: np.ndarray, umbral: float, clases: Sequence[int],
                   con_filtro: bool = True) -> Tuple[dict, Optional[np.ndarray]]:
    """Deteccion por objeto (poste o no) en un bloque. Devuelve la fila de metricas
    y la clase de cada voxel (None si se evalua sin filtro de forma)."""
    ign = d.get("ignorar")          # postes compartidos con train: ni se buscan ni penalizan
    real = np.isin(d["Y"], clases)
    # Postes de una clase que este modelo no detecta (p. ej. los MT para un modelo solo BT):
    # tampoco se buscan ni penalizan. Un candidato sobre ellos no cuenta ni a favor ni en contra.
    otra = (d["Y"] > 0) & ~real
    if otra.any():
        ign = otra if ign is None else (ign | otra)
    if ign is not None:
        real = real & ~ign
    s = 1 - probs[:, 0]
    if con_filtro:
        clase, _ = clasificar_objetos(d["P"], d["hag"], probs, tuple(clases), umbral)
        if ign is not None and ign.any():
            arbol = cKDTree(d["P"][ign])
            for g in objetos_columna(d["P"], clase > 0):
                if np.isfinite(arbol.query(d["P"][g], distance_upper_bound=1.0)[0]).any():
                    clase[g] = 0
        pred = clase > 0
    else:
        clase, pred = None, s >= umbral
    m = metrica_objetos_columna(d["P"], pred, real, ignorar=ign)
    pr, rc, f1, _ = precision_recall_fscore_support(real, s >= umbral, average="binary", zero_division=0)
    return {**m, "prec_voxel": round(pr, 3), "recup_voxel": round(rc, 3), "f1_voxel": round(f1, 3)}, clase


def barrido_umbral(datos: Dict[str, dict], probs: Dict[str, np.ndarray], umbrales: Iterable[float],
                   clases: Sequence[int]) -> pd.DataFrame:
    """Deteccion total sobre `datos` para cada umbral, con y sin filtro de forma.
    La fila sin filtro es la cota: lo que el modelo halla antes de que el filtro tire nada."""
    filas = []
    for u in umbrales:
        for con_filtro in (True, False):
            tot = {"reales": 0, "hallados": 0, "predichos": 0, "correctos": 0}
            for b, d in datos.items():
                m, _ = evaluar_bloque(d, probs[b], u, clases, con_filtro)
                for k in tot:
                    tot[k] += m[k]
            filas.append({"umbral": u, "filtro_forma": con_filtro, **tot,
                          "recuperacion": tot["hallados"] / max(1, tot["reales"]),
                          "precision": tot["correctos"] / tot["predichos"] if tot["predichos"] else np.nan})
    return pd.DataFrame(filas)


def elegir_umbral(tabla: pd.DataFrame, min_precision: float = 0.5) -> float:
    """El umbral (con filtro) que mas postes halla entre los de precision >= min_precision;
    si ninguno llega, el de mas hallados. Avisa si cae en el borde de la rejilla."""
    con = tabla[tabla["filtro_forma"]].copy()
    con["clave"] = list(zip(con["precision"].fillna(0) >= min_precision, con["hallados"], con["precision"].fillna(0)))
    umbral = float(con.loc[con["clave"].idxmax(), "umbral"])
    if umbral <= con["umbral"].min() or umbral >= con["umbral"].max():
        print("AVISO: el umbral cae en el borde de la rejilla; las puntuaciones estan muy comprimidas "
              "(poca confianza o calibracion sesgada). Mira la curva PR y amplia UMBRALES.")
    return umbral


def graficar_umbral(tabla: pd.DataFrame, umbral: float, ruta: Optional[Path] = None, titulo: str = ""):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    for ff, estilo in ((True, "-"), (False, "--")):
        t_ = tabla[tabla["filtro_forma"] == ff]
        suf = "con" if ff else "sin"
        ax[0].plot(t_["umbral"], t_["recuperacion"], estilo, color="C0", label=f"recuperación {suf} filtro")
        ax[0].plot(t_["umbral"], t_["precision"], estilo, color="C1", label=f"precisión {suf} filtro")
        ax[1].plot(t_["umbral"], t_["predichos"], estilo, color="C3", label=f"candidatos {suf} filtro")
    for a in ax:
        a.axvline(umbral, color="k", ls=":"); a.set_xlabel("umbral"); a.legend(fontsize=8)
    ax[0].set_title(f"Detección por objeto · validación {titulo}".strip())
    ax[1].set_title("Candidatos predichos"); ax[1].set_yscale("log")
    plt.tight_layout()
    if ruta:
        plt.savefig(ruta)
    plt.show()


def evaluar_conjunto(datos: Dict[str, dict], probs: Dict[str, np.ndarray], umbral: float,
                     clases: Sequence[int]) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, np.ndarray]]:
    """Deteccion por bloque (con fila TOTAL), tabla por clase y clase de cada voxel por bloque."""
    filas, por_clase, clases_pred = [], [], {}
    for b, d in datos.items():
        m, clase = evaluar_bloque(d, probs[b], umbral, clases, True)
        filas.append({"bloque": b, "escaneo": d["escaneo"][:6], **m})
        Y = d["Y"] if d.get("ignorar") is None else np.where(d["ignorar"], 0, d["Y"])
        por_clase += [{"bloque": b, **f} for f in metrica_objetos_clases(d["P"], clase, Y, tuple(clases))]
        clases_pred[b] = clase
    t_ = pd.DataFrame(filas)
    tot = t_[["reales", "hallados", "predichos", "correctos"]].sum()
    total = {"bloque": "TOTAL", "escaneo": "", **tot.to_dict(),
             "recuperacion": round(tot["hallados"] / max(1, tot["reales"]), 3),
             "precision": round(tot["correctos"] / tot["predichos"], 3) if tot["predichos"] else None}
    tc = pd.DataFrame(por_clase).groupby("clase", sort=False)[COLS_CLASE].sum().reset_index()
    tc["recuperacion"] = (tc["hallados"] / tc["reales"].clip(lower=1)).round(3)
    tc["precision"] = (tc["correctos"] / tc["predichos"].replace(0, np.nan)).round(3)
    return pd.concat([t_, pd.DataFrame([total])], ignore_index=True), tc, clases_pred


def objetos_detectados(d: dict, clase: np.ndarray, s: np.ndarray, tol: float = 1.0) -> List[dict]:
    """Un candidato por objeto: posicion UTM, altura, confianza media, clase predicha y
    etiqueta del poste real mas cercano (`fondo` si no hay ninguno a `tol` m)."""
    etiquetado = d["Y"] > 0
    arbol_real = cKDTree(d["P"][etiquetado]) if etiquetado.any() else None
    Y_real = d["Y"][etiquetado]
    filas = []
    for g in objetos_columna(d["P"], clase > 0):
        etiqueta = 0
        if arbol_real is not None:
            dist, j = arbol_real.query(d["P"][g], distance_upper_bound=tol)
            ok = np.isfinite(dist)
            if ok.any():
                etiqueta = int(np.bincount(Y_real[j[ok]]).argmax())
        xy = np.median(d["P"][g, :2], axis=0) + d["origen"][:2]
        filas.append({"bloque": d["bloque"], "x_utm": round(float(xy[0]), 2), "y_utm": round(float(xy[1]), 2),
                      "altura_m": round(float(d["hag"][g].max()), 1), "voxeles": len(g),
                      "confianza": round(float(s[g].mean()), 3),
                      "clase_predicha": NOMBRE_CLASE[int(np.bincount(clase[g]).argmax())],
                      "etiqueta": NOMBRE_CLASE[etiqueta], "idx": g})
    return filas


def tabla_candidatos(detectados: List[dict]) -> pd.DataFrame:
    """La tabla que va al CSV: ordenada por bloque y confianza, con `coincide` y Street View."""
    if not detectados:
        return pd.DataFrame()
    filas = []
    for r in sorted(detectados, key=lambda r: (r["bloque"], -r["confianza"])):
        lat, lon = utm_a_latlon(r["x_utm"], r["y_utm"])
        filas.append({k: r[k] for k in ("bloque", "x_utm", "y_utm", "altura_m", "voxeles", "confianza", "clase_predicha", "etiqueta")}
                     | {"coincide": r["etiqueta"] == r["clase_predicha"],
                        "street_view": f"https://www.google.com/maps?q&layer=c&cbll={lat:.6f},{lon:.6f}"})
    return pd.DataFrame(filas)


def escribir_salidas(salida: Path, etiqueta_modelo: str, datos: Dict[str, dict], clases_pred: Dict[str, np.ndarray],
                     probs: Dict[str, np.ndarray], nombres: Sequence[str]) -> pd.DataFrame:
    """Por bloque: `<bloque>_PRED_<modelo>.laz` con la clase por voxel y las probabilidades,
    y `<bloque>_candidatos_<modelo>.csv`. Devuelve la tabla de candidatos de todos los bloques."""
    detectados = []
    for b, d in datos.items():
        clase, p = clases_pred[b], probs[b]
        m = clase > 0
        if not m.any():
            print(f"{b}: sin predicciones"); continue
        extra = {"confianza": (1 - p[m, 0]).astype("f4"), "hag": d["hag"][m].astype("f4")}
        for i, nombre in enumerate(nombres[1:], start=1):
            extra[f"p_{nombre.replace('poste_', '')}"] = p[m, i].astype("f4")
        escribir_laz(salida / f"{b}_PRED_{etiqueta_modelo}.laz", d["P"][m].astype("f8") + d["origen"], clase[m], extra)
        por_clase = ", ".join(f"{int((clase == c).sum()):,} {NOMBRE_CLASE[c]}" for c in np.unique(clase[m]))
        print(f"{b}: {int(m.sum()):,} voxeles de poste ({por_clase}) -> {b}_PRED_{etiqueta_modelo}.laz")
        detectados += objetos_detectados(d, clase, 1 - p[:, 0])
    cand = tabla_candidatos(detectados)
    for b, t_ in cand.groupby("bloque") if len(cand) else []:
        t_.to_csv(salida / f"{b}_candidatos_{etiqueta_modelo}.csv", index=False, encoding="utf-8")
    return cand


def comparar_resumenes(salida: Path, patron: str = "*/resumen_*.json") -> pd.DataFrame:
    """Una fila por corrida con lo que hay en su `resumen_<modelo>.json`: deteccion en test
    y recuperacion/precision por clase. `salida` es la carpeta que contiene las carpetas
    `corrida<N>_...`. Para poner los cuadernos y las corridas uno al lado del otro."""
    import json
    filas = []
    for ruta in sorted(Path(salida).glob(patron), key=lambda r: r.stat().st_mtime):
        r = json.loads(ruta.read_text(encoding="utf-8"))
        tot = next((f for f in r.get("test", []) if f.get("bloque") == "TOTAL"), {})
        fila = {"corrida": ruta.parent.name, "modelo": r.get("etiqueta_modelo", ruta.stem),
                "fecha": r.get("fecha", ""), "umbral": r.get("umbral"),
                **{k: tot.get(k) for k in ("reales", "hallados", "predichos", "correctos", "recuperacion", "precision")}}
        for c in r.get("test_por_clase", []):
            fila[f"recup_{c['clase']}"] = c.get("recuperacion"); fila[f"prec_{c['clase']}"] = c.get("precision")
        filas.append(fila)
    return pd.DataFrame(filas)
