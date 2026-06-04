from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import BaseModel, Field

from contentops_core.models import RunRequest, RunStatus
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


class ContentJobFile(BaseModel):
    name: str = "contentops-jobs"
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


class JobExecutionTrendReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    days: int = Field(ge=1)
    buckets: list[JobExecutionTrendBucket]
    summary: JobExecutionTrendSummary


class JobExecutionListResponse(BaseModel):
    items: list[JobExecutionReport]
    total: int
    limit: int
    offset: int


class WorkerJobCatalogItem(BaseModel):
    path: str
    name: str
    valid: bool = True
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


class JobRecoveryPlan(BaseModel):
    execution_id: str
    source_execution_name: str
    failed_count: int
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
    return WorkerJobCatalogItem(
        path=display_path,
        name=job_file.name,
        valid=True,
        total=len(job_file.jobs),
        publish_count=publish_count,
        review_count=len(job_file.jobs) - publish_count,
        handoff_count=handoff_count,
        topics=[job.topic for job in job_file.jobs],
        tags=tags,
        jobs=job_file.jobs,
    )


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


def get_job_execution_report(receipt_dir: Path, execution_id: str) -> JobExecutionReport:
    normalized = execution_id.strip()
    if not normalized:
        raise FileNotFoundError("Job execution not found.")
    for path in _job_execution_receipt_paths(receipt_dir):
        report = _read_job_execution_report(path)
        if report.execution_id == normalized:
            return report
    raise FileNotFoundError(f"Job execution not found: {execution_id}")


def job_recovery_plan(receipt_dir: Path, execution_id: str) -> JobRecoveryPlan:
    report = get_job_execution_report(receipt_dir, execution_id)
    failed_jobs = [
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
            },
        )
        for result in report.results
        if result.error is not None or str(result.status) == "failed"
    ]
    return JobRecoveryPlan(
        execution_id=report.execution_id,
        source_execution_name=report.name,
        failed_count=len(failed_jobs),
        jobs=failed_jobs,
    )


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
    )


def _date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _job_execution_receipt_paths(receipt_dir: Path) -> list[Path]:
    if not receipt_dir.exists():
        return []
    return sorted(
        (path for path in receipt_dir.glob("*.json") if path.name != "s3-mirror-log.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _read_job_execution_report(path: Path) -> JobExecutionReport:
    report = JobExecutionReport.model_validate_json(path.read_text(encoding="utf-8"))
    report.receipt_path = str(path)
    return report


def _duration_ms(started_at: datetime) -> int:
    return max(round((datetime.now(UTC) - started_at).total_seconds() * 1000), 0)
