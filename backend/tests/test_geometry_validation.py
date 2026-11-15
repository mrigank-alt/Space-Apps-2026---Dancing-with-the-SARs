from __future__ import annotations

import pytest

from backend.app.config import Settings
from backend.app.errors import GeometryValidationError
from backend.app.geometry import validate_and_normalize_geometry


SETTINGS = Settings(
    max_selection_area_hectares=500_000,
    min_selection_area_square_meters=1,
    cors_origins=(),
)


def polygon(coordinates: list[list[float]]) -> dict[str, object]:
    return {"type": "Polygon", "coordinates": [coordinates]}


def test_valid_polygon_is_oriented_normalized_and_measured() -> None:
    geometry = polygon(
        [
            [-112.15, 49.79],
            [-112.14, 49.79],
            [-112.14, 49.78],
            [-112.15, 49.78],
            [-112.15, 49.79],
        ]
    )

    result = validate_and_normalize_geometry(geometry, SETTINGS)

    assert result.geometry["type"] == "Polygon"
    ring = result.geometry["coordinates"][0]
    assert ring[0] == ring[-1]
    assert 79 < result.area.hectares < 81
    assert 195 < result.area.acres < 200
    assert result.bbox == pytest.approx((-112.15, 49.78, -112.14, 49.79))
    assert result.reference_point.geometry.type == "Point"


def test_valid_multipolygon_is_supported() -> None:
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[-112.15, 49.79], [-112.145, 49.79], [-112.145, 49.785], [-112.15, 49.785], [-112.15, 49.79]]],
            [[[-112.14, 49.78], [-112.135, 49.78], [-112.135, 49.775], [-112.14, 49.775], [-112.14, 49.78]]],
        ],
    }

    result = validate_and_normalize_geometry(geometry, SETTINGS)

    assert result.geometry["type"] == "MultiPolygon"
    assert result.area.hectares > 39


@pytest.mark.parametrize(
    ("geometry", "code"),
    [
        ({"type": "Polygon", "coordinates": []}, "empty_geometry"),
        (
            polygon([[-112.15, 49.79], [-112.14, 49.79], [-112.14, 49.78], [-112.15, 49.78]]),
            "unclosed_ring",
        ),
        (
            polygon([[-112.15, 49.79], [-112.15, 49.79], [-112.15, 49.79], [-112.15, 49.79]]),
            "zero_area_ring",
        ),
        (
            polygon([[-112.15, 95], [-112.14, 49.79], [-112.14, 49.78], [-112.15, 95]]),
            "latitude_out_of_range",
        ),
        (
            polygon([[-112.15, 49.79, 3], [-112.14, 49.79], [-112.14, 49.78], [-112.15, 49.79, 3]]),
            "invalid_position",
        ),
        ({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "unsupported_geometry_type"),
    ],
)
def test_structural_validation_returns_helpful_codes(
    geometry: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(GeometryValidationError) as caught:
        validate_and_normalize_geometry(geometry, SETTINGS)
    assert caught.value.code == code
    assert caught.value.message


def test_self_intersection_is_rejected() -> None:
    bow_tie = polygon(
        [[-112.15, 49.79], [-112.14, 49.78], [-112.15, 49.78], [-112.14, 49.79], [-112.15, 49.79]]
    )

    with pytest.raises(GeometryValidationError) as caught:
        validate_and_normalize_geometry(bow_tie, SETTINGS)

    assert caught.value.code == "invalid_geometry"
    assert "Self-intersection" in caught.value.message


def test_implausibly_large_selection_is_rejected() -> None:
    continent_scale = polygon(
        [[-120, 30], [-80, 30], [-80, 60], [-120, 60], [-120, 30]]
    )

    with pytest.raises(GeometryValidationError) as caught:
        validate_and_normalize_geometry(continent_scale, SETTINGS)

    assert caught.value.code == "area_too_large"
    assert "500,000-hectare limit" in caught.value.message
