"""Sequential, isolated-cache cold acquisition trials plus their warm repeats.

Run from the repository root. Uses real NASA services and the full selected
product inventory. No dates, quality masks or products are dropped for speed.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--selection-id", required=True)
    p.add_argument("--workers", type=int, nargs="+", default=[4, 8, 16, 25])
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--output", type=Path, default=ROOT / "backend/data/acquisition_experiments")
    p.add_argument("--timeout", type=int, default=2400, help="maximum seconds per trial")
    args = p.parse_args()
    if args.repeats < 1 or min(args.workers) < 1:
        p.error("repeats and workers must be positive")
    run = args.output / ("benchmark_" + uuid.uuid4().hex[:8])
    run.mkdir(parents=True)
    results = []
    for repeat in range(args.repeats):
        # Reverse alternating rounds to reduce fixed-order service-load bias.
        for workers in (args.workers if repeat % 2 == 0 else args.workers[::-1]):
            cache = run / f"cache_r{repeat}_w{workers}"
            for temperature in ("cold", "warm"):
                out = run / f"r{repeat}_w{workers}_{temperature}"
                out.mkdir()
                cmd = [sys.executable, str(ROOT / "nisar_selection_subsidence.py"),
                       "--selection-id", args.selection_id, "--cache-dir", str(cache),
                       "--output", str(out), "--prefetch-only", "--no-plots", "--serial",
                       "--workers", str(workers), "--extent-step", "0"]
                started = time.perf_counter()
                try:
                    with (out / "process.log").open("w", encoding="utf-8") as log:
                        proc = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=log, timeout=args.timeout)
                    code = proc.returncode
                except subprocess.TimeoutExpired:
                    code = "timeout"
                manifest_path = out / "run_manifest.json"
                manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
                events_path = out / "acquisition_events.jsonl"
                events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
                result = dict(workers=workers, repeat=repeat, cache=temperature,
                              wall_seconds=time.perf_counter()-started, exit_code=code,
                              success=code == 0 and bool(manifest) and not manifest.get("cities_failed"),
                              stages=manifest.get("stage_seconds"),
                              remote_jobs=sum(e["stage"] == "submit" for e in events),
                              resumed_jobs=sum(e["stage"] == "resume_remote_job" for e in events),
                              download_bytes=sum(e.get("bytes", 0) for e in events if e["stage"] == "download"))
                results.append(result)
                (run / "results.json").write_text(json.dumps(results, indent=2))
                print(json.dumps(result), flush=True)
    summary = []
    for workers in args.workers:
        for temperature in ("cold", "warm"):
            group = [r["wall_seconds"] for r in results if r["workers"] == workers and r["cache"] == temperature and r["success"]]
            if group:
                summary.append(dict(workers=workers, cache=temperature, successful_runs=len(group),
                                    median_seconds=statistics.median(group), worst_seconds=max(group)))
    (run / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"Report: {run}")


if __name__ == "__main__":
    main()
