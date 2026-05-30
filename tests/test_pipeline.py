from __future__ import annotations

from pathlib import Path

import pytest
from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.models import RunRequest, RunStatus
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings


def test_pipeline_creates_reviewable_artifacts(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        min_publish_score=0.72,
    )
    pipeline = build_pipeline(settings)

    result = pipeline.run(RunRequest(topic="LLM observability for enterprise RAG"))

    assert result.run.status == RunStatus.NEEDS_REVIEW
    assert (result.run.artifact_dir / "request.json").exists()
    assert (result.run.artifact_dir / "research.json").exists()
    assert (result.run.artifact_dir / "outline.md").exists()
    assert (result.run.artifact_dir / "draft.md").exists()
    assert (result.run.artifact_dir / "eval-report.json").exists()
    assert (result.run.artifact_dir / "trace.json").exists()


def test_pipeline_publishes_when_requested_and_ready(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        public_base_url="https://example.com",
        min_publish_score=0.5,
    )
    pipeline = build_pipeline(settings)

    result = pipeline.run(RunRequest(topic="AI evaluation workflow", publish=True))

    assert result.run.status == RunStatus.PUBLISHED
    assert result.published_url is not None
    assert (tmp_path / "site" / "index.html").exists()
    assert any((tmp_path / "site" / "posts").glob("*.html"))


def test_repository_round_trips_run_metadata(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    pipeline = build_pipeline(settings)
    result = pipeline.run(RunRequest(topic="ContentOps pipeline architecture"))
    repo = RunRepository(settings.database_url)

    stored = repo.get(result.run.id)

    assert stored is not None
    assert stored.topic == "ContentOps pipeline architecture"
    assert repo.list(limit=1)[0].id == result.run.id


def test_review_service_lists_artifacts_and_publishes_existing_run(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        public_base_url="https://example.com",
        min_publish_score=0.5,
    )
    pipeline = build_pipeline(settings)
    result = pipeline.run(RunRequest(topic="Reviewable AI article"))
    review_service = build_review_service(settings)

    artifacts = review_service.list_artifacts(result.run.id)
    plan = review_service.publish_plan(result.run.id)
    metrics = review_service.metrics(result.run.id)
    original_request = review_service.request(result.run.id)
    published = review_service.publish(result.run.id)

    assert "draft.json" in artifacts
    assert "eval-report.json" in artifacts
    assert plan.ready is True
    assert len(plan.items) == 3
    assert metrics.run_id == result.run.id
    assert metrics.total_duration_ms is not None
    assert metrics.publish_ready is True
    assert original_request.topic == "Reviewable AI article"
    assert {step.step for step in metrics.step_metrics} >= {"research", "planning", "drafting"}
    assert published.status == RunStatus.PUBLISHED
    assert published.published_url is not None


def test_s3_artifact_store_requires_bucket(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        artifact_store_provider="s3",
    )

    with pytest.raises(ValueError, match="CONTENTOPS_ARTIFACT_S3_BUCKET"):
        build_pipeline(settings)
