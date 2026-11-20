"""Point-cloud I/O.

Two design rules, both forced by the measured data:

1. Nothing reads a whole scan into memory. One scan is up to 177 M points;
   as float64 xyz+rgb that is 8 GB against 15.6 GB of system RAM, before any
   neighbourhood structure exists. Everything here is chunked or per-tile.

2. Las coordenadas son float64 de punta a punta. El easting/northing UTM ronda
   1e5-1e6 metros y float32 tiene ~24 bits de mantisa, lo que da ~6 cm de
   cuantizacion a esas magnitudes: usar float32 destruiria en silencio la
   precision centimetrica de la que va todo el proyecto.

Hubo un formato intermedio propio —.npz comprimido con las coordenadas como
offset del origen del bloque— para pasar puntos de una etapa a otra. Se fue con
las etapas que lo usaban (docs/decisiones/0017): ahora la unica salida es .laz,
que es lo que abre CloudCompare, y no hace falta un segundo formato.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import laspy
import numpy as np

from .config import long_path

# Fields carried through the pipeline. `label` and derived features are added
# later by their own stages; this is the raw payload.
RAW_FIELDS: Dict[str, np.dtype] = {
    "x": np.dtype("f8"),
    "y": np.dtype("f8"),
    "z": np.dtype("f8"),
    "intensity": np.dtype("u2"),
    "red": np.dtype("u1"),
    "green": np.dtype("u1"),
    "blue": np.dtype("u1"),
    "ring": np.dtype("u1"),        # point_source_id: VLP-16 laser index 0-15
    "gps_time": np.dtype("f8"),
}


@dataclass
class Cloud:
    """A tile or chunk of points held in memory."""

    xyz: np.ndarray                       # (N, 3) float64, absolute metres
    attrs: Dict[str, np.ndarray] = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.xyz.shape[0])

    @property
    def n(self) -> int:
        return len(self)

    def subset(self, mask: np.ndarray) -> "Cloud":
        return Cloud(self.xyz[mask], {k: v[mask] for k, v in self.attrs.items()})

    def bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        return self.xyz.min(axis=0), self.xyz.max(axis=0)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def las_header_info(path: Path) -> Dict[str, object]:
    """Header-only read. Cheap: does not touch the point records."""
    with laspy.open(long_path(path)) as fh:
        h = fh.header
        mins, maxs = np.asarray(h.mins, float), np.asarray(h.maxs, float)
        extent = maxs - mins
        area = float(extent[0] * extent[1])
        return {
            "path": str(path),
            "name": path.name,
            "point_count": int(h.point_count),
            "las_version": str(h.version),
            "point_format": int(h.point_format.id),
            "scales": [float(s) for s in h.scales],
            "offsets": [float(o) for o in h.offsets],
            "min_x": float(mins[0]), "min_y": float(mins[1]), "min_z": float(mins[2]),
            "max_x": float(maxs[0]), "max_y": float(maxs[1]), "max_z": float(maxs[2]),
            "extent_x_m": float(extent[0]),
            "extent_y_m": float(extent[1]),
            "extent_z_m": float(extent[2]),
            "footprint_m2": area,
            "density_pts_m2": float(h.point_count / area) if area > 0 else 0.0,
            "crs": _crs_del_header(h),
            "dimensions": [d.name for d in h.point_format.dimensions],
            "file_size_bytes": path.stat().st_size,
        }


def _crs_del_header(h) -> Optional[str]:
    """El CRS declarado en la cabecera, o None si no hay o no se puede leer.

    No es una guarda de adorno. Los escaneos de ate no declaran CRS y
    `parse_crs()` devuelve None sin tocar nada; los de Pachacamac SI lo
    declaran, y entonces laspy importa pyproj para interpretarlo. Sin pyproj
    instalado eso es un ModuleNotFoundError que tumba el catalogo entero a
    mitad de 32 GB, y por un dato informativo: el CRS que leemos aqui solo se
    reporta, nunca se usa para transformar nada. Que falte una dependencia
    opcional no puede costar la etapa.
    """
    try:
        crs = h.parse_crs()
    except Exception:
        return None
    return str(crs) if crs is not None else None


def _extract(points, name: str, dtype: np.dtype, n: int) -> np.ndarray:
    """Pull one dimension, tolerating formats that lack it."""
    try:
        arr = np.asarray(points[name])
    except Exception:
        return np.zeros(n, dtype=dtype)
    if dtype.kind == "u" and arr.dtype.kind in "iu":
        # RGB arrives in 16-bit fields; this data is 8-bit valued (max 255).
        # Scale only if the file genuinely uses the 16-bit range.
        if dtype.itemsize == 1 and arr.size and arr.max() > 255:
            arr = arr >> 8
    return arr.astype(dtype, copy=False)


def read_las_chunks(path: Path, chunk_size: int = 4_000_000) -> Iterator[Cloud]:
    """Stream a .las/.laz file in chunks of `chunk_size` points."""
    with laspy.open(long_path(path)) as fh:
        for pts in fh.chunk_iterator(chunk_size):
            n = len(pts.x)
            xyz = np.empty((n, 3), dtype="f8")
            xyz[:, 0] = np.asarray(pts.x, dtype="f8")
            xyz[:, 1] = np.asarray(pts.y, dtype="f8")
            xyz[:, 2] = np.asarray(pts.z, dtype="f8")
            attrs = {
                "intensity": _extract(pts, "intensity", RAW_FIELDS["intensity"], n),
                "red": _extract(pts, "red", RAW_FIELDS["red"], n),
                "green": _extract(pts, "green", RAW_FIELDS["green"], n),
                "blue": _extract(pts, "blue", RAW_FIELDS["blue"], n),
                "ring": _extract(pts, "point_source_id", RAW_FIELDS["ring"], n),
                "gps_time": _extract(pts, "gps_time", RAW_FIELDS["gps_time"], n),
            }
            yield Cloud(xyz, attrs)


# ---------------------------------------------------------------------------
# Writing LAS/LAZ — for CloudCompare annotation and for CAD hand-off
# ---------------------------------------------------------------------------

def write_las(path: Path, cloud: Cloud, epsg: Optional[int] = None,
              labels: Optional[np.ndarray] = None,
              extra: Optional[Dict[str, np.ndarray]] = None) -> None:
    """Write a cloud as .laz, stamping the CRS the source files were missing.

    Every delivered file reports `parse_crs() -> None`. Anything exported for
    a GIS or CAD user must carry the CRS or it lands in the wrong place on
    the map, so this is written on every export.

    `extra` adds LAS "extra bytes" dimensions; CloudCompare shows each one as
    a scalar field.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    header = laspy.LasHeader(version="1.4", point_format=7)   # 7 = xyz+rgb+time
    for name, values in (extra or {}).items():
        header.add_extra_dim(laspy.ExtraBytesParams(name=name, type=values.dtype))
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.floor(cloud.xyz.min(axis=0))
    if epsg:
        try:
            header.add_crs(_crs_from_epsg(epsg))
        except Exception:
            pass  # pyproj missing: geometry is still correct, tag is not
    las = laspy.LasData(header)
    las.x, las.y, las.z = cloud.xyz[:, 0], cloud.xyz[:, 1], cloud.xyz[:, 2]
    if "intensity" in cloud.attrs:
        las.intensity = cloud.attrs["intensity"].astype("u2")
    for c in ("red", "green", "blue"):
        if c in cloud.attrs:
            # LAS colour channels are 16-bit; the source is 8-bit valued.
            setattr(las, c, (cloud.attrs[c].astype("u2") << 8))
    if "gps_time" in cloud.attrs:
        las.gps_time = cloud.attrs["gps_time"]
    # El indice de laser del VLP-16 (0-15), que llega en `point_source_id`.
    # Se perdia: la etapa de bloques lo leia, lo arrastraba hasta aqui y esta
    # funcion no lo escribia, asi que los bloques salian con todo a 0 mientras
    # `select.keep_dimensions` lo declaraba conservado. El codigo contradecia al
    # parametro y nada avisaba. Vale poco por si solo —es un proxy debil del
    # angulo vertical del rayo, y por tanto de la altura respecto al sensor—
    # pero perderlo en silencio es justo lo que este proyecto dice evitar.
    if "ring" in cloud.attrs:
        las.point_source_id = cloud.attrs["ring"].astype("u2")
    if labels is not None:
        las.classification = labels.astype("u1")
    elif "label" in cloud.attrs:
        las.classification = cloud.attrs["label"].astype("u1")
    for name, values in (extra or {}).items():
        las[name] = values
    las.write(long_path(path))


def _crs_from_epsg(epsg: int):
    from pyproj import CRS
    return CRS.from_epsg(epsg)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def scan_folders(raw_root: Path, scan_groups: Sequence[str]) -> Dict[str, Path]:
    """Every scan folder under the declared groups, as {scan name: folder}.

    A scan folder is one that contains `LiDAR/GeoRef`. It is located by
    searching rather than by a fixed path because the delivery nests scans
    under a district when the group covers more than one:

        datos/crudo/Grupo03_crudo_2025/ate/AVP01MT2611202501/LiDAR/GeoRef
        datos/crudo/Grupo01_crudo_2025/Pachacamac/PACHAP01MT0108202501/LiDAR/GeoRef

    The first delivery had no district level and the path was hard-coded to
    `<group>/<scan>/LiDAR/GeoRef`. When the district appeared, every stage
    silently found zero files: the glob below accepts both depths, so a new
    delivery layout costs nothing. Scan names are unique across groups in
    every delivery so far; if two ever collide, the second one found wins and
    `scan_of` would be ambiguous too, so this asserts rather than guesses.
    """
    out: Dict[str, Path] = {}
    for group in scan_groups:
        root = raw_root / group
        if not root.is_dir():
            continue
        for georef in sorted(root.glob("**/LiDAR/GeoRef")):
            folder = georef.parent.parent
            if folder.name in out and out[folder.name] != folder:
                raise RuntimeError(
                    f"two different folders are both called '{folder.name}': "
                    f"{out[folder.name]} and {folder}. Scan names must be "
                    "unique, because that is the key every stage and every "
                    "annotation path is built on."
                )
            out[folder.name] = folder
    return out


def district_of(path: Path, raw_root: Path) -> str:
    """`ate` from `datos/crudo/Grupo03_crudo_2025/ate/AVP.../LiDAR/GeoRef/x.laz`.

    Empty string when the group has no district level.
    """
    try:
        rel = Path(path).resolve().relative_to(Path(raw_root).resolve()).parts
    except ValueError:
        return ""
    # (group, [district], scan, LiDAR, GeoRef, file)
    return rel[1] if len(rel) >= 6 else ""


def find_laz(raw_root: Path, scan_groups: Sequence[str],
             scans: Sequence[str]) -> List[Path]:
    """Locate the LiDAR files declared in params.yaml, deterministically.

    `scans` is the explicit allow-list from `select.scans`; empty means every
    scan found under the declared groups.
    """
    folders = scan_folders(raw_root, scan_groups)
    wanted = list(scans) if scans else sorted(folders)
    out: List[Path] = []
    for scan in wanted:
        folder = folders.get(scan)
        if folder is None:
            continue
        georef = folder / "LiDAR" / "GeoRef"
        out.extend(sorted(georef.glob("*.laz")))
        out.extend(sorted(georef.glob("*.las")))
    return sorted(out)


def scan_of(path: Path) -> str:
    """AVP01MT2611202501 from .../AVP01MT2611202501/LiDAR/GeoRef/x.laz"""
    parts = path.parts
    for i, p in enumerate(parts):
        if p == "LiDAR" and i >= 1:
            return parts[i - 1]
    return path.parent.name


def ruta_de_escaneo(path: Path, raw_root: Path) -> Path:
    """La ruta del escaneo relativa a `datos/crudo`, sin `LiDAR/GeoRef`.

        datos/crudo/Grupo01_crudo_2025/Pachacamac/PACHAP01MT0108202501/LiDAR/GeoRef/x.laz
        -> Grupo01_crudo_2025/Pachacamac/PACHAP01MT0108202501

    UNA SOLA REGLA PARA TODAS LAS CARPETAS. Es lo que hace que los bloques y la
    verdad de campo se organicen igual que el crudo:

        datos/crudo/<grupo>/<distrito>/<escaneo>/LiDAR/GeoRef/*.laz
        datos/intermedio/01_bloques/<grupo>/<distrito>/<escaneo>/b_*.laz
        annotation_revisada/<grupo>/<distrito>/<escaneo>/b_*.laz

    Antes los bloques se guardaban en una carpeta plana por escaneo. El nombre
    del escaneo basta como clave —`scan_folders` revienta si dos coinciden— pero
    eso resuelve la IDENTIDAD, no la NAVEGACION: con 16 escaneos y mas distritos
    por llegar, una lista plana no dice de que distrito es cada uno, y quien
    elige el siguiente bloque que anotar lo mira todos los dias.

    Devuelve una ruta relativa, nunca absoluta, para que el llamante la pegue
    bajo la raiz que le toque.
    """
    p = Path(path).resolve()
    partes = p.relative_to(Path(raw_root).resolve()).parts
    # (grupo, [distrito], escaneo, LiDAR, GeoRef, archivo) -> recortar en LiDAR
    if "LiDAR" in partes:
        partes = partes[:partes.index("LiDAR")]
    return Path(*partes)
