"""Export any saved app polygon selection as a vertex CSV."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-id", help="Saved selection ID; defaults to the newest selection")
    parser.add_argument("--output", type=Path, help="CSV path; defaults to <label>_coordinates.csv")
    args = parser.parse_args()

    database = Path(__file__).resolve().parent / "backend" / "data" / "selections.sqlite3"
    with sqlite3.connect(database) as connection:
        if args.selection_id:
            row = connection.execute(
                "SELECT record_json FROM selections WHERE selection_id = ?",
                (args.selection_id,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT record_json FROM selections ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
    if row is None:
        raise SystemExit("No matching saved selection found. Draw and confirm a polygon in the app first.")

    record = json.loads(row[0])
    geometry = record["geometry"]
    if geometry["type"] == "Polygon":
        polygons = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        polygons = geometry["coordinates"]
    else:
        raise SystemExit(f"Unsupported saved geometry: {geometry['type']}")

    safe_label = "_".join(record["label"].strip().lower().split()) or "selection"
    output = args.output or Path(__file__).resolve().parent / f"{safe_label}_coordinates.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["selection_id", "label", "polygon_index", "ring_index", "vertex_index", "longitude", "latitude", "crs"]
        )
        for polygon_index, polygon in enumerate(polygons, start=1):
            for ring_index, ring in enumerate(polygon, start=1):
                for vertex_index, coordinates in enumerate(ring, start=1):
                    writer.writerow(
                        [
                            record["selection_id"], record["label"], polygon_index,
                            ring_index, vertex_index, coordinates[0], coordinates[1],
                            record.get("crs", "EPSG:4326"),
                        ]
                    )
    print(f"Exported {record['label']} ({record['selection_id']}) to {output.resolve()}")


if __name__ == "__main__":
    main()
