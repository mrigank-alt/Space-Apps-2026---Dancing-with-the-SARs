from __future__ import annotations

from datetime import UTC, datetime

from backend.app.models import AreaMetrics, PointFeature, PointGeometry, SpatialSelection
from backend.app.repository import SQLiteSelectionRepository


def selection() -> SpatialSelection:
    return SpatialSelection(
        selection_id="sel_persistence_test",
        label="North irrigation field",
        geometry={
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        },
        bbox=(0, 0, 1, 1),
        centroid=PointFeature(
            geometry=PointGeometry(coordinates=(0.5, 0.5)),
            properties={"method": "geometric centroid"},
        ),
        reference_point=PointFeature(
            geometry=PointGeometry(coordinates=(0.5, 0.5)),
            properties={"method": "point guaranteed to lie within the selection"},
        ),
        area=AreaMetrics(square_meters=10_000, hectares=1, acres=2.471054),
        created_at=datetime.now(UTC),
    )


def test_selection_survives_repository_recreation(tmp_path) -> None:
    database_path = str(tmp_path / "spatial.sqlite3")
    first_repository = SQLiteSelectionRepository(database_path)
    first_repository.save(selection())

    restarted_repository = SQLiteSelectionRepository(database_path)
    restored = restarted_repository.get("sel_persistence_test")

    assert restored is not None
    assert restored.label == "North irrigation field"
    assert restored.geometry["type"] == "Polygon"
    assert restored.area.hectares == 1
    assert restored.plot_count == 1
    assert restored.plots[0].plot_id == "sel_persistence_test_plot_001"


def test_rtree_finds_only_intersecting_selections(tmp_path) -> None:
    repository = SQLiteSelectionRepository(str(tmp_path / "spatial.sqlite3"))
    repository.save(selection())

    assert [item.selection_id for item in repository.intersecting((0.5, 0.5, 2, 2))] == [
        "sel_persistence_test"
    ]
    assert repository.intersecting((10, 10, 11, 11)) == []
