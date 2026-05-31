from __future__ import annotations

from collections.abc import Awaitable, Callable

from contentops_core.diagnostics import (
    deployment_manifest,
    release_readiness,
    system_status,
)
from contentops_core.models import (
    DeploymentManifest,
    ReleaseReadinessReport,
    SystemStatus,
)
from contentops_core.repository import RunRepository
from contentops_core.review import ReviewService
from contentops_core.settings import Settings
from fastapi import APIRouter, Depends, Query, Request, Response

ReadAccessDependency = Callable[[Request], Awaitable[None]]


def build_ops_router(
    *,
    settings: Settings,
    repository: RunRepository,
    review_service: ReviewService,
    require_read_access: ReadAccessDependency,
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/ready", response_model=SystemStatus)
    def ready(response: Response) -> SystemStatus:
        status = system_status(settings, repository)
        if status.status == "fail":
            response.status_code = 503
        return status

    @router.get(
        "/deployment-manifest",
        response_model=DeploymentManifest,
        dependencies=[Depends(require_read_access)],
    )
    def get_deployment_manifest() -> DeploymentManifest:
        return deployment_manifest(settings, repository)

    @router.get(
        "/release-readiness",
        response_model=ReleaseReadinessReport,
        dependencies=[Depends(require_read_access)],
    )
    def get_release_readiness(
        window_size: int = Query(default=100, ge=1, le=500),
    ) -> ReleaseReadinessReport:
        operations = review_service.operations_summary(window_size=window_size)
        return release_readiness(settings, repository, operations)

    return router
