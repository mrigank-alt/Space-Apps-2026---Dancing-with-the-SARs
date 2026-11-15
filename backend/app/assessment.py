from __future__ import annotations

import csv
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any
from uuid import uuid4

import numpy as np
import rasterio
from rasterio.transform import Affine
from pyproj import Transformer
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import transform as transform_geometry

from .groundwater import PublicGroundwaterService
from .critical_threshold import CriticalThresholdInputs, CriticalThresholdModel
from .models import (
    Assessment,
    GroundwaterEvidence,
    ProcessingRun,
    Recommendation,
    SpatialSelection,
)


LEVEL_RANK = {"grey": 0, "green": 1, "yellow": 2, "red": 3}


def _number(value: str | None) -> float | None:
    try:
        result = float(value or "nan")
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _persistence(row: dict[str, str]) -> float | None:
    values = [
        _number(value)
        for key, value in row.items()
        if key.startswith("cumulative_los_cm_") and not key.endswith("_1sigma")
    ]
    series = [value for value in values if value is not None]
    if len(series) < 3:
        return None
    increments = [b - a for a, b in zip(series, series[1:])]
    nonzero = [value for value in increments if abs(value) > 1e-8]
    if not nonzero:
        return 0.0
    expected = 1 if series[-1] - series[0] >= 0 else -1
    return sum((1 if value >= 0 else -1) == expected for value in nonzero) / len(nonzero)


class AssessmentService:
    """Converts measured pixels into an explicit, conservative concern assessment."""

    def __init__(self, groundwater: PublicGroundwaterService | None = None) -> None:
        self._groundwater = groundwater or PublicGroundwaterService()

    def create(
        self,
        selection: SpatialSelection,
        processing_run: ProcessingRun,
        manifest: dict[str, Any],
    ) -> Assessment:
        run_dir = Path(str(manifest["run_dir"]))
        csv_path = run_dir / str(manifest.get("heatmap_csv", "heatmap_pixels.csv"))
        with csv_path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            raise ValueError("The satellite run produced no pixels inside the saved farm.")

        interval = manifest.get("measurement_interval") or {}
        groundwater = self._groundwater.check(selection, interval.get("start"), interval.get("end"))
        features, plot_summaries = self._classify(selection, rows, manifest)
        raster_path = self._write_classification_raster(run_dir, features, manifest)
        levels = [feature["properties"]["concern_level"] for feature in features]
        overall = max(levels, key=lambda level: LEVEL_RANK[level]) if levels else "grey"
        uncertainty = bool((manifest.get("pair_network") or {}).get("uncertainty_interpretable"))
        elapsed = float((manifest.get("measurement_interval") or {}).get("elapsed_days") or 0)
        evidence_quality = "strong" if uncertainty and elapsed >= 365 else "moderate" if elapsed >= 180 else "limited"
        assessment_type = "groundwater_related" if groundwater.relationship_eligible else "movement_only"
        limitations = [
            "Satellite values are relative line-of-sight movement, not a direct measurement of groundwater level or pumping.",
            "Concern classes compare pixels within this farm and are exploratory, not validated hazard thresholds.",
        ]
        if not uncertainty:
            limitations.append("Formal measurement uncertainty is unavailable for this image-pair network; red concern is therefore withheld.")
        if elapsed < 365:
            limitations.append("The observation period is shorter than one year, so seasonal and long-term behavior cannot be separated.")
        limitations.extend(groundwater.limitations)

        summary = {
            "red": "A high-priority movement pattern was detected and should be reviewed promptly.",
            "yellow": "Some parts of the farm show more persistent movement than the farm baseline and should be reviewed.",
            "green": "No elevated relative movement concern was identified in the reliable satellite pixels.",
            "grey": "The available satellite pixels are not reliable enough to classify.",
        }[overall]
        recommendations = self._recommendations(overall, groundwater)
        return Assessment(
            assessment_id=f"asmt_{uuid4().hex}",
            selection_id=selection.selection_id,
            processing_run_id=processing_run.run_id,
            assessment_type=assessment_type,
            created_at=datetime.now(UTC),
            observation_start=interval.get("start"),
            observation_end=interval.get("end"),
            summary=summary,
            overall_concern=overall,
            evidence_quality=evidence_quality,
            concern_zones={"type": "FeatureCollection", "features": features},
            plot_summaries=plot_summaries,
            recommendations=recommendations,
            groundwater=groundwater,
            forecast=CriticalThresholdModel().evaluate(CriticalThresholdInputs(
                cell_id="farm_summary",
                observation_count=int((manifest.get("pair_network") or {}).get("epoch_count") or 0),
            )),
            limitations=list(dict.fromkeys(limitations)),
            provenance={
                "satellite_run_id": manifest.get("run_id"),
                "source": "NASA ASF GUNW processed by the Groundsignal SBAS pipeline",
                "grid_crs": manifest.get("crs"),
                "grid_transform": manifest.get("grid_transform"),
                "pair_count": (manifest.get("pair_network") or {}).get("pair_count"),
                "epoch_count": (manifest.get("pair_network") or {}).get("epoch_count"),
                "classifier_version": "relative-concern-v1",
                "classification_raster": raster_path,
                "class_values": {"grey": 0, "green": 1, "yellow": 2, "red": 3},
            },
        )

    @staticmethod
    def _write_classification_raster(
        run_dir: Path, features: list[dict[str, Any]], manifest: dict[str, Any]
    ) -> str:
        transform_values = manifest.get("grid_transform")
        if not isinstance(transform_values, list) or len(transform_values) != 6:
            raise ValueError("The satellite manifest is missing its grid transform.")
        shape_value = manifest.get("grid_shape")
        if isinstance(shape_value, list) and len(shape_value) == 2:
            height, width = int(shape_value[0]), int(shape_value[1])
        else:
            rows = [int(feature["properties"]["source_row"]) for feature in features]
            columns = [int(feature["properties"]["source_column"]) for feature in features]
            height, width = max(rows, default=0) + 1, max(columns, default=0) + 1
        data = np.full((height, width), 255, dtype=np.uint8)
        class_values = {"grey": 0, "green": 1, "yellow": 2, "red": 3}
        for feature in features:
            properties = feature["properties"]
            data[int(properties["source_row"]), int(properties["source_column"])] = class_values[properties["concern_level"]]
        output = run_dir / "concern_classification.tif"
        with rasterio.open(
            output,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=1,
            dtype="uint8",
            crs=manifest.get("crs"),
            transform=Affine(*[float(value) for value in transform_values]),
            nodata=255,
            compress="deflate",
        ) as dataset:
            dataset.write(data, 1)
            dataset.update_tags(
                classification="0=grey,1=green,2=yellow,3=red,255=outside_or_unmeasured",
                methodology="exploratory_relative_concern",
            )
        return str(output)

    def _classify(
        self,
        selection: SpatialSelection,
        rows: list[dict[str, str]],
        manifest: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        velocities = [abs(value) for row in rows if (value := _number(row.get("los_velocity_cm_year"))) is not None]
        center = median(velocities) if velocities else 0.0
        deviations = [abs(value - center) for value in velocities]
        mad = median(deviations) if deviations else 0.0
        robust_scale = max(1.4826 * mad, 0.05)
        transform = manifest.get("grid_transform")
        crs = manifest.get("crs")
        if not isinstance(transform, list) or len(transform) != 6 or not crs:
            raise ValueError("The satellite manifest is missing its grid georeferencing.")
        to_lonlat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        farm_shape = shape(selection.geometry)
        plot_shapes = [(plot.plot_id, plot.plot_index, shape(plot.geometry)) for plot in selection.plots]
        uncertainty_interpretable = bool((manifest.get("pair_network") or {}).get("uncertainty_interpretable"))
        a, b, c, d, e, f = [float(value) for value in transform]
        features: list[dict[str, Any]] = []
        counts = {plot_id: {"green": 0, "yellow": 0, "red": 0, "grey": 0} for plot_id, _, _ in plot_shapes}

        for index, row in enumerate(rows):
            r, col = int(row["row"]), int(row["column"])
            corners = [
                (c + col*a + r*b, f + col*d + r*e),
                (c + (col+1)*a + r*b, f + (col+1)*d + r*e),
                (c + (col+1)*a + (r+1)*b, f + (col+1)*d + (r+1)*e),
                (c + col*a + (r+1)*b, f + col*d + (r+1)*e),
            ]
            cell = transform_geometry(to_lonlat.transform, Polygon(corners)).intersection(farm_shape)
            if cell.is_empty:
                continue
            velocity = _number(row.get("los_velocity_cm_year"))
            change = _number(row.get("los_displacement_change_cm"))
            sigma = _number(row.get("los_velocity_sigma_cm_year_1sigma"))
            persistence = _persistence(row)
            reliable = row.get("quality_mask") == "1" and velocity is not None
            z = ((abs(velocity) - center) / robust_scale) if velocity is not None else None
            significant = uncertainty_interpretable and sigma is not None and abs(velocity or 0) >= 2 * sigma
            if not reliable:
                level = "grey"
                explanation = "This pixel did not meet the pipeline reliability checks, so no concern class is assigned."
            elif significant and (z or 0) >= 2.0 and (persistence or 0) >= 0.75:
                level = "red"
                explanation = "Movement is statistically distinguishable, spatially elevated, and persistent across the observed dates."
            elif (z or 0) >= 1.5 and (persistence or 0) >= 0.60:
                level = "yellow"
                explanation = "Movement is persistently higher than the reliable farm baseline; formal high-concern criteria are not met."
            else:
                level = "green"
                explanation = "This reliable pixel is not elevated relative to the farm movement baseline."
            centroid = cell.representative_point()
            matched = next(((pid, pindex) for pid, pindex, polygon in plot_shapes if polygon.covers(centroid)), None)
            plot_id, plot_index = matched or (selection.plots[0].plot_id, selection.plots[0].plot_index)
            counts[plot_id][level] += 1
            features.append({
                "type": "Feature",
                "id": f"zone_{index+1:05d}",
                "geometry": mapping(cell),
                "properties": {
                    "zone_id": f"zone_{index+1:05d}",
                    "plot_id": plot_id,
                    "plot_index": plot_index,
                    "concern_level": level,
                    "label": {"green": "Lower concern", "yellow": "Review", "red": "Prompt review", "grey": "Insufficient data"}[level],
                    "explanation": explanation,
                    "los_velocity_cm_year": velocity,
                    "observed_los_change_cm": change,
                    "persistence_fraction": persistence,
                    "coherence": _number(row.get("coherence_mean")),
                    "uncertainty_available": uncertainty_interpretable and sigma is not None,
                    "measurement_start": row.get("measurement_start"),
                    "measurement_end": row.get("measurement_end"),
                    "source_row": r,
                    "source_column": col,
                },
            })
        summaries = []
        for plot_id, plot_index, _ in plot_shapes:
            plot_counts = counts[plot_id]
            nonzero = [level for level, count in plot_counts.items() if count]
            level = max(nonzero, key=lambda item: LEVEL_RANK[item]) if nonzero else "grey"
            summaries.append({"plot_id": plot_id, "plot_index": plot_index, "overall_concern": level, "pixel_counts": plot_counts})
        return features, summaries

    @staticmethod
    def _recommendations(level: str, groundwater: GroundwaterEvidence) -> list[Recommendation]:
        result = [Recommendation(
            priority="prompt_review" if level == "red" else "review" if level == "yellow" else "routine",
            title="Review the highlighted areas" if level in {"yellow", "red"} else "Keep monitoring the saved plots",
            detail="Compare the map with field conditions, irrigation records, and known drainage or construction changes. Do not change pumping based on this map alone.",
        )]
        if not groundwater.relationship_eligible:
            result.append(Recommendation(
                priority="review",
                title="Add local groundwater evidence",
                detail="A dated nearby well-level record is needed before the observed movement can be evaluated as groundwater-related.",
            ))
        result.append(Recommendation(
            priority="routine",
            title="Refresh when new satellite dates are available",
            detail="A longer observation history can help separate persistent movement from seasonal or short-lived changes.",
        ))
        return result
