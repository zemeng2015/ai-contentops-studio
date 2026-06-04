from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from contentops_core.artifacts import (
    failed_s3_mirror_records,
    mirror_files_to_s3,
    write_s3_mirror_log,
)
from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.jobs import (
    JobExecutionReport,
    JobRunner,
    load_job_file,
    rewrite_job_execution_report,
    write_job_execution_report,
)
from contentops_core.models import ArtifactMirrorRecord
from contentops_core.release_evidence import build_release_evidence, write_release_evidence
from contentops_core.repository import RunRepository
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
    release_evidence_dir: Annotated[
        Path | None,
        typer.Option(
            help=(
                "Directory for post-run release evidence. Defaults to "
                "artifact_root/release-evidence/job-executions/<execution_id>."
            )
        ),
    ] = None,
    skip_release_evidence: Annotated[
        bool,
        typer.Option(help="Skip post-run release evidence generation for executed jobs."),
    ] = False,
) -> None:
    job_file = load_job_file(path)
    settings = Settings()
    resolved_receipt_dir = receipt_dir or settings.artifact_root / "job-executions"
    if dry_run:
        report = JobRunner.dry_run_report(job_file)
        write_job_execution_report(report, resolved_receipt_dir)
        _mirror_receipt_if_configured(settings, report.receipt_path)
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
    if not skip_release_evidence:
        try:
            _attach_release_evidence(settings, report, release_evidence_dir)
        except Exception as exc:
            report.release_evidence_status = "failed"
            report.release_evidence_error = str(exc)
            rewrite_job_execution_report(report)
            raise typer.BadParameter(f"Failed to generate release evidence: {exc}") from exc
    _mirror_receipt_if_configured(settings, report.receipt_path)
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        return
    typer.echo(f"Job file {report.name}: {report.succeeded}/{report.total} succeeded")
    typer.echo(f"Receipt: {report.receipt_path}")
    if report.release_evidence_path is not None:
        typer.echo(f"Release evidence: {report.release_evidence_path}")
    for result in report.results:
        run_label = result.run_id or "no-run"
        typer.echo(f"- {result.job_name}: {run_label} {result.status}")


def _attach_release_evidence(
    settings: Settings,
    report: JobExecutionReport,
    release_evidence_dir: Path | None,
) -> None:
    target_dir = (
        release_evidence_dir
        or settings.artifact_root / "release-evidence" / "job-executions" / report.execution_id
    )
    bundle = build_release_evidence(
        settings=settings,
        repository=RunRepository(settings.database_url),
        review_service=build_review_service(settings),
    )
    write_release_evidence(bundle, target_dir, settings=settings)
    report.release_evidence_path = str(target_dir)
    report.release_evidence_status = bundle.release_readiness.status
    report.release_evidence_files = bundle.summary.artifact_files
    report.release_evidence_error = None
    rewrite_job_execution_report(report)


def _mirror_receipt_if_configured(settings: Settings, receipt_path: str | None) -> None:
    if settings.artifact_store_provider != "s3":
        return
    if not settings.artifact_s3_bucket:
        raise typer.BadParameter(
            "CONTENTOPS_ARTIFACT_S3_BUCKET is required for S3 receipt mirroring."
        )
    if receipt_path is None:
        raise typer.BadParameter("Job execution receipt path is missing.")
    path = Path(receipt_path)
    records = mirror_files_to_s3(
        [path],
        bucket=settings.artifact_s3_bucket,
        prefix=settings.artifact_s3_prefix,
        collection_id=f"job-executions/{path.stem}",
    )
    write_s3_mirror_log(records, path.parent / "s3-mirror-log.json")
    failures = failed_s3_mirror_records(records)
    if failures:
        raise typer.BadParameter(_mirror_failure_message(failures))


def _mirror_failure_message(failures: list[ArtifactMirrorRecord]) -> str:
    details = "; ".join(
        f"{record.artifact_name}: {record.error or 'mirror failed'}" for record in failures
    )
    return f"Failed to mirror job execution receipt to S3: {details}"
