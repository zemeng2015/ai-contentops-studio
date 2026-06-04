from __future__ import annotations

import os
from pathlib import Path

from contentops_core.models import (
    ReleaseApprovalDecision,
    ReleaseEvidenceBundle,
    ReleaseGateItem,
    ReleaseGateListResponse,
    ReleaseGateReport,
)
from contentops_core.release_evidence import build_release_evidence
from contentops_core.repository import RunRepository
from contentops_core.review import ReviewService
from contentops_core.settings import Settings


def release_gate(
    *,
    settings: Settings,
    repository: RunRepository,
    review_service: ReviewService,
    window_size: int = 100,
    git_sha: str | None = None,
    require_approval: bool = True,
) -> ReleaseGateReport:
    resolved_git_sha = git_sha or os.getenv("GITHUB_SHA") or os.getenv("CONTENTOPS_GIT_SHA")
    bundle = build_release_evidence(
        settings=settings,
        repository=repository,
        review_service=review_service,
        window_size=window_size,
        git_sha=resolved_git_sha,
    )
    checks = [
        _release_readiness_check(bundle),
        _deployment_preflight_check(bundle),
        _approval_check(bundle, require_approval),
        _approval_git_sha_check(bundle, resolved_git_sha, require_approval),
    ]
    status = _gate_status(checks)
    return ReleaseGateReport(
        status=status,
        can_deploy=status == "pass",
        git_sha=resolved_git_sha,
        checks=checks,
        release_evidence=bundle.summary,
        latest_release_approval=bundle.latest_release_approval,
    )


def write_release_gate_report(report: ReleaseGateReport, artifact_root: Path) -> Path:
    directory = release_gate_dir(artifact_root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_release_gate_report_id(report)}.json"
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def list_release_gate_reports(
    artifact_root: Path,
    *,
    limit: int = 20,
    offset: int = 0,
) -> ReleaseGateListResponse:
    reports = sorted(
        (_read_release_gate_report(path) for path in _release_gate_report_paths(artifact_root)),
        key=lambda report: report.generated_at,
        reverse=True,
    )
    return ReleaseGateListResponse(
        items=reports[offset : offset + limit],
        total=len(reports),
        limit=limit,
        offset=offset,
    )


def release_gate_dir(artifact_root: Path) -> Path:
    return artifact_root / "release-gates"


def _release_readiness_check(bundle: ReleaseEvidenceBundle) -> ReleaseGateItem:
    status = "pass" if bundle.summary.can_release else "fail"
    return ReleaseGateItem(
        name="release_readiness",
        status=status,
        message=(
            "Release readiness gates pass."
            if status == "pass"
            else "Release readiness gates block deployment."
        ),
        evidence={
            "release_status": bundle.summary.release_status,
            "can_release": bundle.summary.can_release,
        },
    )


def _deployment_preflight_check(bundle: ReleaseEvidenceBundle) -> ReleaseGateItem:
    status = "pass" if bundle.deployment_check.can_deploy else "fail"
    return ReleaseGateItem(
        name="deployment_preflight",
        status=status,
        message=(
            "Deployment preflight checks pass."
            if status == "pass"
            else "Deployment preflight checks block deployment."
        ),
        evidence={
            "deployment_status": bundle.deployment_check.status,
            "can_deploy": bundle.deployment_check.can_deploy,
        },
    )


def _approval_check(bundle: ReleaseEvidenceBundle, require_approval: bool) -> ReleaseGateItem:
    approval = bundle.latest_release_approval
    if approval is None:
        status = "fail" if require_approval else "warn"
        return ReleaseGateItem(
            name="release_approval",
            status=status,
            message=(
                "No release approval recorded."
                if require_approval
                else "No release approval recorded; approval requirement disabled."
            ),
            evidence={"required": require_approval},
        )
    approved = approval.decision == ReleaseApprovalDecision.APPROVED
    status = "pass" if approved else "fail"
    return ReleaseGateItem(
        name="release_approval",
        status=status,
        message=(
            "Latest release approval allows deployment."
            if approved
            else "Latest release approval rejects deployment."
        ),
        evidence={
            "approval_id": approval.approval_id,
            "decision": approval.decision.value,
            "approver": approval.approver,
            "force": approval.force,
            "approved_at": approval.approved_at.isoformat(),
        },
    )


def _approval_git_sha_check(
    bundle: ReleaseEvidenceBundle,
    git_sha: str | None,
    require_approval: bool,
) -> ReleaseGateItem:
    approval = bundle.latest_release_approval
    if approval is None:
        status = "fail" if require_approval else "warn"
        return ReleaseGateItem(
            name="approval_git_sha",
            status=status,
            message="No release approval exists to compare with the current git SHA.",
            evidence={"git_sha": git_sha, "required": require_approval},
        )
    if git_sha is None:
        return ReleaseGateItem(
            name="approval_git_sha",
            status="warn",
            message="No git SHA provided; approval commit cannot be compared.",
            evidence={"approval_git_sha": approval.git_sha},
        )
    matches = approval.git_sha == git_sha
    return ReleaseGateItem(
        name="approval_git_sha",
        status="pass" if matches else "fail",
        message=(
            "Release approval matches the current git SHA."
            if matches
            else "Release approval does not match the current git SHA."
        ),
        evidence={"approval_git_sha": approval.git_sha, "git_sha": git_sha},
    )


def _gate_status(checks: list[ReleaseGateItem]) -> str:
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "pass"


def _release_gate_report_paths(artifact_root: Path) -> list[Path]:
    directory = release_gate_dir(artifact_root)
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


def _read_release_gate_report(path: Path) -> ReleaseGateReport:
    return ReleaseGateReport.model_validate_json(path.read_text(encoding="utf-8"))


def _release_gate_report_id(report: ReleaseGateReport) -> str:
    marker = report.git_sha or f"{report.generated_at:%Y%m%dT%H%M%SZ}"
    safe_marker = "".join(char if char.isalnum() or char in ".-_" else "-" for char in marker)
    return f"{report.generated_at:%Y%m%dT%H%M%SZ}-{safe_marker[:24]}"
