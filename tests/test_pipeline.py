from __future__ import annotations

import json
from pathlib import Path
from subprocess import run
from zipfile import ZipFile

import pytest
from contentops_core.artifacts import S3MirroringArtifactStore
from contentops_core.diagnostics import (
    deployment_manifest,
    integration_smoke_dir,
    integration_smoke_plan,
    list_integration_smoke_reports,
    provider_health,
    run_integration_smoke,
    system_status,
)
from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.models import (
    RunRecord,
    RunRequest,
    RunStatus,
    SourceReviewDecision,
    SourceReviewRequest,
)
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings
from pydantic import SecretStr


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
    assert (result.run.artifact_dir / "generation-receipt.json").exists()
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
    generation_receipt = review_service.generation_receipt(result.run.id)
    original_request = review_service.request(result.run.id)
    approved = review_service.approve(
        result.run.id,
        reviewer="zack",
        notes="Looks grounded enough to publish.",
    )
    published = review_service.publish(result.run.id)
    approval = review_service.approval(result.run.id)
    receipt = review_service.publish_receipt(result.run.id)
    verification = review_service.verify_publish(result.run.id)
    incident_report = review_service.incident_report(result.run.id)
    incident_reports = review_service.incident_reports(limit=5)
    operations_summary = review_service.operations_summary()
    retention_report = review_service.retention_report(retention_days=3650)
    audit_events = review_service.audit_log(result.run.id)
    global_audit_events = review_service.audit_events(action="publish")
    notifications = review_service.notification_log(result.run.id)

    assert "draft.json" in artifacts
    assert "eval-report.json" in artifacts
    assert "approval.json" not in artifacts
    assert manifest.run_id == result.run.id
    assert manifest.artifacts["draft.json"].size_bytes > 0
    assert len(manifest.artifacts["draft.json"].sha256) == 64
    assert plan.ready is True
    assert len(plan.items) == 4
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
    assert generation_receipt is not None
    assert generation_receipt.provider == "template"
    assert generation_receipt.status == "completed"
    assert generation_receipt.total_tokens is not None
    assert cost_report.estimated_total_tokens == generation_receipt.total_tokens
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
    assert len(receipt.file_changes) == 4
    assert {change.action for change in receipt.file_changes} == {"created"}
    assert all(change.after_sha256 for change in receipt.file_changes)
    assert all("roll back" in change.rollback_hint for change in receipt.file_changes)
    assert verification.verified is True
    assert len(verification.items) == 4
    assert all(item.exists for item in verification.items)
    assert all(item.matches_receipt for item in verification.items)
    assert (result.run.artifact_dir / "publish-verification.json").exists()
    assert incident_report.severity.value == "info"
    assert incident_report.requires_action is False
    assert incident_reports.action_required >= 0
    assert operations_summary.total_runs == 1
    assert operations_summary.published_count == 1
    assert operations_summary.action_required_incidents == 0
    assert operations_summary.quality_pass_rate == 1
    assert operations_summary.budget_pass_rate == 1
    operations_trends = review_service.operations_trends(days=7)
    active_buckets = [bucket for bucket in operations_trends.buckets if bucket.run_count]
    assert operations_trends.summary.total_runs == 1
    assert len(active_buckets) == 1
    assert active_buckets[0].published_count == 1
    assert active_buckets[0].quality_pass_rate == 1
    assert active_buckets[0].budget_pass_rate == 1
    assert active_buckets[0].estimated_total_tokens > 0
    assert retention_report.total_runs_scanned == 1
    assert retention_report.total_size_bytes > 0
    assert retention_report.candidate_count == 0
    assert [event.action for event in audit_events] == ["approve", "publish"]
    assert global_audit_events.total == 1
    assert global_audit_events.items[0].run_id == result.run.id
    assert global_audit_events.action_counts["publish"] == 1
    assert audit_events[0].actor == "zack"
    assert audit_events[1].new_status == RunStatus.PUBLISHED
    assert audit_events[1].fields["changed_files"] == 4
    publish_index = json.loads(
        (tmp_path / "site" / "contentops-publish-index.json").read_text(encoding="utf-8")
    )
    assert publish_index["entries"][0]["run_id"] == result.run.id
    assert publish_index["entries"][0]["quality"]["publish_ready"] is True
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


def test_review_service_exports_homepage_handoff_bundle(tmp_path: Path) -> None:
    homepage = tmp_path / "homepage"
    (homepage / "posts").mkdir(parents=True)
    _init_git_repo(homepage)
    (homepage / "index.html").write_text(
        '<html><body><section id="writing"><div class="post-grid"></div></section></body></html>',
        encoding="utf-8",
    )
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        publisher_provider="homepage",
        homepage_repo_path=homepage,
        homepage_public_base_url="https://example.com",
        min_publish_score=0.5,
    )
    result = build_pipeline(settings).run(RunRequest(topic="Homepage handoff bundle"))
    review_service = build_review_service(settings)

    bundle_path = review_service.create_homepage_handoff(result.run.id)

    assert bundle_path.exists()
    with ZipFile(bundle_path) as bundle:
        names = set(bundle.namelist())
        manifest = json.loads(bundle.read("handoff-manifest.json"))
        plan = json.loads(bundle.read("publish-plan.json"))
        commands = bundle.read("suggested-git-commands.txt").decode("utf-8")

    assert "artifacts/draft.md" in names
    assert "artifacts/eval-report.json" in names
    assert manifest["bundle_type"] == "homepage_handoff"
    assert manifest["publish_plan"]["provider"] == "homepage"
    assert plan["metadata"]["git"]["is_repository"] is True
    assert "git -C" in commands


def test_review_service_blocks_approval_when_scorecard_fails(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        min_publish_score=0.5,
        min_source_count=999,
    )
    pipeline = build_pipeline(settings)
    result = pipeline.run(RunRequest(topic="Approval scorecard gate"))
    review_service = build_review_service(settings)

    with pytest.raises(ValueError, match="scorecard did not pass"):
        review_service.approve(result.run.id)


def test_source_review_exclusions_affect_scorecard_gate(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        min_publish_score=0.5,
        min_source_count=3,
    )
    pipeline = build_pipeline(settings)
    result = pipeline.run(RunRequest(topic="Source review gate"))
    review_service = build_review_service(settings)

    initial = review_service.scorecard(result.run.id)
    review_service.review_source(
        result.run.id,
        SourceReviewRequest(
            source_key="AI engineering pattern library",
            decision=SourceReviewDecision.EXCLUDE,
            reviewer="zack",
            notes="Not specific enough for this run.",
        ),
    )
    updated = review_service.scorecard(result.run.id)

    assert initial.source_count == 3
    assert initial.sources_slo_pass is True
    assert updated.source_count == 2
    assert updated.sources_slo_pass is False
    assert updated.overall_pass is False
    assert any("excluded by reviewer" in warning for warning in updated.warnings)
    with pytest.raises(ValueError, match="scorecard did not pass"):
        review_service.approve(result.run.id)


def test_pending_source_review_blocks_approval(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        min_publish_score=0.5,
    )
    pipeline = build_pipeline(settings)
    result = pipeline.run(RunRequest(topic="Pending source review gate"))
    review_service = build_review_service(settings)

    review_service.review_source(
        result.run.id,
        SourceReviewRequest(
            source_key="AI engineering pattern library",
            decision=SourceReviewDecision.NEEDS_REVIEW,
            reviewer="zack",
            notes="Needs source owner confirmation.",
        ),
    )
    scorecard = review_service.scorecard(result.run.id)

    assert scorecard.sources_slo_pass is False
    assert any("still pending" in warning for warning in scorecard.warnings)
    with pytest.raises(ValueError, match="scorecard did not pass"):
        review_service.approve(result.run.id)


def test_review_service_blocks_approval_when_token_budget_fails(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        min_publish_score=0.5,
        token_budget_per_run=1,
    )
    pipeline = build_pipeline(settings)
    result = pipeline.run(RunRequest(topic="Approval token budget gate"))
    review_service = build_review_service(settings)

    with pytest.raises(ValueError, match="token budget did not pass"):
        review_service.approve(result.run.id)


def test_incident_report_marks_failed_runs_critical(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        generator_provider="openai",
        openai_api_key=None,
    )
    repo = RunRepository(settings.database_url)
    pipeline = build_pipeline(
        Settings(
            artifact_root=tmp_path / "artifacts",
            database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
            site_output_dir=tmp_path / "site",
        )
    )
    result = pipeline.run(RunRequest(topic="Incident failed run seed"))
    failed = result.run
    failed.touch(RunStatus.FAILED)
    failed.error = "simulated incident"
    repo.save(failed)
    review_service = build_review_service(settings)

    incident = review_service.incident_report(failed.id)

    assert incident.severity.value == "critical"
    assert incident.requires_action is True
    assert any(signal.category == "run" for signal in incident.signals)


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
    assert len(rollback.restored_files) == 4
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
    assert len(rollback.deleted_files) == 4
    assert all(not Path(path).exists() for path in rollback.deleted_files)


def test_publish_verification_detects_modified_files(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        public_base_url="https://example.com",
        min_publish_score=0.5,
    )
    pipeline = build_pipeline(settings)
    review_service = build_review_service(settings)
    result = pipeline.run(RunRequest(topic="Publish verification drift"))
    review_service.approve(result.run.id, reviewer="zack")
    review_service.publish(result.run.id)
    receipt = review_service.publish_receipt(result.run.id)
    assert receipt is not None
    Path(receipt.file_changes[0].path).write_text("tampered", encoding="utf-8")

    verification = review_service.verify_publish(result.run.id)
    recovery_plan = review_service.publish_recovery_plan(result.run.id)
    recovery_execution = review_service.execute_publish_recovery(
        result.run.id,
        action="rollback",
        actor="zack",
        notes="Remove drifted publish.",
    )
    incident = review_service.incident_report(result.run.id)

    assert verification.verified is False
    assert any(not item.matches_receipt for item in verification.items)
    assert recovery_plan.verified is False
    assert recovery_plan.runnable is True
    assert recovery_plan.recommended_action == "manual_restore_or_republish"
    assert recovery_plan.file_actions[0].status == "mismatch"
    assert "rollback-publish" in recovery_plan.steps[3]
    assert (result.run.artifact_dir / "publish-recovery-plan.json").exists()
    assert recovery_execution.status == "completed"
    assert recovery_execution.action == "rollback"
    assert recovery_execution.rollback is not None
    assert recovery_execution.rollback.errors == []
    assert (result.run.artifact_dir / "publish-recovery-execution.json").exists()
    assert incident.severity.value == "info"
    assert incident.requires_action is False


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


def test_review_service_batch_publish_records_partial_results(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    pipeline = build_pipeline(settings)
    approved = pipeline.run(RunRequest(topic="Batch publish approved")).run
    blocked = pipeline.run(RunRequest(topic="Batch publish blocked")).run
    review_service = build_review_service(settings)
    review_service.approve(approved.id, reviewer="zack")

    result = review_service.publish_many([approved.id, blocked.id, "missing-run"])

    assert result.action == "publish"
    assert [item.status for item in result.results] == ["ok", "failed", "failed"]
    assert result.results[0].new_status == RunStatus.PUBLISHED
    assert "approved before publishing" in str(result.results[1].error)
    assert "Run not found" in str(result.results[2].error)
    assert review_service.publish_receipt(approved.id) is not None


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


def test_s3_artifact_store_writes_mirror_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads: list[dict[str, object]] = []

    class FakeS3Client:
        def upload_file(
            self,
            filename: str,
            bucket: str,
            key: str,
            ExtraArgs: dict[str, str],
        ) -> None:
            uploads.append(
                {
                    "filename": filename,
                    "bucket": bucket,
                    "key": key,
                    "extra_args": ExtraArgs,
                }
            )

    class FakeBoto3:
        @staticmethod
        def client(service: str) -> FakeS3Client:
            assert service == "s3"
            return FakeS3Client()

    monkeypatch.setattr("contentops_core.artifacts.importlib.import_module", lambda name: FakeBoto3)
    run = RunRecord.create(RunRequest(topic="Mirror receipts"), tmp_path / "artifacts")
    store = S3MirroringArtifactStore(tmp_path / "artifacts", "artifact-bucket", "prefix")
    store.prepare(run)

    store.write_text(run, "draft.md", "hello")

    mirror_log = store.read_text(run, "s3-mirror-log.json")
    assert uploads[-1]["bucket"] == "artifact-bucket"
    assert uploads[-1]["key"] == f"prefix/{run.id}/draft.md"
    assert '"artifact_name": "draft.md"' in mirror_log
    assert '"status": "mirrored"' in mirror_log


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
    assert provider_check.fields["research_readiness"]["scheduled_ready"] is False
    assert provider_check.fields["research_readiness"]["credential_required"] is True
    health = provider_health(settings)
    research = next(item for item in health.items if item.category == "research")
    assert health.status == "fail"
    assert research.name == "search"
    assert research.status == "fail"
    assert research.credential_required is True
    assert research.credential_configured is False
    assert "CONTENTOPS_RESEARCH_SEARCH_API_KEY" in research.remediation_steps[0]
    assert provider_check.fields["provider_health"]["summary"]["fail"] >= 1


def test_system_status_reports_github_research_readiness(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        research_provider="github",
        research_github_token="github-token",
    )
    repo = RunRepository(settings.database_url)

    status = system_status(settings, repo)

    provider_check = next(check for check in status.checks if check.name == "provider_config")
    readiness = provider_check.fields["research_readiness"]
    assert readiness["provider"] == "github"
    assert readiness["mode"] == "repository_intelligence"
    assert readiness["scheduled_ready"] is True
    assert readiness["credential_configured"] is True


def test_provider_health_includes_actionable_remediation_steps(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        research_provider="feed",
        research_feeds="",
        generator_provider="template",
        publisher_provider="homepage",
        homepage_repo_path=None,
    )

    health = provider_health(settings)

    research = next(item for item in health.items if item.category == "research")
    generator = next(item for item in health.items if item.category == "generator")
    publisher = next(item for item in health.items if item.category == "publisher")
    assert research.status == "warn"
    assert "CONTENTOPS_RESEARCH_FEEDS" in research.remediation_steps[0]
    assert generator.status == "warn"
    assert "CONTENTOPS_GENERATOR_PROVIDER=openai" in generator.remediation_steps[0]
    assert publisher.status == "fail"
    assert "CONTENTOPS_HOMEPAGE_REPO_PATH" in publisher.remediation_steps[0]


def test_deployment_manifest_reports_scheduled_research_capability(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        research_provider="github",
    )
    repo = RunRepository(settings.database_url)

    manifest = deployment_manifest(settings, repo)

    capability = next(
        item for item in manifest.capabilities if item.name == "scheduled_research_ready"
    )
    assert capability.status == "ok"
    assert "research_provider=github" in capability.evidence
    assert manifest.runtime["research_readiness"]["mode"] == "repository_intelligence"


def test_integration_smoke_plan_reports_missing_live_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CONTENTOPS_RUN_INTEGRATION", raising=False)
    monkeypatch.delenv("CONTENTOPS_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CONTENTOPS_RESEARCH_SEARCH_API_KEY", raising=False)
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        research_provider="search",
        research_search_api_key=None,
        homepage_repo_path=None,
    )

    report = integration_smoke_plan(settings)

    assert report.status == "warn"
    assert report.integration_enabled is False
    assert report.command == "pytest -m integration tests/test_integration_smoke.py"
    search = next(item for item in report.items if item.name == "search")
    assert search.status == "warn"
    assert "CONTENTOPS_RESEARCH_SEARCH_API_KEY" in search.missing_env
    assert "pytest -m integration" in search.command


def test_run_integration_smoke_writes_skip_report_for_missing_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CONTENTOPS_RUN_INTEGRATION", raising=False)
    monkeypatch.delenv("CONTENTOPS_OPENAI_API_KEY", raising=False)
    output_path = tmp_path / "smoke" / "report.json"

    report = run_integration_smoke(
        Settings(artifact_root=tmp_path / "artifacts"),
        selected=["openai"],
        output_path=output_path,
    )

    assert report.status == "warn"
    assert report.summary["skip"] == 1
    assert report.items[0].name == "openai"
    assert "CONTENTOPS_OPENAI_API_KEY" in report.items[0].missing_env
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["artifact_path"] == str(output_path)
    assert payload["items"][0]["status"] == "skip"
    history = list_integration_smoke_reports(tmp_path / "artifacts")
    assert history.total == 0


def test_integration_smoke_history_lists_recorded_reports(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    output_path = integration_smoke_dir(artifact_root) / "smoke.json"

    report = run_integration_smoke(
        Settings(artifact_root=artifact_root),
        selected=["feed"],
        output_path=output_path,
        dry_run=True,
    )
    history = list_integration_smoke_reports(artifact_root)

    assert report.status == "pass"
    assert history.total == 1
    assert history.summary.latest_status == "pass"
    assert history.items[0].artifact_path == str(output_path)
    assert history.items[0].items[0].status == "planned"


def test_system_status_reports_static_publishing_readiness(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        publisher_provider="static",
    )
    repo = RunRepository(settings.database_url)

    status = system_status(settings, repo)

    provider_check = next(check for check in status.checks if check.name == "provider_config")
    readiness = provider_check.fields["publishing_readiness"]
    assert readiness["provider"] == "static"
    assert readiness["mode"] == "filesystem_static_site"
    assert readiness["ready"] is True
    capability = next(
        item for item in deployment_manifest(settings, repo).capabilities
        if item.name == "publishing_recovery"
    )
    assert capability.status == "ok"
    assert "publisher_provider=static" in capability.evidence


def test_system_status_reports_homepage_publishing_marker(tmp_path: Path) -> None:
    homepage = tmp_path / "homepage"
    homepage.mkdir()
    (homepage / "index.html").write_text("<html><body>No grid yet</body></html>", encoding="utf-8")
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        publisher_provider="homepage",
        homepage_repo_path=homepage,
    )
    repo = RunRepository(settings.database_url)

    status = system_status(settings, repo)

    provider_check = next(check for check in status.checks if check.name == "provider_config")
    readiness = provider_check.fields["publishing_readiness"]
    assert status.status == "degraded"
    assert readiness["provider"] == "homepage"
    assert readiness["ready"] is False
    assert readiness["homepage_index_exists"] is True
    assert readiness["homepage_post_grid_marker"] is False
    assert any("post-grid marker" in warning for warning in readiness["warnings"])


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


def test_system_status_accepts_dedicated_read_key_for_read_protection(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        require_read_api_key=True,
        read_api_key=SecretStr("read-secret"),
        operator_api_key=SecretStr("write-secret"),
    )
    repo = RunRepository(settings.database_url)

    status = system_status(settings, repo)

    security_check = next(check for check in status.checks if check.name == "operator_security")
    assert security_check.status == "ok"
    assert security_check.fields["read_routes_protected"] is True
    assert security_check.fields["read_api_key_configured"] is True


def _init_git_repo(path: Path) -> None:
    run(["git", "-C", str(path), "init"], check=True, capture_output=True)
