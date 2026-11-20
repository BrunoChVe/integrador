"""Stage 3.1 — SELECT: inventory, catalogue and profile the raw scans.

Produces the evidence that CRISP-DM stage 2/3 asks for, as pipeline outputs
rather than hand-written prose:

  datos/intermedio/catalogo/raw_inventory.csv
                             one row per raw file with its MD5, the same hash
                             DVC records. Computed from the files themselves,
                             not read from the downloader's manifest: that
                             manifest is machine-local, so a fresh clone would
                             produce a different inventory and the stage would
                             never reproduce.
  datos/intermedio/catalogo/scan_catalog.csv
                             one row per .laz: header, extent, density, CRS.
  reportes/raw_profile.json  aggregate profile + the data-quality findings
                             that the later stages are built to answer.

Run:  python codigo/seleccionar.py   (desde etapa_3_preparacion/)
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.config import PARAMS, PATHS, long_path, param  # noqa: E402
from common.io_cloud import (find_laz, las_header_info, read_las_chunks,  # noqa: E402
                             scan_of)


def md5_of(path: Path, block: int = 8 * 2**20) -> str:
    h = hashlib.md5()
    with open(long_path(path), "rb") as fh:
        while chunk := fh.read(block):
            h.update(chunk)
    return h.hexdigest()


def build_inventory(out_csv: Path) -> dict:
    """Every raw data file with its MD5. Deterministic on any machine."""
    rows, total_bytes = [], 0
    for p in sorted(PATHS.raw.rglob("*")):
        # .dvc pointers and DVC's own .gitignore files are bookkeeping, not data
        if not p.is_file() or p.suffix == ".dvc" or p.name.startswith("."):
            continue
        rel = p.relative_to(PATHS.raw).as_posix()
        size = p.stat().st_size
        total_bytes += size
        rows.append({
            "rel_path": rel,
            "bytes": size,
            "suffix": p.suffix.lower(),
            "scan": rel.split("/")[1] if rel.count("/") >= 1 else "",
            "md5": md5_of(p),
        })

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    by_suffix = Counter(r["suffix"] for r in rows)
    bytes_by_suffix: Counter = Counter()
    for r in rows:
        bytes_by_suffix[r["suffix"]] += r["bytes"]
    return {
        "files": len(rows),
        "bytes": total_bytes,
        "hashed": len(rows),
        "by_suffix": {k: {"files": v, "bytes": bytes_by_suffix[k]}
                      for k, v in by_suffix.most_common()},
    }


def build_catalog(laz_files, out_csv: Path):
    rows = []
    for p in laz_files:
        info = las_header_info(p)
        info["scan"] = scan_of(p)
        info["dimensions"] = "|".join(info["dimensions"])
        info["path"] = str(p.relative_to(PATHS.root).as_posix())
        rows.append(info)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return rows


def profile_attributes(laz_files):
    """Sample real point records to characterise every retained dimension."""
    n_files = int(param("select.perfil.archivos_muestra"))
    chunk = int(param("select.perfil.puntos_por_archivo"))
    n_conteo = int(param("select.perfil.puntos_para_conteos"))
    step = max(1, len(laz_files) // n_files)
    sampled = laz_files[::step][:n_files]
    acc = {k: [] for k in ("intensity", "red", "green", "blue", "ring", "z")}
    classifications: Counter = Counter()
    returns: Counter = Counter()
    n_sampled = 0

    import laspy
    from common.config import long_path
    for p in sampled:
        with laspy.open(long_path(p)) as fh:
            pts = next(fh.chunk_iterator(chunk))
            n = len(pts.x)
            n_sampled += n
            acc["intensity"].append(np.asarray(pts.intensity))
            for c in ("red", "green", "blue"):
                acc[c].append(np.asarray(getattr(pts, c)))
            acc["ring"].append(np.asarray(pts.point_source_id))
            acc["z"].append(np.asarray(pts.z))
            classifications.update(np.asarray(pts.classification).tolist()[:n_conteo])
            returns.update(np.asarray(pts.number_of_returns).tolist()[:n_conteo])

    def stats(name):
        v = np.concatenate(acc[name])
        return {"min": float(v.min()), "max": float(v.max()),
                "mean": float(v.mean()), "std": float(v.std()),
                "p01": float(np.percentile(v, 1)),
                "p50": float(np.percentile(v, 50)),
                "p99": float(np.percentile(v, 99)),
                "distinct": int(min(np.unique(v).size, 10000))}

    rgb = np.concatenate([np.stack([np.concatenate(acc[c]) for c in
                                    ("red", "green", "blue")], axis=1)])
    return {
        "files_sampled": len(sampled),
        "points_sampled": n_sampled,
        "intensity": stats("intensity"),
        "z": stats("z"),
        "ring": stats("ring"),
        "rgb_max": int(rgb.max()),
        "rgb_is_8bit_valued": bool(rgb.max() <= 255),
        "rgb_black_fraction": float((rgb.sum(axis=1) == 0).mean()),
        "classification_counts": {str(k): int(v) for k, v in classifications.most_common()},
        "number_of_returns_counts": {str(k): int(v) for k, v in returns.most_common()},
    }


def quality_findings(catalog, attrs) -> list:
    """Data-quality problems, each phrased as what it forces downstream.

    This is the hand-off from CRISP-DM stage 2 to stage 3. This stage only
    DIAGNOSES: what was done about each finding, and the measured evidence
    that it worked, is the `documentar` stage's job (reportes/informe_limpieza.json).
    Answers used to live here as a `handled_by` field, and went stale the day
    the stages they named were deleted (docs/decisiones/0020) without anything
    failing.
    """
    findings = []
    # Any file without a CRS is a finding, not only "all of them": a delivery
    # that mixes files with and without CRS is the worse case.
    sin_crs = sum(1 for r in catalog if r["crs"] is None)
    if sin_crs:
        findings.append({
            "id": "Q1", "severity": "high", "field": "header.crs",
            "finding": f"{sin_crs} of {len(catalog)} files declare no CRS "
                       "(parse_crs() returns None), while coordinates are UTM "
                       "18S valued.",
            "impact": "Anything exported to GIS/CAD would land unreferenced.",
        })
    if set(attrs["classification_counts"]) <= {"1"}:
        findings.append({
            "id": "Q2", "severity": "blocking", "field": "classification",
            "finding": "Every sampled point carries classification == 1. The "
                       "delivered set is 100% unlabelled.",
            "impact": "Supervised segmentation cannot start; annotation is the "
                      "critical path, not the network architecture.",
        })
    # It used to fire only on 100 % single return, and the measured profile is
    # ~95 %: the finding vanished while params.yaml still called the field
    # "constant 1". Now the share is reported whatever it is.
    ret = attrs["number_of_returns_counts"]
    unico = ret.get("1", 0) / max(1, sum(ret.values()))
    if unico >= float(param("select.umbral_retorno_unico")):
        findings.append({
            "id": "Q3", "severity": "medium", "field": "number_of_returns",
            "finding": f"{unico:.1%} of sampled points are single-return; the "
                       f"rest have 2-3 returns.",
            "impact": "The classic 'last return is ground, first return is "
                      "wire/vegetation' heuristic is unavailable; ground must be "
                      "fitted geometrically.",
            "single_return_fraction": round(unico, 4),
        })
    if attrs["rgb_is_8bit_valued"]:
        findings.append({
            "id": "Q4", "severity": "low", "field": "red/green/blue",
            "finding": "Colour is stored in 16-bit LAS fields but only uses the "
                       "0-255 range.",
            "impact": "Naive 16-bit normalisation would make every tile near-black.",
        })
    densities = [r["density_pts_m2"] for r in catalog]
    findings.append({
        "id": "Q5", "severity": "medium", "field": "density",
        "finding": f"Density varies {min(densities):.0f}-{max(densities):.0f} pts/m2 "
                   "between files (mobile mapping: near the trajectory is dense, "
                   "far is sparse).",
        "impact": "Any fixed-radius feature behaves differently across a tile.",
    })
    return findings


def main() -> int:
    laz = find_laz(PATHS.raw, param("select.scan_groups"), param("select.scans"))
    if not laz:
        print(f"[X] No .laz found under {PATHS.raw}")
        return 1
    print(f"Found {len(laz)} LiDAR files")

    inventory = build_inventory(PATHS.catalogo / "raw_inventory.csv")
    print(f"  inventory : {inventory['files']:,} files, "
          f"{inventory['bytes'] / 2**30:.2f} GB "
          f"({inventory['hashed']:,} hashed, MD5)")

    catalog = build_catalog(laz, PATHS.catalogo / "scan_catalog.csv")
    total_points = sum(r["point_count"] for r in catalog)
    print(f"  catalogue : {total_points:,} points")

    attrs = profile_attributes(laz)
    print(f"  profile   : sampled {attrs['points_sampled']:,} points from "
          f"{attrs['files_sampled']} files")

    by_scan = {}
    for r in catalog:
        s = by_scan.setdefault(r["scan"], {"files": 0, "points": 0,
                                           "min": [1e12] * 3, "max": [-1e12] * 3})
        s["files"] += 1
        s["points"] += r["point_count"]
        for i, ax in enumerate("xyz"):
            s["min"][i] = min(s["min"][i], r[f"min_{ax}"])
            s["max"][i] = max(s["max"][i], r[f"max_{ax}"])
    for s in by_scan.values():
        s["extent_m"] = [round(b - a, 1) for a, b in zip(s["min"], s["max"])]

    findings = quality_findings(catalog, attrs)
    profile = {
        "crs_epsg_declared": param("project.crs_epsg"),
        "totals": {
            "lidar_files": len(catalog),
            "points": total_points,
            "raw_files": inventory["files"],
            "raw_bytes": inventory["bytes"],
            "compressed_gb": round(sum(r["file_size_bytes"] for r in catalog) / 2**30, 3),
            "mean_density_pts_m2": round(float(np.mean([r["density_pts_m2"] for r in catalog])), 1),
        },
        "by_scan": by_scan,
        "attributes": attrs,
        "quality_findings": findings,
        "ram_estimate_gb": {
            "all_points_float64_xyz_rgb": round(total_points * 6 * 8 / 2**30, 2),
            "all_points_float32_xyz_uint8_rgb": round(total_points * 15 / 2**30, 2),
            "note": "Both exceed a comfortable share of 15.6 GB of system RAM; "
                    "the pipeline is tiled for this reason.",
        },
    }
    out = PATHS.reports / "raw_profile.json"
    out.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n  Quality findings ({len(findings)}):")
    for f in findings:
        print(f"    [{f['severity']:>8}] {f['id']} {f['field']}: {f['finding'][:90]}")
    print(f"\n  Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
