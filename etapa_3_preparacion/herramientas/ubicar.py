"""Convierte coordenadas del proyecto en un enlace a Google Maps o Street View.

    python herramientas/ubicar.py b_1463_43337           # el centro de un bloque
    python herramientas/ubicar.py 292700 8667500         # una coordenada UTM
    python herramientas/ubicar.py b_1463_43337 --abrir   # y lo abre en el navegador
    python herramientas/ubicar.py --todos ate            # todos los bloques de un escaneo

PARA QUE SIRVE AL ANOTAR. Street View resuelve las dudas que la nube no
resuelve: si un poste lleva luminaria, si es de media o de baja, si lo que
parece un pastoral es en realidad una mensula con la BT colgando. Mirar la calle
antes de decidir una clase vale mas que afinar un umbral, y una etiqueta mal
puesta contamina el entrenamiento mucho despues.

Aviso sobre las fotos: las de Street View son de otro ano que el escaneo LiDAR
(ate es de noviembre de 2025 y Pachacamac de agosto de 2025). La red cambia:
un poste puede haberse cambiado o retirado. Sirve para reconocer el TIPO de
estructura, no para confirmar que ese poste exacto sigue ahi.

EL CRS. Los .laz no declaran ninguno —`parse_crs()` devuelve None en los 474
archivos— y el proyecto asume EPSG:32718 (WGS84 / UTM 18S) porque las
coordenadas son inequivocamente easting/northing de esa zona
(docs/decisiones/0001). Esta herramienta es la comprobacion mas barata de esa
suposicion: si un bloque de `ate/` cae en Ate, la suposicion se sostiene.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "codigo"))

from common.anotacion import indice_bloque  # noqa: E402
from common.config import PATHS, param  # noqa: E402


def a_geograficas(x: float, y: float) -> tuple[float, float]:
    """(lat, lon) en WGS84 desde el UTM del proyecto."""
    from pyproj import Transformer
    # always_xy: pyproj devuelve (lon, lat) con este orden, no (lat, lon).
    # Sin esto el resultado sale invertido y el enlace lleva a otro continente.
    t = Transformer.from_crs(f"EPSG:{int(param('project.crs_epsg'))}",
                             "EPSG:4326", always_xy=True)
    lon, lat = t.transform(x, y)
    return lat, lon


def centro_de_bloque(ix: int, iy: int) -> tuple[float, float]:
    size = float(param("tiling.bloque_m"))
    return ix * size + size / 2, iy * size + size / 2


def enlaces(lat: float, lon: float) -> tuple[str, str]:
    return (f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}",
            f"https://www.google.com/maps?q&layer=c&cbll={lat:.6f},{lon:.6f}")


def informe(etiqueta: str, x: float, y: float, abrir: bool) -> None:
    lat, lon = a_geograficas(x, y)
    mapa, calle = enlaces(lat, lon)
    print(f"\n  {etiqueta}")
    print(f"    UTM 18S      {x:.1f}, {y:.1f}")
    print(f"    lat, lon     {lat:.6f}, {lon:.6f}")
    print(f"    mapa         {mapa}")
    print(f"    street view  {calle}")
    if abrir:
        webbrowser.open(calle)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("args", nargs="*",
                    help="un nombre de bloque (b_1463_43337), o dos numeros: "
                         "easting northing")
    ap.add_argument("--todos", metavar="ESCANEO",
                    help="todos los bloques de un escaneo, por su nombre o "
                         "parte de el (p. ej. ate, AVP01MT2611202501)")
    ap.add_argument("--abrir", action="store_true",
                    help="abre Street View en el navegador")
    a = ap.parse_args()

    if a.todos:
        hallados = sorted(p for p in PATHS.bloques.rglob("b_*.laz")
                          if a.todos.lower() in str(p.parent).lower())
        if not hallados:
            print(f"  [X] nada que coincida con '{a.todos}' en {PATHS.bloques}")
            return 1
        print(f"  {len(hallados)} bloques")
        for p in hallados:
            t = indice_bloque(p.stem)
            if t is None:
                continue
            lat, lon = a_geograficas(*centro_de_bloque(*t))
            print(f"    {p.parent.name}/{p.stem:<16}{lat:>11.6f},{lon:>11.6f}"
                  f"   https://www.google.com/maps?q={lat:.6f},{lon:.6f}")
        return 0

    if len(a.args) == 1:
        t = indice_bloque(a.args[0])
        if t is None:
            print(f"  [X] '{a.args[0]}' no es un nombre de bloque. Tiene que ser "
                  "b_<ix>_<iy>, o pasa dos numeros: easting northing")
            return 1
        informe(f"bloque {a.args[0]} (centro)", *centro_de_bloque(*t), abrir=a.abrir)
        return 0

    if len(a.args) == 2:
        try:
            x, y = (float(v) for v in a.args)
        except ValueError:
            print("  [X] las dos coordenadas tienen que ser numeros")
            return 1
        # Un aviso que ahorra tiempo: si CloudCompare aplico su global shift al
        # abrir, las coordenadas que muestra NO son las UTM y la conversion sale
        # a otro continente sin que nada falle.
        if not (100_000 <= x <= 1_000_000 and 1_000_000 <= y <= 10_000_000):
            print(f"  [!] {x:.0f}, {y:.0f} no parecen UTM 18S de Lima, donde el "
                  "easting ronda 250-350 mil y el northing los 8.6 millones.")
            print("      Lo mas probable: CloudCompare aplico su GLOBAL SHIFT al "
                  "abrir el archivo y te mostro coordenadas desplazadas.")
        informe("coordenada", x, y, abrir=a.abrir)
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
