from backend.app.critical_threshold import CriticalThresholdInputs, CriticalThresholdModel
from fastapi.testclient import TestClient
from backend.app.main import app


def test_future_model_refuses_to_invent_a_deadline_without_calibration() -> None:
    result = CriticalThresholdModel().evaluate(
        CriticalThresholdInputs(cell_id="zone_1", observation_count=10)
    )

    assert result.status == "not_available"
    assert result.action_deadline_days is None
    assert result.pumping_target is None
    assert "local well" in result.summary
    assert "locally validated critical threshold" in result.missing_inputs


def test_calibrated_future_model_returns_qualified_range_and_action_window() -> None:
    result = CriticalThresholdModel().evaluate(
        CriticalThresholdInputs(
            cell_id="zone_1",
            current_state=4.0,
            critical_threshold=10.0,
            worsening_rate_per_day=0.10,
            rate_uncertainty_per_day=0.02,
            intervention_lead_days=14,
            current_pumping_rate=100.0,
            calibrated_safe_pumping_rate=70.0,
            calibration_id="synthetic-test-calibration",
            threshold_source="synthetic test threshold",
            observation_count=12,
        )
    )

    assert result.status == "available"
    assert result.threshold_crossing_days_range == (50, 75)
    assert result.action_deadline_days == 36
    assert result.pumping_target == 70.0
    assert "not a guarantee" in result.limitations[0]


def test_calibrated_model_does_not_predict_crossing_for_nonworsening_trend() -> None:
    result = CriticalThresholdModel().evaluate(
        CriticalThresholdInputs(
            cell_id="zone_1",
            current_state=4.0,
            critical_threshold=10.0,
            worsening_rate_per_day=0.0,
            rate_uncertainty_per_day=0.02,
            intervention_lead_days=14,
            current_pumping_rate=100.0,
            calibrated_safe_pumping_rate=70.0,
            calibration_id="synthetic-test-calibration",
            threshold_source="synthetic test threshold",
            observation_count=12,
        )
    )

    assert result.status == "not_available"
    assert result.urgency == "routine_monitoring"


def test_technical_model_api_preserves_unavailable_state() -> None:
    response = TestClient(app).post(
        "/api/v1/models/critical-threshold/evaluate",
        json={"cell_id": "zone_1", "observation_count": 10},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "not_available"
    assert response.json()["action_deadline_days"] is None
