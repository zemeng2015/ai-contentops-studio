from __future__ import annotations

from collections.abc import Awaitable, Callable

from contentops_core.config_audit import config_audit
from contentops_core.config_templates import render_env_template
from contentops_core.diagnostics import (
    deployment_check,
    deployment_manifest,
    release_readiness,
    system_status,
)
from contentops_core.jobs import (
    JobExecutionListResponse,
    JobExecutionReport,
    JobExecutionSummary,
    JobExecutionTrendReport,
    JobRecoveryPlan,
    WorkerJobCatalogResponse,
    get_job_execution_report,
    job_execution_dir,
    job_execution_run_ids,
    job_execution_summary,
    job_execution_trends,
    job_recovery_plan,
    list_job_execution_reports,
    list_worker_job_catalog,
)
from contentops_core.models import (
    AuditEventListResponse,
    ConfigAuditReport,
    CostReportListResponse,
    DeploymentCheckReport,
    DeploymentManifest,
    IncidentReportListResponse,
    JobExecutionPublishRequest,
    JobExecutionReviewRequest,
    OperationsSummary,
    OpsTrendReport,
    PublishedContentListResponse,
    ReleaseApprovalListResponse,
    ReleaseApprovalRecord,
    ReleaseApprovalRequest,
    ReleaseEvidenceBundle,
    ReleaseGateListResponse,
    ReleaseGateReport,
    ReleaseReadinessReport,
    RetentionReport,
    ReviewBatchResult,
    RunStatus,
    ScorecardListResponse,
    SystemStatus,
)
from contentops_core.release_approvals import approve_release, list_release_approvals
from contentops_core.release_evidence import (
    build_release_evidence,
    create_release_evidence_archive,
)
from contentops_core.release_gate import list_release_gate_reports, release_gate
from contentops_core.repository import RunRepository
from contentops_core.review import ReviewService
from contentops_core.settings import Settings
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

ReadAccessDependency = Callable[[Request], Awaitable[None]]
OperatorDependency = Callable[[Request], Awaitable[None]]
StatusParser = Callable[[str], RunStatus | None]


def build_ops_router(
    *,
    settings: Settings,
    repository: RunRepository,
    review_service: ReviewService,
    require_read_access: ReadAccessDependency,
    require_operator: OperatorDependency,
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
        "/deployment-env-template",
        dependencies=[Depends(require_read_access)],
    )
    def get_deployment_env_template(
        profile: str = Query(default="production", pattern="^(local|production)$"),
    ) -> Response:
        return Response(
            content=render_env_template(profile),
            media_type="text/plain",
        )

    @router.get(
        "/config-audit",
        response_model=ConfigAuditReport,
        dependencies=[Depends(require_read_access)],
    )
    def get_config_audit(response: Response) -> ConfigAuditReport:
        report = config_audit(settings)
        if report.status == "fail":
            response.status_code = 409
        return report

    @router.get(
        "/deployment-check",
        response_model=DeploymentCheckReport,
        dependencies=[Depends(require_read_access)],
    )
    def get_deployment_check(
        profile: str = Query(default="production", pattern="^(local|production)$"),
        window_size: int = Query(default=100, ge=1, le=500),
    ) -> DeploymentCheckReport:
        operations = review_service.operations_summary(window_size=window_size)
        return deployment_check(settings, repository, operations, profile=profile)

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
        "/release-evidence",
        response_model=ReleaseEvidenceBundle,
        dependencies=[Depends(require_read_access)],
    )
    def get_release_evidence(
        window_size: int = Query(default=100, ge=1, le=500),
    ) -> ReleaseEvidenceBundle:
        return build_release_evidence(
            settings=settings,
            repository=repository,
            review_service=review_service,
            window_size=window_size,
        )

    @router.get(
        "/release-evidence/bundle",
        dependencies=[Depends(require_read_access)],
    )
    def get_release_evidence_bundle(
        window_size: int = Query(default=100, ge=1, le=500),
    ) -> FileResponse:
        bundle = build_release_evidence(
            settings=settings,
            repository=repository,
            review_service=review_service,
            window_size=window_size,
        )
        archive_path = settings.artifact_root / "release-evidence" / "release-evidence.zip"
        create_release_evidence_archive(bundle, archive_path)
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename=archive_path.name,
        )

    @router.get(
        "/release-approvals",
        response_model=ReleaseApprovalListResponse,
        dependencies=[Depends(require_read_access)],
    )
    def get_release_approvals(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> ReleaseApprovalListResponse:
        return list_release_approvals(settings.artifact_root, limit=limit, offset=offset)

    @router.post(
        "/release-approvals",
        response_model=ReleaseApprovalRecord,
        dependencies=[Depends(require_operator)],
    )
    def create_release_approval(request: ReleaseApprovalRequest) -> ReleaseApprovalRecord:
        try:
            return approve_release(
                settings=settings,
                repository=repository,
                review_service=review_service,
                request=request,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get(
        "/release-gate",
        response_model=ReleaseGateReport,
        dependencies=[Depends(require_read_access)],
    )
    def get_release_gate(
        response: Response,
        git_sha: str | None = Query(default=None),
        window_size: int = Query(default=100, ge=1, le=500),
        require_approval: bool = Query(default=True),
    ) -> ReleaseGateReport:
        report = release_gate(
            settings=settings,
            repository=repository,
            review_service=review_service,
            window_size=window_size,
            git_sha=git_sha,
            require_approval=require_approval,
        )
        if not report.can_deploy:
            response.status_code = 409
        return report

    @router.get(
        "/release-gates",
        response_model=ReleaseGateListResponse,
        dependencies=[Depends(require_read_access)],
    )
    def get_release_gates(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> ReleaseGateListResponse:
        return list_release_gate_reports(settings.artifact_root, limit=limit, offset=offset)

    @router.get(
        "/worker-jobs",
        response_model=WorkerJobCatalogResponse,
        dependencies=[Depends(require_read_access)],
    )
    def list_worker_jobs() -> WorkerJobCatalogResponse:
        return list_worker_job_catalog(settings.pipeline_dir)

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
        "/job-executions/trends",
        response_model=JobExecutionTrendReport,
        dependencies=[Depends(require_read_access)],
    )
    def get_job_execution_trends(
        days: int = Query(default=14, ge=1, le=90),
    ) -> JobExecutionTrendReport:
        return job_execution_trends(job_execution_dir(settings.artifact_root), days=days)

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
        "/job-executions/{execution_id}/summary",
        response_model=JobExecutionSummary,
        dependencies=[Depends(require_read_access)],
    )
    def get_job_execution_summary(execution_id: str) -> JobExecutionSummary:
        try:
            report = get_job_execution_report(
                job_execution_dir(settings.artifact_root),
                execution_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return job_execution_summary(report)

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

    @router.post(
        "/job-executions/{execution_id}/approve-runs",
        response_model=ReviewBatchResult,
        dependencies=[Depends(require_operator)],
    )
    def approve_job_execution_runs(
        execution_id: str,
        request: JobExecutionReviewRequest,
    ) -> ReviewBatchResult:
        try:
            report = get_job_execution_report(
                job_execution_dir(settings.artifact_root),
                execution_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return review_service.approve_many(
            job_execution_run_ids(report),
            reviewer=request.reviewer,
            notes=request.notes,
        )

    @router.post(
        "/job-executions/{execution_id}/publish-runs",
        response_model=ReviewBatchResult,
        dependencies=[Depends(require_operator)],
    )
    def publish_job_execution_runs(
        execution_id: str,
        request: JobExecutionPublishRequest,
    ) -> ReviewBatchResult:
        try:
            report = get_job_execution_report(
                job_execution_dir(settings.artifact_root),
                execution_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return review_service.publish_many(
            job_execution_run_ids(report),
            force=request.force,
        )

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

    @router.get(
        "/ops-trends",
        response_model=OpsTrendReport,
        dependencies=[Depends(require_read_access)],
    )
    def get_ops_trends(
        days: int = Query(default=14, ge=1, le=90),
        window_size: int = Query(default=500, ge=1, le=1000),
    ) -> OpsTrendReport:
        return review_service.operations_trends(days=days, window_size=window_size)

    return router
