from __future__ import annotations

from datetime import UTC, datetime
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
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)

    def to_request(self) -> RunRequest:
        return RunRequest(
            topic=self.topic,
            source_urls=self.source_urls,
            publish=self.publish,
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
    publish: bool = False
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    run_id: str | None = None
    status: RunStatus | str
    artifact_dir: str | None = None
    published_url: str | None = None
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


class JobRunner:
    def __init__(self, pipeline: ContentOpsPipeline) -> None:
        self.pipeline = pipeline

    def run(self, job_file: ContentJobFile, receipt_dir: Path | None = None) -> JobExecutionReport:
        started_at = datetime.now(UTC)
        results: list[JobRunResult] = []
        for job in job_file.jobs:
            job_started = datetime.now(UTC)
            try:
                run_result = self.pipeline.run(job.to_request())
                results.append(
                    JobRunResult(
                        job_name=job.name,
                        topic=job.topic,
                        publish=job.publish,
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
                        publish=job.publish,
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
                publish=job.publish,
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
        target_dir = receipt_dir or self.pipeline.artifact_store.root / "job-executions"
        return write_job_execution_report(report, target_dir)


def load_job_file(path: Path) -> ContentJobFile:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Job file must contain a YAML mapping.")
    return ContentJobFile.from_mapping(data)


def write_job_execution_report(report: JobExecutionReport, receipt_dir: Path) -> Path:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = (
        receipt_dir
        / f"{report.started_at:%Y%m%dT%H%M%SZ}-{report.name}-{report.execution_id}.json"
    )
    report.receipt_path = str(path)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


def _duration_ms(started_at: datetime) -> int:
    return max(round((datetime.now(UTC) - started_at).total_seconds() * 1000), 0)
