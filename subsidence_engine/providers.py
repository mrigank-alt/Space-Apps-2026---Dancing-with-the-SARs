"""Pluggable ancillary-data interfaces; concrete providers are intentionally TODO stubs."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class AncillaryProvider(Protocol):
    name: str
    units: str
    license: str

    def fetch(self, bbox: tuple[float, float, float, float], crs: str,
              transform: tuple[float, ...], shape: tuple[int, int], cache_dir: Path): ...


class UnconfiguredProvider:
    """Clear fail-closed placeholder until access, endpoint, and license are verified."""

    def __init__(self, name: str, data: str):
        self.name = name
        self.data = data
        self.units = "unknown"
        self.license = "unverified"

    def fetch(self, bbox, crs, transform, shape, cache_dir):
        raise NotImplementedError(
            f"{self.name} ({self.data}) provider is not configured. TODO: verify official access, "
            "dataset version, CRS/resampling rules, and licensing before enabling downloads."
        )


ANCILLARY_PROVIDERS = {
    key: UnconfiguredProvider(key, description)
    for key, description in {
        "dem": "Copernicus GLO-30",
        "land_cover": "ESA WorldCover",
        "population": "WorldPop",
        "built_environment": "OpenStreetMap buildings, roads, canals",
        "precipitation": "CHIRPS",
        "reanalysis": "ERA5 (optional)",
    }.items()
}
