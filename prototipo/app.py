"""Prototipo en Python · interfaz mínima sobre el modelo campeón.

    streamlit run prototipo/app.py          (desde la raíz del repositorio)

Qué hace: carga `models:/<modelo_registrado>@campeon` desde el Model Registry
(el alias, no el número de versión), construye un formulario a partir de la
firma del modelo y predice. Es el punto de partida del entregable P4: un
tercero debe poder levantarlo con el README, sin ayuda del equipo.

Reemplaza Streamlit por Gradio o FastAPI si el producto lo pide; lo que no
cambia es el contrato: el prototipo consume el campeón por alias y muestra, junto
al resultado, qué versión de datos y qué commit lo produjeron.
"""
from __future__ import annotations

import pathlib

import pandas as pd
import streamlit as st
import yaml

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CFG = RAIZ / "etapa_4_5_modelado_evaluacion" / "experimento.yaml"

st.set_page_config(page_title="Prototipo · Proyecto Integrador I", page_icon="🧭", layout="centered")
st.title("🧭 Prototipo")
st.caption("Proyecto Integrador I · Maestría en Ciencia de Datos e IA · UTEC Posgrado")


@st.cache_resource(show_spinner="Cargando el campeón desde MLflow…")
def cargar_campeon(tracking_uri: str, nombre: str, alias: str):
    import mlflow
    from mlflow import MlflowClient

    mlflow.set_tracking_uri(tracking_uri)
    modelo = mlflow.pyfunc.load_model(f"models:/{nombre}@{alias}")
    version = MlflowClient().get_model_version_by_alias(nombre, alias)
    return modelo, version


with open(CFG, encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
M = cfg["mlflow"]

try:
    modelo, version = cargar_campeon(M["tracking_uri"], M["modelo_registrado"], M["alias_campeon"])
except Exception as e:  # servidor apagado o campeón sin registrar
    st.error("No se pudo cargar el campeón desde MLflow.")
    st.code(str(e)[:600])
    st.markdown(
        "1. Levanta el servidor: `bash etapa_4_5_modelado_evaluacion/scripts/servidor_mlflow.sh`\n"
        "2. Registra un campeón: `python codigo/promover.py` desde `etapa_4_5_modelado_evaluacion/`\n"
        "3. Recarga esta página."
    )
    st.stop()

with st.sidebar:
    st.subheader("Procedencia")
    st.write(f"**Modelo:** `{M['modelo_registrado']}` v{version.version} @{M['alias_campeon']}")
    for k in ("modelo", "version_datos", "datos_md5", "git_commit", cfg["metrica_primaria"]):
        if k in version.tags:
            st.write(f"**{k}:** `{version.tags[k]}`")
    if "justificacion" in version.tags:
        st.info(version.tags["justificacion"])

# --- entrada: formulario desde la firma del modelo, o CSV si no hay firma ---
firma = modelo.metadata.get_input_schema()
st.subheader("Entrada")
modo = st.radio("¿Cómo ingresas los datos?", ["Formulario", "Archivo CSV"], horizontal=True)

X = None
if modo == "Formulario" and firma is not None:
    valores = {}
    cols = st.columns(2)
    for i, campo in enumerate(firma.inputs):
        nombre, tipo = campo.name, getattr(campo.type, "name", str(campo.type))  # long · double · string · boolean
        with cols[i % 2]:
            if tipo in ("long", "integer"):
                valores[nombre] = st.number_input(nombre, value=0, step=1)
            elif tipo in ("double", "float"):
                valores[nombre] = st.number_input(nombre, value=0.0, format="%.4f")
            elif tipo == "boolean":
                valores[nombre] = st.checkbox(nombre)
            else:
                valores[nombre] = st.text_input(nombre, value="")
    X = pd.DataFrame([valores])
else:
    archivo = st.file_uploader("CSV con las mismas columnas que la tabla de modelado (sin el objetivo)", type="csv")
    if archivo is not None:
        X = pd.read_csv(archivo)
        st.dataframe(X.head(), width="stretch")


def ajustar_tipos(X: pd.DataFrame) -> pd.DataFrame:
    """MLflow valida la entrada contra la firma y no convierte int → float por sí solo."""
    if firma is None:
        return X
    conv = {"long": "int64", "integer": "int32", "double": "float64", "float": "float32",
            "string": "string", "boolean": "bool"}
    for campo in firma.inputs:
        tipo = conv.get(getattr(campo.type, "name", str(campo.type)))
        if campo.name in X.columns and tipo:
            try:
                X[campo.name] = X[campo.name].astype(tipo)
            except (TypeError, ValueError):
                pass
    return X


# --- predicción ---
if X is not None and st.button("Predecir", type="primary"):
    try:
        pred = modelo.predict(ajustar_tipos(X.copy()))
        salida = X.copy()
        salida["prediccion"] = pred
        st.subheader("Resultado")
        st.dataframe(salida, width="stretch")
        st.caption("El agente propone, la persona dispone: la predicción es un insumo de la decisión, no la decisión.")
    except Exception as e:
        st.error(f"El modelo rechazó la entrada: {e}")
