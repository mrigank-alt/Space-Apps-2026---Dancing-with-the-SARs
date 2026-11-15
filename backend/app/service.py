from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from .config import Settings
from .geometry import validate_and_normalize_geometry
from .models import PlotRecord, SelectionCreate, SpatialSelection
from .repository import SelectionRepository


class SelectionService:
    def __init__(self, settings: Settings, repository: SelectionRepository) -> None:
        self._settings = settings
        self._repository = repository

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
            created_at=datetime.now(UTC),
        )
        return self._repository.save(selection)

    def get(self, selection_id: str) -> SpatialSelection | None:
        return self._repository.get(selection_id)
