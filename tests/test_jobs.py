from __future__ import annotations

from pathlib import Path

from contentops_core.factory import build_pipeline
from contentops_core.jobs import JobRunner, load_job_file
from contentops_core.settings import Settings


def test_load_job_file_supports_legacy_single_job(tmp_path: Path) -> None:
    path = tmp_path / "job.yaml"
    path.write_text(
        """
name: daily-ai-roundup
topic: AI engineering roundup
publish: false
source_urls:
  - https://example.com/ai
""",
        encoding="utf-8",
    )

    job_file = load_job_file(path)

    assert job_file.name == "daily-ai-roundup"
    assert len(job_file.jobs) == 1
    assert job_file.jobs[0].topic == "AI engineering roundup"
    assert job_file.jobs[0].source_urls == ["https://example.com/ai"]


def test_load_job_file_supports_batch_jobs(tmp_path: Path) -> None:
    path = tmp_path / "jobs.yaml"
    path.write_text(
        """
name: content-calendar
jobs:
  - name: evals
    topic: LLM evaluation systems
  - name: agents
    topic: Agent workflow observability
    publish: true
""",
        encoding="utf-8",
    )

    job_file = load_job_file(path)

    assert job_file.name == "content-calendar"
    assert [job.name for job in job_file.jobs] == ["evals", "agents"]
    assert job_file.jobs[1].publish is True


def test_job_runner_executes_batch(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    path = tmp_path / "jobs.yaml"
    path.write_text(
        """
name: content-calendar
jobs:
  - name: evals
    topic: LLM evaluation systems
  - name: agents
    topic: Agent workflow observability
""",
        encoding="utf-8",
    )

    report = JobRunner(build_pipeline(settings)).run(load_job_file(path))

    assert report.name == "content-calendar"
    assert report.total == 2
    assert report.succeeded == 2
    assert report.failed == 0
    assert all(result.run_id for result in report.results)
