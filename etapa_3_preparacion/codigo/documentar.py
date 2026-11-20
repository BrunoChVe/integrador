"""Etapas 3.2 y 3.4-3.5 — DOCUMENTAR: informe de limpieza y diccionario de datos.

Cierra la preparacion de datos con las dos salidas documentales que CRISP-DM
pide al final de la etapa 3, generadas aqui y no escritas a mano, porque a mano
se desincronizan en la primera iteracion (docs/decisiones/0022):

  reportes/informe_limpieza.json   el informe de limpieza como metrica:
                                   hallazgo por hallazgo de `seleccionar`, que
                                   se hizo, donde vive la decision y la
                                   EVIDENCIA medida sobre los bloques.
  reportes/informe_limpieza.md     el mismo informe, legible, con el texto
                                   que lo interpreta.
  docs/diccionario/diccionario.csv una fila por campo del conjunto resultante:
                                   el punto del .laz, bloque_index.csv y
                                   particion.csv, con tipo, origen y rango.
  docs/diccionario/diccionario.md  el mismo diccionario, legible.

Por que es una etapa aparte y no parte de `bloques`: cortar cuesta ~2.75 h y
esto segundos. Corregir una frase del informe no puede obligar a recortar 49 GB.

DOS GUARDAS DE COBERTURA. La etapa termina con error si catalog emite un
hallazgo que no tiene respuesta en RESPUESTAS, o si los bloques llevan un campo
que no tiene descripcion en DIMENSIONES / COLUMNAS_INDICE. Asi "el diccionario
cubre el 100 % de las columnas" se comprueba en cada `dvc repro` contra el
esquema real, en vez de prometerse.

Ejecutar: python codigo/documentar.py   (desde etapa_3_preparacion/)
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

import laspy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.config import (CLASS_ESTADO, CLASS_NAMES_ES, PATHS,  # noqa: E402
                           long_path, param)


# ---------------------------------------------------------------------------
# Respuesta a cada hallazgo de calidad de la etapa seleccionar (reportes/
# raw_profile.json). Es texto, no un umbral: explica una decision que ya vive
# en params.yaml o en un ADR, y cita donde. La evidencia NO se escribe aqui:
# se mide sobre los bloques en `evidencia()`.
# ---------------------------------------------------------------------------
RESPUESTAS: Dict[str, Dict[str, object]] = {
    "Q1": {
        "decision": "corregido",
        "accion": "Cada bloque se escribe con el CRS de `project.crs_epsg` "
                  "(EPSG:32718, WGS 84 / UTM 18S) estampado en la cabecera "
                  "(`io_cloud.write_las`). Las coordenadas no se transforman: ya "
                  "estaban en UTM 18S, solo faltaba declararlo.",
        "donde": ["etapa_3_preparacion/params.yaml: project.crs_epsg", "codigo/common/io_cloud.py: write_las"],
        "residual": "Ninguno si la evidencia da 100 %. Depende de pyproj: sin el, "
                    "write_las escribe la geometria sin CRS y esta comprobacion "
                    "lo detecta.",
    },
    "Q2": {
        "decision": "pendiente (camino critico)",
        "accion": "No se puede limpiar: falta la etiqueta. Se anota a mano, "
                  "sobre el bloque de 200 m a resolucion completa y sin "
                  "preetiqueta. La verdad de campo se guarda aparte, en "
                  "`annotation_revisada/` versionada con DVC, porque `bloques` "
                  "borra su carpeta al regenerarse.",
        "donde": ["docs/decisiones/0023-solo-postes-con-su-luminaria.md",
                  "docs/decisiones/0018-el-bloque-de-anotacion-sustituye-a-la-tesela.md",
                  "docs/decisiones/0020-tres-etapas-y-sin-borrador.md",
                  "herramientas/registrar_anotacion.py"],
        "residual": "Sin etiquetas no hay entrenamiento supervisado. Los bloques "
                    "salen con classification = 0 (sin clasificar) y la etiqueta "
                    "se une al punto al registrar la anotacion.",
    },
    "Q3": {
        "decision": "aceptado",
        "accion": "`number_of_returns` y `return_number` se descartan "
                  "(`select.keep_dimensions`). El retorno multiple es marginal y "
                  "no permite la regla de primer/ultimo retorno para separar "
                  "suelo de cable; cuando haga falta altura sobre el suelo se "
                  "calculara por geometria.",
        "donde": ["etapa_3_preparacion/params.yaml: select.keep_dimensions",
                  "etapa_3_preparacion/params.yaml: select.umbral_retorno_unico"],
        "residual": "Se pierde la informacion de retorno del ~5 % de puntos que "
                    "la tienen. Se acepta.",
    },
    "Q4": {
        "decision": "corregido",
        "accion": "El color llega en campos LAS de 16 bits con valores de 0-255. "
                  "Se lee como 8 bits y se escribe desplazado 8 bits, que es la "
                  "convencion LAS: asi CloudCompare y cualquier normalizacion "
                  "por 65535 ven el color real y no una nube casi negra.",
        "donde": ["codigo/common/io_cloud.py: _extract, write_las"],
        "residual": "Ninguno: el desplazamiento es exacto y reversible.",
    },
    "Q5": {
        "decision": "aceptado y diferido al entrenamiento",
        "accion": "No se iguala la densidad aqui. El bloque se guarda a "
                  "resolucion completa porque es lo que se abre para anotar, y "
                  "un poste lejano de la trayectoria ya tiene pocos puntos. La "
                  "igualacion (reduccion por voxel) se hara al cortar la tesela "
                  "de entrenamiento, sin tocar el bloque.",
        "donde": ["docs/decisiones/0018-el-bloque-de-anotacion-sustituye-a-la-tesela.md",
                  "etapa_3_preparacion/params.yaml: tiling.tesela_m"],
        "residual": "Cualquier rasgo de radio fijo calculado sobre el bloque "
                    "crudo se comporta distinto cerca y lejos de la trayectoria.",
    },
}


# ---------------------------------------------------------------------------
# Diccionario: el punto dentro del bloque .laz (LAS 1.4, formato de punto 7).
# Una entrada por dimension del formato, se use o no: un campo que existe en el
# archivo y vale siempre 0 tambien tiene que estar explicado.
# ---------------------------------------------------------------------------
DIMENSIONES: Dict[str, Dict[str, str]] = {
    "X": {"unidad": "m", "origen": "crudo",
          "desc": "Este UTM 18S. Guardado como entero con escala 0.001 m; se "
                  "lee siempre en float64 (en float32 se perderian ~6 cm)."},
    "Y": {"unidad": "m", "origen": "crudo",
          "desc": "Norte UTM 18S, misma escala y precision que X."},
    "Z": {"unidad": "m", "origen": "crudo",
          "desc": "Altura elipsoidal sin verificar (`project.vertical_datum`). "
                  "Solo se usan alturas relativas, asi que el datum no afecta "
                  "a las medidas de gálibo."},
    "intensity": {"unidad": "-", "origen": "crudo",
                  "desc": "Intensidad del retorno del laser, 0-255 en esta "
                          "entrega. Sin calibrar por distancia."},
    "return_number": {"unidad": "-", "origen": "no se conserva",
                      "desc": "Descartado en `select.keep_dimensions` (Q3). "
                              "Siempre 0 en el bloque."},
    "number_of_returns": {"unidad": "-", "origen": "no se conserva",
                          "desc": "Descartado en `select.keep_dimensions` (Q3). "
                                  "Siempre 0 en el bloque."},
    "synthetic": {"unidad": "bandera", "origen": "no se usa",
                  "desc": "Bandera LAS de punto sintetico. Siempre 0."},
    "key_point": {"unidad": "bandera", "origen": "no se usa",
                  "desc": "Bandera LAS de punto clave. Siempre 0."},
    "withheld": {"unidad": "bandera", "origen": "no se usa",
                 "desc": "Bandera LAS de punto retenido. Siempre 0."},
    "overlap": {"unidad": "bandera", "origen": "no se usa",
                "desc": "Bandera LAS de solape entre pasadas. Siempre 0: el "
                        "solape entre escaneos se resuelve con un bloque por "
                        "escaneo, no marcando puntos."},
    "scanner_channel": {"unidad": "-", "origen": "no se usa",
                        "desc": "Canal del escaner (LAS 1.4). Siempre 0; el "
                                "indice de laser va en point_source_id."},
    "scan_direction_flag": {"unidad": "bandera", "origen": "no se conserva",
                            "desc": "Constante en el crudo; descartado."},
    "edge_of_flight_line": {"unidad": "bandera", "origen": "no se conserva",
                            "desc": "Constante en el crudo; descartado."},
    "classification": {"unidad": "id de clase", "origen": "anotacion",
                       "desc": "Clase del punto segun `ontology.classes`. En el "
                               "bloque vale 0 (sin clasificar, Q2); la "
                               "anotacion escribe aqui el id de la clase."},
    "user_data": {"unidad": "-", "origen": "no se conserva",
                  "desc": "Constante en el crudo; descartado."},
    "scan_angle": {"unidad": "grados", "origen": "no se usa",
                   "desc": "Angulo de escaneo. El crudo (formato 3) no lo trae "
                           "util; siempre 0."},
    "point_source_id": {"unidad": "-", "origen": "crudo",
                        "desc": "Indice de laser del VLP-16, 0-15. Proxy debil "
                                "del angulo vertical del rayo. Se perdia en "
                                "silencio hasta 5fefd3f; aqui se comprueba que "
                                "no vuelva a salir todo a 0."},
    "gps_time": {"unidad": "s", "origen": "crudo",
                 "desc": "Tiempo GPS de la medida (segundos de la semana GPS). "
                         "Ordena los puntos a lo largo de la trayectoria."},
    "red": {"unidad": "-", "origen": "crudo, reescalado",
            "desc": "Canal rojo de la colorizacion por camara, 0-255 desplazado "
                    "a 16 bits (Q4): valores multiplos de 256."},
    "green": {"unidad": "-", "origen": "crudo, reescalado",
              "desc": "Canal verde, igual que red."},
    "blue": {"unidad": "-", "origen": "crudo, reescalado",
             "desc": "Canal azul, igual que red."},
}

# Columnas de datos/intermedio/01_bloques/bloque_index.csv: una fila por bloque.
COLUMNAS_INDICE: Dict[str, str] = {
    "scan": "Escaneo de origen: nombre de su carpeta en datos/crudo. Un mismo "
            "suelo cubierto por dos escaneos da dos bloques.",
    "grupo": "Entrega de la que viene el escaneo (primer nivel de datos/crudo).",
    "distrito": "Distrito (segundo nivel de datos/crudo); vacio si la entrega no "
                "tiene ese nivel.",
    "bloque_ix": "Indice de columna de la rejilla: floor(este / bloque_m).",
    "bloque_iy": "Indice de fila de la rejilla: floor(norte / bloque_m).",
    "path": "Ruta del .laz del bloque, relativa a la raiz del repositorio.",
    "points_total": "Puntos del archivo, nucleo mas anillo de contexto.",
    "points_core": "Puntos dentro del cuadrado de bloque_m, sin anillo.",
    "min_x": "Este de la esquina SO del nucleo (m, UTM 18S).",
    "min_y": "Norte de la esquina SO del nucleo (m, UTM 18S).",
    "bloque_m": "Lado del nucleo (m), `tiling.bloque_m`.",
    "buffer_m": "Ancho del anillo de contexto (m), `tiling.buffer_m`.",
    "min_z": "Z minima de los puntos del bloque (m).",
    "max_z": "Z maxima de los puntos del bloque (m).",
    "density_core_pts_m2": "points_core / bloque_m^2.",
}


# Columnas de datos/final/particion.csv: la tabla final, una fila por bloque
# con la particion a la que pertenece (etapa `particionar`, ADR 0024).
COLUMNAS_PARTICION: Dict[str, str] = {
    "path": "Ruta del .laz del bloque; enlaza con bloque_index.csv.",
    "scan": "Escaneo de origen.",
    "distrito": "Distrito de origen.",
    "bloque_ix": "Columna de la rejilla de bloques.",
    "bloque_iy": "Fila de la rejilla de bloques.",
    "supercelda": "Celda de `particion.supercelda_m` que contiene al bloque: "
                  "la unidad que se asigna entera a una particion.",
    "points_core": "Puntos de nucleo del bloque, para pesar las particiones.",
    "particion": "train, valid o test.",
}


def leer_indice() -> List[Dict[str, str]]:
    idx = PATHS.bloques / "bloque_index.csv"
    with open(idx, encoding="utf-8") as fh:
        return sorted(csv.DictReader(fh), key=lambda r: r["path"])


def muestra(filas: List[Dict[str, str]], k: int) -> List[Dict[str, str]]:
    """k bloques repartidos a paso fijo sobre el indice ordenado por ruta."""
    pos = np.unique(np.linspace(0, len(filas) - 1, min(k, len(filas))).round().astype(int))
    return [filas[i] for i in pos]


def medir_dimensiones(rutas: List[Path]) -> Dict[str, Dict[str, float]]:
    """Minimo, maximo y valores distintos de cada dimension en la muestra."""
    acc: Dict[str, Dict[str, float]] = {}
    for ruta in rutas:
        las = laspy.read(long_path(ruta))
        for dim in las.point_format.dimension_names:
            # X, Y, Z son enteros escalados: se miden en metros.
            v = np.asarray(getattr(las, dim.lower()) if dim in "XYZ" else las[dim])
            d = acc.setdefault(dim, {"min": np.inf, "max": -np.inf,
                                     "dtype": str(las[dim].dtype),
                                     "multiplo_256": True})
            d["min"] = min(d["min"], float(v.min()))
            d["max"] = max(d["max"], float(v.max()))
            if dim in ("red", "green", "blue"):
                d["multiplo_256"] &= bool((v.astype(np.int64) % 256 == 0).all())
    return acc


def evidencia(hid: str, filas, dims, crs_ok: int, n_bloques: int) -> Dict[str, object]:
    """Lo que se MIDE sobre los bloques para cada hallazgo."""
    if hid == "Q1":
        return {"bloques_con_crs_correcto": crs_ok, "bloques": n_bloques,
                "cumple": crs_ok == n_bloques}
    if hid == "Q2":
        return {"classification_min": dims["classification"]["min"],
                "classification_max": dims["classification"]["max"],
                "cumple": dims["classification"]["max"] == 0}
    if hid == "Q3":
        return {"number_of_returns_max": dims["number_of_returns"]["max"],
                "cumple": dims["number_of_returns"]["max"] == 0}
    if hid == "Q4":
        ok = all(dims[c]["multiplo_256"] for c in ("red", "green", "blue"))
        return {"rgb_max": max(dims[c]["max"] for c in ("red", "green", "blue")),
                "rgb_multiplo_de_256": ok, "cumple": ok}
    if hid == "Q5":
        dens = np.array([float(r["density_core_pts_m2"]) for r in filas])
        return {"densidad_bloque_pts_m2": {
                    "min": round(float(dens.min()), 1),
                    "p50": round(float(np.median(dens)), 1),
                    "max": round(float(dens.max()), 1)},
                "cumple": True}
    raise KeyError(hid)


def fmt(v: float) -> str:
    if v in (np.inf, -np.inf):
        return "—"
    if float(v).is_integer():
        return f"{int(v):,}".replace(",", " ")
    return f"{v:,.3f}".replace(",", " ")


def main() -> int:
    perfil = json.loads((PATHS.reports / "raw_profile.json").read_text(encoding="utf-8"))
    bloques = json.loads((PATHS.reports / "bloques.json").read_text(encoding="utf-8"))
    hallazgos = perfil["quality_findings"]

    # --- guarda 1: todo hallazgo tiene respuesta ---------------------------
    sin_resp = [h["id"] for h in hallazgos if h["id"] not in RESPUESTAS]
    if sin_resp:
        print(f"[X] Hallazgos de catalog sin respuesta en RESPUESTAS: {sin_resp}")
        return 1

    filas = leer_indice()
    if not filas:
        print("[X] bloque_index.csv vacio: ejecuta antes s02_bloques.py")
        return 1

    # --- guarda 2: el diccionario cubre el esquema real ---------------------
    faltan_col = [c for c in filas[0] if c not in COLUMNAS_INDICE]
    with open(PATHS.final / "particion.csv", encoding="utf-8") as fh:
        part = list(csv.DictReader(fh))
    faltan_col += [c for c in part[0] if c not in COLUMNAS_PARTICION]
    sel = muestra(filas, int(param("informe.bloques_muestra")))
    rutas = [PATHS.root / r["path"] for r in sel]
    with laspy.open(long_path(rutas[0])) as fh:
        esquema = list(fh.header.point_format.dimension_names)
    faltan_dim = [d for d in esquema if d not in DIMENSIONES]
    if faltan_col or faltan_dim:
        print(f"[X] Campos sin descripcion en el diccionario: "
              f"indice {faltan_col}, punto {faltan_dim}")
        return 1

    print(f"Midiendo {len(sel)} bloques de muestra y las cabeceras de {len(filas)}")
    dims = medir_dimensiones(rutas)

    # CRS: solo cabecera, asi que se comprueba en TODOS los bloques.
    epsg = int(param("project.crs_epsg"))
    crs_ok = 0
    for r in filas:
        with laspy.open(long_path(PATHS.root / r["path"])) as fh:
            crs = fh.header.parse_crs()
        crs_ok += int(crs is not None and crs.to_epsg() == epsg)

    # --- puntos: del crudo al bloque ----------------------------------------
    crudo = int(perfil["totals"]["points"])
    nucleo = int(bloques["points_core"])
    puntos = {
        "crudo": crudo, "nucleo_en_bloques": nucleo,
        "descartados": crudo - nucleo,
        "descartados_pct": round(100.0 * (crudo - nucleo) / crudo, 6),
        "motivo": f"bloques con menos de tiling.min_points = "
                  f"{param('tiling.min_points')} puntos no se escriben",
    }

    # --- controles que no vienen de un hallazgo -----------------------------
    controles = {
        "point_source_id_no_nulo": dims["point_source_id"]["max"] > 0,
        "gps_time_no_nulo": dims["gps_time"]["max"] > 0,
        "dimensiones_conservadas_presentes": all(
            d.lower() in {e.lower() for e in esquema}
            for d in param("select.keep_dimensions")),
    }

    informe = {
        "hallazgos": [
            {**{k: h[k] for k in ("id", "severity", "field", "finding")},
             **RESPUESTAS[h["id"]],
             "evidencia": evidencia(h["id"], filas, dims, crs_ok, len(filas))}
            for h in hallazgos
        ],
        "puntos": puntos,
        "controles": controles,
        "muestra": [r["path"] for r in sel],
    }
    informe["resumen"] = {
        "hallazgos": len(hallazgos),
        "corregidos": sum(1 for h in informe["hallazgos"] if h["decision"] == "corregido"),
        "pendientes": sum(1 for h in informe["hallazgos"]
                          if str(h["decision"]).startswith("pendiente")),
        "evidencia_cumple": sum(1 for h in informe["hallazgos"] if h["evidencia"]["cumple"]),
        "controles_cumplen": sum(controles.values()),
        "controles": len(controles),
    }
    (PATHS.reports / "informe_limpieza.json").write_text(
        json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")

    escribir_informe_md(informe, bloques)
    escribir_diccionario_md(esquema, dims, filas, sel, part)
    escribir_diccionario_csv(esquema, dims, filas, part)

    r = informe["resumen"]
    print(f"  {r['hallazgos']} hallazgos: {r['corregidos']} corregidos, "
          f"{r['pendientes']} pendientes; evidencia {r['evidencia_cumple']}/"
          f"{r['hallazgos']}; controles {r['controles_cumplen']}/{r['controles']}")
    print(f"  {puntos['descartados']:,} puntos descartados "
          f"({puntos['descartados_pct']} %)")
    return 0


AVISO = ("<!-- Generado por etapa_3_preparacion/codigo/documentar.py (etapa `documentar` de "
         "dvc.yaml). No editar a mano: se sobrescribe en cada `dvc repro`. -->\n\n")


def escribir_informe_md(inf: dict, bloques: dict) -> None:
    p = inf["puntos"]
    L = [AVISO, "# Informe de limpieza\n\n",
         "Responde, hallazgo por hallazgo, a los problemas de calidad que la etapa "
         "`seleccionar` encontró en el crudo (`reportes/raw_profile.json`). Para cada "
         "uno dice qué se hizo, dónde vive la decisión y qué se **midió** sobre "
         "los bloques para comprobar que funcionó. La versión de máquina es "
         "`reportes/informe_limpieza.json`. Por qué no hay más limpieza que esta: "
         "[ADR 0022](../../docs/decisiones/0022-informe-de-limpieza-y-diccionario-generados.md).\n\n",
         "## Del crudo al bloque\n\n",
         "| | puntos |\n|---|---:|\n",
         f"| crudo (cabeceras de los .laz) | {fmt(p['crudo'])} |\n",
         f"| núcleo en {fmt(bloques['bloques'])} bloques | {fmt(p['nucleo_en_bloques'])} |\n",
         f"| descartados | {fmt(p['descartados'])} ({p['descartados_pct']} %) |\n\n",
         f"Los descartados son {p['motivo']}: roces de la trayectoria en el borde "
         "de un escaneo. No se elimina ningún punto por ser ruido o atípico; el "
         "bloque se guarda a resolución completa.\n\n",
         "## Hallazgos\n\n"]
    for h in inf["hallazgos"]:
        ev = {k: v for k, v in h["evidencia"].items() if k != "cumple"}
        L += [f"### {h['id']} · `{h['field']}` · {h['severity']}\n\n",
              f"**Hallazgo.** {h['finding']}\n\n",
              f"**Decisión: {h['decision']}.** {h['accion']}\n\n",
              "**Dónde:** " + ", ".join(f"`{d}`" for d in h["donde"]) + "\n\n",
              f"**Evidencia medida** ({'cumple' if h['evidencia']['cumple'] else 'NO CUMPLE'}): "
              f"`{json.dumps(ev, ensure_ascii=False)}`\n\n",
              f"**Queda sin resolver.** {h['residual']}\n\n"]
    L += ["## Controles\n\n", "| control | resultado |\n|---|---|\n"]
    L += [f"| `{k}` | {'cumple' if v else 'NO CUMPLE'} |\n" for k, v in inf["controles"].items()]
    L += ["\nMedidos sobre los bloques de muestra: "
          + ", ".join(f"`{Path(m).name}`" for m in inf["muestra"]) + ".\n"]
    (PATHS.reports / "informe_limpieza.md").write_text("".join(L), encoding="utf-8")


def escribir_diccionario_md(esquema, dims, filas, sel, part) -> None:
    L = [AVISO, "# Diccionario de datos\n\n",
         "El conjunto que produce la preparación son los **bloques** de "
         f"{fmt(float(param('tiling.bloque_m')))} m: un archivo `.laz` por bloque "
         "y escaneo bajo `datos/intermedio/01_bloques/`, más un índice "
         "`bloque_index.csv` y la tabla final `datos/final/particion.csv`, que "
         "asigna cada bloque a train, valid o test. **Una fila es un punto** "
         "LiDAR; el bloque es la unidad de almacenamiento y de anotación "
         "([ADR 0018](../decisiones/0018-el-bloque-de-anotacion-sustituye-a-la-tesela.md)). "
         "La versión de máquina es `diccionario.csv`.\n\n",
         f"Rangos medidos sobre {len(sel)} bloques de muestra "
         "(`informe.bloques_muestra`). Formato LAS 1.4, formato de punto 7, "
         f"EPSG:{param('project.crs_epsg')}.\n\n",
         "## Punto (cada registro del `.laz`)\n\n",
         "| campo | tipo | unidad | origen | mín | máx | descripción |\n",
         "|---|---|---|---|---:|---:|---|\n"]
    for d in esquema:
        m, e = dims[d], DIMENSIONES[d]
        L.append(f"| `{d}` | {m['dtype']} | {e['unidad']} | {e['origen']} | "
                 f"{fmt(m['min'])} | {fmt(m['max'])} | {e['desc']} |\n")
    L += ["\n### Valores de `classification`\n\n",
          "| id | clase | estado |\n|---:|---|---|\n"]
    for cid in sorted(CLASS_NAMES_ES):
        L.append(f"| {cid} | {CLASS_NAMES_ES[cid]} | {CLASS_ESTADO[cid]} |\n")
    L += ["\nSolo las clases `activa` se anotan y entran al entrenamiento "
          "([ADR 0023](../decisiones/0023-solo-postes-con-su-luminaria.md)). "
          "La definición de cada una está en `etapa_3_preparacion/params.yaml: ontology.classes`.\n\n",
          f"## Índice de bloques (`bloque_index.csv`, {fmt(len(filas))} filas)\n\n",
          "| columna | ejemplo | descripción |\n|---|---|---|\n"]
    for c, desc in COLUMNAS_INDICE.items():
        L.append(f"| `{c}` | `{filas[0][c]}` | {desc} |\n")
    L += [f"\n## Tabla final (`datos/final/particion.csv`, {fmt(len(part))} filas)\n\n",
          "| columna | ejemplo | descripción |\n|---|---|---|\n"]
    for c, desc in COLUMNAS_PARTICION.items():
        L.append(f"| `{c}` | `{part[0][c]}` | {desc} |\n")
    PATHS.diccionario.mkdir(parents=True, exist_ok=True)
    (PATHS.diccionario / "diccionario.md").write_text("".join(L), encoding="utf-8")


def escribir_diccionario_csv(esquema, dims, filas, part) -> None:
    """docs/diccionario/diccionario.csv: una fila por campo, de las tres tablas."""
    salida = []
    for d in esquema:
        m, e = dims[d], DIMENSIONES[d]
        salida.append({"tabla": "punto (.laz del bloque)", "columna": d,
                       "tipo": m["dtype"], "unidad": e["unidad"], "origen": e["origen"],
                       "minimo": fmt(m["min"]), "maximo": fmt(m["max"]),
                       "ejemplo": "", "descripcion": e["desc"]})
    for tabla, cols, fila in (("bloque_index.csv", COLUMNAS_INDICE, filas[0]),
                              ("particion.csv (tabla final)", COLUMNAS_PARTICION, part[0])):
        for c, desc in cols.items():
            salida.append({"tabla": tabla, "columna": c, "tipo": "", "unidad": "",
                           "origen": "", "minimo": "", "maximo": "",
                           "ejemplo": fila[c], "descripcion": desc})
    PATHS.diccionario.mkdir(parents=True, exist_ok=True)
    with open(PATHS.diccionario / "diccionario.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(salida[0].keys()))
        w.writeheader()
        w.writerows(salida)


if __name__ == "__main__":
    raise SystemExit(main())
