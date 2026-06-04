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
    release_readiness,
    system_status,
)
from contentops_core.models import (
    ArtifactManifest,
    ArtifactMetadata,
    ReleaseEvidenceBundle,
    ReleaseEvidenceSummary,
)
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
) -> ReleaseEvidenceBundle:
    doctor = system_status(settings, repository)
    manifest = deployment_manifest(settings, repository)
    operations = review_service.operations_summary(window_size=window_size)
    readiness = release_readiness(settings, repository, operations)
    preflight = deployment_check(settings, repository, operations)
    summary = ReleaseEvidenceSummary(
        git_sha=git_sha or os.getenv("GITHUB_SHA") or os.getenv("CONTENTOPS_GIT_SHA"),
        doctor_status=doctor.status,
        release_status=readiness.status,
        can_release=readiness.can_release,
        artifact_files=[
            "doctor.json",
            "deployment_check.json",
            "deployment_manifest.json",
            "evidence_manifest.json",
            "operations_summary.json",
            "release_readiness.json",
            "summary.json",
        ],
    )
    return ReleaseEvidenceBundle(
        summary=summary,
        doctor=doctor,
        deployment_manifest=manifest,
        operations_summary=operations,
        release_readiness=readiness,
        deployment_check=preflight,
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
        "operations_summary": bundle.operations_summary.model_dump(mode="json"),
        "release_readiness": bundle.release_readiness.model_dump(mode="json"),
        "summary": bundle.summary.model_dump(mode="json"),
    }
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
