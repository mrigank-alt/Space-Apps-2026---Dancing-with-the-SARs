from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Protocol

from .models import Assessment, PlotRecord, ProcessingRun, SpatialSelection


class SelectionRepository(Protocol):
    def save(self, selection: SpatialSelection) -> SpatialSelection: ...

    def get(self, selection_id: str) -> SpatialSelection | None: ...

    def intersecting(
        self, bbox: tuple[float, float, float, float]
    ) -> list[SpatialSelection]: ...

    def save_processing_run(self, run: ProcessingRun) -> ProcessingRun: ...

    def get_processing_run(self, run_id: str) -> ProcessingRun | None: ...

    def list_processing_runs(self, selection_id: str) -> list[ProcessingRun]: ...

    def claim_processing_run(self, run: ProcessingRun) -> bool: ...

    def recover_interrupted_processing_runs(self) -> list[str]: ...

    def list_queued_processing_runs(self) -> list[ProcessingRun]: ...

    def save_assessment(self, assessment: Assessment) -> Assessment: ...

    def get_assessment(self, assessment_id: str) -> Assessment | None: ...

    def list_assessments(self, selection_id: str) -> list[Assessment]: ...


class InMemorySelectionRepository:
    """Development repository with the same interface a durable store can implement."""

    def __init__(self) -> None:
        self._items: dict[str, SpatialSelection] = {}
        self._processing_runs: dict[str, ProcessingRun] = {}
        self._assessments: dict[str, Assessment] = {}
        self._lock = RLock()

    def save(self, selection: SpatialSelection) -> SpatialSelection:
        with self._lock:
            self._items[selection.selection_id] = selection
        return selection

    def get(self, selection_id: str) -> SpatialSelection | None:
        with self._lock:
            return self._items.get(selection_id)

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

    def save_processing_run(self, run: ProcessingRun) -> ProcessingRun:
        with self._lock:
            self._processing_runs[run.run_id] = run
        return run

    def get_processing_run(self, run_id: str) -> ProcessingRun | None:
        with self._lock:
            return self._processing_runs.get(run_id)

    def list_processing_runs(self, selection_id: str) -> list[ProcessingRun]:
        with self._lock:
            return sorted(
                (run for run in self._processing_runs.values() if run.selection_id == selection_id),
                key=lambda run: run.created_at,
                reverse=True,
            )

    def claim_processing_run(self, run: ProcessingRun) -> bool:
        with self._lock:
            current = self._processing_runs.get(run.run_id)
            if current is None or current.status != "queued":
                return False
            self._processing_runs[run.run_id] = run
            return True

    def recover_interrupted_processing_runs(self) -> list[str]:
        with self._lock:
            recovered = []
            for run_id, run in list(self._processing_runs.items()):
                if run.status == "running":
                    queued = run.model_copy(update={"status": "queued", "started_at": None,
                                                    "message": "Resuming analysis after a server restart.",
                                                    "stage": "Waiting", "progress_percent": 5})
                    self._processing_runs[run_id] = queued
                    recovered.append(run_id)
            return recovered

    def list_queued_processing_runs(self) -> list[ProcessingRun]:
        with self._lock:
            return sorted((run for run in self._processing_runs.values() if run.status == "queued"),
                          key=lambda run: run.created_at)

    def save_assessment(self, assessment: Assessment) -> Assessment:
        with self._lock:
            self._assessments[assessment.assessment_id] = assessment
        return assessment

    def get_assessment(self, assessment_id: str) -> Assessment | None:
        with self._lock:
            return self._assessments.get(assessment_id)

    def list_assessments(self, selection_id: str) -> list[Assessment]:
        with self._lock:
            return sorted(
                (item for item in self._assessments.values() if item.selection_id == selection_id),
                key=lambda item: item.created_at,
                reverse=True,
            )


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
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processing_runs (
                    run_id TEXT PRIMARY KEY,
                    selection_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(selection_id) REFERENCES selections(selection_id)
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS processing_runs_selection_idx "
                "ON processing_runs(selection_id, created_at DESC)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS assessments (
                    assessment_id TEXT PRIMARY KEY,
                    selection_id TEXT NOT NULL,
                    processing_run_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(selection_id) REFERENCES selections(selection_id),
                    FOREIGN KEY(processing_run_id) REFERENCES processing_runs(run_id)
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS assessments_selection_idx "
                "ON assessments(selection_id, created_at DESC)"
            )

    def save(self, selection: SpatialSelection) -> SpatialSelection:
        payload = selection.model_dump(mode="json")
        record_json = json.dumps(payload, separators=(",", ":"))
        geometry_json = json.dumps(selection.geometry, separators=(",", ":"))
        west, south, east, north = selection.bbox
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT id FROM selections WHERE selection_id = ?",
                (selection.selection_id,),
            ).fetchone()
            if existing is not None:
                row_id = int(existing["id"])
                self._connection.execute(
                    """
                    UPDATE selections SET
                        label = ?, geometry_type = ?, geometry_json = ?, record_json = ?,
                        min_longitude = ?, min_latitude = ?, max_longitude = ?,
                        max_latitude = ?, area_square_meters = ?, created_at = ?
                    WHERE id = ?
                    """,
                    (
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
                        row_id,
                    ),
                )
                self._connection.execute(
                    """
                    UPDATE selection_bounds SET
                        min_longitude = ?, max_longitude = ?,
                        min_latitude = ?, max_latitude = ?
                    WHERE id = ?
                    """,
                    (west, east, south, north, row_id),
                )
                return selection

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
        return selection

    def get(self, selection_id: str) -> SpatialSelection | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT record_json FROM selections WHERE selection_id = ?",
                (selection_id,),
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

    def save_processing_run(self, run: ProcessingRun) -> ProcessingRun:
        payload = json.dumps(run.model_dump(mode="json"), separators=(",", ":"))
        updated_at = (run.completed_at or run.started_at or run.created_at).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO processing_runs (
                    run_id, selection_id, status, record_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    record_json = excluded.record_json,
                    updated_at = excluded.updated_at
                """,
                (
                    run.run_id,
                    run.selection_id,
                    run.status,
                    payload,
                    run.created_at.isoformat(),
                    updated_at,
                ),
            )
        return run

    def get_processing_run(self, run_id: str) -> ProcessingRun | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT record_json FROM processing_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return ProcessingRun.model_validate(json.loads(row["record_json"]))

    def list_processing_runs(self, selection_id: str) -> list[ProcessingRun]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT record_json FROM processing_runs WHERE selection_id = ? ORDER BY created_at DESC",
                (selection_id,),
            ).fetchall()
        return [ProcessingRun.model_validate(json.loads(row["record_json"])) for row in rows]

    def claim_processing_run(self, run: ProcessingRun) -> bool:
        payload = json.dumps(run.model_dump(mode="json"), separators=(",", ":"))
        updated_at = (run.started_at or run.created_at).isoformat()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE processing_runs SET status = ?, record_json = ?, updated_at = ? "
                "WHERE run_id = ? AND status = 'queued'",
                (run.status, payload, updated_at, run.run_id),
            )
            return cursor.rowcount == 1

    def recover_interrupted_processing_runs(self) -> list[str]:
        recovered = []
        with self._lock, self._connection:
            rows = self._connection.execute(
                "SELECT record_json FROM processing_runs WHERE status = 'running'"
            ).fetchall()
            for row in rows:
                run = ProcessingRun.model_validate(json.loads(row["record_json"]))
                queued = run.model_copy(update={"status": "queued", "started_at": None,
                                                "message": "Resuming analysis after a server restart.",
                                                "stage": "Waiting", "progress_percent": 5})
                payload = json.dumps(queued.model_dump(mode="json"), separators=(",", ":"))
                self._connection.execute(
                    "UPDATE processing_runs SET status = 'queued', record_json = ?, updated_at = ? "
                    "WHERE run_id = ? AND status = 'running'",
                    (payload, queued.created_at.isoformat(), queued.run_id),
                )
                recovered.append(queued.run_id)
        return recovered

    def list_queued_processing_runs(self) -> list[ProcessingRun]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT record_json FROM processing_runs WHERE status = 'queued' ORDER BY created_at"
            ).fetchall()
        return [ProcessingRun.model_validate(json.loads(row["record_json"])) for row in rows]

    def save_assessment(self, assessment: Assessment) -> Assessment:
        payload = json.dumps(assessment.model_dump(mode="json"), separators=(",", ":"))
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO assessments (
                    assessment_id, selection_id, processing_run_id, record_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(assessment_id) DO UPDATE SET record_json = excluded.record_json
                """,
                (
                    assessment.assessment_id,
                    assessment.selection_id,
                    assessment.processing_run_id,
                    payload,
                    assessment.created_at.isoformat(),
                ),
            )
        return assessment

    def get_assessment(self, assessment_id: str) -> Assessment | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT record_json FROM assessments WHERE assessment_id = ?",
                (assessment_id,),
            ).fetchone()
        return None if row is None else Assessment.model_validate(json.loads(row["record_json"]))

    def list_assessments(self, selection_id: str) -> list[Assessment]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT record_json FROM assessments WHERE selection_id = ? ORDER BY created_at DESC",
                (selection_id,),
            ).fetchall()
        return [Assessment.model_validate(json.loads(row["record_json"])) for row in rows]

    @staticmethod
    def _record(row: sqlite3.Row | None) -> SpatialSelection | None:
        if row is None:
            return None
        selection = SpatialSelection.model_validate(json.loads(row["record_json"]))
        if selection.plots:
            return selection
        legacy_plot = PlotRecord(
            plot_id=f"{selection.selection_id}_plot_001",
            plot_index=1,
            geometry=selection.geometry,
            bbox=selection.bbox,
            centroid=selection.centroid,
            reference_point=selection.reference_point,
            area=selection.area,
        )
        return selection.model_copy(update={"plots": [legacy_plot], "plot_count": 1})
