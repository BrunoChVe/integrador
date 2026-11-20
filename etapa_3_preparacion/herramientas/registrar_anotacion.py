"""Registra los recortes hechos a mano, con validacion antes de aceptarlos.

    python herramientas/registrar_anotacion.py recortes/b_1466_433341__poste_bt.laz
    python herramientas/registrar_anotacion.py recortes/*.laz
    python herramientas/registrar_anotacion.py --estado

COMO SE ANOTA. Abres un bloque de
`datos/intermedio/01_bloques/<grupo>/<distrito>/<escaneo>/` en
CloudCompare, recortas con las tijeras los puntos de UNA clase, y guardas el
recorte con el nombre del bloque y la clase al final:

    b_1466_433341__poste_bt.laz
    b_1466_433341__poste_mt.laz

La CLASE la pone el NOMBRE del archivo, no su contenido: asi no depende de que
haga CloudCompare con el campo `classification` al guardar, que es la fuente
mas comun de error. Un poste con luminaria es UN solo recorte (0023): el
poste entero, con pastoral y luminaria, como `poste_bt` o `poste_mt`. Entre
0017 y 0023 eran dos recortes, y la clase `luminaria` queda obsoleta.

Se pueden entregar varios recortes del mismo bloque, en la misma corrida o en
dias distintos, y se ACUMULAN: cada recorte manda donde toca y lo registrado
antes se conserva. Si dos recortes se solapan, gana el ultimo registrado.

QUE SE GUARDA. Solo los puntos que recortaste, en
`datos/crudo/anotacion/<grupo>/<distrito>/<escaneo>/b_<ix>_<iy>.laz` —la misma
ruta que el bloque bajo `01_bloques/`— con su clase en
`classification`. No el bloque entero: todo punto del archivo es verdad de
campo por construccion y lo que no esta simplemente no se ha mirado. Son KB en
vez de GB.

POR QUE NO SE GUARDA DENTRO DE `01_bloques/`. La etapa 02 borra su carpeta de
salida entera antes de regenerarla, asi que una correccion guardada ahi se
perderia en el siguiente `dvc repro`. `datos/crudo/anotacion/` no la toca ninguna
etapa.

QUE COMPRUEBA ANTES DE ACEPTAR UN ARCHIVO, y por que:

 1. Que el nombre lleve la clase: `<region>__<clase>.laz`. Sin ella no hay
    forma de saber que se recorto.
 2. Que la clase este en la ontologia Y ACTIVA. Desde 0023 solo los dos
    postes lo estan; registrar una clase en espera dejaria una etiqueta que ninguna
    etapa lee, y el trabajo se daria por hecho sin llegar al entrenamiento.
 3. Que el nombre apunte a un bloque que existe. Solo eso: A DONDE va el
    recorte lo decide su geometria, no su nombre. Importa porque las pasadas
    del vehiculo se solapan y un mismo id de bloque existe en varios escaneos
    —en ate, 24 de 106—, asi que el nombre no identifica un archivo unico.
 4. Que el recorte caiga de verdad sobre puntos del bloque. Si no empareja casi
    nada, lo normal es que CloudCompare haya guardado con el global shift
    aplicado, y hay que volver a exportar sin el.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "codigo"))

import numpy as np  # noqa: E402

from common.anotacion import (extension_bloque, indice_bloque,  # noqa: E402
                              leer_laz)
from common.config import (CLASS_ESTADO, CLASS_NAMES, CLASS_NAMES_ES,  # noqa: E402
                           PATHS, TARGET_IDS, es_activa, param)
from common.io_cloud import Cloud, write_las  # noqa: E402

# Se acepta el nombre en ingles de la ontologia y el español del manual: el
# anotador tiene delante `poste_bt`, no `pole_lv`, y equivocarse de idioma al
# teclear un nombre de archivo no deberia costar un rechazo.
POR_NOMBRE = {n: i for i, n in CLASS_NAMES.items()}
POR_NOMBRE.update({n: i for i, n in CLASS_NAMES_ES.items()})
MIN_COBERTURA = 0.99   # por debajo, avisar: parte del recorte no cayo en nada


class Rechazo(Exception):
    """Un archivo que no pasa la validacion. No se escribe nada."""


# Tambien vale el nombre con que se trabaja el etiquetado: el recorte se guarda
# junto a su nube en data/etiquetado/<escaneo>/<train|test>/ con sufijo _BT o _MT.
SUFIJOS_CLASE = {"BT": "poste_bt", "MT": "poste_mt"}


def partir_nombre(stem: str) -> tuple[str, str | None]:
    """`b_1466_433341__poste_bt` o `b_1466_433341_BT` -> ('b_1466_433341', 'poste_bt')."""
    if "__" in stem:
        region, clase = stem.rsplit("__", 1)
        return region, clase
    region, _, sufijo = stem.rpartition("_")
    if region and sufijo.upper() in SUFIJOS_CLASE:
        return region, SUFIJOS_CLASE[sufijo.upper()]
    return stem, None


def bloques_bajo(xyz_c: np.ndarray) -> list[Path]:
    """Candidatos: todo bloque del arbol cuya extension cubre algun punto.

    SE PREGUNTA POR GEOMETRIA, NUNCA POR EL NOMBRE. Dos razones, y la segunda
    es la que obliga:

      1. El anillo de contexto de `buffer_m` pertenece a DOS bloques vecinos,
         asi que un recorte guardado como `b_1466_433341__poste_bt` puede tener
         puntos que viven tambien en el de al lado. Hay que corregirlos en los
         dos o, al entrenar sobre el vecino, saldrian sin etiquetar.

      2. LAS PASADAS SE SOLAPAN. Un mismo id de bloque existe en varios
         escaneos —medido en ate: 24 de 106 ids estan en 2 o 3— porque el
         vehiculo recorrio la misma calle mas de una vez. Resolver el escaneo
         por el nombre del archivo elegia uno arbitrario, el primero
         alfabeticamente, y podia buscar pareja contra los puntos de OTRA
         pasada: otra medicion del mismo poste, no los mismos puntos. A la
         tolerancia de 5 mm eso no empareja casi nada, asi que el recorte se
         rechazaba o se registraba a medias.

    Devolver todos los candidatos y dejar que el emparejamiento por coordenada
    decida es autocorrector: solo el escaneo del que salio el recorte tiene esos
    puntos exactos, asi que solo ahi se registra. No hay que saber de que
    archivo salio.

    El filtro es aritmetica sobre el id del bloque, sin leer un punto, asi que
    recorrer el arbol entero es instantaneo.
    """
    objetivos = []
    for p in sorted(PATHS.bloques.rglob("b_*.laz")):
        t = indice_bloque(p.stem)
        if t is None:
            continue
        x0, y0, x1, y1 = extension_bloque(*t)
        dentro = ((xyz_c[:, 0] >= x0) & (xyz_c[:, 0] < x1) &
                  (xyz_c[:, 1] >= y0) & (xyz_c[:, 1] < y1))
        if dentro.any():
            objetivos.append(p)
    return objetivos


def destino_de(bloque: Path) -> Path:
    """Donde se guarda la verdad de campo de este bloque.

    Reproduce bajo `datos/crudo/anotacion/` la misma ruta que el bloque ocupa
    bajo `datos/intermedio/01_bloques/`, que a su vez es la que ocupa su escaneo
    bajo `datos/crudo/`. Una sola regla para las tres carpetas: asi no hay dos
    convenciones que recordar al buscar un archivo a mano.
    """
    return PATHS.annotation_revisada / bloque.relative_to(PATHS.bloques)


def registrar_en(bloque: Path, xyz_c: np.ndarray, clase_id: int,
                 tol: float) -> dict | None:
    """Aplica el recorte a un bloque, encima de lo ya registrado en el.

    Devuelve None si el recorte no empareja con ningun punto de este bloque.
    """
    from scipy.spatial import cKDTree

    xyz_b, _ = leer_laz(bloque)
    # Se empareja del BLOQUE al recorte, no al reves, para quedarse con las
    # coordenadas exactas del bloque: guardar en CloudCompare puede reordenar
    # los puntos y redondear la ultima cifra, y la verdad de campo tiene que
    # apuntar a los puntos reales o al entrenar no encontraria pareja.
    d, _ = cKDTree(xyz_c).query(xyz_b, distance_upper_bound=tol)
    nuevos = np.flatnonzero(np.isfinite(d))
    if nuevos.size == 0:
        return None

    xyz_nuevo = xyz_b[nuevos]
    clases_nuevo = np.full(nuevos.size, clase_id, dtype="u1")

    # Acumular sobre lo ya registrado. Donde los dos coinciden manda el nuevo:
    # volver a registrar un punto es corregirse, y la correccion mas reciente
    # es la que vale.
    destino = destino_de(bloque)
    previos = 0
    if destino.exists():
        xyz_v, clases_v = leer_laz(destino)
        previos = len(xyz_v)
        if previos:
            dv, _ = cKDTree(xyz_nuevo).query(xyz_v, distance_upper_bound=tol)
            conserva = ~np.isfinite(dv)
            xyz_nuevo = np.concatenate([xyz_v[conserva], xyz_nuevo])
            clases_nuevo = np.concatenate([clases_v[conserva], clases_nuevo])

    # Que puntos del RECORTE cayeron sobre este bloque. Se pregunta desde el
    # recorte y no desde el bloque: si el recorte trae puntos repetidos —pasa
    # al fusionar en CloudCompare trozos que se solapan— cada punto del bloque
    # solo "ve" a uno de los repetidos y el otro pareceria huerfano.
    dc, _ = cKDTree(xyz_b[nuevos]).query(xyz_c, distance_upper_bound=tol)
    return {"xyz": xyz_nuevo, "clases": clases_nuevo,
            "anadidos": int(nuevos.size), "previos": previos,
            "usados": np.flatnonzero(np.isfinite(dc)), "destino": destino}


def guardar(info: dict) -> Path:
    info["destino"].parent.mkdir(parents=True, exist_ok=True)
    write_las(info["destino"], Cloud(info["xyz"]),
              epsg=int(param("project.crs_epsg")), labels=info["clases"])
    return info["destino"]


def registrar(ruta: Path, tol: float) -> bool:
    print(f"\n  {ruta.name}")
    try:
        return _registrar(ruta, tol)
    except Rechazo as e:
        print(f"    [X] {e}")
        return False


def _registrar(ruta: Path, tol: float) -> bool:
    if ruta.suffix.lower() not in (".laz", ".las"):
        raise Rechazo("no es un .laz ni un .las")

    region, clase = partir_nombre(ruta.stem)
    activas = ", ".join(CLASS_NAMES_ES[c] for c in TARGET_IDS)
    if clase is None:
        raise Rechazo("al nombre le falta la clase. Tiene que acabar en "
                      f"__<clase>.laz o en _BT / _MT, con una de estas: {activas}")
    if clase not in POR_NOMBRE:
        raise Rechazo(f"'{clase}' no es una clase de la ontologia. "
                      f"Las del alcance actual son: {activas}")
    clase_id = POR_NOMBRE[clase]
    if not es_activa(clase_id):
        pista = ""
        if CLASS_NAMES_ES.get(clase_id) == "luminaria":
            pista = (" Desde 0023 la luminaria es parte del poste: une este "
                     "recorte con el del fuste en CloudCompare y guardalo "
                     "como __poste_bt o __poste_mt.")
        raise Rechazo(f"la clase '{clase}' esta en estado "
                      f"'{CLASS_ESTADO[clase_id]}', fuera del alcance de esta "
                      f"fase (0023). Las activas son: {activas}.{pista}")

    xyz_c, _ = leer_laz(ruta)
    if len(xyz_c) == 0:
        raise Rechazo("el archivo no tiene puntos")

    # El nombre solo sirve de comprobacion: que apunte a algo que existe, para
    # pillar un archivo renombrado. A DONDE va el recorte lo decide su
    # geometria, no su nombre (ver `bloques_bajo`).
    if indice_bloque(region) is not None and not any(
            PATHS.bloques.rglob(f"{region}.laz")):
        raise Rechazo(f"no hay ningun bloque llamado '{region}'. "
                      "¿Se renombro el archivo?")

    objetivos = bloques_bajo(xyz_c)
    if not objetivos:
        raise Rechazo("el recorte no cae dentro de ningun bloque. "
                      "¿Se guardo con el global shift aplicado?")

    usado = np.zeros(len(xyz_c), dtype=bool)
    filas = []
    for bloque in objetivos:
        info = registrar_en(bloque, xyz_c, clase_id, tol)
        if info is None:
            continue
        usado[info["usados"]] = True
        guardar(info)
        etiqueta = f"{bloque.parent.name}/{bloque.stem}"
        filas.append((etiqueta, info["anadidos"], len(info["xyz"])))

    if not filas:
        raise Rechazo("ningun punto del recorte coincide con el bloque. "
                      "¿Se guardo con el global shift aplicado?")

    anadidos = sum(f[1] for f in filas)
    cobertura = float(usado.mean())
    print(f"    OK · {CLASS_NAMES_ES[clase_id]} · {len(filas)} bloque(s) · "
          f"{anadidos:,} puntos registrados")
    if len(filas) > 1:
        # Se imprime el escaneo ademas del bloque: con pasadas que se solapan,
        # el mismo id de bloque existe en varios y hay que poder ver en cual
        # cayo de verdad el recorte.
        for nombre, n, total in filas:
            print(f"        {nombre:<42}{n:>9,} nuevos{total:>11,} en total")
    print(f"    cobertura del recorte: {100 * cobertura:.1f} % de sus puntos emparejados")
    repetidos = len(xyz_c) - len(np.unique(np.round(xyz_c, 3), axis=0))
    if repetidos:
        print(f"    ({repetidos:,} puntos repetidos en el recorte: suele pasar al "
              "fusionar trozos que se solapan. No afecta.)")
    if cobertura < MIN_COBERTURA:
        print(f"    [!] {int((~usado).sum()):,} puntos del recorte no cayeron sobre "
              "ningun bloque. Si son muchos, revisa el global shift al guardar.")
    return True


def estado() -> None:
    bloques = sorted(PATHS.bloques.rglob("b_*.laz"))
    anotados = sorted(PATHS.annotation_revisada.rglob("b_*.laz"))
    print(f"\n  bloques disponibles  : {len(bloques)}")
    print(f"  bloques con anotacion: {len(anotados)}")

    # El recuento POR CLASE es la cifra que dice si el conjunto da para
    # entrenar, y la que hay que mirar antes de dejar de anotar. Un total de
    # puntos no la sustituye: tres postes de MT y mil de BT suman mucho y no
    # entrenan nada.
    porclase: Counter = Counter()
    for r in anotados:
        _, clases = leer_laz(r)
        rel = r.relative_to(PATHS.annotation_revisada).as_posix()
        print(f"    {rel:<58}{len(clases):>9,} puntos")
        porclase.update(int(c) for c in clases)
    print("\n  verdad de campo por clase:")
    for cid in TARGET_IDS:
        print(f"    {cid:>2} {CLASS_NAMES_ES[cid]:<16}{porclase.get(cid, 0):>10,}")
    fuera = {c: n for c, n in porclase.items() if c not in TARGET_IDS}
    if fuera:
        print(f"  [!] clases fuera del alcance en los archivos: {fuera}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("archivos", nargs="*", type=Path)
    ap.add_argument("--estado", action="store_true",
                    help="muestra cuanta verdad de campo hay, por bloque y por clase")
    args = ap.parse_args()

    if args.estado:
        estado()
        return 0
    if not args.archivos:
        ap.print_help()
        return 2

    tol = float(param("anotacion.tolerancia_m"))
    aceptados = sum(registrar(r, tol) for r in args.archivos)
    print(f"\n  {aceptados} de {len(args.archivos)} registrados")
    if aceptados:
        print("\n  Para versionarlos:")
        print("    dvc add datos/crudo/anotacion")
        print("    git add datos/crudo/anotacion.dvc")
        print('    git commit -m "anotacion: <que se etiqueto>"')
        print("    dvc push && git push")
    return 0 if aceptados == len(args.archivos) else 1


if __name__ == "__main__":
    raise SystemExit(main())
