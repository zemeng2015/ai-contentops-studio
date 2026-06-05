from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from contentops_core.diagnostics import provider_health
from contentops_core.jobs import (
    job_execution_alert_report,
    job_execution_dir,
    job_recovery_lineage,
)
from contentops_core.models import (
    IncidentReportListResponse,
    IncidentSeverity,
    OperationsSummary,
    OpsBriefAction,
    OpsBriefDelivery,
    OpsBriefReport,
    OpsBriefRisk,
)
from contentops_core.review import ReviewService
from contentops_core.settings import Settings


def build_ops_brief(
    *,
    settings: Settings,
    review_service: ReviewService,
    days: int = 14,
    window_size: int = 100,
) -> OpsBriefReport:
    days = max(1, days)
    window_size = max(1, window_size)
    summary = review_service.operations_summary(window_size=window_size)
    providers = provider_health(settings)
    worker_alerts = job_execution_alert_report(
        job_execution_dir(settings.artifact_root),
        days=days,
    )
    worker_recovery = job_recovery_lineage(
        job_execution_dir(settings.artifact_root),
        days=days,
    )
    incidents = review_service.incident_reports(limit=min(window_size, 100))
    trends = review_service.operations_trends(days=days, window_size=max(window_size, 500))
    risks = _top_risks(
        summary=summary,
        provider_status=providers.status,
        provider_failures=sum(1 for item in providers.items if item.status == "fail"),
        provider_warnings=sum(1 for item in providers.items if item.status == "warn"),
        worker_alerts=worker_alerts.model_dump(mode="json"),
        worker_recovery=worker_recovery.model_dump(mode="json"),
        incidents=incidents,
    )
    actions = _recommended_actions(risks)
    status = _brief_status(risks)
    return OpsBriefReport(
        status=status,
        days=days,
        window_size=window_size,
        headline=_headline(status, summary.total_runs, len(risks)),
        summary=summary,
        provider_health=providers,
        worker_execution_alerts=worker_alerts.model_dump(mode="json"),
        worker_recovery_lineage=worker_recovery.model_dump(mode="json"),
        incidents=incidents,
        trends=trends,
        top_risks=risks[:8],
        recommended_actions=actions[:8],
    )


def notify_ops_brief(
    *,
    settings: Settings,
    review_service: ReviewService,
    days: int = 14,
    window_size: int = 100,
    endpoint: str | None = None,
    timeout_seconds: float = 5.0,
) -> OpsBriefDelivery:
    report = build_ops_brief(
        settings=settings,
        review_service=review_service,
        days=days,
        window_size=window_size,
    )
    delivery = _deliver_ops_brief(
        report,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
    )
    write_ops_brief_delivery(delivery, settings.artifact_root)
    return delivery


def write_ops_brief_delivery(delivery: OpsBriefDelivery, artifact_root: Path) -> Path:
    artifact_root.mkdir(parents=True, exist_ok=True)
    path = ops_brief_notification_log_path(artifact_root)
    if path.exists():
        deliveries = json.loads(path.read_text(encoding="utf-8"))
    else:
        deliveries = []
    deliveries.append(delivery.model_dump(mode="json"))
    path.write_text(json.dumps(deliveries, indent=2), encoding="utf-8")
    return path


def ops_brief_notification_log(artifact_root: Path) -> list[OpsBriefDelivery]:
    path = ops_brief_notification_log_path(artifact_root)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [OpsBriefDelivery.model_validate(item) for item in data]


def ops_brief_notification_log_path(artifact_root: Path) -> Path:
    return artifact_root / "ops-brief-notification-log.json"


def _top_risks(
    *,
    summary: OperationsSummary,
    provider_status: str,
    provider_failures: int,
    provider_warnings: int,
    worker_alerts: dict[str, Any],
    worker_recovery: dict[str, Any],
    incidents: IncidentReportListResponse,
) -> list[OpsBriefRisk]:
    risks: list[OpsBriefRisk] = []
    if provider_failures:
        risks.append(
            OpsBriefRisk(
                severity=IncidentSeverity.CRITICAL,
                category="provider_health",
                message=f"{provider_failures} provider check(s) are failing.",
                evidence="provider_health",
            )
        )
    elif provider_status == "warn" or provider_warnings:
        risks.append(
            OpsBriefRisk(
                severity=IncidentSeverity.WARNING,
                category="provider_health",
                message=f"{provider_warnings} provider check(s) need attention.",
                evidence="provider_health",
            )
        )
    worker_severity = worker_alerts.get("severity")
    unrecovered_executions = _int_field(worker_recovery, "unrecovered_execution_count")
    recovered_executions = _int_field(worker_recovery, "recovered_execution_count")
    recovery_attempts = _int_field(worker_recovery, "recovery_attempt_count")
    if unrecovered_executions:
        risks.append(
            OpsBriefRisk(
                severity=IncidentSeverity.CRITICAL,
                category="worker_recovery",
                message=(
                    f"{unrecovered_executions} worker execution(s) still need recovery."
                ),
                evidence="worker_recovery_lineage",
            )
        )
    if worker_alerts.get("action_required"):
        severity = (
            IncidentSeverity.WARNING
            if recovered_executions and recovery_attempts and not unrecovered_executions
            else (
                IncidentSeverity.CRITICAL
                if worker_severity == IncidentSeverity.CRITICAL.value
                else IncidentSeverity.WARNING
            )
        )
        message = str(worker_alerts.get("message") or "Worker execution needs action.")
        if recovered_executions and recovery_attempts and not unrecovered_executions:
            message = "Recent worker failures were recovered; review the recovery lineage."
        risks.append(
            OpsBriefRisk(
                severity=severity,
                category="worker_execution",
                message=message,
                evidence=(
                    "worker_recovery_lineage"
                    if recovered_executions and recovery_attempts and not unrecovered_executions
                    else "worker_execution_alerts"
                ),
            )
        )
    if summary.critical_incidents:
        risks.append(
            OpsBriefRisk(
                severity=IncidentSeverity.CRITICAL,
                category="run_incidents",
                message=f"{summary.critical_incidents} critical run incident(s) need action.",
                evidence="incident_reports",
            )
        )
    if summary.failed_count:
        risks.append(
            OpsBriefRisk(
                severity=IncidentSeverity.WARNING,
                category="run_failures",
                message=f"{summary.failed_count} run(s) are currently failed.",
                evidence="ops_summary",
            )
        )
    if summary.review_queue_depth:
        risks.append(
            OpsBriefRisk(
                severity=IncidentSeverity.INFO,
                category="review_queue",
                message=f"{summary.review_queue_depth} run(s) are waiting for review.",
                evidence="ops_summary",
            )
        )
    if summary.quality_pass_rate < 0.9 and summary.total_runs:
        risks.append(
            OpsBriefRisk(
                severity=IncidentSeverity.WARNING,
                category="quality_slo",
                message=f"Quality pass rate is {summary.quality_pass_rate:.0%}.",
                evidence="ops_summary",
            )
        )
    if summary.budget_pass_rate < 0.9 and summary.total_runs:
        risks.append(
            OpsBriefRisk(
                severity=IncidentSeverity.WARNING,
                category="budget_slo",
                message=f"Budget pass rate is {summary.budget_pass_rate:.0%}.",
                evidence="ops_summary",
            )
        )
    for report in incidents.items:
        if not report.requires_action:
            continue
        risks.append(
            OpsBriefRisk(
                severity=report.severity,
                category="run_incident",
                message=f"{report.run_id}: {report.topic}",
                evidence=f"runs/{report.run_id}/incident-report",
            )
        )
    return sorted(risks, key=_risk_sort_key)


def _deliver_ops_brief(
    report: OpsBriefReport,
    *,
    endpoint: str | None,
    timeout_seconds: float,
) -> OpsBriefDelivery:
    action_required = report.status == "fail"
    if endpoint is None:
        return OpsBriefDelivery(
            provider="local",
            status="skipped",
            brief_status=report.status,
            action_required=action_required,
            message=report.headline,
        )
    try:
        response = httpx.post(
            endpoint,
            json={"ops_brief": report.model_dump(mode="json")},
            timeout=timeout_seconds,
        )
    except httpx.HTTPError as exc:
        return OpsBriefDelivery(
            provider="webhook",
            status="failed",
            brief_status=report.status,
            action_required=action_required,
            message=report.headline,
            endpoint=endpoint,
            error=str(exc),
        )
    return OpsBriefDelivery(
        provider="webhook",
        status="delivered" if response.is_success else "failed",
        brief_status=report.status,
        action_required=action_required,
        message=report.headline,
        endpoint=endpoint,
        status_code=response.status_code,
        error=None if response.is_success else response.text[:500],
    )


def _recommended_actions(risks: list[OpsBriefRisk]) -> list[OpsBriefAction]:
    actions: list[OpsBriefAction] = []
    for risk in risks:
        priority = _priority(risk.severity)
        if risk.category == "provider_health":
            actions.append(
                OpsBriefAction(
                    priority=priority,
                    owner="platform",
                    action="Fix provider configuration before the next scheduled run.",
                    reason=risk.message,
                )
            )
        elif risk.category == "worker_execution":
            actions.append(
                OpsBriefAction(
                    priority=priority,
                    owner="operations",
                    action="Open worker execution alerts and rerun or recover failed jobs.",
                    reason=risk.message,
                )
            )
        elif risk.category == "worker_recovery":
            actions.append(
                OpsBriefAction(
                    priority=priority,
                    owner="operations",
                    action=(
                        "Inspect worker recovery lineage and rerun unrecovered failed jobs."
                    ),
                    reason=risk.message,
                )
            )
        elif risk.category in {"run_incidents", "run_incident", "run_failures"}:
            actions.append(
                OpsBriefAction(
                    priority=priority,
                    owner="reviewer",
                    action="Inspect incident reports, repair artifacts, then regenerate evidence.",
                    reason=risk.message,
                )
            )
        elif risk.category == "review_queue":
            actions.append(
                OpsBriefAction(
                    priority=priority,
                    owner="reviewer",
                    action="Review pending runs and approve, reject, or request source changes.",
                    reason=risk.message,
                )
            )
        elif risk.category == "quality_slo":
            actions.append(
                OpsBriefAction(
                    priority=priority,
                    owner="content",
                    action="Review low-scoring drafts and strengthen sources before publishing.",
                    reason=risk.message,
                )
            )
        elif risk.category == "budget_slo":
            actions.append(
                OpsBriefAction(
                    priority=priority,
                    owner="platform",
                    action="Audit token usage and adjust model, source, or retry settings.",
                    reason=risk.message,
                )
            )
    if not actions:
        actions.append(
            OpsBriefAction(
                priority=5,
                owner="operations",
                action="No urgent action. Continue monitoring the next scheduled execution.",
                reason="No actionable risks were detected in the current window.",
            )
        )
    return _dedupe_actions(actions)


def _brief_status(risks: list[OpsBriefRisk]) -> str:
    if any(risk.severity == IncidentSeverity.CRITICAL for risk in risks):
        return "fail"
    if any(risk.severity == IncidentSeverity.WARNING for risk in risks):
        return "warn"
    return "pass"


def _headline(status: str, total_runs: int, risk_count: int) -> str:
    if status == "fail":
        return f"Action required: {risk_count} operational risk(s) across {total_runs} run(s)."
    if status == "warn":
        return f"Needs attention: {risk_count} operational warning(s) across {total_runs} run(s)."
    return f"Healthy: no actionable operational risks across {total_runs} run(s)."


def _risk_sort_key(risk: OpsBriefRisk) -> tuple[int, str, str]:
    severity_rank = {
        IncidentSeverity.CRITICAL: 0,
        IncidentSeverity.WARNING: 1,
        IncidentSeverity.INFO: 2,
    }
    return (severity_rank[risk.severity], risk.category, risk.message)


def _priority(severity: IncidentSeverity) -> int:
    if severity == IncidentSeverity.CRITICAL:
        return 1
    if severity == IncidentSeverity.WARNING:
        return 2
    return 4


def _int_field(data: dict[str, Any], key: str) -> int:
    value = data.get(key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _dedupe_actions(actions: list[OpsBriefAction]) -> list[OpsBriefAction]:
    seen: set[tuple[str, str]] = set()
    deduped: list[OpsBriefAction] = []
    for action in sorted(actions, key=lambda item: (item.priority, item.owner, item.action)):
        key = (action.owner, action.action)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped
