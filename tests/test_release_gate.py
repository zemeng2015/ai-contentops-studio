from __future__ import annotations

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


def test_release_gate_reports_can_be_persisted_and_listed(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    report = release_gate(
        settings=settings,
        repository=RunRepository(settings.database_url),
        review_service=build_review_service(settings),
        git_sha="history-sha",
        require_approval=False,
    )

    path = write_release_gate_report(report, settings.artifact_root)
    reports = list_release_gate_reports(settings.artifact_root)

    assert path.exists()
    assert reports.total == 1
    assert reports.items[0].git_sha == "history-sha"
