from __future__ import annotations

import os
from dataclasses import dataclass


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero.")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    max_selection_area_hectares: float
    min_selection_area_square_meters: float
    cors_origins: tuple[str, ...]
    database_path: str = "backend/data/selections.sqlite3"

    @classmethod
    def from_environment(cls) -> "Settings":
        origins = tuple(
            value.strip()
            for value in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if value.strip()
        )
        return cls(
            max_selection_area_hectares=_float_env(
                "MAX_SELECTION_AREA_HECTARES", 500_000.0
            ),
            min_selection_area_square_meters=_float_env(
                "MIN_SELECTION_AREA_SQUARE_METERS", 1.0
            ),
            cors_origins=origins,
            database_path=os.getenv(
                "SELECTION_DATABASE_PATH", "backend/data/selections.sqlite3"
            ),
        )
