from __future__ import annotations

import json
import mimetypes
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import TypeVar
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from contentops_publishing.static_site import Publisher
from pydantic import BaseModel

from contentops_core.artifacts import (
    failed_s3_mirror_records,
    mirror_files_to_s3,
    write_s3_mirror_log,
)
from contentops_core.metrics import MetricsService
from contentops_core.models import (
    ApprovalDecision,
    ApprovalRecord,
    ArtifactManifest,
    ArtifactMetadata,
    ArtifactMirrorRecord,
    AuditEvent,
    AuditEventListResponse,
    CostReportListResponse,
    Draft,
    EvaluationReport,
    GenerationReceipt,
    IncidentReportListResponse,
    IncidentSeverity,
    NotificationDelivery,
    OperationsSummary,
    OpsTrendBucket,
    OpsTrendReport,
    PublishedContentItem,
    PublishedContentListResponse,
    PublishFileChange,
    PublishPlan,
    PublishReceipt,
    PublishRecoveryExecutionResult,
    PublishRecoveryFileAction,
    PublishRecoveryPlan,
    PublishRollbackResult,
    PublishVerificationItem,
    PublishVerificationReport,
    ResearchPacket,
    RetentionArchiveListResponse,
    RetentionArchiveRecord,
    RetentionCandidate,
    RetentionReport,
    ReviewActionResult,
    ReviewBatchResult,
    RunComparison,
    RunCostReport,
    RunIncidentReport,
    RunIncidentSignal,
    RunMetrics,
    RunRecord,
    RunRequest,
    RunScorecard,
    RunStatus,
    ScorecardListResponse,
    Source,
    SourceOverlap,
    SourceReviewDecision,
    SourceReviewRecord,
    SourceReviewRequest,
)
from contentops_core.notifications import LocalNotificationPublisher, NotificationPublisher
from contentops_core.repository import RunRepository

T = TypeVar("T", bound=BaseModel)


class ReviewService:
    def __init__(
        self,
        repository: RunRepository,
        publisher: Publisher,
        notifier: NotificationPublisher | None = None,
        latency_slo_ms: int = 120000,
        min_source_count: int = 1,
        token_budget_per_run: int = 12000,
        model: str = "template",
        artifact_root: Path | None = None,
        artifact_store_provider: str = "local",
        artifact_s3_bucket: str = "",
        artifact_s3_prefix: str = "contentops-artifacts",
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.notifier = notifier or LocalNotificationPublisher()
        self.latency_slo_ms = latency_slo_ms
        self.min_source_count = min_source_count
        self.token_budget_per_run = token_budget_per_run
        self.model = model
        self.artifact_root = artifact_root or Path("artifacts")
        self.artifact_store_provider = artifact_store_provider
        self.artifact_s3_bucket = artifact_s3_bucket
        self.artifact_s3_prefix = artifact_s3_prefix
        self.metrics_service = MetricsService()

    def list_artifacts(self, run_id: str) -> list[str]:
        run = self._get_run(run_id)
        return sorted(path.name for path in run.artifact_dir.iterdir() if path.is_file())

    def artifact_manifest(self, run_id: str) -> ArtifactManifest:
        run = self._get_run(run_id)
        artifacts: dict[str, ArtifactMetadata] = {}
        for path in sorted(run.artifact_dir.iterdir()):
            if not path.is_file():
                continue
            stat = path.stat()
            media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            artifacts[path.name] = ArtifactMetadata(
                name=path.name,
                size_bytes=stat.st_size,
                media_type=media_type,
                sha256=sha256(path.read_bytes()).hexdigest(),
                updated_at=datetime.fromtimestamp(stat.st_mtime, UTC),
            )
        return ArtifactManifest(
            run_id=run.id,
            artifacts=artifacts,
            metadata={
                "artifact_dir": str(run.artifact_dir),
                "status": run.status.value,
            },
        )

    def read_artifact(self, run_id: str, artifact_name: str) -> str:
        run = self._get_run(run_id)
        artifact_path = self._safe_artifact_path(run.artifact_dir, artifact_name)
        return artifact_path.read_text(encoding="utf-8")

    def source_reviews(self, run_id: str) -> list[SourceReviewRecord]:
        run = self._get_run(run_id)
        return self._load_source_reviews(run)

    def review_source(
        self,
        run_id: str,
        request: SourceReviewRequest,
    ) -> SourceReviewRecord:
        run = self._get_run(run_id)
        sources = self._load_sources(run)
        source_by_key = {self._source_key(source): source for source in sources}
        normalized_key = request.source_key.strip().casefold()
        source = source_by_key.get(normalized_key)
        if source is None:
            raise ValueError(f"Source not found for key: {request.source_key}")
        record = SourceReviewRecord(
            source_key=normalized_key,
            source_title=source.title,
            decision=request.decision,
            reviewer=request.reviewer,
            notes=request.notes,
        )
        reviews = [
            existing
            for existing in self.source_reviews(run_id)
            if existing.source_key != normalized_key
        ]
        reviews.append(record)
        self._write_source_reviews(run, reviews)
        self._record_audit_event(
            run,
            AuditEvent(
                run_id=run_id,
                action="source_review",
                actor=request.reviewer,
                fields={
                    "source_key": normalized_key,
                    "source_title": source.title,
                    "decision": request.decision.value,
                    "notes": request.notes,
                },
            ),
        )
        return record

    def s3_mirror_log(self, run_id: str) -> list[ArtifactMirrorRecord]:
        run = self._get_run(run_id)
        path = run.artifact_dir / "s3-mirror-log.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [ArtifactMirrorRecord.model_validate(item) for item in data]

    def create_bundle(self, run_id: str, output_path: Path | None = None) -> Path:
        run = self._get_run(run_id)
        target = output_path or run.artifact_dir / f"{run.id}-bundle.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        artifact_paths = [
            path
            for path in sorted(run.artifact_dir.iterdir())
            if path.is_file()
            and path.resolve() != target.resolve()
            and not path.name.endswith(".zip")
        ]
        manifest = {
            "run": run.model_dump(mode="json"),
            "artifacts": {
                path.name: {
                    "size_bytes": path.stat().st_size,
                    "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    "sha256": sha256(path.read_bytes()).hexdigest(),
                }
                for path in artifact_paths
            },
            "created_at": datetime.now(UTC).isoformat(),
        }
        with ZipFile(target, "w", compression=ZIP_DEFLATED) as bundle:
            bundle.writestr(
                "bundle-manifest.json",
                json.dumps(manifest, indent=2),
            )
            for path in artifact_paths:
                bundle.write(path, f"artifacts/{path.name}")
        return target

    def create_homepage_handoff(self, run_id: str, output_path: Path | None = None) -> Path:
        run = self._get_run(run_id)
        draft = self._load_json(run, "draft.json", Draft)
        report = self._load_json(run, "eval-report.json", EvaluationReport)
        plan = self.publisher.plan(run, draft, report)
        if plan.provider != "homepage":
            raise ValueError("Homepage handoff requires CONTENTOPS_PUBLISHER_PROVIDER=homepage.")
        target = output_path or run.artifact_dir / f"{run.id}-homepage-handoff.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        artifact_names = [
            "draft.md",
            "draft.json",
            "eval-report.json",
            "final.html",
            "scorecard.json",
            "source-audit.json",
        ]
        artifact_paths = [
            run.artifact_dir / artifact_name
            for artifact_name in artifact_names
            if (run.artifact_dir / artifact_name).is_file()
        ]
        commands = plan.metadata.get("suggested_commands", [])
        manifest = {
            "bundle_type": "homepage_handoff",
            "run": run.model_dump(mode="json"),
            "publish_plan": plan.model_dump(mode="json"),
            "created_at": datetime.now(UTC).isoformat(),
            "artifacts": {
                path.name: {
                    "size_bytes": path.stat().st_size,
                    "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    "sha256": sha256(path.read_bytes()).hexdigest(),
                }
                for path in artifact_paths
            },
        }
        with ZipFile(target, "w", compression=ZIP_DEFLATED) as bundle:
            bundle.writestr("handoff-manifest.json", json.dumps(manifest, indent=2))
            bundle.writestr("publish-plan.json", plan.model_dump_json(indent=2))
            bundle.writestr("suggested-git-commands.txt", _command_text(commands))
            for path in artifact_paths:
                bundle.write(path, f"artifacts/{path.name}")
        return target

    def publish(self, run_id: str, force: bool = False) -> RunRecord:
        run = self._get_run(run_id)
        draft = self._load_json(run, "draft.json", Draft)
        report = self._load_json(run, "eval-report.json", EvaluationReport)
        approval = self.approval(run_id)
        previous_status = run.status
        if run.status == RunStatus.NEEDS_REVIEW and approval is None and not force:
            raise ValueError("Run must be approved before publishing. Use force=true to override.")
        if approval is not None and approval.decision == ApprovalDecision.REJECTED and not force:
            raise ValueError("Run was rejected. Use force=true to override.")
        if not report.publish_ready and not force:
            raise ValueError("Run is not publish-ready. Use force=true to override.")
        plan = self.publisher.plan(run, draft, report)
        if not plan.ready and not force:
            raise ValueError("; ".join(plan.warnings))
        before_snapshot = self._snapshot_publish_targets(plan)
        backups = self._backup_publish_targets(run, plan)
        run.touch(RunStatus.PUBLISHING)
        self.repository.save(run)
        run.published_url = self.publisher.publish(run, draft, report)
        after_snapshot = self._snapshot_publish_targets(plan)
        file_changes = self._publish_file_changes(
            plan,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            backups=backups,
        )
        self._write_publish_receipt(
            run,
            PublishReceipt(
                run_id=run_id,
                provider=plan.provider,
                url=run.published_url,
                plan_items=plan.items,
                plan_metadata=plan.metadata,
                file_changes=file_changes,
                approval=approval,
                force=force,
            ),
        )
        run.touch(RunStatus.PUBLISHED)
        self.repository.save(run)
        actor = approval.reviewer if approval is not None else "force"
        self._record_audit_event(
            run,
            AuditEvent(
                run_id=run_id,
                action="publish",
                actor=actor,
                previous_status=previous_status,
                new_status=run.status,
                fields={
                    "force": force,
                    "provider": plan.provider,
                    "url": run.published_url,
                    "changed_files": len(file_changes),
                },
            ),
        )
        return run

    def approve(self, run_id: str, reviewer: str = "operator", notes: str = "") -> RunRecord:
        run = self._get_run(run_id)
        previous_status = run.status
        report = self._load_json(run, "eval-report.json", EvaluationReport)
        if not report.publish_ready:
            raise ValueError("Run is not publish-ready and cannot be approved.")
        scorecard = self._scorecard_for_run(run)
        if not scorecard.overall_pass:
            raise ValueError(
                "Run scorecard did not pass: " + "; ".join(scorecard.warnings)
            )
        cost_report = self._cost_report_for_run(run)
        if not cost_report.budget_pass:
            raise ValueError(
                "Run token budget did not pass: " + "; ".join(cost_report.warnings)
            )
        plan = self.publish_plan(run_id)
        if not plan.ready:
            raise ValueError("; ".join(plan.warnings))
        self._write_approval(
            run,
            ApprovalRecord(
                run_id=run_id,
                decision=ApprovalDecision.APPROVED,
                reviewer=reviewer,
                notes=notes,
            ),
        )
        run.touch(RunStatus.APPROVED)
        self.repository.save(run)
        self._record_audit_event(
            run,
            AuditEvent(
                run_id=run_id,
                action="approve",
                actor=reviewer,
                previous_status=previous_status,
                new_status=run.status,
                fields={"notes": notes},
            ),
        )
        return run

    def approve_many(
        self,
        run_ids: list[str],
        reviewer: str = "operator",
        notes: str = "",
    ) -> ReviewBatchResult:
        return self._batch_review(
            action="approve",
            run_ids=run_ids,
            reviewer=reviewer,
            notes=notes,
        )

    def reject(self, run_id: str, reviewer: str = "operator", notes: str = "") -> RunRecord:
        run = self._get_run(run_id)
        previous_status = run.status
        self._write_approval(
            run,
            ApprovalRecord(
                run_id=run_id,
                decision=ApprovalDecision.REJECTED,
                reviewer=reviewer,
                notes=notes,
            ),
        )
        run.touch(RunStatus.REJECTED)
        self.repository.save(run)
        self._record_audit_event(
            run,
            AuditEvent(
                run_id=run_id,
                action="reject",
                actor=reviewer,
                previous_status=previous_status,
                new_status=run.status,
                fields={"notes": notes},
            ),
        )
        return run

    def reject_many(
        self,
        run_ids: list[str],
        reviewer: str = "operator",
        notes: str = "",
    ) -> ReviewBatchResult:
        return self._batch_review(
            action="reject",
            run_ids=run_ids,
            reviewer=reviewer,
            notes=notes,
        )

    def publish_many(
        self,
        run_ids: list[str],
        force: bool = False,
    ) -> ReviewBatchResult:
        results: list[ReviewActionResult] = []
        for run_id in run_ids:
            try:
                run = self.publish(run_id, force=force)
            except (FileNotFoundError, ValueError) as exc:
                results.append(
                    ReviewActionResult(
                        run_id=run_id,
                        action="publish",
                        status="failed",
                        error=str(exc),
                    )
                )
                continue
            results.append(
                ReviewActionResult(
                    run_id=run_id,
                    action="publish",
                    status="ok",
                    new_status=run.status,
                )
            )
        return ReviewBatchResult(action="publish", results=results)

    def audit_log(self, run_id: str) -> list[AuditEvent]:
        run = self._get_run(run_id)
        path = run.artifact_dir / "audit-log.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [AuditEvent.model_validate(item) for item in data]

    def audit_events(
        self,
        limit: int = 20,
        offset: int = 0,
        status: RunStatus | None = None,
        query: str = "",
        action: str = "",
    ) -> AuditEventListResponse:
        events = self._audit_events(status=status, query=query, action=action)
        page = events[offset : offset + limit]
        action_counts: dict[str, int] = {}
        for event in events:
            action_counts[event.action] = action_counts.get(event.action, 0) + 1
        return AuditEventListResponse(
            items=page,
            total=len(events),
            limit=limit,
            offset=offset,
            action_counts=action_counts,
        )

    def notification_log(self, run_id: str) -> list[NotificationDelivery]:
        run = self._get_run(run_id)
        path = run.artifact_dir / "notification-log.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [NotificationDelivery.model_validate(item) for item in data]

    def approval(self, run_id: str) -> ApprovalRecord | None:
        run = self._get_run(run_id)
        path = run.artifact_dir / "approval.json"
        if not path.exists():
            return None
        return ApprovalRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def publish_receipt(self, run_id: str) -> PublishReceipt | None:
        run = self._get_run(run_id)
        path = run.artifact_dir / "publish-receipt.json"
        if not path.exists():
            return None
        return PublishReceipt.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def verify_publish(self, run_id: str) -> PublishVerificationReport:
        run = self._get_run(run_id)
        receipt = self.publish_receipt(run_id)
        if receipt is None:
            raise ValueError("No publish receipt recorded.")
        items = [self._verify_publish_change(change) for change in receipt.file_changes]
        report = PublishVerificationReport(
            run_id=run_id,
            provider=receipt.provider,
            url=receipt.url,
            verified=bool(items) and all(item.matches_receipt for item in items),
            items=items,
        )
        self._write_publish_verification(run, report)
        return report

    def publish_recovery_plan(self, run_id: str) -> PublishRecoveryPlan:
        run = self._get_run(run_id)
        report = self.verify_publish(run_id)
        file_actions = [_publish_recovery_file_action(item) for item in report.items]
        if report.verified:
            plan = PublishRecoveryPlan(
                run_id=run_id,
                provider=report.provider,
                url=report.url,
                verified=True,
                recommended_action="none",
                runnable=False,
                blocked_reason="Published files already match the publish receipt.",
                file_actions=file_actions,
                steps=[
                    "No recovery is required.",
                    "Keep `publish-verification.json` with the release evidence.",
                ],
            )
        else:
            plan = PublishRecoveryPlan(
                run_id=run_id,
                provider=report.provider,
                url=report.url,
                verified=False,
                recommended_action="manual_restore_or_republish",
                runnable=True,
                file_actions=file_actions,
                steps=[
                    f"Inspect `publish-verification.json` for run `{run_id}`.",
                    (
                        "Restore target files to the expected receipt hashes or republish "
                        "approved content."
                    ),
                    f"Run `contentops verify-publish {run_id}` until verification passes.",
                    (
                        f"Use `contentops rollback-publish {run_id} --actor <name>` "
                        "if the published change should be removed."
                    ),
                    "Regenerate release evidence and rerun the release gate.",
                ],
            )
        self._write_publish_recovery_plan(run, plan)
        return plan

    def execute_publish_recovery(
        self,
        run_id: str,
        *,
        action: str,
        actor: str = "operator",
        notes: str = "",
    ) -> PublishRecoveryExecutionResult:
        normalized_action = action.strip().casefold()
        if normalized_action != "rollback":
            raise ValueError("Unsupported publish recovery action. Supported actions: rollback.")
        plan = self.publish_recovery_plan(run_id)
        if not plan.runnable:
            raise ValueError(plan.blocked_reason or "Publish recovery plan is not runnable.")
        rollback = self.rollback_publish(run_id, actor=actor)
        result = PublishRecoveryExecutionResult(
            run_id=run_id,
            action=normalized_action,
            actor=actor,
            status="completed",
            plan=plan,
            rollback=rollback,
            message=(
                notes
                or "Publish recovery rollback completed; regenerate release evidence next."
            ),
        )
        run = self._get_run(run_id)
        self._write_publish_recovery_execution(run, result)
        return result

    def published_content(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> PublishedContentListResponse:
        runs = self.repository.list(
            limit=limit,
            offset=offset,
            status=RunStatus.PUBLISHED,
        )
        items = [self._published_content_item(run) for run in runs if run.published_url]
        return PublishedContentListResponse(
            items=items,
            total=self.repository.count(status=RunStatus.PUBLISHED),
            limit=limit,
            offset=offset,
        )

    def rollback_publish(
        self,
        run_id: str,
        actor: str = "operator",
    ) -> PublishRollbackResult:
        run = self._get_run(run_id)
        receipt = self.publish_receipt(run_id)
        if receipt is None:
            raise ValueError("No publish receipt recorded.")
        previous_status = run.status
        result = self._restore_publish_changes(run, receipt)
        self._write_publish_rollback(run, result)
        if result.errors:
            raise ValueError("; ".join(result.errors))
        run.published_url = None
        run.touch(RunStatus.APPROVED if receipt.approval is not None else RunStatus.NEEDS_REVIEW)
        self.repository.save(run)
        self._record_audit_event(
            run,
            AuditEvent(
                run_id=run_id,
                action="rollback_publish",
                actor=actor,
                previous_status=previous_status,
                new_status=run.status,
                fields={
                    "restored_files": len(result.restored_files),
                    "deleted_files": len(result.deleted_files),
                    "skipped_files": len(result.skipped_files),
                },
            ),
        )
        return result

    def publish_plan(self, run_id: str) -> PublishPlan:
        run = self._get_run(run_id)
        draft = self._load_json(run, "draft.json", Draft)
        report = self._load_json(run, "eval-report.json", EvaluationReport)
        return self.publisher.plan(run, draft, report)

    def metrics(self, run_id: str) -> RunMetrics:
        return self.metrics_service.run_metrics(self._get_run(run_id))

    def scorecard(self, run_id: str) -> RunScorecard:
        return self._scorecard_for_run(self._get_run(run_id))

    def scorecards(
        self,
        limit: int = 20,
        offset: int = 0,
        status: RunStatus | None = None,
        query: str = "",
    ) -> ScorecardListResponse:
        runs = self.repository.list(limit=limit, offset=offset, status=status, query=query)
        items = [self._scorecard_for_run(run) for run in runs]
        evaluated = [item for item in items if item.quality_pass is not None]
        passing = sum(1 for item in evaluated if item.quality_pass)
        durations = [
            item.total_duration_ms for item in items if item.total_duration_ms is not None
        ]
        return ScorecardListResponse(
            items=items,
            total=self.repository.count(status=status, query=query),
            limit=limit,
            offset=offset,
            quality_pass_rate=round(passing / len(evaluated), 3) if evaluated else 0.0,
            avg_duration_ms=round(sum(durations) / len(durations)) if durations else None,
        )

    def request(self, run_id: str) -> RunRequest:
        return self._load_json(self._get_run(run_id), "request.json", RunRequest)

    def cost_report(self, run_id: str) -> RunCostReport:
        return self._cost_report_for_run(self._get_run(run_id))

    def generation_receipt(self, run_id: str) -> GenerationReceipt | None:
        run = self._get_run(run_id)
        return self._load_optional_json(run, "generation-receipt.json", GenerationReceipt)

    def cost_reports(
        self,
        limit: int = 20,
        offset: int = 0,
        status: RunStatus | None = None,
        query: str = "",
    ) -> CostReportListResponse:
        runs = self.repository.list(limit=limit, offset=offset, status=status, query=query)
        items = [self._cost_report_for_run(run) for run in runs]
        passing = sum(1 for item in items if item.budget_pass)
        return CostReportListResponse(
            items=items,
            total=self.repository.count(status=status, query=query),
            limit=limit,
            offset=offset,
            budget_pass_rate=round(passing / len(items), 3) if items else 0.0,
            estimated_total_tokens=sum(item.estimated_total_tokens for item in items),
        )

    def incident_report(self, run_id: str) -> RunIncidentReport:
        return self._incident_report_for_run(self._get_run(run_id))

    def incident_reports(
        self,
        limit: int = 20,
        offset: int = 0,
        status: RunStatus | None = None,
        query: str = "",
    ) -> IncidentReportListResponse:
        runs = self.repository.list(limit=limit, offset=offset, status=status, query=query)
        items = [self._incident_report_for_run(run) for run in runs]
        return IncidentReportListResponse(
            items=items,
            total=self.repository.count(status=status, query=query),
            limit=limit,
            offset=offset,
            action_required=sum(1 for item in items if item.requires_action),
        )

    def operations_summary(self, window_size: int = 100) -> OperationsSummary:
        window_size = max(1, window_size)
        runs = self.repository.list(limit=window_size)
        scorecards = [self._scorecard_for_run(run) for run in runs]
        cost_reports = [self._cost_report_for_run(run) for run in runs]
        incident_reports = [self._incident_report_for_run(run) for run in runs]
        durations = [
            item.total_duration_ms
            for item in scorecards
            if item.total_duration_ms is not None
        ]
        return OperationsSummary(
            window_size=window_size,
            total_runs=self.repository.count(),
            status_counts={
                status.value: self.repository.count(status=status)
                for status in RunStatus
            },
            review_queue_depth=self.repository.count(status=RunStatus.NEEDS_REVIEW),
            approved_ready_count=self.repository.count(status=RunStatus.APPROVED),
            published_count=self.repository.count(status=RunStatus.PUBLISHED),
            failed_count=self.repository.count(status=RunStatus.FAILED),
            action_required_incidents=sum(
                1 for item in incident_reports if item.requires_action
            ),
            critical_incidents=sum(
                1
                for item in incident_reports
                if item.severity == IncidentSeverity.CRITICAL
            ),
            warning_incidents=sum(
                1
                for item in incident_reports
                if item.severity == IncidentSeverity.WARNING
            ),
            quality_pass_rate=_pass_rate(
                item.overall_pass for item in scorecards if item.overall_pass is not None
            ),
            budget_pass_rate=_pass_rate(item.budget_pass for item in cost_reports),
            avg_duration_ms=(
                int(sum(durations) / len(durations)) if durations else None
            ),
            estimated_total_tokens=sum(
                item.estimated_total_tokens for item in cost_reports
            ),
        )

    def operations_trends(self, days: int = 14, window_size: int = 500) -> OpsTrendReport:
        days = max(1, days)
        window_size = max(1, window_size)
        runs = self.repository.list(limit=window_size)
        today = datetime.now(UTC).date()
        bucket_keys = [(today - timedelta(days=offset)).isoformat() for offset in range(days)]
        buckets_by_date: dict[str, list[RunRecord]] = {key: [] for key in bucket_keys}
        for run in runs:
            date_key = _ensure_utc(run.updated_at).date().isoformat()
            if date_key in buckets_by_date:
                buckets_by_date[date_key].append(run)
        buckets = [
            self._ops_trend_bucket(date_key, buckets_by_date[date_key])
            for date_key in reversed(bucket_keys)
        ]
        return OpsTrendReport(
            days=days,
            window_size=window_size,
            buckets=buckets,
            summary=self.operations_summary(window_size=window_size),
        )

    def retention_report(
        self,
        retention_days: int = 90,
        limit: int = 100,
    ) -> RetentionReport:
        retention_days = max(0, retention_days)
        limit = max(1, limit)
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        runs = self.repository.list(limit=limit)
        candidates: list[RetentionCandidate] = []
        total_size = 0
        for run in runs:
            artifact_count, size_bytes = _artifact_dir_stats(run.artifact_dir)
            total_size += size_bytes
            updated_at = _ensure_utc(run.updated_at)
            if updated_at <= cutoff:
                candidates.append(
                    RetentionCandidate(
                        run_id=run.id,
                        status=run.status,
                        topic=run.topic,
                        updated_at=updated_at,
                        artifact_dir=str(run.artifact_dir),
                        artifact_count=artifact_count,
                        size_bytes=size_bytes,
                        reason=f"Run has not changed for at least {retention_days} day(s).",
                    )
                )
        return RetentionReport(
            retention_days=retention_days,
            total_runs_scanned=len(runs),
            total_size_bytes=total_size,
            candidate_count=len(candidates),
            candidate_size_bytes=sum(item.size_bytes for item in candidates),
            candidates=candidates,
        )

    def retention_archive(
        self,
        retention_days: int = 90,
        limit: int = 100,
        output_dir: Path | None = None,
        dry_run: bool = False,
    ) -> RetentionArchiveRecord:
        report = self.retention_report(retention_days=retention_days, limit=limit)
        target_dir = output_dir or self.artifact_root / "retention-archives"
        target_dir.mkdir(parents=True, exist_ok=True)
        archive_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        archive_path = target_dir / f"retention-{archive_id}.zip"
        manifest = {
            "archive_id": archive_id,
            "retention_report": report.model_dump(mode="json"),
            "dry_run": dry_run,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if not dry_run:
            with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr(
                    "retention-archive-manifest.json",
                    json.dumps(manifest, indent=2),
                )
                for candidate in report.candidates:
                    artifact_dir = Path(candidate.artifact_dir)
                    for path in sorted(artifact_dir.rglob("*")):
                        if not path.is_file():
                            continue
                        relative_path = path.relative_to(artifact_dir)
                        archive.write(path, f"runs/{candidate.run_id}/{relative_path.as_posix()}")
            archive_sha = sha256(archive_path.read_bytes()).hexdigest()
        else:
            archive_path = target_dir / f"retention-{archive_id}-dry-run.json"
            archive_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            archive_sha = sha256(archive_path.read_bytes()).hexdigest()
        record = RetentionArchiveRecord(
            archive_id=archive_id,
            retention_days=report.retention_days,
            run_ids=[candidate.run_id for candidate in report.candidates],
            candidate_count=report.candidate_count,
            archived_size_bytes=report.candidate_size_bytes,
            archive_path=str(archive_path),
            sha256=archive_sha,
            dry_run=dry_run,
        )
        record_path = target_dir / f"{archive_id}-retention-archive.json"
        record_path.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
        self._mirror_retention_archive_to_s3(
            record=record,
            archive_path=archive_path,
            record_path=record_path,
            target_dir=target_dir,
        )
        return record

    def _mirror_retention_archive_to_s3(
        self,
        *,
        record: RetentionArchiveRecord,
        archive_path: Path,
        record_path: Path,
        target_dir: Path,
    ) -> None:
        if self.artifact_store_provider != "s3":
            return
        if not self.artifact_s3_bucket:
            raise ValueError("CONTENTOPS_ARTIFACT_S3_BUCKET is required for S3 archive mirroring.")
        records = mirror_files_to_s3(
            [archive_path, record_path],
            bucket=self.artifact_s3_bucket,
            prefix=self.artifact_s3_prefix,
            collection_id=f"retention-archives/{record.archive_id}",
        )
        mirror_log_path = target_dir / "s3-mirror-log.json"
        write_s3_mirror_log(records, mirror_log_path)
        failures = failed_s3_mirror_records(records)
        record.s3_mirror_status = "failed" if failures else "mirrored"
        record.s3_mirror_log_path = str(mirror_log_path)
        record.s3_mirror_failures = len(failures)
        record_path.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
        if failures:
            details = "; ".join(
                f"{item.artifact_name}: {item.error or 'mirror failed'}" for item in failures
            )
            raise RuntimeError(f"Failed to mirror retention archive to S3: {details}")

    def retention_archives(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> RetentionArchiveListResponse:
        limit = max(1, limit)
        offset = max(0, offset)
        archive_dir = self.artifact_root / "retention-archives"
        records: list[RetentionArchiveRecord] = []
        for path in sorted(archive_dir.glob("*-retention-archive.json"), reverse=True):
            try:
                records.append(
                    RetentionArchiveRecord.model_validate_json(
                        path.read_text(encoding="utf-8")
                    )
                )
            except ValueError:
                continue
        page = records[offset : offset + limit]
        return RetentionArchiveListResponse(
            items=page,
            total=len(records),
            limit=limit,
            offset=offset,
        )

    def _ops_trend_bucket(self, date_key: str, runs: list[RunRecord]) -> OpsTrendBucket:
        scorecards = [self._scorecard_for_run(run) for run in runs]
        cost_reports = [self._cost_report_for_run(run) for run in runs]
        incident_reports = [self._incident_report_for_run(run) for run in runs]
        durations = [
            item.total_duration_ms
            for item in scorecards
            if item.total_duration_ms is not None
        ]
        return OpsTrendBucket(
            date=date_key,
            run_count=len(runs),
            published_count=sum(1 for run in runs if run.status == RunStatus.PUBLISHED),
            failed_count=sum(1 for run in runs if run.status == RunStatus.FAILED),
            review_queue_count=sum(1 for run in runs if run.status == RunStatus.NEEDS_REVIEW),
            action_required_incidents=sum(
                1 for item in incident_reports if item.requires_action
            ),
            quality_pass_rate=_pass_rate(
                item.overall_pass for item in scorecards if item.overall_pass is not None
            ),
            budget_pass_rate=_pass_rate(item.budget_pass for item in cost_reports),
            avg_duration_ms=(
                int(sum(durations) / len(durations)) if durations else None
            ),
            estimated_total_tokens=sum(
                item.estimated_total_tokens for item in cost_reports
            ),
        )

    def compare(self, base_run_id: str, candidate_run_id: str) -> RunComparison:
        base = self._get_run(base_run_id)
        candidate = self._get_run(candidate_run_id)
        base_metrics = self.metrics_service.run_metrics(base)
        candidate_metrics = self.metrics_service.run_metrics(candidate)
        base_report = self._load_json(base, "eval-report.json", EvaluationReport)
        candidate_report = self._load_json(candidate, "eval-report.json", EvaluationReport)
        duration_delta = None
        if (
            base_metrics.total_duration_ms is not None
            and candidate_metrics.total_duration_ms is not None
        ):
            duration_delta = candidate_metrics.total_duration_ms - base_metrics.total_duration_ms
        eval_deltas: dict[str, float | None] = {
            "groundedness": round(candidate_report.groundedness - base_report.groundedness, 3),
            "source_coverage": round(
                candidate_report.source_coverage - base_report.source_coverage, 3
            ),
            "source_quality": round(
                candidate_report.source_quality - base_report.source_quality, 3
            ),
            "career_relevance": round(
                candidate_report.career_relevance - base_report.career_relevance, 3
            ),
            "technical_depth": round(
                candidate_report.technical_depth - base_report.technical_depth, 3
            ),
        }
        source_delta = candidate_metrics.source_count - base_metrics.source_count
        publish_ready_changed = candidate_metrics.publish_ready != base_metrics.publish_ready
        source_overlap = self._source_overlap(
            self._load_sources(base),
            self._load_sources(candidate),
        )
        summary = [
            f"Topic match: {str(base.topic.casefold() == candidate.topic.casefold()).lower()}.",
            f"Source count delta: {source_delta:+d}.",
            f"Shared sources: {source_overlap.shared_count}.",
            f"Publish readiness changed: {str(publish_ready_changed).lower()}.",
        ]
        if duration_delta is not None:
            summary.append(f"Duration delta: {duration_delta:+d}ms.")
        for score, delta in eval_deltas.items():
            summary.append(f"{score} delta: {delta:+.3f}.")
        return RunComparison(
            base_run_id=base_run_id,
            candidate_run_id=candidate_run_id,
            base_topic=base.topic,
            candidate_topic=candidate.topic,
            same_topic=base.topic.casefold() == candidate.topic.casefold(),
            duration_delta_ms=duration_delta,
            source_count_delta=source_delta,
            publish_ready_changed=publish_ready_changed,
            evaluation_deltas=eval_deltas,
            source_overlap=source_overlap,
            summary=summary,
        )

    def _get_run(self, run_id: str) -> RunRecord:
        run = self.repository.get(run_id)
        if run is None:
            raise FileNotFoundError(f"Run not found: {run_id}")
        return run

    def _batch_review(
        self,
        action: str,
        run_ids: list[str],
        reviewer: str,
        notes: str,
    ) -> ReviewBatchResult:
        results: list[ReviewActionResult] = []
        for run_id in run_ids:
            try:
                if action == "approve":
                    run = self.approve(run_id, reviewer=reviewer, notes=notes)
                else:
                    run = self.reject(run_id, reviewer=reviewer, notes=notes)
            except (FileNotFoundError, ValueError) as exc:
                results.append(
                    ReviewActionResult(
                        run_id=run_id,
                        action=action,
                        status="failed",
                        error=str(exc),
                    )
                )
                continue
            results.append(
                ReviewActionResult(
                    run_id=run_id,
                    action=action,
                    status="ok",
                    new_status=run.status,
                )
            )
        return ReviewBatchResult(action=action, results=results)

    @staticmethod
    def _safe_artifact_path(artifact_dir: Path, artifact_name: str) -> Path:
        path = (artifact_dir / artifact_name).resolve()
        root = artifact_dir.resolve()
        if root not in path.parents and path != root:
            raise ValueError("Artifact path escapes the run directory.")
        if not path.is_file():
            raise FileNotFoundError(f"Artifact not found: {artifact_name}")
        return path

    @staticmethod
    def _load_json(run: RunRecord, artifact_name: str, model: type[T]) -> T:
        path = run.artifact_dir / artifact_name
        if not path.exists():
            raise FileNotFoundError(f"Required artifact not found: {artifact_name}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return model.model_validate(data)

    @staticmethod
    def _write_approval(run: RunRecord, approval: ApprovalRecord) -> None:
        path = run.artifact_dir / "approval.json"
        path.write_text(approval.model_dump_json(indent=2), encoding="utf-8")

    @staticmethod
    def _write_source_reviews(run: RunRecord, reviews: list[SourceReviewRecord]) -> None:
        path = run.artifact_dir / "source-review.json"
        data = [review.model_dump(mode="json") for review in reviews]
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _write_publish_receipt(run: RunRecord, receipt: PublishReceipt) -> None:
        path = run.artifact_dir / "publish-receipt.json"
        path.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")

    @staticmethod
    def _write_publish_rollback(run: RunRecord, result: PublishRollbackResult) -> None:
        path = run.artifact_dir / "publish-rollback.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    @staticmethod
    def _write_publish_verification(
        run: RunRecord,
        report: PublishVerificationReport,
    ) -> None:
        path = run.artifact_dir / "publish-verification.json"
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    @staticmethod
    def _write_publish_recovery_plan(
        run: RunRecord,
        plan: PublishRecoveryPlan,
    ) -> None:
        path = run.artifact_dir / "publish-recovery-plan.json"
        path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    @staticmethod
    def _write_publish_recovery_execution(
        run: RunRecord,
        result: PublishRecoveryExecutionResult,
    ) -> None:
        path = run.artifact_dir / "publish-recovery-execution.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    def _published_content_item(self, run: RunRecord) -> PublishedContentItem:
        draft = self._load_json(run, "draft.json", Draft)
        report = self._load_json(run, "eval-report.json", EvaluationReport)
        receipt = self.publish_receipt(run.id)
        return PublishedContentItem(
            run_id=run.id,
            topic=run.topic,
            slug=run.slug,
            title=draft.title,
            url=receipt.url if receipt is not None else run.published_url or "",
            provider=receipt.provider if receipt is not None else "unknown",
            published_at=receipt.published_at if receipt is not None else run.updated_at,
            publish_ready=report.publish_ready,
            groundedness=report.groundedness,
            source_coverage=report.source_coverage,
            source_quality=report.source_quality,
            career_relevance=report.career_relevance,
            technical_depth=report.technical_depth,
        )

    def _scorecard_for_run(self, run: RunRecord) -> RunScorecard:
        metrics = self.metrics_service.run_metrics(run)
        warnings: list[str] = []
        report = self._load_optional_json(run, "eval-report.json", EvaluationReport)
        quality_pass: bool | None = None
        if report is None:
            warnings.append("Evaluation report is missing.")
        else:
            quality_pass = report.publish_ready
            if not report.publish_ready:
                warnings.append("Evaluation report is not publish-ready.")
            warnings.extend(report.findings)
        latency_slo_pass: bool | None = None
        if metrics.total_duration_ms is None:
            warnings.append("Run duration is unavailable.")
        else:
            latency_slo_pass = metrics.total_duration_ms <= self.latency_slo_ms
            if not latency_slo_pass:
                warnings.append(
                    f"Run exceeded latency SLO of {self.latency_slo_ms}ms."
                )
        effective_source_count, source_review_pass, review_warnings = (
            self._review_adjusted_source_count(run, metrics.source_count)
        )
        warnings.extend(review_warnings)
        sources_slo_pass = effective_source_count >= self.min_source_count and source_review_pass
        if not sources_slo_pass:
            warnings.append(
                f"Run has fewer than {self.min_source_count} approved source(s)."
            )
        return RunScorecard(
            run_id=run.id,
            status=run.status,
            topic=run.topic,
            slug=run.slug,
            published_url=run.published_url,
            source_count=effective_source_count,
            total_duration_ms=metrics.total_duration_ms,
            latency_slo_ms=self.latency_slo_ms,
            min_source_count=self.min_source_count,
            publish_ready=report.publish_ready if report is not None else None,
            groundedness=report.groundedness if report is not None else None,
            source_coverage=report.source_coverage if report is not None else None,
            source_quality=report.source_quality if report is not None else None,
            career_relevance=report.career_relevance if report is not None else None,
            technical_depth=report.technical_depth if report is not None else None,
            quality_pass=quality_pass,
            latency_slo_pass=latency_slo_pass,
            sources_slo_pass=sources_slo_pass,
            overall_pass=quality_pass is True
            and latency_slo_pass is not False
            and sources_slo_pass,
            warnings=warnings,
        )

    def _cost_report_for_run(self, run: RunRecord) -> RunCostReport:
        warnings: list[str] = []
        receipt = self._load_optional_json(run, "generation-receipt.json", GenerationReceipt)
        if (
            receipt is not None
            and receipt.input_tokens is not None
            and receipt.output_tokens is not None
        ):
            input_tokens = receipt.input_tokens
            output_tokens = receipt.output_tokens
            total_tokens = receipt.total_tokens or input_tokens + output_tokens
            if receipt.fallback_used:
                warnings.append("Generation used fallback output.")
            budget_pass = total_tokens <= self.token_budget_per_run
            if not budget_pass:
                warnings.append(
                    f"Estimated token usage exceeds budget of {self.token_budget_per_run}."
                )
            return RunCostReport(
                run_id=run.id,
                status=run.status,
                topic=run.topic,
                slug=run.slug,
                model=receipt.model,
                estimated_input_tokens=input_tokens,
                estimated_output_tokens=output_tokens,
                estimated_total_tokens=total_tokens,
                token_budget=self.token_budget_per_run,
                budget_pass=budget_pass,
                warnings=warnings,
            )
        if receipt is None:
            warnings.append("Generation receipt is missing; using artifact-based estimate.")
        else:
            warnings.append(
                "Generation receipt has no usage tokens; using artifact-based estimate."
            )
        input_text = self._artifact_text(
            run,
            ["request.json", "research.json", "source-audit.json", "outline.md"],
            warnings,
        )
        output_text = self._artifact_text(
            run,
            ["draft.md", "draft.json", "eval-report.json"],
            warnings,
        )
        input_tokens = self._estimate_tokens(input_text)
        output_tokens = self._estimate_tokens(output_text)
        total_tokens = input_tokens + output_tokens
        budget_pass = total_tokens <= self.token_budget_per_run
        if not budget_pass:
            warnings.append(
                f"Estimated token usage exceeds budget of {self.token_budget_per_run}."
            )
        return RunCostReport(
            run_id=run.id,
            status=run.status,
            topic=run.topic,
            slug=run.slug,
            model=receipt.model if receipt is not None else self.model,
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            estimated_total_tokens=total_tokens,
            token_budget=self.token_budget_per_run,
            budget_pass=budget_pass,
            warnings=warnings,
        )

    def _incident_report_for_run(self, run: RunRecord) -> RunIncidentReport:
        signals: list[RunIncidentSignal] = []
        if run.status == RunStatus.FAILED:
            signals.append(
                RunIncidentSignal(
                    severity=IncidentSeverity.CRITICAL,
                    category="run",
                    message=run.error or "Run failed without a recorded error.",
                    artifact="trace.json",
                )
            )
        scorecard = self._scorecard_for_run(run)
        if not scorecard.overall_pass:
            signals.append(
                RunIncidentSignal(
                    severity=IncidentSeverity.WARNING,
                    category="quality",
                    message="Run scorecard did not pass.",
                    artifact="eval-report.json",
                )
            )
            for warning in scorecard.warnings:
                signals.append(
                    RunIncidentSignal(
                        severity=IncidentSeverity.WARNING,
                        category="quality",
                        message=warning,
                        artifact="eval-report.json",
                    )
                )
        cost_report = self._cost_report_for_run(run)
        if not cost_report.budget_pass:
            signals.append(
                RunIncidentSignal(
                    severity=IncidentSeverity.WARNING,
                    category="cost",
                    message="Run exceeded the configured token budget.",
                    artifact="generation-receipt.json",
                )
            )
        for warning in cost_report.warnings:
            signals.append(
                RunIncidentSignal(
                    severity=IncidentSeverity.WARNING,
                    category="cost",
                    message=warning,
                    artifact="generation-receipt.json",
                )
            )
        if run.status == RunStatus.PUBLISHED:
            try:
                verification = self.verify_publish(run.id)
            except ValueError as exc:
                signals.append(
                    RunIncidentSignal(
                        severity=IncidentSeverity.CRITICAL,
                        category="publish",
                        message=str(exc),
                        artifact="publish-receipt.json",
                    )
                )
            else:
                if not verification.verified:
                    signals.append(
                        RunIncidentSignal(
                            severity=IncidentSeverity.CRITICAL,
                            category="publish",
                            message="Published files do not match the publish receipt.",
                            artifact="publish-verification.json",
                        )
                    )
        for delivery in self.notification_log(run.id):
            if delivery.status == "failed":
                signals.append(
                    RunIncidentSignal(
                        severity=IncidentSeverity.WARNING,
                        category="notification",
                        message=delivery.error or "Notification delivery failed.",
                        artifact="notification-log.json",
                    )
                )
        if not signals:
            signals.append(
                RunIncidentSignal(
                    severity=IncidentSeverity.INFO,
                    category="run",
                    message="No incident signals detected.",
                )
            )
        severity = _max_severity(signal.severity for signal in signals)
        return RunIncidentReport(
            run_id=run.id,
            status=run.status,
            topic=run.topic,
            severity=severity,
            requires_action=severity != IncidentSeverity.INFO,
            signals=signals,
        )

    def _audit_events(
        self,
        status: RunStatus | None,
        query: str,
        action: str,
    ) -> list[AuditEvent]:
        normalized_action = action.strip()
        events: list[AuditEvent] = []
        for run in self.repository.list(limit=1000, status=status, query=query):
            events.extend(
                event
                for event in self.audit_log(run.id)
                if not normalized_action or event.action == normalized_action
            )
        return sorted(events, key=lambda event: event.occurred_at, reverse=True)

    def _record_audit_event(self, run: RunRecord, event: AuditEvent) -> None:
        self._append_audit_event(run, event)
        delivery = self.notifier.notify(run, event)
        self._append_notification_delivery(run, delivery)

    @staticmethod
    def _verify_publish_change(change: PublishFileChange) -> PublishVerificationItem:
        path = Path(change.path)
        if not path.exists():
            return PublishVerificationItem(
                path=change.path,
                expected_sha256=change.after_sha256,
                exists=False,
                matches_receipt=False,
                message="Published file is missing.",
            )
        actual_sha = sha256(path.read_bytes()).hexdigest()
        matches = change.after_sha256 is not None and actual_sha == change.after_sha256
        return PublishVerificationItem(
            path=change.path,
            expected_sha256=change.after_sha256,
            actual_sha256=actual_sha,
            exists=True,
            matches_receipt=matches,
            message="File hash matches receipt." if matches else "File hash differs from receipt.",
        )

    @staticmethod
    def _append_audit_event(run: RunRecord, event: AuditEvent) -> None:
        path = run.artifact_dir / "audit-log.json"
        if path.exists():
            events = json.loads(path.read_text(encoding="utf-8"))
        else:
            events = []
        events.append(event.model_dump(mode="json"))
        path.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _append_notification_delivery(run: RunRecord, delivery: NotificationDelivery) -> None:
        path = run.artifact_dir / "notification-log.json"
        if path.exists():
            deliveries = json.loads(path.read_text(encoding="utf-8"))
        else:
            deliveries = []
        deliveries.append(delivery.model_dump(mode="json"))
        path.write_text(json.dumps(deliveries, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _load_sources(run: RunRecord) -> list[Source]:
        path = run.artifact_dir / "research.json"
        if not path.exists():
            return []
        packet = ResearchPacket.model_validate(json.loads(path.read_text(encoding="utf-8")))
        return packet.sources

    @staticmethod
    def _load_source_reviews(run: RunRecord) -> list[SourceReviewRecord]:
        path = run.artifact_dir / "source-review.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [SourceReviewRecord.model_validate(item) for item in data]

    @classmethod
    def _review_adjusted_source_count(
        cls,
        run: RunRecord,
        raw_source_count: int,
    ) -> tuple[int, bool, list[str]]:
        reviews = cls._load_source_reviews(run)
        excluded_count = sum(
            1 for review in reviews if review.decision == SourceReviewDecision.EXCLUDE
        )
        pending_count = sum(
            1 for review in reviews if review.decision == SourceReviewDecision.NEEDS_REVIEW
        )
        effective_source_count = max(raw_source_count - excluded_count, 0)
        warnings: list[str] = []
        if excluded_count:
            warnings.append(f"{excluded_count} source(s) were excluded by reviewer decision.")
        if pending_count:
            warnings.append(f"{pending_count} source review decision(s) are still pending.")
        return effective_source_count, pending_count == 0, warnings

    @staticmethod
    def _load_optional_json(run: RunRecord, artifact_name: str, model: type[T]) -> T | None:
        path = run.artifact_dir / artifact_name
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return model.model_validate(data)

    @staticmethod
    def _artifact_text(run: RunRecord, artifact_names: list[str], warnings: list[str]) -> str:
        parts: list[str] = []
        for artifact_name in artifact_names:
            path = run.artifact_dir / artifact_name
            if not path.exists():
                warnings.append(f"Artifact missing from cost estimate: {artifact_name}.")
                continue
            parts.append(path.read_text(encoding="utf-8"))
        return "\n".join(parts)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return (len(text) + 3) // 4

    @classmethod
    def _source_overlap(
        cls,
        base_sources: list[Source],
        candidate_sources: list[Source],
    ) -> SourceOverlap:
        base_map = {cls._source_key(source): source.title for source in base_sources}
        candidate_map = {cls._source_key(source): source.title for source in candidate_sources}
        base_keys = set(base_map)
        candidate_keys = set(candidate_map)
        shared = base_keys & candidate_keys
        return SourceOverlap(
            base_count=len(base_sources),
            candidate_count=len(candidate_sources),
            shared_count=len(shared),
            base_only=sorted(base_map[key] for key in base_keys - candidate_keys),
            candidate_only=sorted(candidate_map[key] for key in candidate_keys - base_keys),
        )

    @staticmethod
    def _source_key(source: Source) -> str:
        return (source.canonical_url or source.url or source.title).strip().casefold()

    @staticmethod
    def _snapshot_publish_targets(plan: PublishPlan) -> dict[str, str | None]:
        snapshot: dict[str, str | None] = {}
        for item in plan.items:
            path = Path(item.path)
            snapshot[item.path] = sha256(path.read_bytes()).hexdigest() if path.exists() else None
        return snapshot

    @staticmethod
    def _backup_publish_targets(run: RunRecord, plan: PublishPlan) -> dict[str, str]:
        backups: dict[str, str] = {}
        backup_dir = run.artifact_dir / "publish-backups"
        for index, item in enumerate(plan.items, start=1):
            path = Path(item.path)
            if not path.exists() or not path.is_file():
                continue
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_name = f"{index}-{sha256(item.path.encode('utf-8')).hexdigest()[:12]}.bak"
            backup_path = backup_dir / backup_name
            backup_path.write_bytes(path.read_bytes())
            backups[item.path] = str(backup_path.relative_to(run.artifact_dir))
        return backups

    @staticmethod
    def _publish_file_changes(
        plan: PublishPlan,
        *,
        before_snapshot: dict[str, str | None],
        after_snapshot: dict[str, str | None],
        backups: dict[str, str],
    ) -> list[PublishFileChange]:
        changes: list[PublishFileChange] = []
        for item in plan.items:
            before_sha = before_snapshot.get(item.path)
            after_sha = after_snapshot.get(item.path)
            if before_sha == after_sha:
                action = "unchanged"
            elif before_sha is None and after_sha is not None:
                action = "created"
            elif before_sha is not None and after_sha is None:
                action = "deleted"
            else:
                action = "updated"
            backup_artifact = backups.get(item.path)
            changes.append(
                PublishFileChange(
                    path=item.path,
                    action=action,
                    existed_before=before_sha is not None,
                    exists_after=after_sha is not None,
                    before_sha256=before_sha,
                    after_sha256=after_sha,
                    backup_artifact=backup_artifact,
                    rollback_hint=_rollback_hint(action, backup_artifact),
                )
            )
        return changes

    @classmethod
    def _restore_publish_changes(
        cls,
        run: RunRecord,
        receipt: PublishReceipt,
    ) -> PublishRollbackResult:
        result = PublishRollbackResult(run_id=run.id)
        for change in receipt.file_changes:
            target_path = Path(change.path)
            try:
                if change.backup_artifact:
                    backup_path = cls._safe_backup_path(run.artifact_dir, change.backup_artifact)
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_bytes(backup_path.read_bytes())
                    result.restored_files.append(change.path)
                elif change.action == "created":
                    if target_path.exists():
                        target_path.unlink()
                    result.deleted_files.append(change.path)
                else:
                    result.skipped_files.append(change.path)
            except (OSError, ValueError) as exc:
                result.errors.append(f"{change.path}: {exc}")
        return result

    @staticmethod
    def _safe_backup_path(artifact_dir: Path, backup_artifact: str) -> Path:
        path = (artifact_dir / backup_artifact).resolve()
        root = artifact_dir.resolve()
        if root not in path.parents and path != root:
            raise ValueError("Backup artifact path escapes the run directory.")
        if not path.is_file():
            raise FileNotFoundError(f"Backup artifact not found: {backup_artifact}")
        return path


def _rollback_hint(action: str, backup_artifact: str | None) -> str:
    if backup_artifact:
        return f"Restore artifact {backup_artifact} to this path."
    if action == "created":
        return "Delete this created file to roll back."
    if action == "unchanged":
        return "No rollback action needed."
    return "No backup artifact is available; inspect version control or deployment history."


def _command_text(commands: object) -> str:
    if not isinstance(commands, list):
        return ""
    return "\n".join(str(command) for command in commands) + ("\n" if commands else "")


def _pass_rate(values: Iterable[bool]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return round(sum(1 for item in items if item) / len(items), 3)


def _publish_recovery_file_action(
    item: PublishVerificationItem,
) -> PublishRecoveryFileAction:
    if item.matches_receipt:
        return PublishRecoveryFileAction(
            path=item.path,
            status="ok",
            exists=item.exists,
            matches_receipt=item.matches_receipt,
            recommended_action="none",
            reason="Published file matches the receipt.",
        )
    if not item.exists:
        return PublishRecoveryFileAction(
            path=item.path,
            status="missing",
            exists=item.exists,
            matches_receipt=item.matches_receipt,
            recommended_action="restore_or_republish",
            reason="Published file is missing from the target.",
        )
    return PublishRecoveryFileAction(
        path=item.path,
        status="mismatch",
        exists=item.exists,
        matches_receipt=item.matches_receipt,
        recommended_action="restore_expected_hash_or_republish",
        reason="Published file exists but does not match the receipt hash.",
    )


def _artifact_dir_stats(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    files = [item for item in path.rglob("*") if item.is_file()]
    size_bytes = 0
    for item in files:
        try:
            size_bytes += item.stat().st_size
        except OSError:
            continue
    return len(files), size_bytes


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _max_severity(severities: Iterable[IncidentSeverity]) -> IncidentSeverity:
    rank = {
        IncidentSeverity.INFO: 0,
        IncidentSeverity.WARNING: 1,
        IncidentSeverity.CRITICAL: 2,
    }
    selected = IncidentSeverity.INFO
    for severity in severities:
        if isinstance(severity, IncidentSeverity) and rank[severity] > rank[selected]:
            selected = severity
    return selected
