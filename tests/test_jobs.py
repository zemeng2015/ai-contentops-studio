from __future__ import annotations

from pathlib import Path

from contentops_core.factory import build_pipeline
from contentops_core.jobs import (
    JobRunner,
    get_job_execution_report,
    list_job_execution_reports,
    load_job_file,
    write_job_execution_report,
)
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
    assert report.dry_run is False
    assert report.receipt_path is not None
    assert Path(report.receipt_path).exists()
    assert all(result.duration_ms is not None for result in report.results)
    assert all(result.run_id for result in report.results)


def test_job_runner_builds_dry_run_receipt(tmp_path: Path) -> None:
    path = tmp_path / "jobs.yaml"
    path.write_text(
        """
name: dry-calendar
jobs:
  - name: roundup
    topic: AI platform weekly roundup
    publish: true
    tags: [ai, roundup]
    metadata:
      owner: zack
""",
        encoding="utf-8",
    )

    report = JobRunner.dry_run_report(load_job_file(path))

    assert report.name == "dry-calendar"
    assert report.dry_run is True
    assert report.total == 1
    assert report.succeeded == 1
    assert report.results[0].status == "dry_run"
    assert report.results[0].publish is True
    assert report.results[0].tags == ["ai", "roundup"]
    assert report.results[0].metadata == {"owner": "zack"}


def test_job_execution_receipts_can_be_listed_and_loaded(tmp_path: Path) -> None:
    path = tmp_path / "jobs.yaml"
    path.write_text("name: queryable\ntopic: Queryable job history\n", encoding="utf-8")
    receipt_dir = tmp_path / "receipts"
    report = JobRunner.dry_run_report(load_job_file(path))

    write_job_execution_report(report, receipt_dir)
    report_list = list_job_execution_reports(receipt_dir, limit=10)
    loaded = get_job_execution_report(receipt_dir, report.execution_id)

    assert report_list.total == 1
    assert report_list.items[0].execution_id == report.execution_id
    assert report_list.items[0].receipt_path is not None
    assert loaded.name == "queryable"
    assert loaded.results[0].topic == "Queryable job history"


def test_missing_job_execution_history_is_empty(tmp_path: Path) -> None:
    report_list = list_job_execution_reports(tmp_path / "missing", limit=10)

    assert report_list.total == 0
    assert report_list.items == []
