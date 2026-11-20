"""El reporte final también es una ejecución: `reporte-final`, con la tabla
comparativa y la figura como artefactos. Es la quinta pieza del entregable.

    python codigo/reporte.py
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import pandas as pd
from mlflow import MlflowClient

from comun import RESULTADOS, config, procedencia

cfg = config()
M, primaria = cfg["mlflow"], cfg["metrica_primaria"]
tabla_ruta = RESULTADOS / "comparacion_modelos.csv"
if not tabla_ruta.exists():
    raise SystemExit("Falta resultados/comparacion_modelos.csv: ejecuta antes codigo/evaluar.py")
tabla = pd.read_csv(tabla_ruta)

mlflow.set_tracking_uri(M["tracking_uri"])
mlflow.set_experiment(M["experimento"])
cli = MlflowClient()

# figura: la métrica primaria por familia de modelo y versión de datos (mejor de cada una)
mejor = (tabla.sort_values(primaria, ascending=not cfg["mayor_es_mejor"])
              .groupby(["modelo", "version_datos"], as_index=False).first())
fig, ax = plt.subplots(figsize=(8, 4.2))
for v, sub in mejor.groupby("version_datos"):
    ax.bar([f"{m}\n{v}" for m in sub["modelo"]], sub[primaria], label=f"datos {v}")
ax.set_ylabel(primaria); ax.set_title(f"Mejor {primaria} por familia de modelo (valid)")
ax.legend(); fig.tight_layout()
RESULTADOS.mkdir(exist_ok=True)
figura = RESULTADOS / f"{primaria}_por_modelo.png"
fig.savefig(figura, dpi=150)

campeon = None
try:
    mv = cli.get_model_version_by_alias(M["modelo_registrado"], M["alias_campeon"])
    campeon = {"modelo_registrado": M["modelo_registrado"], "version": mv.version, "run_id": mv.run_id,
               **{k: v for k, v in mv.tags.items()}}
except Exception:
    pass

with mlflow.start_run(run_name="reporte-final") as run:
    mlflow.set_tags({"tipo": "reporte", **procedencia(cfg)})
    mlflow.log_params({"n_ejecuciones": len(tabla), "n_familias": tabla["modelo"].nunique(),
                       "n_versiones_datos": tabla["version_datos"].nunique(), "metrica_primaria": primaria})
    base = tabla[tabla["modelo"] == cfg["modelo_baseline"]]
    if not base.empty:
        mlflow.log_metric(f"baseline_{primaria}", float(base.iloc[0][primaria]))
    mlflow.log_metric(f"mejor_{primaria}", float(tabla.iloc[0][primaria]))
    mlflow.log_artifact(str(tabla_ruta))
    mlflow.log_artifact(str(figura))
    if campeon:
        mlflow.log_dict(campeon, "campeon.json")
    print(f"reporte-final registrado (run {run.info.run_id[:8]}) · {len(tabla)} ejecuciones · figura {figura.name}")
    if not campeon:
        print("⚠ Aún no hay campeón con alias: ejecuta codigo/promover.py y vuelve a generar el reporte.")
