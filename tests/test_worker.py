from __future__ import annotations

import json
from pathlib import Path
from subprocess import run

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
    receipt = _job_receipt(receipt_dir)
    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["release_evidence_path"] == str(evidence_dir)
    assert receipt_payload["release_evidence_path"] == str(evidence_dir)
    assert payload["release_evidence_status"] in {"pass", "warn", "fail"}
    assert "homepage_handoffs.json" in payload["release_evidence_files"]
    assert (evidence_dir / "summary.json").exists()
    assert (evidence_dir / "evidence_manifest.json").exists()


def test_worker_run_generates_content_distribution_assets_before_release_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_dir = tmp_path / "site"
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(site_dir))
    monkeypatch.setenv("CONTENTOPS_PUBLIC_BASE_URL", "https://example.com")
    monkeypatch.setenv("CONTENTOPS_MIN_PUBLISH_SCORE", "0.1")
    path = tmp_path / "jobs.yaml"
    path.write_text(
        """
name: distribution-job
jobs:
  - name: daily-ai-note
    topic: Worker generated AI distribution assets
    publish: true
""",
        encoding="utf-8",
    )
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
    receipt = _job_receipt(receipt_dir)
    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["content_assets_path"] == str(site_dir)
    assert receipt_payload["content_assets_status"] == "generated"
    assert payload["content_assets_files"] == [
        "feed.xml",
        "sitemap.xml",
        "promotion-brief.md",
        "content-distribution-manifest.json",
    ]
    assert (site_dir / "feed.xml").exists()
    assert (site_dir / "sitemap.xml").exists()
    assert (site_dir / "promotion-brief.md").exists()
    assert (site_dir / "content-distribution-manifest.json").exists()
    content_distribution = json.loads(
        (evidence_dir / "content_distribution.json").read_text(encoding="utf-8")
    )
    assert content_distribution["total"] == 1
    assert content_distribution["items"][0]["manifest_path"] == (
        "content-distribution-manifest.json"
    )
    assert content_distribution["items"][0]["sha256"]
    delivery_summary_path = Path(payload["delivery_summary_path"])
    delivery_summary_markdown_path = Path(payload["delivery_summary_markdown_path"])
    delivery_summary = json.loads(delivery_summary_path.read_text(encoding="utf-8"))
    worker_delivery_summaries = json.loads(
        (evidence_dir / "worker_delivery_summaries.json").read_text(encoding="utf-8")
    )
    notification_log = json.loads(
        (receipt_dir / "worker-delivery-summary-notification-log.json").read_text(
            encoding="utf-8"
        )
    )
    ops_brief_notification_log = json.loads(
        (tmp_path / "artifacts" / "ops-brief-notification-log.json").read_text(
            encoding="utf-8"
        )
    )
    ops_brief_deliveries = json.loads(
        (evidence_dir / "ops_brief_deliveries.json").read_text(encoding="utf-8")
    )
    assert delivery_summary_path.exists()
    assert delivery_summary_markdown_path.exists()
    assert delivery_summary["published_items"][0]["published_url"].startswith(
        "https://example.com"
    )
    assert worker_delivery_summaries["total"] == 1
    assert worker_delivery_summaries["items"][0]["execution_id"] == payload["execution_id"]
    assert notification_log[0]["execution_id"] == payload["execution_id"]
    assert notification_log[0]["status"] == "skipped"
    assert ops_brief_notification_log[0]["status"] == "skipped"
    assert ops_brief_deliveries[0]["delivery_id"] == ops_brief_notification_log[0]["delivery_id"]


def test_worker_run_can_prepare_requested_homepage_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    homepage = tmp_path / "homepage"
    (homepage / "posts").mkdir(parents=True)
    _init_git_repo(homepage)
    (homepage / "index.html").write_text(
        '<html><body><section id="writing"><div class="post-grid"></div></section></body></html>',
        encoding="utf-8",
    )
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    monkeypatch.setenv("CONTENTOPS_PUBLISHER_PROVIDER", "homepage")
    monkeypatch.setenv("CONTENTOPS_HOMEPAGE_REPO_PATH", str(homepage))
    path = tmp_path / "jobs.yaml"
    path.write_text(
        """
name: homepage-calendar
jobs:
  - name: homepage-ready
    topic: Homepage handoff automation
    homepage_handoff: true
""",
        encoding="utf-8",
    )
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
    job_result = payload["results"][0]
    handoff_path = Path(job_result["homepage_handoff_path"])
    handoffs = json.loads((evidence_dir / "homepage_handoffs.json").read_text(encoding="utf-8"))
    assert handoff_path.exists()
    assert handoff_path.name.endswith("-homepage-handoff.zip")
    assert job_result["homepage_handoff_error"] is None
    assert handoffs["total"] == 1
    assert handoffs["items"][0]["run_id"] == job_result["run_id"]


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


def test_worker_run_can_skip_ops_brief_notification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    path = tmp_path / "jobs.yaml"
    path.write_text("name: skip-ops-brief\ntopic: Skip ops brief notification\n", encoding="utf-8")
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
            "--skip-ops-brief-notification",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert not (tmp_path / "artifacts" / "ops-brief-notification-log.json").exists()
    ops_brief_deliveries = json.loads(
        (evidence_dir / "ops_brief_deliveries.json").read_text(encoding="utf-8")
    )
    assert ops_brief_deliveries == []


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


def _init_git_repo(path: Path) -> None:
    run(["git", "init"], cwd=path, check=True, capture_output=True)
    run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def _job_receipt(receipt_dir: Path) -> Path:
    return next(
        path
        for path in receipt_dir.glob("*.json")
        if not path.name.endswith("-delivery-summary.json")
        and path.name
        not in {
            "s3-mirror-log.json",
            "worker-alert-notification-log.json",
            "worker-delivery-summary-notification-log.json",
        }
    )
