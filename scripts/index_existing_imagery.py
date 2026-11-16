"""Register validated legacy raw clips using saved selection/inventory provenance.

Does not infer a granule identity from raster values, alter arrays, or contact NASA.
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
import nisar_selection_subsidence as source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path.home()/".cache/groundsignal")
    args = parser.parse_args()
    fetcher = source.Fetcher(args.cache_dir, source.RunOptions(offline=True))
    with sqlite3.connect(ROOT / "backend/data/selections.sqlite3") as db:
        records = [json.loads(row[0]) for row in db.execute("SELECT record_json FROM selections")]
    seen = set()
    registered = 0
    for record in records:
        bbox = source._expanded_aoi_bbox(record["geometry"])
        folder = ROOT / "backend/data/processing" / record["selection_id"]
        for inventory in folder.glob("*/source_screening/asf_inventory.csv"):
            with inventory.open() as stream:
                for item in csv.DictReader(stream):
                    key = (item["name"], item["pol"], tuple(bbox))
                    if key in seen:
                        continue
                    seen.add(key)
                    if fetcher._valid_exact(item, bbox) is not None:
                        registered += 1
    print(json.dumps({"validated_extents_registered": registered}))


if __name__ == "__main__":
    main()
