from __future__ import annotations

import math
from dataclasses import dataclass

from .models import ForecastResult


@dataclass(frozen=True, slots=True)
class CriticalThresholdInputs:
    """Inputs required before a cell-level damage timeline can be estimated.

    Values must come from a locally calibrated groundwater/compaction model. The
    satellite movement rate by itself is intentionally insufficient.
    """

    cell_id: str
    current_state: float | None = None
    critical_threshold: float | None = None
    worsening_rate_per_day: float | None = None
    rate_uncertainty_per_day: float | None = None
    intervention_lead_days: int | None = None
    current_pumping_rate: float | None = None
    calibrated_safe_pumping_rate: float | None = None
    calibration_id: str | None = None
    threshold_source: str | None = None
    observation_count: int = 0


class CriticalThresholdModel:
    """Guarded future model for qualified threshold and pumping deadlines."""

    version = "critical-threshold-v0.1"

    def evaluate(self, inputs: CriticalThresholdInputs) -> ForecastResult:
        required = {
            "current land/aquifer state": inputs.current_state,
            "locally validated critical threshold": inputs.critical_threshold,
            "calibrated worsening rate": inputs.worsening_rate_per_day,
            "rate uncertainty": inputs.rate_uncertainty_per_day,
            "intervention response time": inputs.intervention_lead_days,
            "current pumping rate": inputs.current_pumping_rate,
            "calibrated safe pumping rate": inputs.calibrated_safe_pumping_rate,
            "model calibration record": inputs.calibration_id,
            "threshold source": inputs.threshold_source,
        }
        missing = [label for label, value in required.items() if value is None]
        if inputs.observation_count < 6:
            missing.append("at least six compatible observation dates")
        if missing:
            return ForecastResult(
                status="not_available",
                title="A safe deadline cannot be calculated yet",
                urgency="monitor_and_investigate",
                summary=(
                    "We do not yet have the local well, pumping, and calibrated damage-threshold "
                    "information needed to say when the land could reach a point of no return."
                ),
                missing_inputs=missing,
                model_version=self.version,
                limitations=[
                    "Satellite movement alone cannot determine when land will become unusable.",
                    "Do not set a pumping deadline or volume from this result without a calibrated local groundwater-response model.",
                ],
            )

        assert inputs.current_state is not None
        assert inputs.critical_threshold is not None
        assert inputs.worsening_rate_per_day is not None
        assert inputs.rate_uncertainty_per_day is not None
        assert inputs.intervention_lead_days is not None
        assert inputs.current_pumping_rate is not None
        assert inputs.calibrated_safe_pumping_rate is not None
        assert inputs.calibration_id is not None
        assert inputs.threshold_source is not None

        remaining = inputs.critical_threshold - inputs.current_state
        if remaining <= 0:
            return ForecastResult(
                status="available",
                title="The calibrated threshold is already reached",
                urgency="prompt_review",
                summary="The supplied calibrated model places this cell at or beyond its management threshold. Confirm with field measurements immediately.",
                threshold_crossing_days_range=(0, 0),
                action_deadline_days=0,
                pumping_target=inputs.calibrated_safe_pumping_rate,
                pumping_target_units="same units as the supplied pumping record",
                model_version=self.version,
                calibration_id=inputs.calibration_id,
                threshold_source=inputs.threshold_source,
                limitations=["This is a modelled management threshold, not proof that the land is permanently damaged."],
            )
        if inputs.worsening_rate_per_day <= 0:
            return ForecastResult(
                status="not_available",
                title="No worsening threshold crossing is supported",
                urgency="routine_monitoring",
                summary="The calibrated input trend is not moving toward the supplied threshold, so no crossing date is calculated.",
                model_version=self.version,
                calibration_id=inputs.calibration_id,
                threshold_source=inputs.threshold_source,
                limitations=["Continue monitoring because the trend may change."],
            )

        slow_rate = max(inputs.worsening_rate_per_day - inputs.rate_uncertainty_per_day, 1e-12)
        fast_rate = inputs.worsening_rate_per_day + inputs.rate_uncertainty_per_day
        if fast_rate <= 0 or not all(math.isfinite(value) for value in (slow_rate, fast_rate, remaining)):
            return ForecastResult(
                status="not_available",
                title="The calibrated forecast inputs are invalid",
                urgency="monitor_and_investigate",
                summary="The threshold model could not calculate a defensible range from the supplied values.",
                model_version=self.version,
                missing_inputs=["finite positive calibrated rate and uncertainty"],
                limitations=["Review the calibration inputs before using this model."],
            )

        earliest = max(0, math.floor((remaining / fast_rate) + 1e-9))
        latest = max(earliest, math.ceil((remaining / slow_rate) - 1e-9))
        action_deadline = max(0, earliest - inputs.intervention_lead_days)
        return ForecastResult(
            status="available",
            title="A calibrated action window is available",
            urgency="prompt_review" if action_deadline <= 30 else "planned_action",
            summary=(
                f"The supplied local model estimates the management threshold could be reached in "
                f"{earliest} to {latest} days. Complete review and any approved pumping change within "
                f"{action_deadline} days so the modelled response has time to take effect."
            ),
            threshold_crossing_days_range=(earliest, latest),
            action_deadline_days=action_deadline,
            pumping_target=inputs.calibrated_safe_pumping_rate,
            pumping_target_units="same units as the supplied pumping record",
            model_version=self.version,
            calibration_id=inputs.calibration_id,
            threshold_source=inputs.threshold_source,
            limitations=[
                "This is a qualified model estimate, not a guarantee or a declaration that the land will be dead.",
                "The result is only valid for the supplied calibration, threshold, pumping record, and uncertainty range.",
            ],
        )
