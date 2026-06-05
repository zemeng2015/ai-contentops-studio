from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from contentops_core.factory import build_review_service
from contentops_core.models import ReleaseApprovalDecision, ReleaseApprovalRequest
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
    assert "release_approval" in {
        check.name for check in report.checks if check.status == "fail"
    }


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
    assert "configuration_audit" in {check.name for check in report.checks}


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
    assert report.release_evidence.can_release is False


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
