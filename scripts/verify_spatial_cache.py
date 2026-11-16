"""Compare a saved exact acquisition with reusable containing imagery.

An exact native-grid match is required before broad rollout of enclosing extents.
The report checks every available pair, including masks and prepared arrays.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from shapely.geometry import shape
import nisar_selection_subsidence as source
from acquisition_cache import crop_native


def compare(a, b):
    if a is None or b is None:
        return {"equal": a is None and b is None}
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape:
        return {"equal": False, "shape_a": list(a.shape), "shape_b": list(b.shape)}
    finite = np.isfinite(a) & np.isfinite(b)
    difference = float(np.max(np.abs(a[finite].astype(float)-b[finite].astype(float)))) if finite.any() else 0
    return {"equal": bool(np.array_equal(a, b, equal_nan=True)), "max_abs_difference": difference}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--selection-id", required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--cache-dir", type=Path, default=Path.home()/".cache/groundsignal")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    with sqlite3.connect(ROOT / "backend/data/selections.sqlite3") as db:
        row = db.execute("SELECT record_json FROM selections WHERE selection_id=?", (args.selection_id,)).fetchone()
    if not row:
        raise ValueError("Unknown selection")
    source.SELECTION_GEOMETRY = json.loads(row[0])["geometry"]
    point = shape(source.SELECTION_GEOMETRY).representative_point()
    bbox = source._expanded_aoi_bbox(source.SELECTION_GEOMETRY)
    spec = {"bbox": bbox, "center": (point.x, point.y)}
    fetcher = source.Fetcher(args.cache_dir, source.RunOptions(offline=True))
    results = []
    with args.inventory.open() as stream:
        items = list(csv.DictReader(stream))
    for item in items:
        path = fetcher._legacy_path(item, bbox)
        if not path.exists():
            path = fetcher._path(item, bbox)
        original = fetcher._load_cache(path) if path.exists() else None
        reused = None
        reused_path = None
        for candidate in fetcher._extent_index.candidates(fetcher._identity(item), bbox):
            if candidate in (fetcher._legacy_path(item, bbox), fetcher._path(item, bbox)):
                continue  # Never "validate" a clip by comparing it to itself.
            containing = fetcher._load_cache(candidate)
            reused = crop_native(containing, bbox) if containing is not None else None
            if reused is not None:
                reused_path = str(candidate)
                break
        result = {"product": item["name"], "available": original is not None and reused is not None}
        if result["available"]:
            result["containing_cache"] = reused_path
            result["raw"] = {k: compare(original[k], reused[k]) for k in ("phase", "coh", "cc", "incidence", "tf")}
            a, b = source._prepare_pair(original, spec), source._prepare_pair(reused, spec)
            if "skip" in a or "skip" in b:
                result["prepared_equal"] = a.get("skip") == b.get("skip")
            else:
                result["prepared"] = {k: compare(a[k], b[k]) for k in ("ph", "coh", "incidence", "tf")}
                result["prepared_equal"] = all(v["equal"] for v in result["prepared"].values())
            result["equal"] = all(v["equal"] for v in result["raw"].values()) and result["prepared_equal"]
        results.append(result)
    report = {"pair_count": len(results), "all_equal": bool(results) and all(r.get("equal", False) for r in results), "pairs": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "pairs"}))
    return 0 if report["all_equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
