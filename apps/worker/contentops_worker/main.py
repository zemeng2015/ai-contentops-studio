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
    notify_worker_delivery_summary,
    rewrite_job_execution_report,
    write_job_execution_delivery_summary,
    write_job_execution_report,
)
from contentops_core.models import ArtifactMirrorRecord
from contentops_core.ops_brief import notify_ops_brief
from contentops_core.release_evidence import build_release_evidence, write_release_evidence
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings
from contentops_publishing.publish_index import write_distribution_assets

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
    skip_homepage_handoff: Annotated[
        bool,
        typer.Option(help="Skip homepage handoff generation for jobs that request it."),
    ] = False,
    skip_content_assets: Annotated[
        bool,
        typer.Option(
            help="Skip post-publish RSS, sitemap, promotion brief, and manifest output."
        ),
    ] = False,
    review_only: Annotated[
        bool,
        typer.Option(
            help=(
                "Execute jobs as review packages even when the YAML declares publish=true. "
                "The original publish intent is preserved in run metadata."
            )
        ),
    ] = False,
    skip_delivery_summary: Annotated[
        bool,
        typer.Option(help="Skip post-run worker delivery summary generation."),
    ] = False,
    skip_delivery_notification: Annotated[
        bool,
        typer.Option(help="Skip post-run worker delivery summary notification."),
    ] = False,
    skip_ops_brief_notification: Annotated[
        bool,
        typer.Option(help="Skip post-run operations brief notification."),
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

    report = JobRunner(build_pipeline(settings)).run(
        job_file,
        receipt_dir=resolved_receipt_dir,
        review_only=review_only,
    )
    handoff_errors: list[str] = []
    if not skip_homepage_handoff:
        handoff_errors = _attach_homepage_handoffs(settings, report)
    if not skip_content_assets:
        try:
            _attach_content_assets(settings, report)
        except Exception as exc:
            report.content_assets_status = "failed"
            report.content_assets_error = str(exc)
            rewrite_job_execution_report(report)
            raise typer.BadParameter(
                f"Failed to generate content distribution assets: {exc}"
            ) from exc
    if not skip_release_evidence:
        try:
            _attach_release_evidence(
                settings,
                report,
                release_evidence_dir,
                write_delivery_summary=not skip_delivery_summary,
                notify_delivery_summary=not skip_delivery_notification,
                notify_operations_brief=not skip_ops_brief_notification,
            )
        except Exception as exc:
            report.release_evidence_status = "failed"
            report.release_evidence_error = str(exc)
            rewrite_job_execution_report(report)
            raise typer.BadParameter(f"Failed to generate release evidence: {exc}") from exc
    elif not skip_delivery_summary:
        _attach_delivery_summary(report)
        if not skip_delivery_notification:
            _notify_delivery_summary(settings, report)
    _mirror_receipt_if_configured(settings, report.receipt_path)
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        if handoff_errors:
            raise typer.Exit(1)
        return
    typer.echo(f"Job file {report.name}: {report.succeeded}/{report.total} succeeded")
    typer.echo(f"Receipt: {report.receipt_path}")
    if report.content_assets_path is not None:
        typer.echo(f"Content assets: {report.content_assets_path}")
    if report.delivery_summary_markdown_path is not None:
        typer.echo(f"Delivery summary: {report.delivery_summary_markdown_path}")
    if report.release_evidence_path is not None:
        typer.echo(f"Release evidence: {report.release_evidence_path}")
    for result in report.results:
        run_label = result.run_id or "no-run"
        typer.echo(f"- {result.job_name}: {run_label} {result.status}")
        if result.homepage_handoff_path:
            typer.echo(f"  homepage handoff: {result.homepage_handoff_path}")
        if result.homepage_handoff_error:
            typer.echo(f"  homepage handoff error: {result.homepage_handoff_error}")
    if handoff_errors:
        raise typer.Exit(1)


def _attach_homepage_handoffs(settings: Settings, report: JobExecutionReport) -> list[str]:
    if not any(result.homepage_handoff for result in report.results):
        return []
    service = build_review_service(settings)
    errors: list[str] = []
    for result in report.results:
        if not result.homepage_handoff:
            continue
        if result.error is not None or result.run_id is None:
            result.homepage_handoff_error = result.error or "Run id is missing."
            errors.append(f"{result.job_name}: {result.homepage_handoff_error}")
            continue
        try:
            result.homepage_handoff_path = str(service.create_homepage_handoff(result.run_id))
            result.homepage_handoff_error = None
        except Exception as exc:
            result.homepage_handoff_error = str(exc)
            errors.append(f"{result.job_name}: {exc}")
    rewrite_job_execution_report(report)
    return errors


def _attach_content_assets(settings: Settings, report: JobExecutionReport) -> None:
    if not any(result.published_url for result in report.results):
        report.content_assets_status = "skipped"
        report.content_assets_error = None
        rewrite_job_execution_report(report)
        return
    target_dir = _publisher_target_dir(settings)
    index_path = target_dir / "contentops-publish-index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"Publish index not found: {index_path}")
    assets = write_distribution_assets(
        index_path,
        target_dir,
        channel_title="AI ContentOps Studio",
        channel_description="Reviewed AI and technical content.",
        channel_url=_publisher_public_url(settings),
    )
    report.content_assets_path = str(target_dir)
    report.content_assets_status = "generated"
    report.content_assets_files = [path.name for path in assets.values()]
    report.content_assets_error = None
    rewrite_job_execution_report(report)


def _attach_release_evidence(
    settings: Settings,
    report: JobExecutionReport,
    release_evidence_dir: Path | None,
    *,
    write_delivery_summary: bool,
    notify_delivery_summary: bool,
    notify_operations_brief: bool,
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
    report.release_evidence_path = str(target_dir)
    report.release_evidence_status = bundle.release_readiness.status
    report.release_evidence_files = bundle.summary.artifact_files
    report.release_evidence_error = None
    rewrite_job_execution_report(report)
    if write_delivery_summary:
        _attach_delivery_summary(report)
        if notify_delivery_summary:
            _notify_delivery_summary(settings, report)
        delivery_summary_paths = (
            [Path(report.delivery_summary_path)] if report.delivery_summary_path else None
        )
    else:
        delivery_summary_paths = None
    if notify_operations_brief:
        _notify_operations_brief(settings)
    if write_delivery_summary or notify_operations_brief:
        bundle = build_release_evidence(
            settings=settings,
            repository=RunRepository(settings.database_url),
            review_service=build_review_service(settings),
            worker_delivery_summary_paths=delivery_summary_paths,
        )
        report.release_evidence_files = bundle.summary.artifact_files
        rewrite_job_execution_report(report)
    write_release_evidence(bundle, target_dir, settings=settings)


def _attach_delivery_summary(report: JobExecutionReport) -> None:
    try:
        write_job_execution_delivery_summary(report)
    except Exception as exc:
        report.delivery_summary_error = str(exc)
        rewrite_job_execution_report(report)
        raise


def _notify_delivery_summary(settings: Settings, report: JobExecutionReport) -> None:
    notify_worker_delivery_summary(
        report,
        endpoint=settings.notification_webhook_url,
        timeout_seconds=settings.notification_timeout_seconds,
    )


def _notify_operations_brief(settings: Settings) -> None:
    notify_ops_brief(
        settings=settings,
        review_service=build_review_service(settings),
        endpoint=settings.notification_webhook_url,
        timeout_seconds=settings.notification_timeout_seconds,
    )


def _publisher_target_dir(settings: Settings) -> Path:
    if settings.publisher_provider == "homepage":
        if settings.homepage_repo_path is None:
            raise typer.BadParameter(
                "CONTENTOPS_HOMEPAGE_REPO_PATH is required for homepage content assets."
            )
        return settings.homepage_repo_path
    return settings.site_output_dir


def _publisher_public_url(settings: Settings) -> str:
    if settings.publisher_provider == "homepage":
        return settings.homepage_public_base_url
    return settings.public_base_url


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
