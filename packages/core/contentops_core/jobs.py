from __future__ import annotations

import hashlib
import json
import mimetypes
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import yaml
from pydantic import BaseModel, Field

from contentops_core.models import IncidentSeverity, RunRequest, RunStatus
from contentops_core.pipeline import ContentOpsPipeline


class ContentJob(BaseModel):
    name: str = "content-job"
    topic: str
    source_urls: list[str] = Field(default_factory=list)
    publish: bool = False
    homepage_handoff: bool = False
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)

    def to_request(self, workflow_name: str | None = None) -> RunRequest:
        metadata = dict(self.metadata)
        metadata["contentops_job_name"] = self.name
        metadata["contentops_publish_intent"] = "publish" if self.publish else "review"
        metadata["contentops_homepage_handoff"] = str(self.homepage_handoff).lower()
        if self.tags:
            metadata["contentops_job_tags"] = ",".join(self.tags)
        if workflow_name:
            metadata["contentops_workflow_name"] = workflow_name
        return RunRequest(
            topic=self.topic,
            source_urls=self.source_urls,
            publish=self.publish,
            metadata=metadata,
        )


class WorkerJobSchedule(BaseModel):
    enabled: bool = True
    cron: str | None = None
    timezone: str = "UTC"
    description: str = ""


class WorkerJobRetryPolicy(BaseModel):
    max_attempts: int = Field(ge=1, default=2)
    backoff_seconds: int = Field(ge=0, default=300)


class WorkerJobRunPolicy(BaseModel):
    timeout_minutes: int = Field(ge=1, default=30)
    concurrency_policy: str = "forbid"
    retry: WorkerJobRetryPolicy = Field(default_factory=WorkerJobRetryPolicy)


class ContentJobFile(BaseModel):
    name: str = "contentops-jobs"
    schedule: WorkerJobSchedule | None = None
    run_policy: WorkerJobRunPolicy = Field(default_factory=WorkerJobRunPolicy)
    jobs: list[ContentJob]

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> ContentJobFile:
        if "jobs" in data:
            return cls.model_validate(data)
        job = ContentJob.model_validate(data)
        return cls(name=job.name, jobs=[job])


class JobRunResult(BaseModel):
    job_name: str
    topic: str
    source_urls: list[str] = Field(default_factory=list)
    publish: bool = False
    homepage_handoff: bool = False
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    run_id: str | None = None
    status: RunStatus | str
    artifact_dir: str | None = None
    published_url: str | None = None
    homepage_handoff_path: str | None = None
    homepage_handoff_error: str | None = None
    duration_ms: int | None = None
    error: str | None = None


class JobExecutionReport(BaseModel):
    execution_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    dry_run: bool = False
    total: int
    succeeded: int
    failed: int
    results: list[JobRunResult]
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: int = 0
    receipt_path: str | None = None
    content_assets_path: str | None = None
    content_assets_status: str | None = None
    content_assets_files: list[str] = Field(default_factory=list)
    content_assets_error: str | None = None
    delivery_summary_path: str | None = None
    delivery_summary_markdown_path: str | None = None
    delivery_summary_error: str | None = None
    release_evidence_path: str | None = None
    release_evidence_status: str | None = None
    release_evidence_files: list[str] = Field(default_factory=list)
    release_evidence_error: str | None = None


class JobExecutionSummary(BaseModel):
    total_jobs: int
    succeeded: int
    failed: int
    generated_runs: int
    publish_intent: int
    review_intent: int
    published_runs: int
    homepage_handoff_requested: int
    homepage_handoff_ready: int
    homepage_handoff_failed: int
    release_evidence_ready: bool
    action_required: bool


class JobExecutionTrendBucket(BaseModel):
    date: str
    execution_count: int = Field(ge=0)
    total_jobs: int = Field(ge=0)
    succeeded_jobs: int = Field(ge=0)
    failed_jobs: int = Field(ge=0)
    generated_runs: int = Field(ge=0)
    published_runs: int = Field(ge=0)
    homepage_handoff_ready: int = Field(ge=0)
    homepage_handoff_failed: int = Field(ge=0)
    action_required: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=1)
    publish_rate: float = Field(ge=0, le=1)
    handoff_success_rate: float = Field(ge=0, le=1)
    top_failure_reasons: list[JobExecutionFailureReason] = Field(default_factory=list)


class JobExecutionFailureReason(BaseModel):
    category: str
    reason: str
    count: int = Field(ge=0)
    latest_execution_id: str | None = None
    latest_at: datetime | None = None
    remediation_steps: list[str] = Field(default_factory=list)


class JobExecutionTrendSummary(BaseModel):
    execution_count: int = Field(ge=0)
    total_jobs: int = Field(ge=0)
    succeeded_jobs: int = Field(ge=0)
    failed_jobs: int = Field(ge=0)
    generated_runs: int = Field(ge=0)
    published_runs: int = Field(ge=0)
    homepage_handoff_ready: int = Field(ge=0)
    homepage_handoff_failed: int = Field(ge=0)
    action_required: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=1)
    publish_rate: float = Field(ge=0, le=1)
    handoff_success_rate: float = Field(ge=0, le=1)
    latest_success_at: datetime | None = None
    latest_failure_at: datetime | None = None
    top_failure_reasons: list[JobExecutionFailureReason] = Field(default_factory=list)


class JobExecutionTrendReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    days: int = Field(ge=1)
    buckets: list[JobExecutionTrendBucket]
    summary: JobExecutionTrendSummary


class JobExecutionAlertSignal(BaseModel):
    severity: IncidentSeverity
    category: str
    message: str
    latest_execution_id: str | None = None
    latest_at: datetime | None = None
    remediation_steps: list[str] = Field(default_factory=list)


class JobExecutionAlertReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    days: int = Field(ge=1)
    severity: IncidentSeverity
    action_required: bool
    message: str
    signals: list[JobExecutionAlertSignal] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    trend_summary: JobExecutionTrendSummary


class JobExecutionAlertDelivery(BaseModel):
    delivery_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    action: str = "worker_execution_alert"
    provider: str
    status: str
    severity: IncidentSeverity
    action_required: bool
    message: str
    endpoint: str | None = None
    status_code: int | None = None
    error: str | None = None
    delivered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkerDeliverySummaryDelivery(BaseModel):
    delivery_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    action: str = "worker_delivery_summary"
    execution_id: str
    provider: str
    status: str
    action_required: bool
    message: str
    summary_path: str | None = None
    markdown_path: str | None = None
    endpoint: str | None = None
    status_code: int | None = None
    error: str | None = None
    delivered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ScheduledWorkflowReviewItem(BaseModel):
    execution_id: str
    name: str
    dry_run: bool
    completed_at: datetime
    action_required: bool
    succeeded: int = Field(ge=0)
    total: int = Field(ge=0)
    published_urls: list[str] = Field(default_factory=list)
    homepage_handoff_paths: list[str] = Field(default_factory=list)
    content_assets_path: str | None = None
    content_assets_status: str | None = None
    content_assets_files: list[str] = Field(default_factory=list)
    content_assets_error: str | None = None
    worker_receipt_path: str | None = None
    release_evidence_path: str | None = None
    delivery_summary_markdown_path: str | None = None
    failure_reasons: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    pr_title: str
    pr_checklist: list[str] = Field(default_factory=list)


class ScheduledWorkflowReviewReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    total: int = Field(ge=0)
    action_required_count: int = Field(ge=0)
    published_count: int = Field(ge=0)
    handoff_count: int = Field(ge=0)
    content_assets_count: int = Field(ge=0)
    content_assets_failed_count: int = Field(ge=0)
    operations_console_summary: dict[str, Any] = Field(default_factory=dict)
    items: list[ScheduledWorkflowReviewItem] = Field(default_factory=list)


class ScheduledWorkflowPrMetadata(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    title: str
    body: str
    source_execution_ids: list[str] = Field(default_factory=list)
    action_required: bool = False
    operations_console_summary: dict[str, Any] = Field(default_factory=dict)
    checklist: list[str] = Field(default_factory=list)


class ScheduledWorkflowReviewArtifact(BaseModel):
    path: str
    name: str
    exists: bool
    size_bytes: int = Field(ge=0, default=0)
    media_type: str = "application/octet-stream"
    sha256: str | None = None
    updated_at: datetime | None = None


class ScheduledWorkflowReviewManifest(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    manifest_type: str = "scheduled_workflow_review"
    review_markdown_path: str | None = None
    pr_metadata_path: str | None = None
    operations_console_path: str | None = None
    source_execution_ids: list[str] = Field(default_factory=list)
    worker_receipt_paths: list[str] = Field(default_factory=list)
    delivery_summary_paths: list[str] = Field(default_factory=list)
    release_evidence_paths: list[str] = Field(default_factory=list)
    content_assets_paths: list[str] = Field(default_factory=list)
    homepage_handoff_paths: list[str] = Field(default_factory=list)
    published_urls: list[str] = Field(default_factory=list)
    action_required: bool = False
    operations_console_summary: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, ScheduledWorkflowReviewArtifact] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobExecutionListResponse(BaseModel):
    items: list[JobExecutionReport]
    total: int
    limit: int
    offset: int


class WorkerJobCatalogItem(BaseModel):
    path: str
    name: str
    valid: bool = True
    schedule: WorkerJobSchedule | None = None
    run_policy: WorkerJobRunPolicy | None = None
    readiness_status: str = "unknown"
    total: int = 0
    publish_count: int = 0
    review_count: int = 0
    handoff_count: int = 0
    topics: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    jobs: list[ContentJob] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class WorkerJobCatalogResponse(BaseModel):
    items: list[WorkerJobCatalogItem]
    total: int
    job_count: int
    publish_count: int
    review_count: int
    handoff_count: int
    invalid_count: int
    ready_count: int = 0
    action_required_count: int = 0


class WorkerJobReadinessCheck(BaseModel):
    name: str
    status: str
    message: str
    remediation_steps: list[str] = Field(default_factory=list)


class WorkerJobReadinessItem(BaseModel):
    path: str
    name: str
    status: str
    valid: bool
    checks: list[WorkerJobReadinessCheck] = Field(default_factory=list)


class WorkerJobReadinessResponse(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    total: int = 0
    ready_count: int = 0
    warning_count: int = 0
    failed_count: int = 0
    can_schedule: bool = False
    items: list[WorkerJobReadinessItem] = Field(default_factory=list)


class JobRecoveryPlan(BaseModel):
    execution_id: str
    source_execution_name: str
    source_dry_run: bool = False
    failed_count: int
    runnable: bool = True
    blocked_reason: str | None = None
    jobs: list[ContentJob]

    def to_job_file(self) -> ContentJobFile:
        return ContentJobFile(
            name=f"{self.source_execution_name}-recovery",
            jobs=self.jobs,
        )


class JobRunner:
    def __init__(self, pipeline: ContentOpsPipeline) -> None:
        self.pipeline = pipeline

    def run(self, job_file: ContentJobFile, receipt_dir: Path | None = None) -> JobExecutionReport:
        started_at = datetime.now(UTC)
        results: list[JobRunResult] = []
        for job in job_file.jobs:
            job_started = datetime.now(UTC)
            try:
                run_result = self.pipeline.run(job.to_request(workflow_name=job_file.name))
                results.append(
                    JobRunResult(
                        job_name=job.name,
                        topic=job.topic,
                        source_urls=job.source_urls,
                        publish=job.publish,
                        homepage_handoff=job.homepage_handoff,
                        tags=job.tags,
                        metadata=job.metadata,
                        run_id=run_result.run.id,
                        status=run_result.run.status,
                        artifact_dir=str(run_result.run.artifact_dir),
                        published_url=run_result.run.published_url,
                        duration_ms=_duration_ms(job_started),
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive execution boundary
                results.append(
                    JobRunResult(
                        job_name=job.name,
                        topic=job.topic,
                        source_urls=job.source_urls,
                        publish=job.publish,
                        homepage_handoff=job.homepage_handoff,
                        tags=job.tags,
                        metadata=job.metadata,
                        status="failed",
                        duration_ms=_duration_ms(job_started),
                        error=str(exc),
                    )
                )
        failed = sum(1 for result in results if result.error is not None)
        report = JobExecutionReport(
            name=job_file.name,
            total=len(results),
            succeeded=len(results) - failed,
            failed=failed,
            results=results,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            duration_ms=_duration_ms(started_at),
        )
        self.write_report(report, receipt_dir=receipt_dir)
        return report

    @staticmethod
    def dry_run_report(job_file: ContentJobFile) -> JobExecutionReport:
        started_at = datetime.now(UTC)
        results = [
            JobRunResult(
                job_name=job.name,
                topic=job.topic,
                source_urls=job.source_urls,
                publish=job.publish,
                homepage_handoff=job.homepage_handoff,
                tags=job.tags,
                metadata=job.metadata,
                status="dry_run",
            )
            for job in job_file.jobs
        ]
        return JobExecutionReport(
            name=job_file.name,
            dry_run=True,
            total=len(results),
            succeeded=len(results),
            failed=0,
            results=results,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            duration_ms=_duration_ms(started_at),
        )

    def write_report(
        self,
        report: JobExecutionReport,
        receipt_dir: Path | None = None,
    ) -> Path:
        target_dir = receipt_dir or job_execution_dir(self.pipeline.artifact_store.root)
        return write_job_execution_report(report, target_dir)


def load_job_file(path: Path) -> ContentJobFile:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Job file must contain a YAML mapping.")
    return ContentJobFile.from_mapping(data)


def list_worker_job_catalog(pipeline_dir: Path) -> WorkerJobCatalogResponse:
    items: list[WorkerJobCatalogItem] = []
    for path in _worker_job_paths(pipeline_dir):
        items.append(_worker_job_catalog_item(path, pipeline_dir))
    return WorkerJobCatalogResponse(
        items=items,
        total=len(items),
        job_count=sum(item.total for item in items),
        publish_count=sum(item.publish_count for item in items),
        review_count=sum(item.review_count for item in items),
        handoff_count=sum(item.handoff_count for item in items),
        invalid_count=sum(1 for item in items if not item.valid),
        ready_count=sum(1 for item in items if item.readiness_status == "ready"),
        action_required_count=sum(
            1 for item in items if item.readiness_status in {"warning", "failed"}
        ),
    )


def worker_job_readiness(pipeline_dir: Path) -> WorkerJobReadinessResponse:
    catalog = list_worker_job_catalog(pipeline_dir)
    items = [_worker_job_readiness_item(item) for item in catalog.items]
    return WorkerJobReadinessResponse(
        total=len(items),
        ready_count=sum(1 for item in items if item.status == "ready"),
        warning_count=sum(1 for item in items if item.status == "warning"),
        failed_count=sum(1 for item in items if item.status == "failed"),
        can_schedule=bool(items) and all(item.status in {"ready", "warning"} for item in items),
        items=items,
    )


def write_job_execution_report(report: JobExecutionReport, receipt_dir: Path) -> Path:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = (
        receipt_dir
        / f"{report.started_at:%Y%m%dT%H%M%SZ}-{report.name}-{report.execution_id}.json"
    )
    report.receipt_path = str(path)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


def rewrite_job_execution_report(report: JobExecutionReport) -> Path:
    if report.receipt_path is None:
        raise ValueError("Job execution receipt path is missing.")
    path = Path(report.receipt_path)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


def write_job_execution_delivery_summary(report: JobExecutionReport) -> tuple[Path, Path]:
    if report.receipt_path is None:
        raise ValueError("Job execution receipt path is missing.")
    receipt_path = Path(report.receipt_path)
    output_dir = receipt_path.parent
    json_path = output_dir / f"{report.execution_id}-delivery-summary.json"
    markdown_path = output_dir / f"{report.execution_id}-delivery-summary.md"
    payload = _job_execution_delivery_summary_payload(report)
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(
        _job_execution_delivery_summary_markdown(payload),
        encoding="utf-8",
    )
    report.delivery_summary_path = str(json_path)
    report.delivery_summary_markdown_path = str(markdown_path)
    report.delivery_summary_error = None
    rewrite_job_execution_report(report)
    return json_path, markdown_path


def notify_worker_delivery_summary(
    report: JobExecutionReport,
    receipt_dir: Path | None = None,
    *,
    endpoint: str | None = None,
    timeout_seconds: float = 5.0,
) -> WorkerDeliverySummaryDelivery:
    if report.delivery_summary_path is None:
        write_job_execution_delivery_summary(report)
    resolved_receipt_dir = receipt_dir or _report_receipt_dir(report)
    delivery = _deliver_worker_delivery_summary(
        report,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
    )
    write_worker_delivery_summary_delivery(delivery, resolved_receipt_dir)
    return delivery


def write_worker_delivery_summary_delivery(
    delivery: WorkerDeliverySummaryDelivery,
    receipt_dir: Path,
) -> Path:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = worker_delivery_summary_notification_log_path(receipt_dir)
    if path.exists():
        deliveries = json.loads(path.read_text(encoding="utf-8"))
    else:
        deliveries = []
    deliveries.append(delivery.model_dump(mode="json"))
    path.write_text(json.dumps(deliveries, indent=2), encoding="utf-8")
    return path


def worker_delivery_summary_notification_log(
    receipt_dir: Path,
) -> list[WorkerDeliverySummaryDelivery]:
    path = worker_delivery_summary_notification_log_path(receipt_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [WorkerDeliverySummaryDelivery.model_validate(item) for item in data]


def worker_delivery_summary_notification_log_path(receipt_dir: Path) -> Path:
    return receipt_dir / "worker-delivery-summary-notification-log.json"


def job_execution_dir(artifact_root: Path) -> Path:
    return artifact_root / "job-executions"


def _worker_job_paths(pipeline_dir: Path) -> list[Path]:
    if pipeline_dir.is_file():
        return [pipeline_dir]
    if not pipeline_dir.exists():
        return []
    paths = [*pipeline_dir.glob("*.yaml"), *pipeline_dir.glob("*.yml")]
    return sorted({path.resolve() for path in paths}, key=lambda path: path.name)


def _worker_job_catalog_item(path: Path, pipeline_dir: Path) -> WorkerJobCatalogItem:
    display_path = _display_path(path, pipeline_dir)
    try:
        job_file = load_job_file(path)
    except Exception as exc:
        return WorkerJobCatalogItem(
            path=display_path,
            name=path.stem,
            valid=False,
            errors=[str(exc)],
        )
    tags = sorted({tag for job in job_file.jobs for tag in job.tags})
    publish_count = sum(1 for job in job_file.jobs if job.publish)
    handoff_count = sum(1 for job in job_file.jobs if job.homepage_handoff)
    readiness = _worker_job_readiness_for_job_file(
        display_path,
        job_file.name,
        valid=True,
        schedule=job_file.schedule,
        run_policy=job_file.run_policy,
        total=len(job_file.jobs),
        publish_count=publish_count,
        review_count=len(job_file.jobs) - publish_count,
        handoff_count=handoff_count,
        errors=[],
    )
    return WorkerJobCatalogItem(
        path=display_path,
        name=job_file.name,
        valid=True,
        schedule=job_file.schedule,
        run_policy=job_file.run_policy,
        readiness_status=readiness.status,
        total=len(job_file.jobs),
        publish_count=publish_count,
        review_count=len(job_file.jobs) - publish_count,
        handoff_count=handoff_count,
        topics=[job.topic for job in job_file.jobs],
        tags=tags,
        jobs=job_file.jobs,
    )


def _worker_job_readiness_item(item: WorkerJobCatalogItem) -> WorkerJobReadinessItem:
    return _worker_job_readiness_for_job_file(
        item.path,
        item.name,
        valid=item.valid,
        schedule=item.schedule,
        run_policy=item.run_policy or WorkerJobRunPolicy(),
        total=item.total,
        publish_count=item.publish_count,
        review_count=item.review_count,
        handoff_count=item.handoff_count,
        errors=item.errors,
    )


def _worker_job_readiness_for_job_file(
    path: str,
    name: str,
    *,
    valid: bool,
    schedule: WorkerJobSchedule | None,
    run_policy: WorkerJobRunPolicy,
    total: int,
    publish_count: int,
    review_count: int,
    handoff_count: int,
    errors: list[str],
) -> WorkerJobReadinessItem:
    checks: list[WorkerJobReadinessCheck] = []
    if not valid:
        checks.append(
            WorkerJobReadinessCheck(
                name="yaml_schema",
                status="fail",
                message="Worker job file cannot be loaded.",
                remediation_steps=errors or ["Fix the YAML file and rerun worker-job-readiness."],
            )
        )
        return WorkerJobReadinessItem(
            path=path,
            name=name,
            status="failed",
            valid=False,
            checks=checks,
        )
    checks.extend(
        [
            _schedule_readiness_check(schedule),
            _run_policy_timeout_check(run_policy),
            _run_policy_concurrency_check(run_policy),
            _run_policy_retry_check(run_policy),
            _job_mix_readiness_check(
                total=total,
                publish_count=publish_count,
                review_count=review_count,
                handoff_count=handoff_count,
            ),
        ]
    )
    return WorkerJobReadinessItem(
        path=path,
        name=name,
        status=_readiness_status(checks),
        valid=True,
        checks=checks,
    )


def _schedule_readiness_check(schedule: WorkerJobSchedule | None) -> WorkerJobReadinessCheck:
    if schedule is None:
        return WorkerJobReadinessCheck(
            name="schedule",
            status="fail",
            message="No schedule is declared for this worker job file.",
            remediation_steps=[
                "Add schedule.enabled, schedule.cron, and schedule.timezone to the YAML file.",
                "Use worker dry runs before enabling the schedule in production.",
            ],
        )
    if not schedule.enabled:
        return WorkerJobReadinessCheck(
            name="schedule",
            status="warn",
            message="Schedule is present but disabled.",
            remediation_steps=["Set schedule.enabled=true before wiring this job into automation."],
        )
    if not schedule.cron or not _looks_like_cron(schedule.cron):
        return WorkerJobReadinessCheck(
            name="schedule",
            status="fail",
            message="Schedule is enabled but cron expression is missing or invalid.",
            remediation_steps=[
                "Use a five-field cron expression such as `0 8 * * *`.",
                "Confirm the timezone matches the operator's expected publishing window.",
            ],
        )
    if not schedule.timezone.strip():
        return WorkerJobReadinessCheck(
            name="schedule",
            status="fail",
            message="Schedule timezone is empty.",
            remediation_steps=["Set schedule.timezone, for example `Asia/Shanghai` or `UTC`."],
        )
    return WorkerJobReadinessCheck(
        name="schedule",
        status="pass",
        message=f"Scheduled with cron `{schedule.cron}` in {schedule.timezone}.",
    )


def _run_policy_timeout_check(run_policy: WorkerJobRunPolicy) -> WorkerJobReadinessCheck:
    if run_policy.timeout_minutes < 5:
        return WorkerJobReadinessCheck(
            name="timeout",
            status="warn",
            message="Timeout is very short for research and publishing workflows.",
            remediation_steps=["Use at least 15 minutes for scheduled research jobs."],
        )
    return WorkerJobReadinessCheck(
        name="timeout",
        status="pass",
        message=f"Worker timeout is {run_policy.timeout_minutes} minute(s).",
    )


def _run_policy_concurrency_check(run_policy: WorkerJobRunPolicy) -> WorkerJobReadinessCheck:
    allowed = {"forbid", "replace", "allow"}
    if run_policy.concurrency_policy not in allowed:
        return WorkerJobReadinessCheck(
            name="concurrency",
            status="fail",
            message=f"Unsupported concurrency policy: {run_policy.concurrency_policy}.",
            remediation_steps=[
                "Use `forbid` for production publishing jobs.",
                "Use `replace` only when newer executions should supersede older ones.",
            ],
        )
    if run_policy.concurrency_policy == "allow":
        return WorkerJobReadinessCheck(
            name="concurrency",
            status="warn",
            message="Concurrent executions are allowed.",
            remediation_steps=[
                "Prefer `forbid` when jobs publish files or write shared artifacts.",
            ],
        )
    return WorkerJobReadinessCheck(
        name="concurrency",
        status="pass",
        message=f"Concurrency policy is `{run_policy.concurrency_policy}`.",
    )


def _run_policy_retry_check(run_policy: WorkerJobRunPolicy) -> WorkerJobReadinessCheck:
    retry = run_policy.retry
    if retry.max_attempts == 1:
        return WorkerJobReadinessCheck(
            name="retry",
            status="warn",
            message="No retry is configured for transient provider or publishing failures.",
            remediation_steps=["Set run_policy.retry.max_attempts to 2 or 3 for scheduled jobs."],
        )
    return WorkerJobReadinessCheck(
        name="retry",
        status="pass",
        message=(
            f"Retry policy allows {retry.max_attempts} attempt(s) "
            f"with {retry.backoff_seconds}s backoff."
        ),
    )


def _job_mix_readiness_check(
    *,
    total: int,
    publish_count: int,
    review_count: int,
    handoff_count: int,
) -> WorkerJobReadinessCheck:
    if total == 0:
        return WorkerJobReadinessCheck(
            name="job_mix",
            status="fail",
            message="Worker job file does not define any jobs.",
            remediation_steps=["Add at least one job with a topic before scheduling the file."],
        )
    if publish_count > 0 and handoff_count == 0:
        return WorkerJobReadinessCheck(
            name="job_mix",
            status="warn",
            message="Publishing jobs do not request homepage handoff evidence.",
            remediation_steps=[
                "Set homepage_handoff=true for scheduled publishing jobs that feed the portfolio.",
            ],
        )
    return WorkerJobReadinessCheck(
        name="job_mix",
        status="pass",
        message=(
            f"{total} job(s): {publish_count} publish, "
            f"{review_count} review, {handoff_count} homepage handoff."
        ),
    )


def _readiness_status(checks: list[WorkerJobReadinessCheck]) -> str:
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        return "failed"
    if "warn" in statuses:
        return "warning"
    return "ready"


def _looks_like_cron(expression: str) -> bool:
    fields = expression.split()
    if len(fields) != 5:
        return False
    return all(field.strip() for field in fields)


def _display_path(path: Path, pipeline_dir: Path) -> str:
    try:
        return str(path.relative_to(pipeline_dir.resolve()))
    except ValueError:
        return str(path)


def list_job_execution_reports(
    receipt_dir: Path,
    limit: int = 20,
    offset: int = 0,
) -> JobExecutionListResponse:
    paths = _job_execution_receipt_paths(receipt_dir)
    selected = paths[offset : offset + limit]
    return JobExecutionListResponse(
        items=[_read_job_execution_report(path) for path in selected],
        total=len(paths),
        limit=limit,
        offset=offset,
    )


def scheduled_workflow_review_report(
    receipt_dir: Path,
    *,
    limit: int = 5,
    operations_console: dict[str, Any] | None = None,
) -> ScheduledWorkflowReviewReport:
    reports = list_job_execution_reports(receipt_dir, limit=limit).items
    items = [_scheduled_workflow_review_item(report) for report in reports]
    operations_console_summary = _operations_console_summary(operations_console)
    return ScheduledWorkflowReviewReport(
        total=len(items),
        action_required_count=sum(1 for item in items if item.action_required),
        published_count=sum(len(item.published_urls) for item in items),
        handoff_count=sum(len(item.homepage_handoff_paths) for item in items),
        content_assets_count=sum(
            1 for item in items if item.content_assets_status == "generated"
        ),
        content_assets_failed_count=sum(
            1 for item in items if item.content_assets_status == "failed"
        ),
        operations_console_summary=operations_console_summary,
        items=items,
    )


def write_scheduled_workflow_review_markdown(
    report: ScheduledWorkflowReviewReport,
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_scheduled_workflow_review_markdown(report), encoding="utf-8")
    return output_path


def scheduled_workflow_pr_metadata(
    report: ScheduledWorkflowReviewReport,
) -> ScheduledWorkflowPrMetadata:
    checklist = _scheduled_workflow_pr_checklist(report)
    return ScheduledWorkflowPrMetadata(
        title=_scheduled_workflow_pr_title(report),
        body=_scheduled_workflow_pr_body(report, checklist),
        source_execution_ids=[item.execution_id for item in report.items],
        action_required=(
            report.action_required_count > 0
            or bool(report.operations_console_summary.get("action_required"))
        ),
        operations_console_summary=report.operations_console_summary,
        checklist=checklist,
    )


def write_scheduled_workflow_pr_metadata(
    report: ScheduledWorkflowReviewReport,
    output_path: Path,
) -> Path:
    metadata = scheduled_workflow_pr_metadata(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def scheduled_workflow_review_manifest(
    report: ScheduledWorkflowReviewReport,
    *,
    review_markdown_path: Path | None = None,
    pr_metadata_path: Path | None = None,
    operations_console_path: Path | None = None,
) -> ScheduledWorkflowReviewManifest:
    worker_receipt_paths = [
        item.worker_receipt_path
        for item in report.items
        if item.worker_receipt_path is not None
    ]
    delivery_summary_paths = [
        item.delivery_summary_markdown_path
        for item in report.items
        if item.delivery_summary_markdown_path is not None
    ]
    release_evidence_paths = [
        item.release_evidence_path for item in report.items if item.release_evidence_path
    ]
    content_assets_paths = [
        item.content_assets_path for item in report.items if item.content_assets_path
    ]
    homepage_handoff_paths = [
        path for item in report.items for path in item.homepage_handoff_paths
    ]
    artifact_paths = _dedupe_preserve_order(
        [
            path
            for path in [
                _optional_path(review_markdown_path),
                _optional_path(pr_metadata_path),
                _optional_path(operations_console_path),
                *worker_receipt_paths,
                *delivery_summary_paths,
                *release_evidence_paths,
                *content_assets_paths,
                *homepage_handoff_paths,
            ]
            if path is not None
        ]
    )
    return ScheduledWorkflowReviewManifest(
        review_markdown_path=_optional_path(review_markdown_path),
        pr_metadata_path=_optional_path(pr_metadata_path),
        operations_console_path=_optional_path(operations_console_path),
        source_execution_ids=[item.execution_id for item in report.items],
        worker_receipt_paths=worker_receipt_paths,
        delivery_summary_paths=delivery_summary_paths,
        release_evidence_paths=release_evidence_paths,
        content_assets_paths=content_assets_paths,
        homepage_handoff_paths=homepage_handoff_paths,
        published_urls=[url for item in report.items for url in item.published_urls],
        action_required=(
            report.action_required_count > 0
            or bool(report.operations_console_summary.get("action_required"))
        ),
        operations_console_summary=report.operations_console_summary,
        artifacts={
            path: _scheduled_review_artifact(path)
            for path in artifact_paths
        },
        metadata={
            "hash_algorithm": "sha256",
            "artifact_count": len(artifact_paths),
        },
    )


def write_scheduled_workflow_review_manifest(
    report: ScheduledWorkflowReviewReport,
    output_path: Path,
    *,
    review_markdown_path: Path | None = None,
    pr_metadata_path: Path | None = None,
    operations_console_path: Path | None = None,
) -> Path:
    manifest = scheduled_workflow_review_manifest(
        report,
        review_markdown_path=review_markdown_path,
        pr_metadata_path=pr_metadata_path,
        operations_console_path=operations_console_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def _optional_path(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _scheduled_review_artifact(path_value: str) -> ScheduledWorkflowReviewArtifact:
    path = Path(path_value)
    if path.is_dir():
        return _scheduled_review_directory_artifact(path_value, path)
    if not path.exists():
        return ScheduledWorkflowReviewArtifact(
            path=path_value,
            name=path.name,
            exists=False,
        )
    stat = path.stat()
    return ScheduledWorkflowReviewArtifact(
        path=path_value,
        name=path.name,
        exists=True,
        size_bytes=stat.st_size,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        updated_at=datetime.fromtimestamp(stat.st_mtime, UTC),
    )


def _scheduled_review_directory_artifact(
    path_value: str,
    path: Path,
) -> ScheduledWorkflowReviewArtifact:
    files = sorted(item for item in path.rglob("*") if item.is_file())
    digest = hashlib.sha256()
    size_bytes = 0
    for item in files:
        relative = item.relative_to(path).as_posix()
        content = item.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        size_bytes += len(content)
    latest = max((item.stat().st_mtime for item in files), default=path.stat().st_mtime)
    return ScheduledWorkflowReviewArtifact(
        path=path_value,
        name=path.name,
        exists=True,
        size_bytes=size_bytes,
        media_type="inode/directory",
        sha256=digest.hexdigest(),
        updated_at=datetime.fromtimestamp(latest, UTC),
    )


def _operations_console_summary(
    operations_console: dict[str, Any] | None,
) -> dict[str, Any]:
    if not operations_console:
        return {}
    summary = operations_console.get("summary")
    if not isinstance(summary, dict):
        return {}
    keys = [
        "status",
        "action_required",
        "brief_status",
        "release_gate_status",
        "retention_gate_status",
        "worker_alert_severity",
        "review_queue_depth",
        "action_required_incidents",
        "archive_candidate_count",
        "worker_success_rate",
        "top_risk_count",
        "recommended_action_count",
    ]
    return {key: summary[key] for key in keys if key in summary}


def job_execution_trends(receipt_dir: Path, days: int = 14) -> JobExecutionTrendReport:
    if days < 1:
        raise ValueError("days must be at least 1.")
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    reports = [
        report
        for report in (
            _read_job_execution_report(path) for path in _job_execution_receipt_paths(receipt_dir)
        )
        if report.completed_at.date() >= start
    ]
    reports_by_date: dict[str, list[JobExecutionReport]] = {}
    for report in reports:
        key = report.completed_at.date().isoformat()
        reports_by_date.setdefault(key, []).append(report)
    buckets = [
        _job_execution_trend_bucket(day, reports_by_date.get(day.isoformat(), []))
        for day in _date_range(start, today)
    ]
    return JobExecutionTrendReport(
        days=days,
        buckets=buckets,
        summary=_job_execution_trend_summary(reports),
    )


def job_execution_alert_report(receipt_dir: Path, days: int = 14) -> JobExecutionAlertReport:
    trends = job_execution_trends(receipt_dir, days=days)
    summary = trends.summary
    signals: list[JobExecutionAlertSignal] = []
    if summary.failed_jobs > 0:
        signals.append(
            JobExecutionAlertSignal(
                severity=IncidentSeverity.CRITICAL,
                category="worker_failure",
                message=(
                    f"{summary.failed_jobs} worker job(s) failed across "
                    f"{summary.action_required} action-required execution(s)."
                ),
                latest_execution_id=_latest_failure_execution_id(summary),
                latest_at=summary.latest_failure_at,
                remediation_steps=_worker_signal_remediation_steps(
                    "worker_failure",
                    summary,
                ),
            )
        )
    if summary.homepage_handoff_failed > 0:
        signals.append(
            JobExecutionAlertSignal(
                severity=IncidentSeverity.WARNING,
                category="homepage_handoff",
                message=f"{summary.homepage_handoff_failed} homepage handoff(s) failed.",
                latest_execution_id=_latest_failure_execution_id(summary),
                latest_at=summary.latest_failure_at,
                remediation_steps=_worker_signal_remediation_steps(
                    "homepage_handoff",
                    summary,
                ),
            )
        )
    if summary.action_required > 0 and not signals:
        signals.append(
            JobExecutionAlertSignal(
                severity=IncidentSeverity.WARNING,
                category="worker_action_required",
                message=f"{summary.action_required} worker execution(s) require review.",
                latest_execution_id=_latest_failure_execution_id(summary),
                latest_at=summary.latest_failure_at,
                remediation_steps=_worker_signal_remediation_steps(
                    "worker_action_required",
                    summary,
                ),
            )
        )
    severity = _max_alert_severity(signal.severity for signal in signals)
    return JobExecutionAlertReport(
        days=days,
        severity=severity,
        action_required=severity != IncidentSeverity.INFO,
        message=_worker_alert_message(summary, severity),
        signals=signals,
        recommended_actions=_worker_alert_recommended_actions(summary),
        trend_summary=summary,
    )


def notify_job_execution_alert(
    receipt_dir: Path,
    *,
    days: int = 14,
    endpoint: str | None = None,
    timeout_seconds: float = 5.0,
) -> JobExecutionAlertDelivery:
    report = job_execution_alert_report(receipt_dir, days=days)
    delivery = _deliver_job_execution_alert(
        report,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
    )
    write_job_execution_alert_delivery(delivery, receipt_dir)
    return delivery


def write_job_execution_alert_delivery(
    delivery: JobExecutionAlertDelivery,
    receipt_dir: Path,
) -> Path:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = job_execution_alert_notification_log_path(receipt_dir)
    if path.exists():
        deliveries = json.loads(path.read_text(encoding="utf-8"))
    else:
        deliveries = []
    deliveries.append(delivery.model_dump(mode="json"))
    path.write_text(json.dumps(deliveries, indent=2), encoding="utf-8")
    return path


def job_execution_alert_notification_log(
    receipt_dir: Path,
) -> list[JobExecutionAlertDelivery]:
    path = job_execution_alert_notification_log_path(receipt_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [JobExecutionAlertDelivery.model_validate(item) for item in data]


def job_execution_alert_notification_log_path(receipt_dir: Path) -> Path:
    return receipt_dir / "worker-alert-notification-log.json"


def get_job_execution_report(receipt_dir: Path, execution_id: str) -> JobExecutionReport:
    normalized = execution_id.strip()
    if not normalized:
        raise FileNotFoundError("Job execution not found.")
    for path in _job_execution_receipt_paths(receipt_dir):
        report = _read_job_execution_report(path)
        if report.execution_id == normalized:
            return report
    raise FileNotFoundError(f"Job execution not found: {execution_id}")


def job_recovery_plan(
    receipt_dir: Path,
    execution_id: str,
    *,
    actor: str | None = None,
    notes: str | None = None,
) -> JobRecoveryPlan:
    report = get_job_execution_report(receipt_dir, execution_id)
    blocked_reason = (
        "Dry-run worker receipts are schedule previews and cannot be recovered."
        if report.dry_run
        else None
    )
    failed_jobs = [] if report.dry_run else [
        ContentJob(
            name=result.job_name,
            topic=result.topic,
            source_urls=result.source_urls,
            publish=result.publish,
            homepage_handoff=result.homepage_handoff,
            tags=result.tags,
            metadata={
                **result.metadata,
                "recovery_source_execution_id": report.execution_id,
                **_recovery_metadata(actor=actor, notes=notes),
            },
        )
        for result in report.results
        if result.error is not None or str(result.status) == "failed"
    ]
    return JobRecoveryPlan(
        execution_id=report.execution_id,
        source_execution_name=report.name,
        source_dry_run=report.dry_run,
        failed_count=len(failed_jobs),
        runnable=blocked_reason is None and bool(failed_jobs),
        blocked_reason=blocked_reason,
        jobs=failed_jobs,
    )


def _recovery_metadata(*, actor: str | None, notes: str | None) -> dict[str, str]:
    metadata: dict[str, str] = {}
    normalized_actor = (actor or "").strip()
    normalized_notes = (notes or "").strip()
    if normalized_actor:
        metadata["recovery_actor"] = normalized_actor
    if normalized_notes:
        metadata["recovery_notes"] = normalized_notes
    return metadata


def job_execution_run_ids(report: JobExecutionReport) -> list[str]:
    seen: set[str] = set()
    run_ids: list[str] = []
    for result in report.results:
        if result.run_id is None or result.run_id in seen:
            continue
        seen.add(result.run_id)
        run_ids.append(result.run_id)
    return run_ids


def job_execution_summary(report: JobExecutionReport) -> JobExecutionSummary:
    generated_runs = sum(1 for result in report.results if result.run_id is not None)
    publish_intent = sum(1 for result in report.results if result.publish)
    handoff_requested = sum(1 for result in report.results if result.homepage_handoff)
    handoff_ready = sum(1 for result in report.results if result.homepage_handoff_path)
    handoff_failed = sum(1 for result in report.results if result.homepage_handoff_error)
    published_runs = sum(
        1
        for result in report.results
        if str(result.status) == RunStatus.PUBLISHED.value or bool(result.published_url)
    )
    action_required = (
        report.failed > 0
        or handoff_failed > 0
        or report.content_assets_error is not None
        or report.delivery_summary_error is not None
        or report.release_evidence_error is not None
        or generated_runs < report.total
    )
    return JobExecutionSummary(
        total_jobs=report.total,
        succeeded=report.succeeded,
        failed=report.failed,
        generated_runs=generated_runs,
        publish_intent=publish_intent,
        review_intent=report.total - publish_intent,
        published_runs=published_runs,
        homepage_handoff_requested=handoff_requested,
        homepage_handoff_ready=handoff_ready,
        homepage_handoff_failed=handoff_failed,
        release_evidence_ready=report.release_evidence_path is not None
        and report.release_evidence_error is None,
        action_required=action_required,
    )


def _scheduled_workflow_review_item(report: JobExecutionReport) -> ScheduledWorkflowReviewItem:
    summary = job_execution_summary(report)
    failure_reasons = [reason for _, reason in _job_execution_failure_reasons(report)]
    return ScheduledWorkflowReviewItem(
        execution_id=report.execution_id,
        name=report.name,
        dry_run=report.dry_run,
        completed_at=report.completed_at,
        action_required=summary.action_required,
        succeeded=report.succeeded,
        total=report.total,
        published_urls=[
            result.published_url for result in report.results if result.published_url is not None
        ],
        homepage_handoff_paths=[
            result.homepage_handoff_path
            for result in report.results
            if result.homepage_handoff_path is not None
        ],
        content_assets_path=report.content_assets_path,
        content_assets_status=report.content_assets_status,
        content_assets_files=report.content_assets_files,
        content_assets_error=report.content_assets_error,
        worker_receipt_path=report.receipt_path,
        release_evidence_path=report.release_evidence_path,
        delivery_summary_markdown_path=report.delivery_summary_markdown_path,
        failure_reasons=failure_reasons,
        recommended_actions=_job_execution_delivery_actions(report, summary),
        pr_title=_scheduled_pr_title(report),
        pr_checklist=_scheduled_pr_checklist(report, summary, failure_reasons),
    )


def _scheduled_workflow_review_markdown(report: ScheduledWorkflowReviewReport) -> str:
    lines = [
        "# Scheduled ContentOps Review",
        "",
        f"- Generated at: `{report.generated_at.isoformat()}`",
        f"- Executions reviewed: `{report.total}`",
        f"- Action required: `{report.action_required_count}`",
        f"- Published URLs: `{report.published_count}`",
        f"- Homepage handoffs: `{report.handoff_count}`",
        f"- Content asset sets: `{report.content_assets_count}`",
        f"- Failed content asset sets: `{report.content_assets_failed_count}`",
        "",
    ]
    if report.operations_console_summary:
        summary = report.operations_console_summary
        lines.extend(
            [
                "## Operations Console",
                "",
                f"- Status: `{summary.get('status', 'unknown')}`",
                f"- Action required: `{str(summary.get('action_required', False)).lower()}`",
                f"- Brief status: `{summary.get('brief_status', 'unknown')}`",
                f"- Release gate: `{summary.get('release_gate_status', 'unknown')}`",
                f"- Retention gate: `{summary.get('retention_gate_status', 'unknown')}`",
                f"- Worker alert severity: `{summary.get('worker_alert_severity', 'unknown')}`",
                f"- Review queue: `{summary.get('review_queue_depth', 0)}`",
                f"- Action-required incidents: `{summary.get('action_required_incidents', 0)}`",
                "",
            ]
        )
    if not report.items:
        lines.extend(
            [
                "No worker execution receipts were found.",
                "",
                (
                    "Run `contentops-worker run-pipeline <pipeline.yaml> "
                    "--receipt-dir artifacts/job-executions`."
                ),
            ]
        )
        return "\n".join(lines) + "\n"
    for item in report.items:
        lines.extend(
            [
                f"## {item.name} `{item.execution_id}`",
                "",
                f"- Completed: `{item.completed_at.isoformat()}`",
                f"- Mode: `{'dry-run' if item.dry_run else 'executed'}`",
                f"- Jobs: `{item.succeeded}/{item.total}`",
                f"- Action required: `{str(item.action_required).lower()}`",
                f"- Release evidence: `{item.release_evidence_path or 'not recorded'}`",
                f"- Delivery summary: `{item.delivery_summary_markdown_path or 'not recorded'}`",
                "",
                "### Published URLs",
                "",
            ]
        )
        if item.published_urls:
            lines.extend(f"- {url}" for url in item.published_urls)
        else:
            lines.append("- None")
        lines.extend(["", "### Homepage Handoffs", ""])
        if item.homepage_handoff_paths:
            lines.extend(f"- `{path}`" for path in item.homepage_handoff_paths)
        else:
            lines.append("- None")
        lines.extend(["", "### Distribution Assets", ""])
        lines.extend(
            [
                f"- Status: `{item.content_assets_status or 'not recorded'}`",
                f"- Path: `{item.content_assets_path or 'not recorded'}`",
                f"- Files: `{', '.join(item.content_assets_files) or 'none'}`",
                f"- Error: `{item.content_assets_error or 'none'}`",
            ]
        )
        lines.extend(["", "### Failures", ""])
        if item.failure_reasons:
            lines.extend(f"- {reason}" for reason in item.failure_reasons)
        else:
            lines.append("- None")
        lines.extend(["", "### Next Actions", ""])
        lines.extend(f"- {action}" for action in item.recommended_actions)
        lines.extend(
            [
                "",
                "### PR Handoff",
                "",
                f"- Suggested PR title: `{item.pr_title}`",
                "- Suggested checklist:",
            ]
        )
        lines.extend(f"  - [ ] {check}" for check in item.pr_checklist)
        lines.append("")
    return "\n".join(lines)


def _scheduled_pr_title(report: JobExecutionReport) -> str:
    return f"Publish scheduled ContentOps output: {report.name} {report.execution_id}"


def _scheduled_pr_checklist(
    report: JobExecutionReport,
    summary: JobExecutionSummary,
    failure_reasons: list[str],
) -> list[str]:
    checklist = [
        f"Review worker receipt `{report.receipt_path or report.execution_id}`.",
        "Confirm generated drafts, eval reports, source audits, and scorecards are acceptable.",
    ]
    if report.delivery_summary_markdown_path:
        checklist.append(f"Read delivery summary `{report.delivery_summary_markdown_path}`.")
    if report.release_evidence_path:
        checklist.append(f"Inspect release evidence `{report.release_evidence_path}`.")
    if summary.published_runs > 0:
        checklist.append("Verify published URLs render and match the approved content.")
    if summary.homepage_handoff_ready > 0:
        checklist.append("Apply homepage handoff zip files in a separate homepage repository PR.")
    if report.content_assets_path:
        checklist.append("Review regenerated feed, promotion brief, and distribution manifest.")
    if failure_reasons:
        checklist.append("Resolve listed failure reasons before merging publishing changes.")
    if report.dry_run:
        checklist.append("Rerun without dry-run before opening a publishing PR.")
    checklist.append("Link this scheduled review issue or Actions run from the PR description.")
    return checklist


def _scheduled_workflow_pr_title(report: ScheduledWorkflowReviewReport) -> str:
    if not report.items:
        return "Review scheduled ContentOps output"
    latest = report.items[0]
    return f"Review scheduled ContentOps output: {latest.name} {latest.execution_id}"


def _scheduled_workflow_pr_checklist(report: ScheduledWorkflowReviewReport) -> list[str]:
    checklist = [
        "Review the scheduled workflow summary and linked Actions run.",
        "Confirm release evidence and delivery summary artifacts are attached.",
    ]
    if report.operations_console_summary:
        status = str(report.operations_console_summary.get("status") or "unknown")
        checklist.append(f"Review Operations Console status `{status}` before merge.")
        if report.operations_console_summary.get("action_required"):
            checklist.append("Resolve Operations Console action-required signals.")
    if report.published_count:
        checklist.append("Verify published URLs and generated content assets.")
    if report.content_assets_count:
        checklist.append("Review generated feed, promotion brief, and distribution manifest.")
    if report.content_assets_failed_count:
        checklist.append("Regenerate failed content distribution assets before merge.")
    if report.handoff_count:
        checklist.append("Apply homepage handoff artifacts in the target homepage repository.")
    if report.action_required_count:
        checklist.append("Resolve action-required executions before merge.")
    for item in report.items:
        checklist.extend(f"{item.execution_id}: {entry}" for entry in item.pr_checklist)
    return _dedupe_preserve_order(checklist)


def _scheduled_workflow_pr_body(
    report: ScheduledWorkflowReviewReport,
    checklist: list[str],
) -> str:
    lines = [
        "# Scheduled ContentOps Publish Review",
        "",
        "This PR was prepared from scheduled worker execution evidence.",
        "",
        "## Summary",
        "",
        f"- Executions reviewed: `{report.total}`",
        f"- Action required: `{report.action_required_count}`",
        f"- Published URLs: `{report.published_count}`",
        f"- Homepage handoffs: `{report.handoff_count}`",
        f"- Content asset sets: `{report.content_assets_count}`",
        f"- Failed content asset sets: `{report.content_assets_failed_count}`",
        "",
    ]
    if report.operations_console_summary:
        summary = report.operations_console_summary
        lines.extend(
            [
                "## Operations Console",
                "",
                f"- Status: `{summary.get('status', 'unknown')}`",
                f"- Action required: `{str(summary.get('action_required', False)).lower()}`",
                f"- Release gate: `{summary.get('release_gate_status', 'unknown')}`",
                f"- Retention gate: `{summary.get('retention_gate_status', 'unknown')}`",
                f"- Worker alert severity: `{summary.get('worker_alert_severity', 'unknown')}`",
                "",
            ]
        )
    lines.extend(["## Checklist", ""])
    lines.extend(f"- [ ] {item}" for item in checklist)
    lines.extend(["", "## Evidence", "", _scheduled_workflow_review_markdown(report)])
    return "\n".join(lines)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _job_execution_delivery_summary_payload(report: JobExecutionReport) -> dict[str, Any]:
    summary = job_execution_summary(report)
    published_items = [
        {
            "job_name": result.job_name,
            "topic": result.topic,
            "run_id": result.run_id,
            "published_url": result.published_url,
            "artifact_dir": result.artifact_dir,
            "tags": result.tags,
        }
        for result in report.results
        if result.published_url
    ]
    failed_items = [
        {
            "job_name": result.job_name,
            "topic": result.topic,
            "run_id": result.run_id,
            "status": str(result.status),
            "error": result.error or result.homepage_handoff_error,
        }
        for result in report.results
        if result.error or result.homepage_handoff_error
    ]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "execution_id": report.execution_id,
        "name": report.name,
        "dry_run": report.dry_run,
        "started_at": report.started_at.isoformat(),
        "completed_at": report.completed_at.isoformat(),
        "duration_ms": report.duration_ms,
        "summary": summary.model_dump(mode="json"),
        "published_items": published_items,
        "failed_items": failed_items,
        "content_assets": {
            "path": report.content_assets_path,
            "status": report.content_assets_status,
            "files": report.content_assets_files,
            "error": report.content_assets_error,
        },
        "release_evidence": {
            "path": report.release_evidence_path,
            "status": report.release_evidence_status,
            "files": report.release_evidence_files,
            "error": report.release_evidence_error,
        },
        "recommended_actions": _job_execution_delivery_actions(report, summary),
    }


def _job_execution_delivery_summary_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    content_assets = payload["content_assets"]
    release_evidence = payload["release_evidence"]
    lines = [
        f"# Worker Delivery Summary: {payload['name']}",
        "",
        f"- Execution ID: `{payload['execution_id']}`",
        f"- Generated at: {payload['generated_at']}",
        f"- Duration: {payload['duration_ms']} ms",
        f"- Jobs: {summary['succeeded']}/{summary['total_jobs']} succeeded",
        f"- Published runs: {summary['published_runs']}",
        f"- Action required: {str(summary['action_required']).lower()}",
        "",
        "## Published Content",
        "",
    ]
    published_items = payload["published_items"]
    if published_items:
        for item in published_items:
            lines.append(
                f"- {item['job_name']}: {item['topic']} "
                f"({item['published_url'] or 'not published'})"
            )
    else:
        lines.append("- No content was published in this execution.")
    lines.extend(
        [
            "",
            "## Distribution Assets",
            "",
            f"- Status: {content_assets['status'] or 'n/a'}",
            f"- Path: `{content_assets['path'] or 'not recorded'}`",
            f"- Files: {', '.join(content_assets['files']) or 'none'}",
            f"- Error: {content_assets['error'] or 'none'}",
            "",
            "## Release Evidence",
            "",
            f"- Status: {release_evidence['status'] or 'n/a'}",
            f"- Path: `{release_evidence['path'] or 'not recorded'}`",
            f"- Files: {len(release_evidence['files'])}",
            f"- Error: {release_evidence['error'] or 'none'}",
            "",
            "## Recommended Actions",
            "",
        ]
    )
    for action in payload["recommended_actions"]:
        lines.append(f"- {action}")
    return "\n".join(lines) + "\n"


def _job_execution_delivery_actions(
    report: JobExecutionReport,
    summary: JobExecutionSummary,
) -> list[str]:
    if report.dry_run:
        return [
            "Rerun without `--dry-run` when this schedule is ready for production execution."
        ]
    actions: list[str] = []
    if summary.published_runs:
        actions.append(
            "Review generated distribution assets before committing the publishing target."
        )
    if report.content_assets_error:
        actions.append(
            "Regenerate content assets after fixing the publish index or output directory."
        )
    if report.release_evidence_error:
        actions.append("Regenerate release evidence after fixing the reported evidence error.")
    if report.failed:
        actions.append("Generate a recovery plan and rerun only failed worker jobs.")
    if not actions:
        actions.append(
            "No operator action is required; archive this summary with release evidence."
        )
    return actions


def _job_execution_trend_bucket(
    bucket_date: date,
    reports: list[JobExecutionReport],
) -> JobExecutionTrendBucket:
    summary = _job_execution_trend_summary(reports)
    return JobExecutionTrendBucket(
        date=bucket_date.isoformat(),
        execution_count=summary.execution_count,
        total_jobs=summary.total_jobs,
        succeeded_jobs=summary.succeeded_jobs,
        failed_jobs=summary.failed_jobs,
        generated_runs=summary.generated_runs,
        published_runs=summary.published_runs,
        homepage_handoff_ready=summary.homepage_handoff_ready,
        homepage_handoff_failed=summary.homepage_handoff_failed,
        action_required=summary.action_required,
        success_rate=summary.success_rate,
        publish_rate=summary.publish_rate,
        handoff_success_rate=summary.handoff_success_rate,
        top_failure_reasons=summary.top_failure_reasons,
    )


def _job_execution_trend_summary(
    reports: list[JobExecutionReport],
) -> JobExecutionTrendSummary:
    summaries = [job_execution_summary(report) for report in reports]
    total_jobs = sum(summary.total_jobs for summary in summaries)
    succeeded_jobs = sum(summary.succeeded for summary in summaries)
    generated_runs = sum(summary.generated_runs for summary in summaries)
    published_runs = sum(summary.published_runs for summary in summaries)
    handoff_ready = sum(summary.homepage_handoff_ready for summary in summaries)
    handoff_failed = sum(summary.homepage_handoff_failed for summary in summaries)
    handoff_total = handoff_ready + handoff_failed
    latest_success_at = max(
        (report.completed_at for report in reports if report.failed == 0),
        default=None,
    )
    latest_failure_at = max(
        (
            report.completed_at
            for report in reports
            if job_execution_summary(report).action_required
        ),
        default=None,
    )
    return JobExecutionTrendSummary(
        execution_count=len(reports),
        total_jobs=total_jobs,
        succeeded_jobs=succeeded_jobs,
        failed_jobs=sum(summary.failed for summary in summaries),
        generated_runs=generated_runs,
        published_runs=published_runs,
        homepage_handoff_ready=handoff_ready,
        homepage_handoff_failed=handoff_failed,
        action_required=sum(1 for summary in summaries if summary.action_required),
        success_rate=_ratio(succeeded_jobs, total_jobs),
        publish_rate=_ratio(published_runs, generated_runs),
        handoff_success_rate=_ratio(handoff_ready, handoff_total),
        latest_success_at=latest_success_at,
        latest_failure_at=latest_failure_at,
        top_failure_reasons=_top_failure_reasons(reports),
    )


def _top_failure_reasons(
    reports: list[JobExecutionReport],
    limit: int = 5,
) -> list[JobExecutionFailureReason]:
    counts: Counter[tuple[str, str]] = Counter()
    latest: dict[tuple[str, str], tuple[str, datetime]] = {}
    for report in reports:
        for category, reason in _job_execution_failure_reasons(report):
            key = (category, reason)
            counts[key] += 1
            current = latest.get(key)
            if current is None or report.completed_at > current[1]:
                latest[key] = (report.execution_id, report.completed_at)
    return [
        JobExecutionFailureReason(
            category=category,
            reason=reason,
            count=count,
            latest_execution_id=latest[(category, reason)][0],
            latest_at=latest[(category, reason)][1],
            remediation_steps=_job_failure_remediation_steps(category, reason),
        )
        for (category, reason), count in counts.most_common(limit)
    ]


def _job_execution_failure_reasons(report: JobExecutionReport) -> list[tuple[str, str]]:
    reasons: list[tuple[str, str]] = []
    if report.dry_run:
        reasons.append(("dry_run_preview", "dry run: execution did not generate persisted runs"))
    if report.content_assets_error:
        reasons.append(
            (
                "content_distribution",
                f"content assets: {_normalize_failure_reason(report.content_assets_error)}",
            )
        )
    if report.delivery_summary_error:
        reasons.append(
            (
                "delivery_summary",
                f"delivery summary: {_normalize_failure_reason(report.delivery_summary_error)}",
            )
        )
    if report.release_evidence_error:
        reasons.append(
            (
                "release_evidence",
                f"release evidence: {_normalize_failure_reason(report.release_evidence_error)}",
            )
        )
    for result in report.results:
        if result.error:
            reasons.append(
                (
                    _job_result_failure_category(result.error),
                    f"{result.job_name}: {_normalize_failure_reason(result.error)}",
                )
            )
        if result.homepage_handoff_error:
            reasons.append(
                (
                    "homepage_handoff",
                    f"{result.job_name} homepage handoff: "
                    f"{_normalize_failure_reason(result.homepage_handoff_error)}",
                )
            )
        if not result.error and str(result.status) == "failed":
            reasons.append(
                ("worker_failure", f"{result.job_name}: failed status without error detail")
            )
    return reasons


def _normalize_failure_reason(reason: str) -> str:
    normalized = " ".join(reason.strip().split())
    return normalized[:180] if normalized else "unknown failure"


def _job_result_failure_category(reason: str) -> str:
    lowered = reason.lower()
    if "provider" in lowered or "research" in lowered or "source" in lowered:
        return "provider_failure"
    if "approval" in lowered:
        return "approval_gate"
    if "publish" in lowered:
        return "publishing"
    if "config" in lowered or "environment" in lowered:
        return "configuration"
    return "worker_failure"


def _deliver_job_execution_alert(
    report: JobExecutionAlertReport,
    *,
    endpoint: str | None,
    timeout_seconds: float,
) -> JobExecutionAlertDelivery:
    if not report.action_required:
        return JobExecutionAlertDelivery(
            provider="local",
            status="skipped",
            severity=report.severity,
            action_required=report.action_required,
            message=report.message,
        )
    if endpoint is None:
        return JobExecutionAlertDelivery(
            provider="local",
            status="skipped",
            severity=report.severity,
            action_required=report.action_required,
            message=report.message,
        )
    try:
        response = httpx.post(
            endpoint,
            json={"worker_execution_alert": report.model_dump(mode="json")},
            timeout=timeout_seconds,
        )
    except httpx.HTTPError as exc:
        return JobExecutionAlertDelivery(
            provider="webhook",
            status="failed",
            severity=report.severity,
            action_required=report.action_required,
            message=report.message,
            endpoint=endpoint,
            error=str(exc),
        )
    return JobExecutionAlertDelivery(
        provider="webhook",
        status="delivered" if response.is_success else "failed",
        severity=report.severity,
        action_required=report.action_required,
        message=report.message,
        endpoint=endpoint,
        status_code=response.status_code,
        error=None if response.is_success else response.text[:500],
    )


def _deliver_worker_delivery_summary(
    report: JobExecutionReport,
    *,
    endpoint: str | None,
    timeout_seconds: float,
) -> WorkerDeliverySummaryDelivery:
    payload = _read_delivery_summary_payload(report)
    action_required = bool(payload.get("summary", {}).get("action_required"))
    message = _worker_delivery_summary_message(payload)
    if endpoint is None:
        return WorkerDeliverySummaryDelivery(
            execution_id=report.execution_id,
            provider="local",
            status="skipped",
            action_required=action_required,
            message=message,
            summary_path=report.delivery_summary_path,
            markdown_path=report.delivery_summary_markdown_path,
        )
    try:
        response = httpx.post(
            endpoint,
            json={
                "worker_delivery_summary": payload,
                "markdown": _read_delivery_summary_markdown(report),
            },
            timeout=timeout_seconds,
        )
    except httpx.HTTPError as exc:
        return WorkerDeliverySummaryDelivery(
            execution_id=report.execution_id,
            provider="webhook",
            status="failed",
            action_required=action_required,
            message=message,
            summary_path=report.delivery_summary_path,
            markdown_path=report.delivery_summary_markdown_path,
            endpoint=endpoint,
            error=str(exc),
        )
    return WorkerDeliverySummaryDelivery(
        execution_id=report.execution_id,
        provider="webhook",
        status="delivered" if response.is_success else "failed",
        action_required=action_required,
        message=message,
        summary_path=report.delivery_summary_path,
        markdown_path=report.delivery_summary_markdown_path,
        endpoint=endpoint,
        status_code=response.status_code,
        error=None if response.is_success else response.text[:500],
    )


def _read_delivery_summary_payload(report: JobExecutionReport) -> dict[str, Any]:
    if report.delivery_summary_path is None:
        return _job_execution_delivery_summary_payload(report)
    path = Path(report.delivery_summary_path)
    if not path.exists():
        return _job_execution_delivery_summary_payload(report)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return _job_execution_delivery_summary_payload(report)
    return data


def _read_delivery_summary_markdown(report: JobExecutionReport) -> str:
    if report.delivery_summary_markdown_path is None:
        return _job_execution_delivery_summary_markdown(
            _job_execution_delivery_summary_payload(report)
        )
    path = Path(report.delivery_summary_markdown_path)
    if not path.exists():
        return _job_execution_delivery_summary_markdown(
            _job_execution_delivery_summary_payload(report)
        )
    return path.read_text(encoding="utf-8")


def _worker_delivery_summary_message(payload: dict[str, Any]) -> str:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    published_runs = int(summary.get("published_runs") or 0)
    action_required = bool(summary.get("action_required"))
    outcome = "requires review" if action_required else "completed"
    return (
        f"Worker execution {payload.get('execution_id', 'unknown')} {outcome}: "
        f"{published_runs} published run(s)."
    )


def _report_receipt_dir(report: JobExecutionReport) -> Path:
    if report.receipt_path is None:
        raise ValueError("Job execution receipt path is missing.")
    return Path(report.receipt_path).parent


def _latest_failure_execution_id(summary: JobExecutionTrendSummary) -> str | None:
    if not summary.top_failure_reasons:
        return None
    return summary.top_failure_reasons[0].latest_execution_id


def _worker_alert_message(
    summary: JobExecutionTrendSummary,
    severity: IncidentSeverity,
) -> str:
    if severity == IncidentSeverity.INFO:
        return "Worker automation is healthy for the selected window."
    if summary.top_failure_reasons:
        top_reason = summary.top_failure_reasons[0]
        return (
            f"Worker automation needs attention: {top_reason.reason} "
            f"occurred {top_reason.count} time(s)."
        )
    return f"{summary.action_required} worker execution(s) require operator review."


def _worker_alert_recommended_actions(summary: JobExecutionTrendSummary) -> list[str]:
    if summary.action_required == 0:
        return ["Keep the current worker schedule and monitor the next execution."]
    actions = [
        "Open /dashboard/job-execution-trends and inspect the latest action-required execution.",
        "Run contentops job-recovery-plan <execution_id> for failed worker jobs.",
    ]
    if summary.top_failure_reasons:
        actions.extend(summary.top_failure_reasons[0].remediation_steps[:2])
    if summary.homepage_handoff_failed > 0:
        actions.append("Check CONTENTOPS_HOMEPAGE_REPO_PATH and homepage handoff artifacts.")
    if summary.failed_jobs > 0:
        actions.append(
            "Review provider configuration, source reachability, and generated run logs."
        )
    return actions


def _worker_signal_remediation_steps(
    category: str,
    summary: JobExecutionTrendSummary,
) -> list[str]:
    if category == "worker_failure":
        steps = [
            "Open the latest failed worker execution and inspect per-job error details.",
            "Generate a recovery plan with `contentops job-recovery-plan <execution_id>`.",
        ]
        if summary.top_failure_reasons:
            steps.extend(summary.top_failure_reasons[0].remediation_steps[:2])
        return _dedupe_steps(steps)
    if category == "homepage_handoff":
        return [
            "Confirm CONTENTOPS_HOMEPAGE_REPO_PATH points to a writable homepage checkout.",
            "Inspect homepage handoff artifacts and rerun the failed worker job.",
        ]
    if category == "worker_action_required":
        return [
            "Open /dashboard/job-execution-trends and inspect the latest execution.",
            "If the execution was a dry run, rerun it without `--dry-run` to generate runs.",
        ]
    return ["Inspect the worker execution receipt and rerun after resolving the failure."]


def _job_failure_remediation_steps(category: str, reason: str) -> list[str]:
    if category == "dry_run_preview":
        return [
            "Rerun the worker without `--dry-run` when a real execution is intended.",
            "Use dry-run receipts only for schedule validation, not release readiness.",
        ]
    if category == "content_distribution":
        return [
            "Regenerate content distribution assets with `contentops content-assets`.",
            "Confirm the publishing target contains contentops-publish-index.json.",
            "Rerun the worker so release evidence can index the distribution manifest.",
        ]
    if category == "delivery_summary":
        return [
            "Open the worker receipt and confirm delivery_summary_path is writable.",
            "Retry `contentops job-execution-delivery-notify <execution_id>` after repair.",
        ]
    if category == "release_evidence":
        return [
            "Run `contentops release-evidence` locally to reproduce the evidence failure.",
            "Fix missing artifacts, deployment checks, or artifact store settings.",
            "Rerun the worker so a fresh post-run release evidence bundle is written.",
        ]
    if category == "homepage_handoff":
        return [
            "Check CONTENTOPS_HOMEPAGE_REPO_PATH and homepage repository permissions.",
            "Inspect homepage handoff artifacts for missing files or git write errors.",
            "Rerun the failed job after the homepage checkout is writable.",
        ]
    if category == "provider_failure":
        return [
            "Check provider API keys, network access, and source URL reachability.",
            "Rerun the failed job with the same topic after provider access is restored.",
        ]
    if category in {"approval_gate", "publishing"}:
        return [
            "Open the generated run in the dashboard and review approval or publish gates.",
            "Approve the run or fix publish configuration before rerunning publication.",
        ]
    if category == "configuration":
        return [
            "Run `contentops config-audit --json` to identify missing settings.",
            "Populate required environment variables or secret references.",
        ]
    return [
        "Open the worker execution detail and inspect the failed job error.",
        "Generate a recovery plan and rerun only the failed jobs after fixing the cause.",
    ]


def _dedupe_steps(steps: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for step in steps:
        if step in seen:
            continue
        seen.add(step)
        deduped.append(step)
    return deduped


def _max_alert_severity(severities: Iterable[IncidentSeverity]) -> IncidentSeverity:
    rank = {
        IncidentSeverity.INFO: 0,
        IncidentSeverity.WARNING: 1,
        IncidentSeverity.CRITICAL: 2,
    }
    selected = IncidentSeverity.INFO
    for severity in severities:
        if rank[severity] > rank[selected]:
            selected = severity
    return selected


def _date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _job_execution_receipt_paths(receipt_dir: Path) -> list[Path]:
    if not receipt_dir.exists():
        return []
    ignored_names = {
        "s3-mirror-log.json",
        "worker-alert-notification-log.json",
        "worker-delivery-summary-notification-log.json",
    }
    return sorted(
        (
            path
            for path in receipt_dir.glob("*.json")
            if path.name not in ignored_names
            and not path.name.endswith("-delivery-summary.json")
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _read_job_execution_report(path: Path) -> JobExecutionReport:
    report = JobExecutionReport.model_validate_json(path.read_text(encoding="utf-8"))
    report.receipt_path = str(path)
    return report


def _duration_ms(started_at: datetime) -> int:
    return max(round((datetime.now(UTC) - started_at).total_seconds() * 1000), 0)
