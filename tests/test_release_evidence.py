from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

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
    manifest = json.loads((output_dir / "deployment_manifest.json").read_text(encoding="utf-8"))
    evidence_manifest = json.loads(
        (output_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert readiness["deployment"]["runtime"]["database_engine"] == "sqlite"
    assert "checks" in manifest
    assert "operator_api_key" not in json.dumps(manifest).casefold()
    assert set(bundle.summary.artifact_files) == expected_files
    assert evidence_manifest["metadata"]["bundle_type"] == "release_evidence"
    assert set(evidence_manifest["artifacts"]) == expected_files - {"evidence_manifest.json"}
    summary_sha = hashlib.sha256((output_dir / "summary.json").read_bytes()).hexdigest()
    assert evidence_manifest["artifacts"]["summary.json"]["sha256"] == summary_sha


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
    monkeypatch.setenv("CONTENTOPS_GIT_SHA", "release-sha")
    output_dir = tmp_path / "release-evidence"

    generate_release_evidence(output_dir)

    mirror_log = json.loads((output_dir / "s3-mirror-log.json").read_text(encoding="utf-8"))
    assert uploads
    assert {item["bucket"] for item in uploads} == {"evidence-bucket"}
    assert "contentops-prod/release-evidence/release-sha/summary.json" in {
        item["key"] for item in uploads
    }
    assert mirror_log[0]["provider"] == "s3"
    assert {record["status"] for record in mirror_log} == {"mirrored"}
