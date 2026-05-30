from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from contentops_core.diagnostics import system_status
from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.jobs import (
    get_job_execution_report,
    job_execution_dir,
    list_job_execution_reports,
)
from contentops_core.models import RunRequest, RunStatus, SourceAuditReport
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings

app = typer.Typer(help="AI ContentOps Studio command line tools.")


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
        typer.echo(
            f"{report.execution_id}  {report.name:24}  "
            f"{report.succeeded}/{report.total} ok  failed={report.failed}"
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


@app.command()
def manifest(run_id: str) -> None:
    service = build_review_service(Settings())
    try:
        artifact_manifest = service.artifact_manifest(run_id)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(artifact_manifest.model_dump_json(indent=2))


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
) -> None:
    if path.exists():
        raise typer.BadParameter(f"File already exists: {path}")
    path.write_text(
        "\n".join(
            [
                "CONTENTOPS_ARTIFACT_ROOT=artifacts",
                "CONTENTOPS_ARTIFACT_STORE_PROVIDER=local",
                "# CONTENTOPS_ARTIFACT_S3_BUCKET=",
                "CONTENTOPS_ARTIFACT_S3_PREFIX=contentops-artifacts",
                "CONTENTOPS_DATABASE_URL=sqlite:///contentops.db",
                "CONTENTOPS_SITE_OUTPUT_DIR=site",
                "CONTENTOPS_PUBLIC_BASE_URL=http://localhost:8000/site",
                "CONTENTOPS_MIN_PUBLISH_SCORE=0.72",
                "CONTENTOPS_RESEARCH_PROVIDER=discovery",
                (
                    "CONTENTOPS_RESEARCH_FEEDS=https://export.arxiv.org/api/query?"
                    "search_query=cat:cs.AI%20OR%20cat:cs.CL%20OR%20cat:cs.LG"
                    "&start=0&max_results=25&sortBy=submittedDate&sortOrder=descending"
                ),
                "CONTENTOPS_RESEARCH_MAX_SOURCES=6",
                "CONTENTOPS_RESEARCH_RETRY_ATTEMPTS=2",
                "CONTENTOPS_RESEARCH_RETRY_BACKOFF_SECONDS=0.1",
                "CONTENTOPS_RESEARCH_SEARCH_ENDPOINT=https://api.search.brave.com/res/v1/web/search",
                "# CONTENTOPS_RESEARCH_SEARCH_API_KEY=",
                "CONTENTOPS_RESEARCH_SEARCH_ENRICH=true",
                "CONTENTOPS_GENERATOR_PROVIDER=template",
                "CONTENTOPS_PUBLISHER_PROVIDER=static",
                "CONTENTOPS_OPENAI_MODEL=gpt-5-mini",
                "CONTENTOPS_OPENAI_TIMEOUT_SECONDS=60",
                "CONTENTOPS_OPENAI_RETRY_ATTEMPTS=2",
                "CONTENTOPS_OPENAI_RETRY_BACKOFF_SECONDS=0.5",
                "CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true",
                "# CONTENTOPS_OPENAI_API_KEY=",
                "# CONTENTOPS_OPERATOR_API_KEY=",
                "# CONTENTOPS_READ_API_KEY=",
                "CONTENTOPS_REQUIRE_READ_API_KEY=false",
                "# CONTENTOPS_NOTIFICATION_WEBHOOK_URL=",
                "CONTENTOPS_NOTIFICATION_TIMEOUT_SECONDS=5",
                "CONTENTOPS_LATENCY_SLO_MS=120000",
                "CONTENTOPS_MIN_SOURCE_COUNT=1",
                "CONTENTOPS_TOKEN_BUDGET_PER_RUN=12000",
                "# CONTENTOPS_HOMEPAGE_REPO_PATH=C:\\path\\to\\zack-ai-homepage",
                "# CONTENTOPS_HOMEPAGE_PUBLIC_BASE_URL=https://zemeng2015.github.io/zack-ai-homepage",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    typer.echo(f"Created {path}")


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
