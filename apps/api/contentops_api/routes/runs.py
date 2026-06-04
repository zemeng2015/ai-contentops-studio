from __future__ import annotations

from collections.abc import Awaitable, Callable

from contentops_core.models import (
    ApprovalRecord,
    ArtifactManifest,
    ArtifactMirrorRecord,
    AuditEvent,
    GenerationReceipt,
    NotificationDelivery,
    PublishReceipt,
    PublishRollbackResult,
    PublishVerificationReport,
    ReviewBatchRequest,
    ReviewBatchResult,
    RunComparison,
    RunCostReport,
    RunIncidentReport,
    RunListResponse,
    RunMetrics,
    RunRecord,
    RunRequest,
    RunScorecard,
    RunStatus,
    SourceAuditReport,
)
from contentops_core.pipeline import ContentOpsPipeline
from contentops_core.repository import RunRepository
from contentops_core.review import ReviewService
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

ReadAccessDependency = Callable[[Request], Awaitable[None]]
OperatorDependency = Callable[[Request], Awaitable[None]]
StatusParser = Callable[[str], RunStatus | None]


def build_runs_router(
    *,
    pipeline: ContentOpsPipeline,
    repository: RunRepository,
    review_service: ReviewService,
    require_read_access: ReadAccessDependency,
    require_operator: OperatorDependency,
    parse_status_filter: StatusParser,
) -> APIRouter:
    router = APIRouter()

    async def operator_dependency(request: Request) -> None:
        await require_operator(request)

    @router.post(
        "/runs",
        response_model=RunRecord,
        dependencies=[Depends(operator_dependency)],
    )
    def create_run(
        request: RunRequest,
    ) -> RunRecord:
        result = pipeline.run(request)
        return result.run


    @router.get(
        "/runs",
        response_model=list[RunRecord],
        dependencies=[Depends(require_read_access)],
    )
    def list_runs(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        status: str = Query(default=""),
        q: str = Query(default=""),
    ) -> list[RunRecord]:
        return repository.list(
            limit=limit,
            offset=offset,
            status=parse_status_filter(status),
            query=q,
        )


    @router.get(
        "/review-queue",
        response_model=RunListResponse,
        dependencies=[Depends(require_read_access)],
    )
    def review_queue(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        status: str = Query(default=RunStatus.NEEDS_REVIEW.value),
        q: str = Query(default=""),
    ) -> RunListResponse:
        status_filter = parse_status_filter(status)
        return RunListResponse(
            items=repository.list(
                limit=limit,
                offset=offset,
                status=status_filter,
                query=q,
            ),
            total=repository.count(status=status_filter, query=q),
            limit=limit,
            offset=offset,
        )



    @router.get(
        "/runs/{run_id}",
        response_model=RunRecord,
        dependencies=[Depends(require_read_access)],
    )
    def get_run(run_id: str) -> RunRecord:
        run = repository.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run


    @router.get(
        "/runs/{run_id}/artifacts",
        response_model=list[str],
        dependencies=[Depends(require_read_access)],
    )
    def list_artifacts(run_id: str) -> list[str]:
        try:
            return review_service.list_artifacts(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.get(
        "/runs/{run_id}/artifact-manifest",
        response_model=ArtifactManifest,
        dependencies=[Depends(require_read_access)],
    )
    def get_artifact_manifest(run_id: str) -> ArtifactManifest:
        try:
            return review_service.artifact_manifest(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.get(
        "/runs/{run_id}/s3-mirror-log",
        response_model=list[ArtifactMirrorRecord],
        dependencies=[Depends(require_read_access)],
    )
    def get_s3_mirror_log(run_id: str) -> list[ArtifactMirrorRecord]:
        try:
            return review_service.s3_mirror_log(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.get("/runs/{run_id}/bundle", dependencies=[Depends(require_read_access)])
    def get_run_bundle(run_id: str) -> FileResponse:
        try:
            bundle_path = review_service.create_bundle(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(
            bundle_path,
            media_type="application/zip",
            filename=bundle_path.name,
        )


    @router.get("/runs/{run_id}/homepage-handoff", dependencies=[Depends(require_read_access)])
    def get_homepage_handoff(run_id: str) -> FileResponse:
        try:
            bundle_path = review_service.create_homepage_handoff(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return FileResponse(
            bundle_path,
            media_type="application/zip",
            filename=bundle_path.name,
        )


    @router.get(
        "/runs/{run_id}/artifacts/{artifact_name}",
        dependencies=[Depends(require_read_access)],
    )
    def get_artifact(run_id: str, artifact_name: str) -> Response:
        try:
            content = review_service.read_artifact(run_id, artifact_name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        media_type = "application/json" if artifact_name.endswith(".json") else "text/plain"
        return Response(content=content, media_type=media_type)


    @router.post(
        "/runs/{run_id}/publish",
        response_model=RunRecord,
        dependencies=[Depends(operator_dependency)],
    )
    def publish_run(
        run_id: str,
        force: bool = False,
    ) -> RunRecord:
        try:
            return review_service.publish(run_id, force=force)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


    @router.post(
        "/runs/{run_id}/approve",
        response_model=RunRecord,
        dependencies=[Depends(operator_dependency)],
    )
    def approve_run(
        run_id: str,
        reviewer: str = "operator",
        notes: str = "",
    ) -> RunRecord:
        try:
            return review_service.approve(run_id, reviewer=reviewer, notes=notes)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


    @router.post(
        "/runs/{run_id}/reject",
        response_model=RunRecord,
        dependencies=[Depends(operator_dependency)],
    )
    def reject_run(
        run_id: str,
        reviewer: str = "operator",
        notes: str = "",
    ) -> RunRecord:
        try:
            return review_service.reject(run_id, reviewer=reviewer, notes=notes)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.post(
        "/review-queue/batch-approve",
        response_model=ReviewBatchResult,
        dependencies=[Depends(operator_dependency)],
    )
    def batch_approve_runs(
        request: ReviewBatchRequest,
    ) -> ReviewBatchResult:
        return review_service.approve_many(
            request.run_ids,
            reviewer=request.reviewer,
            notes=request.notes,
        )


    @router.post(
        "/review-queue/batch-reject",
        response_model=ReviewBatchResult,
        dependencies=[Depends(operator_dependency)],
    )
    def batch_reject_runs(
        request: ReviewBatchRequest,
    ) -> ReviewBatchResult:
        return review_service.reject_many(
            request.run_ids,
            reviewer=request.reviewer,
            notes=request.notes,
        )


    @router.get(
        "/runs/{run_id}/approval",
        response_model=ApprovalRecord | None,
        dependencies=[Depends(require_read_access)],
    )
    def get_approval(run_id: str) -> ApprovalRecord | None:
        try:
            return review_service.approval(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.get(
        "/runs/{run_id}/publish-receipt",
        response_model=PublishReceipt | None,
        dependencies=[Depends(require_read_access)],
    )
    def get_publish_receipt(run_id: str) -> PublishReceipt | None:
        try:
            return review_service.publish_receipt(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.get(
        "/runs/{run_id}/publish-verification",
        response_model=PublishVerificationReport,
        dependencies=[Depends(require_read_access)],
    )
    def get_publish_verification(run_id: str) -> PublishVerificationReport:
        try:
            return review_service.verify_publish(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


    @router.get(
        "/runs/{run_id}/generation-receipt",
        response_model=GenerationReceipt | None,
        dependencies=[Depends(require_read_access)],
    )
    def get_generation_receipt(run_id: str) -> GenerationReceipt | None:
        try:
            return review_service.generation_receipt(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.post(
        "/runs/{run_id}/rollback-publish",
        response_model=PublishRollbackResult,
        dependencies=[Depends(operator_dependency)],
    )
    def rollback_published_run(
        run_id: str,
        actor: str = "operator",
    ) -> PublishRollbackResult:
        try:
            return review_service.rollback_publish(run_id, actor=actor)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


    @router.get(
        "/runs/{run_id}/audit-log",
        response_model=list[AuditEvent],
        dependencies=[Depends(require_read_access)],
    )
    def get_audit_log(run_id: str) -> list[AuditEvent]:
        try:
            return review_service.audit_log(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.get(
        "/runs/{run_id}/notifications",
        response_model=list[NotificationDelivery],
        dependencies=[Depends(require_read_access)],
    )
    def get_notification_log(run_id: str) -> list[NotificationDelivery]:
        try:
            return review_service.notification_log(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.post(
        "/runs/{run_id}/rerun",
        response_model=RunRecord,
        dependencies=[Depends(operator_dependency)],
    )
    def rerun(
        run_id: str,
        publish: bool | None = None,
    ) -> RunRecord:
        try:
            request = review_service.request(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if publish is not None:
            request.publish = publish
        return pipeline.run(request).run


    @router.get("/runs/{run_id}/publish-plan", dependencies=[Depends(require_read_access)])
    def get_publish_plan(run_id: str) -> dict[str, object]:
        try:
            return review_service.publish_plan(run_id).model_dump(mode="json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.get(
        "/runs/{run_id}/metrics",
        response_model=RunMetrics,
        dependencies=[Depends(require_read_access)],
    )
    def get_run_metrics(run_id: str) -> RunMetrics:
        try:
            return review_service.metrics(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.get(
        "/runs/{run_id}/scorecard",
        response_model=RunScorecard,
        dependencies=[Depends(require_read_access)],
    )
    def get_run_scorecard(run_id: str) -> RunScorecard:
        try:
            return review_service.scorecard(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.get(
        "/runs/{run_id}/cost-report",
        response_model=RunCostReport,
        dependencies=[Depends(require_read_access)],
    )
    def get_run_cost_report(run_id: str) -> RunCostReport:
        try:
            return review_service.cost_report(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.get(
        "/runs/{run_id}/incident-report",
        response_model=RunIncidentReport,
        dependencies=[Depends(require_read_access)],
    )
    def get_run_incident_report(run_id: str) -> RunIncidentReport:
        try:
            return review_service.incident_report(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.get(
        "/runs/{run_id}/source-audit",
        response_model=SourceAuditReport,
        dependencies=[Depends(require_read_access)],
    )
    def get_source_audit(run_id: str) -> SourceAuditReport:
        try:
            raw = review_service.read_artifact(run_id, "source-audit.json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return SourceAuditReport.model_validate_json(raw)


    @router.get(
        "/runs/{base_run_id}/compare/{candidate_run_id}",
        response_model=RunComparison,
        dependencies=[Depends(require_read_access)],
    )
    def compare_runs(base_run_id: str, candidate_run_id: str) -> RunComparison:
        try:
            return review_service.compare(base_run_id, candidate_run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
