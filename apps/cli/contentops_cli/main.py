from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml
from contentops_core.config_audit import config_audit
from contentops_core.config_templates import render_env_template
from contentops_core.diagnostics import (
    deployment_check,
    deployment_manifest,
    release_readiness,
    system_status,
)
from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.jobs import (
    get_job_execution_report,
    job_execution_dir,
    job_execution_summary,
    job_execution_trends,
    job_recovery_plan,
    list_job_execution_reports,
    list_worker_job_catalog,
)
from contentops_core.models import (
    ReleaseApprovalDecision,
    ReleaseApprovalRequest,
    RunRequest,
    RunStatus,
    SourceAuditReport,
)
from contentops_core.release_approvals import approve_release, list_release_approvals
from contentops_core.release_evidence import build_release_evidence, write_release_evidence
from contentops_core.release_gate import (
    list_release_gate_reports,
    release_gate,
    write_release_gate_report,
)
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings

app = typer.Typer(help="AI ContentOps Studio command line tools.")

DEMO_TOPICS = [
    "Production LLM evaluation workflow for enterprise RAG",
    "Agent workflow reliability patterns for applied AI teams",
    "AI engineering observability signals for content operations",
]


@app.command()
def run(
    topic: Annotated[str, typer.Option(help="Research topic or content angle.")],
    publish: Annotated[bool, typer.Option(help="Publish if evaluation passes.")] = False,
    source_url: Annotated[
        list[str] | None, typer.Option(help="Optional source URLs.")
    ] = None,
) -> None:
    settings = Settings()
    pipeline = build_pipeline(settings)
    request = RunRequest(topic=topic, publish=publish, source_urls=source_url or [])
    result = pipeline.run(request)
    typer.echo(f"Run: {result.run.id}")
    typer.echo(f"Status: {result.run.status.value}")
    typer.echo(f"Artifacts: {result.run.artifact_dir}")
    if result.published_url:
        typer.echo(f"Published: {result.published_url}")


@app.command("demo-seed")
def demo_seed(
    topic: Annotated[
        list[str] | None,
        typer.Option("--topic", help="Demo topic to generate. Repeat for multiple runs."),
    ] = None,
    publish_first: Annotated[
        bool,
        typer.Option(help="Approve and publish the first generated demo run."),
    ] = True,
    approve_second: Annotated[
        bool,
        typer.Option(help="Approve the second generated demo run without publishing it."),
    ] = True,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    settings = Settings()
    pipeline = build_pipeline(settings)
    service = build_review_service(settings)
    topics = topic or DEMO_TOPICS
    seeded: list[dict[str, str | None]] = []

    for index, run_topic in enumerate(topics):
        result = pipeline.run(RunRequest(topic=run_topic, publish=False))
        run = result.run
        action = "created"
        error: str | None = None
        try:
            if index == 0 and publish_first:
                run = service.approve(run.id, reviewer="demo", notes="Seeded demo approval")
                run = service.publish(run.id)
                action = "published"
            elif index == 1 and approve_second:
                run = service.approve(run.id, reviewer="demo", notes="Seeded demo approval")
                action = "approved"
        except ValueError as exc:
            error = str(exc)
            action = "created"
        seeded.append(
            {
                "id": run.id,
                "topic": run.topic,
                "status": run.status.value,
                "action": action,
                "published_url": run.published_url,
                "error": error,
            }
        )

    if json_output:
        typer.echo(json.dumps({"runs": seeded}, indent=2))
        return
    typer.echo(f"Seeded {len(seeded)} demo run(s)")
    for item in seeded:
        suffix = f" -> {item['published_url']}" if item["published_url"] else ""
        typer.echo(f"- {item['id']}  {item['status']}  {item['topic']}{suffix}")


@app.command("runs")
def list_runs(
    limit: Annotated[int, typer.Option(help="Number of recent runs to show.")] = 20,
    offset: Annotated[int, typer.Option(help="Number of matching runs to skip.")] = 0,
    status: Annotated[str, typer.Option(help="Optional run status filter.")] = "",
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Search run id, slug, or topic."),
    ] = "",
) -> None:
    repo = RunRepository(Settings().database_url)
    status_filter = _parse_status(status)
    for record in repo.list(limit=limit, offset=offset, status=status_filter, query=query):
        typer.echo(f"{record.id}  {record.status.value:13}  {record.topic}")


@app.command()
def doctor(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    settings = Settings()
    report = system_status(settings, RunRepository(settings.database_url))
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        raise typer.Exit(0 if report.status != "fail" else 1)
    typer.echo(f"Status: {report.status}")
    for check in report.checks:
        typer.echo(f"- {check.name}: {check.status} - {check.message}")
    raise typer.Exit(0 if report.status != "fail" else 1)


@app.command("deployment-manifest")
def show_deployment_manifest() -> None:
    settings = Settings()
    manifest = deployment_manifest(settings, RunRepository(settings.database_url))
    typer.echo(manifest.model_dump_json(indent=2))


@app.command("config-audit")
def show_config_audit(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    report = config_audit(Settings())
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        raise typer.Exit(0 if report.status != "fail" else 1)
    typer.echo(f"Status: {report.status}")
    for item in report.items:
        typer.echo(f"- {item.name}: {item.status} - {item.message}")
    raise typer.Exit(0 if report.status != "fail" else 1)


@app.command("deployment-check")
def show_deployment_check(
    profile: Annotated[
        str,
        typer.Option(help="Environment template profile to include in deployment checks."),
    ] = "production",
    window_size: Annotated[
        int,
        typer.Option(help="Number of recent runs to include in release gates."),
    ] = 100,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    settings = Settings()
    service = build_review_service(settings)
    report = deployment_check(
        settings,
        RunRepository(settings.database_url),
        service.operations_summary(window_size=window_size),
        profile=profile,
    )
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        raise typer.Exit(0 if report.can_deploy else 1)
    typer.echo(f"Status: {report.status}")
    typer.echo(f"Can deploy: {str(report.can_deploy).lower()}")
    for check in report.checks:
        typer.echo(f"- {check.name}: {check.status} - {check.message}")
    raise typer.Exit(0 if report.can_deploy else 1)


@app.command("release-readiness")
def show_release_readiness(
    window_size: Annotated[
        int,
        typer.Option(help="Number of recent runs to include in release gates."),
    ] = 100,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    settings = Settings()
    service = build_review_service(settings)
    report = release_readiness(
        settings,
        RunRepository(settings.database_url),
        service.operations_summary(window_size=window_size),
    )
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        raise typer.Exit(0 if report.can_release else 1)
    typer.echo(f"Status: {report.status}")
    typer.echo(f"Can release: {str(report.can_release).lower()}")
    for check in report.checks:
        typer.echo(f"- {check.name}: {check.status} - {check.message}")
    raise typer.Exit(0 if report.can_release else 1)


@app.command("release-evidence")
def show_release_evidence(
    window_size: Annotated[
        int,
        typer.Option(help="Number of recent runs to include in release gates."),
    ] = 100,
    output_dir: Annotated[
        Path | None,
        typer.Option(help="Optional directory where release evidence JSON files are written."),
    ] = None,
) -> None:
    settings = Settings()
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)
    bundle = build_release_evidence(
        settings=settings,
        repository=repository,
        review_service=service,
        window_size=window_size,
    )
    if output_dir is not None:
        write_release_evidence(bundle, output_dir, settings=settings)
    typer.echo(bundle.model_dump_json(indent=2))
    raise typer.Exit(0 if bundle.release_readiness.can_release else 1)


@app.command("release-approve")
def release_approve(
    decision: Annotated[
        ReleaseApprovalDecision,
        typer.Option(help="Release approval decision."),
    ] = ReleaseApprovalDecision.APPROVED,
    approver: Annotated[str, typer.Option(help="Approver name or automation identity.")] = (
        "operator"
    ),
    notes: Annotated[str, typer.Option(help="Approval notes or rejection reason.")] = "",
    force: Annotated[
        bool,
        typer.Option(help="Allow approval even when release or deployment gates fail."),
    ] = False,
    window_size: Annotated[
        int,
        typer.Option(help="Number of recent runs to include in release gates."),
    ] = 100,
) -> None:
    settings = Settings()
    try:
        record = approve_release(
            settings=settings,
            repository=RunRepository(settings.database_url),
            review_service=build_review_service(settings),
            request=ReleaseApprovalRequest(
                decision=decision,
                approver=approver,
                notes=notes,
                force=force,
                window_size=window_size,
            ),
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(record.model_dump_json(indent=2))


@app.command("release-approvals")
def release_approvals(
    limit: Annotated[int, typer.Option(help="Maximum approvals to show.")] = 20,
    offset: Annotated[int, typer.Option(help="Number of approvals to skip.")] = 0,
) -> None:
    settings = Settings()
    approvals = list_release_approvals(settings.artifact_root, limit=limit, offset=offset)
    typer.echo(approvals.model_dump_json(indent=2))


@app.command("release-gate")
def show_release_gate(
    git_sha: Annotated[
        str | None,
        typer.Option(help="Git SHA that the deployment pipeline is about to release."),
    ] = None,
    window_size: Annotated[
        int,
        typer.Option(help="Number of recent runs to include in release gates."),
    ] = 100,
    require_approval: Annotated[
        bool,
        typer.Option(help="Require an approved release approval record."),
    ] = True,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
    record: Annotated[
        bool,
        typer.Option(help="Persist the release gate report under the artifact root."),
    ] = False,
) -> None:
    settings = Settings()
    report = release_gate(
        settings=settings,
        repository=RunRepository(settings.database_url),
        review_service=build_review_service(settings),
        window_size=window_size,
        git_sha=git_sha,
        require_approval=require_approval,
    )
    if record:
        write_release_gate_report(report, settings.artifact_root)
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        raise typer.Exit(0 if report.can_deploy else 1)
    typer.echo(f"Status: {report.status}")
    typer.echo(f"Can deploy: {str(report.can_deploy).lower()}")
    for check in report.checks:
        typer.echo(f"- {check.name}: {check.status} - {check.message}")
    raise typer.Exit(0 if report.can_deploy else 1)


@app.command("release-gates")
def release_gates(
    limit: Annotated[int, typer.Option(help="Maximum release gate reports to show.")] = 20,
    offset: Annotated[int, typer.Option(help="Number of release gate reports to skip.")] = 0,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    settings = Settings()
    reports = list_release_gate_reports(settings.artifact_root, limit=limit, offset=offset)
    if json_output:
        typer.echo(reports.model_dump_json(indent=2))
        return
    typer.echo(f"Showing {len(reports.items)} of {reports.total} release gate reports")
    for report in reports.items:
        typer.echo(
            f"{report.generated_at.isoformat()}  {report.status:5}  "
            f"can_deploy={str(report.can_deploy).lower()}  git_sha={report.git_sha or 'n/a'}"
        )


@app.command("ops-summary")
def ops_summary(
    window_size: Annotated[
        int,
        typer.Option(help="Number of recent runs to include in quality/cost windows."),
    ] = 100,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    service = build_review_service(Settings())
    summary = service.operations_summary(window_size=window_size)
    if json_output:
        typer.echo(summary.model_dump_json(indent=2))
        return
    typer.echo(f"Total runs: {summary.total_runs}")
    typer.echo(f"Needs review: {summary.review_queue_depth}")
    typer.echo(f"Approved: {summary.approved_ready_count}")
    typer.echo(f"Published: {summary.published_count}")
    typer.echo(f"Failed: {summary.failed_count}")
    typer.echo(f"Incidents requiring action: {summary.action_required_incidents}")
    typer.echo(f"Critical incidents: {summary.critical_incidents}")
    typer.echo(f"Warning incidents: {summary.warning_incidents}")
    typer.echo(f"Quality pass rate: {summary.quality_pass_rate:.0%}")
    typer.echo(f"Budget pass rate: {summary.budget_pass_rate:.0%}")
    typer.echo(f"Estimated window tokens: {summary.estimated_total_tokens}")


@app.command("ops-trends")
def ops_trends(
    days: Annotated[
        int,
        typer.Option(help="Number of recent calendar days to bucket."),
    ] = 14,
    window_size: Annotated[
        int,
        typer.Option(help="Number of recent runs to scan."),
    ] = 500,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    service = build_review_service(Settings())
    report = service.operations_trends(days=days, window_size=window_size)
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        return
    typer.echo(f"Days: {report.days}")
    typer.echo(f"Window size: {report.window_size}")
    for bucket in report.buckets:
        typer.echo(
            f"{bucket.date} runs={bucket.run_count} published={bucket.published_count} "
            f"failed={bucket.failed_count} quality={bucket.quality_pass_rate:.0%} "
            f"budget={bucket.budget_pass_rate:.0%} tokens={bucket.estimated_total_tokens}"
        )


@app.command("queue")
def review_queue(
    limit: Annotated[int, typer.Option(help="Number of queue items to show.")] = 20,
    offset: Annotated[int, typer.Option(help="Number of matching items to skip.")] = 0,
    status: Annotated[
        str,
        typer.Option(help="Run status to inspect. Empty shows all statuses."),
    ] = RunStatus.NEEDS_REVIEW.value,
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Search run id, slug, or topic."),
    ] = "",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    repo = RunRepository(Settings().database_url)
    status_filter = _parse_status(status)
    runs = repo.list(limit=limit, offset=offset, status=status_filter, query=query)
    total = repo.count(status=status_filter, query=query)
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "items": [run.model_dump(mode="json") for run in runs],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                },
                indent=2,
            )
        )
        return
    typer.echo(f"Showing {len(runs)} of {total} matching runs")
    for record in runs:
        typer.echo(f"{record.id}  {record.status.value:13}  {record.topic}")


@app.command("job-executions")
def job_executions(
    limit: Annotated[int, typer.Option(help="Number of recent job executions to show.")] = 20,
    offset: Annotated[int, typer.Option(help="Number of job executions to skip.")] = 0,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    settings = Settings()
    report_list = list_job_execution_reports(
        job_execution_dir(settings.artifact_root),
        limit=limit,
        offset=offset,
    )
    if json_output:
        typer.echo(report_list.model_dump_json(indent=2))
        return
    typer.echo(f"Showing {len(report_list.items)} of {report_list.total} job executions")
    for report in report_list.items:
        summary = job_execution_summary(report)
        typer.echo(
            f"{report.execution_id}  {report.name:24}  "
            f"{report.succeeded}/{report.total} ok  failed={report.failed}  "
            f"runs={summary.generated_runs} published={summary.published_runs} "
            f"action_required={str(summary.action_required).lower()}"
        )


@app.command("worker-jobs")
def worker_jobs(
    pipeline_dir: Annotated[
        Path | None,
        typer.Option(help="Directory or YAML file containing worker job definitions."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    settings = Settings()
    catalog = list_worker_job_catalog(pipeline_dir or settings.pipeline_dir)
    if json_output:
        typer.echo(catalog.model_dump_json(indent=2))
        return
    typer.echo(
        f"Found {catalog.job_count} job(s) in {catalog.total} file(s); "
        f"publish={catalog.publish_count} review={catalog.review_count} "
        f"invalid={catalog.invalid_count}"
    )
    for item in catalog.items:
        status = "valid" if item.valid else "invalid"
        typer.echo(
            f"{item.path}  {item.name:24}  {status:7}  "
            f"jobs={item.total} publish={item.publish_count} review={item.review_count}"
        )


@app.command("job-execution")
def job_execution(execution_id: str) -> None:
    settings = Settings()
    try:
        report = get_job_execution_report(
            job_execution_dir(settings.artifact_root),
            execution_id,
        )
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(report.model_dump_json(indent=2))


@app.command("job-execution-summary")
def job_execution_summary_command(execution_id: str) -> None:
    settings = Settings()
    try:
        report = get_job_execution_report(
            job_execution_dir(settings.artifact_root),
            execution_id,
        )
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(job_execution_summary(report).model_dump_json(indent=2))


@app.command("job-execution-trends")
def job_execution_trends_command(
    days: Annotated[int, typer.Option(help="Number of days to include.")] = 14,
) -> None:
    settings = Settings()
    report = job_execution_trends(job_execution_dir(settings.artifact_root), days=days)
    typer.echo(report.model_dump_json(indent=2))


@app.command("job-recovery-plan")
def job_recovery_plan_command(
    execution_id: str,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional YAML file to write."),
    ] = None,
) -> None:
    settings = Settings()
    try:
        plan = job_recovery_plan(
            job_execution_dir(settings.artifact_root),
            execution_id,
        )
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if output is not None:
        content = yaml.safe_dump(
            plan.to_job_file().model_dump(mode="json"),
            sort_keys=False,
        )
        output.write_text(content, encoding="utf-8")
        typer.echo(f"Wrote recovery plan: {output}")
        return
    typer.echo(plan.model_dump_json(indent=2))


@app.command("content")
def content_catalog(
    limit: Annotated[int, typer.Option(help="Number of published items to show.")] = 20,
    offset: Annotated[int, typer.Option(help="Number of published items to skip.")] = 0,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    service = build_review_service(Settings())
    catalog = service.published_content(limit=limit, offset=offset)
    if json_output:
        typer.echo(catalog.model_dump_json(indent=2))
        return
    typer.echo(f"Showing {len(catalog.items)} of {catalog.total} published content items")
    for item in catalog.items:
        typer.echo(
            f"{item.run_id}  {item.provider:10}  "
            f"{item.groundedness:.2f}/{item.technical_depth:.2f}  {item.title}"
        )


@app.command("scorecards")
def scorecards(
    limit: Annotated[int, typer.Option(help="Number of scorecards to show.")] = 20,
    offset: Annotated[int, typer.Option(help="Number of scorecards to skip.")] = 0,
    status: Annotated[str, typer.Option(help="Optional run status filter.")] = "",
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Search run id, slug, or topic."),
    ] = "",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    service = build_review_service(Settings())
    response = service.scorecards(
        limit=limit,
        offset=offset,
        status=_parse_status(status),
        query=query,
    )
    if json_output:
        typer.echo(response.model_dump_json(indent=2))
        return
    typer.echo(
        f"Showing {len(response.items)} of {response.total} scorecards "
        f"(quality pass rate {response.quality_pass_rate:.0%})"
    )
    for item in response.items:
        duration = "n/a" if item.total_duration_ms is None else f"{item.total_duration_ms}ms"
        typer.echo(
            f"{item.run_id}  {item.status.value:13}  "
            f"overall={str(item.overall_pass).lower():5}  "
            f"sources={item.source_count}  duration={duration}  {item.topic}"
        )


@app.command("scorecard")
def scorecard(run_id: str) -> None:
    service = build_review_service(Settings())
    try:
        item = service.scorecard(run_id)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(item.model_dump_json(indent=2))


@app.command("cost-reports")
def cost_reports(
    limit: Annotated[int, typer.Option(help="Number of cost reports to show.")] = 20,
    offset: Annotated[int, typer.Option(help="Number of cost reports to skip.")] = 0,
    status: Annotated[str, typer.Option(help="Optional run status filter.")] = "",
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Search run id, slug, or topic."),
    ] = "",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    service = build_review_service(Settings())
    response = service.cost_reports(
        limit=limit,
        offset=offset,
        status=_parse_status(status),
        query=query,
    )
    if json_output:
        typer.echo(response.model_dump_json(indent=2))
        return
    typer.echo(
        f"Showing {len(response.items)} of {response.total} cost reports "
        f"(budget pass rate {response.budget_pass_rate:.0%})"
    )
    for item in response.items:
        typer.echo(
            f"{item.run_id}  {item.status.value:13}  "
            f"budget={str(item.budget_pass).lower():5}  "
            f"tokens={item.estimated_total_tokens}/{item.token_budget}  {item.topic}"
        )


@app.command("cost-report")
def cost_report(run_id: str) -> None:
    service = build_review_service(Settings())
    try:
        item = service.cost_report(run_id)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(item.model_dump_json(indent=2))


@app.command("incident-reports")
def incident_reports(
    limit: Annotated[int, typer.Option(help="Number of incident reports to show.")] = 20,
    offset: Annotated[int, typer.Option(help="Number of incident reports to skip.")] = 0,
    status: Annotated[str, typer.Option(help="Optional run status filter.")] = "",
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Search run id, slug, or topic."),
    ] = "",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    service = build_review_service(Settings())
    response = service.incident_reports(
        limit=limit,
        offset=offset,
        status=_parse_status(status),
        query=query,
    )
    if json_output:
        typer.echo(response.model_dump_json(indent=2))
        return
    typer.echo(
        f"Showing {len(response.items)} of {response.total} incident reports "
        f"({response.action_required} require action)"
    )
    for item in response.items:
        typer.echo(
            f"{item.run_id}  {item.status.value:13}  "
            f"{item.severity.value:8}  action={str(item.requires_action).lower():5}  "
            f"{item.topic}"
        )


@app.command("audit-events")
def audit_events(
    limit: Annotated[int, typer.Option(help="Number of audit events to show.")] = 20,
    offset: Annotated[int, typer.Option(help="Number of audit events to skip.")] = 0,
    status: Annotated[str, typer.Option(help="Optional run status filter.")] = "",
    action: Annotated[str, typer.Option(help="Optional audit action filter.")] = "",
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Search run id, slug, or topic."),
    ] = "",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    service = build_review_service(Settings())
    response = service.audit_events(
        limit=limit,
        offset=offset,
        status=_parse_status(status),
        query=query,
        action=action,
    )
    if json_output:
        typer.echo(response.model_dump_json(indent=2))
        return
    typer.echo(f"Showing {len(response.items)} of {response.total} audit events")
    for event in response.items:
        previous = event.previous_status.value if event.previous_status else "n/a"
        new = event.new_status.value if event.new_status else "n/a"
        typer.echo(
            f"{event.occurred_at.isoformat()}  {event.run_id}  "
            f"{event.action:16}  {event.actor:12}  {previous}->{new}"
        )


@app.command("retention-report")
def retention_report(
    days: Annotated[
        int,
        typer.Option(help="Artifact retention window in days."),
    ] = 90,
    limit: Annotated[int, typer.Option(help="Number of recent runs to scan.")] = 100,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    service = build_review_service(Settings())
    report = service.retention_report(retention_days=days, limit=limit)
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        return
    typer.echo(f"Scanned runs: {report.total_runs_scanned}")
    typer.echo(f"Total artifact bytes: {report.total_size_bytes}")
    typer.echo(f"Candidates: {report.candidate_count}")
    typer.echo(f"Candidate bytes: {report.candidate_size_bytes}")
    for item in report.candidates:
        typer.echo(
            f"{item.run_id}  {item.status.value:13}  "
            f"{item.artifact_count:3} files  {item.size_bytes:8} bytes  {item.topic}"
        )


@app.command("incident-report")
def incident_report(run_id: str) -> None:
    service = build_review_service(Settings())
    try:
        report = service.incident_report(run_id)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(report.model_dump_json(indent=2))


@app.command()
def show(
    run_id: str,
    artifact: Annotated[
        str,
        typer.Option(help="Artifact file name to print."),
    ] = "eval-report.json",
) -> None:
    repo = RunRepository(Settings().database_url)
    record = repo.get(run_id)
    if record is None:
        raise typer.BadParameter(f"Run not found: {run_id}")
    path = record.artifact_dir / artifact
    if not path.exists():
        raise typer.BadParameter(f"Artifact not found: {path}")
    if path.suffix == ".json":
        typer.echo(json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2))
    else:
        typer.echo(path.read_text(encoding="utf-8"))


@app.command()
def artifacts(run_id: str) -> None:
    service = build_review_service(Settings())
    for artifact in service.list_artifacts(run_id):
        typer.echo(artifact)


@app.command("export-run")
def export_run(
    run_id: str,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional zip file path."),
    ] = None,
) -> None:
    service = build_review_service(Settings())
    try:
        bundle_path = service.create_bundle(run_id, output_path=output)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Bundle: {bundle_path}")


@app.command("homepage-handoff")
def homepage_handoff(
    run_id: str,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional zip file path."),
    ] = None,
) -> None:
    service = build_review_service(Settings())
    try:
        bundle_path = service.create_homepage_handoff(run_id, output_path=output)
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Homepage handoff: {bundle_path}")


@app.command()
def manifest(run_id: str) -> None:
    service = build_review_service(Settings())
    try:
        artifact_manifest = service.artifact_manifest(run_id)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(artifact_manifest.model_dump_json(indent=2))


@app.command("s3-mirror-log")
def s3_mirror_log(run_id: str) -> None:
    service = build_review_service(Settings())
    try:
        records = service.s3_mirror_log(run_id)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps([record.model_dump(mode="json") for record in records], indent=2))


@app.command()
def publish(
    run_id: str,
    force: Annotated[
        bool,
        typer.Option(help="Publish even if eval report is not ready."),
    ] = False,
) -> None:
    service = build_review_service(Settings())
    try:
        record = service.publish(run_id, force=force)
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Status: {record.status.value}")
    if record.published_url:
        typer.echo(f"Published: {record.published_url}")


@app.command()
def approve(
    run_id: str,
    reviewer: Annotated[str, typer.Option(help="Reviewer name.")] = "operator",
    notes: Annotated[str, typer.Option(help="Approval notes.")] = "",
) -> None:
    service = build_review_service(Settings())
    try:
        record = service.approve(run_id, reviewer=reviewer, notes=notes)
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Status: {record.status.value}")


@app.command("approve-many")
def approve_many(
    run_ids: list[str],
    reviewer: Annotated[str, typer.Option(help="Reviewer name.")] = "operator",
    notes: Annotated[str, typer.Option(help="Approval notes.")] = "",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    service = build_review_service(Settings())
    result = service.approve_many(run_ids, reviewer=reviewer, notes=notes)
    _echo_batch_result(result.model_dump(mode="json"), json_output=json_output)


@app.command()
def reject(
    run_id: str,
    reviewer: Annotated[str, typer.Option(help="Reviewer name.")] = "operator",
    notes: Annotated[str, typer.Option(help="Rejection notes.")] = "",
) -> None:
    service = build_review_service(Settings())
    try:
        record = service.reject(run_id, reviewer=reviewer, notes=notes)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Status: {record.status.value}")


@app.command("reject-many")
def reject_many(
    run_ids: list[str],
    reviewer: Annotated[str, typer.Option(help="Reviewer name.")] = "operator",
    notes: Annotated[str, typer.Option(help="Rejection notes.")] = "",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    service = build_review_service(Settings())
    result = service.reject_many(run_ids, reviewer=reviewer, notes=notes)
    _echo_batch_result(result.model_dump(mode="json"), json_output=json_output)


@app.command()
def approval(run_id: str) -> None:
    service = build_review_service(Settings())
    try:
        decision = service.approval(run_id)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if decision is None:
        typer.echo("No approval decision recorded.")
        return
    typer.echo(decision.model_dump_json(indent=2))


@app.command("publish-receipt")
def publish_receipt(run_id: str) -> None:
    service = build_review_service(Settings())
    try:
        receipt = service.publish_receipt(run_id)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if receipt is None:
        typer.echo("No publish receipt recorded.")
        return
    typer.echo(receipt.model_dump_json(indent=2))


@app.command("verify-publish")
def verify_publish(run_id: str) -> None:
    service = build_review_service(Settings())
    try:
        report = service.verify_publish(run_id)
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(report.model_dump_json(indent=2))


@app.command("generation-receipt")
def generation_receipt(run_id: str) -> None:
    service = build_review_service(Settings())
    try:
        receipt = service.generation_receipt(run_id)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if receipt is None:
        typer.echo("No generation receipt recorded.")
        return
    typer.echo(receipt.model_dump_json(indent=2))


@app.command("rollback-publish")
def rollback_publish(
    run_id: str,
    actor: Annotated[str, typer.Option(help="Operator name for audit log.")] = "operator",
) -> None:
    service = build_review_service(Settings())
    try:
        result = service.rollback_publish(run_id, actor=actor)
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(result.model_dump_json(indent=2))


@app.command("audit-log")
def audit_log(run_id: str) -> None:
    service = build_review_service(Settings())
    try:
        events = service.audit_log(run_id)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps([event.model_dump(mode="json") for event in events], indent=2))


@app.command("notifications")
def notifications(run_id: str) -> None:
    service = build_review_service(Settings())
    try:
        deliveries = service.notification_log(run_id)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        json.dumps([delivery.model_dump(mode="json") for delivery in deliveries], indent=2)
    )


@app.command("publish-plan")
def publish_plan(run_id: str) -> None:
    service = build_review_service(Settings())
    plan = service.publish_plan(run_id)
    typer.echo(plan.model_dump_json(indent=2))


@app.command()
def metrics(run_id: str) -> None:
    service = build_review_service(Settings())
    run_metrics = service.metrics(run_id)
    typer.echo(run_metrics.model_dump_json(indent=2))


@app.command("source-audit")
def source_audit(
    run_id: str,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON."),
    ] = False,
) -> None:
    service = build_review_service(Settings())
    try:
        report = SourceAuditReport.model_validate_json(
            service.read_artifact(run_id, "source-audit.json")
        )
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        return
    typer.echo(f"Sources: {report.source_count}")
    typer.echo(f"Average score: {report.average_score:.2f}")
    typer.echo(
        f"Strong: {report.strong_count}  "
        f"Review: {report.review_count}  "
        f"Failed: {report.failed_count}"
    )
    for assessment in report.assessments:
        typer.echo(
            f"- {assessment.grade:6} {assessment.score:.2f} "
            f"{assessment.source_title}: {assessment.recommendation}"
        )


@app.command()
def compare(base_run_id: str, candidate_run_id: str) -> None:
    service = build_review_service(Settings())
    comparison = service.compare(base_run_id, candidate_run_id)
    typer.echo(comparison.model_dump_json(indent=2))


@app.command()
def rerun(
    run_id: str,
    publish: Annotated[
        bool | None,
        typer.Option(help="Override publish flag for the new run."),
    ] = None,
) -> None:
    settings = Settings()
    service = build_review_service(settings)
    request = service.request(run_id)
    if publish is not None:
        request.publish = publish
    result = build_pipeline(settings).run(request)
    typer.echo(f"Run: {result.run.id}")
    typer.echo(f"Status: {result.run.status.value}")
    typer.echo(f"Artifacts: {result.run.artifact_dir}")


@app.command()
def init_config(
    path: Annotated[Path, typer.Option(help="Config file to create.")] = Path(".env"),
    profile: Annotated[
        str,
        typer.Option(help="Config template profile to render."),
    ] = "local",
) -> None:
    if path.exists():
        raise typer.BadParameter(f"File already exists: {path}")
    try:
        template = render_env_template(profile)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    path.write_text(template, encoding="utf-8")
    typer.echo(f"Created {path} from {profile} profile")


def _parse_status(status: str) -> RunStatus | None:
    normalized = status.strip().casefold()
    if not normalized:
        return None
    try:
        return RunStatus(normalized)
    except ValueError as exc:
        raise typer.BadParameter(f"Unknown run status: {status}") from exc


def _echo_batch_result(payload: dict[str, object], json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    results = payload.get("results", [])
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict):
                label = item.get("new_status") or item.get("error") or item.get("status")
                typer.echo(f"{item.get('run_id')}: {label}")
