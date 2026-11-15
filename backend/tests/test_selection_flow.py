from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import backend.app.main as main_module
from backend.app.main import app


client = TestClient(app)


def farmer_payload() -> dict[str, object]:
    return {
        "farmer": {
            "operator_name": "Taylor Miller",
            "contact_email": "taylor@example.com",
            "contact_phone": "+1 555 0100",
        },
        "farm_profile": {
            "primary_crop_or_land_use": "Alfalfa",
            "water_source": "groundwater_well",
            "monitoring_goal": "groundwater_risk",
            "location_label": "Southern Alberta",
        },
        "data_processing_consent": True,
    }


def test_drawn_boundary_reaches_api_and_returns_reusable_selection() -> None:
    # This is the exact geometry shape emitted by the frontend after a user
    # finishes a Terra Draw polygon around an example Alberta field.
    terra_draw_geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [-112.15, 49.79],
                [-112.14, 49.79],
                [-112.14, 49.78],
                [-112.15, 49.78],
                [-112.15, 49.79],
            ]
        ],
    }

    response = client.post(
        "/api/v1/selections",
        json={
            "geometry": terra_draw_geometry,
            "source": "drawn",
            "label": "South pivot field",
            **farmer_payload(),
        },
    )

    assert response.status_code == 201
    created = response.json()
    assert created["selection_id"].startswith("sel_")
    assert created["label"] == "South pivot field"
    assert created["geometry"]["type"] == "Polygon"
    assert created["crs"] == "EPSG:4326"
    assert created["coordinate_order"] == "longitude, latitude"
    assert 79 < created["area"]["hectares"] < 81
    assert created["bbox"] == [-112.15, 49.78, -112.14, 49.79]
    assert created["reference_point"]["geometry"]["type"] == "Point"

    fetched = client.get(f"/api/v1/selections/{created['selection_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_invalid_drawn_boundary_returns_actionable_error() -> None:
    response = client.post(
        "/api/v1/selections",
        json={
            "label": "Invalid example",
            **farmer_payload(),
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[0, 0], [0.01, 0.01], [0, 0.01], [0.01, 0], [0, 0]]
                ],
            }
        },
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_geometry"
    assert error["message"]
    assert error["hint"]


def test_multiple_plots_are_saved_as_one_queryable_farm_selection() -> None:
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[-112.15, 49.79], [-112.145, 49.79], [-112.145, 49.785], [-112.15, 49.785], [-112.15, 49.79]]],
            [[[-112.14, 49.78], [-112.135, 49.78], [-112.135, 49.775], [-112.14, 49.775], [-112.14, 49.78]]],
        ],
    }

    response = client.post(
        "/api/v1/selections",
        json={
            "geometry": geometry,
            "source": "drawn",
            "label": "Miller Family Farm",
            **farmer_payload(),
        },
    )

    assert response.status_code == 201
    saved = response.json()
    assert saved["geometry"]["type"] == "MultiPolygon"
    assert saved["plot_count"] == 2
    assert len(saved["plots"]) == 2
    assert saved["plots"][0]["plot_id"].endswith("_plot_001")
    assert saved["plots"][1]["plot_id"].endswith("_plot_002")
    assert sum(plot["area"]["square_meters"] for plot in saved["plots"]) == pytest.approx(
        saved["area"]["square_meters"], abs=1
    )
    fetched = client.get(f"/api/v1/selections/{saved['selection_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == saved


def test_missing_geometry_returns_consistent_error_envelope() -> None:
    response = client.post(
        "/api/v1/selections",
        json={"source": "drawn", "label": "Missing geometry", **farmer_payload()},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_name_is_required_for_a_saved_boundary() -> None:
    response = client.post(
        "/api/v1/selections",
        json={
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
            },
            "source": "drawn",
            **farmer_payload(),
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_farmer_profile_and_satellite_status_are_saved() -> None:
    response = client.post(
        "/api/v1/selections",
        json={
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0]]],
            },
            "source": "drawn",
            "label": "Miller Family Farm",
            **farmer_payload(),
        },
    )

    assert response.status_code == 201
    saved = response.json()
    assert saved["farmer"]["operator_name"] == "Taylor Miller"
    assert saved["farm_profile"]["water_source"] == "groundwater_well"
    assert saved["data_processing_consent"] is True
    assert saved["consent_recorded_at"]
    assert saved["gunw_availability"]["status"] == "not_checked"


def test_technical_records_are_protected_when_key_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    response = client.post(
        "/api/v1/selections",
        json={
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0]]],
            },
            "source": "drawn",
            "label": "Protected Farm",
            **farmer_payload(),
        },
    )
    selection_id = response.json()["selection_id"]
    protected_settings = replace(
        main_module.settings,
        technical_api_key="test-technical-key",
    )
    monkeypatch.setattr(main_module, "settings", protected_settings)

    assert client.get(f"/api/v1/selections/{selection_id}").status_code == 401
    authorized = client.get(
        f"/api/v1/selections/{selection_id}",
        headers={"X-Technical-API-Key": "test-technical-key"},
    )
    assert authorized.status_code == 200


def test_saved_boundary_can_start_and_retrieve_a_processing_run() -> None:
    response = client.post(
        "/api/v1/selections",
        json={
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-112.15, 49.79], [-112.14, 49.79], [-112.14, 49.78], [-112.15, 49.79]]],
            },
            "source": "drawn",
            "label": "Processing flow farm",
            **farmer_payload(),
        },
    )
    selection_id = response.json()["selection_id"]

    started = client.post(f"/api/v1/selections/{selection_id}/processing-runs")

    assert started.status_code == 202
    run_id = started.json()["run_id"]
    fetched = client.get(f"/api/v1/processing-runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["selection_id"] == selection_id
    assert fetched.json()["status"] == "no_data"
