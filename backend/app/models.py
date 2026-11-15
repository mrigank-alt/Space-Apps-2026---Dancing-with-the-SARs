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


class PlotRecord(BaseModel):
    """One independently queryable parcel within a saved farm selection."""

    plot_id: str
    plot_index: int = Field(..., ge=1)
    geometry: GeoJSONGeometry
    bbox: tuple[float, float, float, float]
    centroid: PointFeature
    reference_point: PointFeature
    area: AreaMetrics


class SpatialSelection(BaseModel):
    """Canonical geometry record consumed by later spatial-query modules."""

    selection_id: str
    geometry: GeoJSONGeometry
    bbox: tuple[float, float, float, float]
    centroid: PointFeature
    reference_point: PointFeature
    area: AreaMetrics
    plot_count: int = Field(default=0, ge=0)
    plots: list[PlotRecord] = Field(default_factory=list)
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
    plot_count: int
    plots: list[PlotRecord]
    crs: Literal["EPSG:4326"]
    coordinate_order: Literal["longitude, latitude"]
    created_at: datetime

    @classmethod
    def from_record(cls, record: SpatialSelection) -> "SelectionResponse":
        payload = record.model_dump()
        if not payload["plots"]:
            legacy_plot = PlotRecord(
                plot_id=f"{record.selection_id}_plot_001",
                plot_index=1,
                geometry=record.geometry,
                bbox=record.bbox,
                centroid=record.centroid,
                reference_point=record.reference_point,
                area=record.area,
            )
            payload["plots"] = [legacy_plot.model_dump()]
            payload["plot_count"] = 1
        return cls.model_validate(payload)


class ErrorDetail(BaseModel):
    code: str
    message: str
    hint: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
