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


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false.")


@dataclass(frozen=True, slots=True)
class Settings:
    max_selection_area_hectares: float
    min_selection_area_square_meters: float
    cors_origins: tuple[str, ...]
    database_path: str = "backend/data/selections.sqlite3"
    gunw_catalog_enabled: bool = True
    asf_search_api_url: str = "https://api.daac.asf.alaska.edu/services/search/param"
    gunw_catalog_timeout_seconds: float = 20.0
    gunw_product_sample_limit: int = 20
    environment: str = "development"
    technical_api_key: str | None = None
    processing_output_root: str = "backend/data/processing"

    @classmethod
    def from_environment(cls) -> "Settings":
        environment = os.getenv("APP_ENV", "development").strip().lower()
        if environment not in {"development", "test", "production"}:
            raise RuntimeError("APP_ENV must be development, test, or production.")
        technical_api_key = os.getenv("TECHNICAL_API_KEY", "").strip() or None
        if environment == "production" and technical_api_key is None:
            raise RuntimeError("TECHNICAL_API_KEY is required when APP_ENV=production.")
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
            gunw_catalog_enabled=_bool_env("GUNW_CATALOG_ENABLED", True),
            asf_search_api_url=os.getenv(
                "ASF_SEARCH_API_URL",
                "https://api.daac.asf.alaska.edu/services/search/param",
            ),
            gunw_catalog_timeout_seconds=_float_env(
                "GUNW_CATALOG_TIMEOUT_SECONDS", 20.0
            ),
            gunw_product_sample_limit=int(
                os.getenv("GUNW_PRODUCT_SAMPLE_LIMIT", "20")
            ),
            environment=environment,
            technical_api_key=technical_api_key,
            processing_output_root=os.getenv(
                "PROCESSING_OUTPUT_ROOT", "backend/data/processing"
            ),
        )
