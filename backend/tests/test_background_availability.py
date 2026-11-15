from __future__ import annotations

from dataclasses import replace

import backend.app.main as main_module
from backend.app.models import GUNWAvailability, PlotGUNWAvailability, SelectionCreate
from backend.app.repository import InMemorySelectionRepository
from backend.app.service import SelectionService


class RecordingCatalog:
    def __init__(self) -> None:
        self.calls = 0

    def check(self, plots):
        self.calls += 1
        return GUNWAvailability(
            status="available",
            message="Imagery found.",
            plot_results=[
                PlotGUNWAvailability(
                    plot_id=plot.plot_id,
                    status="available",
                    message="Imagery found.",
                )
                for plot in plots
            ],
        )


def payload() -> SelectionCreate:
    return SelectionCreate.model_validate(
        {
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[-112.15, 49.79], [-112.14, 49.79], [-112.14, 49.78], [-112.15, 49.79]]
                ],
            },
            "source": "drawn",
            "label": "Fast save farm",
            "farmer": {
                "operator_name": "Taylor Miller",
                "contact_email": "taylor@example.com",
            },
            "farm_profile": {
                "primary_crop_or_land_use": "Alfalfa",
                "water_source": "groundwater_well",
                "monitoring_goal": "groundwater_risk",
            },
            "data_processing_consent": True,
        }
    )


def test_create_saves_before_catalog_check_and_refresh_updates_same_record() -> None:
    catalog = RecordingCatalog()
    repository = InMemorySelectionRepository()
    service = SelectionService(
        replace(main_module.settings, gunw_catalog_enabled=True),
        repository,
        catalog,
    )

    saved = service.create(payload())

    assert catalog.calls == 0
    assert saved.gunw_availability is not None
    assert saved.gunw_availability.status == "checking"
    assert repository.get(saved.selection_id) == saved

    refreshed = service.refresh_gunw_availability(saved.selection_id)

    assert catalog.calls == 1
    assert refreshed is not None
    assert refreshed.selection_id == saved.selection_id
    assert refreshed.gunw_availability is not None
    assert refreshed.gunw_availability.status == "available"
    assert repository.get(saved.selection_id) == refreshed
