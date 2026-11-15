from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Protocol

from .models import SpatialSelection


class SelectionRepository(Protocol):
    def save(self, selection: SpatialSelection) -> SpatialSelection: ...

    def get(self, selection_id: str) -> SpatialSelection | None: ...

    def latest(self) -> SpatialSelection | None: ...

    def intersecting(
        self, bbox: tuple[float, float, float, float]
    ) -> list[SpatialSelection]: ...


class InMemorySelectionRepository:
    """Development repository with the same interface a durable store can implement."""

    def __init__(self) -> None:
        self._items: dict[str, SpatialSelection] = {}
        self._lock = RLock()

    def save(self, selection: SpatialSelection) -> SpatialSelection:
        with self._lock:
            self._items[selection.selection_id] = selection
        return selection

    def get(self, selection_id: str) -> SpatialSelection | None:
        with self._lock:
            return self._items.get(selection_id)

    def latest(self) -> SpatialSelection | None:
        with self._lock:
            return next(reversed(self._items.values()), None) if self._items else None

    def intersecting(
        self, bbox: tuple[float, float, float, float]
    ) -> list[SpatialSelection]:
        west, south, east, north = bbox
        with self._lock:
            return [
                item
                for item in self._items.values()
                if item.bbox[0] <= east
                and item.bbox[2] >= west
                and item.bbox[1] <= north
                and item.bbox[3] >= south
            ]


class SQLiteSelectionRepository:
    """Durable GeoJSON records with an R-tree index for bounding-box queries."""

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        self._lock = RLock()
        if database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS selections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    selection_id TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL,
                    geometry_type TEXT NOT NULL,
                    geometry_json TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    min_longitude REAL NOT NULL,
                    min_latitude REAL NOT NULL,
                    max_longitude REAL NOT NULL,
                    max_latitude REAL NOT NULL,
                    area_square_meters REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS selection_bounds USING rtree(
                    id,
                    min_longitude, max_longitude,
                    min_latitude, max_latitude
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS selections_label_idx ON selections(label)"
            )

    def save(self, selection: SpatialSelection) -> SpatialSelection:
        payload = selection.model_dump(mode="json")
        record_json = json.dumps(payload, separators=(",", ":"))
        geometry_json = json.dumps(selection.geometry, separators=(",", ":"))
        west, south, east, north = selection.bbox
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO selections (
                    selection_id, label, geometry_type, geometry_json, record_json,
                    min_longitude, min_latitude, max_longitude, max_latitude,
                    area_square_meters, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selection.selection_id,
                    selection.label,
                    selection.geometry["type"],
                    geometry_json,
                    record_json,
                    west,
                    south,
                    east,
                    north,
                    selection.area.square_meters,
                    selection.created_at.isoformat(),
                ),
            )
            self._connection.execute(
                "INSERT INTO selection_bounds VALUES (?, ?, ?, ?, ?)",
                (cursor.lastrowid, west, east, south, north),
            )
            # Keep only the just-confirmed boundary as the active GeoJSON.
            self._connection.execute(
                "DELETE FROM selection_bounds WHERE id != ?", (cursor.lastrowid,)
            )
            self._connection.execute(
                "DELETE FROM selections WHERE id != ?", (cursor.lastrowid,)
            )
        return selection

    def get(self, selection_id: str) -> SpatialSelection | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT record_json FROM selections WHERE selection_id = ?",
                (selection_id,),
            ).fetchone()
        return self._record(row)

    def latest(self) -> SpatialSelection | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT record_json FROM selections ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return self._record(row)

    def intersecting(
        self, bbox: tuple[float, float, float, float]
    ) -> list[SpatialSelection]:
        west, south, east, north = bbox
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT selections.record_json
                FROM selection_bounds
                JOIN selections ON selections.id = selection_bounds.id
                WHERE selection_bounds.min_longitude <= ?
                  AND selection_bounds.max_longitude >= ?
                  AND selection_bounds.min_latitude <= ?
                  AND selection_bounds.max_latitude >= ?
                ORDER BY selections.created_at DESC
                """,
                (east, west, north, south),
            ).fetchall()
        return [record for row in rows if (record := self._record(row)) is not None]

    @staticmethod
    def _record(row: sqlite3.Row | None) -> SpatialSelection | None:
        if row is None:
            return None
        return SpatialSelection.model_validate(json.loads(row["record_json"]))
