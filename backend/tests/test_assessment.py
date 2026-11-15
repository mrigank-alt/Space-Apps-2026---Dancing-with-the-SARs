from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.assessment import AssessmentService
from backend.app.groundwater import PublicGroundwaterService
from backend.app.main import app, repository
from backend.app.models import (
    AreaMetrics,
    GroundwaterEvidence,
    PlotRecord,
    PointFeature,
    PointGeometry,
    ProcessingRun,
    SpatialSelection,
)


class NoGroundwater:
    def check(self, _selection: SpatialSelection, _start: str | None = None, _end: str | None = None) -> GroundwaterEvidence:
        return GroundwaterEvidence(
            status="outside_coverage",
            checked_at=datetime.now(UTC),
            relationship_eligible=False,
            summary="No supported provider covers this farm.",
        )


def selection(selection_id: str = "sel_assessment_test") -> SpatialSelection:
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [0.03, 0], [0.03, 0.02], [0, 0.02], [0, 0]]],
    }
    point = PointFeature(geometry=PointGeometry(coordinates=(0.015, 0.01)))
    area = AreaMetrics(square_meters=1_000_000, hectares=100, acres=247.105)
    plot = PlotRecord(
        plot_id=f"{selection_id}_plot_001",
        plot_index=1,
        geometry=geometry,
        bbox=(0, 0, 0.03, 0.02),
        centroid=point,
        reference_point=point,
        area=area,
    )
    return SpatialSelection(
        selection_id=selection_id,
        geometry=geometry,
        bbox=(0, 0, 0.03, 0.02),
        centroid=point,
        reference_point=point,
        area=area,
        plot_count=1,
        plots=[plot],
        label="Assessment farm",
        created_at=datetime.now(UTC),
    )


def write_run(tmp_path: Path) -> dict:
    fields = [
        "row", "column", "los_velocity_cm_year", "los_velocity_sigma_cm_year_1sigma",
        "los_displacement_change_cm", "coherence_mean", "quality_mask", "measurement_start",
        "measurement_end", "cumulative_los_cm_2026-01-01", "cumulative_los_cm_2026-02-01",
        "cumulative_los_cm_2026-03-01", "cumulative_los_cm_2026-04-01",
    ]
    rows = [
        [0, 0, -0.2, "nan", -0.05, 0.8, 1, "2026-01-01", "2026-04-01", 0, -0.02, -0.03, -0.05],
        [0, 1, -0.25, "nan", -0.06, 0.8, 1, "2026-01-01", "2026-04-01", 0, -0.02, -0.04, -0.06],
        [0, 2, -2.5, "nan", -0.9, 0.8, 1, "2026-01-01", "2026-04-01", 0, -0.3, -0.6, -0.9],
    ]
    with (tmp_path / "heatmap_pixels.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerows(rows)
    return {
        "run_id": "pipeline_test",
        "run_dir": str(tmp_path),
        "heatmap_csv": "heatmap_pixels.csv",
        "crs": "EPSG:4326",
        "grid_transform": [0.01, 0, 0, 0, 0.02, 0],
        "measurement_interval": {"start": "2026-01-01", "end": "2026-04-01", "elapsed_days": 90},
        "pair_network": {"pair_count": 3, "epoch_count": 4, "uncertainty_interpretable": False},
    }


def test_classifier_creates_clipped_map_zones_and_withholds_red_without_uncertainty(tmp_path: Path) -> None:
    saved = selection()
    run = ProcessingRun(
        run_id="run_assessment_test",
        selection_id=saved.selection_id,
        status="running",
        message="test",
        created_at=datetime.now(UTC),
    )
    assessment = AssessmentService(NoGroundwater()).create(saved, run, write_run(tmp_path))

    assert assessment.assessment_type == "movement_only"
    assert assessment.overall_concern == "yellow"
    assert len(assessment.concern_zones["features"]) == 3
    assert {item["properties"]["concern_level"] for item in assessment.concern_zones["features"]} == {"green", "yellow"}
    assert all(item["properties"]["plot_id"] == saved.plots[0].plot_id for item in assessment.concern_zones["features"])
    assert any("red concern is therefore withheld" in item for item in assessment.limitations)
    raster_path = Path(str(assessment.provenance["classification_raster"]))
    assert raster_path.exists()
    import rasterio
    with rasterio.open(raster_path) as dataset:
        assert dataset.crs.to_string() == "EPSG:4326"
        assert dataset.width == 3
        assert set(dataset.read(1).ravel()) == {1, 2}


def test_groundwater_service_explicitly_reports_unsupported_region() -> None:
    saved = selection()
    saved = saved.model_copy(update={
        "centroid": PointFeature(geometry=PointGeometry(coordinates=(55.95, 30.4))),
        "reference_point": PointFeature(geometry=PointGeometry(coordinates=(55.95, 30.4))),
    })
    evidence = PublicGroundwaterService().check(saved)
    assert evidence.status == "outside_coverage"
    assert evidence.relationship_eligible is False


def test_completed_assessment_is_persistent_and_available_through_api(tmp_path: Path) -> None:
    saved = selection("sel_api_assessment")
    repository.save(saved)
    run = ProcessingRun(
        run_id="run_api_assessment",
        selection_id=saved.selection_id,
        status="completed",
        message="ready",
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    repository.save_processing_run(run)
    assessment = AssessmentService(NoGroundwater()).create(saved, run, write_run(tmp_path))
    repository.save_assessment(assessment)

    response = TestClient(app).get(f"/api/v1/selections/{saved.selection_id}/assessments/latest")
    assert response.status_code == 200
    payload = response.json()
    assert payload["assessment_id"] == assessment.assessment_id
    assert payload["concern_zones"]["features"]
    zone_id = payload["concern_zones"]["features"][0]["properties"]["zone_id"]
    zone_response = TestClient(app).get(f"/api/v1/assessments/{assessment.assessment_id}/zones/{zone_id}")
    assert zone_response.status_code == 200
    assert zone_response.json()["properties"]["zone_id"] == zone_id
