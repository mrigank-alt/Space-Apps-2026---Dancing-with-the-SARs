from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import load_config
from .pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Build georeferenced hazard layers from a prepared GUNW pair stack")
    parser.add_argument("--config", required=True, help="YAML pipeline configuration")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    manifest = run_pipeline(load_config(args.config))
    csv_path = Path(manifest["run_dir"]) / manifest["heatmap_csv"]
    speed = manifest["speed"]
    print(f"CSV saved: {csv_path}")
    print(f"Total: {speed['elapsed_total_seconds']:.2f}s; source: "
          f"{(speed['source_search_download_and_stack_export_seconds'] or 0):.2f}s; "
          f"SBAS: {speed['sbas_solver_seconds']:.3f}s")


if __name__ == "__main__":
    main()
