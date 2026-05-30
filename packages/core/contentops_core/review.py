from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from contentops_publishing.static_site import Publisher
from pydantic import BaseModel

from contentops_core.metrics import MetricsService
from contentops_core.models import (
    ApprovalDecision,
    ApprovalRecord,
    Draft,
    EvaluationReport,
    PublishPlan,
    PublishReceipt,
    ResearchPacket,
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

    def read_artifact(self, run_id: str, artifact_name: str) -> str:
        run = self._get_run(run_id)
        artifact_path = self._safe_artifact_path(run.artifact_dir, artifact_name)
        return artifact_path.read_text(encoding="utf-8")

    def publish(self, run_id: str, force: bool = False) -> RunRecord:
        run = self._get_run(run_id)
        draft = self._load_json(run, "draft.json", Draft)
        report = self._load_json(run, "eval-report.json", EvaluationReport)
        approval = self.approval(run_id)
        if run.status == RunStatus.NEEDS_REVIEW and approval is None and not force:
            raise ValueError("Run must be approved before publishing. Use force=true to override.")
        if approval is not None and approval.decision == ApprovalDecision.REJECTED and not force:
            raise ValueError("Run was rejected. Use force=true to override.")
        if not report.publish_ready and not force:
            raise ValueError("Run is not publish-ready. Use force=true to override.")
        plan = self.publisher.plan(run, draft, report)
        if not plan.ready and not force:
            raise ValueError("; ".join(plan.warnings))
        run.touch(RunStatus.PUBLISHING)
        self.repository.save(run)
        run.published_url = self.publisher.publish(run, draft, report)
        self._write_publish_receipt(
            run,
            PublishReceipt(
                run_id=run_id,
                provider=plan.provider,
                url=run.published_url,
                plan_items=plan.items,
                approval=approval,
                force=force,
            ),
        )
        run.touch(RunStatus.PUBLISHED)
        self.repository.save(run)
        return run

    def approve(self, run_id: str, reviewer: str = "operator", notes: str = "") -> RunRecord:
        run = self._get_run(run_id)
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
        return run

    def reject(self, run_id: str, reviewer: str = "operator", notes: str = "") -> RunRecord:
        run = self._get_run(run_id)
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
        return run

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
