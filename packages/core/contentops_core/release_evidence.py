from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from contentops_core.artifacts import (
    failed_s3_mirror_records,
    mirror_files_to_s3,
    write_s3_mirror_log,
)
from contentops_core.diagnostics import (
    deployment_check,
    deployment_manifest,
    integration_smoke_plan,
    provider_health,
    release_readiness,
    system_status,
)
from contentops_core.jobs import (
    job_execution_alert_notification_log,
    job_execution_alert_report,
    job_execution_dir,
    job_execution_trends,
    list_scheduled_workflow_review_packages,
    worker_delivery_summary_notification_log,
)
from contentops_core.models import (
    ArtifactManifest,
    ArtifactMetadata,
    ContentDistributionEvidence,
    ContentDistributionEvidenceItem,
    HomepageHandoffEvidence,
    HomepageHandoffEvidenceItem,
    PublishRecoveryExecutionEvidence,
    PublishRecoveryExecutionEvidenceItem,
    PublishVerificationEvidence,
    PublishVerificationEvidenceItem,
    ReleaseEvidenceBundle,
    ReleaseEvidenceSummary,
    RetentionArchiveEvidence,
    RunStatus,
    ScheduledReviewPackageEvidence,
    ScheduledReviewPackageEvidenceItem,
    SourceReviewDecision,
    SourceReviewEvidence,
    SourceReviewEvidenceItem,
    SourceReviewRecord,
    WorkerDeliverySummaryEvidence,
    WorkerDeliverySummaryEvidenceItem,
)
from contentops_core.operations_console import build_operations_console
from contentops_core.ops_brief import build_ops_brief, ops_brief_notification_log
from contentops_core.repository import RunRepository
from contentops_core.review import ReviewService
from contentops_core.settings import Settings


def build_release_evidence(
    *,
    settings: Settings,
    repository: RunRepository,
    review_service: ReviewService,
    window_size: int = 100,
    git_sha: str | None = None,
    worker_delivery_summary_paths: list[Path] | None = None,
) -> ReleaseEvidenceBundle:
    doctor = system_status(settings, repository)
    providers = provider_health(settings)
    smoke_plan = integration_smoke_plan(settings)
    manifest = deployment_manifest(settings, repository)
    operations = review_service.operations_summary(window_size=window_size)
    operations_console = build_operations_console(
        settings=settings,
        repository=repository,
        review_service=review_service,
        window_size=window_size,
        include_release_gate=False,
    )
    ops_brief = build_ops_brief(
        settings=settings,
        review_service=review_service,
        window_size=window_size,
    )
    readiness = release_readiness(settings, repository, operations)
    preflight = deployment_check(settings, repository, operations)
    approval = _latest_release_approval(settings.artifact_root)
    homepage_handoffs = _homepage_handoff_evidence(settings.artifact_root)
    content_distribution = _content_distribution_evidence(settings)
    publish_verifications = _publish_verification_evidence(repository, review_service)
    publish_recovery_executions = _publish_recovery_execution_evidence(settings.artifact_root)
    worker_delivery_summaries = _worker_delivery_summary_evidence(
        settings.artifact_root,
        extra_paths=worker_delivery_summary_paths,
    )
    retention_archives = _retention_archive_evidence(review_service)
    scheduled_review_packages = _scheduled_review_package_evidence(settings.artifact_root)
    source_reviews = _source_review_evidence(settings.artifact_root)
    has_publish_drift = (
        publish_verifications.drift_count > 0
        or publish_verifications.missing_receipt_count > 0
    )
    release_status = (
        "fail"
        if source_reviews.needs_review_count or has_publish_drift
        else readiness.status
    )
    can_release = (
        readiness.can_release
        and source_reviews.needs_review_count == 0
        and not has_publish_drift
    )
    worker_execution_trends = job_execution_trends(
        job_execution_dir(settings.artifact_root),
        days=14,
    )
    worker_execution_alerts = job_execution_alert_report(
        job_execution_dir(settings.artifact_root),
        days=14,
    )
    worker_alert_deliveries = job_execution_alert_notification_log(
        job_execution_dir(settings.artifact_root)
    )
    worker_summary_deliveries = worker_delivery_summary_notification_log(
        job_execution_dir(settings.artifact_root)
    )
    ops_brief_deliveries = ops_brief_notification_log(settings.artifact_root)
    artifact_files = [
        "doctor.json",
        "deployment_check.json",
        "deployment_manifest.json",
        "content_distribution.json",
        "evidence_manifest.json",
        "homepage_handoffs.json",
        "operations_summary.json",
        "operations_console.json",
        "ops_brief.json",
        "ops_brief_deliveries.json",
        "provider_health.json",
        "integration_smoke_plan.json",
        "publish_recovery_executions.json",
        "publish_verifications.json",
        "release_readiness.json",
        "retention_archives.json",
        "source_reviews.json",
        "scheduled_review_packages.json",
        "summary.json",
        "worker_execution_alert_deliveries.json",
        "worker_execution_alerts.json",
        "worker_execution_trends.json",
        "worker_delivery_summary_deliveries.json",
        "worker_delivery_summaries.json",
    ]
    if approval is not None:
        artifact_files.append("release_approval.json")
    summary = ReleaseEvidenceSummary(
        git_sha=git_sha or os.getenv("GITHUB_SHA") or os.getenv("CONTENTOPS_GIT_SHA"),
        doctor_status=doctor.status,
        release_status=release_status,
        can_release=can_release,
        artifact_files=artifact_files,
    )
    return ReleaseEvidenceBundle(
        summary=summary,
        doctor=doctor,
        provider_health=providers,
        integration_smoke_plan=smoke_plan,
        operations_console=operations_console,
        ops_brief=ops_brief,
        ops_brief_deliveries=ops_brief_deliveries,
        deployment_manifest=manifest,
        operations_summary=operations,
        release_readiness=readiness,
        deployment_check=preflight,
        homepage_handoffs=homepage_handoffs,
        content_distribution=content_distribution,
        publish_verifications=publish_verifications,
        publish_recovery_executions=publish_recovery_executions,
        source_reviews=source_reviews,
        worker_delivery_summaries=worker_delivery_summaries,
        retention_archives=retention_archives,
        scheduled_review_packages=scheduled_review_packages,
        worker_execution_alerts=worker_execution_alerts.model_dump(mode="json"),
        worker_execution_alert_deliveries=[
            delivery.model_dump(mode="json") for delivery in worker_alert_deliveries
        ],
        worker_delivery_summary_deliveries=[
            delivery.model_dump(mode="json") for delivery in worker_summary_deliveries
        ],
        worker_execution_trends=worker_execution_trends.model_dump(mode="json"),
        latest_release_approval=approval,
    )


def write_release_evidence(
    bundle: ReleaseEvidenceBundle,
    output_dir: Path,
    settings: Settings | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, Any] = {
        "doctor": bundle.doctor.model_dump(mode="json"),
        "deployment_check": bundle.deployment_check.model_dump(mode="json"),
        "deployment_manifest": bundle.deployment_manifest.model_dump(mode="json"),
        "content_distribution": bundle.content_distribution.model_dump(mode="json"),
        "homepage_handoffs": bundle.homepage_handoffs.model_dump(mode="json"),
        "operations_summary": bundle.operations_summary.model_dump(mode="json"),
        "operations_console": bundle.operations_console.model_dump(mode="json"),
        "ops_brief": bundle.ops_brief.model_dump(mode="json"),
        "ops_brief_deliveries": [
            delivery.model_dump(mode="json") for delivery in bundle.ops_brief_deliveries
        ],
        "provider_health": bundle.provider_health.model_dump(mode="json"),
        "integration_smoke_plan": bundle.integration_smoke_plan.model_dump(mode="json"),
        "publish_recovery_executions": bundle.publish_recovery_executions.model_dump(
            mode="json"
        ),
        "publish_verifications": bundle.publish_verifications.model_dump(mode="json"),
        "release_readiness": bundle.release_readiness.model_dump(mode="json"),
        "retention_archives": bundle.retention_archives.model_dump(mode="json"),
        "scheduled_review_packages": bundle.scheduled_review_packages.model_dump(mode="json"),
        "source_reviews": bundle.source_reviews.model_dump(mode="json"),
        "summary": bundle.summary.model_dump(mode="json"),
        "worker_execution_alert_deliveries": bundle.worker_execution_alert_deliveries,
        "worker_execution_alerts": bundle.worker_execution_alerts,
        "worker_execution_trends": bundle.worker_execution_trends,
        "worker_delivery_summary_deliveries": bundle.worker_delivery_summary_deliveries,
        "worker_delivery_summaries": bundle.worker_delivery_summaries.model_dump(mode="json"),
    }
    if bundle.latest_release_approval is not None:
        payloads["release_approval"] = bundle.latest_release_approval.model_dump(mode="json")
    for name, payload in payloads.items():
        (output_dir / f"{name}.json").write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
    evidence_manifest = _evidence_manifest(
        output_dir,
        [f"{name}.json" for name in payloads],
    )
    (output_dir / "evidence_manifest.json").write_text(
        evidence_manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    if settings is not None:
        mirror_release_evidence_to_s3(bundle, output_dir, settings)


def create_release_evidence_archive(
    bundle: ReleaseEvidenceBundle,
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="contentops-release-evidence-") as directory:
        evidence_dir = Path(directory)
        write_release_evidence(bundle, evidence_dir)
        with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(evidence_dir.glob("*.json")):
                archive.write(path, path.name)
    return output_path


def mirror_release_evidence_to_s3(
    bundle: ReleaseEvidenceBundle,
    output_dir: Path,
    settings: Settings,
) -> None:
    if settings.artifact_store_provider != "s3":
        return
    if not settings.artifact_s3_bucket:
        raise ValueError("CONTENTOPS_ARTIFACT_S3_BUCKET is required for S3 evidence mirroring.")
    collection_id = _release_evidence_collection_id(bundle)
    records = mirror_files_to_s3(
        output_dir.glob("*.json"),
        bucket=settings.artifact_s3_bucket,
        prefix=settings.artifact_s3_prefix,
        collection_id=collection_id,
    )
    write_s3_mirror_log(records, output_dir / "s3-mirror-log.json")
    failures = failed_s3_mirror_records(records)
    if failures:
        details = "; ".join(
            f"{record.artifact_name}: {record.error or 'mirror failed'}"
            for record in failures
        )
        raise RuntimeError(f"Failed to mirror release evidence to S3: {details}")


def _release_evidence_collection_id(bundle: ReleaseEvidenceBundle) -> str:
    marker = bundle.summary.git_sha or f"{bundle.summary.generated_at:%Y%m%dT%H%M%SZ}"
    safe_marker = "".join(char if char.isalnum() or char in ".-_" else "-" for char in marker)
    return f"release-evidence/{safe_marker}"


def _latest_release_approval(artifact_root: Path) -> Any | None:
    from contentops_core.release_approvals import latest_release_approval

    return latest_release_approval(artifact_root)


def _homepage_handoff_evidence(artifact_root: Path, limit: int = 50) -> HomepageHandoffEvidence:
    if not artifact_root.exists():
        return HomepageHandoffEvidence(total=0)
    paths = sorted(
        artifact_root.rglob("*-homepage-handoff.zip"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    items = [_homepage_handoff_item(artifact_root, path) for path in paths[:limit]]
    return HomepageHandoffEvidence(total=len(paths), items=items)


def _homepage_handoff_item(
    artifact_root: Path,
    path: Path,
) -> HomepageHandoffEvidenceItem:
    stat = path.stat()
    file_name = path.name
    run_id = file_name.removesuffix("-homepage-handoff.zip")
    try:
        artifact_path = path.relative_to(artifact_root).as_posix()
    except ValueError:
        artifact_path = path.as_posix()
    return HomepageHandoffEvidenceItem(
        run_id=run_id,
        artifact_path=artifact_path,
        size_bytes=stat.st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        updated_at=datetime.fromtimestamp(stat.st_mtime, UTC),
    )


def _content_distribution_evidence(
    settings: Settings,
    limit: int = 20,
) -> ContentDistributionEvidence:
    candidate_roots = [settings.site_output_dir, settings.artifact_root]
    if settings.homepage_repo_path is not None:
        candidate_roots.insert(0, settings.homepage_repo_path)
    paths: list[Path] = []
    seen: set[Path] = set()
    for root in candidate_roots:
        if not root.exists():
            continue
        for path in root.rglob("content-distribution-manifest.json"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(path)
    paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    items = [
        item
        for path in paths[:limit]
        if (item := _content_distribution_item(settings, path)) is not None
    ]
    return ContentDistributionEvidence(total=len(paths), items=items)


def _content_distribution_item(
    settings: Settings,
    path: Path,
) -> ContentDistributionEvidenceItem | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    assets = payload.get("assets")
    git = payload.get("git")
    stat = path.stat()
    return ContentDistributionEvidenceItem(
        manifest_path=_best_relative_path(settings, path),
        output_dir=str(payload.get("output_dir")) if payload.get("output_dir") else None,
        asset_count=len(assets) if isinstance(assets, list) else 0,
        size_bytes=stat.st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        git=git if isinstance(git, dict) else {},
        updated_at=datetime.fromtimestamp(stat.st_mtime, UTC),
    )


def _publish_verification_evidence(
    repository: RunRepository,
    review_service: ReviewService,
    limit: int = 100,
) -> PublishVerificationEvidence:
    total_published = repository.count(status=RunStatus.PUBLISHED)
    runs = repository.list(limit=limit, status=RunStatus.PUBLISHED)
    items: list[PublishVerificationEvidenceItem] = []
    missing_receipt_count = 0
    for run in runs:
        try:
            report = review_service.verify_publish(run.id)
        except ValueError:
            missing_receipt_count += 1
            continue
        mismatch_count = sum(1 for item in report.items if not item.matches_receipt)
        missing_count = sum(1 for item in report.items if not item.exists)
        verification_path = run.artifact_dir / "publish-verification.json"
        items.append(
            PublishVerificationEvidenceItem(
                run_id=run.id,
                url=report.url,
                provider=report.provider,
                verified=report.verified,
                item_count=len(report.items),
                mismatch_count=mismatch_count,
                missing_count=missing_count,
                artifact_path=_best_relative_path_to_root(
                    run.artifact_dir.parent,
                    verification_path,
                ),
                verified_at=report.verified_at,
            )
        )
    return PublishVerificationEvidence(
        total=total_published,
        verified_count=sum(1 for item in items if item.verified),
        drift_count=sum(1 for item in items if not item.verified),
        missing_receipt_count=missing_receipt_count,
        items=items,
    )


def _publish_recovery_execution_evidence(
    artifact_root: Path,
    limit: int = 50,
) -> PublishRecoveryExecutionEvidence:
    if not artifact_root.exists():
        return PublishRecoveryExecutionEvidence(total=0)
    paths = sorted(
        artifact_root.rglob("publish-recovery-execution.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    items = [
        item
        for path in paths[:limit]
        if (item := _publish_recovery_execution_item(artifact_root, path)) is not None
    ]
    return PublishRecoveryExecutionEvidence(
        total=len(paths),
        completed_count=sum(1 for item in items if item.status == "completed"),
        failed_count=sum(1 for item in items if item.status != "completed"),
        error_count=sum(item.error_count for item in items),
        items=items,
    )


def _publish_recovery_execution_item(
    artifact_root: Path,
    path: Path,
) -> PublishRecoveryExecutionEvidenceItem | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    rollback_payload = payload.get("rollback")
    rollback = rollback_payload if isinstance(rollback_payload, dict) else {}
    executed_at = _parse_datetime_field(payload.get("executed_at"), path)
    return PublishRecoveryExecutionEvidenceItem(
        run_id=str(payload.get("run_id", "unknown")),
        action=str(payload.get("action", "unknown")),
        actor=str(payload.get("actor", "unknown")),
        status=str(payload.get("status", "unknown")),
        message=str(payload.get("message", "")),
        restored_files=len(rollback.get("restored_files", [])),
        deleted_files=len(rollback.get("deleted_files", [])),
        skipped_files=len(rollback.get("skipped_files", [])),
        error_count=len(rollback.get("errors", [])),
        artifact_path=_best_relative_path_to_root(artifact_root, path),
        executed_at=executed_at,
    )


def _parse_datetime_field(value: object, fallback_path: Path) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback_path.stat().st_mtime, UTC)


def _worker_delivery_summary_evidence(
    artifact_root: Path,
    limit: int = 50,
    extra_paths: list[Path] | None = None,
) -> WorkerDeliverySummaryEvidence:
    receipt_dir = job_execution_dir(artifact_root)
    paths: list[Path] = []
    seen: set[Path] = set()
    if receipt_dir.exists():
        for path in receipt_dir.glob("*-delivery-summary.json"):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                paths.append(path)
    for path in extra_paths or []:
        if not path.exists():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        paths.append(path)
    paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    items = [
        item
        for path in paths[:limit]
        if (item := _worker_delivery_summary_item(artifact_root, path)) is not None
    ]
    return WorkerDeliverySummaryEvidence(total=len(paths), items=items)


def _retention_archive_evidence(review_service: ReviewService) -> RetentionArchiveEvidence:
    archives = review_service.retention_archives(limit=20)
    return RetentionArchiveEvidence(total=archives.total, items=archives.items)


def _scheduled_review_package_evidence(
    artifact_root: Path,
) -> ScheduledReviewPackageEvidence:
    packages = list_scheduled_workflow_review_packages(artifact_root, limit=50)
    items = [
        ScheduledReviewPackageEvidenceItem(
            id=item.id,
            manifest_path=_best_relative_path_to_root(artifact_root, Path(item.manifest_path)),
            status=item.status,
            action_required=item.action_required,
            artifact_count=item.artifact_count,
            source_execution_ids=item.source_execution_ids,
            verification_status=item.verification_status,
            verification_failed_count=item.verification_failed_count,
            archive_path=(
                _best_relative_path_to_root(artifact_root, Path(item.archive_path))
                if item.archive_path
                else None
            ),
            archive_exists=item.archive_exists,
            archive_size_bytes=item.archive_size_bytes,
            archive_sha256=item.archive_sha256,
            s3_mirror_status=item.s3_mirror_status,
            s3_mirror_log_path=(
                _best_relative_path_to_root(artifact_root, Path(item.s3_mirror_log_path))
                if item.s3_mirror_log_path
                else None
            ),
            s3_mirror_failures=item.s3_mirror_failures,
            updated_at=item.updated_at,
        )
        for item in packages.items
    ]
    return ScheduledReviewPackageEvidence(
        total=packages.total,
        archived_count=sum(1 for item in items if item.archive_exists),
        failed_count=sum(1 for item in items if item.verification_status == "fail"),
        action_required_count=sum(1 for item in items if item.action_required),
        items=items,
    )


def _worker_delivery_summary_item(
    artifact_root: Path,
    path: Path,
) -> WorkerDeliverySummaryEvidenceItem | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    summary = payload.get("summary")
    content_assets = payload.get("content_assets")
    release_evidence = payload.get("release_evidence")
    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(content_assets, dict):
        content_assets = {}
    if not isinstance(release_evidence, dict):
        release_evidence = {}
    stat = path.stat()
    return WorkerDeliverySummaryEvidenceItem(
        execution_id=str(payload.get("execution_id") or path.stem),
        name=str(payload.get("name") or "worker-execution"),
        artifact_path=_best_relative_path_to_root(artifact_root, path),
        markdown_path=_worker_delivery_markdown_path(artifact_root, path),
        published_runs=int(summary.get("published_runs") or 0),
        content_assets_status=_optional_str(content_assets.get("status")),
        release_evidence_status=_optional_str(release_evidence.get("status")),
        action_required=bool(summary.get("action_required")),
        size_bytes=stat.st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        generated_at=_parse_delivery_generated_at(payload.get("generated_at"), stat),
    )


def _worker_delivery_markdown_path(artifact_root: Path, json_path: Path) -> str | None:
    markdown_path = json_path.with_suffix(".md")
    if not markdown_path.exists():
        return None
    return _best_relative_path_to_root(artifact_root, markdown_path)


def _parse_delivery_generated_at(value: object, stat: os.stat_result) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    return datetime.fromtimestamp(stat.st_mtime, UTC)


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _source_review_evidence(artifact_root: Path, limit: int = 100) -> SourceReviewEvidence:
    if not artifact_root.exists():
        return SourceReviewEvidence(total_runs=0, total_decisions=0)
    paths = sorted(
        artifact_root.rglob("source-review.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    items = [
        item
        for path in paths[:limit]
        if (item := _source_review_item(artifact_root, path)) is not None
    ]
    return SourceReviewEvidence(
        total_runs=len(paths),
        total_decisions=sum(item.total for item in items),
        include_count=sum(item.include_count for item in items),
        exclude_count=sum(item.exclude_count for item in items),
        needs_review_count=sum(item.needs_review_count for item in items),
        items=items,
    )


def _source_review_item(
    artifact_root: Path,
    path: Path,
) -> SourceReviewEvidenceItem | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return None
    records = [SourceReviewRecord.model_validate(item) for item in data if isinstance(item, dict)]
    try:
        artifact_path = path.relative_to(artifact_root).as_posix()
    except ValueError:
        artifact_path = path.as_posix()
    return SourceReviewEvidenceItem(
        run_id=_run_id_from_artifact_dir(path.parent),
        artifact_path=artifact_path,
        total=len(records),
        include_count=sum(
            1 for record in records if record.decision == SourceReviewDecision.INCLUDE
        ),
        exclude_count=sum(
            1 for record in records if record.decision == SourceReviewDecision.EXCLUDE
        ),
        needs_review_count=sum(
            1 for record in records if record.decision == SourceReviewDecision.NEEDS_REVIEW
        ),
        latest_reviewed_at=max((record.decided_at for record in records), default=None),
    )


def _run_id_from_artifact_dir(path: Path) -> str:
    name = path.name
    if "-" not in name:
        return name
    return name.rsplit("-", 1)[-1]


def _best_relative_path(settings: Settings, path: Path) -> str:
    for root in [
        settings.homepage_repo_path,
        settings.site_output_dir,
        settings.artifact_root,
    ]:
        if root is None:
            continue
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def _best_relative_path_to_root(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _evidence_manifest(output_dir: Path, artifact_files: list[str]) -> ArtifactManifest:
    artifacts = {
        file_name: _artifact_metadata(output_dir / file_name)
        for file_name in sorted(artifact_files)
    }
    return ArtifactManifest(
        run_id="release-evidence",
        artifacts=artifacts,
        metadata={
            "bundle_type": "release_evidence",
            "manifest_file": "evidence_manifest.json",
            "hash_algorithm": "sha256",
        },
    )


def _artifact_metadata(path: Path) -> ArtifactMetadata:
    stat = path.stat()
    return ArtifactMetadata(
        name=path.name,
        size_bytes=stat.st_size,
        media_type="application/json",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        updated_at=datetime.fromtimestamp(stat.st_mtime, UTC),
    )
