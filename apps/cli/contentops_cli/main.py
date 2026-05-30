from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.models import RunRequest
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
) -> None:
    repo = RunRepository(Settings().database_url)
    for record in repo.list(limit=limit):
        typer.echo(f"{record.id}  {record.status.value:13}  {record.topic}")


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


@app.command()
def publish(
    run_id: str,
    force: Annotated[
        bool,
        typer.Option(help="Publish even if eval report is not ready."),
    ] = False,
) -> None:
    service = build_review_service(Settings())
    record = service.publish(run_id, force=force)
    typer.echo(f"Status: {record.status.value}")
    if record.published_url:
        typer.echo(f"Published: {record.published_url}")


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
                "CONTENTOPS_RESEARCH_PROVIDER=hybrid",
                "CONTENTOPS_GENERATOR_PROVIDER=template",
                "CONTENTOPS_PUBLISHER_PROVIDER=static",
                "CONTENTOPS_OPENAI_MODEL=gpt-5-mini",
                "# CONTENTOPS_OPENAI_API_KEY=",
                "# CONTENTOPS_HOMEPAGE_REPO_PATH=C:\\path\\to\\zack-ai-homepage",
                "# CONTENTOPS_HOMEPAGE_PUBLIC_BASE_URL=https://zemeng2015.github.io/zack-ai-homepage",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    typer.echo(f"Created {path}")
