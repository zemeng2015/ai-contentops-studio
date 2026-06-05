from __future__ import annotations

from contentops_core.jobs import (
    job_execution_alert_report,
    job_execution_dir,
    job_execution_trends,
)
from contentops_core.models import OperationsConsoleReport, OperationsConsoleSummary
from contentops_core.ops_brief import build_ops_brief
from contentops_core.repository import RunRepository
from contentops_core.review import ReviewService
from contentops_core.settings import Settings


def build_operations_console(
    *,
    settings: Settings,
    repository: RunRepository,
    review_service: ReviewService,
    days: int = 14,
    window_size: int = 100,
    include_release_gate: bool = True,
) -> OperationsConsoleReport:
    operations_summary = review_service.operations_summary(window_size=window_size)
    ops_brief = build_ops_brief(
        settings=settings,
        review_service=review_service,
        days=days,
        window_size=window_size,
    )
    worker_trends = job_execution_trends(
        job_execution_dir(settings.artifact_root),
        days=days,
    )
    worker_alerts = job_execution_alert_report(
        job_execution_dir(settings.artifact_root),
        days=days,
    )
    retention_report = review_service.retention_report()
    retention_archives = review_service.retention_archives(limit=20)
    retention_gate_status = _retention_gate_status(
        candidate_count=retention_report.candidate_count,
        archive_receipt_count=retention_archives.total,
        failed_mirror_count=sum(
            1 for item in retention_archives.items if item.s3_mirror_status == "failed"
        ),
    )
    release_gate_status = "not_evaluated"
    release_gate_payload: dict[str, object] = {}
    if include_release_gate:
        from contentops_core.release_gate import release_gate

        release_gate_report = release_gate(
            settings=settings,
            repository=repository,
            review_service=review_service,
            require_approval=False,
        )
        release_gate_status = release_gate_report.status
        release_gate_payload = release_gate_report.model_dump(mode="json")
        retention_gate = next(
            check
            for check in release_gate_report.checks
            if check.name == "retention_archive_governance"
        )
        retention_gate_status = retention_gate.status
    summary = OperationsConsoleSummary(
        status=_console_status(
            ops_brief.status,
            release_gate_status,
            retention_gate_status,
            worker_alerts.severity.value,
        ),
        action_required=(
            ops_brief.status == "fail"
            or release_gate_status == "fail"
            or retention_gate_status == "fail"
            or worker_alerts.action_required
        ),
        brief_status=ops_brief.status,
        release_gate_status=release_gate_status,
        retention_gate_status=retention_gate_status,
        worker_alert_severity=worker_alerts.severity.value,
        review_queue_depth=operations_summary.review_queue_depth,
        action_required_incidents=operations_summary.action_required_incidents,
        archive_candidate_count=retention_report.candidate_count,
        archive_receipt_count=retention_archives.total,
        worker_success_rate=worker_trends.summary.success_rate,
        top_risk_count=len(ops_brief.top_risks),
        recommended_action_count=len(ops_brief.recommended_actions),
    )
    return OperationsConsoleReport(
        days=days,
        window_size=window_size,
        summary=summary,
        operations_summary=operations_summary,
        ops_brief=ops_brief,
        worker_execution_trends=worker_trends.model_dump(mode="json"),
        worker_execution_alerts=worker_alerts.model_dump(mode="json"),
        release_gate=release_gate_payload,
        retention_report=retention_report,
        retention_archives=retention_archives,
    )


def _console_status(
    brief_status: str,
    release_gate_status: str,
    retention_gate_status: str,
    worker_alert_severity: str,
) -> str:
    statuses = {
        brief_status,
        release_gate_status if release_gate_status != "not_evaluated" else "pass",
        retention_gate_status,
        "fail" if worker_alert_severity == "critical" else worker_alert_severity,
    }
    if "fail" in statuses or "critical" in statuses:
        return "fail"
    if "warn" in statuses or "warning" in statuses:
        return "warn"
    return "pass"


def _retention_gate_status(
    *,
    candidate_count: int,
    archive_receipt_count: int,
    failed_mirror_count: int,
) -> str:
    if failed_mirror_count:
        return "fail"
    if candidate_count and archive_receipt_count == 0:
        return "warn"
    return "pass"
