from __future__ import annotations

from collections.abc import Awaitable, Callable

from contentops_core.diagnostics import (
    deployment_manifest,
    release_readiness,
    system_status,
)
from contentops_core.jobs import (
    JobExecutionListResponse,
    JobExecutionReport,
    JobRecoveryPlan,
    get_job_execution_report,
    job_execution_dir,
    job_recovery_plan,
    list_job_execution_reports,
)
from contentops_core.models import (
    AuditEventListResponse,
    CostReportListResponse,
    DeploymentManifest,
    IncidentReportListResponse,
    OperationsSummary,
    PublishedContentListResponse,
    ReleaseReadinessReport,
    RetentionReport,
    RunStatus,
    ScorecardListResponse,
    SystemStatus,
)
from contentops_core.repository import RunRepository
from contentops_core.review import ReviewService
from contentops_core.settings import Settings
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

ReadAccessDependency = Callable[[Request], Awaitable[None]]
StatusParser = Callable[[str], RunStatus | None]


def build_ops_router(
    *,
    settings: Settings,
    repository: RunRepository,
    review_service: ReviewService,
    require_read_access: ReadAccessDependency,
    parse_status_filter: StatusParser,
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

    @router.get(
        "/job-executions",
        response_model=JobExecutionListResponse,
        dependencies=[Depends(require_read_access)],
    )
    def list_job_executions(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> JobExecutionListResponse:
        return list_job_execution_reports(
            job_execution_dir(settings.artifact_root),
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/job-executions/{execution_id}",
        response_model=JobExecutionReport,
        dependencies=[Depends(require_read_access)],
    )
    def get_job_execution(execution_id: str) -> JobExecutionReport:
        try:
            return get_job_execution_report(
                job_execution_dir(settings.artifact_root),
                execution_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/job-executions/{execution_id}/recovery-plan",
        response_model=JobRecoveryPlan,
        dependencies=[Depends(require_read_access)],
    )
    def get_job_recovery_plan(execution_id: str) -> JobRecoveryPlan:
        try:
            return job_recovery_plan(
                job_execution_dir(settings.artifact_root),
                execution_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/content",
        response_model=PublishedContentListResponse,
        dependencies=[Depends(require_read_access)],
    )
    def list_published_content(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> PublishedContentListResponse:
        return review_service.published_content(limit=limit, offset=offset)

    @router.get(
        "/scorecards",
        response_model=ScorecardListResponse,
        dependencies=[Depends(require_read_access)],
    )
    def list_scorecards(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        status: str = Query(default=""),
        q: str = Query(default=""),
    ) -> ScorecardListResponse:
        return review_service.scorecards(
            limit=limit,
            offset=offset,
            status=parse_status_filter(status),
            query=q,
        )

    @router.get(
        "/cost-reports",
        response_model=CostReportListResponse,
        dependencies=[Depends(require_read_access)],
    )
    def list_cost_reports(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        status: str = Query(default=""),
        q: str = Query(default=""),
    ) -> CostReportListResponse:
        return review_service.cost_reports(
            limit=limit,
            offset=offset,
            status=parse_status_filter(status),
            query=q,
        )

    @router.get(
        "/incident-reports",
        response_model=IncidentReportListResponse,
        dependencies=[Depends(require_read_access)],
    )
    def list_incident_reports(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        status: str = Query(default=""),
        q: str = Query(default=""),
    ) -> IncidentReportListResponse:
        return review_service.incident_reports(
            limit=limit,
            offset=offset,
            status=parse_status_filter(status),
            query=q,
        )

    @router.get(
        "/audit-events",
        response_model=AuditEventListResponse,
        dependencies=[Depends(require_read_access)],
    )
    def list_audit_events(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        status: str = Query(default=""),
        q: str = Query(default=""),
        action: str = Query(default=""),
    ) -> AuditEventListResponse:
        return review_service.audit_events(
            limit=limit,
            offset=offset,
            status=parse_status_filter(status),
            query=q,
            action=action,
        )

    @router.get(
        "/retention-report",
        response_model=RetentionReport,
        dependencies=[Depends(require_read_access)],
    )
    def get_retention_report(
        days: int = Query(default=90, ge=0, le=3650),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> RetentionReport:
        return review_service.retention_report(retention_days=days, limit=limit)

    @router.get(
        "/ops-summary",
        response_model=OperationsSummary,
        dependencies=[Depends(require_read_access)],
    )
    def get_ops_summary(
        window_size: int = Query(default=100, ge=1, le=500),
    ) -> OperationsSummary:
        return review_service.operations_summary(window_size=window_size)

    return router
