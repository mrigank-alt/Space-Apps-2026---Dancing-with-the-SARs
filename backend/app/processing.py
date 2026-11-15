from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from subsidence_engine import PipelineConfig, run_pipeline

from .models import ProcessingRun
from .repository import SelectionRepository


class GUNWProcessingService:
    """Runs the integrated GUNW screening and SBAS engine with durable status."""

    def __init__(self, repository: SelectionRepository, output_root: str) -> None:
        self._repository = repository
        self._output_root = Path(output_root)

    def queue(self, selection_id: str) -> ProcessingRun | None:
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
        )
        return self._repository.save_processing_run(run)

    def execute(self, run_id: str) -> None:
        run = self._repository.get_processing_run(run_id)
        if run is None:
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

        started = run.model_copy(
            update={
                "status": "running",
                "message": "Satellite imagery is being prepared for your plots.",
                "started_at": datetime.now(UTC),
            }
        )
        self._repository.save_processing_run(started)
        try:
            manifest = run_pipeline(
                PipelineConfig(
                    aoi_id=selection.selection_id,
                    selection_id=selection.selection_id,
                    output_root=self._output_root,
                )
            )
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
            }
            completed = started.model_copy(
                update={
                    "status": "completed",
                    "message": "Satellite results are ready for these plots.",
                    "completed_at": datetime.now(UTC),
                    "output_directory": manifest.get("run_dir"),
                    "result_summary": summary,
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
                }
            )
            self._repository.save_processing_run(failed)

    def get(self, run_id: str) -> ProcessingRun | None:
        return self._repository.get_processing_run(run_id)

    def _finish(self, run: ProcessingRun, status: str, message: str) -> None:
        self._repository.save_processing_run(
            run.model_copy(
                update={
                    "status": status,
                    "message": message,
                    "completed_at": datetime.now(UTC),
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
