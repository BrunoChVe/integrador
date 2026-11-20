"""Pasa la cabeza de torch a un .npz que MLflow carga sin torch, y comprueba que da lo mismo.

Corre en el entorno con torch:
    python codigo/postes/exportar_cabeza.py
"""
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

CODIGO = Path(__file__).resolve().parents[1]
R = CODIGO.parent / "resultados" / "experimentos"

ck = torch.load(R / "v2_sonata_mlp_btmt.pt", map_location="cpu", weights_only=False)
capas = sorted(k for k in ck["estado"] if k.endswith(".weight"))
capas = sorted(capas, key=lambda k: int(k.split(".")[1]))
z = {"media": np.asarray(ck["media"], "f4"), "desvio": np.asarray(ck["desvio"], "f4"),
     "n_capas": len(capas), "umbral": ck["umbral"], "clases": np.array(ck["clases"])}
for i, k in enumerate(capas):
    z[f"w{i}"] = ck["estado"][k].numpy()
    z[f"b{i}"] = ck["estado"][k.replace("weight", "bias")].numpy()
np.savez(R / "v2_cabeza_pesos.npz", **z)

# Comprobacion: misma salida que la red original sobre rasgos al azar
mods, d = [], ck["d_in"]
for h in ck["ocultas"]:
    mods += [nn.Linear(d, h), nn.GELU(), nn.Dropout(ck["dropout"])]
    d = h
red = nn.Sequential(*mods, nn.Linear(d, ck["n_clases"]))
red.load_state_dict({k.removeprefix("red."): v for k, v in ck["estado"].items()})
red.eval()
X = np.random.default_rng(0).normal(z["media"], z["desvio"], (2000, ck["d_in"])).astype("f4")
with torch.no_grad():
    t = torch.softmax(red(torch.from_numpy((X - z["media"]) / z["desvio"])), 1).numpy()
np.savez(R / "v2_cabeza_comprobacion.npz", X=X[:200], p=t[:200])
print("capas", len(capas), "umbral", ck["umbral"], "->", R / "v2_cabeza_pesos.npz")
