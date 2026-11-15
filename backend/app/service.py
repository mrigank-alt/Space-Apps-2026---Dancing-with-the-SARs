from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from .config import Settings
from .geometry import validate_and_normalize_geometry
from .models import (
    GUNWAvailability,
    PlotGUNWAvailability,
    PlotRecord,
    SelectionCreate,
    SpatialSelection,
)
from .repository import SelectionRepository
from .satellite import CHECK_FAILED_MESSAGE, GUNWCatalog


class SelectionService:
    def __init__(
        self,
        settings: Settings,
        repository: SelectionRepository,
        gunw_catalog: GUNWCatalog,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._gunw_catalog = gunw_catalog

    def create(self, payload: SelectionCreate) -> SpatialSelection:
        validated = validate_and_normalize_geometry(payload.geometry, self._settings)
        selection_id = f"sel_{uuid4().hex}"
        polygon_geometries = (
            [validated.geometry]
            if validated.geometry["type"] == "Polygon"
            else [
                {"type": "Polygon", "coordinates": coordinates}
                for coordinates in validated.geometry["coordinates"]
            ]
        )
        plots = []
        for index, geometry in enumerate(polygon_geometries, start=1):
            plot = validate_and_normalize_geometry(geometry, self._settings)
            plots.append(
                PlotRecord(
                    plot_id=f"{selection_id}_plot_{index:03d}",
                    plot_index=index,
                    geometry=plot.geometry,
                    bbox=plot.bbox,
                    centroid=plot.centroid,
                    reference_point=plot.reference_point,
                    area=plot.area,
                )
            )
        availability = (
            GUNWAvailability(
                status="checking",
                message="Checking satellite imagery availability in the background.",
                plot_results=[
                    PlotGUNWAvailability(
                        plot_id=plot.plot_id,
                        status="checking",
                        message="Checking imagery availability for this plot.",
                    )
                    for plot in plots
                ],
            )
            if self._settings.gunw_catalog_enabled
            else self._gunw_catalog.check(plots)
        )
        selection = SpatialSelection(
            selection_id=selection_id,
            geometry=validated.geometry,
            bbox=validated.bbox,
            centroid=validated.centroid,
            reference_point=validated.reference_point,
            area=validated.area,
            plot_count=len(plots),
            plots=plots,
            source=payload.source,
            label=payload.label,
            farmer=payload.farmer,
            farm_profile=payload.farm_profile,
            data_processing_consent=payload.data_processing_consent,
            consent_recorded_at=datetime.now(UTC),
            gunw_availability=availability,
            created_at=datetime.now(UTC),
        )
        return self._repository.save(selection)

    def get(self, selection_id: str) -> SpatialSelection | None:
        return self._repository.get(selection_id)

    def refresh_gunw_availability(self, selection_id: str) -> SpatialSelection | None:
        selection = self._repository.get(selection_id)
        if selection is None:
            return None
        try:
            availability = self._gunw_catalog.check(selection.plots)
        except Exception:
            availability = GUNWAvailability(
                status="check_failed",
                message=CHECK_FAILED_MESSAGE,
                plot_results=[
                    PlotGUNWAvailability(
                        plot_id=plot.plot_id,
                        status="check_failed",
                        message=CHECK_FAILED_MESSAGE,
                    )
                    for plot in selection.plots
                ],
            )
        updated = selection.model_copy(
            update={"gunw_availability": availability}
        )
        return self._repository.save(updated)
