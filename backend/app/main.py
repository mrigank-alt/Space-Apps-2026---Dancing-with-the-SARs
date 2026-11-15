from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .errors import GeometryValidationError
from .models import (
    Assessment,
    ErrorDetail,
    ErrorResponse,
    ProcessingRun,
    SelectionCreate,
    SelectionResponse,
)
from .repository import SQLiteSelectionRepository
from .processing import GUNWProcessingService
from .satellite import ASFGUNWCatalog, DisabledGUNWCatalog
from .service import SelectionService


settings = Settings.from_environment()
repository = SQLiteSelectionRepository(settings.database_path)
gunw_catalog = (
    ASFGUNWCatalog(
        settings.asf_search_api_url,
        settings.gunw_catalog_timeout_seconds,
        settings.gunw_product_sample_limit,
    )
    if settings.gunw_catalog_enabled
    else DisabledGUNWCatalog()
)
service = SelectionService(settings, repository, gunw_catalog)
processing_service = GUNWProcessingService(repository, settings.processing_output_root)

app = FastAPI(
    title="Groundsignal Farm Selection API",
    version="1.0.0",
    description=(
        "Stores farmer-confirmed plot boundaries and checks whether suitable "
        "satellite imagery is available."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Technical-API-Key"],
)


def require_technical_access(
    supplied_key: Annotated[str | None, Header(alias="X-Technical-API-Key")] = None,
) -> None:
    """Protect farmer records and operational refresh actions outside local development."""
    expected_key = settings.technical_api_key
    if expected_key is None:
        return
    if supplied_key is None or not secrets.compare_digest(supplied_key, expected_key):
        raise HTTPException(status_code=401, detail="Technical access key required.")


@app.exception_handler(GeometryValidationError)
async def geometry_error_handler(
    _request: Request,
    exc: GeometryValidationError,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(code=exc.code, message=exc.message, hint=exc.hint)
    )
    return JSONResponse(status_code=422, content=payload.model_dump(exclude_none=True))


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", []) if part != "body")
    message = first.get("msg", "The request body is invalid.")
    if location:
        message = f"{location}: {message}"
    payload = ErrorResponse(
        error=ErrorDetail(
            code="invalid_request",
            message=message,
            hint="Send JSON with a Polygon or MultiPolygon in the geometry field.",
        )
    )
    return JSONResponse(status_code=422, content=payload.model_dump(exclude_none=True))


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "farm-selection"}


@app.post(
    "/api/v1/selections",
    response_model=SelectionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": ErrorResponse}},
    tags=["selections"],
)
def create_selection(payload: SelectionCreate) -> SelectionResponse:
    return SelectionResponse.from_record(service.create(payload))


@app.get(
    "/api/v1/selections/{selection_id}",
    response_model=SelectionResponse,
    responses={404: {"model": ErrorResponse}},
    tags=["selections"],
)
def get_selection(
    selection_id: str,
    _authorized: Annotated[None, Depends(require_technical_access)],
) -> SelectionResponse | JSONResponse:
    selection = service.get(selection_id)
    if selection is None:
        payload = ErrorResponse(
            error=ErrorDetail(
                code="selection_not_found",
                message="No saved selection exists with that ID.",
                hint="Check the selection ID or confirm the boundary again.",
            )
        )
        return JSONResponse(status_code=404, content=payload.model_dump(exclude_none=True))
    return SelectionResponse.from_record(selection)


@app.post(
    "/api/v1/selections/{selection_id}/gunw-availability",
    response_model=SelectionResponse,
    responses={404: {"model": ErrorResponse}},
    tags=["satellite availability"],
)
def refresh_gunw_availability(
    selection_id: str,
    _authorized: Annotated[None, Depends(require_technical_access)],
) -> SelectionResponse | JSONResponse:
    selection = service.refresh_gunw_availability(selection_id)
    if selection is None:
        payload = ErrorResponse(
            error=ErrorDetail(
                code="selection_not_found",
                message="No saved farm exists with that ID.",
                hint="Check the selection ID and try again.",
            )
        )
        return JSONResponse(status_code=404, content=payload.model_dump(exclude_none=True))
    return SelectionResponse.from_record(selection)


@app.post(
    "/api/v1/selections/{selection_id}/processing-runs",
    response_model=ProcessingRun,
    response_model_exclude={"error_detail"},
    status_code=status.HTTP_202_ACCEPTED,
    responses={404: {"model": ErrorResponse}},
    tags=["satellite processing"],
)
def create_processing_run(
    selection_id: str,
    background_tasks: BackgroundTasks,
    _authorized: Annotated[None, Depends(require_technical_access)],
) -> ProcessingRun | JSONResponse:
    run = processing_service.queue(selection_id)
    if run is None:
        payload = ErrorResponse(
            error=ErrorDetail(
                code="selection_not_found",
                message="No saved farm exists with that ID.",
                hint="Save the farm boundary before preparing satellite results.",
            )
        )
        return JSONResponse(status_code=404, content=payload.model_dump(exclude_none=True))
    background_tasks.add_task(processing_service.execute, run.run_id)
    return run


@app.get(
    "/api/v1/processing-runs/{run_id}",
    response_model=ProcessingRun,
    response_model_exclude={"error_detail"},
    responses={404: {"model": ErrorResponse}},
    tags=["satellite processing"],
)
def get_processing_run(
    run_id: str,
    _authorized: Annotated[None, Depends(require_technical_access)],
) -> ProcessingRun | JSONResponse:
    run = processing_service.get(run_id)
    if run is None:
        payload = ErrorResponse(
            error=ErrorDetail(
                code="processing_run_not_found",
                message="No satellite-analysis run exists with that ID.",
            )
        )
        return JSONResponse(status_code=404, content=payload.model_dump(exclude_none=True))
    return run


@app.get(
    "/api/v1/selections/{selection_id}/processing-runs",
    response_model=list[ProcessingRun],
    response_model_exclude={"error_detail"},
    tags=["satellite processing"],
)
def list_processing_runs(
    selection_id: str,
    _authorized: Annotated[None, Depends(require_technical_access)],
) -> list[ProcessingRun]:
    return repository.list_processing_runs(selection_id)


@app.get(
    "/api/v1/assessments/{assessment_id}",
    response_model=Assessment,
    responses={404: {"model": ErrorResponse}},
    tags=["assessments"],
)
def get_assessment(
    assessment_id: str,
    _authorized: Annotated[None, Depends(require_technical_access)],
) -> Assessment | JSONResponse:
    assessment = repository.get_assessment(assessment_id)
    if assessment is None:
        payload = ErrorResponse(error=ErrorDetail(
            code="assessment_not_found",
            message="No saved assessment exists with that ID.",
        ))
        return JSONResponse(status_code=404, content=payload.model_dump(exclude_none=True))
    return assessment


@app.get(
    "/api/v1/selections/{selection_id}/assessments",
    response_model=list[Assessment],
    tags=["assessments"],
)
def list_assessments(
    selection_id: str,
    _authorized: Annotated[None, Depends(require_technical_access)],
) -> list[Assessment]:
    return repository.list_assessments(selection_id)


@app.get(
    "/api/v1/selections/{selection_id}/assessments/latest",
    response_model=Assessment,
    responses={404: {"model": ErrorResponse}},
    tags=["assessments"],
)
def get_latest_assessment(
    selection_id: str,
    _authorized: Annotated[None, Depends(require_technical_access)],
) -> Assessment | JSONResponse:
    assessments = repository.list_assessments(selection_id)
    if not assessments:
        payload = ErrorResponse(error=ErrorDetail(
            code="assessment_not_found",
            message="This farm does not have a completed assessment yet.",
        ))
        return JSONResponse(status_code=404, content=payload.model_dump(exclude_none=True))
    return assessments[0]


@app.get(
    "/api/v1/assessments/{assessment_id}/map",
    response_model=dict,
    tags=["assessments"],
)
def get_assessment_map(
    assessment_id: str,
    _authorized: Annotated[None, Depends(require_technical_access)],
) -> dict | JSONResponse:
    assessment = repository.get_assessment(assessment_id)
    if assessment is None:
        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(
            code="assessment_not_found", message="No saved assessment exists with that ID."
        )).model_dump(exclude_none=True))
    return assessment.concern_zones


@app.get(
    "/api/v1/assessments/{assessment_id}/zones/{zone_id}",
    response_model=dict,
    tags=["assessments"],
)
def get_concern_zone(
    assessment_id: str,
    zone_id: str,
    _authorized: Annotated[None, Depends(require_technical_access)],
) -> dict | JSONResponse:
    assessment = repository.get_assessment(assessment_id)
    if assessment is None:
        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(
            code="assessment_not_found", message="No saved assessment exists with that ID."
        )).model_dump(exclude_none=True))
    zone = next(
        (feature for feature in assessment.concern_zones.get("features", [])
         if feature.get("properties", {}).get("zone_id") == zone_id),
        None,
    )
    if zone is None:
        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(
            code="zone_not_found", message="No concern area with that ID exists in this assessment."
        )).model_dump(exclude_none=True))
    return zone


@app.get(
    "/api/v1/assessments/{assessment_id}/recommendations",
    response_model=list[dict],
    tags=["assessments"],
)
def get_recommendations(
    assessment_id: str,
    _authorized: Annotated[None, Depends(require_technical_access)],
) -> list[dict] | JSONResponse:
    assessment = repository.get_assessment(assessment_id)
    if assessment is None:
        return JSONResponse(status_code=404, content=ErrorResponse(error=ErrorDetail(
            code="assessment_not_found", message="No saved assessment exists with that ID."
        )).model_dump(exclude_none=True))
    return [item.model_dump(mode="json") for item in assessment.recommendations]
