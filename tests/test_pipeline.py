from __future__ import annotations

from pathlib import Path

import pytest
from contentops_core.diagnostics import system_status
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
    assert (result.run.artifact_dir / "source-audit.json").exists()
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


def test_repository_filters_and_counts_run_queue(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    pipeline = build_pipeline(settings)
    first = pipeline.run(RunRequest(topic="Queue searchable RAG review")).run
    second = pipeline.run(RunRequest(topic="Queue unrelated agent article")).run
    repo = RunRepository(settings.database_url)

    filtered = repo.list(status=RunStatus.NEEDS_REVIEW, query="searchable")
    paged = repo.list(limit=1, offset=1, status=RunStatus.NEEDS_REVIEW)

    assert [run.id for run in filtered] == [first.id]
    assert repo.count() == 2
    assert repo.count(status=RunStatus.NEEDS_REVIEW) == 2
    assert repo.count(status=RunStatus.NEEDS_REVIEW, query=second.slug) == 1
    assert len(paged) == 1


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
    manifest = review_service.artifact_manifest(result.run.id)
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
    audit_events = review_service.audit_log(result.run.id)

    assert "draft.json" in artifacts
    assert "eval-report.json" in artifacts
    assert "approval.json" not in artifacts
    assert manifest.run_id == result.run.id
    assert manifest.artifacts["draft.json"].size_bytes > 0
    assert len(manifest.artifacts["draft.json"].sha256) == 64
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
    assert [event.action for event in audit_events] == ["approve", "publish"]
    assert audit_events[0].actor == "zack"
    assert audit_events[1].new_status == RunStatus.PUBLISHED
    assert (result.run.artifact_dir / "publish-receipt.json").exists()
    assert (result.run.artifact_dir / "audit-log.json").exists()


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
    audit_events = review_service.audit_log(result.run.id)

    assert rejected.status == RunStatus.REJECTED
    assert approval is not None
    assert approval.decision.value == "rejected"
    assert approval.notes == "Needs a better angle."
    assert len(audit_events) == 1
    assert audit_events[0].action == "reject"
    assert audit_events[0].actor == "zack"


def test_review_service_batch_approve_records_partial_results(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    pipeline = build_pipeline(settings)
    first = pipeline.run(RunRequest(topic="Batch service first")).run
    second = pipeline.run(RunRequest(topic="Batch service second")).run
    review_service = build_review_service(settings)

    result = review_service.approve_many(
        [first.id, second.id, "missing-run"],
        reviewer="zack",
        notes="Batch reviewed.",
    )

    assert result.action == "approve"
    assert [item.status for item in result.results] == ["ok", "ok", "failed"]
    assert result.results[0].new_status == RunStatus.APPROVED
    assert result.results[2].error is not None
    assert review_service.approval(first.id) is not None


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


def test_system_status_reports_configuration_failures(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        generator_provider="openai",
        openai_api_key=None,
    )
    repo = RunRepository(settings.database_url)

    status = system_status(settings, repo)

    assert status.status == "fail"
    provider_check = next(check for check in status.checks if check.name == "provider_config")
    assert provider_check.status == "fail"
    assert "CONTENTOPS_OPENAI_API_KEY" in provider_check.fields["failures"][0]


def test_system_status_reports_missing_search_credentials(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        research_provider="search",
        research_search_api_key=None,
    )
    repo = RunRepository(settings.database_url)

    status = system_status(settings, repo)

    assert status.status == "fail"
    provider_check = next(check for check in status.checks if check.name == "provider_config")
    assert "CONTENTOPS_RESEARCH_SEARCH_API_KEY" in provider_check.fields["failures"][0]
