from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from contentops_core.config_audit import config_audit
from contentops_core.models import (
    ConfigAuditReport,
    ReleaseApprovalDecision,
    ReleaseEvidenceBundle,
    ReleaseGateFailureSummary,
    ReleaseGateHistorySummary,
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
    audit = config_audit(settings)
    bundle = build_release_evidence(
        settings=settings,
        repository=repository,
        review_service=review_service,
        window_size=window_size,
        git_sha=resolved_git_sha,
    )
    checks = [
        _release_readiness_check(bundle),
        _source_review_governance_check(bundle),
        _deployment_preflight_check(bundle),
        _configuration_audit_check(audit),
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
        config_audit=audit,
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
        summary=_release_gate_history_summary(reports),
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
        remediation_steps=(
            []
            if status == "pass"
            else [
                "Open the release evidence dashboard and review failing readiness checks.",
                "Resolve quality, budget, incident, source review, or operator security blockers.",
                "Regenerate release evidence after fixes are applied.",
            ]
        ),
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
        remediation_steps=(
            []
            if status == "pass"
            else [
                "Run `contentops deployment-check --json` to inspect failing preflight checks.",
                "Fix missing deployment capabilities, environment values, or infrastructure.",
                "Rerun the release gate after the deployment preflight is pass or warn.",
            ]
        ),
    )


def _source_review_governance_check(bundle: ReleaseEvidenceBundle) -> ReleaseGateItem:
    source_reviews = bundle.source_reviews
    if source_reviews.needs_review_count:
        return ReleaseGateItem(
            name="source_review_governance",
            status="fail",
            message="Pending source review decisions block deployment.",
            evidence={
                "total_decisions": source_reviews.total_decisions,
                "include_count": source_reviews.include_count,
                "exclude_count": source_reviews.exclude_count,
                "needs_review_count": source_reviews.needs_review_count,
            },
            remediation_steps=[
                "Open the source review dashboard for affected runs.",
                "Resolve each `needs_review` source as `include` or `exclude` with notes.",
                "Regenerate release evidence so source governance reflects the decisions.",
            ],
        )
    if source_reviews.exclude_count:
        return ReleaseGateItem(
            name="source_review_governance",
            status="pass",
            message="Source review decisions are resolved; excluded sources are documented.",
            evidence={
                "total_decisions": source_reviews.total_decisions,
                "include_count": source_reviews.include_count,
                "exclude_count": source_reviews.exclude_count,
            },
        )
    return ReleaseGateItem(
        name="source_review_governance",
        status="pass",
        message="No pending source review decisions block deployment.",
        evidence={
            "total_decisions": source_reviews.total_decisions,
            "needs_review_count": source_reviews.needs_review_count,
        },
    )


def _configuration_audit_check(audit: ConfigAuditReport) -> ReleaseGateItem:
    failed_items = [item.name for item in audit.items if item.status == "fail"]
    blocking = audit.status == "fail"
    return ReleaseGateItem(
        name="configuration_audit",
        status="fail" if blocking else "pass",
        message=(
            "Configuration audit has no blocking failures."
            if not blocking
            else "Configuration audit blocks deployment because required settings are missing."
        ),
        evidence={
            "audit_status": audit.status,
            "redacted": audit.redacted,
            "summary": audit.summary,
            "failed_items": failed_items,
        },
        remediation_steps=(
            []
            if not blocking
            else [
                "Run `contentops config-audit --json` to inspect missing required settings.",
                "Populate required environment variables or secret references.",
                "Rerun the release gate after the configuration audit no longer reports failures.",
            ]
        ),
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
            remediation_steps=(
                [
                    "Review the release evidence and deployment preflight output.",
                    "Record approval with `contentops release-approve --decision approved`.",
                    "Rerun `contentops release-gate --git-sha <sha> --record` after approval.",
                ]
                if require_approval
                else [
                    "Record release approval before using this report for production deployment.",
                    "Enable approval enforcement by omitting `--no-require-approval`.",
                ]
            ),
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
        remediation_steps=(
            []
            if approved
            else [
                "Review the rejection notes on the latest release approval.",
                "Fix the release blockers and record a new approved release decision.",
                "Rerun the release gate against the commit being deployed.",
            ]
        ),
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
            remediation_steps=(
                [
                    "Record a release approval for the commit being deployed.",
                    "Pass the deployment commit with `--git-sha` or set `CONTENTOPS_GIT_SHA`.",
                ]
                if require_approval
                else [
                    "Pass a git SHA when generating advisory release gate reports.",
                    "Record a matching approval before enforcing deployment.",
                ]
            ),
        )
    if git_sha is None:
        return ReleaseGateItem(
            name="approval_git_sha",
            status="warn",
            message="No git SHA provided; approval commit cannot be compared.",
            evidence={"approval_git_sha": approval.git_sha},
            remediation_steps=[
                "Pass `--git-sha <sha>` in CI/CD or set `CONTENTOPS_GIT_SHA`.",
                "Confirm the recorded approval was created for the same commit being deployed.",
            ],
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
        remediation_steps=(
            []
            if matches
            else [
                "Deploy the approved commit or record a new approval for the current git SHA.",
                "Confirm CI passes the reviewed SHA to `contentops release-gate --git-sha`.",
                "Avoid reusing approvals after new commits are pushed.",
            ]
        ),
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


def _release_gate_history_summary(
    reports: list[ReleaseGateReport],
) -> ReleaseGateHistorySummary:
    total = len(reports)
    status_counts = Counter(report.status for report in reports)
    deployable_count = sum(1 for report in reports if report.can_deploy)
    failed_checks = Counter(
        check.name
        for report in reports
        for check in report.checks
        if check.status == "fail"
    )
    consecutive_failures = 0
    for report in reports:
        if report.status != "fail":
            break
        consecutive_failures += 1
    return ReleaseGateHistorySummary(
        total_reports=total,
        pass_count=status_counts["pass"],
        warn_count=status_counts["warn"],
        fail_count=status_counts["fail"],
        deployable_count=deployable_count,
        blocked_count=total - deployable_count,
        pass_rate=(status_counts["pass"] / total) if total else 0,
        consecutive_failures=consecutive_failures,
        latest_status=reports[0].status if reports else None,
        latest_generated_at=reports[0].generated_at if reports else None,
        most_common_failed_checks=[
            ReleaseGateFailureSummary(name=name, count=count)
            for name, count in failed_checks.most_common(5)
        ],
    )


def _release_gate_report_id(report: ReleaseGateReport) -> str:
    marker = report.git_sha or f"{report.generated_at:%Y%m%dT%H%M%SZ}"
    safe_marker = "".join(char if char.isalnum() or char in ".-_" else "-" for char in marker)
    return f"{report.generated_at:%Y%m%dT%H%M%SZ}-{safe_marker[:24]}"
