from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from contentops_core.factory import build_pipeline
from contentops_core.jobs import JobRunner, load_job_file, write_job_execution_report
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
    receipt_dir: Annotated[
        Path | None,
        typer.Option(
            help="Directory for job execution receipts. Defaults to artifact_root/job-executions."
        ),
    ] = None,
) -> None:
    job_file = load_job_file(path)
    settings = Settings()
    resolved_receipt_dir = receipt_dir or settings.artifact_root / "job-executions"
    if dry_run:
        report = JobRunner.dry_run_report(job_file)
        write_job_execution_report(report, resolved_receipt_dir)
        if json_output:
            typer.echo(report.model_dump_json(indent=2))
            return
        typer.echo(f"Loaded {len(job_file.jobs)} job(s) from {path}")
        typer.echo(f"Receipt: {report.receipt_path}")
        for job in job_file.jobs:
            publish_label = "publish" if job.publish else "review"
            typer.echo(f"- {job.name}: {job.topic} ({publish_label})")
        return

    report = JobRunner(build_pipeline(settings)).run(job_file, receipt_dir=resolved_receipt_dir)
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        return
    typer.echo(f"Job file {report.name}: {report.succeeded}/{report.total} succeeded")
    typer.echo(f"Receipt: {report.receipt_path}")
    for result in report.results:
        run_label = result.run_id or "no-run"
        typer.echo(f"- {result.job_name}: {run_label} {result.status}")
