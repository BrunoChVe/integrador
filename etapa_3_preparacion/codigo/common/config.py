"""Project paths and parameter loading.

Every stage imports `PARAMS` and `PATHS` from here instead of hard-coding a
threshold or a directory. That is what makes the rule "no constant inside the
code" checkable: grep the stages for a literal number and there should be
almost nothing to find.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

# --------------------------------------------------------------------------
# Raiz del repositorio. Se descubre, no se escribe: el arbol se puede mover o
# clonar en cualquier sitio, y sin `.git` (una copia en ZIP) tambien funciona.
# La raiz es la carpeta que contiene a la vez `datos/` y la etapa 3; los
# parametros y el pipeline viven en `etapa_3_preparacion/`.
# --------------------------------------------------------------------------
_MARKERS = ("datos", "etapa_3_preparacion")
ETAPA = "etapa_3_preparacion"


def find_repo_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if all((candidate / m).is_dir() for m in _MARKERS):
            return candidate
    raise RuntimeError(
        "Raiz del repositorio no encontrada: ninguna carpeta por encima de "
        f"{here} contiene a la vez {_MARKERS}"
    )


ROOT = find_repo_root()


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def etapa(self) -> Path:
        """etapa_3_preparacion/: dvc.yaml, params.yaml, codigo/ y reportes/."""
        return self.root / ETAPA

    @property
    def raw(self) -> Path:
        """El crudo, inmutable: solo punteros .dvc en git."""
        return self.root / "datos" / "crudo"

    @property
    def interim(self) -> Path:
        return self.root / "datos" / "intermedio"

    @property
    def final(self) -> Path:
        return self.root / "datos" / "final"

    @property
    def catalogo(self) -> Path:
        """Inventario y catalogo de archivos. Son tablas, asi que no van a
        git: los versiona DVC como salida de `seleccionar`."""
        return self.interim / "catalogo"

    @property
    def reports(self) -> Path:
        return self.etapa / "reportes"

    @property
    def resultados_eda(self) -> Path:
        return self.root / "etapa_1_2_comprension" / "resultados"

    @property
    def diccionario(self) -> Path:
        return self.root / "docs" / "diccionario"

    @property
    def bloques(self) -> Path:
        """Bloques de 200 m a resolucion completa: lo que se abre para anotar.

        Es la salida de la etapa 02 y la unidad de almacenamiento y de
        anotacion (docs/decisiones/0018). Se llamaba `01_tiles` cuando la tesela
        de 40 m era a la vez unidad de almacenamiento, de anotacion y de
        entrenamiento; ahora son dos rejillas distintas y el nombre de la
        carpeta dice cual de las dos vive aqui.

        Sigue bajo `interim/` aunque ya no haya etapas intermedias detras: es
        derivado de `datos/crudo` y `dvc repro` lo regenera.
        """
        return self.interim / "01_bloques"

    @property
    def annotation_revisada(self) -> Path:
        """Bloques corregidos a mano. NINGUNA etapa escribe aqui.

        Separarlos de la salida de `bloques` no es orden por gusto: esa etapa
        borra su carpeta entera antes de regenerarla, asi que una correccion
        guardada ahi se perderia en el siguiente `dvc repro`. Vive bajo
        `datos/crudo/` porque es un dato de entrada hecho por personas, no un
        derivado: se registra a mano con `dvc add`, como el resto del crudo.
        """
        return self.raw / "anotacion"

    def ensure(self) -> "Paths":
        for p in (self.interim, self.reports, self.catalogo):
            p.mkdir(parents=True, exist_ok=True)
        return self


PATHS = Paths(ROOT).ensure()


@lru_cache(maxsize=1)
def load_params(path: Path | None = None) -> Dict[str, Any]:
    """Read params.yaml once per process."""
    p = path or (ROOT / ETAPA / "params.yaml")
    with open(p, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


PARAMS: Dict[str, Any] = load_params()


def param(dotted: str, default: Any = ...) -> Any:
    """Fetch a nested parameter: param("tiling.bloque_m").

    Raises on a missing key unless a default is supplied. Failing loudly is
    deliberate: a silently-defaulted threshold is exactly the untraceable
    constant the parameter file exists to prevent.
    """
    node: Any = PARAMS
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            if default is ...:
                raise KeyError(f"params.yaml has no key '{dotted}'")
            return default
        node = node[key]
    return node


# --------------------------------------------------------------------------
# Ontology helpers
# --------------------------------------------------------------------------
CLASSES = {c["id"]: c for c in param("ontology.classes")}
CLASS_NAMES = {cid: c["name"] for cid, c in CLASSES.items()}
CLASS_NAMES_ES = {cid: c.get("name_es", c["name"]) for cid, c in CLASSES.items()}
CLASS_COLORS = {cid: tuple(c["color"]) for cid, c in CLASSES.items()}
IGNORE_ID = int(param("ontology.ignore_id"))
N_CLASSES = len(CLASSES)

# `estado` per class, and the subset the pipeline actually works on.
#
# Why a flag instead of a short class list (docs/decisiones/0017). The scope of
# this phase is the pole, the street light and the medium-voltage network. The
# other eight classes are not deleted: deleting them would force a renumber
# the day one comes back, and renumbering invalidates every annotation already
# registered, because the class id is what is stored in the LAS
# `classification` field. So the ids stay frozen and the stages filter by
# state. Reactivating a class is one word in params.yaml.
#
# ESTADO_ACTIVA is deliberately the only thing the stages import. Asking
# "is this class in scope?" anywhere else would be a second source of truth.
ESTADO_ACTIVA = "activa"
ESTADO_EN_ESPERA = "en_espera"
ESTADO_OBSOLETA = "obsoleta"
_ESTADOS = (ESTADO_ACTIVA, ESTADO_EN_ESPERA, ESTADO_OBSOLETA)

CLASS_ESTADO = {cid: str(c.get("estado", ESTADO_ACTIVA)) for cid, c in CLASSES.items()}
_malos = {cid: e for cid, e in CLASS_ESTADO.items() if e not in _ESTADOS}
if _malos:
    raise ValueError(
        f"ontology.classes: estado desconocido {_malos}. "
        f"Los validos son {', '.join(_ESTADOS)}."
    )

ACTIVE_IDS = tuple(sorted(c for c, e in CLASS_ESTADO.items() if e == ESTADO_ACTIVA))
ACTIVE_NAMES = {cid: CLASS_NAMES[cid] for cid in ACTIVE_IDS}
# Las clases que el modelo tiene que acertar: las activas menos `ignore_id`.
# Es lo que cuenta para la mIoU y para los pesos de clase.
TARGET_IDS = tuple(cid for cid in ACTIVE_IDS if cid != IGNORE_ID)

if IGNORE_ID not in ACTIVE_IDS:
    raise ValueError(
        f"ontology.ignore_id = {IGNORE_ID} tiene que estar activa: es donde "
        "cae todo lo que no es un activo del alcance."
    )
if not TARGET_IDS:
    raise ValueError("ontology: no hay ninguna clase activa aparte de ignore_id")


def es_activa(class_id: int) -> bool:
    return CLASS_ESTADO.get(int(class_id)) == ESTADO_ACTIVA


def long_path(p: Path | str) -> str:
    r"""Windows \\?\ prefix, so deep interim trees do not hit MAX_PATH."""
    s = os.path.abspath(str(p))
    if os.name != "nt" or s.startswith("\\\\?\\"):
        return s
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s
