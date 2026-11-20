"""Recupera TODAS las ejecuciones del experimento en una tabla comparable y la
deja en resultados/comparacion_modelos.csv (esta tabla sí va a Git).

    python codigo/evaluar.py
    python codigo/evaluar.py --version-datos v2

Dos trampas que este script evita a propósito:
  1. filtra por igualdad de etiquetas (un `!=` sobre una etiqueta ausente devuelve cero filas);
  2. ordena DESPUÉS de filtrar por versión de datos y conjunto: el mejor número
     del barrido suele ser el menos fiable si viene de una versión pequeña.
"""
import argparse

import mlflow
import pandas as pd

from comun import RESULTADOS, config

ap = argparse.ArgumentParser()
ap.add_argument("--version-datos", default=None, help="por defecto, todas las versiones")
ap.add_argument("--conjunto", default="valid")
ap.add_argument("--top", type=int, default=15)
a = ap.parse_args()

cfg = config()
primaria = cfg["metrica_primaria"]
mlflow.set_tracking_uri(cfg["mlflow"]["tracking_uri"])
exp = mlflow.get_experiment_by_name(cfg["mlflow"]["experimento"])
if exp is None:
    raise SystemExit("Todavía no hay experimento: ejecuta primero codigo/registrar_experimentos.py")

filtro = f"tags.tipo = 'experimento' and tags.conjunto_evaluacion = '{a.conjunto}'"
if a.version_datos:
    filtro += f" and tags.version_datos = '{a.version_datos}'"
runs = mlflow.search_runs(experiment_ids=[exp.experiment_id], filter_string=filtro, max_results=5000)
if runs.empty:
    raise SystemExit(f"Sin ejecuciones para el filtro: {filtro}")

cols_m = [c for c in runs.columns if c.startswith("metrics.")]
cols_p = [c for c in runs.columns if c.startswith("params.") and c not in ("params.n_train", "params.n_eval")]
tabla = runs[["run_id", "tags.mlflow.runName", "tags.modelo", "tags.version_datos", "tags.datos_md5",
              "tags.git_commit", "tags.conjunto_evaluacion", "start_time", *cols_p, *cols_m]].copy()
tabla.columns = [c.replace("tags.mlflow.runName", "nombre").replace("tags.", "").replace("metrics.", "")
                 .replace("params.", "p_") for c in tabla.columns]
tabla = tabla.sort_values(primaria, ascending=not cfg["mayor_es_mejor"])

RESULTADOS.mkdir(exist_ok=True)
salida = RESULTADOS / "comparacion_modelos.csv"
tabla.to_csv(salida, index=False)

pd.set_option("display.width", 160)
print(f"{len(tabla)} ejecuciones · conjunto={a.conjunto} · ordenadas por {primaria} "
      f"({'mayor' if cfg['mayor_es_mejor'] else 'menor'} es mejor)\n")
print(tabla[["nombre", "modelo", "version_datos", primaria]].head(a.top).to_string(index=False))
base = tabla[tabla["modelo"] == cfg["modelo_baseline"]]
if not base.empty:
    print(f"\nbaseline: {primaria}={base.iloc[0][primaria]:.4f} · mejor candidato: {tabla.iloc[0][primaria]:.4f} "
          f"({tabla.iloc[0]['nombre']})")
else:
    print("\n⚠ No hay baseline registrado: registra el baseline con codigo/registrar_experimentos.py antes de comparar nada.")
print(f"\n→ {salida.relative_to(RESULTADOS.parent)}")
