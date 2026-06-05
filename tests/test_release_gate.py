from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.jobs import (
    JobExecutionReport,
    JobRunResult,
    create_scheduled_workflow_review_archive,
    job_execution_dir,
    scheduled_workflow_review_report,
    verify_scheduled_workflow_review_manifest,
    write_job_execution_report,
    write_scheduled_workflow_pr_metadata,
    write_scheduled_workflow_review_manifest,
    write_scheduled_workflow_review_markdown,
)
from contentops_core.models import ReleaseApprovalDecision, ReleaseApprovalRequest, RunRequest
from contentops_core.release_approvals import approve_release
from contentops_core.release_gate import (
    list_release_gate_reports,
    release_gate,
    write_release_gate_report,
)
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings


def test_release_gate_requires_approval_by_default(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )

    report = release_gate(
        settings=settings,
        repository=RunRepository(settings.database_url),
        review_service=build_review_service(settings),
        git_sha="release-sha",
    )

    assert report.status == "fail"
    assert report.can_deploy is False
    approval_check = next(check for check in report.checks if check.name == "release_approval")
    assert approval_check.status == "fail"
    assert approval_check.remediation_steps
    assert "release-approve" in approval_check.remediation_steps[1]


def test_release_gate_passes_with_matching_approval(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)
    approval = approve_release(
        settings=settings,
        repository=repository,
        review_service=service,
        request=ReleaseApprovalRequest(
            decision=ReleaseApprovalDecision.APPROVED,
            approver="zack",
            notes="Deploy this commit.",
        ),
        git_sha="release-sha",
    )

    report = release_gate(
        settings=settings,
        repository=repository,
        review_service=service,
        git_sha="release-sha",
    )

    assert report.status == "pass"
    assert report.can_deploy is True
    assert report.latest_release_approval is not None
    assert report.latest_release_approval.approval_id == approval.approval_id
    assert report.config_audit is not None
    assert report.config_audit.redacted is True
    check_names = {check.name for check in report.checks}
    assert "configuration_audit" in check_names
    assert "content_distribution" in check_names
    assert "retention_archive_governance" in check_names
    assert "scheduled_review_packages" in check_names


def test_release_gate_warns_for_dirty_distribution_assets(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=site_dir,
    )
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)
    _write_distribution_manifest(site_dir, dirty=True)
    approve_release(
        settings=settings,
        repository=repository,
        review_service=service,
        request=ReleaseApprovalRequest(
            decision=ReleaseApprovalDecision.APPROVED,
            approver="zack",
            notes="Distribution evidence reviewed.",
        ),
        git_sha="release-sha",
    )

    report = release_gate(
        settings=settings,
        repository=repository,
        review_service=service,
        git_sha="release-sha",
    )

    distribution_check = next(
        check for check in report.checks if check.name == "content_distribution"
    )
    assert report.status == "warn"
    assert report.can_deploy is False
    assert distribution_check.status == "warn"
    assert distribution_check.evidence["dirty_git_manifests"] == [
        "content-distribution-manifest.json"
    ]
    assert "content-assets" in distribution_check.remediation_steps[0]


def test_release_gate_fails_when_published_content_drifts(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)
    pipeline = build_pipeline(settings)
    result = pipeline.run(RunRequest(topic="Release gate publish drift"))
    service.approve(result.run.id, reviewer="zack")
    service.publish(result.run.id)
    approve_release(
        settings=settings,
        repository=repository,
        review_service=service,
        request=ReleaseApprovalRequest(
            decision=ReleaseApprovalDecision.APPROVED,
            approver="zack",
            notes="Approved before drift.",
        ),
        git_sha="release-sha",
    )
    target_file = next(settings.site_output_dir.glob("*.html"))
    target_file.write_text("manual edit after publish", encoding="utf-8")

    report = release_gate(
        settings=settings,
        repository=repository,
        review_service=service,
        git_sha="release-sha",
    )

    publish_check = next(check for check in report.checks if check.name == "publish_verification")
    assert report.status == "fail"
    assert report.can_deploy is False
    assert publish_check.status == "fail"
    assert publish_check.evidence["drift_count"] == 1
    assert publish_check.evidence["drifting_run_ids"] == [result.run.id]
    assert "verify-publish" in publish_check.remediation_steps[0]


def test_release_gate_fails_when_approval_git_sha_does_not_match(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)
    approve_release(
        settings=settings,
        repository=repository,
        review_service=service,
        request=ReleaseApprovalRequest(decision=ReleaseApprovalDecision.APPROVED),
        git_sha="approved-sha",
    )

    report = release_gate(
        settings=settings,
        repository=repository,
        review_service=service,
        git_sha="current-sha",
    )

    failed_checks = {check.name for check in report.checks if check.status == "fail"}
    assert report.status == "fail"
    assert report.can_deploy is False
    assert "approval_git_sha" in failed_checks


def test_release_gate_fails_when_required_config_is_missing(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        generator_provider="openai",
        openai_api_key=None,
    )
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)
    approve_release(
        settings=settings,
        repository=repository,
        review_service=service,
        request=ReleaseApprovalRequest(decision=ReleaseApprovalDecision.APPROVED, force=True),
        git_sha="release-sha",
    )

    report = release_gate(
        settings=settings,
        repository=repository,
        review_service=service,
        git_sha="release-sha",
    )

    failed_checks = {check.name for check in report.checks if check.status == "fail"}
    config_check = next(check for check in report.checks if check.name == "configuration_audit")

    assert report.status == "fail"
    assert report.can_deploy is False
    assert "configuration_audit" in failed_checks
    assert config_check.evidence["failed_items"] == ["openai_api_key"]
    assert config_check.remediation_steps
    assert "config-audit" in config_check.remediation_steps[0]
    assert report.config_audit is not None
    assert report.config_audit.status == "fail"


def test_release_gate_fails_with_pending_source_reviews(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)
    _write_source_review(
        settings.artifact_root / "20260605-release-source-review-run123",
        decision="needs_review",
    )

    report = release_gate(
        settings=settings,
        repository=repository,
        review_service=service,
        git_sha="source-review-sha",
        require_approval=False,
    )

    source_review_check = next(
        check for check in report.checks if check.name == "source_review_governance"
    )
    assert report.status == "fail"
    assert report.can_deploy is False
    assert source_review_check.status == "fail"
    assert source_review_check.evidence["needs_review_count"] == 1
    assert "source review dashboard" in source_review_check.remediation_steps[0]
    assert report.release_evidence.can_release is False


def test_release_gate_fails_when_scheduled_review_package_verification_fails(
    tmp_path: Path,
) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)
    receipt = JobExecutionReport(
        name="scheduled-review-gate",
        total=1,
        succeeded=1,
        failed=0,
        results=[
            JobRunResult(
                job_name="review",
                topic="Scheduled review gate",
                publish=False,
                run_id="run-scheduled-gate",
                status="needs_review",
            )
        ],
    )
    write_job_execution_report(receipt, job_execution_dir(settings.artifact_root))
    scheduled_dir = settings.artifact_root / "scheduled"
    scheduled_dir.mkdir(parents=True)
    operations_console_path = scheduled_dir / "daily-operations-console.json"
    operations_console_path.write_text("{}", encoding="utf-8")
    review = scheduled_workflow_review_report(
        job_execution_dir(settings.artifact_root),
        limit=5,
        operations_console={"status": "pass"},
    )
    markdown_path = write_scheduled_workflow_review_markdown(
        review,
        scheduled_dir / "daily-review.md",
    )
    metadata_path = write_scheduled_workflow_pr_metadata(
        review,
        scheduled_dir / "daily-pr-metadata.json",
    )
    manifest_path = write_scheduled_workflow_review_manifest(
        review,
        scheduled_dir / "daily-review-manifest.json",
        review_markdown_path=markdown_path,
        pr_metadata_path=metadata_path,
        operations_console_path=operations_console_path,
    )
    markdown_path.write_text("manual drift", encoding="utf-8")
    verification = verify_scheduled_workflow_review_manifest(manifest_path)
    (scheduled_dir / "daily-review-manifest-verification.json").write_text(
        verification.model_dump_json(indent=2),
        encoding="utf-8",
    )

    report = release_gate(
        settings=settings,
        repository=repository,
        review_service=service,
        git_sha="scheduled-review-fail-sha",
        require_approval=False,
    )

    scheduled_check = next(
        check for check in report.checks if check.name == "scheduled_review_packages"
    )
    assert report.status == "fail"
    assert report.can_deploy is False
    assert scheduled_check.status == "fail"
    assert scheduled_check.evidence["failed_count"] == 1
    assert scheduled_check.evidence["failed_package_ids"]
    assert "/dashboard/scheduled-reviews" in scheduled_check.remediation_steps[0]


def test_release_gate_warns_when_scheduled_review_archive_is_missing(
    tmp_path: Path,
) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)
    receipt = JobExecutionReport(
        name="scheduled-review-archive-missing",
        total=1,
        succeeded=1,
        failed=0,
        results=[
            JobRunResult(
                job_name="review",
                topic="Scheduled review archive missing",
                publish=False,
                run_id="run-scheduled-archive-missing",
                status="needs_review",
            )
        ],
    )
    write_job_execution_report(receipt, job_execution_dir(settings.artifact_root))
    scheduled_dir = settings.artifact_root / "scheduled"
    scheduled_dir.mkdir(parents=True)
    operations_console_path = scheduled_dir / "daily-operations-console.json"
    operations_console_path.write_text("{}", encoding="utf-8")
    review = scheduled_workflow_review_report(
        job_execution_dir(settings.artifact_root),
        limit=5,
        operations_console={"status": "pass"},
    )
    markdown_path = write_scheduled_workflow_review_markdown(
        review,
        scheduled_dir / "daily-review.md",
    )
    metadata_path = write_scheduled_workflow_pr_metadata(
        review,
        scheduled_dir / "daily-pr-metadata.json",
    )
    manifest_path = write_scheduled_workflow_review_manifest(
        review,
        scheduled_dir / "daily-review-manifest.json",
        review_markdown_path=markdown_path,
        pr_metadata_path=metadata_path,
        operations_console_path=operations_console_path,
    )
    verification = verify_scheduled_workflow_review_manifest(manifest_path)
    (scheduled_dir / "daily-review-manifest-verification.json").write_text(
        verification.model_dump_json(indent=2),
        encoding="utf-8",
    )

    report = release_gate(
        settings=settings,
        repository=repository,
        review_service=service,
        git_sha="scheduled-review-warn-sha",
        require_approval=False,
    )

    scheduled_check = next(
        check for check in report.checks if check.name == "scheduled_review_packages"
    )
    assert report.status == "warn"
    assert report.can_deploy is False
    assert scheduled_check.status == "warn"
    assert scheduled_check.evidence["missing_archive_package_ids"]
    assert "scheduled-workflow-archive" in scheduled_check.remediation_steps[0]


def test_release_gate_fails_when_scheduled_review_package_mirror_fails(
    tmp_path: Path,
) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)
    receipt = JobExecutionReport(
        name="scheduled-review-mirror-fail",
        total=1,
        succeeded=1,
        failed=0,
        results=[
            JobRunResult(
                job_name="review",
                topic="Scheduled review mirror fail",
                publish=False,
                run_id="run-scheduled-mirror-fail",
                status="needs_review",
            )
        ],
    )
    write_job_execution_report(receipt, job_execution_dir(settings.artifact_root))
    scheduled_dir = settings.artifact_root / "scheduled"
    scheduled_dir.mkdir(parents=True)
    operations_console_path = scheduled_dir / "daily-operations-console.json"
    operations_console_path.write_text("{}", encoding="utf-8")
    review = scheduled_workflow_review_report(
        job_execution_dir(settings.artifact_root),
        limit=5,
        operations_console={"status": "pass"},
    )
    markdown_path = write_scheduled_workflow_review_markdown(
        review,
        scheduled_dir / "daily-review.md",
    )
    metadata_path = write_scheduled_workflow_pr_metadata(
        review,
        scheduled_dir / "daily-pr-metadata.json",
    )
    manifest_path = write_scheduled_workflow_review_manifest(
        review,
        scheduled_dir / "daily-review-manifest.json",
        review_markdown_path=markdown_path,
        pr_metadata_path=metadata_path,
        operations_console_path=operations_console_path,
    )
    verification = verify_scheduled_workflow_review_manifest(manifest_path)
    (scheduled_dir / "daily-review-manifest-verification.json").write_text(
        verification.model_dump_json(indent=2),
        encoding="utf-8",
    )
    archive_report = create_scheduled_workflow_review_archive(
        manifest_path,
        scheduled_dir / "daily-review-package.zip",
    )
    (scheduled_dir / "daily-review-package.json").write_text(
        archive_report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (scheduled_dir / "s3-mirror-log.json").write_text(
        json.dumps(
            [
                {
                    "run_id": "scheduled-reviews/mirror-fail",
                    "artifact_name": "daily-review-package.zip",
                    "provider": "s3",
                    "bucket": "contentops-test-bucket",
                    "key": "contentops-artifacts/scheduled-reviews/mirror-fail.zip",
                    "content_type": "application/zip",
                    "status": "failed",
                    "error": "AccessDenied",
                }
            ]
        ),
        encoding="utf-8",
    )

    report = release_gate(
        settings=settings,
        repository=repository,
        review_service=service,
        git_sha="scheduled-review-mirror-fail-sha",
        require_approval=False,
    )

    scheduled_check = next(
        check for check in report.checks if check.name == "scheduled_review_packages"
    )
    assert report.status == "fail"
    assert report.can_deploy is False
    assert scheduled_check.status == "fail"
    assert scheduled_check.evidence["failed_s3_mirror_package_ids"]
    assert "s3-mirror-log.json" in scheduled_check.remediation_steps[0]


def test_release_gate_warns_when_retention_candidates_lack_archive(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)
    result = build_pipeline(settings).run(RunRequest(topic="Old retention candidate"))
    result.run.updated_at = datetime.now(UTC) - timedelta(days=120)
    repository.save(result.run)

    report = release_gate(
        settings=settings,
        repository=repository,
        review_service=service,
        git_sha="retention-warn-sha",
        require_approval=False,
    )

    retention_check = next(
        check for check in report.checks if check.name == "retention_archive_governance"
    )
    assert retention_check.status == "warn"
    assert retention_check.evidence["candidate_count"] == 1
    assert retention_check.evidence["archive_receipt_count"] == 0
    assert "retention-archive" in retention_check.remediation_steps[0]


def test_release_gate_passes_when_retention_archive_exists(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)
    result = build_pipeline(settings).run(RunRequest(topic="Archived retention candidate"))
    result.run.updated_at = datetime.now(UTC) - timedelta(days=120)
    repository.save(result.run)
    service.retention_archive(retention_days=90)

    report = release_gate(
        settings=settings,
        repository=repository,
        review_service=service,
        git_sha="retention-pass-sha",
        require_approval=False,
    )

    retention_check = next(
        check for check in report.checks if check.name == "retention_archive_governance"
    )
    assert retention_check.status == "pass"
    assert retention_check.evidence["candidate_count"] == 1
    assert retention_check.evidence["non_dry_run_archive_count"] == 1


def test_release_gate_reports_can_be_persisted_and_listed(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)
    warning_report = release_gate(
        settings=settings,
        repository=repository,
        review_service=service,
        git_sha="history-warn-sha",
        require_approval=False,
    )
    warning_report.generated_at = datetime(2026, 6, 5, 10, 0, tzinfo=UTC)
    failing_report = release_gate(
        settings=settings,
        repository=repository,
        review_service=service,
        git_sha="history-fail-sha",
    )
    failing_report.generated_at = datetime(2026, 6, 5, 11, 0, tzinfo=UTC)

    write_release_gate_report(warning_report, settings.artifact_root)
    path = write_release_gate_report(failing_report, settings.artifact_root)
    reports = list_release_gate_reports(settings.artifact_root)

    assert path.exists()
    assert reports.total == 2
    assert reports.items[0].git_sha == "history-fail-sha"
    assert reports.summary.total_reports == 2
    assert reports.summary.warn_count == 1
    assert reports.summary.fail_count == 1
    assert reports.summary.blocked_count == 2
    assert reports.summary.pass_rate == 0
    assert reports.summary.latest_status == "fail"
    assert reports.summary.consecutive_failures == 1
    assert reports.summary.most_common_failed_checks[0].name == "release_approval"


def _write_source_review(run_dir: Path, decision: str) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "source-review.json").write_text(
        json.dumps(
            [
                {
                    "source_key": "https://example.com/source",
                    "source_title": "Example source",
                    "decision": decision,
                    "reviewer": "zack",
                    "notes": "Release gate test.",
                    "decided_at": "2026-06-05T00:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )


def _write_distribution_manifest(site_dir: Path, dirty: bool) -> None:
    (site_dir / "content-distribution-manifest.json").write_text(
        json.dumps(
            {
                "manifest_type": "content_distribution",
                "output_dir": str(site_dir),
                "assets": [
                    {"relative_path": "feed.xml", "sha256": "feed-sha"},
                    {"relative_path": "promotion-brief.md", "sha256": "brief-sha"},
                    {
                        "relative_path": "content-distribution-manifest.json",
                        "sha256": "manifest-sha",
                    },
                ],
                "git": {"is_repository": True, "branch": "main", "dirty": dirty},
            }
        ),
        encoding="utf-8",
    )
