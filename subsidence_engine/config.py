from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class PipelineConfig(BaseModel):
    """Validated configuration for one additive hazard-layer run."""

    model_config = ConfigDict(extra="forbid")

    aoi_id: str = Field(min_length=1)
    geometry: dict[str, Any] | None = None
    selection_id: str | None = Field(default=None, description="Saved selection ID, or 'latest' for the newest confirmed boundary")
    output_root: Path = Path("outputs")
    pair_stack_npz: Path | None = None
    start_date: str | None = None
    end_date: str | None = None
    csv_only: bool = False
    reference_point: tuple[float, float] | None = None
    remove_ramp: bool = True
    phase_sign: float = 1.0
    minimum_valid_pairs: int = Field(default=3, ge=2)
    reliability_min_valid_fraction: float = Field(default=0.6, gt=0, le=1)
    acceleration_min_months: int = Field(default=6, ge=4)
    seasonal_min_months: int = Field(default=12, ge=12)
    risk_weights: dict[str, float] | None = None

    @model_validator(mode="after")
    def require_aoi(self) -> "PipelineConfig":
        if self.geometry is None and self.selection_id is None:
            raise ValueError("Provide geometry or selection_id")
        if self.phase_sign not in (-1.0, 1.0):
            raise ValueError("phase_sign must be -1 or +1")
        return self


def load_config(path: str | Path) -> PipelineConfig:
    with Path(path).open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    return PipelineConfig.model_validate(data)
