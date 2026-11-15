from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from .config import Settings
from .geometry import validate_and_normalize_geometry
from .models import SelectionCreate, SpatialSelection
from .repository import SelectionRepository


class SelectionService:
    def __init__(self, settings: Settings, repository: SelectionRepository) -> None:
        self._settings = settings
        self._repository = repository

    def create(self, payload: SelectionCreate) -> SpatialSelection:
        validated = validate_and_normalize_geometry(payload.geometry, self._settings)
        selection = SpatialSelection(
            selection_id=f"sel_{uuid4().hex}",
            geometry=validated.geometry,
            bbox=validated.bbox,
            centroid=validated.centroid,
            reference_point=validated.reference_point,
            area=validated.area,
            source=payload.source,
            label=payload.label,
            created_at=datetime.now(UTC),
        )
        return self._repository.save(selection)

    def get(self, selection_id: str) -> SpatialSelection | None:
        return self._repository.get(selection_id)
