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
from pyproj import Transformer, Geod
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import transform as transform_geometry

from .groundwater import PublicGroundwaterService
from .climate import ClimateService
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
    dated = []
    for key, value in row.items():
        if not key.startswith("cumulative_los_cm_") or key.endswith("_1sigma"):
            continue
        try:
            epoch = datetime.strptime(key.removeprefix("cumulative_los_cm_"), "%Y-%m-%d")
        except ValueError:
            continue
        number = _number(value)
        if number is not None:
            dated.append((epoch, number))
    dated.sort()
    if len(dated) < 6:
        return None
    cadence = median((dated[i][0] - dated[i-1][0]).days for i in range(1, len(dated)))
    adjacent = [(dated[i][1] - dated[i-1][1], (dated[i][0] - dated[i-1][0]).days)
                for i in range(1, len(dated))
                if (dated[i][0] - dated[i-1][0]).days <= max(1.75 * cadence, cadence + 1)]
    if len(adjacent) < 5:
        return None
    increments = [value for value, _days in adjacent]
    series = [value for _, value in dated]
    net = sum(increments)
    total = sum(abs(value) for value in increments)
    if abs(net) <= 0.02 or total <= 0.02:
        return 0.0
    # Path efficiency: 1 is a straight monotonic trend; values near 0 are a noisy walk.
    return abs(net) / total


def _area_summary(features, geometry):
    geod = Geod(ellps="WGS84")
    total = abs(geod.geometry_area_perimeter(shape(geometry))[0])
    areas = {level: 0.0 for level in LEVEL_RANK}
    for feature in features:
        areas[feature["properties"]["concern_level"]] += abs(geod.geometry_area_perimeter(shape(feature["geometry"]))[0])
    # Include unmeasured boundary area in the denominator and in grey.
    areas["grey"] += max(0.0, total - sum(areas.values()))
    shares = {level: value / max(total, 1e-12) for level, value in areas.items()}
    dominant = max(shares, key=lambda level: (shares[level], LEVEL_RANK[level]))
    usable = sum(f["properties"]["concern_level"] != "grey" for f in features)
    if usable < 3 or shares["grey"] >= 0.5:
        dominant = "grey"
    return {"dominant_class": dominant, "area_square_meters": areas, "area_fractions": shares,
            "total_area_square_meters": total, "summary_method": "dominant_geodesic_area_including_unmeasured"}


class AssessmentService:
    """Converts measured pixels into an explicit, conservative concern assessment."""

    def __init__(self, groundwater: PublicGroundwaterService | None = None, climate: ClimateService | None = None) -> None:
        self._groundwater = groundwater or PublicGroundwaterService()
        self._climate = climate or ClimateService()

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
        usable = sum(level != "grey" for level in levels)
        reliable_count = usable
        reliable_fraction = usable / max(len(levels), 1)
        area_summary = _area_summary(features, selection.geometry)
        overall = area_summary["dominant_class"]
        red_pixels = {(int(f["properties"]["source_row"]), int(f["properties"]["source_column"]))
                      for f in features if f["properties"]["concern_level"] == "red"}
        red_cluster = self._largest_cluster(red_pixels)
        climate = self._climate.check(selection, interval.get("start"), interval.get("end"))
        uncertainty = bool((manifest.get("pair_network") or {}).get("uncertainty_interpretable"))
        elapsed = float((manifest.get("measurement_interval") or {}).get("elapsed_days") or 0)
        evidence_quality = "limited"
        assessment_type = "groundwater_related" if groundwater.relationship_eligible else "movement_only"
        limitations = [
            "Satellite values are relative line-of-sight movement, not a direct measurement of groundwater level or pumping.",
            "Concern classes screen measured LOS change and within-farm differences using exploratory thresholds; yellow includes uncertain movement needing review.",
        ]
        signal_quality = manifest.get("signal_quality_diagnostics") or {}
        reference_quality = signal_quality.get("reference") or {}
        closure_quality = signal_quality.get("temporal_closure") or {}
        if reference_quality.get("status") == "measured_stability_not_independently_verified":
            limitations.append("Reference-area residual spread was measured, but the reference area's physical stability has not been independently verified.")
        elif reference_quality.get("status") in {"insufficient_reference_support", "not_recorded", "invalid_diagnostics"}:
            limitations.append("Reference-area stability diagnostics are unavailable or have insufficient support.")
        if closure_quality.get("status") == "insufficient_network_cycles":
            limitations.append("The acquisition network has no complete temporal triangles, so closure-based consistency could not be checked.")
        elif closure_quality:
            limitations.append("Temporal triangle-closure residuals are recorded for review, but no validated threshold currently turns them into a pass/fail quality gate.")
        if not uncertainty:
            limitations.append("Formal measurement uncertainty is unavailable for this image-pair network; red concern is therefore withheld.")
        limitations.append("The uncertainty estimates have not been calibrated against independent ground measurements; concern labels remain exploratory.")
        if elapsed < 365:
            limitations.append("The observation period is shorter than one year, so seasonal and long-term behavior cannot be separated.")
        if reliable_fraction < 0.5:
            limitations.append("Fewer than half of mapped cells passed reliability checks; the farm-level result is insufficient data.")
        transform_values = manifest.get("grid_transform") or [0, 0, 0, 0, 0, 0]
        pixel_width_m, pixel_height_m = abs(float(transform_values[0])), abs(float(transform_values[4]))
        if reliable_count < 3:
            limitations.append(f"Only {reliable_count} reliable source pixels are available; spatial support is limited (grid spacing about {pixel_width_m:.0f} × {pixel_height_m:.0f} CRS units).")
        farm_movement = [value for row in rows if row.get("quality_mask", "").strip().lower() in {"1", "1.0", "true"}
                         and (value := _number(row.get("los_velocity_cm_year"))) is not None]
        if farm_movement and abs(float(median(farm_movement))) >= 1.0:
            limitations.append("The farm-wide median LOS velocity is elevated; a farm-relative map can hide motion shared by most of the farm.")
        if red_cluster < 4:
            limitations.append("High-concern labels require at least four adjacent source pixels; isolated cells are not promoted to a farm-level prompt review.")
        limitations.extend(groundwater.limitations)

        summary = {
            "red": "A high-priority movement pattern was detected and should be reviewed promptly.",
            "yellow": "Movement or unresolved measurement uncertainty covers the largest area; review is needed before calling the land stable.",
            "green": "Small measured movement with calibrated uncertainty covers the largest area; inspect any highlighted minority areas separately.",
            "grey": "The available satellite pixels are not reliable enough to classify.",
        }[overall]
        recommendations = self._recommendations(overall, groundwater, area_summary)
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
            climate=climate,
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
                "classifier_version": "movement-screen-v3",
                "area_summary": area_summary,
                "calibration_status": "uncalibrated_no_independent_ground_truth",
                "signal_quality_diagnostics": signal_quality,
                "reliable_pixel_fraction": reliable_fraction,
                "reliable_pixel_count": reliable_count,
                "farm_median_los_velocity_cm_year": median(farm_movement) if farm_movement else None,
                "grid_spacing_map_units": [pixel_width_m, pixel_height_m],
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
        transform = manifest.get("grid_transform")
        crs = manifest.get("crs")
        if not isinstance(transform, list) or len(transform) != 6 or not crs:
            raise ValueError("The satellite manifest is missing its grid georeferencing.")
        to_lonlat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        farm_shape = shape(selection.geometry)
        plot_shapes = [(plot.plot_id, plot.plot_index, shape(plot.geometry)) for plot in selection.plots]
        uncertainty_interpretable = bool((manifest.get("pair_network") or {}).get("uncertainty_interpretable"))
        a, b, c, d, e, f = [float(value) for value in transform]
        def intersects_farm(row: dict[str, str]):
            rr, cc = int(row["row"]), int(row["column"])
            corners = [(c+cc*a+rr*b,f+cc*d+rr*e),(c+(cc+1)*a+rr*b,f+(cc+1)*d+rr*e),
                       (c+(cc+1)*a+(rr+1)*b,f+(cc+1)*d+(rr+1)*e),(c+cc*a+(rr+1)*b,f+(rr+1)*d+(rr+1)*e)]
            cell = transform_geometry(to_lonlat.transform, Polygon(corners)).intersection(farm_shape)
            if cell.is_empty or cell.area <= 1e-12 or cell.geom_type not in {"Polygon", "MultiPolygon"}:
                return None
            return cell
        candidate_cells = {int(row["row"])*1_000_000+int(row["column"]): intersects_farm(row) for row in rows}
        velocities = [value for row in rows if row.get("quality_mask", "").strip().lower() in {"1", "1.0", "true"}
                      and candidate_cells.get(int(row["row"])*1_000_000+int(row["column"])) is not None
                      and (value := _number(row.get("los_velocity_cm_year"))) is not None]
        center = median(velocities) if velocities else 0.0
        deviations = [abs(value - center) for value in velocities]
        robust_scale = max(1.4826 * median(deviations), 0.3) if deviations else 0.3
        features: list[dict[str, Any]] = []
        counts = {plot_id: {"green": 0, "yellow": 0, "red": 0, "grey": 0} for plot_id, _, _ in plot_shapes}

        for index, row in enumerate(rows):
            r, col = int(row["row"]), int(row["column"])
            cell = candidate_cells.get(r*1_000_000+col)
            if cell is None:
                continue
            velocity = _number(row.get("los_velocity_cm_year"))
            change = _number(row.get("los_displacement_change_cm"))
            sigma = _number(row.get("los_velocity_sigma_cm_year_1sigma"))
            persistence = _persistence(row)
            reliable = row.get("quality_mask", "").strip().lower() in {"1", "1.0", "true"} and velocity is not None
            deviation = velocity - center if velocity is not None else None
            z = abs(deviation) / robust_scale if deviation is not None else None
            sigma_valid = sigma is not None and sigma > 0
            sigma_eff = math.hypot(sigma or 0.0, robust_scale / math.sqrt(max(len(velocities), 1)))
            calibrated = bool(manifest.get("uncertainty_calibrated", False)) and uncertainty_interpretable and sigma_valid
            # More sensitive review thresholds, explicitly not calibrated hazard limits.
            effect = velocity is not None and change is not None and (abs(velocity) >= 1.0 or abs(change) >= 0.5)
            local_effect = (z or 0) >= 1.5 and abs(deviation or 0) >= 0.5
            if not reliable or persistence is None or change is None:
                level = "grey"
                explanation = "Insufficient usable measurements or dates; no movement conclusion is supported."
            elif calibrated and abs(velocity) >= max(2.0, 3 * sigma_eff) and abs(change) >= 1.0 and persistence >= 0.5:
                level = "red"
                explanation = "Large sustained LOS movement exceeds the calibrated uncertainty gate; prompt verification is needed."
            elif effect or local_effect:
                level = "yellow"
                explanation = "Measured LOS movement meets the sensitive review threshold, including motion shared across the farm; this does not confirm vertical subsidence."
            elif calibrated and abs(velocity) + 2 * sigma_eff < 1.0 and abs(change) < 0.5:
                level = "green"
                explanation = "Measured change is small and the calibrated uncertainty bound remains below the movement review threshold."
            else:
                level = "yellow"
                explanation = "Measured movement is small, but uncertainty cannot establish stability; verification is needed."
            centroid = cell.representative_point()
            matched = next(((pid, pindex) for pid, pindex, polygon in plot_shapes if polygon.covers(centroid)), None)
            if matched is None:
                continue
            plot_id, plot_index = matched
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
                    "label": {"green": "Low measured movement", "yellow": "Movement / uncertainty to review", "red": "Strong movement: prompt review", "grey": "Insufficient data"}[level],
                    "explanation": explanation,
                    "los_velocity_cm_year": velocity,
                    "los_velocity_sigma_cm_year": sigma,
                    "deviation_from_farm_median_cm_year": deviation,
                    "relative_z_score": z,
                    "observed_los_change_cm": change,
                    "persistence_fraction": persistence,
                    "coherence": _number(row.get("coherence_mean")),
                    "uncertainty_available": bool(manifest.get("uncertainty_calibrated", False)) and uncertainty_interpretable and sigma_valid,
                    "measurement_start": row.get("measurement_start"),
                    "measurement_end": row.get("measurement_end"),
                    "source_row": r,
                    "source_column": col,
                },
            })
        # Isolated red cells remain review signals, not strong spatial evidence.
        red_cells = {(f["properties"]["source_row"], f["properties"]["source_column"])
                     for f in features if f["properties"]["concern_level"] == "red"}
        for feature in features:
            props = feature["properties"]
            if props["concern_level"] == "red":
                component = {(props["source_row"], props["source_column"])}
                pending = list(component)
                while pending:
                    rr, cc = pending.pop()
                    for neighbor in ((rr-1,cc),(rr+1,cc),(rr,cc-1),(rr,cc+1)):
                        if neighbor in red_cells and neighbor not in component:
                            component.add(neighbor); pending.append(neighbor)
                if len(component) < 4:
                    props.update(concern_level="yellow", label="Isolated movement: review",
                                 explanation="The strong movement signal lacks four adjacent source cells; verify it locally.")
        summaries = []
        for plot_id, plot_index, polygon in plot_shapes:
            subset = [f for f in features if f["properties"]["plot_id"] == plot_id]
            plot_counts = {level: sum(f["properties"]["concern_level"] == level for f in subset) for level in LEVEL_RANK}
            area = _area_summary(subset, mapping(polygon))
            summaries.append({"plot_id": plot_id, "plot_index": plot_index,
                              "overall_concern": area["dominant_class"], "pixel_counts": plot_counts, **area})
        return features, summaries

    @staticmethod
    def _recommendations(level: str, groundwater: GroundwaterEvidence, area_summary=None) -> list[Recommendation]:
        shares = (area_summary or {}).get("area_fractions", {})
        extent = ", ".join(f"{name}: {100*shares.get(name, 0):.1f}%" for name in ("green", "yellow", "red", "grey"))
        actions = {
            "red": [("prompt_review", "Arrange a displacement survey", "Ask a licensed surveyor or geotechnical specialist to check repeat elevations against a stable benchmark. Prioritize canals, buried pipes, and buildings crossing highlighted cells; visible damage warrants inspection before operation."),
                    ("review", "Review pumping with your groundwater manager", "Compare dated well levels and metered abstraction with the displacement record. Ask the local groundwater agency whether pumping redistribution or permitted recharge is appropriate; site geology and water availability must support the choice.")],
            "yellow": [("review", "Verify movement before calling this land stable", "Compare the LOS layer and dated displacement values with DWR/USGS or a local survey covering matching dates. Missing uncertainty is a reason to investigate, not evidence of sinking."),
                       ("review", "Check drainage and irrigation infrastructure", "Inspect highlighted cells for changing canal grades, ponding, cracked conveyance, or leaking pipelines. Measure suspected grade changes before deciding on regrading or repairs."),
                       ("review", "Link movement to local water records", "Align monthly well levels, pump-meter readings, crop irrigation demand, and displacement. Have the groundwater manager evaluate any pumping changes; weather alone cannot establish compaction.")],
            "green": [("routine", "Maintain repeat benchmark checks", "Keep dated elevation checks at stable survey marks and inspect yellow/red minority areas separately. A predominantly green farm can still contain local movement."),
                      ("routine", "Track water use and infrastructure condition", "Maintain pump-meter and well-level records, repair confirmed irrigation leaks, and compare future displacement over matching seasons.")],
            "grey": [("review", "Close the measurement gap", "Confirm the boundary, identify missing cells, and request repeat levelling or GNSS at representative sites. More satellite dates or a different viewing track may improve usable coverage.")],
        }
        result = [Recommendation(priority=priority, title=title, detail=detail) for priority, title, detail in actions[level]]
        result.insert(0, Recommendation(priority="review" if level != "green" else "routine",
                      title="Review area coverage", detail=f"Dominant area class: {level}. {extent}. Unmeasured area is included as grey; a minority red area still warrants local review."))
        return result

    @staticmethod
    def _largest_cluster(pixels: set[tuple[int, int]]) -> int:
        largest = 0
        remaining = set(pixels)
        while remaining:
            seed = remaining.pop()
            stack = [seed]
            size = 0
            while stack:
                row, col = stack.pop()
                size += 1
                for neighbor in ((row-1,col),(row+1,col),(row,col-1),(row,col+1)):
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        stack.append(neighbor)
            largest = max(largest, size)
        return largest
