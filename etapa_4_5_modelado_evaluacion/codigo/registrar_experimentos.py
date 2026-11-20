"""Registra en MLflow todos los experimentos de deteccion de postes.

    python codigo/registrar_experimentos.py         # todas las versiones, sobre una base vacia
    python codigo/registrar_experimentos.py v5 v7   # solo esas versiones, sin duplicar las anteriores

Los modelos se entrenan en el entorno con GPU (cuadernos/ y codigo/postes/) y dejan
sus resultados en resultados/experimentos/. Este script los lee y crea una ejecucion
por experimento, con las mismas metricas y la misma procedencia. Las etiquetas
`datos_md5` salen del puntero DVC en la etiqueta de Git de cada version de datos.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import yaml
from mlflow.models import infer_signature

from comun import AQUI, config, procedencia

sys.path.insert(0, str(AQUI / "codigo"))
from modelo_postes import COLUMNAS, CabezaPostes, adelante  # noqa: E402

R = AQUI / "resultados" / "experimentos"
cfg = config()
mlflow.set_tracking_uri(cfg["mlflow"]["tracking_uri"])
mlflow.set_experiment(cfg["mlflow"]["experimento"])


def md5_de(tag: str) -> dict:
    txt = subprocess.run(["git", "show", f"{tag}:datos/crudo/etiquetado.dvc"], capture_output=True, text=True, cwd=AQUI, check=True).stdout
    s = yaml.safe_load(txt)["outs"][0]
    return {"datos_md5": s["md5"], "datos_bytes": str(s["size"]), "git_tag_datos": tag}


TODAS = ("v1", "v2", "v3", "v4", "v5", "v7")
SOLO = sys.argv[1:] or list(TODAS)
assert set(SOLO) <= set(TODAS), f"versiones validas: {TODAS}"
VERSIONES = {v: md5_de(f"etiquetas-{v}") for v in TODAS}
BASE = procedencia(cfg)


def tags(version, modelo, conjunto, tipo="experimento", **extra):
    return {**BASE, **VERSIONES[version], "version_datos": version, "tipo": tipo, "modelo": modelo,
            "conjunto_evaluacion": conjunto, "tarea": cfg["tarea"], **extra}


def met(d: dict) -> dict:
    """Las mismas metricas en todas las ejecuciones."""
    h, re, pr, co = d["hallados"], d["reales"], d["predichos"], d["correctos"]
    rec = h / re if re else 0.0
    pre = co / pr if pr else 0.0
    return {"recuperacion": rec, "precision": pre, "f1": 2 * rec * pre / (rec + pre) if rec + pre else 0.0,
            "reales": re, "hallados": h, "predichos": pr, "correctos": co}


def fila_val(r: dict) -> dict:
    return next(f for f in r["validacion_umbral"] if f["filtro_forma"] and f["umbral"] == r["umbral"])


def total(r: dict) -> dict:
    return next(f for f in r["test"] if f["bloque"] == "TOTAL")


def por_clase(r: dict) -> dict:
    out = {}
    for c in r.get("test_por_clase", []):
        out[f"recuperacion_{c['clase']}"] = c["recuperacion"] or 0.0
        out[f"hallados_{c['clase']}"] = c["hallados"]
        out[f"reales_{c['clase']}"] = c["reales"]
    return out


def correr(nombre, t, params, m, artefactos=(), historia=None, nested=False, modelo_fn=None):
    with mlflow.start_run(run_name=nombre, nested=nested) as run:
        mlflow.set_tags(t)
        mlflow.log_params({k: str(v) for k, v in params.items()})
        mlflow.log_metrics({k: float(v) for k, v in m.items() if v is not None})
        for f in artefactos:
            if (R / f).exists():
                mlflow.log_artifact(str(R / f))
        for h in historia or []:
            mlflow.log_metrics({k: float(h[k]) for k in ("loss_train", "loss_val", "ap_val") if h.get(k) == h.get(k) and k in h}, step=int(h["epoca"]))
        if modelo_fn:
            modelo_fn()
        print(f"{run.info.run_id[:8]} {nombre}: {t['conjunto_evaluacion']} rec={m['recuperacion']:.3f} prec={m['precision']:.3f}")
        return run.info.run_id


def par(version, modelo, sufijo, r, params, artefactos, historia=None, extra=None, modelo_fn=None):
    """Una ejecucion en valid (umbral elegido ahi) y otra en test (solo candidatos finales)."""
    extra = extra or {}
    p = {"modelo": modelo, "umbral": r["umbral"], "particion_test": ",".join(r["particion"]["test"]), **params}
    id_val = None
    if "validacion_umbral" in r:
        id_val = correr(f"{modelo}{sufijo}-{version}-valid", tags(version, modelo, "valid", **extra), p, met(fila_val(r)),
                        artefactos, historia, modelo_fn=modelo_fn)
    correr(f"{modelo}{sufijo}-{version}-test", tags(version, modelo, "test", **extra), p, {**met(total(r)), **por_clase(r)}, artefactos)
    return id_val


if "v1" in SOLO:
    # ---- v1: etiquetas del 30-oct. Registradas a posteriori desde sus resumenes.
    NOTA = {"origen": "registro_a_posteriori", "alcance": "solo_bt", "particion": "anterior_por_bloque"}
    r1 = json.loads((R / "v1_sonata_256x128.json").read_text(encoding="utf-8"))
    base = r1["baseline_geometrico"]
    correr("geo_hgb-v1-test", tags("v1", "geo_hgb", "test", tipo="experimento", **NOTA), {"modelo": "geo_hgb", "umbral": base["umbral"]}, met(base["test"]))
    for f, suf, cab in (("v1_sonata_256x128", "-256x128", "256x128, dropout 0.3, wd 1e-3"), ("v1_sonata_128", "-128", "128, dropout 0.5, wd 1e-2")):
        r = json.loads((R / f"{f}.json").read_text(encoding="utf-8"))
        par("v1", "sonata_mlp", suf, r, {"cabeza": cab, "fecha_corrida": "2026-10-30", **{k: r["config"][k] for k in ("lr", "wd", "dropout")}},
            [f"{f}.json", f"{f}_curvas.png", f"{f}_umbral.png"], r["historia"], NOTA)

if "v2" in SOLO:
    # ---- v2: baseline primero, luego barridos en validacion y candidatos finales
    EXTRA = {"alcance": "bt_y_mt", "particion": "carpetas_train_test"}
    rg = json.loads((R / "v2_geo_hgb.json").read_text(encoding="utf-8"))
    par("v2", "geo_hgb", "", rg, {"rasgos": 20, **{k: rg["config"][k] for k in ("learning_rate", "max_leaf_nodes", "max_iter")}},
        ["v2_geo_hgb.json", "v2_geo_hgb_curvas.png", "v2_geo_hgb_umbral.png"], extra=EXTRA)

    barrido = json.loads((R / "barrido_v2.json").read_text(encoding="utf-8"))
    for familia, grupo in pd.DataFrame(barrido["filas"]).groupby("familia", sort=False):
        with mlflow.start_run(run_name=f"barrido-{familia}") as madre:
            mlflow.set_tags({**tags("v2", familia, "valid", tipo="barrido", **EXTRA)})
            mlflow.log_param("n_combinaciones", len(grupo))
            mejor = 0.0
            for _, f in grupo.iterrows():
                etiqueta = "-".join(f"{k}={v}" for k, v in f["hiper"].items()).replace(" ", "")
                m = met(f.to_dict())
                if f.get("ap_val") == f.get("ap_val"):
                    m["ap_val"] = f["ap_val"]
                mejor = max(mejor, m["recuperacion"])
                correr(f"{familia}-{etiqueta}", tags("v2", familia, "valid", barrido=madre.info.run_id, **EXTRA),
                       {"modelo": familia, "umbral": f["umbral"], **f["hiper"]}, m, nested=True)
            mlflow.log_metric("mejor_recuperacion", mejor)

    rs = json.loads((R / "v2_sonata_mlp_btmt.json").read_text(encoding="utf-8"))


    def registrar_modelo():
        z = np.load(R / "v2_cabeza_comprobacion.npz")
        with np.load(R / "v2_cabeza_pesos.npz") as w:
            pesos = {k: w[k] for k in w.files}
        dif = float(np.abs(adelante(z["X"], pesos) - z["p"]).max())
        assert dif < 1e-3, dif
        mlflow.log_metric("dif_max_con_torch", dif)
        ej = pd.DataFrame(z["X"][:3], columns=COLUMNAS)
        salida = pd.DataFrame(adelante(z["X"][:3], pesos), columns=["p_fondo", "p_poste_bt", "p_poste_mt"])
        # DVC deja sus archivos en solo lectura y MLflow, en Windows, no podria borrar su copia temporal.
        with tempfile.TemporaryDirectory() as tmp:
            copia = Path(tmp) / "v2_cabeza_pesos.npz"
            copia.write_bytes((R / "v2_cabeza_pesos.npz").read_bytes())
            mlflow.pyfunc.log_model(name="modelo", python_model=CabezaPostes(), artifacts={"pesos": str(copia)},
                                    code_paths=[str(AQUI / "codigo" / "modelo_postes.py")],
                                    signature=infer_signature(ej, salida), input_example=ej,
                                    metadata={"umbral": float(pesos["umbral"]), "licencia_pesos_backbone": "CC-BY-NC 4.0"})


    id_campeon = par("v2", "sonata_mlp", "-256x128", rs,
                     {"cabeza": "256x128, dropout 0.3, wd 1e-3", "ronda_final": rs["ronda_final"], "mejor_epoca": rs["mejor_epoca"],
                      **{k: rs["config"][k] for k in ("lr", "wd", "dropout", "lote")}},
                     ["v2_sonata_mlp_btmt.json", "v2_sonata_mlp_btmt_curvas.png", "v2_sonata_mlp_btmt_umbral.png"],
                     rs["historia"], EXTRA, modelo_fn=registrar_modelo)
    (AQUI / "resultados" / "run_campeon.txt").write_text(id_campeon, encoding="utf-8")
    print("campeon candidato:", id_campeon)

# ---- v3: 28 recortes en 3 escaneos, solo recortes (la nube sale de datos/intermedio/01_bloques).
# Un modelo por clase: corrida 9 (solo BT) y corrida 10 (solo MT) del 7-nov, lr 5e-5.
# No se registra como modelo: el campeon sigue siendo el de v2, que detecta BT y MT a la vez.
if "v3" in SOLO:
    for clase in ("bt", "mt"):
        f = f"v3_sonata_mlp_solo_{clase}"
        r = json.loads((R / f"{f}.json").read_text(encoding="utf-8"))
        par("v3", f"sonata_mlp_solo_{clase}", "-256x128", r,
            {"cabeza": "256x128, dropout 0.3, wd 1e-3", "clase_objetivo": r["config"]["clase_objetivo"],
             "ronda_final": r["ronda_final"], "mejor_epoca": r["mejor_epoca"], "fecha_corrida": r["fecha"],
             **{k: r["config"][k] for k in ("lr", "wd", "dropout", "lote", "franja_neutra_m", "criterio_seleccion")}},
            [f"{f}.json", f"{f}_curvas.png", f"{f}_umbral.png", f"{f}.pt"], r["historia"],
            {"alcance": f"solo_{clase}", "particion": "carpetas_train_test", "etiquetas_md5": r["etiquetas"]["md5"]})

# ---- v4: 45 recortes en 4 escaneos, con una carpeta por clase (<escaneo>/poste_bt|poste_mt/<train|test>):
# cada modelo toma la particion de su clase. BT suma 17 recortes en PACHAP01MT0108202502 (204 postes en
# train); MT suma AVP01MT2611202502 y deja fuera los MT de Pachacamac (solo Ate). Corridas 15 (BT) y 14 (MT)
# del 11-nov, entrenadas en Khipu (CPU) con scripts/khipu/. El campeon sigue siendo el de v2.
if "v4" in SOLO:
    for clase in ("bt", "mt"):
        f = f"v4_sonata_mlp_solo_{clase}"
        r = json.loads((R / f"{f}.json").read_text(encoding="utf-8"))
        par("v4", f"sonata_mlp_solo_{clase}", "-256x128", r,
            {"cabeza": "256x128, dropout 0.3, wd 1e-3", "clase_objetivo": r["config"]["clase_objetivo"],
             "ronda_final": r["ronda_final"], "mejor_epoca": r["mejor_epoca"], "fecha_corrida": r["fecha"],
             **{k: r["config"][k] for k in ("lr", "wd", "dropout", "lote", "franja_neutra_m", "criterio_seleccion")}},
            [f"{f}.json", f"{f}_curvas.png", f"{f}_umbral.png", f"{f}.pt"], r["historia"],
            {"alcance": f"solo_{clase}", "particion": "carpetas_por_clase", "etiquetas_md5": r["etiquetas"]["md5"],
             "entorno": "khipu_cpu"})

# ---- v5: 51 recortes; MT suma 6 bloques en AVP01MT2611202502 (55 postes MT en train). Solo se entreno MT
# (corrida 16 del 11-nov, Khipu CPU): el BT de v5 es el mismo de v4.
# ---- v7: 74 recortes; MT de Pachacamac (escaneos 01-03) y 3 bloques mas de AVP02, BT del escaneo 03
# (212 postes BT y 88 MT en train). Dos pares del 14-nov, Khipu CPU:
#   corridas 18 (BT) y 19 (MT): mismo metodo que v4;
#   corridas 20 (BT) y 21 (MT), sufijo -neg: los negativos duros dejan fuera el fondo con puntuacion >= 0,5
#   y forma de poste (posibles postes sin etiquetar, listados en candidatos_sin_etiqueta.csv).
# El BT de la corrida 18 uso los mismos recortes BT que v7 (v7 solo sumo recortes MT despues).
# v6 (56 recortes) no tiene corridas propias. El campeon sigue siendo el de v2.
for version, archivos in (("v5", (("mt", ""),)), ("v7", (("bt", ""), ("mt", ""), ("bt", "_neg"), ("mt", "_neg")))):
    if version not in SOLO:
        continue
    for clase, neg in archivos:
        f = f"{version}_sonata_mlp_solo_{clase}{neg}"
        r = json.loads((R / f"{f}.json").read_text(encoding="utf-8"))
        cfg_r = r["config"]
        par(version, f"sonata_mlp_solo_{clase}", "-256x128" + ("-neg" if neg else ""), r,
            {"cabeza": "256x128, dropout 0.3, wd 1e-3", "clase_objetivo": cfg_r["clase_objetivo"],
             "ronda_final": r["ronda_final"], "mejor_epoca": r["mejor_epoca"], "fecha_corrida": r["fecha"],
             "umbral_sin_etiqueta": cfg_r.get("umbral_sin_etiqueta", 0), "candidatos_sin_etiqueta": cfg_r.get("candidatos_sin_etiqueta", 0),
             **{k: cfg_r[k] for k in ("lr", "wd", "dropout", "lote", "franja_neutra_m", "criterio_seleccion")}},
            [f"{f}.json", f"{f}_curvas.png", f"{f}_umbral.png", f"{f}.pt"], r["historia"],
            {"alcance": f"solo_{clase}", "particion": "carpetas_por_clase", "etiquetas_md5": r["etiquetas"]["md5"],
             "entorno": "khipu_cpu", "negativos_sin_candidatos": "si" if neg else "no"})
