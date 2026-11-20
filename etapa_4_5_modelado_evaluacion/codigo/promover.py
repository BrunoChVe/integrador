"""Registra el campeón en el Model Registry con alias.

    python codigo/promover.py                    # el mejor en valid, sobre datos.version_datos
    python codigo/promover.py --run-id 3f2a9c1b  # uno elegido a mano (con su justificación)

El alias es lo que consume el prototipo (`models:/<nombre>@campeon`), no el
número de versión: cambiar de campeón es mover el alias, sin tocar la app.
La justificación («por qué este y no el de arriba de la tabla») se guarda como
etiqueta de la versión y se repite en el README de la etapa.
"""
import argparse

import mlflow
from mlflow import MlflowClient

from comun import config

ap = argparse.ArgumentParser()
ap.add_argument("--run-id", default=None, help="run a promover; si falta, el mejor en valid")
ap.add_argument("--justificacion", default="", help="por qué este campeón (obligatoria en la entrega)")
a = ap.parse_args()

cfg = config()
M, primaria = cfg["mlflow"], cfg["metrica_primaria"]
mlflow.set_tracking_uri(M["tracking_uri"])
cli = MlflowClient()
exp = mlflow.get_experiment_by_name(M["experimento"])
if exp is None:
    raise SystemExit("No existe el experimento; registra primero el baseline.")

if a.run_id:
    run = cli.get_run(a.run_id)
else:
    runs = mlflow.search_runs(
        experiment_ids=[exp.experiment_id],
        filter_string=(f"tags.tipo = 'experimento' and tags.conjunto_evaluacion = 'valid' "
                       f"and tags.version_datos = '{cfg['datos']['version_datos']}' and tags.modelo != '{cfg['modelo_baseline']}'"),
        order_by=[f"metrics.{primaria} {'DESC' if cfg['mayor_es_mejor'] else 'ASC'}"], max_results=1)
    if runs.empty:
        raise SystemExit("No hay candidatos (tipo=experimento, conjunto=valid) para esta versión de datos.")
    run = cli.get_run(runs.iloc[0].run_id)

valor = run.data.metrics.get(primaria)
print(f"candidato: {run.info.run_name} · {primaria}={valor} · version_datos={run.data.tags.get('version_datos')} "
      f"· datos_md5={run.data.tags.get('datos_md5')}")

# En MLflow 3 el modelo no cuelga de los artefactos del run: es un LoggedModel
# enlazado a él (run.outputs.model_outputs). De ahí sale el URI que se registra.
salidas = run.outputs.model_outputs if run.outputs else []
if not salidas:
    raise SystemExit("Esa ejecución no guardó el modelo (¿barrido con --sin-modelo?). "
                     "Promueve la ejecución del candidato final, que sí lo guarda.")
modelo_registrado = cli.get_logged_model(salidas[0].model_id)

mv = mlflow.register_model(modelo_registrado.model_uri, M["modelo_registrado"])
cli.set_registered_model_alias(M["modelo_registrado"], M["alias_campeon"], mv.version)
for k in ("version_datos", "datos_md5", "git_commit", "modelo"):
    if k in run.data.tags:
        cli.set_model_version_tag(M["modelo_registrado"], mv.version, k, run.data.tags[k])
cli.set_model_version_tag(M["modelo_registrado"], mv.version, primaria, str(valor))
if a.justificacion:
    cli.set_model_version_tag(M["modelo_registrado"], mv.version, "justificacion", a.justificacion)
cli.set_tag(run.info.run_id, "tipo", "campeon")

m = mlflow.pyfunc.load_model(f"models:/{M['modelo_registrado']}@{M['alias_campeon']}")
print(f"registrado {M['modelo_registrado']} v{mv.version} @{M['alias_campeon']} · carga verificada ({type(m).__name__})")
