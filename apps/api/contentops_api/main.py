from __future__ import annotations

import secrets
from uuid import uuid4

from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.models import (
    RunStatus,
)
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint

from contentops_api.routes.dashboard import build_dashboard_router
from contentops_api.routes.ops import build_ops_router
from contentops_api.routes.runs import build_runs_router

settings = Settings()
pipeline = build_pipeline(settings)
repository = RunRepository(settings.database_url)
review_service = build_review_service(settings)

app = FastAPI(
    title="AI ContentOps Studio",
    version="0.1.0",
    description="Research, evaluation, and publishing automation for technical content.",
)


@app.middleware("http")
async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
    request_id = request.headers.get("x-contentops-request-id") or uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["x-contentops-request-id"] = request_id
    return response


@app.exception_handler(HTTPException)
async def http_error_response(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = _request_id(request)
    headers = dict(exc.headers or {})
    headers["x-contentops-request-id"] = request_id
    return JSONResponse(
        status_code=exc.status_code,
        headers=headers,
        content={
            "error": {
                "code": _error_code(exc.status_code),
                "message": str(exc.detail),
                "request_id": request_id,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_response(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        status_code=422,
        headers={"x-contentops-request-id": request_id},
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed.",
                "request_id": request_id,
                "fields": exc.errors(),
            }
        },
    )


async def require_operator(request: Request) -> None:
    configured = settings.operator_api_key
    if configured is None:
        return
    expected = configured.get_secret_value()
    provided = request.headers.get("x-contentops-api-key") or request.query_params.get("api_key")
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Valid operator API key required.")


async def require_read_access(request: Request) -> None:
    if not settings.require_read_api_key:
        return
    allowed_keys = [
        configured.get_secret_value()
        for configured in (settings.read_api_key, settings.operator_api_key)
        if configured is not None
    ]
    if not allowed_keys:
        raise HTTPException(
            status_code=503,
            detail="Read access protection requires a read or operator API key.",
        )
    provided = request.headers.get("x-contentops-api-key") or request.query_params.get("api_key")
    if provided is None or not any(secrets.compare_digest(provided, key) for key in allowed_keys):
        raise HTTPException(status_code=401, detail="Valid read API key required.")


def _parse_status_filter(status: str) -> RunStatus | None:
    normalized = status.strip().casefold()
    if not normalized:
        return None
    try:
        return RunStatus(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown run status: {status}") from exc


app.include_router(
    build_ops_router(
        settings=settings,
        repository=repository,
        review_service=review_service,
        require_read_access=require_read_access,
        require_operator=require_operator,
        parse_status_filter=_parse_status_filter,
    )
)

app.include_router(
    build_dashboard_router(
        settings=settings,
        pipeline=pipeline,
        repository=repository,
        review_service=review_service,
        require_read_access=require_read_access,
        require_operator=require_operator,
        parse_status_filter=_parse_status_filter,
    )
)

app.include_router(
    build_runs_router(
        pipeline=pipeline,
        repository=repository,
        review_service=review_service,
        require_read_access=require_read_access,
        require_operator=require_operator,
        parse_status_filter=_parse_status_filter,
    )
)


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", "")
    return str(value) if value else uuid4().hex


def _error_code(status_code: int) -> str:
    labels = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        500: "internal_error",
        503: "service_unavailable",
    }
    return labels.get(status_code, "http_error")

