from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from contentops_core.factory import build_pipeline
from contentops_core.jobs import (
    ContentJob,
    ContentJobFile,
    JobExecutionReport,
    JobRunner,
    JobRunResult,
    get_job_execution_report,
    job_execution_alert_notification_log,
    job_execution_alert_report,
    job_execution_summary,
    job_execution_trends,
    job_recovery_plan,
    list_job_execution_reports,
    list_worker_job_catalog,
    load_job_file,
    notify_job_execution_alert,
    notify_worker_delivery_summary,
    worker_delivery_summary_notification_log,
    write_job_execution_delivery_summary,
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
    homepage_handoff: true
""",
        encoding="utf-8",
    )

    job_file = load_job_file(path)

    assert job_file.name == "content-calendar"
    assert [job.name for job in job_file.jobs] == ["evals", "agents"]
    assert job_file.jobs[1].publish is True
    assert job_file.jobs[1].homepage_handoff is True


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


def test_job_runner_persists_workflow_context(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    path = tmp_path / "jobs.yaml"
    path.write_text(
        """
name: project-updates
jobs:
  - name: repo-update
    topic: GitHub repository launch update
    source_urls:
      - https://github.com/zemeng2015/ai-contentops-studio
    tags: [github, portfolio]
    metadata:
      research_provider: github
      content_type: project update
""",
        encoding="utf-8",
    )

    report = JobRunner(build_pipeline(settings)).run(load_job_file(path))
    run_id = report.results[0].run_id
    assert run_id is not None
    artifact_dir = Path(str(report.results[0].artifact_dir))
    context = (artifact_dir / "workflow-context.json").read_text(encoding="utf-8")
    request = (artifact_dir / "request.json").read_text(encoding="utf-8")

    assert '"contentops_workflow_name": "project-updates"' in context
    assert '"contentops_job_name": "repo-update"' in context
    assert '"contentops_job_tags": "github,portfolio"' in context
    assert '"research_provider": "github"' in request


def test_job_runner_builds_dry_run_receipt(tmp_path: Path) -> None:
    path = tmp_path / "jobs.yaml"
    path.write_text(
        """
name: dry-calendar
jobs:
  - name: roundup
    topic: AI platform weekly roundup
    publish: true
    homepage_handoff: true
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
    assert report.results[0].homepage_handoff is True
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


def test_job_execution_summary_counts_outcomes() -> None:
    report = JobExecutionReport(
        name="summary",
        total=3,
        succeeded=2,
        failed=1,
        release_evidence_path="release-evidence",
        results=[
            JobRunResult(
                job_name="published",
                topic="Published",
                publish=True,
                run_id="run-published",
                status="published",
                published_url="https://example.com/published",
            ),
            JobRunResult(
                job_name="handoff",
                topic="Handoff",
                homepage_handoff=True,
                run_id="run-handoff",
                status="needs_review",
                homepage_handoff_path="artifacts/run-handoff.zip",
            ),
            JobRunResult(
                job_name="failed",
                topic="Failed",
                homepage_handoff=True,
                status="failed",
                homepage_handoff_error="homepage repo missing",
                error="provider failed",
            ),
        ],
    )

    summary = job_execution_summary(report)

    assert summary.generated_runs == 2
    assert summary.publish_intent == 1
    assert summary.review_intent == 2
    assert summary.published_runs == 1
    assert summary.homepage_handoff_requested == 2
    assert summary.homepage_handoff_ready == 1
    assert summary.homepage_handoff_failed == 1
    assert summary.release_evidence_ready is True
    assert summary.action_required is True


def test_job_execution_delivery_summary_writes_json_and_markdown(tmp_path: Path) -> None:
    report = JobExecutionReport(
        name="delivery-summary",
        total=1,
        succeeded=1,
        failed=0,
        content_assets_path=str(tmp_path / "site"),
        content_assets_status="generated",
        content_assets_files=["feed.xml", "promotion-brief.md"],
        release_evidence_path=str(tmp_path / "release-evidence"),
        release_evidence_status="warn",
        release_evidence_files=["summary.json", "worker_delivery_summaries.json"],
        results=[
            JobRunResult(
                job_name="published",
                topic="Published AI content",
                publish=True,
                run_id="run-summary",
                status="published",
                published_url="https://example.com/published",
            )
        ],
    )
    write_job_execution_report(report, tmp_path / "receipts")

    json_path, markdown_path = write_job_execution_delivery_summary(report)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["execution_id"] == report.execution_id
    assert payload["summary"]["published_runs"] == 1
    assert payload["content_assets"]["status"] == "generated"
    assert payload["release_evidence"]["status"] == "warn"
    assert "Worker Delivery Summary" in markdown
    assert "Published AI content" in markdown
    assert report.delivery_summary_path == str(json_path)
    assert report.delivery_summary_markdown_path == str(markdown_path)


def test_job_execution_trends_aggregate_receipts(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipts"
    completed_at = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    first = JobExecutionReport(
        name="first",
        total=2,
        succeeded=2,
        failed=0,
        release_evidence_path="release-evidence/first",
        completed_at=completed_at - timedelta(minutes=5),
        results=[
            JobRunResult(
                job_name="published",
                topic="Published",
                publish=True,
                run_id="run-1",
                status="published",
                published_url="https://example.com/one",
            ),
            JobRunResult(
                job_name="handoff",
                topic="Handoff",
                homepage_handoff=True,
                run_id="run-2",
                status="needs_review",
                homepage_handoff_path="handoff.zip",
            ),
        ],
    )
    second = JobExecutionReport(
        name="second",
        total=1,
        succeeded=0,
        failed=1,
        release_evidence_error="release evidence archive failed",
        completed_at=completed_at,
        results=[
            JobRunResult(
                job_name="failed",
                topic="Failed",
                homepage_handoff=True,
                status="failed",
                homepage_handoff_error="missing homepage repo",
                error="provider failed",
            )
        ],
    )
    write_job_execution_report(first, receipt_dir)
    write_job_execution_report(second, receipt_dir)

    report = job_execution_trends(receipt_dir, days=1)

    assert report.summary.execution_count == 2
    assert report.summary.total_jobs == 3
    assert report.summary.succeeded_jobs == 2
    assert report.summary.failed_jobs == 1
    assert report.summary.generated_runs == 2
    assert report.summary.published_runs == 1
    assert report.summary.homepage_handoff_ready == 1
    assert report.summary.homepage_handoff_failed == 1
    assert report.summary.action_required == 1
    assert report.summary.success_rate == pytest.approx(2 / 3)
    assert report.summary.latest_success_at == first.completed_at
    assert report.summary.latest_failure_at == second.completed_at
    assert [reason.reason for reason in report.summary.top_failure_reasons] == [
        "release evidence: release evidence archive failed",
        "failed: provider failed",
        "failed homepage handoff: missing homepage repo",
    ]
    assert "release-evidence" in report.summary.top_failure_reasons[0].remediation_steps[0]
    assert "provider" in report.summary.top_failure_reasons[1].remediation_steps[0]
    assert "HOMEPAGE_REPO_PATH" in report.summary.top_failure_reasons[2].remediation_steps[0]
    assert report.buckets[-1].execution_count == 2
    assert report.buckets[-1].top_failure_reasons[0].latest_execution_id == second.execution_id


def test_job_execution_alert_report_flags_actionable_worker_failures(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipts"
    failed = JobExecutionReport(
        name="alerts",
        total=1,
        succeeded=0,
        failed=1,
        results=[
            JobRunResult(
                job_name="roundup",
                topic="Roundup",
                status="failed",
                error="research provider timeout",
            )
        ],
    )
    write_job_execution_report(failed, receipt_dir)

    report = job_execution_alert_report(receipt_dir, days=1)

    assert report.severity.value == "critical"
    assert report.action_required is True
    assert "research provider timeout" in report.message
    assert report.signals[0].category == "worker_failure"
    assert report.signals[0].remediation_steps
    assert "provider" in report.recommended_actions[2]
    assert "job-recovery-plan" in report.recommended_actions[1]


def test_notify_job_execution_alert_writes_delivery_receipt(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipts"
    failed = JobExecutionReport(
        name="notify-alert",
        total=1,
        succeeded=0,
        failed=1,
        results=[
            JobRunResult(
                job_name="roundup",
                topic="Roundup",
                status="failed",
                error="provider timeout",
            )
        ],
    )
    write_job_execution_report(failed, receipt_dir)

    delivery = notify_job_execution_alert(receipt_dir, days=1)
    deliveries = job_execution_alert_notification_log(receipt_dir)

    assert delivery.status == "skipped"
    assert delivery.provider == "local"
    assert delivery.action_required is True
    assert delivery.severity.value == "critical"
    assert deliveries[0].delivery_id == delivery.delivery_id


def test_notify_worker_delivery_summary_writes_delivery_receipt(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipts"
    report = JobExecutionReport(
        name="summary-notify",
        total=1,
        succeeded=1,
        failed=0,
        results=[
            JobRunResult(
                job_name="daily-ai",
                topic="Daily AI",
                publish=True,
                run_id="run-summary-notify",
                status="published",
                published_url="https://example.com/daily-ai",
            )
        ],
    )
    write_job_execution_report(report, receipt_dir)
    write_job_execution_delivery_summary(report)

    delivery = notify_worker_delivery_summary(report)
    deliveries = worker_delivery_summary_notification_log(receipt_dir)

    assert delivery.status == "skipped"
    assert delivery.provider == "local"
    assert delivery.action_required is False
    assert delivery.summary_path == report.delivery_summary_path
    assert delivery.markdown_path == report.delivery_summary_markdown_path
    assert deliveries[0].delivery_id == delivery.delivery_id


def test_notify_worker_delivery_summary_posts_webhook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_dir = tmp_path / "receipts"
    requests: list[dict[str, Any]] = []

    class Response:
        is_success = True
        status_code = 202
        text = "accepted"

    def fake_post(url: str, *, json: dict[str, object], timeout: float) -> Response:
        requests.append({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("contentops_core.jobs.httpx.post", fake_post)
    report = JobExecutionReport(
        name="summary-webhook",
        total=1,
        succeeded=1,
        failed=0,
        results=[
            JobRunResult(
                job_name="daily-ai",
                topic="Daily AI",
                publish=True,
                run_id="run-summary-webhook",
                status="published",
                published_url="https://example.com/daily-ai",
            )
        ],
    )
    write_job_execution_report(report, receipt_dir)
    write_job_execution_delivery_summary(report)

    delivery = notify_worker_delivery_summary(
        report,
        endpoint="https://hooks.example.com/contentops",
        timeout_seconds=2.5,
    )

    assert delivery.status == "delivered"
    assert delivery.provider == "webhook"
    assert delivery.status_code == 202
    assert requests[0]["url"] == "https://hooks.example.com/contentops"
    assert requests[0]["timeout"] == 2.5
    payload = cast(dict[str, Any], requests[0]["json"])
    assert "worker_delivery_summary" in payload
    assert "markdown" in payload
    assert payload["worker_delivery_summary"]["execution_id"] == report.execution_id


def test_job_execution_alert_report_is_info_when_worker_window_is_clean(tmp_path: Path) -> None:
    report = job_execution_alert_report(tmp_path / "missing", days=1)

    assert report.severity.value == "info"
    assert report.action_required is False
    assert report.signals == []
    assert report.recommended_actions == [
        "Keep the current worker schedule and monitor the next execution."
    ]


def test_job_recovery_plan_rebuilds_failed_jobs(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipts"
    report = JobExecutionReport(
        name="daily-calendar",
        total=2,
        succeeded=1,
        failed=1,
        results=[
            JobRunResult(
                job_name="ok",
                topic="Successful job",
                status="needs_review",
                run_id="run-ok",
            ),
            JobRunResult(
                job_name="failed",
                topic="Failed job",
                source_urls=["https://example.com/source"],
                publish=True,
                homepage_handoff=True,
                tags=["retry"],
                metadata={"owner": "zack"},
                status="failed",
                error="provider timeout",
            ),
        ],
    )
    write_job_execution_report(report, receipt_dir)

    plan = job_recovery_plan(receipt_dir, report.execution_id)
    job_file = plan.to_job_file()

    assert plan.failed_count == 1
    assert plan.runnable is True
    assert plan.source_dry_run is False
    assert plan.blocked_reason is None
    assert job_file.name == "daily-calendar-recovery"
    assert len(job_file.jobs) == 1
    assert job_file.jobs[0].name == "failed"
    assert job_file.jobs[0].source_urls == ["https://example.com/source"]
    assert job_file.jobs[0].publish is True
    assert job_file.jobs[0].homepage_handoff is True
    assert job_file.jobs[0].metadata["recovery_source_execution_id"] == report.execution_id


def test_job_recovery_plan_blocks_dry_run_receipts(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipts"
    job_file = ContentJobFile(
        name="dry-run-calendar",
        jobs=[ContentJob(name="preview", topic="Preview only")],
    )
    report = JobRunner.dry_run_report(job_file)
    write_job_execution_report(report, receipt_dir)

    plan = job_recovery_plan(receipt_dir, report.execution_id)

    assert plan.source_dry_run is True
    assert plan.runnable is False
    assert plan.failed_count == 0
    assert plan.jobs == []
    assert "Dry-run" in (plan.blocked_reason or "")


def test_missing_job_execution_history_is_empty(tmp_path: Path) -> None:
    report_list = list_job_execution_reports(tmp_path / "missing", limit=10)

    assert report_list.total == 0
    assert report_list.items == []


def test_worker_job_catalog_lists_valid_and_invalid_yaml(tmp_path: Path) -> None:
    pipeline_dir = tmp_path / "pipelines"
    pipeline_dir.mkdir()
    (pipeline_dir / "daily.yaml").write_text(
        """
name: daily-calendar
jobs:
  - name: production-llm
    topic: Production LLM systems
    publish: true
    homepage_handoff: true
    tags: [llm, portfolio]
  - name: agent-watch
    topic: Agent workflow reliability
    tags: [agents]
""",
        encoding="utf-8",
    )
    (pipeline_dir / "broken.yaml").write_text("- not-a-mapping\n", encoding="utf-8")

    catalog = list_worker_job_catalog(pipeline_dir)

    assert catalog.total == 2
    assert catalog.job_count == 2
    assert catalog.publish_count == 1
    assert catalog.review_count == 1
    assert catalog.handoff_count == 1
    assert catalog.invalid_count == 1
    daily = next(item for item in catalog.items if item.name == "daily-calendar")
    assert daily.path == "daily.yaml"
    assert daily.topics == ["Production LLM systems", "Agent workflow reliability"]
    assert daily.tags == ["agents", "llm", "portfolio"]
    assert daily.handoff_count == 1
    broken = next(item for item in catalog.items if item.path == "broken.yaml")
    assert broken.valid is False
    assert broken.errors


def test_project_repository_updates_pipeline_targets_github_repos() -> None:
    job_file = load_job_file(Path("pipelines/project_repository_updates.yaml"))

    assert job_file.name == "project-repository-updates"
    assert len(job_file.jobs) >= 4
    assert all(job.publish is False for job in job_file.jobs)
    assert all("github" in job.tags for job in job_file.jobs)
    assert all(job.metadata["research_provider"] == "github" for job in job_file.jobs)
    assert all(job.source_urls for job in job_file.jobs)
    assert all(
        source_url.startswith("https://github.com/zemeng2015/")
        for job in job_file.jobs
        for source_url in job.source_urls
    )
