"""Bounded background imagery refresh, independent of the API worker.

Each invocation refreshes the configured regions once and fetches only missing
products. Run periodically with your deployment's scheduler; it is not started
automatically by each API process. Dates/regions are explicit to bound storage.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/acquisition_regions.json")
    parser.add_argument("--cache-dir", type=Path, default=Path.home()/".cache/groundsignal")
    parser.add_argument("--output", type=Path, default=ROOT / "backend/data/acquisition_experiments/regions")
    parser.add_argument("--workers", type=int, default=25)
    args = parser.parse_args()
    regions = json.loads(args.config.read_text())["regions"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    results = []
    for region in regions:
        name = region["id"]
        if not name.replace("_", "").isalnum():
            raise ValueError("Region IDs may contain only letters, numbers and underscores")
        out = args.output / stamp / name
        out.mkdir(parents=True, exist_ok=True)
        geometry = out / "region.geojson"
        geometry.write_text(json.dumps(region["geometry"]))
        cmd = [sys.executable, str(ROOT / "nisar_selection_subsidence.py"),
               "--geojson", str(geometry), "--label", name, "--output", str(out),
               "--cache-dir", str(args.cache_dir), "--prefetch-only", "--no-plots", "--serial",
               "--workers", str(args.workers), "--extent-step", str(region.get("extent_step", .1)),
               "--start-date", region["start_date"], "--end-date-exclusive", region["end_date_exclusive"]]
        with (out / "process.log").open("w", encoding="utf-8") as log:
            proc = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=log)
        manifest_path = out / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        result = dict(region=name, success=proc.returncode == 0 and bool(manifest) and not manifest.get("cities_failed"),
                      seconds=manifest.get("runtime_seconds"), cache=manifest.get("cache"),
                      cache_total_bytes=sum(p.stat().st_size for p in args.cache_dir.glob("*.npz")))
        results.append(result)
        print(json.dumps(result), flush=True)
    (args.output / stamp / "refresh.json").write_text(json.dumps(results, indent=2))
    return 0 if all(r["success"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
