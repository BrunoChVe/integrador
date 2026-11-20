"""Nombres de bloque y lectura de la verdad de campo.

Dos consumidores comparten esto —`herramientas/registrar_anotacion.py` y la etapa de
entrenamiento, cuando se escriba— y los dos tienen que entender los archivos
EXACTAMENTE igual. Por eso vive aqui y no copiado en cada sitio.

EL BLOQUE (docs/decisiones/0018). La unidad de almacenamiento y de anotacion es
el bloque de `tiling.bloque_m` (200 m), a resolucion completa. Hasta 0018 era
la tesela de 40 m, demasiado pequena para anotar: un vano de MT mide 50-70 m y
salia cortado siempre. Hubo un parche intermedio —la ZONA de 0016, que agrupaba
teselas al VER para volver a partirlas al REGISTRAR— que con el bloque dejo de
hacer falta y se ha borrado: lo que se abre, lo que se recorta y lo que se
registra son el mismo archivo.

SOLO LOS PUNTOS REVISADOS. Un archivo de `annotation_revisada/` contiene
unicamente los puntos que una persona miro y clasifico, no el bloque entero.
Antes de 0017 se guardaba el bloque completo con una dimension extra `revisado`
que valia 1 en lo tocado, porque hacia falta distinguir la correccion humana
del BORRADOR geometrico que rellenaba el resto. Al quitar el borrador esa
distincion desaparece: todo punto presente en el archivo es verdad de campo por
construccion, y todo punto ausente simplemente no se ha mirado. Es mas simple y
ademas pesa KB en vez de GB —un bloque son 2-17 M puntos y lo anotado son
miles—, asi que la verdad de campo cabe en el remoto sin pensarlo.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

import numpy as np

from common.config import long_path, param

_NOMBRE_BLOQUE = re.compile(r"^b_(-?\d+)_(-?\d+)$")


def indice_bloque(nombre: str) -> Tuple[int, int] | None:
    """`b_1466_433341` -> (1466, 433341). None si no es un nombre de bloque.

    El prefijo es `b_` y no `t_` a proposito: los nombres `t_<ix>_<iy>` de
    antes de 0018 indexaban una rejilla de 40 m, asi que un `t_7322_216695`
    suelto cubre otro suelo distinto. Prefijos distintos hacen imposible
    mezclar las dos rejillas por descuido.
    """
    m = _NOMBRE_BLOQUE.match(nombre)
    return (int(m.group(1)), int(m.group(2))) if m else None


def nombre_bloque(ix: int, iy: int) -> str:
    return f"b_{ix}_{iy}"


def extension_bloque(ix: int, iy: int) -> Tuple[float, float, float, float]:
    """(xmin, ymin, xmax, ymax) de lo que guarda el bloque, anillo incluido.

    El bloque almacena su nucleo de `tiling.bloque_m` mas un anillo de contexto
    de `tiling.buffer_m`, asi que un mismo punto puede estar en dos bloques.
    Quien reparta un recorte tiene que mirar la extension CON anillo, o esos
    puntos quedarian corregidos en un bloque y no en su vecino.
    """
    size = float(param("tiling.bloque_m"))
    buf = float(param("tiling.buffer_m"))
    return (ix * size - buf, iy * size - buf,
            (ix + 1) * size + buf, (iy + 1) * size + buf)


def bloques_vecinos(bloque: Tuple[int, int], disponibles: List[Tuple[int, int]],
                    radio: int) -> List[Tuple[int, int]]:
    """Bloques vecinos, hasta `radio` bloques de distancia."""
    if radio <= 0:
        return []
    return sorted(b for b in disponibles
                  if b != bloque
                  and max(abs(b[0] - bloque[0]), abs(b[1] - bloque[1])) <= radio)


def leer_laz(ruta: Path) -> Tuple[np.ndarray, np.ndarray]:
    """(xyz, classification) de un .laz. Es como se leen recortes y verdad."""
    import laspy
    with laspy.open(long_path(ruta)) as fh:
        d = fh.read()
    xyz = np.stack([np.asarray(d.x), np.asarray(d.y), np.asarray(d.z)], axis=1)
    return xyz, np.asarray(d.classification).astype("u1")
