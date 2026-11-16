from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


GeoJSONGeometry = dict[str, Any]

WaterSource = Literal[
    "groundwater_well",
    "surface_water",
    "rainfed",
    "municipal",
    "mixed",
    "other",
    "unknown",
]
MonitoringGoal = Literal[
    "groundwater_risk",
    "land_subsidence",
    "irrigation_planning",
    "general_monitoring",
]


class FarmerProfile(BaseModel):
    operator_name: str = Field(..., min_length=2, max_length=120)
    contact_email: str = Field(
        ...,
        min_length=5,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    contact_phone: str | None = Field(default=None, max_length=40)


class FarmProfile(BaseModel):
    primary_crop_or_land_use: str = Field(..., min_length=2, max_length=120)
    water_source: WaterSource
    monitoring_goal: MonitoringGoal
    location_label: str | None = Field(default=None, max_length=300)
    location_context: str | None = Field(default=None, max_length=300)


class SelectionCreate(BaseModel):
    """A client-drawn boundary in GeoJSON longitude-latitude order."""

    model_config = ConfigDict(extra="forbid")

    geometry: GeoJSONGeometry = Field(
        ...,
        description="GeoJSON Polygon or MultiPolygon in EPSG:4326.",
    )
    source: Literal["drawn", "imported"] = "drawn"
    label: str = Field(..., min_length=1, max_length=200)
    farmer: FarmerProfile
    farm_profile: FarmProfile
    data_processing_consent: Literal[True]


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


class GUNWProduct(BaseModel):
    product_id: str
    collection: str | None = None
    file_name: str | None = None
    start_time: datetime | None = None
    stop_time: datetime | None = None
    flight_direction: str | None = None
    frame_number: int | None = None
    platform: str | None = None
    download_url: str | None = None


class DatasetAvailability(BaseModel):
    dataset_id: str
    label: str
    category: Literal["gunw", "source"]
    status: Literal["available", "not_available", "check_failed", "not_checked"]
    matched_product_count: int = Field(default=0, ge=0)
    products: list[GUNWProduct] = Field(default_factory=list)
    results_truncated: bool = False
    message: str
    elapsed_seconds: float | None = None
    processable: bool = False


class PlotGUNWAvailability(BaseModel):
    plot_id: str
    status: Literal[
        "available",
        "source_available",
        "not_available",
        "check_failed",
        "not_checked",
        "checking",
    ]
    matched_product_count: int = Field(default=0, ge=0)
    archived_gunw_product_count: int = Field(default=0, ge=0)
    source_scene_count: int = Field(default=0, ge=0)
    products: list[GUNWProduct] = Field(default_factory=list)
    datasets: list[DatasetAvailability] = Field(default_factory=list)
    results_truncated: bool = False
    message: str


class GUNWAvailability(BaseModel):
    status: Literal[
        "available",
        "partial",
        "source_available",
        "not_available",
        "check_failed",
        "not_checked",
        "checking",
    ]
    provider: str = "NASA Alaska Satellite Facility DAAC"
    collection: str = "multiple ASF GUNW collections"
    collections_checked: list[str] = Field(default_factory=list)
    checked_at: datetime | None = None
    matched_product_count: int = Field(default=0, ge=0)
    archived_gunw_product_count: int = Field(default=0, ge=0)
    sentinel1_source_scene_count: int = Field(default=0, ge=0)
    on_demand_processing_may_be_possible: bool = False
    plot_results: list[PlotGUNWAvailability] = Field(default_factory=list)
    message: str
    earthdata_login_required_for_download: bool = True
    elapsed_seconds: float | None = None


class ProcessingRun(BaseModel):
    """Durable status for one GUNW-to-SBAS processing attempt."""

    run_id: str
    selection_id: str
    status: Literal[
        "queued",
        "running",
        "completed",
        "no_data",
        "credentials_required",
        "failed",
    ]
    message: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output_directory: str | None = None
    result_summary: dict[str, Any] | None = None
    error_detail: str | None = None
    progress_percent: int = Field(default=0, ge=0, le=100)
    stage: str = "Waiting"
    assessment_id: str | None = None


ConcernLevel = Literal["green", "yellow", "red", "grey"]


class GroundwaterEvidence(BaseModel):
    status: Literal["available", "not_available", "outside_coverage", "check_failed"]
    provider: str | None = None
    checked_at: datetime
    observation_count: int = Field(default=0, ge=0)
    monitoring_site_count: int = Field(default=0, ge=0)
    relationship_eligible: bool = False
    relationship_assessment: Literal["supports", "contradicts", "insufficient"] = "insufficient"
    trend_summary: str | None = None
    summary: str
    limitations: list[str] = Field(default_factory=list)


class ForecastResult(BaseModel):
    status: Literal["available", "not_available"] = "not_available"
    title: str = "A safe deadline cannot be calculated yet"
    urgency: Literal[
        "routine_monitoring", "monitor_and_investigate", "planned_action", "prompt_review"
    ] = "monitor_and_investigate"
    summary: str
    threshold_crossing_days_range: tuple[int, int] | None = None
    action_deadline_days: int | None = Field(default=None, ge=0)
    pumping_target: float | None = None
    pumping_target_units: str | None = None
    missing_inputs: list[str] = Field(default_factory=list)
    model_version: str | None = None
    calibration_id: str | None = None
    threshold_source: str | None = None
    limitations: list[str] = Field(default_factory=list)


class CriticalThresholdRequest(BaseModel):
    """Technical inputs from a future locally calibrated response model."""

    cell_id: str = Field(..., min_length=1, max_length=200)
    current_state: float | None = None
    critical_threshold: float | None = None
    worsening_rate_per_day: float | None = None
    rate_uncertainty_per_day: float | None = Field(default=None, ge=0)
    intervention_lead_days: int | None = Field(default=None, ge=0)
    current_pumping_rate: float | None = Field(default=None, ge=0)
    calibrated_safe_pumping_rate: float | None = Field(default=None, ge=0)
    calibration_id: str | None = Field(default=None, max_length=300)
    threshold_source: str | None = Field(default=None, max_length=500)
    observation_count: int = Field(default=0, ge=0)


class Recommendation(BaseModel):
    priority: Literal["routine", "review", "prompt_review"]
    title: str
    detail: str
    scope: str = "farm"


class Assessment(BaseModel):
    """Durable, auditable interpretation of one completed satellite run."""

    assessment_id: str
    selection_id: str
    processing_run_id: str
    status: Literal["completed"] = "completed"
    assessment_type: Literal["movement_only", "groundwater_related"]
    methodology: Literal["exploratory_relative_concern"] = "exploratory_relative_concern"
    created_at: datetime
    observation_start: str | None = None
    observation_end: str | None = None
    summary: str
    overall_concern: ConcernLevel
    evidence_quality: Literal["limited", "moderate", "strong"]
    concern_zones: dict[str, Any]
    plot_summaries: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    groundwater: GroundwaterEvidence
    forecast: ForecastResult
    climate: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


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
    farmer: FarmerProfile | None = None
    farm_profile: FarmProfile | None = None
    data_processing_consent: bool = False
    consent_recorded_at: datetime | None = None
    gunw_availability: GUNWAvailability | None = None
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
    farmer: FarmerProfile | None
    farm_profile: FarmProfile | None
    data_processing_consent: bool
    consent_recorded_at: datetime | None
    gunw_availability: GUNWAvailability | None
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
