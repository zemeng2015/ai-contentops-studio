from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from contentops_publishing.static_site import Publisher
from pydantic import BaseModel

from contentops_core.metrics import MetricsService
from contentops_core.models import (
    Draft,
    EvaluationReport,
    PublishPlan,
    RunMetrics,
    RunRecord,
    RunStatus,
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
        if not report.publish_ready and not force:
            raise ValueError("Run is not publish-ready. Use force=true to override.")
        plan = self.publisher.plan(run, draft, report)
        if not plan.ready and not force:
            raise ValueError("; ".join(plan.warnings))
        run.touch(RunStatus.PUBLISHING)
        self.repository.save(run)
        run.published_url = self.publisher.publish(run, draft, report)
        run.touch(RunStatus.PUBLISHED)
        self.repository.save(run)
        return run

    def publish_plan(self, run_id: str) -> PublishPlan:
        run = self._get_run(run_id)
        draft = self._load_json(run, "draft.json", Draft)
        report = self._load_json(run, "eval-report.json", EvaluationReport)
        return self.publisher.plan(run, draft, report)

    def metrics(self, run_id: str) -> RunMetrics:
        return self.metrics_service.run_metrics(self._get_run(run_id))

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
