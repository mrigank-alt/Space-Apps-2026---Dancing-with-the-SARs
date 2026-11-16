from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4

from subsidence_engine import PipelineConfig, run_pipeline

from .assessment import AssessmentService
from .models import ProcessingRun
from .repository import SelectionRepository


class GUNWProcessingService:
    """Runs the integrated GUNW screening and SBAS engine with durable status."""

    def __init__(self, repository: SelectionRepository, output_root: str) -> None:
        self._repository = repository
        self._output_root = Path(output_root)
        self._assessments = AssessmentService()
        self._executor_lock = Lock()
        self._queue_lock = Lock()
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="gunw-processing")

    def queue(self, selection_id: str) -> ProcessingRun | None:
        # Keep repeated clicks/retries from adding another expensive acquisition.
        with self._queue_lock:
            for existing in self._repository.list_processing_runs(selection_id):
                if existing.status in {"queued", "running"}:
                    return self.get(existing.run_id)
            return self._queue_new(selection_id)

    def _queue_new(self, selection_id: str) -> ProcessingRun | None:
        selection = self._repository.get(selection_id)
        if selection is None:
            return None
        now = datetime.now(UTC)
        run = ProcessingRun(
            run_id=f"run_{uuid4().hex}",
            selection_id=selection_id,
            status="queued",
            message="Your satellite analysis is waiting to start.",
            created_at=now,
            progress_percent=5,
            stage="Waiting",
        )
        saved = self._repository.save_processing_run(run)
        self.submit(saved.run_id)
        return saved

    def start(self) -> None:
        """Recover queued or interrupted work after the API process starts."""
        with self._executor_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gunw-processing")
        self._repository.recover_interrupted_processing_runs()
        for run in self._repository.list_queued_processing_runs():
            self.submit(run.run_id)

    def submit(self, run_id: str) -> None:
        with self._executor_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gunw-processing")
            self._executor.submit(self.execute, run_id)

    def close(self) -> None:
        with self._executor_lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=False)

    def execute(self, run_id: str) -> None:
        run = self._repository.get_processing_run(run_id)
        if run is None or run.status != "queued":
            return
        started = run.model_copy(
            update={
                "status": "running",
                "message": "Satellite imagery is being prepared for your plots.",
                "started_at": datetime.now(UTC),
                "progress_percent": 20,
                "stage": "Preparing satellite imagery",
            }
        )
        if not self._repository.claim_processing_run(started):
            return
        selection = self._repository.get(run.selection_id)
        if selection is None:
            self._finish(run, "failed", "The saved farm could not be found.")
            return
        availability = selection.gunw_availability
        if availability is None or availability.archived_gunw_product_count == 0:
            self._finish(
                run,
                "no_data",
                "No suitable archived satellite imagery is available for these plots yet.",
            )
            return
        if not self._earthdata_credentials_available():
            self._finish(
                run,
                "credentials_required",
                "Imagery is available. The analysis server needs NASA Earthdata access before it can prepare results.",
            )
            return

        try:
            manifest = run_pipeline(
                PipelineConfig(
                    aoi_id=selection.selection_id,
                    selection_id=selection.selection_id,
                    output_root=self._output_root,
                    csv_only=True,
                )
            )
            interpreting = started.model_copy(update={
                "message": "The satellite measurements are being checked and mapped.",
                "progress_percent": 85,
                "stage": "Building your concern map",
            })
            self._repository.save_processing_run(interpreting)
            assessment_started = time.perf_counter()
            assessment = self._assessments.create(selection, interpreting, manifest)
            assessment_seconds = time.perf_counter() - assessment_started
            self._repository.save_assessment(assessment)
            summary = {
                "run_id": manifest.get("run_id"),
                "pair_count": (manifest.get("pair_network") or {}).get("pair_count"),
                "epoch_count": (manifest.get("pair_network") or {}).get("epoch_count"),
                "reliable_pixel_fraction": (manifest.get("quality_summary") or {}).get(
                    "reliable_pixel_fraction"
                ),
                "median_los_displacement_change_cm": (manifest.get("quality_summary") or {}).get(
                    "median_los_displacement_change_cm"
                ),
                "median_velocity_los_cm_year": (manifest.get("quality_summary") or {}).get(
                    "median_velocity_los_cm_year"
                ),
                "measurement_interval": manifest.get("measurement_interval"),
                "phase_processing": (manifest.get("processing") or {}).get("phase_processing"),
                "assessment_seconds": assessment_seconds,
                "assessment_feature_count": len(assessment.concern_zones.get("features", [])),
                "assessment_payload_bytes": len(assessment.model_dump_json().encode("utf-8")),
                "pipeline_timings": manifest.get("speed"),
                "signal_quality_diagnostics": manifest.get("signal_quality_diagnostics"),
            }
            completed = interpreting.model_copy(
                update={
                    "status": "completed",
                    "message": "Satellite results are ready for these plots.",
                    "completed_at": datetime.now(UTC),
                    "output_directory": manifest.get("run_dir"),
                    "result_summary": summary,
                    "progress_percent": 100,
                    "stage": "Ready",
                    "assessment_id": assessment.assessment_id,
                }
            )
            self._repository.save_processing_run(completed)
        except Exception as exc:  # Worker failures are persisted instead of crashing the API.
            detail = f"{type(exc).__name__}: {exc}"
            lowered = detail.lower()
            if "earthdata" in lowered or "credential" in lowered or "token" in lowered:
                status = "credentials_required"
                message = (
                    "Imagery is available. The analysis server needs NASA Earthdata access "
                    "before it can prepare results."
                )
            elif "no matching" in lowered or "expected one prepared pair stack, found 0" in lowered:
                status = "no_data"
                message = "No suitable satellite imagery is available for these plots yet."
            else:
                status = "failed"
                message = "We could not prepare the satellite results. Please try again later."
            failed = started.model_copy(
                update={
                    "status": status,
                    "message": message,
                    "completed_at": datetime.now(UTC),
                    "error_detail": detail[-8000:],
                    "stage": "Needs attention",
                }
            )
            self._repository.save_processing_run(failed)

    def get(self, run_id: str) -> ProcessingRun | None:
        run = self._repository.get_processing_run(run_id)
        if run is not None and run.status == "queued":
            queued = self._repository.list_queued_processing_runs()
            position = next((index + 1 for index, item in enumerate(queued) if item.run_id == run_id), None)
            if position is not None:
                return run.model_copy(update={
                    "stage": f"Waiting · queue position {position}",
                    "message": ("Another analysis is using the processing worker. "
                                f"Your job is position {position} in the waiting queue; "
                                "it has not started downloading imagery yet."),
                })
        return run

    def _finish(self, run: ProcessingRun, status: str, message: str) -> None:
        self._repository.save_processing_run(
            run.model_copy(
                update={
                    "status": status,
                    "message": message,
                    "completed_at": datetime.now(UTC),
                    "stage": "Complete",
                    "progress_percent": 100,
                }
            )
        )

    @staticmethod
    def _earthdata_credentials_available() -> bool:
        if os.getenv("EARTHDATA_TOKEN") or os.getenv("EARTHDATA_BEARER_TOKEN"):
            return True
        username = os.getenv("EARTHDATA_USER") or os.getenv("EDL_USERNAME")
        password = os.getenv("EARTHDATA_PASS") or os.getenv("EDL_PASSWORD")
        if username and password:
            return True
        try:
            from earthdata_auth import get_token

            return bool(get_token())
        except Exception:
            return False
