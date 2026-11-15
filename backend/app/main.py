from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .errors import GeometryValidationError
from .models import (
    ErrorDetail,
    ErrorResponse,
    SelectionCreate,
    SelectionResponse,
)
from .repository import SQLiteSelectionRepository
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
