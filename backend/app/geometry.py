from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

from pyproj import Geod
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.validation import explain_validity

from .config import Settings
from .errors import GeometryValidationError
from .models import AreaMetrics, GeoJSONGeometry, PointFeature, PointGeometry


WGS84_GEOD = Geod(ellps="WGS84")
SQUARE_METERS_PER_ACRE = 4046.8564224


@dataclass(frozen=True, slots=True)
class ValidatedGeometry:
    geometry: GeoJSONGeometry
    bbox: tuple[float, float, float, float]
    centroid: PointFeature
    reference_point: PointFeature
    area: AreaMetrics


def validate_and_normalize_geometry(
    value: GeoJSONGeometry,
    settings: Settings,
) -> ValidatedGeometry:
    if not isinstance(value, dict):
        raise GeometryValidationError(
            "invalid_geometry",
            "Geometry must be a GeoJSON object.",
            "Send a Polygon or MultiPolygon geometry, not a FeatureCollection.",
        )

    geometry_type = value.get("type")
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        raise GeometryValidationError(
            "unsupported_geometry_type",
            "Only GeoJSON Polygon and MultiPolygon geometries are accepted.",
            "Draw a closed farm boundary before confirming it.",
        )

    coordinates = value.get("coordinates")
    if geometry_type == "Polygon":
        _validate_polygon_coordinates(coordinates, "coordinates")
    else:
        if not isinstance(coordinates, list) or not coordinates:
            raise GeometryValidationError(
                "empty_geometry",
                "The MultiPolygon must contain at least one polygon.",
                "Draw one or more closed land parcels.",
            )
        for polygon_index, polygon in enumerate(coordinates):
            _validate_polygon_coordinates(
                polygon,
                f"coordinates[{polygon_index}]",
            )

    try:
        parsed = shape({"type": geometry_type, "coordinates": coordinates})
    except (TypeError, ValueError, KeyError) as exc:
        raise GeometryValidationError(
            "invalid_geometry",
            "The GeoJSON coordinates could not be read as a valid geometry.",
            "Use numeric [longitude, latitude] pairs and closed rings.",
        ) from exc

    if parsed.is_empty:
        raise GeometryValidationError(
            "empty_geometry",
            "The farm boundary is empty.",
            "Draw a boundary with at least three distinct corners.",
        )
    if not isinstance(parsed, (Polygon, MultiPolygon)):
        raise GeometryValidationError(
            "unsupported_geometry_type",
            "Only Polygon and MultiPolygon geometries are accepted.",
        )
    if not parsed.is_valid:
        reason = explain_validity(parsed)
        raise GeometryValidationError(
            "invalid_geometry",
            f"The farm boundary is not geometrically valid: {reason}.",
            "Edit the boundary so edges do not cross and holes remain inside the outer ring.",
        )

    normalized = _orient_geometry(parsed)
    square_meters = abs(WGS84_GEOD.geometry_area_perimeter(normalized)[0])
    if not math.isfinite(square_meters) or square_meters < settings.min_selection_area_square_meters:
        raise GeometryValidationError(
            "area_too_small",
            "The farm boundary has no measurable area.",
            "Move the corners apart and make sure the ring encloses land.",
        )

    hectares = square_meters / 10_000.0
    if hectares > settings.max_selection_area_hectares:
        maximum = f"{settings.max_selection_area_hectares:,.0f}"
        raise GeometryValidationError(
            "area_too_large",
            f"The selected area is {hectares:,.0f} hectares, above the {maximum}-hectare limit.",
            "Zoom in and draw only the farm parcels you intend to monitor.",
        )

    centroid = normalized.centroid
    reference = normalized.representative_point()
    return ValidatedGeometry(
        geometry=_mapping_as_json(normalized),
        bbox=tuple(float(value) for value in normalized.bounds),
        centroid=_point_feature(centroid.x, centroid.y, "geometric centroid"),
        reference_point=_point_feature(
            reference.x,
            reference.y,
            "point guaranteed to lie within the selection",
        ),
        area=AreaMetrics(
            square_meters=round(square_meters, 3),
            hectares=round(hectares, 6),
            acres=round(square_meters / SQUARE_METERS_PER_ACRE, 6),
        ),
    )


def _validate_polygon_coordinates(value: Any, path: str) -> None:
    if not isinstance(value, list) or not value:
        raise GeometryValidationError(
            "empty_geometry",
            f"{path} must contain at least one closed ring.",
            "Draw an outer boundary around the farm.",
        )

    for ring_index, ring in enumerate(value):
        ring_path = f"{path}[{ring_index}]"
        if not isinstance(ring, list) or len(ring) < 4:
            raise GeometryValidationError(
                "invalid_ring",
                f"{ring_path} must contain at least four positions, including closure.",
                "A valid ring has three distinct corners and repeats its first position at the end.",
            )
        normalized_positions = [
            _validate_position(position, f"{ring_path}[{position_index}]")
            for position_index, position in enumerate(ring)
        ]
        if normalized_positions[0] != normalized_positions[-1]:
            raise GeometryValidationError(
                "unclosed_ring",
                f"{ring_path} is not closed.",
                "Repeat the first [longitude, latitude] position as the final position.",
            )
        distinct = set(normalized_positions[:-1])
        if len(distinct) < 3:
            raise GeometryValidationError(
                "zero_area_ring",
                f"{ring_path} has fewer than three distinct corners.",
                "Draw at least three different points around the farm.",
            )


def _validate_position(value: Any, path: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise GeometryValidationError(
            "invalid_position",
            f"{path} must be exactly [longitude, latitude].",
            "This API accepts two-dimensional EPSG:4326 positions only.",
        )
    longitude, latitude = value
    if (
        isinstance(longitude, bool)
        or isinstance(latitude, bool)
        or not isinstance(longitude, (int, float))
        or not isinstance(latitude, (int, float))
        or not math.isfinite(float(longitude))
        or not math.isfinite(float(latitude))
    ):
        raise GeometryValidationError(
            "invalid_coordinate",
            f"{path} contains a non-numeric or non-finite coordinate.",
            "Coordinates must be finite decimal numbers.",
        )
    longitude = float(longitude)
    latitude = float(latitude)
    if not -180 <= longitude <= 180:
        raise GeometryValidationError(
            "longitude_out_of_range",
            f"Longitude {longitude} at {path} is outside -180 to 180.",
            "Coordinates must use longitude-latitude order in EPSG:4326.",
        )
    if not -90 <= latitude <= 90:
        raise GeometryValidationError(
            "latitude_out_of_range",
            f"Latitude {latitude} at {path} is outside -90 to 90.",
            "Coordinates must use longitude-latitude order in EPSG:4326.",
        )
    return longitude, latitude


def _orient_geometry(geometry: BaseGeometry) -> Polygon | MultiPolygon:
    if isinstance(geometry, Polygon):
        return orient(geometry, sign=1.0)
    if isinstance(geometry, MultiPolygon):
        return MultiPolygon([orient(polygon, sign=1.0) for polygon in geometry.geoms])
    raise TypeError("Expected Polygon or MultiPolygon.")


def _mapping_as_json(geometry: Polygon | MultiPolygon) -> GeoJSONGeometry:
    mapped = mapping(geometry)
    return {
        "type": mapped["type"],
        "coordinates": _nested_lists(mapped["coordinates"]),
    }


def _nested_lists(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_nested_lists(item) for item in value]
    if isinstance(value, list):
        return [_nested_lists(item) for item in value]
    if isinstance(value, float):
        return round(value, 9)
    return value


def _point_feature(longitude: float, latitude: float, method: str) -> PointFeature:
    return PointFeature(
        geometry=PointGeometry(
            coordinates=(round(float(longitude), 9), round(float(latitude), 9))
        ),
        properties={"method": method},
    )
