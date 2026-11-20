"""Utilidades compartidas por los scripts de modelado y evaluación.

Todo script de esta carpeta se ejecuta desde `etapa_4_5_modelado_evaluacion/`,
lee el vocabulario de `experimento.yaml` y registra en MLflow. El código está
pensado para tablas (la salida de la etapa 3); en proyectos de texto, imagen o
series se reemplazan `cargar_particiones` y `crear_modelo` conservando el
contrato: mismas métricas, mismas etiquetas, misma procedencia.
"""
from __future__ import annotations

import pathlib
import subprocess

import numpy as np
import pandas as pd
import yaml
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (accuracy_score, average_precision_score, f1_score, mean_absolute_error,
                             mean_absolute_percentage_error, mean_squared_error, precision_score, r2_score,
                             recall_score, roc_auc_score)
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

AQUI = pathlib.Path(__file__).resolve().parent.parent  # etapa_4_5_modelado_evaluacion/
RESULTADOS = AQUI / "resultados"


def config() -> dict:
    with open(AQUI / "experimento.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ----------------------------------------------------------------------------
# Procedencia: el puente DVC → MLflow. Responde «qué bytes exactos de datos
# entraron aquí», la pregunta que ninguna métrica contesta.
# ----------------------------------------------------------------------------
def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, cwd=AQUI).stdout.strip()
    except FileNotFoundError:
        return ""


def procedencia(cfg: dict) -> dict:
    tags = {"git_commit": _git("rev-parse", "--short", "HEAD") or "sin-git",
            "git_tag": _git("describe", "--tags", "--always") or "sin-tag",
            "git_limpio": "si" if _git("status", "--porcelain") == "" else "NO",
            "version_datos": str(cfg["datos"]["version_datos"])}
    puntero = (AQUI / cfg["datos"]["puntero_dvc"]).resolve()
    try:
        with open(puntero, encoding="utf-8") as f:
            salida = yaml.safe_load(f)["outs"][0]
        tags.update({"datos_md5": salida["md5"], "datos_bytes": str(salida["size"])})
    except (FileNotFoundError, KeyError, TypeError):
        tags["datos_md5"] = "sin-dvc"
    return tags


# ----------------------------------------------------------------------------
# Datos
# ----------------------------------------------------------------------------
def cargar_particiones(cfg: dict) -> dict[str, tuple[pd.DataFrame, pd.Series]]:
    carpeta = (AQUI / cfg["datos"]["carpeta"]).resolve()
    objetivo = cfg["datos"]["objetivo"]
    partes = {}
    for nombre in ("train", "valid", "test"):
        ruta = carpeta / f"{nombre}.parquet"
        if not ruta.exists():
            raise SystemExit(f"No existe {ruta}. Ejecuta antes el pipeline de la etapa 3 (`dvc repro`).")
        df = pd.read_parquet(ruta)
        partes[nombre] = (df.drop(columns=[objetivo]), df[objetivo])
    return partes


def preprocesador(X: pd.DataFrame) -> ColumnTransformer:
    """Imputación y escalado/codificación DENTRO del pipeline: se aprenden solo
    de train y se reaplican igual a valid y test. Así no hay fuga."""
    num = X.select_dtypes(include="number").columns.tolist()
    cat = [c for c in X.columns if c not in num]
    return ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("esc", StandardScaler())]), num),
        ("cat", Pipeline([("imp", SimpleImputer(strategy="most_frequent")),
                          ("oh", OneHotEncoder(handle_unknown="ignore", min_frequency=10))]), cat),
    ])


# ----------------------------------------------------------------------------
# Modelos: un nombre → un estimador. `baseline` es obligatorio y va primero.
# Para PyTorch/TensorFlow: entrena aparte y registra con mlflow.pytorch.log_model
# (recuerda `input_example`), conservando las mismas métricas y etiquetas.
# ----------------------------------------------------------------------------
MODELOS = {
    "clasificacion": {
        "baseline":  lambda s, h: DummyClassifier(strategy=h.get("strategy", "most_frequent")),
        "logistica": lambda s, h: LogisticRegression(max_iter=2000, C=float(h.get("C", 1.0)), class_weight=h.get("class_weight")),
        "arbol":     lambda s, h: DecisionTreeClassifier(random_state=s, max_depth=h.get("max_depth")),
        "bosque":    lambda s, h: RandomForestClassifier(random_state=s, n_estimators=int(h.get("n_estimators", 300)),
                                                        max_depth=h.get("max_depth"), n_jobs=-1, class_weight=h.get("class_weight")),
        "gbm":       lambda s, h: HistGradientBoostingClassifier(random_state=s, learning_rate=float(h.get("learning_rate", 0.1)),
                                                                max_depth=h.get("max_depth"), max_iter=int(h.get("max_iter", 200))),
        "mlp":       lambda s, h: MLPClassifier(random_state=s, hidden_layer_sizes=tuple(h.get("hidden", (64, 32))), max_iter=500),
    },
    "regresion": {
        "baseline":  lambda s, h: DummyRegressor(strategy=h.get("strategy", "mean")),
        "ridge":     lambda s, h: Ridge(alpha=float(h.get("alpha", 1.0))),
        "arbol":     lambda s, h: DecisionTreeRegressor(random_state=s, max_depth=h.get("max_depth")),
        "bosque":    lambda s, h: RandomForestRegressor(random_state=s, n_estimators=int(h.get("n_estimators", 300)),
                                                       max_depth=h.get("max_depth"), n_jobs=-1),
        "gbm":       lambda s, h: HistGradientBoostingRegressor(random_state=s, learning_rate=float(h.get("learning_rate", 0.1)),
                                                               max_depth=h.get("max_depth"), max_iter=int(h.get("max_iter", 200))),
        "mlp":       lambda s, h: MLPRegressor(random_state=s, hidden_layer_sizes=tuple(h.get("hidden", (64, 32))), max_iter=500),
    },
}

# Rejillas pequeñas para barrido.py · amplíalas con criterio (y tiempo de cómputo)
REJILLAS = {
    "logistica": [{"C": c} for c in (0.01, 0.1, 1.0, 10.0)],
    "ridge":     [{"alpha": a} for a in (0.1, 1.0, 10.0, 100.0)],
    "arbol":     [{"max_depth": d} for d in (3, 5, 8, None)],
    "bosque":    [{"n_estimators": n, "max_depth": d} for n in (200, 500) for d in (None, 10)],
    "gbm":       [{"learning_rate": lr, "max_depth": d} for lr in (0.03, 0.1) for d in (None, 6)],
    "mlp":       [{"hidden": h} for h in ((64,), (64, 32), (128, 64))],
}


def crear_modelo(nombre: str, cfg: dict, hiper: dict | None = None) -> Pipeline:
    tarea = cfg["tarea"]
    if nombre not in MODELOS[tarea]:
        raise SystemExit(f"Modelo '{nombre}' no definido para {tarea}. Opciones: {list(MODELOS[tarea])}")
    return nombre, MODELOS[tarea][nombre](int(cfg["semilla"]), hiper or {})


def ensamblar(X: pd.DataFrame, estimador) -> Pipeline:
    return Pipeline([("pre", preprocesador(X)), ("modelo", estimador)])


# ----------------------------------------------------------------------------
# Métricas: se llaman IGUAL en todas las ejecuciones (el evaluador ordena por ellas)
# ----------------------------------------------------------------------------
def metricas(cfg: dict, modelo: Pipeline, X: pd.DataFrame, y: pd.Series) -> dict[str, float]:
    if cfg["tarea"] == "regresion":
        pred = modelo.predict(X)
        return {"mae": float(mean_absolute_error(y, pred)),
                "rmse": float(np.sqrt(mean_squared_error(y, pred))),
                "r2": float(r2_score(y, pred)),
                "mape": float(mean_absolute_percentage_error(y, pred))}
    pred = modelo.predict(X)
    binaria = pd.Series(y).nunique() == 2
    prom = "binary" if binaria else "macro"
    m = {"accuracy": float(accuracy_score(y, pred)),
         "precision": float(precision_score(y, pred, average=prom, zero_division=0)),
         "recall": float(recall_score(y, pred, average=prom, zero_division=0)),
         "f1": float(f1_score(y, pred, average=prom, zero_division=0))}
    if hasattr(modelo, "predict_proba"):
        proba = modelo.predict_proba(X)
        try:
            if binaria:
                m["roc_auc"] = float(roc_auc_score(y, proba[:, 1]))
                m["auc_pr"] = float(average_precision_score(y, proba[:, 1]))
            else:
                m["roc_auc"] = float(roc_auc_score(y, proba, multi_class="ovr"))
        except ValueError:
            pass
    return m


# ----------------------------------------------------------------------------
# Registro del modelo. MLflow 3 serializa scikit-learn con skops y RECHAZA al
# registrar (no al cargar) los tipos que no se declaran de confianza; un
# ColumnTransformer ya arrastra numpy.dtype. Si añades un transformador propio,
# ponlo en un módulo importable, súmalo aquí y pásalo en code_paths.
# ----------------------------------------------------------------------------
TIPOS_CONFIABLES = ["numpy.dtype", "numpy.ndarray", "collections.OrderedDict"]


def registrar_modelo(modelo, X_ejemplo: pd.DataFrame):
    import mlflow
    from mlflow.models import infer_signature

    return mlflow.sklearn.log_model(
        modelo, name="modelo",
        signature=infer_signature(X_ejemplo, modelo.predict(X_ejemplo)),
        input_example=X_ejemplo.head(3),
        skops_trusted_types=TIPOS_CONFIABLES,
    )


def parsear_hiper(pares: list[str]) -> dict:
    """--hiper C=0.1 max_depth=5 hidden=64,32  →  {'C': 0.1, 'max_depth': 5, 'hidden': (64, 32)}"""
    out = {}
    for par in pares or []:
        k, v = par.split("=", 1)
        if "," in v:
            out[k] = tuple(int(x) for x in v.split(","))
        elif v.lower() in ("none", "null"):
            out[k] = None
        else:
            try:
                out[k] = int(v) if v.lstrip("-").isdigit() else float(v)
            except ValueError:
                out[k] = v
    return out
