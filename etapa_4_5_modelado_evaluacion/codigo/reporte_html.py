"""Genera resultados/reporte_mlflow.html: un solo archivo, sin servidor ni dependencias.

    python codigo/reporte_html.py

Las cifras se leen de MLflow en el momento de generarlo. Las figuras van incrustadas.
"""
from __future__ import annotations

import base64
import html
import json

import mlflow
import pandas as pd
from mlflow import MlflowClient

from comun import AQUI, RESULTADOS, config

cfg = config()
M = cfg["mlflow"]
mlflow.set_tracking_uri(M["tracking_uri"])
cli = MlflowClient()
exp = mlflow.get_experiment_by_name(M["experimento"])
runs = mlflow.search_runs(experiment_ids=[exp.experiment_id], max_results=5000)
R = AQUI / "resultados" / "experimentos"
mv = cli.get_model_version_by_alias(M["modelo_registrado"], M["alias_campeon"])
e = html.escape


def png_liviano(ruta) -> bytes:
    """La figura con paleta de 128 colores: los graficos tienen pocos colores y pesan ~3 veces
    menos. Sin esto el HTML pasa de 1 MB, el limite del hook del curso para un archivo en Git."""
    try:
        import io
        from PIL import Image
        with Image.open(ruta) as im:
            buf = io.BytesIO()
            im.convert("RGB").quantize(colors=128).save(buf, format="PNG", optimize=True)
            return buf.getvalue()
    except ImportError:
        return ruta.read_bytes()


def img(nombre, pie):
    b = base64.b64encode(png_liviano(R / nombre)).decode()
    return f'<figure><img alt="{e(pie)}" src="data:image/png;base64,{b}"><figcaption>{e(pie)}</figcaption></figure>'


def n(v, d=3):
    return "" if pd.isna(v) else (f"{int(v)}" if float(v).is_integer() and d == 0 else f"{float(v):.{d}f}")


def pct(v):
    return "" if pd.isna(v) else f"{100 * float(v):.0f} %"


def uno(nombre):
    return runs[runs["tags.mlflow.runName"] == nombre].sort_values("start_time").iloc[-1]


def tabla(filas, cab, id_="", ordenable=True):
    th = "".join(f"<th>{e(c)}</th>" for c in cab)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in f) + "</tr>" for f in filas)
    return f'<div class="tw"><table{" id=" + id_ if id_ else ""}{" class=ord" if ordenable else ""}><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


exps = runs[runs["tags.tipo"].isin(["experimento", "campeon"])].copy()
sc, bl = uno("sonata_mlp-256x128-v2-test"), uno("geo_hgb-v2-test")
scv = uno("sonata_mlp-256x128-v2-valid")
rs = json.loads((R / "v2_sonata_mlp_btmt.json").read_text(encoding="utf-8"))
barr = json.loads((R / "barrido_v2.json").read_text(encoding="utf-8"))
v3 = {c: (uno(f"sonata_mlp_solo_{c}-256x128-v3-valid"), uno(f"sonata_mlp_solo_{c}-256x128-v3-test"),
          json.loads((R / f"v3_sonata_mlp_solo_{c}.json").read_text(encoding="utf-8"))) for c in ("bt", "mt")}
v4 = {c: (uno(f"sonata_mlp_solo_{c}-256x128-v4-valid"), uno(f"sonata_mlp_solo_{c}-256x128-v4-test"),
          json.loads((R / f"v4_sonata_mlp_solo_{c}.json").read_text(encoding="utf-8"))) for c in ("bt", "mt")}

NOMBRE_MODELO = {"geo_hgb": "Rasgos geométricos + HistGradientBoosting", "sonata_mlp": "Sonata congelado + cabeza MLP",
                 "sonata_lineal": "Sonata congelado + cabeza lineal",
                 "sonata_mlp_solo_bt": "Sonata congelado + cabeza MLP, solo BT", "sonata_mlp_solo_mt": "Sonata congelado + cabeza MLP, solo MT"}


def filas_exp(df):
    out = []
    for _, r in df.sort_values(["tags.version_datos", "tags.conjunto_evaluacion", "metrics.recuperacion"], ascending=[False, True, False]).iterrows():
        out.append([f"<code>{e(r['tags.mlflow.runName'])}</code>", e(NOMBRE_MODELO.get(r["tags.modelo"], r["tags.modelo"])), r["tags.version_datos"],
                    r["tags.conjunto_evaluacion"], n(r["metrics.hallados"], 0) + " / " + n(r["metrics.reales"], 0), n(r["metrics.predichos"], 0),
                    n(r["metrics.recuperacion"]), n(r["metrics.precision"]), n(r["metrics.f1"]),
                    "" if pd.isna(r.get("params.umbral")) else r["params.umbral"], f"<code>{r['run_id'][:8]}</code>"])
    return out


CAB = ["Ejecución", "Modelo", "Datos", "Conjunto", "Hallados / reales", "Candidatos", "Recuperación", "Precisión", "F1", "Umbral", "Run"]
por_bloque = [[r["bloque"], n(r["reales"], 0), n(r["hallados"], 0), n(r["predichos"], 0), n(r["correctos"], 0), pct(r["recuperacion"]), pct(r["precision"])] for r in rs["test"]]
por_clase = [[c["clase"], c["reales"], c["hallados"], c["hallados_otra_clase"], c["predichos"], c["correctos"], c["clase_equivocada"], c["inventados"]] for c in rs["test_por_clase"]]
datos = [[d["particion"], d["bloque"], d["escaneo"], f"{d['voxeles']:,}", d["postes_bt"], d["postes_mt"]] for d in rs["datos"]]
barrido = [[f["familia"], e(json.dumps(f["hiper"])), f["umbral"], f"{f['hallados']} / {f['reales']}", f["predichos"], n(f["recuperacion"]), n(f["precision"]), "" if "ap_val" not in f or f["ap_val"] != f["ap_val"] else n(f["ap_val"])] for f in barr["filas"]]
ver = {v: runs[runs["tags.version_datos"] == v].iloc[0] for v in ("v1", "v2", "v3", "v4")}
n_postes = {k: (sum(d["postes_bt"] for d in rs["datos"] if d["particion"] == k), sum(d["postes_mt"] for d in rs["datos"] if d["particion"] == k)) for k in ("train", "val", "test")}

SECCIONES = [
 ("resumen", "1. Resumen ejecutivo", f"""
<div class="kpis"><div><b>{n(sc['metrics.hallados'],0)} / {n(sc['metrics.reales'],0)}</b>postes hallados en test por el campeón</div>
<div><b>{n(bl['metrics.hallados'],0)} / {n(bl['metrics.reales'],0)}</b>postes hallados por el baseline</div>
<div><b>{pct(sc['metrics.precision'])}</b>de candidatos correctos del campeón</div>
<div><b>{n(sc['metrics.hallados_poste_mt'],0)} / {n(sc['metrics.reales_poste_mt'],0)}</b>postes de MT hallados en test</div></div>
<p><b>Conclusión.</b> Sonata congelado con una cabeza MLP halla más postes que el baseline geométrico sobre los mismos datos, y queda registrado como campeón. Aún no está listo para operar sin revisión: casi la mitad de sus candidatos no coinciden con un poste etiquetado y no detecta el único poste de MT de test.</p>
<p><b>Qué se decide con esto.</b> El modelo sirve hoy para proponer postes de BT que una persona confirma. La prioridad siguiente es etiquetar más postes de MT y revisar los candidatos sin etiqueta, no afinar hiperparámetros.</p>"""),
 ("proyecto", "2. El proyecto y la tarea", """
<p>El proyecto automatiza el inventario de postes eléctricos a partir de nubes de puntos LiDAR móvil, en Ate y Pachacámac (Lima). Hoy esa identificación se hace a mano sobre la nube.</p>
<p><b>Tarea del modelo.</b> Clasificar cada voxel como fondo, <code>poste_bt</code> o <code>poste_mt</code>, agrupar los voxeles en objetos y entregar una lista de postes.</p>
<p><b>Métrica primaria: recuperación por objeto.</b> Es la fracción de postes reales que recibe al menos un candidato a 1 m o menos. Se mide por poste porque el inventario cuenta postes, no voxeles. La precisión por objeto dice cuántos candidatos habría que descartar a mano.</p>"""),
 ("datos", "3. Datos y versiones", f"""
<p>Cada bloque cubre 200 m. Una persona recorta sus postes en CloudCompare y guarda sus recortes <code>_BT</code> y <code>_MT</code> en <code>datos/crudo/etiquetado/&lt;escaneo&gt;/train</code> o <code>test</code>; desde v4, en una carpeta por clase: <code>&lt;escaneo&gt;/poste_bt/&lt;train|test&gt;</code> y <code>&lt;escaneo&gt;/poste_mt/&lt;train|test&gt;</code>, y cada modelo toma la partición de su clase. Hasta v2 la nube del bloque iba al lado; desde v3 se toma de <code>datos/intermedio/01_bloques</code>. Esa carpeta decide la partición; validación se aparta de train por nombre de bloque.</p>
{tabla([["v1", "<code>etiquetas-v1</code>", f"<code>{ver['v1']['tags.datos_md5']}</code>", "Recortes del 30-oct: postes de BT y un poste de MT. Reconstruida quitando el recorte añadido el 31-oct."],["v2", "<code>etiquetas-v2</code>", f"<code>{ver['v2']['tags.datos_md5']}</code>", "Añade siete postes de MT en b_1465_43337. Es la versión del campeón."],["v3", "<code>etiquetas-v3</code>", f"<code>{ver['v3']['tags.datos_md5']}</code>", "28 recortes en 3 escaneos (suma PACHAP01MT0108202502), solo recortes, sin las nubes. Partición nueva: no se compara cifra a cifra con v2.",["v4", "<code>etiquetas-v4</code>", f"<code>{ver['v4']['tags.datos_md5']}</code>", "45 recortes en 4 escaneos, una carpeta por clase. BT suma 17 recortes en PACHAP01MT0108202502 (204 postes en train); MT suma AVP01MT2611202502 y deja fuera los MT de Pachacámac. Partición nueva: no se compara cifra a cifra con v3."]]], ["Versión", "Etiqueta Git", "datos_md5 (DVC)", "Contenido"], ordenable=False)}
<h3>Partición de la versión v2</h3>
<p>Train: {n_postes['train'][0]} BT y {n_postes['train'][1]} MT. Validación: {n_postes['val'][0]} BT y {n_postes['val'][1]} MT. Test: {n_postes['test'][0]} BT y {n_postes['test'][1]} MT, contados antes de excluir los compartidos.</p>
{tabla(datos, ["Partición", "Bloque", "Escaneo", "Voxeles", "Postes BT", "Postes MT"])}"""),
 ("metodo", "4. Cómo se entrena y se mide", """
<ol><li><b>Rasgos.</b> Sonata (PTv3) preentrenado y congelado da 1088 rasgos por voxel de 0,08 m, proyectados a 256 con PCA.</li>
<li><b>Cabeza.</b> Se entrena solo una MLP de tres salidas, con entropía cruzada ponderada, parada temprana y una ronda de negativos difíciles.</li>
<li><b>Umbral.</b> Se elige en validación: el que más postes halla con precisión de al menos 0,5.</li>
<li><b>Objetos.</b> Los voxeles se agrupan por columna, pasan un filtro de forma y cada objeto recibe una sola clase.</li>
<li><b>Test.</b> Solo los candidatos finales tocan test, con el umbral ya fijo.</li></ol>
<p><b>Anti-fuga.</b> Un poste junto al borde aparece en dos bloques vecinos por el anillo de contexto. Los que train comparte con validación o test se excluyen de la métrica: dos en validación y uno en test.</p>"""),
 ("experimentos", "5. Experimentos registrados", f"""
<p>Hay un solo experimento de MLflow, <code>{e(M['experimento'])}</code>, con {len(exps)} ejecuciones comparables. Filtra con el buscador o ordena haciendo clic en una columna. Baseline primero en cada versión; test solo para candidatos finales.</p>
{tabla(filas_exp(exps), CAB, "t-exp")}
<h3>Barridos en validación (v2)</h3>
<p>Cada combinación es una ejecución hija de <code>barrido-&lt;familia&gt;</code>. Test no interviene aquí.</p>
{tabla(barrido, ["Familia", "Hiperparámetros", "Umbral", "Hallados / reales", "Candidatos", "Recuperación", "Precisión", "AP val"])}
<h3>Etiquetas v3: un modelo por clase</h3>
<p>Con v3 se entrenó una cabeza por clase, con lr 5e-5 (antes 5e-4): con el lr anterior la mejor época era siempre la primera. Umbral elegido en validación con la misma regla.</p>
{tabla([[NOMBRE_MODELO[f"sonata_mlp_solo_{c}"], v3[c][2]["mejor_epoca"], v3[c][2]["umbral"], n(v3[c][0]["metrics.hallados"],0)+" / "+n(v3[c][0]["metrics.reales"],0), n(v3[c][1]["metrics.hallados"],0)+" / "+n(v3[c][1]["metrics.reales"],0), n(v3[c][1]["metrics.predichos"],0), pct(v3[c][1]["metrics.recuperacion"]), pct(v3[c][1]["metrics.precision"])] for c in ("bt", "mt")], ["Modelo", "Mejor época", "Umbral", "Valid hallados / reales", "Test hallados / reales", "Candidatos test", "Recuperación test", "Precisión test"], ordenable=False)}
<p><b>Lectura.</b> BT halla 32 de 48 postes de test, pero en los bloques de test que comparte con la corrida anterior halla lo mismo: la mejora viene sobre todo del cambio de partición. Lo que más limita es el filtro de forma, que en validación descarta 7 de 36 postes que el modelo sí veía. MT pasa de un AP de validación de 0,20 a 0,67 y halla 12 de 13 postes en train, pero en test solo hay 2. El campeón no cambia: sigue siendo el modelo v2, el único que detecta BT y MT a la vez.</p>
{img('v3_sonata_mlp_solo_bt_curvas.png', 'Curvas de entrenamiento del modelo v3 solo BT')}
{img('v3_sonata_mlp_solo_mt_curvas.png', 'Curvas de entrenamiento del modelo v3 solo MT')}
<h3>Etiquetas v4: partición por clase y más bloques</h3>
<p>Desde v4 cada clase tiene su carpeta de train y test, y un bloque puede ir a train para una clase y a test para la otra. Entrenado en el clúster Khipu de UTEC, en CPU, con <code>scripts/khipu/</code>.</p>
{tabla([[NOMBRE_MODELO[f"sonata_mlp_solo_{c}"], v4[c][2]["mejor_epoca"], v4[c][2]["umbral"], n(v4[c][0]["metrics.hallados"],0)+" / "+n(v4[c][0]["metrics.reales"],0), n(v4[c][1]["metrics.hallados"],0)+" / "+n(v4[c][1]["metrics.reales"],0), n(v4[c][1]["metrics.predichos"],0), pct(v4[c][1]["metrics.recuperacion"]), pct(v4[c][1]["metrics.precision"])] for c in ("bt", "mt")], ["Modelo", "Mejor época", "Umbral", "Valid hallados / reales", "Test hallados / reales", "Candidatos test", "Recuperación test", "Precisión test"], ordenable=False)}
<p><b>Lectura.</b> BT pasa de 104 a 204 postes en train, en 16 bloques. La recuperación en test casi no cambia (70 %), pero la precisión sube de 53 % a 67 %: con más bloques el modelo ve más fondo variado y propone menos candidatos falsos. Una curva de aprendizaje previa (con 25, 50, 75 y 100 % de los postes de train) ya mostraba que más postes de BT casi no suben la recuperación. MT, solo con Ate y 35 postes en train, halla 8 de 12 en test con 50 % de precisión. Cautela: 12 postes de test de BT están en bloques vecinos de train y se excluyen de la métrica, pero train y test comparten calles, así que la cifra puede ser algo optimista.</p>
{img('v4_sonata_mlp_solo_bt_curvas.png', 'Curvas de entrenamiento del modelo v4 solo BT')}
{img('v4_sonata_mlp_solo_mt_curvas.png', 'Curvas de entrenamiento del modelo v4 solo MT')}
<p><b>Lectura del barrido v2.</b> Validación tiene solo 12 postes tras la exclusión, sin ninguno de MT, así que un poste mueve la recuperación 8 puntos. Las diferencias pequeñas entre combinaciones no son concluyentes. La cabeza no lineal sí supera a la lineal: 9 frente a 7 postes y AP de 0,874 frente a 0,805. El campeón y el baseline empatan en validación con 9 de 12; se separan en test.</p>"""),
 ("campeon", "6. El campeón", f"""
<p><b>Modelo registrado:</b> <code>models:/{e(M['modelo_registrado'])}@{e(M['alias_campeon'])}</code>, versión {mv.version}, ejecución <code>{mv.run_id[:8]}</code>.</p>
<p><b>Justificación:</b> {e(mv.tags.get('justificacion', ''))}</p>
<h3>Test por bloque</h3>{tabla(por_bloque, ["Bloque", "Reales", "Hallados", "Candidatos", "Correctos", "Recuperación", "Precisión"])}
<h3>Test por clase</h3>{tabla(por_clase, ["Clase", "Reales", "Hallados", "Hallados con otra clase", "Candidatos", "Correctos", "Clase equivocada", "Inventados"])}
{img('v2_sonata_mlp_btmt_curvas.png', 'Curvas de entrenamiento y validación del campeón')}
{img('v2_sonata_mlp_btmt_umbral.png', 'Detección por objeto en validación según el umbral')}"""),
 ("baseline", "7. Campeón frente a baseline", f"""
{tabla([["Sonata + MLP", n(sc['metrics.hallados'],0)+" / "+n(sc['metrics.reales'],0), n(sc['metrics.predichos'],0), pct(sc['metrics.recuperacion']), pct(sc['metrics.precision']), n(sc['metrics.f1'])],["Geométrico + HGB", n(bl['metrics.hallados'],0)+" / "+n(bl['metrics.reales'],0), n(bl['metrics.predichos'],0), pct(bl['metrics.recuperacion']), pct(bl['metrics.precision']), n(bl['metrics.f1'])]], ["Modelo", "Hallados / reales", "Candidatos", "Recuperación", "Precisión", "F1"], ordenable=False)}
<p>La recuperación mejora y la precisión queda prácticamente igual. Con 23 postes en test, la diferencia es de 5 postes: orienta la decisión, pero no es una estimación precisa.</p>
{img('v2_geo_hgb_curvas.png', 'Curvas del baseline geométrico')}"""),
 ("limites", "8. Limitaciones", """
<ul><li><b>MT casi sin evidencia.</b> En v2 se aprende con siete postes y se mide con uno, que no se detectó. En v3 hay 13 en train, 5 en validación y 2 en test: el modelo sobreajusta en dos épocas. Hace falta recortar más postes de MT.</li>
<li><b>Precisión posiblemente subestimada.</b> Los candidatos sin etiqueta pueden ser postes aún no recortados; b_1494_43240 concentra la mayoría y falta revisarlos en Street View.</li>
<li><b>Test y validación pequeños.</b> Las cifras cambian mucho con pocos postes; falta validación cruzada por bloques.</li>
<li><b>v1 y v2 no se comparan cifra a cifra.</b> Cambian partición, alcance y número de postes. Las corridas v1 se registraron a posteriori desde sus resúmenes y usan el filtro de forma de esa fecha: con la agrupación por columna actual, la cabeza 256x128 de v1 subía de 33 a 40 de 48 postes, medición que no está registrada como ejecución.</li>
<li><b>Partición distinta de la etapa 3.</b> Esta partición por carpetas no es la de superceldas de la etapa <code>particionar</code>, que dejaba los bloques etiquetados sin test.</li>
<li><b>Licencia.</b> Los pesos de Sonata son CC-BY-NC 4.0: sirven para este trabajo académico, no para uso comercial.</li></ul>"""),
 ("reproducir", "9. Cómo reproducirlo", """
<pre># requiere la credencial de lectura de R2 en .dvc/config.local
dvc pull datos/crudo/etiquetado.dvc etapa_4_5_modelado_evaluacion/resultados/experimentos/v2_cabeza_pesos.npz.dvc etapa_4_5_modelado_evaluacion/resultados/experimentos/v2_cabeza_comprobacion.npz.dvc
bash etapa_4_5_modelado_evaluacion/scripts/servidor_mlflow.sh   # terminal aparte
cd etapa_4_5_modelado_evaluacion
python codigo/registrar_experimentos.py
python codigo/evaluar.py
python codigo/promover.py --run-id "$(cat resultados/run_campeon.txt)" --justificacion "..."
python codigo/reporte.py
python codigo/reporte_html.py</pre>
<p>Reentrenar requiere GPU y el entorno de Sonata: <code>cuadernos/baseline_geometrico.ipynb</code>, <code>cuadernos/sonata_mlp.ipynb</code> y <code>codigo/postes/barrido_modelos.py</code>. Las caches se regeneran solas desde las nubes.</p>"""),
]
cab = sum(1 for _ in exps.iterrows())
crit = [["1", "Servidor con sqlite", "<code>scripts/servidor_mlflow.sh</code>. Falta que otra persona lo reproduzca."],
        ["2", "Baseline, 2 o más familias, barridos, 2 o más versiones", f"{exps['tags.modelo'].nunique()} familias, versiones v1, v2, v3 y v4."],
        ["3", "Procedencia en todas", f"{int(runs['tags.datos_md5'].notna().sum())} de {len(runs)} ejecuciones con <code>datos_md5</code>, <code>version_datos</code> y <code>git_commit</code>."],
        ["4", "Mismos nombres de métricas", "<code>recuperacion</code>, <code>precision</code>, <code>f1</code> en todas."],
        ["5", "Un modelo con alias", f"<code>{e(M['modelo_registrado'])}@{e(M['alias_campeon'])}</code>."],
        ["6", "Reporte final", "Ejecución <code>reporte-final</code> con tabla, figura y este HTML."],
        ["7", "Base y artefactos fuera de Git", "<code>mlflow.db</code> y <code>mlartifacts/</code> están en <code>.gitignore</code>."]]
SECCIONES.append(("criterios", "10. Criterios de aceptación", tabla(crit, ["#", "Criterio", "Evidencia"], ordenable=False)))

nav = "".join(f'<a href="#{i}">{e(t)}</a>' for i, t, _ in SECCIONES)
cuerpo = "".join(f'<section id="{i}"><h2>{e(t)}</h2>{c}<div class="pn"><button data-d="-1">← Anterior</button><button data-d="1">Siguiente →</button><a href="#top">↑ Inicio</a></div></section>' for i, t, c in SECCIONES)
PAGINA = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reporte MLflow · Detección de postes</title><style>
:root{--t:#1c2733;--m:#5b6b7b;--l:#dde3e9;--a:#0b5cad;--f:#f5f7f9}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;font:16px/1.55 system-ui,Segoe UI,Arial,sans-serif;color:var(--t)}
aside{position:fixed;inset:0 auto 0 0;width:280px;background:var(--f);border-right:1px solid var(--l);padding:18px;overflow:auto}
aside h1{font-size:17px;margin:0 0 12px}aside a{display:block;padding:6px 8px;border-radius:5px;color:var(--t);text-decoration:none;font-size:14px}
aside a:hover{background:#e7edf3}aside a.on{background:var(--a);color:#fff}
#q{width:100%;padding:8px;border:1px solid #aab6c2;border-radius:5px;font-size:14px}#st{font-size:12px;color:var(--m);min-height:18px;margin:4px 0 10px}
.btns{display:flex;gap:4px;margin-bottom:12px}main{margin-left:280px;padding:28px 40px;max-width:1180px}
section{padding-bottom:18px;border-bottom:1px solid var(--l);margin-bottom:26px;scroll-margin-top:14px}h2{margin-top:0}
button{border:1px solid #aab6c2;background:#fff;border-radius:5px;padding:5px 9px;cursor:pointer;font-size:13px}button:hover{background:#e7edf3}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:12px 0}.kpis div{border:1px solid var(--l);border-radius:8px;padding:12px;font-size:13px;color:var(--m)}.kpis b{display:block;font-size:26px;color:var(--t)}
.tw{overflow:auto;margin:10px 0}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--l);padding:6px 8px;text-align:left;vertical-align:top}th{background:var(--f);position:sticky;top:0}.ord th{cursor:pointer}.ord th:hover{color:var(--a)}
code,pre{font-family:Consolas,monospace;font-size:.92em}pre{background:var(--f);padding:12px;overflow:auto;border-radius:6px}img{max-width:100%}figure{margin:16px 0}figcaption{font-size:13px;color:var(--m)}
mark{background:#ffe08a}.pn{display:flex;gap:6px;align-items:center;margin-top:14px;font-size:13px}.oc{display:none}
@media(max-width:800px){aside{position:static;width:auto}main{margin:0;padding:18px}}@media print{aside,.pn{display:none}main{margin:0}}
</style></head><body id="top"><aside><h1>Detección de postes<br><small>Reporte MLflow · G9</small></h1>
<input id="q" type="search" placeholder="Buscar en el reporte…" aria-label="Buscar"><div id="st"></div>
<div class="btns"><button id="pv" title="Coincidencia anterior">← Atrás</button><button id="nx" title="Coincidencia siguiente">Sigue →</button><button id="cl">Limpiar</button></div>
<nav>__NAV__</nav></aside><main>__CUERPO__<p style="color:var(--m);font-size:13px">Generado desde MLflow por <code>codigo/reporte_html.py</code>.</p></main><script>
const secs=[...document.querySelectorAll('section')],links=[...document.querySelectorAll('nav a')];
const io=new IntersectionObserver(es=>es.forEach(x=>{if(x.isIntersecting)links.forEach(l=>l.classList.toggle('on',l.hash==='#'+x.target.id))}),{rootMargin:'-20% 0px -70% 0px'});secs.forEach(s=>io.observe(s));
document.querySelectorAll('[data-d]').forEach(b=>b.onclick=()=>{const i=secs.indexOf(b.closest('section'))+ +b.dataset.d;if(secs[i])secs[i].scrollIntoView()});
document.querySelectorAll('table.ord th').forEach((th,_)=>{th.title='Ordenar';th.onclick=()=>{const t=th.closest('table'),c=[...th.parentNode.children].indexOf(th),d=th.dataset.o==='1'?-1:1;th.dataset.o=d===1?'1':'0';const b=t.tBodies[0],v=x=>{const s=x.children[c].textContent.trim(),n=parseFloat(s);return isNaN(n)?s:n};[...b.rows].sort((p,q)=>{const a=v(p),z=v(q);return (typeof a==='number'&&typeof z==='number'?a-z:String(a).localeCompare(String(z)))*d}).forEach(r=>b.appendChild(r))}});
let marks=[],pos=-1;const q=document.getElementById('q'),st=document.getElementById('st'),main=document.querySelector('main');
function limpiar(){main.querySelectorAll('mark').forEach(m=>{m.replaceWith(m.textContent)});main.normalize();main.querySelectorAll('tr.oc').forEach(r=>r.classList.remove('oc'));marks=[];pos=-1;st.textContent=''}
function ir(d){if(!marks.length)return;pos=(pos+d+marks.length)%marks.length;marks[pos].scrollIntoView({block:'center'});st.textContent=(pos+1)+' de '+marks.length}
function buscar(){limpiar();const s=q.value.trim().toLowerCase();if(s.length<2)return;const w=document.createTreeWalker(main,NodeFilter.SHOW_TEXT),ns=[];while(w.nextNode())ns.push(w.currentNode);
ns.forEach(n=>{let t=n.nodeValue,i=t.toLowerCase().indexOf(s);if(i<0)return;const f=document.createDocumentFragment();let k=0;while(i>=0){f.append(t.slice(k,i));const m=document.createElement('mark');m.textContent=t.slice(i,i+s.length);f.append(m);marks.push(m);k=i+s.length;i=t.toLowerCase().indexOf(s,k)}f.append(t.slice(k));n.replaceWith(f)});
main.querySelectorAll('table.ord tbody tr').forEach(r=>{if(!r.querySelector('mark')&&r.closest('table').querySelector('mark'))r.classList.add('oc')});
st.textContent=marks.length?'':'Sin coincidencias';ir(1)}
let tm;q.oninput=()=>{clearTimeout(tm);tm=setTimeout(buscar,250)};q.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();ir(e.shiftKey?-1:1)}};
document.getElementById('nx').onclick=()=>ir(1);document.getElementById('pv').onclick=()=>ir(-1);document.getElementById('cl').onclick=()=>{q.value='';limpiar()};
</script></body></html>"""
RESULTADOS.mkdir(exist_ok=True)
salida = RESULTADOS / "reporte_mlflow.html"
salida.write_text(PAGINA.replace("__NAV__", nav).replace("__CUERPO__", cuerpo), encoding="utf-8")
rep = runs[runs["tags.mlflow.runName"] == "reporte-final"].sort_values("start_time").iloc[-1]
cli.log_artifact(rep["run_id"], str(salida))
print("->", salida, f"{salida.stat().st_size / 1e6:.1f} MB", "· artefacto de reporte-final", rep["run_id"][:8])
