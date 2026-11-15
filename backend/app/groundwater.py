from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

import requests

from .models import GroundwaterEvidence, SpatialSelection


class GroundwaterProvider(Protocol):
    def check(
        self, selection: SpatialSelection, observation_start: str | None = None, observation_end: str | None = None
    ) -> GroundwaterEvidence: ...


class PublicGroundwaterService:
    """Looks for public groundwater context without inventing a local trend."""

    _USGS_URL = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/monitoring-locations/items"
    _USGS_MEASUREMENTS_URL = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/field-measurements/items"

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self._timeout_seconds = timeout_seconds

    def check(
        self, selection: SpatialSelection, observation_start: str | None = None, observation_end: str | None = None
    ) -> GroundwaterEvidence:
        now = datetime.now(UTC)
        lon, lat = selection.reference_point.geometry.coordinates
        if not self._within_us_coverage(lon, lat):
            return GroundwaterEvidence(
                status="outside_coverage",
                checked_at=now,
                relationship_eligible=False,
                summary="No supported public groundwater-monitoring provider covers this farm yet.",
                limitations=[
                    "A nearby well record or a supported regional groundwater service is required before the movement can be evaluated as groundwater-related.",
                ],
            )

        west, south, east, north = selection.bbox
        pad = 0.08
        try:
            response = requests.get(
                self._USGS_MEASUREMENTS_URL,
                params={
                    "f": "json",
                    "bbox": f"{west-pad},{south-pad},{east+pad},{north+pad}",
                    "parameter_code": "72019",
                    "limit": 1000,
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            features = response.json().get("features", [])
        except (requests.RequestException, ValueError, TypeError) as exc:
            return GroundwaterEvidence(
                status="check_failed",
                provider="USGS Water Data APIs",
                checked_at=now,
                relationship_eligible=False,
                summary="Public groundwater records could not be checked right now.",
                limitations=[f"USGS groundwater-measurement lookup failed: {type(exc).__name__}."],
            )

        if not features:
            return GroundwaterEvidence(
                status="not_available",
                provider="USGS Water Data APIs",
                checked_at=now,
                relationship_eligible=False,
                summary="No nearby public groundwater-level measurements were found.",
                limitations=["No well-level history is available to compare with the satellite movement."],
            )
        site_ids = {
            str((feature.get("properties") or {}).get("monitoring_location_id"))
            for feature in features
            if (feature.get("properties") or {}).get("monitoring_location_id")
        }
        dated = []
        for feature in features:
            properties = feature.get("properties") or {}
            when = str(properties.get("time") or "")[:10]
            try:
                value = float(properties.get("value"))
            except (TypeError, ValueError):
                continue
            if when:
                dated.append((when, value))
        overlap = [
            item for item in dated
            if (not observation_start or item[0] >= observation_start)
            and (not observation_end or item[0] <= observation_end)
        ]
        trend_summary = None
        if len(dated) >= 2:
            first = min(dated, key=lambda item: item[0])
            last = max(dated, key=lambda item: item[0])
            direction = "deeper" if last[1] > first[1] else "shallower" if last[1] < first[1] else "unchanged"
            trend_summary = (
                f"Available measurements span {first[0]} to {last[0]}; the first-to-last depth-to-water value is {direction}. "
                "This simple comparison is context, not a calibrated aquifer trend."
            )
        overlap_note = (
            f" {len(overlap)} measurements overlap the satellite observation dates."
            if observation_start and observation_end
            else ""
        )
        return GroundwaterEvidence(
            status="available",
            provider="USGS Water Data APIs",
            checked_at=now,
            observation_count=len(dated),
            monitoring_site_count=len(site_ids),
            relationship_eligible=False,
            trend_summary=trend_summary,
            summary=(
                f"{len(dated)} public groundwater-level measurements from {len(site_ids)} nearby sites were found."
                f"{overlap_note} The records are not enough on their own to attribute land movement to groundwater."
            ),
            limitations=[
                "Nearby measurements may represent different aquifers, well depths, or local conditions.",
                "Groundwater causation requires aquifer relevance, geological context, and a defensible temporal relationship to the movement.",
            ],
        )

    @staticmethod
    def _within_us_coverage(lon: float, lat: float) -> bool:
        conus = -125 <= lon <= -66 and 24 <= lat <= 50
        alaska = -180 <= lon <= -129 and 51 <= lat <= 72
        hawaii = -161 <= lon <= -154 and 18 <= lat <= 23
        return conus or alaska or hawaii
