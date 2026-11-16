"""Coordinate-based weather context; never a temperature-to-subsidence predictor."""
from __future__ import annotations

import calendar
import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from shapely.geometry import shape


def monthly_context(daily: dict, start: str, end: str) -> list[dict]:
    buckets = defaultdict(list)
    dates = daily.get("time", [])
    temperatures = daily.get("temperature_2m_mean", [])
    rain = daily.get("precipitation_sum", [])
    if len(dates) != len(temperatures) or len(dates) != len(rain):
        raise ValueError("Weather response arrays have different lengths")
    for day, temp, precipitation in zip(dates, temperatures, rain):
        if start <= day <= end:
            buckets[day[:7]].append((day, temp, precipitation))
    result = []
    for month, values in sorted(buckets.items()):
        year, number = map(int, month.split("-"))
        expected_start = max(date.fromisoformat(start), date(year, number, 1))
        expected_end = min(date.fromisoformat(end), date(year, number, calendar.monthrange(year, number)[1]))
        expected = (expected_end - expected_start).days + 1
        temps = [float(t) for _, t, _ in values if t is not None and math.isfinite(float(t))]
        rains = [float(r) for _, _, r in values if r is not None and math.isfinite(float(r))]
        result.append({"month": month, "expected_days": expected,
                       "temperature_days": len(temps), "precipitation_days": len(rains),
                       "mean_temperature_c": sum(temps) / len(temps) if temps else None,
                       "precipitation_mm": sum(rains) if len(rains) == expected else None,
                       "partial_calendar_month": expected != calendar.monthrange(year, number)[1]})
    return result


class ClimateService:
    def __init__(self, client=None, cache_dir: Path | None = None):
        self._client = client
        self._cache_dir = cache_dir or Path.home() / ".cache" / "groundsignal" / "weather"

    def check(self, selection, start: str | None, end: str | None) -> dict:
        point = shape(selection.geometry).representative_point()
        context = {"status": "not_available", "provider": "Open-Meteo historical reanalysis",
                   "source_url": "https://open-meteo.com/en/docs/historical-weather-api",
                   "location": {"type": "Point", "coordinates": [point.x, point.y]},
                   "requested_start": start, "requested_end": end, "monthly": [],
                   "expected_subsidence_cm_year": None,
                   "comparison_status": "requires_validated_local_displacement_baseline",
                   "changes_concern_colours": False,
                   "summary": "Temperature and rainfall provide context; no normal subsidence rate can be inferred from weather alone.",
                   "limitations": ["A representative weather grid cell does not describe every field in the boundary.",
                                   "These are monthly weather summaries over the observation period, not long-term climate normals.",
                                   "Seasonal movement may include recoverable and permanent deformation; matching a seasonal pattern does not establish safety."]}
        if not start or not end:
            return context
        try:
            start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
            available_end = min(end_day, datetime.now(UTC).date() - timedelta(days=6))
            if available_end < start_day or (end_day - start_day).days > 3660:
                return context
            params = {"latitude": point.y, "longitude": point.x, "start_date": start,
                      "end_date": available_end.isoformat(), "daily": "temperature_2m_mean,precipitation_sum",
                      "timezone": "UTC"}
            key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
            path = self._cache_dir / f"{key}.json"
            try:
                cached = json.loads(path.read_text())
                fresh = (datetime.now(UTC) - datetime.fromisoformat(cached["fetched_at"])).total_seconds() < 86400
                payload = cached["data"] if fresh else None
            except (OSError, ValueError, KeyError, TypeError):
                payload = None
            if payload is None:
                if self._client is None:
                    with httpx.Client(timeout=4.0) as client:
                        response = client.get("https://archive-api.open-meteo.com/v1/archive", params=params)
                else:
                    response = self._client.get("https://archive-api.open-meteo.com/v1/archive", params=params)
                response.raise_for_status()
                payload = response.json()
                # Validate before caching, including corrupt upstream responses.
                monthly_context(payload["daily"], start, available_end.isoformat())
                try:
                    self._cache_dir.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps({"fetched_at": datetime.now(UTC).isoformat(), "data": payload}))
                except OSError:
                    pass
            monthly = monthly_context(payload["daily"], start, available_end.isoformat())
            if not monthly:
                return context
            context.update(status="available", monthly=monthly, available_end=available_end.isoformat(),
                           weather_grid_coordinates=[payload.get("longitude"), payload.get("latitude")])
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            context["status"] = "check_failed"
        return context
