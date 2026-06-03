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
