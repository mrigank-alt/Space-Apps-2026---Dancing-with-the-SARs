from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


GeoJSONGeometry = dict[str, Any]


class SelectionCreate(BaseModel):
    """A client-drawn boundary in GeoJSON longitude-latitude order."""

    model_config = ConfigDict(extra="forbid")

    geometry: GeoJSONGeometry = Field(
        ...,
        description="GeoJSON Polygon or MultiPolygon in EPSG:4326.",
    )
    source: Literal["drawn", "imported"] = "drawn"
    label: str = Field(..., min_length=1, max_length=200)


class AreaMetrics(BaseModel):
    square_meters: float
    hectares: float
    acres: float


class PointGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]


class PointFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: PointGeometry
    properties: dict[str, str] = Field(default_factory=dict)


class SpatialSelection(BaseModel):
    """Canonical geometry record consumed by later spatial-query modules."""

    selection_id: str
    geometry: GeoJSONGeometry
    bbox: tuple[float, float, float, float]
    centroid: PointFeature
    reference_point: PointFeature
    area: AreaMetrics
    crs: Literal["EPSG:4326"] = "EPSG:4326"
    coordinate_order: Literal["longitude, latitude"] = "longitude, latitude"
    source: Literal["drawn", "imported"] = "drawn"
    label: str
    created_at: datetime


class SelectionResponse(BaseModel):
    selection_id: str
    label: str
    geometry: GeoJSONGeometry
    bbox: tuple[float, float, float, float]
    centroid: PointFeature
    reference_point: PointFeature
    area: AreaMetrics
    crs: Literal["EPSG:4326"]
    coordinate_order: Literal["longitude, latitude"]
    created_at: datetime

    @classmethod
    def from_record(cls, record: SpatialSelection) -> "SelectionResponse":
        return cls.model_validate(record.model_dump())


class ErrorDetail(BaseModel):
    code: str
    message: str
    hint: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
