"""EDA — comprensión de los datos, reproducible por cualquiera.

Cualquiera clona el repositorio, ejecuta una instrucción y obtiene las mismas
figuras y las mismas cifras. Toda cifra que se cite sobre los datos —en un
informe, una presentación o una reunión— debe poder rastrearse hasta
`etapa_1_2_comprension/resultados/eda.json`; si no está ahí, no es verificable.

Diseño, y por qué:

  * Lee SOLO los .laz crudos. No depende del pipeline de preparación, que
    tarda casi una hora: esto tiene que poder regenerarse en minutos, no en
    una tarde.
  * Es DETERMINISTA. Mismo muestreo (cada k-ésimo archivo, primer bloque), sin
    aleatoriedad y sin marcas de tiempo en la salida. Sin eso, un `dvc repro`
    en otra máquina produciría un JSON distinto y la verificación fallaría
    aunque los datos fueran idénticos.
  * Las figuras se guardan sin metadatos de software. Aun así, sus bytes pueden
    variar entre máquinas por las fuentes instaladas; lo que se compara
    exactamente son las cifras del JSON, no los PNG.

Salidas:
    resultados/eda.json            las cifras: volumen, formato, periodo,
                                   variable objetivo y calidad
    resultados/figuras/*.png        las figuras, citables como evidencia

Se ejecuta con:  dvc repro eda
             o:  python etapa_1_2_comprension/codigo/eda.py
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

# El codigo comun vive con el pipeline, en etapa_3_preparacion/codigo/.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "etapa_3_preparacion" / "codigo"))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import laspy  # noqa: E402

from common.config import PATHS, long_path, param  # noqa: E402
from common.io_cloud import find_laz, las_header_info, scan_of  # noqa: E402

OUT = PATHS.resultados_eda
# Las figuras son documentación, no datos: se versionan en Git, donde se ven
# sin descargar nada. Los datos siguen yendo por DVC.
FIG = PATHS.resultados_eda / "figuras"

AZUL, ROJO, VERDE, GRIS, TINTA = "#1D5FD1", "#C1372C", "#4E9A2F", "#56697A", "#101A22"


def _estilo(ax, titulo, x=None, y=None):
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    ax.set_title(titulo, loc="left", fontsize=10.5, fontweight="bold", color=TINTA)
    if x:
        ax.set_xlabel(x, fontsize=9)
    if y:
        ax.set_ylabel(y, fontsize=9)
    ax.grid(True, color="#E4EAEF", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=8, colors=GRIS)


def _guardar(fig, nombre):
    FIG.mkdir(parents=True, exist_ok=True)
    ruta = FIG / nombre
    fig.tight_layout()
    fig.savefig(ruta, dpi=110, metadata={"Software": None})
    plt.close(fig)
    return ruta.relative_to(PATHS.root).as_posix()


def _r(v, n=4):
    return round(float(v), n)


def hsv(rgb):
    """RGB a HSV, para el histograma de tono.

    Estaba copiada de `s05_features.rgb_to_hsv` para no hacer depender el
    EDA de una etapa de preparación. Esa etapa ya no existe (0017), así que
    ahora esta es la única implementación y la copia dejó de ser una."""
    rf, gf, bf = [(rgb[:, i] / 255.0).astype("f4") for i in range(3)]
    mx = np.maximum(np.maximum(rf, gf), bf)
    mn = np.minimum(np.minimum(rf, gf), bf)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    i = nz & (mx == rf)
    h[i] = ((gf[i] - bf[i]) / d[i]) % 6
    i = nz & (mx == gf)
    h[i] = (bf[i] - rf[i]) / d[i] + 2
    i = nz & (mx == bf)
    h[i] = (rf[i] - gf[i]) / d[i] + 4
    h = h / 6.0
    s = np.zeros_like(mx)
    s[mx > 1e-6] = d[mx > 1e-6] / mx[mx > 1e-6]
    return h, s, mx


def fecha_de_escaneo(scan: str):
    m = re.search(param("eda.scan_date_pattern"), scan)
    if not m:
        return None
    dd, mm, yyyy = (int(g) for g in m.groups()[:3])
    return dt.date(yyyy, mm, dd)


def periodo_de_captura(archivos_escaneo, scan):
    """Ventana real de captura a partir del gps_time de todos los puntos."""
    tmin, tmax, tipo = np.inf, -np.inf, None
    for p in archivos_escaneo:
        with laspy.open(long_path(p)) as fh:
            tipo = int(fh.header.global_encoding.gps_time_type)
            for ch in fh.chunk_iterator(5_000_000):
                g = np.asarray(ch.gps_time)
                tmin, tmax = min(tmin, g.min()), max(tmax, g.max())
    leap = int(param("eda.gps_utc_leap_seconds"))
    offset = int(param("eda.local_utc_offset_hours"))
    fecha = fecha_de_escaneo(scan)
    if tipo == 1:        # adjusted standard GPS time: segundos GPS - 1e9
        base = dt.datetime(1980, 1, 6)
        ini = base + dt.timedelta(seconds=float(tmin) + 1e9 - leap)
        fin = base + dt.timedelta(seconds=float(tmax) + 1e9 - leap)
    elif fecha is not None:   # GPS week time: se ancla al domingo de esa semana
        d0 = dt.datetime.combine(fecha, dt.time())
        domingo = d0 - dt.timedelta(days=(d0.weekday() + 1) % 7)
        ini = domingo + dt.timedelta(seconds=float(tmin) - leap)
        fin = domingo + dt.timedelta(seconds=float(tmax) - leap)
    else:
        return {"gps_time_min_s": _r(tmin, 1), "gps_time_max_s": _r(tmax, 1),
                "nota": "sin fecha anclable: gps_time en segundos de semana GPS"}
    ini += dt.timedelta(hours=offset)
    fin += dt.timedelta(hours=offset)
    return {
        "fecha": ini.strftime("%Y-%m-%d"),
        "dia": ["lunes", "martes", "miércoles", "jueves", "viernes",
                "sábado", "domingo"][ini.weekday()],
        "inicio_hora_local": ini.strftime("%H:%M"),
        "fin_hora_local": fin.strftime("%H:%M"),
        "duracion_min": _r((tmax - tmin) / 60.0, 1),
        "gps_time_type": tipo,
        "fecha_tomada_de": "nombre de carpeta del escaneo" if tipo == 0 else "gps_time",
    }


def main() -> int:
    archivos = find_laz(PATHS.raw, param("select.scan_groups"), param("select.scans"))
    if not archivos:
        print(f"[X] No hay archivos .laz en {PATHS.raw}.")
        print("    Ejecuta: dvc pull")
        return 1

    k_archivos = int(param("eda.sample_files"))
    n_bloque = int(param("eda.sample_chunk_points"))
    # Definición de «verde» para el histograma de tono. Vivía en
    # `weak_labels.green_area`, que se fue con la etapa 06: el análisis se
    # queda porque mide la CALIDAD del color entregado, no una clase.
    banda_verde = [float(x) / 360.0 for x in param("eda.banda_verde_hue_deg")]
    sat_min = float(param("eda.banda_verde_min_saturation"))
    val_min = float(param("eda.banda_verde_min_value"))
    k_iqr = float(param("eda.outlier_iqr_k"))

    print(f"EDA sobre {len(archivos)} archivos .laz")

    # ------------------------------------------------------------------ cabeceras
    cab = []
    for p in archivos:
        info = las_header_info(p)
        info["scan"] = scan_of(p)
        cab.append(info)
    puntos = int(sum(c["point_count"] for c in cab))
    escaneos = sorted({c["scan"] for c in cab})
    dens = np.array([c["density_pts_m2"] for c in cab])
    sin_crs = sum(1 for c in cab if c["crs"] is None)
    dimensiones = cab[0]["dimensions"]

    # ------------------------------------------------------------------ periodo
    print("  periodo de captura (lee gps_time de todos los puntos)...")
    periodos = {}
    for s in escaneos:
        periodos[s] = periodo_de_captura([p for p in archivos if scan_of(p) == s], s)

    # ------------------------------------------------------------------ muestra
    paso = max(1, len(archivos) // k_archivos)
    muestra = archivos[::paso][:k_archivos]
    print(f"  muestra determinista: {len(muestra)} archivos x {n_bloque:,} puntos")
    clases, retornos, anillos = Counter(), Counter(), Counter()
    n_m = dup = z_bajo = z_alto = inten_sat = rgb_negro = 0
    rgb_16_bits_reales = False
    hues, sats, vals, inten_all, z_all = [], [], [], [], []
    for p in muestra:
        with laspy.open(long_path(p)) as fh:
            ch = next(fh.chunk_iterator(n_bloque))
        n = len(ch.X)
        n_m += n
        clases.update(np.asarray(ch.classification).tolist())
        retornos.update(np.asarray(ch.number_of_returns).tolist())
        anillos.update(np.asarray(ch.point_source_id).tolist())
        xyz = np.stack([np.asarray(ch.X), np.asarray(ch.Y), np.asarray(ch.Z)], axis=1)
        dup += n - np.unique(xyz, axis=0).shape[0]
        z = np.asarray(ch.z, dtype="f8")
        q1, q3 = np.percentile(z, [25, 75])
        iqr = q3 - q1
        z_bajo += int((z < q1 - k_iqr * iqr).sum())
        z_alto += int((z > q3 + k_iqr * iqr).sum())
        it = np.asarray(ch.intensity)
        inten_sat += int((it >= 255).sum())
        rgb = np.stack([np.asarray(ch.red), np.asarray(ch.green), np.asarray(ch.blue)], 1)
        if rgb.max() > 255:
            rgb_16_bits_reales = True
            rgb = rgb >> 8
        rgb_negro += int((rgb.sum(axis=1) == 0).sum())
        h, s_, v = hsv(rgb)
        hues.append(h); sats.append(s_); vals.append(v)
        inten_all.append(it[::20]); z_all.append(z[::20])
    h = np.concatenate(hues); s_ = np.concatenate(sats); v = np.concatenate(vals)
    saturado = (s_ >= sat_min) & (v >= val_min)
    verde = saturado & (h >= banda_verde[0]) & (h <= banda_verde[1])
    calido = saturado & (h < 60 / 360)

    # ------------------------------------------------------------------ figuras
    print("  figuras...")
    figs = {}

    fig, axes = plt.subplots(1, len(escaneos), figsize=(4.2 * len(escaneos), 4.1))
    axes = np.atleast_1d(axes)
    for ax, s in zip(axes, escaneos):
        g = [c for c in cab if c["scan"] == s]
        for c in g:
            ax.add_patch(plt.Rectangle((c["min_x"], c["min_y"]), c["extent_x_m"],
                                       c["extent_y_m"], facecolor=AZUL, alpha=.2,
                                       edgecolor=AZUL, linewidth=.8))
        ax.set_xlim(min(c["min_x"] for c in g) - 40, max(c["max_x"] for c in g) + 40)
        ax.set_ylim(min(c["min_y"] for c in g) - 40, max(c["max_y"] for c in g) + 40)
        ax.set_aspect("equal")
        ax.ticklabel_format(style="plain", useOffset=False)
        ax.tick_params(axis="x", rotation=30)
        _estilo(ax, f"{s}\n{len(g)} archivos · {sum(c['point_count'] for c in g)/1e6:.0f} M pts",
                "Este UTM (m)", "Norte UTM (m)")
    figs["huellas"] = _guardar(fig, "fig01_huellas_escaneos.png")

    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.hist(dens, bins=28, color=AZUL, alpha=.85, edgecolor="white", linewidth=.5)
    ax.axvline(np.median(dens), color=ROJO, ls="--", lw=1.4,
               label=f"mediana {np.median(dens):.0f} pts/m²")
    ax.legend(frameon=False, fontsize=8.5)
    _estilo(ax, f"Densidad horizontal por archivo · varía {dens.max()/dens.min():.0f}x",
            "puntos por m² (sobre la huella del archivo)", "archivos")
    figs["densidad"] = _guardar(fig, "fig02_densidad_por_archivo.png")

    fig, ax = plt.subplots(figsize=(8, 3.2))
    etiquetas = [str(k) for k in sorted(clases)]
    ax.bar(etiquetas, [clases[k] for k in sorted(clases)], color=GRIS)
    _estilo(ax, f"Valores de `classification` en la muestra · {100*clases.get(1,0)/n_m:.2f} % = 1 (sin clasificar)",
            "código LAS", "puntos")
    figs["clasificacion"] = _guardar(fig, "fig03_clasificacion.png")

    fig, ax = plt.subplots(figsize=(8, 3.2))
    ks = sorted(anillos)
    ax.bar([str(k) for k in ks], [anillos[k] for k in ks], color=AZUL, alpha=.85)
    _estilo(ax, f"Índice de láser (point_source_id) · {len(ks)} anillos: firma del Velodyne VLP-16",
            "anillo", "puntos")
    figs["anillos"] = _guardar(fig, "fig04_anillos_laser.png")

    fig, axes = plt.subplots(1, 2, figsize=(11, 3.4))
    axes[0].hist(np.concatenate(inten_all), bins=64, color=AZUL, alpha=.85)
    _estilo(axes[0], "Intensidad del retorno", "valor (0–255)", "puntos (1/20)")
    axes[1].hist(np.concatenate(z_all), bins=80, color=AZUL, alpha=.85)
    _estilo(axes[1], "Altura Z absoluta", "metros", "puntos (1/20)")
    figs["intensidad_z"] = _guardar(fig, "fig05_intensidad_y_altura.png")

    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.hist(h[saturado] * 360, bins=36, range=(0, 360), color=GRIS, alpha=.8)
    ax.axvspan(banda_verde[0] * 360, banda_verde[1] * 360, color=VERDE, alpha=.18,
               label=f"banda verde {banda_verde[0]*360:.0f}–{banda_verde[1]*360:.0f}°")
    ax.legend(frameon=False, fontsize=8.5)
    _estilo(ax, f"Tono del color (puntos saturados) · verde {100*verde.sum()/n_m:.2f} % de la muestra",
            "tono (grados)", "puntos")
    figs["tono"] = _guardar(fig, "fig06_tono_del_color.png")

    # ------------------------------------------------------------------ resultado
    resultado = {
        "descripcion": "Cifras del EDA sobre los datos entregados. Determinista: "
                       "sin marcas de tiempo ni aleatoriedad.",
        "datos_recolectados": {
            "fuente": "Nubes LiDAR .laz de cartografía móvil (Velodyne VLP-16), "
                      "entregadas por enlace de OneDrive",
            "unidad_de_analisis": "punto LiDAR; para modelado, tesela de 40 m",
            # <grupo>/<escaneo>/LiDAR/GeoRef/<archivo>.laz
            "grupos": sorted({Path(c["path"]).parts[-5] for c in cab}),
            "escaneos": escaneos,
            "archivos_laz": len(cab),
            "bytes_comprimidos": int(sum(c["file_size_bytes"] for c in cab)),
            "n_registros_puntos": puntos,
            "n_variables_por_punto": len(dimensiones),
            "variables_por_punto": dimensiones,
            "n_variables_informativas": len(param("select.keep_dimensions")),
            "formato": {"las_version": sorted({c["las_version"] for c in cab}),
                        "point_format": sorted({c["point_format"] for c in cab}),
                        "escala_m": cab[0]["scales"]},
            "periodo_cubierto": periodos,
            "variable_objetivo": "classification (LAS): clase de la ontología por punto",
            "variable_objetivo_estado": f"{100*clases.get(1,0)/n_m:.2f} % de los puntos "
                                        f"muestreados = 1 (sin clasificar): la variable "
                                        f"objetivo aún no existe; se construye anotando",
            "estado_acceso": "Disponible: descargado y verificado por hash",
        },
        "calidad": {
            "faltantes": {
                "archivos_sin_crs_pct": _r(100 * sin_crs / len(cab), 2),
                "puntos_sin_color_pct": _r(100 * rgb_negro / n_m, 4),
                "puntos_sin_etiqueta_pct": _r(100 * clases.get(1, 0) / n_m, 4),
            },
            "duplicados_inconsistencias": {
                "puntos_duplicados_exactos_pct": _r(100 * dup / n_m, 4),
                "color_16_bits_con_valores_8_bits": not rgb_16_bits_reales,
                "retornos_distintos_de_1_pct": _r(100 * (n_m - retornos.get(1, 0)) / n_m, 4),
            },
            "atipicos": {
                "regla": f"Tukey sobre Z por archivo, k = {k_iqr}",
                "z_por_debajo_pct": _r(100 * z_bajo / n_m, 4),
                "z_por_encima_pct": _r(100 * z_alto / n_m, 4),
                "intensidad_saturada_255_pct": _r(100 * inten_sat / n_m, 4),
                "decision": "No se borran en el EDA. La etapa de limpieza (E3) usa recorte "
                            "por altura sobre el suelo y filtro de componentes, nunca SOR "
                            "global: ver docs/decisiones/0004-el-sor-destruye-los-cables.md",
            },
            "sesgo_representatividad": {
                "dias_de_captura": len({p.get("fecha") for p in periodos.values()}),
                "escaneos": len(escaneos),
                "densidad_min_pts_m2": _r(dens.min(), 1),
                "densidad_mediana_pts_m2": _r(np.median(dens), 1),
                "densidad_max_pts_m2": _r(dens.max(), 1),
                "densidad_razon_max_min": _r(dens.max() / dens.min(), 1),
                "anillos_laser": len(anillos),
                "retorno_unico": set(retornos) == {1},
                "puntos_saturados_tono_calido_pct": _r(100 * calido.sum() / max(1, saturado.sum()), 2),
            },
        },
        "hallazgos": [
            {"cifra": f"{100*clases.get(1,0)/n_m:.2f} % de los puntos con classification = 1",
             "consecuencia": "no hay variable objetivo: la ruta crítica es la anotación, "
                             "no la elección de arquitectura",
             "evidencia": figs["clasificacion"]},
            {"cifra": f"densidad de {dens.min():.0f} a {dens.max():.0f} pts/m² "
                      f"({dens.max()/dens.min():.0f}x)",
             "consecuencia": "un radio de vecindad fijo no es comparable entre zonas: rasgos "
                             "multiescala y reducción por vóxeles",
             "evidencia": figs["densidad"]},
            {"cifra": f"{len(anillos)} anillos de láser y retorno único",
             "consecuencia": "sensor VLP-16 (±3 cm): la precisión milimétrica no es alcanzable "
                             "y el suelo debe ajustarse geométricamente",
             "evidencia": figs["anillos"]},
            {"cifra": f"{100*verde.sum()/n_m:.2f} % de los puntos (a cualquier altura, copas "
                      f"incluidas) con tono verde saturado; "
                      f"{100*calido.sum()/max(1,saturado.sum()):.0f} % de los saturados con "
                      f"tono cálido",
             "consecuencia": "la clase área verde no puede apoyarse solo en el color: "
                             "reglas provisionales y corrección humana",
             "evidencia": figs["tono"]},
            {"cifra": f"{100*sin_crs/len(cab):.0f} % de archivos sin sistema de referencia",
             "consecuencia": "se estampa EPSG:32718 en toda exportación a SIG/CAD",
             "evidencia": figs["huellas"]},
        ],
        "muestra": {
            "archivos": len(muestra),
            "puntos_por_archivo_max": n_bloque,
            "puntos": int(n_m),
            "criterio": "cada k-ésimo archivo en orden de ruta, primer bloque",
        },
        "figuras": figs,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "eda.json").write_text(
        json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")

    b6 = resultado["datos_recolectados"]
    print(f"\n  puntos: {b6['n_registros_puntos']:,} · archivos: {b6['archivos_laz']} · "
          f"variables: {b6['n_variables_por_punto']}")
    for s, per in periodos.items():
        print(f"  {s}: {per.get('dia','')} {per.get('fecha','')} "
              f"{per.get('inicio_hora_local','')}–{per.get('fin_hora_local','')}")
    print(f"  Escrito: {(OUT / 'eda.json').relative_to(PATHS.root).as_posix()} "
          f"y {len(figs)} figuras")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
