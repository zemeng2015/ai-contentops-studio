from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from contentops_core.factory import build_review_service
from contentops_core.models import ReleaseApprovalDecision, ReleaseApprovalRequest
from contentops_core.release_approvals import approve_release
from contentops_core.release_evidence import create_release_evidence_archive
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings

from scripts.generate_release_evidence import generate_release_evidence


def test_generate_release_evidence_writes_operational_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setenv("CONTENTOPS_GIT_SHA", "test-sha")
    output_dir = tmp_path / "release-evidence"

    bundle = generate_release_evidence(output_dir)

    expected_files = {
        "doctor.json",
        "deployment_check.json",
        "deployment_manifest.json",
        "evidence_manifest.json",
        "operations_summary.json",
        "release_readiness.json",
        "summary.json",
    }
    assert {path.name for path in output_dir.glob("*.json")} == expected_files
    assert bundle.summary.git_sha == "test-sha"
    assert bundle.summary.release_status in {"pass", "warn", "fail"}
    readiness = json.loads((output_dir / "release_readiness.json").read_text(encoding="utf-8"))
    deployment_check = json.loads(
        (output_dir / "deployment_check.json").read_text(encoding="utf-8")
    )
    manifest = json.loads((output_dir / "deployment_manifest.json").read_text(encoding="utf-8"))
    evidence_manifest = json.loads(
        (output_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert readiness["deployment"]["runtime"]["database_engine"] == "sqlite"
    assert deployment_check["profile"] == "production"
    assert "environment_template" in {check["name"] for check in deployment_check["checks"]}
    assert "checks" in manifest
    assert "operator_api_key" not in json.dumps(manifest).casefold()
    assert set(bundle.summary.artifact_files) == expected_files
    assert evidence_manifest["metadata"]["bundle_type"] == "release_evidence"
    assert set(evidence_manifest["artifacts"]) == expected_files - {"evidence_manifest.json"}
    summary_sha = hashlib.sha256((output_dir / "summary.json").read_bytes()).hexdigest()
    assert evidence_manifest["artifacts"]["summary.json"]["sha256"] == summary_sha


def test_release_evidence_includes_latest_release_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    monkeypatch.setenv("CONTENTOPS_GIT_SHA", "approval-sha")
    settings = Settings()
    repository = RunRepository(settings.database_url)
    output_dir = tmp_path / "release-evidence"

    approval = approve_release(
        settings=settings,
        repository=repository,
        review_service=build_review_service(settings),
        request=ReleaseApprovalRequest(
            decision=ReleaseApprovalDecision.APPROVED,
            approver="zack",
            notes="Evidence reviewed.",
        ),
    )
    bundle = generate_release_evidence(output_dir)

    approval_payload = json.loads(
        (output_dir / "release_approval.json").read_text(encoding="utf-8")
    )
    evidence_manifest = json.loads(
        (output_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )

    assert bundle.latest_release_approval is not None
    assert bundle.latest_release_approval.approval_id == approval.approval_id
    assert "release_approval.json" in bundle.summary.artifact_files
    assert approval_payload["approval_id"] == approval.approval_id
    assert evidence_manifest["artifacts"]["release_approval.json"]["media_type"] == (
        "application/json"
    )


def test_create_release_evidence_archive_writes_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setenv("CONTENTOPS_GIT_SHA", "archive-sha")
    bundle = generate_release_evidence(tmp_path / "release-evidence")
    archive_path = create_release_evidence_archive(bundle, tmp_path / "release-evidence.zip")

    assert archive_path.exists()
    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert names == set(bundle.summary.artifact_files)
        summary = json.loads(archive.read("summary.json"))
        assert summary["git_sha"] == "archive-sha"


def test_generate_release_evidence_mirrors_to_s3_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads: list[dict[str, object]] = []

    class FakeS3Client:
        def upload_file(
            self,
            filename: str,
            bucket: str,
            key: str,
            ExtraArgs: dict[str, str],
        ) -> None:
            uploads.append(
                {
                    "filename": filename,
                    "bucket": bucket,
                    "key": key,
                    "extra_args": ExtraArgs,
                }
            )

    class FakeBoto3:
        @staticmethod
        def client(service: str) -> FakeS3Client:
            assert service == "s3"
            return FakeS3Client()

    monkeypatch.setattr("contentops_core.artifacts.importlib.import_module", lambda name: FakeBoto3)
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_STORE_PROVIDER", "s3")
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_S3_BUCKET", "evidence-bucket")
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_S3_PREFIX", "contentops-prod")
    monkeypatch.setenv("GITHUB_SHA", "release-sha")
    output_dir = tmp_path / "release-evidence"

    generate_release_evidence(output_dir)

    mirror_log = json.loads((output_dir / "s3-mirror-log.json").read_text(encoding="utf-8"))
    assert uploads
    assert {item["bucket"] for item in uploads} == {"evidence-bucket"}
    assert "contentops-prod/release-evidence/release-sha/summary.json" in {
        item["key"] for item in uploads
    }
    assert "contentops-prod/release-evidence/release-sha/deployment_check.json" in {
        item["key"] for item in uploads
    }
    assert mirror_log[0]["provider"] == "s3"
    assert {record["status"] for record in mirror_log} == {"mirrored"}
