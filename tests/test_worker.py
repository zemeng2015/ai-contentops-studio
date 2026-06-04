from __future__ import annotations

import json
from pathlib import Path

import pytest
from contentops_worker.main import app
from typer.testing import CliRunner


def test_worker_dry_run_prints_batch_jobs(tmp_path: Path) -> None:
    path = tmp_path / "jobs.yaml"
    path.write_text(
        """
name: worker-calendar
jobs:
  - name: roundup
    topic: AI platform weekly roundup
  - name: evals
    topic: LLM evaluation checklist
    publish: true
""",
        encoding="utf-8",
    )
    runner = CliRunner()

    receipt_dir = tmp_path / "receipts"

    result = runner.invoke(
        app,
        ["run-pipeline", str(path), "--dry-run", "--receipt-dir", str(receipt_dir)],
    )

    assert result.exit_code == 0
    assert "Loaded 2 job(s)" in result.output
    assert "Receipt:" in result.output
    assert "roundup: AI platform weekly roundup" in result.output
    assert "evals: LLM evaluation checklist" in result.output
    assert len(list(receipt_dir.glob("*.json"))) == 1


def test_worker_dry_run_can_emit_json(tmp_path: Path) -> None:
    path = tmp_path / "jobs.yaml"
    path.write_text("name: one\ntopic: AI systems\n", encoding="utf-8")
    runner = CliRunner()

    receipt_dir = tmp_path / "receipts"

    result = runner.invoke(
        app,
        ["run-pipeline", str(path), "--dry-run", "--json", "--receipt-dir", str(receipt_dir)],
    )

    assert result.exit_code == 0
    assert '"topic": "AI systems"' in result.output
    assert '"dry_run": true' in result.output
    assert len(list(receipt_dir.glob("*.json"))) == 1


def test_worker_run_attaches_release_evidence_to_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    path = tmp_path / "jobs.yaml"
    path.write_text("name: evidence-job\ntopic: Worker evidence automation\n", encoding="utf-8")
    receipt_dir = tmp_path / "receipts"
    evidence_dir = tmp_path / "release-evidence"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run-pipeline",
            str(path),
            "--receipt-dir",
            str(receipt_dir),
            "--release-evidence-dir",
            str(evidence_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    receipt = next(receipt_dir.glob("*.json"))
    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["release_evidence_path"] == str(evidence_dir)
    assert receipt_payload["release_evidence_path"] == str(evidence_dir)
    assert payload["release_evidence_status"] in {"pass", "warn", "fail"}
    assert "homepage_handoffs.json" in payload["release_evidence_files"]
    assert (evidence_dir / "summary.json").exists()
    assert (evidence_dir / "evidence_manifest.json").exists()


def test_worker_run_can_skip_release_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    path = tmp_path / "jobs.yaml"
    path.write_text("name: skip-evidence\ntopic: Skip worker evidence\n", encoding="utf-8")
    receipt_dir = tmp_path / "receipts"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run-pipeline",
            str(path),
            "--receipt-dir",
            str(receipt_dir),
            "--skip-release-evidence",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["release_evidence_path"] is None
    assert payload["release_evidence_files"] == []
    assert not (tmp_path / "artifacts" / "release-evidence").exists()


def test_worker_dry_run_mirrors_receipt_to_s3(
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
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_STORE_PROVIDER", "s3")
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_S3_BUCKET", "receipt-bucket")
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_S3_PREFIX", "contentops-prod")
    path = tmp_path / "jobs.yaml"
    path.write_text("name: mirrored-job\ntopic: AI systems\n", encoding="utf-8")
    receipt_dir = tmp_path / "receipts"
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["run-pipeline", str(path), "--dry-run", "--receipt-dir", str(receipt_dir)],
    )

    assert result.exit_code == 0
    receipt = next(path for path in receipt_dir.glob("*.json") if path.name != "s3-mirror-log.json")
    mirror_log = json.loads((receipt_dir / "s3-mirror-log.json").read_text(encoding="utf-8"))
    assert uploads[0]["bucket"] == "receipt-bucket"
    assert uploads[0]["key"] == f"contentops-prod/job-executions/{receipt.stem}/{receipt.name}"
    assert mirror_log[0]["artifact_name"] == receipt.name
    assert mirror_log[0]["status"] == "mirrored"
