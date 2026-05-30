from __future__ import annotations

from pathlib import Path
from typing import Any

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
    run_id: str | None = None
    status: RunStatus | str
    artifact_dir: str | None = None
    published_url: str | None = None
    error: str | None = None


class JobExecutionReport(BaseModel):
    name: str
    total: int
    succeeded: int
    failed: int
    results: list[JobRunResult]


class JobRunner:
    def __init__(self, pipeline: ContentOpsPipeline) -> None:
        self.pipeline = pipeline

    def run(self, job_file: ContentJobFile) -> JobExecutionReport:
        results: list[JobRunResult] = []
        for job in job_file.jobs:
            try:
                run_result = self.pipeline.run(job.to_request())
                results.append(
                    JobRunResult(
                        job_name=job.name,
                        topic=job.topic,
                        run_id=run_result.run.id,
                        status=run_result.run.status,
                        artifact_dir=str(run_result.run.artifact_dir),
                        published_url=run_result.run.published_url,
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive execution boundary
                results.append(
                    JobRunResult(
                        job_name=job.name,
                        topic=job.topic,
                        status="failed",
                        error=str(exc),
                    )
                )
        failed = sum(1 for result in results if result.error is not None)
        return JobExecutionReport(
            name=job_file.name,
            total=len(results),
            succeeded=len(results) - failed,
            failed=failed,
            results=results,
        )


def load_job_file(path: Path) -> ContentJobFile:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Job file must contain a YAML mapping.")
    return ContentJobFile.from_mapping(data)
