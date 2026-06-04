from __future__ import annotations

import json
from pathlib import Path

import pytest
from contentops_core.factory import build_review_service
from contentops_core.models import ReleaseApprovalDecision, ReleaseApprovalRequest
from contentops_core.release_approvals import approve_release, list_release_approvals
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings


def test_release_approval_records_release_evidence_snapshot(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    repository = RunRepository(settings.database_url)

    record = approve_release(
        settings=settings,
        repository=repository,
        review_service=build_review_service(settings),
        request=ReleaseApprovalRequest(
            decision=ReleaseApprovalDecision.APPROVED,
            approver="zack",
            notes="Ready for production rollout.",
        ),
        git_sha="release-sha",
    )

    approval_path = settings.artifact_root / "release-approvals" / f"{record.approval_id}.json"
    payload = json.loads(approval_path.read_text(encoding="utf-8"))
    approvals = list_release_approvals(settings.artifact_root)

    assert record.release_id == "release-sha"
    assert record.git_sha == "release-sha"
    assert record.approver == "zack"
    assert record.can_release is True
    assert record.can_deploy is True
    assert len(record.evidence_sha256) == 64
    assert "deployment_check.json" in record.evidence_files
    assert payload["decision"] == "approved"
    assert approvals.total == 1
    assert approvals.items[0].approval_id == record.approval_id


def test_release_approval_blocks_failed_release_without_force(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
        artifact_store_provider="s3",
        artifact_s3_bucket=None,
    )

    with pytest.raises(ValueError, match="Release readiness must pass"):
        approve_release(
            settings=settings,
            repository=RunRepository(settings.database_url),
            review_service=build_review_service(settings),
            request=ReleaseApprovalRequest(decision=ReleaseApprovalDecision.APPROVED),
        )

    forced = approve_release(
        settings=settings,
        repository=RunRepository(settings.database_url),
        review_service=build_review_service(settings),
        request=ReleaseApprovalRequest(
            decision=ReleaseApprovalDecision.APPROVED,
            approver="incident-commander",
            force=True,
        ),
    )

    assert forced.force is True
    assert forced.can_release is False
