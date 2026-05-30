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
    approved = review_service.approve(
        result.run.id,
        reviewer="zack",
        notes="Looks grounded enough to publish.",
    )
    published = review_service.publish(result.run.id)
    approval = review_service.approval(result.run.id)
    receipt = review_service.publish_receipt(result.run.id)

    assert "draft.json" in artifacts
    assert "eval-report.json" in artifacts
    assert "approval.json" not in artifacts
    assert plan.ready is True
    assert len(plan.items) == 3
    assert metrics.run_id == result.run.id
    assert metrics.total_duration_ms is not None
    assert metrics.publish_ready is True
    assert original_request.topic == "Reviewable AI article"
    assert {step.step for step in metrics.step_metrics} >= {"research", "planning", "drafting"}
    assert approved.status == RunStatus.APPROVED
    assert approval is not None
    assert approval.reviewer == "zack"
    assert published.status == RunStatus.PUBLISHED
    assert published.published_url is not None
    assert receipt is not None
    assert receipt.provider == "static"
    assert receipt.url == published.published_url
    assert receipt.approval is not None
    assert receipt.approval.reviewer == "zack"
    assert (result.run.artifact_dir / "publish-receipt.json").exists()


def test_review_service_requires_approval_before_publish(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        public_base_url="https://example.com",
        min_publish_score=0.5,
    )
    pipeline = build_pipeline(settings)
    result = pipeline.run(RunRequest(topic="Approval gate article"))
    review_service = build_review_service(settings)

    with pytest.raises(ValueError, match="approved before publishing"):
        review_service.publish(result.run.id)

    review_service.approve(result.run.id)
    published = review_service.publish(result.run.id)
    receipt = review_service.publish_receipt(result.run.id)

    assert published.status == RunStatus.PUBLISHED
    assert receipt is not None
    assert receipt.force is False


def test_review_service_rejects_run(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    pipeline = build_pipeline(settings)
    result = pipeline.run(RunRequest(topic="Rejected AI article"))
    review_service = build_review_service(settings)

    rejected = review_service.reject(result.run.id, reviewer="zack", notes="Needs a better angle.")
    approval = review_service.approval(result.run.id)

    assert rejected.status == RunStatus.REJECTED
    assert approval is not None
    assert approval.decision.value == "rejected"
    assert approval.notes == "Needs a better angle."


def test_review_service_records_forced_publish_receipt(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        public_base_url="https://example.com",
        min_publish_score=0.5,
    )
    pipeline = build_pipeline(settings)
    result = pipeline.run(RunRequest(topic="Forced publish receipt"))
    review_service = build_review_service(settings)

    published = review_service.publish(result.run.id, force=True)
    receipt = review_service.publish_receipt(result.run.id)

    assert published.status == RunStatus.PUBLISHED
    assert receipt is not None
    assert receipt.force is True
    assert receipt.approval is None


def test_review_service_compares_runs(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    pipeline = build_pipeline(settings)
    base = pipeline.run(RunRequest(topic="Agent quality review")).run
    candidate = pipeline.run(
        RunRequest(
            topic="Agent quality review",
            source_urls=["https://example.com/agent-quality-review"],
        )
    ).run
    review_service = build_review_service(settings)

    comparison = review_service.compare(base.id, candidate.id)

    assert comparison.base_run_id == base.id
    assert comparison.candidate_run_id == candidate.id
    assert comparison.same_topic is True
    assert comparison.source_count_delta >= 1
    assert comparison.source_overlap.base_count >= 1
    assert "groundedness" in comparison.evaluation_deltas
    assert comparison.summary


def test_s3_artifact_store_requires_bucket(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        artifact_store_provider="s3",
    )

    with pytest.raises(ValueError, match="CONTENTOPS_ARTIFACT_S3_BUCKET"):
        build_pipeline(settings)
