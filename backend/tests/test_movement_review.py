from datetime import date, timedelta

import pytest

from backend.app.assessment import AssessmentService, _area_summary
from backend.app.climate import ClimateService, monthly_context
from backend.tests.test_assessment import NoClimate, NoGroundwater, selection


def classify(velocity, change, *, calibrated=False, quality=1, count=3):
    saved = selection()
    rows = []
    for index in range(count):
        row = {"row": "0", "column": str(index), "los_velocity_cm_year": str(velocity),
               "los_displacement_change_cm": str(change), "quality_mask": str(quality),
               "los_velocity_sigma_cm_year_1sigma": "0.05", "coherence_mean": "0.8"}
        for epoch in range(8):
            day = date(2025, 1, 1) + timedelta(days=30 * epoch)
            row[f"cumulative_los_cm_{day}"] = str(change * epoch / 7)
        rows.append(row)
    manifest = {"grid_transform": [0.03 / count, 0, 0, 0, 0.02, 0], "crs": "EPSG:4326",
                "uncertainty_calibrated": calibrated,
                "pair_network": {"uncertainty_interpretable": calibrated}}
    return AssessmentService(NoGroundwater(), NoClimate())._classify(saved, rows, manifest)[0]


def test_uniform_farm_movement_is_reviewed_without_local_outliers():
    assert {f["properties"]["concern_level"] for f in classify(-3, -1.4)} == {"yellow"}


def test_uncertain_small_movement_cannot_be_green_or_red():
    assert {f["properties"]["concern_level"] for f in classify(0.1, 0.1)} == {"yellow"}
    assert {f["properties"]["concern_level"] for f in classify(-30, -10)} == {"yellow"}
    assert {f["properties"]["concern_level"] for f in classify(0.1, 0.1, calibrated=True)} == {"green"}


def test_missing_quality_stays_grey_and_isolated_red_is_downgraded():
    assert {f["properties"]["concern_level"] for f in classify(-3, -2, quality=0)} == {"grey"}
    assert {f["properties"]["concern_level"] for f in classify(-3, -2, calibrated=True)} == {"yellow"}


def test_area_summary_uses_area_and_accounts_for_unmapped_land():
    geometry = selection().geometry
    def cell(left, right, level):
        return {"properties": {"concern_level": level}, "geometry": {"type": "Polygon", "coordinates": [[[left,0],[right,0],[right,.02],[left,.02],[left,0]]]}}
    # Green has three cells, but yellow covers more actual land.
    features = [cell(0,.001,"green"), cell(.001,.002,"green"), cell(.002,.003,"green"), cell(.003,.025,"yellow")]
    summary = _area_summary(features, geometry)
    assert summary["dominant_class"] == "yellow"
    assert summary["area_fractions"]["grey"] > .1
    assert sum(summary["area_fractions"].values()) == pytest.approx(1, abs=1e-5)


def test_monthly_weather_does_not_invent_subsidence_or_missing_rain():
    monthly = monthly_context({"time": ["2025-01-30", "2025-01-31"],
                               "temperature_2m_mean": [10, 20], "precipitation_sum": [2, None]},
                              "2025-01-30", "2025-01-31")
    assert monthly[0]["mean_temperature_c"] == 15
    assert monthly[0]["precipitation_mm"] is None
    assert monthly[0]["partial_calendar_month"]


def test_weather_request_uses_geojson_coordinates_and_cache(tmp_path):
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"latitude": .01, "longitude": .015, "daily": {"time": ["2025-01-01"], "temperature_2m_mean": [12], "precipitation_sum": [1]}}
    class Client:
        calls = 0
        def get(self, url, params):
            self.calls += 1
            assert params["latitude"] == pytest.approx(.01)
            assert params["longitude"] == pytest.approx(.015)
            return Response()
    client = Client()
    service = ClimateService(client=client, cache_dir=tmp_path)
    first = service.check(selection(), "2025-01-01", "2025-01-01")
    second = service.check(selection(), "2025-01-01", "2025-01-01")
    assert first == second
    assert client.calls == 1
    assert first["expected_subsidence_cm_year"] is None
    assert first["changes_concern_colours"] is False


def test_red_requires_calibrated_spatial_support():
    features = classify(-3, -2, calibrated=True, count=4)
    assert {f["properties"]["concern_level"] for f in features} == {"red"}
