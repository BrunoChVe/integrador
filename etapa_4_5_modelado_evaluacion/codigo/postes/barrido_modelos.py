"""Barrido de hiperparametros sobre VALIDACION, sin tocar test.

Corre en el entorno con GPU (F:\\venvs\\sonata) y solo escribe un JSON. Lo registra
en MLflow `codigo/registrar_experimentos.py`, que corre en el entorno del proyecto:
el backbone no entra en ese entorno.

    python codigo/postes/barrido_modelos.py

Tres familias, todas medidas igual (deteccion por objeto, umbral elegido en validacion):
    geo_hgb        rasgos geometricos + HistGradientBoosting
    sonata_lineal  rasgos de Sonata + cabeza lineal
    sonata_mlp     rasgos de Sonata + cabeza MLP no lineal
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import postes_datos as pdt  # noqa: E402
from evaluacion_postes import barrido_umbral, elegir_umbral  # noqa: E402

SEMILLA = 0
CLASES = (5, 12)
N = 1 + len(CLASES)
INDICE = np.zeros(256, dtype="i8")
for i, c in enumerate(CLASES):
    INDICE[c] = i + 1
UMBRALES = np.round(np.concatenate([[0.01, 0.02, 0.03], np.arange(0.05, 0.96, 0.05)]), 2)
MAX_FONDO_TRAIN, MAX_FONDO_VAL = 400_000, 200_000
EPOCAS, PACIENCIA, LOTE, LR = 30, 6, 8192, 5e-4
DEV = "cuda" if torch.cuda.is_available() else "cpu"
MAX_VOX_POSTE = 300_000
SALIDA = AQUI.parents[1] / "resultados" / "experimentos" / "barrido_v2.json"

REJILLA = {
    "geo_hgb": [dict(learning_rate=0.1, max_leaf_nodes=31, max_iter=300),
                dict(learning_rate=0.05, max_leaf_nodes=31, max_iter=300),
                dict(learning_rate=0.1, max_leaf_nodes=63, max_iter=150)],
    "sonata_lineal": [dict(ocultas=(), dropout=0.0, wd=1e-3), dict(ocultas=(), dropout=0.0, wd=1e-2)],
    "sonata_mlp": [dict(ocultas=(256, 128), dropout=0.3, wd=1e-3), dict(ocultas=(128,), dropout=0.5, wd=1e-2),
                   dict(ocultas=(512, 256), dropout=0.3, wd=1e-3), dict(ocultas=(64,), dropout=0.3, wd=1e-3)],
}


def metricas_val(datos, probs) -> dict:
    # Con mas de MAX_VOX_POSTE voxeles marcados el agrupamiento agota la memoria. A esos
    # umbrales el modelo marca fachadas enteras: nunca serian el umbral elegido.
    validos = [u for u in UMBRALES if max(int(((1 - p[:, 0]) >= u).sum()) for p in probs.values()) <= MAX_VOX_POSTE]
    tabla = barrido_umbral(datos, probs, validos, CLASES)
    u = elegir_umbral(tabla)
    f = tabla[tabla["filtro_forma"] & (tabla["umbral"] == u)].iloc[0]
    return {"umbral": u, **{k: int(f[k]) for k in ("reales", "hallados", "predichos", "correctos")},
            "recuperacion": float(f["recuperacion"]), "precision": float(f["precision"])}


def muestra(bloques, max_fondo, semilla):
    rng = np.random.default_rng(semilla)
    F, Y = [], []
    for b in bloques:
        d = pdt.cargar_cache_sonata(b)
        fondo = np.flatnonzero(d["Y"] == 0)
        if len(fondo) > max_fondo:
            fondo = rng.choice(fondo, max_fondo, replace=False)
        idx = np.sort(np.concatenate([np.flatnonzero(np.isin(d["Y"], CLASES)), fondo]))
        F.append(np.asarray(d["F"][idx])); Y.append(d["Y"][idx])
    return np.concatenate(F), INDICE[np.concatenate(Y)]


def cabeza(d_in, ocultas, dropout):
    capas, d = [], d_in
    for h in ocultas:
        capas += [nn.Linear(d, h), nn.GELU(), nn.Dropout(dropout)]
        d = h
    return nn.Sequential(*capas, nn.Linear(d, N)).to(DEV)


def barrer_sonata(particion, datos_val, ind) -> list:
    Ftr, ytr = muestra(particion["train"], MAX_FONDO_TRAIN, SEMILLA)
    Fva, yva = muestra(particion["val"], MAX_FONDO_VAL, SEMILLA + 1)
    media, desvio = Ftr.astype("f4").mean(0), Ftr.astype("f4").std(0) + 1e-6
    est = lambda F: (torch.from_numpy(np.array(F, dtype="f4")) - torch.from_numpy(media)) / torch.from_numpy(desvio)
    Xtr, Xva = est(Ftr).to(DEV).half(), est(Fva).to(DEV).half()
    ytr_t, yva_t = torch.from_numpy(ytr).to(DEV), torch.from_numpy(yva).to(DEV)
    n = torch.bincount(ytr_t, minlength=N).float()
    pesos = torch.where(n > 0, torch.sqrt(n[0] / n.clamp(min=1)), torch.ones_like(n)); pesos[0] = 1.0
    perdida = nn.CrossEntropyLoss(weight=pesos)
    out = []
    for familia in ("sonata_lineal", "sonata_mlp"):
        for h in REJILLA[familia]:
            t0 = time.perf_counter()
            torch.manual_seed(SEMILLA)
            m = cabeza(Xtr.shape[1], h["ocultas"], h["dropout"])
            opt = torch.optim.AdamW(m.parameters(), lr=LR, weight_decay=h["wd"])
            sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCAS)
            mejor, sin_mejora, estado, ep_mejor = -1.0, 0, None, 0
            for ep in range(1, EPOCAS + 1):
                m.train()
                perm = torch.randperm(len(Xtr), device=DEV)
                for a in range(0, len(perm), LOTE):
                    b = perm[a:a + LOTE]
                    loss = perdida(m(Xtr[b].float()), ytr_t[b])
                    opt.zero_grad(set_to_none=True); loss.backward(); opt.step()
                sched.step()
                m.eval()
                with torch.no_grad():
                    p = torch.cat([torch.softmax(m(Xva[a:a + 65536].float()), 1) for a in range(0, len(Xva), 65536)]).cpu().numpy()
                ap = average_precision_score(yva == 1, p[:, 1])     # validacion no tiene postes de MT
                if ap > mejor:
                    mejor, ep_mejor, sin_mejora = ap, ep, 0
                    estado = {k: v.detach().clone() for k, v in m.state_dict().items()}
                else:
                    sin_mejora += 1
                    if sin_mejora >= PACIENCIA:
                        break
            m.load_state_dict(estado); m.eval()
            probs = {}
            with torch.no_grad():
                for b, d in datos_val.items():
                    s = np.empty((len(d["Y"]), N), dtype="f4")
                    for a in range(0, len(s), 400_000):
                        s[a:a + 400_000] = torch.softmax(m(est(d["F"][a:a + 400_000]).to(DEV)), 1).cpu().numpy()
                    probs[b] = s
            fila = {"familia": familia, "hiper": {**h, "ocultas": list(h["ocultas"])}, "ap_val": float(mejor),
                    "mejor_epoca": ep_mejor, **metricas_val(datos_val, probs), "segundos": round(time.perf_counter() - t0)}
            print(fila, flush=True); out.append(fila); ind(out)
    return out


def barrer_hgb(particion, ind) -> list:
    Xg, Yg, _ = pdt.conjunto(particion["train"], max_fondo=MAX_FONDO_TRAIN, semilla=SEMILLA)
    yg = INDICE[Yg]
    n = np.bincount(yg, minlength=N).astype("f8")
    w = np.where(n > 0, np.sqrt(n[0] / np.maximum(n, 1)), 1.0); w[0] = 1.0
    datos = {b: pdt.cargar_cache(b) for b in particion["val"]}
    excl = pdt.marcar_compartidos(datos, particion["train"], pdt.cargar_cache)
    out = []
    for h in REJILLA["geo_hgb"]:
        t0 = time.perf_counter()
        hgb = HistGradientBoostingClassifier(**h, early_stopping=False, random_state=SEMILLA).fit(Xg, yg, sample_weight=w[yg])
        probs = {}
        for b, d in datos.items():
            p = np.zeros((len(d["X"]), N), dtype="f4")
            p[:, hgb.classes_.astype(int)] = hgb.predict_proba(d["X"])
            probs[b] = p
        fila = {"familia": "geo_hgb", "hiper": h, **metricas_val(datos, probs), "segundos": round(time.perf_counter() - t0)}
        print(fila, flush=True); out.append(fila); ind(out)
    print("postes de validacion excluidos:", excl)
    return out


def main() -> None:
    particion = pdt.particion_por_carpetas()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    resultado = {"particion": particion, "conjunto": "valid", "etiquetas": pdt.huella_etiquetas(), "filas": []}

    def guardar(_=None):
        SALIDA.write_text(json.dumps(resultado, indent=1, ensure_ascii=False), encoding="utf-8")

    def anotar(base):
        def f(filas):
            resultado["filas"] = base + filas
            guardar()
        return f

    previo = json.loads(SALIDA.read_text(encoding="utf-8"))["filas"] if SALIDA.exists() else []
    hgb = [f for f in previo if f["familia"] == "geo_hgb"]
    if len(hgb) < len(REJILLA["geo_hgb"]):
        hgb = barrer_hgb(particion, anotar([]))
    datos_val = {b: pdt.cargar_cache_sonata(b) for b in particion["val"]}
    pdt.marcar_compartidos(datos_val, particion["train"], pdt.cargar_cache_sonata)
    barrer_sonata(particion, datos_val, anotar(hgb))
    print("->", SALIDA)


if __name__ == "__main__":
    main()
