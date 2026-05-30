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
    scorecard = review_service.scorecard(result.run.id)
    scorecards = review_service.scorecards(limit=5)
    cost_report = review_service.cost_report(result.run.id)
    cost_reports = review_service.cost_reports(limit=5)
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
    notifications = review_service.notification_log(result.run.id)

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
    assert scorecard.run_id == result.run.id
    assert scorecard.overall_pass is True
    assert scorecard.quality_pass is True
    assert scorecard.sources_slo_pass is True
    assert scorecard.groundedness is not None
    assert any(item.run_id == result.run.id for item in scorecards.items)
    assert scorecards.quality_pass_rate >= 0
    assert cost_report.run_id == result.run.id
    assert cost_report.estimated_total_tokens > 0
    assert cost_report.budget_pass is True
    assert any(item.run_id == result.run.id for item in cost_reports.items)
    assert cost_reports.estimated_total_tokens >= cost_report.estimated_total_tokens
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
    assert len(receipt.file_changes) == 3
    assert {change.action for change in receipt.file_changes} == {"created"}
    assert all(change.after_sha256 for change in receipt.file_changes)
    assert all("roll back" in change.rollback_hint for change in receipt.file_changes)
    assert [event.action for event in audit_events] == ["approve", "publish"]
    assert audit_events[0].actor == "zack"
    assert audit_events[1].new_status == RunStatus.PUBLISHED
    assert audit_events[1].fields["changed_files"] == 3
    assert [delivery.action for delivery in notifications] == ["approve", "publish"]
    assert {delivery.provider for delivery in notifications} == {"local"}
    assert {delivery.status for delivery in notifications} == {"skipped"}
    assert (result.run.artifact_dir / "publish-receipt.json").exists()
    assert (result.run.artifact_dir / "audit-log.json").exists()
    assert (result.run.artifact_dir / "notification-log.json").exists()


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


def test_publish_receipt_records_overwrite_backups(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        public_base_url="https://example.com",
        min_publish_score=0.5,
    )
    pipeline = build_pipeline(settings)
    review_service = build_review_service(settings)

    first = pipeline.run(RunRequest(topic="Overwrite publish metadata")).run
    review_service.approve(first.id, reviewer="zack")
    review_service.publish(first.id)
    second = pipeline.run(RunRequest(topic="Overwrite publish metadata")).run
    review_service.approve(second.id, reviewer="zack")
    review_service.publish(second.id)
    receipt = review_service.publish_receipt(second.id)

    assert receipt is not None
    assert {change.action for change in receipt.file_changes} <= {"updated", "unchanged"}
    assert any(change.action == "updated" for change in receipt.file_changes)
    assert all(change.before_sha256 for change in receipt.file_changes)
    assert all(change.after_sha256 for change in receipt.file_changes)
    assert all(change.backup_artifact for change in receipt.file_changes)
    for change in receipt.file_changes:
        assert change.backup_artifact is not None
        assert (second.artifact_dir / change.backup_artifact).exists()

    rollback = review_service.rollback_publish(second.id, actor="zack")
    rolled_back = review_service.repository.get(second.id)
    audit_events = review_service.audit_log(second.id)
    notifications = review_service.notification_log(second.id)

    assert rollback.errors == []
    assert len(rollback.restored_files) == 3
    assert rolled_back is not None
    assert rolled_back.status == RunStatus.APPROVED
    assert rolled_back.published_url is None
    assert (second.artifact_dir / "publish-rollback.json").exists()
    assert audit_events[-1].action == "rollback_publish"
    assert audit_events[-1].actor == "zack"
    assert notifications[-1].action == "rollback_publish"


def test_publish_rollback_deletes_created_files(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        public_base_url="https://example.com",
        min_publish_score=0.5,
    )
    pipeline = build_pipeline(settings)
    review_service = build_review_service(settings)
    result = pipeline.run(RunRequest(topic="Rollback created files"))
    review_service.approve(result.run.id, reviewer="zack")
    review_service.publish(result.run.id)
    receipt = review_service.publish_receipt(result.run.id)

    rollback = review_service.rollback_publish(result.run.id, actor="zack")

    assert receipt is not None
    assert {change.action for change in receipt.file_changes} == {"created"}
    assert rollback.errors == []
    assert len(rollback.deleted_files) == 3
    assert all(not Path(path).exists() for path in rollback.deleted_files)


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
    notifications = review_service.notification_log(result.run.id)

    assert rejected.status == RunStatus.REJECTED
    assert approval is not None
    assert approval.decision.value == "rejected"
    assert approval.notes == "Needs a better angle."
    assert len(audit_events) == 1
    assert audit_events[0].action == "reject"
    assert audit_events[0].actor == "zack"
    assert notifications[0].action == "reject"


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


def test_system_status_validates_research_retry_policy(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        research_retry_attempts=0,
        research_retry_backoff_seconds=-0.1,
    )
    repo = RunRepository(settings.database_url)

    status = system_status(settings, repo)

    assert status.status == "fail"
    provider_check = next(check for check in status.checks if check.name == "provider_config")
    assert "research retry attempts must be at least 1" in provider_check.fields["failures"]
    assert "research retry backoff cannot be negative" in provider_check.fields["failures"]


def test_system_status_validates_openai_resilience_settings(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        openai_timeout_seconds=0,
        openai_retry_attempts=0,
        openai_retry_backoff_seconds=-0.1,
    )
    repo = RunRepository(settings.database_url)

    status = system_status(settings, repo)

    assert status.status == "fail"
    provider_check = next(check for check in status.checks if check.name == "provider_config")
    assert "OpenAI timeout must be greater than 0" in provider_check.fields["failures"]
    assert "OpenAI retry attempts must be at least 1" in provider_check.fields["failures"]
    assert "OpenAI retry backoff cannot be negative" in provider_check.fields["failures"]


def test_system_status_validates_scorecard_slo_settings(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        latency_slo_ms=0,
        min_source_count=0,
    )
    repo = RunRepository(settings.database_url)

    status = system_status(settings, repo)

    assert status.status == "fail"
    provider_check = next(check for check in status.checks if check.name == "provider_config")
    assert "latency SLO must be greater than 0" in provider_check.fields["failures"]
    assert "minimum source count must be at least 1" in provider_check.fields["failures"]


def test_system_status_validates_token_budget_settings(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        token_budget_per_run=0,
    )
    repo = RunRepository(settings.database_url)

    status = system_status(settings, repo)

    assert status.status == "fail"
    provider_check = next(check for check in status.checks if check.name == "provider_config")
    assert "token budget per run must be at least 1" in provider_check.fields["failures"]
