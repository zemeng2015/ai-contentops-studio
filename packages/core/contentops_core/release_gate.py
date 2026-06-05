from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterable
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
        _publish_verification_check(bundle),
        _content_distribution_check(bundle),
        _scheduled_review_package_check(bundle),
        _retention_archive_governance_check(bundle, review_service),
        _worker_automation_health_check(bundle),
        _deployment_preflight_check(bundle),
        _integration_smoke_plan_check(bundle),
        _integration_smoke_history_check(bundle),
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
        deployment_checklist=_deployment_checklist(
            status=status,
            checks=checks,
            bundle=bundle,
            git_sha=resolved_git_sha,
        ),
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


def write_release_gate_checklist(report: ReleaseGateReport, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_release_gate_checklist_markdown(report), encoding="utf-8")
    return output_path


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


def _worker_automation_health_check(bundle: ReleaseEvidenceBundle) -> ReleaseGateItem:
    alerts = bundle.worker_execution_alerts
    recovery = bundle.worker_recovery_lineage
    trend_summary = alerts.get("trend_summary", {})
    signals = alerts.get("signals", [])
    severity = str(alerts.get("severity", "info"))
    action_required = bool(alerts.get("action_required", False))
    failed_jobs = _int_field(trend_summary, "failed_jobs")
    failed_executions = _int_field(trend_summary, "action_required")
    total_failed_executions = _int_field(recovery, "total_failed_executions")
    recovered_executions = _int_field(recovery, "recovered_execution_count")
    unrecovered_executions = _int_field(recovery, "unrecovered_execution_count")
    recovery_attempts = _int_field(recovery, "recovery_attempt_count")
    recovery_action_required = bool(recovery.get("action_required", False))
    top_failure_reasons = _string_field_list(
        reason.get("reason")
        for reason in trend_summary.get("top_failure_reasons", [])
        if isinstance(reason, dict)
    )
    latest_execution_ids = _string_field_list(
        signal.get("latest_execution_id")
        for signal in signals
        if isinstance(signal, dict)
    )
    evidence = {
        "severity": severity,
        "action_required": action_required,
        "failed_jobs": failed_jobs,
        "failed_executions": failed_executions,
        "recovery_total_failed_executions": total_failed_executions,
        "recovered_executions": recovered_executions,
        "unrecovered_executions": unrecovered_executions,
        "recovery_attempts": recovery_attempts,
        "recovery_action_required": recovery_action_required,
        "latest_execution_ids": latest_execution_ids,
        "top_failure_reasons": top_failure_reasons,
    }
    if unrecovered_executions > 0 or recovery_action_required:
        return ReleaseGateItem(
            name="worker_automation_health",
            status="fail",
            message="Recent worker failures still have unrecovered execution backlog.",
            evidence=evidence,
            remediation_steps=[
                "Open `/dashboard/job-execution-trends` and review worker alert signals.",
                "Run `contentops job-recovery-lineage --days 14` to inspect recovery backlog.",
                "Run `contentops job-recovery-plan <execution_id> --run` for unrecovered jobs.",
                "Regenerate release evidence and rerun the release gate after recovery succeeds.",
            ],
        )
    if severity == "critical" or failed_jobs > 0:
        return ReleaseGateItem(
            name="worker_automation_health",
            status="warn",
            message="Recent worker failures were recovered but should be reviewed before release.",
            evidence=evidence,
            remediation_steps=[
                "Open `/dashboard/job-execution-trends` and review the recovery lineage.",
                "Attach the successful recovery receipt to the release review trail.",
                "Monitor the next scheduled worker execution for repeated provider failures.",
            ],
        )
    if action_required or severity == "warning" or failed_executions > 0:
        return ReleaseGateItem(
            name="worker_automation_health",
            status="warn",
            message="Recent worker automation requires operator review.",
            evidence=evidence,
            remediation_steps=[
                "Open `/dashboard/job-execution-trends` and review action-required receipts.",
                "Resolve homepage handoff, delivery summary, or scheduled workflow warnings.",
                "Record a clean worker execution before the next production deployment.",
            ],
        )
    return ReleaseGateItem(
        name="worker_automation_health",
        status="pass",
        message="Recent worker automation has no release-blocking alerts.",
        evidence=evidence,
    )


def _integration_smoke_plan_check(bundle: ReleaseEvidenceBundle) -> ReleaseGateItem:
    plan = bundle.integration_smoke_plan
    missing_env = sorted(
        {
            env
            for item in plan.items
            for env in item.missing_env
            if env != "CONTENTOPS_RUN_INTEGRATION"
        }
    )
    evidence = {
        "status": plan.status,
        "integration_enabled": plan.integration_enabled,
        "command": plan.command,
        "missing_env": missing_env,
        "warn_count": plan.summary.get("warn", 0),
        "fail_count": plan.summary.get("fail", 0),
    }
    if plan.status == "fail":
        return ReleaseGateItem(
            name="integration_smoke_plan",
            status="fail",
            message="Live provider smoke planning has invalid provider configuration.",
            evidence=evidence,
            remediation_steps=[
                "Open `integration_smoke_plan.json` in release evidence.",
                "Fix invalid provider configuration before running live smoke tests.",
                "Regenerate release evidence and rerun `contentops release-gate`.",
            ],
        )
    if plan.status == "warn":
        return ReleaseGateItem(
            name="integration_smoke_plan",
            status="warn",
            message="Live provider smoke tests are not fully ready to run.",
            evidence=evidence,
            remediation_steps=[
                "Open `integration_smoke_plan.json` in release evidence.",
                "Set missing provider credentials or paths before live provider validation.",
                (
                    "Run `contentops integration-smoke-plan --json` and then the listed "
                    "pytest selectors."
                ),
            ],
        )
    return ReleaseGateItem(
        name="integration_smoke_plan",
        status="pass",
        message="Live provider smoke tests are planned and ready.",
        evidence=evidence,
    )


def _integration_smoke_history_check(bundle: ReleaseEvidenceBundle) -> ReleaseGateItem:
    smoke_runs = bundle.integration_smoke_runs
    latest = smoke_runs.items[0] if smoke_runs.items else None
    evidence: dict[str, object] = {
        "total_reports": smoke_runs.summary.total_reports,
        "latest_status": smoke_runs.summary.latest_status,
        "latest_generated_at": (
            smoke_runs.summary.latest_generated_at.isoformat()
            if smoke_runs.summary.latest_generated_at
            else None
        ),
        "pass_count": smoke_runs.summary.pass_count,
        "warn_count": smoke_runs.summary.warn_count,
        "fail_count": smoke_runs.summary.fail_count,
    }
    if latest is None:
        return ReleaseGateItem(
            name="integration_smoke_history",
            status="warn",
            message="No recorded integration smoke run is available for release review.",
            evidence=evidence,
            remediation_steps=[
                (
                    "Run `contentops integration-smoke-run --dry-run --record --json` "
                    "to record a plan."
                ),
                (
                    "After credentials are configured, run "
                    "`contentops integration-smoke-run --record --json`."
                ),
                "Regenerate release evidence and rerun `contentops release-gate`.",
            ],
        )
    latest_failures = [item.name for item in latest.items if item.status == "fail"]
    latest_skips = [item.name for item in latest.items if item.status == "skip"]
    latest_planned = [item.name for item in latest.items if item.status == "planned"]
    evidence.update(
        {
            "latest_artifact_path": latest.artifact_path,
            "latest_dry_run": latest.dry_run,
            "latest_integration_enabled": latest.integration_enabled,
            "latest_selected": latest.selected,
            "latest_summary": latest.summary,
            "latest_failures": latest_failures,
            "latest_skips": latest_skips,
            "latest_planned": latest_planned,
        }
    )
    if latest.status == "fail" or latest_failures:
        return ReleaseGateItem(
            name="integration_smoke_history",
            status="fail",
            message="The latest recorded integration smoke run failed.",
            evidence=evidence,
            remediation_steps=[
                "Open `integration_smoke_runs.json` in release evidence.",
                (
                    "Inspect the failed provider stdout/stderr tails and fix credentials "
                    "or provider access."
                ),
                "Rerun `contentops integration-smoke-run --record --json` after the fix.",
            ],
        )
    if latest.dry_run or latest.status == "warn" or latest_skips or latest_planned:
        return ReleaseGateItem(
            name="integration_smoke_history",
            status="warn",
            message="The latest integration smoke evidence is not a full live provider pass.",
            evidence=evidence,
            remediation_steps=[
                "Open `integration_smoke_runs.json` in release evidence.",
                (
                    "Configure missing provider credentials or homepage path if providers "
                    "were skipped."
                ),
                "Run `contentops integration-smoke-run --record --json` without `--dry-run`.",
            ],
        )
    return ReleaseGateItem(
        name="integration_smoke_history",
        status="pass",
        message="The latest recorded integration smoke run passed.",
        evidence=evidence,
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


def _content_distribution_check(bundle: ReleaseEvidenceBundle) -> ReleaseGateItem:
    distribution = bundle.content_distribution
    published_count = bundle.operations_summary.published_count
    if distribution.total == 0:
        if published_count == 0:
            return ReleaseGateItem(
                name="content_distribution",
                status="pass",
                message="No published content requires distribution assets.",
                evidence={
                    "published_count": published_count,
                    "distribution_manifest_count": distribution.total,
                },
            )
        return ReleaseGateItem(
            name="content_distribution",
            status="warn",
            message="Published content has no recorded distribution assets.",
            evidence={
                "published_count": published_count,
                "distribution_manifest_count": distribution.total,
            },
            remediation_steps=[
                "Run `contentops content-assets --output-dir <site-output>` after publishing.",
                "Review `promotion-brief.md` and deploy `feed.xml` plus "
                "`sitemap.xml` with the site.",
                "Regenerate release evidence so `content_distribution.json` is populated.",
            ],
        )
    incomplete = [
        item.manifest_path for item in distribution.items if item.asset_count < 4
    ]
    dirty = [
        item.manifest_path
        for item in distribution.items
        if item.git.get("is_repository") and item.git.get("dirty")
    ]
    status = "fail" if incomplete else "warn" if dirty else "pass"
    return ReleaseGateItem(
        name="content_distribution",
        status=status,
        message=(
            "Content distribution assets are recorded and clean."
            if status == "pass"
            else "Content distribution assets need operator review before deployment."
        ),
        evidence={
            "published_count": published_count,
            "distribution_manifest_count": distribution.total,
            "incomplete_manifests": incomplete,
            "dirty_git_manifests": dirty,
        },
        remediation_steps=(
            []
            if status == "pass"
            else [
                "Regenerate distribution assets with `contentops content-assets`.",
                "Confirm feed, sitemap, promotion brief, and distribution manifest are present.",
                "Commit or intentionally stage distribution asset changes before deployment.",
            ]
        ),
    )


def _publish_verification_check(bundle: ReleaseEvidenceBundle) -> ReleaseGateItem:
    verifications = bundle.publish_verifications
    if verifications.missing_receipt_count:
        return ReleaseGateItem(
            name="publish_verification",
            status="fail",
            message="Published runs are missing publish receipts.",
            evidence={
                "published_count": verifications.total,
                "verified_count": verifications.verified_count,
                "drift_count": verifications.drift_count,
                "missing_receipt_count": verifications.missing_receipt_count,
            },
            remediation_steps=[
                "Inspect published runs without `publish-receipt.json`.",
                "Republish through ContentOps or roll back orphaned published records.",
                "Regenerate release evidence after receipts are restored.",
            ],
        )
    if verifications.drift_count:
        return ReleaseGateItem(
            name="publish_verification",
            status="fail",
            message="Published content drift detected against publish receipts.",
            evidence={
                "published_count": verifications.total,
                "verified_count": verifications.verified_count,
                "drift_count": verifications.drift_count,
                "drifting_run_ids": [
                    item.run_id for item in verifications.items if not item.verified
                ],
            },
            remediation_steps=[
                "Run `contentops verify-publish <run_id>` for each drifting run.",
                "Restore expected files, republish approved content, or roll back the run.",
                "Regenerate release evidence once `publish-verification.json` is verified.",
            ],
        )
    return ReleaseGateItem(
        name="publish_verification",
        status="pass",
        message="Published content matches publish receipts.",
        evidence={
            "published_count": verifications.total,
            "verified_count": verifications.verified_count,
            "drift_count": verifications.drift_count,
            "missing_receipt_count": verifications.missing_receipt_count,
        },
    )


def _scheduled_review_package_check(bundle: ReleaseEvidenceBundle) -> ReleaseGateItem:
    packages = bundle.scheduled_review_packages
    failed = [
        item.id for item in packages.items if item.verification_status == "fail"
    ]
    missing_archives = [
        item.id
        for item in packages.items
        if item.verification_status == "pass" and not item.archive_exists
    ]
    failed_mirrors = [
        item.id for item in packages.items if item.s3_mirror_status == "failed"
    ]
    evidence = {
        "total": packages.total,
        "archived_count": packages.archived_count,
        "failed_count": packages.failed_count,
        "action_required_count": packages.action_required_count,
        "failed_package_ids": failed,
        "missing_archive_package_ids": missing_archives,
        "failed_s3_mirror_package_ids": failed_mirrors,
    }
    if failed:
        return ReleaseGateItem(
            name="scheduled_review_packages",
            status="fail",
            message="Scheduled review package verification failures block deployment.",
            evidence=evidence,
            remediation_steps=[
                "Open `/dashboard/scheduled-reviews` and inspect failed package verification.",
                (
                    "Regenerate the scheduled review manifest after missing or drifted files "
                    "are fixed."
                ),
                "Rerun `contentops scheduled-workflow-verify` and regenerate release evidence.",
            ],
        )
    if failed_mirrors:
        return ReleaseGateItem(
            name="scheduled_review_packages",
            status="fail",
            message="Scheduled review package S3 mirroring failed.",
            evidence=evidence,
            remediation_steps=[
                "Open the package `s3-mirror-log.json` and inspect failed records.",
                "Fix S3 bucket, IAM, or network configuration for artifact mirroring.",
                "Rerun `contentops scheduled-workflow-archive` and regenerate release evidence.",
            ],
        )
    if missing_archives:
        return ReleaseGateItem(
            name="scheduled_review_packages",
            status="warn",
            message="Scheduled review manifests passed verification but have no archive ZIP.",
            evidence=evidence,
            remediation_steps=[
                "Run `contentops scheduled-workflow-archive <manifest.json> <package.zip>`.",
                "Keep the ZIP with Actions artifacts or the configured artifact root.",
                "Regenerate release evidence so scheduled review packages show archive readiness.",
            ],
        )
    return ReleaseGateItem(
        name="scheduled_review_packages",
        status="pass",
        message="Scheduled review packages are verified or not required for this release.",
        evidence=evidence,
    )


def _retention_archive_governance_check(
    bundle: ReleaseEvidenceBundle,
    review_service: ReviewService,
) -> ReleaseGateItem:
    retention_report = review_service.retention_report()
    archives = bundle.retention_archives
    failed_mirrors = [
        item.archive_id for item in archives.items if item.s3_mirror_status == "failed"
    ]
    non_dry_run_archives = [item for item in archives.items if not item.dry_run]
    evidence = {
        "retention_days": retention_report.retention_days,
        "candidate_count": retention_report.candidate_count,
        "candidate_size_bytes": retention_report.candidate_size_bytes,
        "archive_receipt_count": archives.total,
        "non_dry_run_archive_count": len(non_dry_run_archives),
        "failed_s3_mirror_archive_ids": failed_mirrors,
    }
    if failed_mirrors:
        return ReleaseGateItem(
            name="retention_archive_governance",
            status="fail",
            message="Retention archive receipts include failed S3 mirror attempts.",
            evidence=evidence,
            remediation_steps=[
                "Open `retention_archives.json` and the archive `s3-mirror-log.json`.",
                "Fix S3 bucket, IAM, or network configuration for archive mirroring.",
                "Rerun `contentops retention-archive --days 90` and regenerate release evidence.",
            ],
        )
    if retention_report.candidate_count and not non_dry_run_archives:
        return ReleaseGateItem(
            name="retention_archive_governance",
            status="warn",
            message="Old artifact candidates exist without a non-dry-run archive receipt.",
            evidence=evidence,
            remediation_steps=[
                "Run `contentops retention-archive --days 90` before artifact cleanup.",
                "Review the generated zip and JSON receipt under `retention-archives`.",
                "Regenerate release evidence so `retention_archives.json` includes the receipt.",
            ],
        )
    return ReleaseGateItem(
        name="retention_archive_governance",
        status="pass",
        message="Artifact retention archive evidence is sufficient for the current window.",
        evidence=evidence,
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


def _int_field(payload: object, key: str) -> int:
    if not isinstance(payload, dict):
        return 0
    value = payload.get(key, 0)
    return value if isinstance(value, int) else 0


def _string_field_list(values: Iterable[object]) -> list[str]:
    return [str(value) for value in values if value]


def _deployment_checklist(
    *,
    status: str,
    checks: list[ReleaseGateItem],
    bundle: ReleaseEvidenceBundle,
    git_sha: str | None,
) -> list[str]:
    checklist = [
        f"Confirm release gate status is `{status}` for git SHA `{git_sha or 'not provided'}`.",
        (
            "Archive the release evidence bundle and release gate JSON before deploying; "
            f"evidence files include `{', '.join(bundle.summary.artifact_files)}`."
        ),
        (
            "Verify deployment preflight status "
            f"`{bundle.deployment_check.status}` and release readiness "
            f"`{bundle.summary.release_status}`."
        ),
    ]
    approval = bundle.latest_release_approval
    if approval is None:
        checklist.append("Record a release approval for this git SHA before production deploy.")
    else:
        checklist.append(
            "Confirm release approval "
            f"`{approval.approval_id}` by `{approval.approver}` applies to this deployment."
        )
    for check in checks:
        if check.status == "pass":
            continue
        checklist.append(f"Resolve `{check.name}` because it is `{check.status}`: {check.message}")
        checklist.extend(check.remediation_steps)
    if status == "pass":
        checklist.extend(
            [
                "Deploy the reviewed commit through the approved environment pipeline.",
                "After deploy, verify published URLs, distribution assets, and rollback hints.",
                "Record deployment notes with the release gate JSON and evidence archive.",
            ]
        )
    else:
        checklist.append("Do not deploy until every failed release gate check is resolved.")
    return _dedupe_preserve_order(checklist)


def _release_gate_checklist_markdown(report: ReleaseGateReport) -> str:
    lines = [
        "# Release Gate Deployment Checklist",
        "",
        f"- Status: `{report.status}`",
        f"- Can deploy: `{str(report.can_deploy).lower()}`",
        f"- Git SHA: `{report.git_sha or 'not provided'}`",
        "",
        "## Checklist",
        "",
    ]
    lines.extend(f"- [ ] {item}" for item in report.deployment_checklist)
    lines.extend(["", "## Gate Checks", ""])
    for check in report.checks:
        lines.append(f"- `{check.name}`: `{check.status}` - {check.message}")
    lines.append("")
    return "\n".join(lines)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


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
