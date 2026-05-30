from __future__ import annotations

import json
import mimetypes
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TypeVar
from zipfile import ZIP_DEFLATED, ZipFile

from contentops_publishing.static_site import Publisher
from pydantic import BaseModel

from contentops_core.metrics import MetricsService
from contentops_core.models import (
    ApprovalDecision,
    ApprovalRecord,
    ArtifactManifest,
    ArtifactMetadata,
    AuditEvent,
    Draft,
    EvaluationReport,
    PublishedContentItem,
    PublishedContentListResponse,
    PublishFileChange,
    PublishPlan,
    PublishReceipt,
    PublishRollbackResult,
    ResearchPacket,
    ReviewActionResult,
    ReviewBatchResult,
    RunComparison,
    RunMetrics,
    RunRecord,
    RunRequest,
    RunStatus,
    Source,
    SourceOverlap,
)
from contentops_core.repository import RunRepository

T = TypeVar("T", bound=BaseModel)


class ReviewService:
    def __init__(self, repository: RunRepository, publisher: Publisher) -> None:
        self.repository = repository
        self.publisher = publisher
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
                file_changes=file_changes,
                approval=approval,
                force=force,
            ),
        )
        run.touch(RunStatus.PUBLISHED)
        self.repository.save(run)
        actor = approval.reviewer if approval is not None else "force"
        self._append_audit_event(
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
        self._append_audit_event(
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
        self._append_audit_event(
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

    def audit_log(self, run_id: str) -> list[AuditEvent]:
        run = self._get_run(run_id)
        path = run.artifact_dir / "audit-log.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [AuditEvent.model_validate(item) for item in data]

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
        self._append_audit_event(
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

    def request(self, run_id: str) -> RunRequest:
        return self._load_json(self._get_run(run_id), "request.json", RunRequest)

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
    def _write_publish_receipt(run: RunRecord, receipt: PublishReceipt) -> None:
        path = run.artifact_dir / "publish-receipt.json"
        path.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")

    @staticmethod
    def _write_publish_rollback(run: RunRecord, result: PublishRollbackResult) -> None:
        path = run.artifact_dir / "publish-rollback.json"
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
    def _load_sources(run: RunRecord) -> list[Source]:
        path = run.artifact_dir / "research.json"
        if not path.exists():
            return []
        packet = ResearchPacket.model_validate(json.loads(path.read_text(encoding="utf-8")))
        return packet.sources

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
