from __future__ import annotations

from pathlib import Path

import typer
from contentops_core.factory import build_pipeline
from contentops_core.jobs import JobRunner, load_job_file
from contentops_core.settings import Settings

app = typer.Typer(help="Run scheduled or YAML-defined ContentOps jobs.")


@app.callback()
def main() -> None:
    """Run scheduled or YAML-defined ContentOps jobs."""


@app.command()
def run_pipeline(
    path: Path,
    dry_run: bool = typer.Option(False, help="Validate and print jobs without executing them."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    job_file = load_job_file(path)
    if dry_run:
        if json_output:
            typer.echo(job_file.model_dump_json(indent=2))
            return
        typer.echo(f"Loaded {len(job_file.jobs)} job(s) from {path}")
        for job in job_file.jobs:
            publish_label = "publish" if job.publish else "review"
            typer.echo(f"- {job.name}: {job.topic} ({publish_label})")
        return

    settings = Settings()
    report = JobRunner(build_pipeline(settings)).run(job_file)
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        return
    typer.echo(f"Job file {report.name}: {report.succeeded}/{report.total} succeeded")
    for result in report.results:
        run_label = result.run_id or "no-run"
        typer.echo(f"- {result.job_name}: {run_label} {result.status}")
