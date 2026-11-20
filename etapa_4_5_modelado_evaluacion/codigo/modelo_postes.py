"""La cabeza MLP como modelo de MLflow, sin depender de torch.

Entrada: rasgos de Sonata ya proyectados con la PCA (r0..r255, sin estandarizar).
Salida: probabilidad por voxel de fondo, poste_bt y poste_mt. Agrupar los voxeles en
postes es un paso posterior (`postes/evaluacion_postes.py`), igual que el umbral, que
viaja en los metadatos del modelo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from mlflow.pyfunc import PythonModel

COLUMNAS = [f"r{i}" for i in range(256)]
SALIDAS = ["p_fondo", "p_poste_bt", "p_poste_mt"]


def adelante(X: np.ndarray, z: dict) -> np.ndarray:
    """Misma cuenta que la red de torch en modo evaluacion (GELU exacta, sin dropout)."""
    from scipy.special import erf
    h = (X.astype("f4") - z["media"]) / z["desvio"]
    n = int(z["n_capas"])
    for i in range(n):
        h = h @ z[f"w{i}"].T + z[f"b{i}"]
        if i < n - 1:
            h = 0.5 * h * (1.0 + erf(h / np.sqrt(2.0)))
    h = h - h.max(axis=1, keepdims=True)
    e = np.exp(h)
    return e / e.sum(axis=1, keepdims=True)


class CabezaPostes(PythonModel):
    def load_context(self, context):
        with np.load(context.artifacts["pesos"]) as z:
            self.z = {k: z[k] for k in z.files}

    def predict(self, context, model_input, params=None):
        X = model_input[COLUMNAS].to_numpy() if isinstance(model_input, pd.DataFrame) else np.asarray(model_input)
        return pd.DataFrame(adelante(X, self.z), columns=SALIDAS)
