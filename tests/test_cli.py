from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from contentops_cli.main import app
from contentops_core.jobs import (
    JobRunner,
    job_execution_dir,
    load_job_file,
    write_job_execution_report,
)
from contentops_core.settings import Settings
from typer.testing import CliRunner


def test_cli_publish_reports_approval_gate_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    runner = CliRunner()

    run_result = runner.invoke(app, ["run", "--topic", "CLI approval gate"])
    run_id = next(
        line.split(":", 1)[1].strip()
        for line in run_result.output.splitlines()
        if line.startswith("Run:")
    )
    publish_result = runner.invoke(app, ["publish", run_id])

    assert run_result.exit_code == 0
    assert publish_result.exit_code != 0
    assert "approved before publishing" in publish_result.output
    assert "Traceback" not in publish_result.output


def test_cli_doctor_reports_system_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    runner = CliRunner()

    result = runner.invoke(app, ["doctor", "--json"])
    manifest_result = runner.invoke(app, ["deployment-manifest"])
    release_result = runner.invoke(app, ["release-readiness", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] in {"ok", "degraded"}
    assert {check["name"] for check in payload["checks"]} >= {
        "database",
        "artifact_store",
        "provider_config",
        "operator_security",
    }
    assert manifest_result.exit_code == 0
    manifest_payload = json.loads(manifest_result.output)
    assert manifest_payload["status"] in {"ok", "degraded"}
    assert manifest_payload["runtime"]["database_engine"] == "sqlite"
    assert "openai_api_key" not in manifest_result.output
    assert release_result.exit_code == 0
    release_payload = json.loads(release_result.output)
    assert release_payload["status"] in {"pass", "warn"}
    assert release_payload["can_release"] is True


def test_cli_approve_then_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    monkeypatch.setenv("CONTENTOPS_PUBLIC_BASE_URL", "https://example.com")
    runner = CliRunner()

    run_result = runner.invoke(app, ["run", "--topic", "CLI approval publish"])
    run_id = next(
        line.split(":", 1)[1].strip()
        for line in run_result.output.splitlines()
        if line.startswith("Run:")
    )
    approve_result = runner.invoke(app, ["approve", run_id, "--reviewer", "zack"])
    publish_result = runner.invoke(app, ["publish", run_id])
    receipt_result = runner.invoke(app, ["publish-receipt", run_id])
    verification_result = runner.invoke(app, ["verify-publish", run_id])
    content_result = runner.invoke(app, ["content", "--json"])
    rollback_result = runner.invoke(app, ["rollback-publish", run_id, "--actor", "zack"])
    audit_result = runner.invoke(app, ["audit-log", run_id])
    audit_events_result = runner.invoke(app, ["audit-events", "--action", "publish", "--json"])
    notifications_result = runner.invoke(app, ["notifications", run_id])

    assert approve_result.exit_code == 0
    assert "Status: approved" in approve_result.output
    assert publish_result.exit_code == 0
    assert "Status: published" in publish_result.output
    assert receipt_result.exit_code == 0
    assert '"provider": "static"' in receipt_result.output
    assert '"reviewer": "zack"' in receipt_result.output
    assert verification_result.exit_code == 0
    assert '"verified": true' in verification_result.output
    assert content_result.exit_code == 0
    assert run_id in content_result.output
    assert '"provider": "static"' in content_result.output
    assert rollback_result.exit_code == 0
    assert '"deleted_files"' in rollback_result.output
    assert audit_result.exit_code == 0
    assert '"action": "approve"' in audit_result.output
    assert '"action": "publish"' in audit_result.output
    assert '"action": "rollback_publish"' in audit_result.output
    assert audit_events_result.exit_code == 0
    audit_events_payload = json.loads(audit_events_result.output)
    assert audit_events_payload["action_counts"]["publish"] == 1
    assert audit_events_payload["items"][0]["run_id"] == run_id
    assert notifications_result.exit_code == 0
    assert '"provider": "local"' in notifications_result.output
    assert '"action": "rollback_publish"' in notifications_result.output


def test_cli_demo_seed_creates_reviewable_dashboard_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    monkeypatch.setenv("CONTENTOPS_PUBLIC_BASE_URL", "https://example.com")
    runner = CliRunner()

    result = runner.invoke(app, ["demo-seed", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [item["status"] for item in payload["runs"]] == [
        "published",
        "approved",
        "needs_review",
    ]
    assert payload["runs"][0]["published_url"] is not None
    assert (tmp_path / "site" / "index.html").exists()


def test_cli_queue_and_manifest_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    runner = CliRunner()

    run_result = runner.invoke(app, ["run", "--topic", "CLI queue searchable"])
    run_id = next(
        line.split(":", 1)[1].strip()
        for line in run_result.output.splitlines()
        if line.startswith("Run:")
    )
    run_artifact_dir = next((tmp_path / "artifacts").glob(f"*-{run_id}"))
    (run_artifact_dir / "s3-mirror-log.json").write_text(
        json.dumps(
            [
                {
                    "run_id": run_id,
                    "artifact_name": "eval-report.json",
                    "provider": "s3",
                    "bucket": "cli-bucket",
                    "key": f"contentops/{run_id}/eval-report.json",
                    "content_type": "application/json",
                    "status": "mirrored",
                }
            ]
        ),
        encoding="utf-8",
    )
    queue_result = runner.invoke(
        app,
        ["queue", "--query", "searchable", "--status", "needs_review", "--json"],
    )
    scorecard_result = runner.invoke(app, ["scorecard", run_id])
    scorecards_result = runner.invoke(app, ["scorecards", "--query", "searchable", "--json"])
    cost_report_result = runner.invoke(app, ["cost-report", run_id])
    cost_reports_result = runner.invoke(app, ["cost-reports", "--query", "searchable", "--json"])
    incident_report_result = runner.invoke(app, ["incident-report", run_id])
    incident_reports_result = runner.invoke(
        app,
        ["incident-reports", "--query", "searchable", "--json"],
    )
    ops_summary_result = runner.invoke(app, ["ops-summary", "--json"])
    release_readiness_result = runner.invoke(app, ["release-readiness", "--json"])
    release_evidence_dir = tmp_path / "release-evidence"
    release_evidence_result = runner.invoke(
        app,
        ["release-evidence", "--output-dir", str(release_evidence_dir)],
    )
    retention_result = runner.invoke(app, ["retention-report", "--days", "3650", "--json"])
    generation_receipt_result = runner.invoke(app, ["generation-receipt", run_id])
    manifest_result = runner.invoke(app, ["manifest", run_id])
    mirror_log_result = runner.invoke(app, ["s3-mirror-log", run_id])
    source_audit_result = runner.invoke(app, ["source-audit", run_id, "--json"])
    bundle_path = tmp_path / "bundle.zip"
    export_result = runner.invoke(app, ["export-run", run_id, "--output", str(bundle_path)])

    assert run_result.exit_code == 0
    assert queue_result.exit_code == 0
    queue_payload = json.loads(queue_result.output)
    assert queue_payload["total"] == 1
    assert queue_payload["items"][0]["id"] == run_id
    assert scorecard_result.exit_code == 0
    scorecard_payload = json.loads(scorecard_result.output)
    assert scorecard_payload["run_id"] == run_id
    assert scorecard_payload["overall_pass"] is True
    assert scorecards_result.exit_code == 0
    scorecards_payload = json.loads(scorecards_result.output)
    assert scorecards_payload["total"] == 1
    assert scorecards_payload["items"][0]["run_id"] == run_id
    assert cost_report_result.exit_code == 0
    cost_report_payload = json.loads(cost_report_result.output)
    assert cost_report_payload["run_id"] == run_id
    assert cost_report_payload["estimated_total_tokens"] > 0
    assert cost_reports_result.exit_code == 0
    cost_reports_payload = json.loads(cost_reports_result.output)
    assert cost_reports_payload["total"] == 1
    assert cost_reports_payload["items"][0]["run_id"] == run_id
    assert incident_report_result.exit_code == 0
    incident_report_payload = json.loads(incident_report_result.output)
    assert incident_report_payload["run_id"] == run_id
    assert incident_reports_result.exit_code == 0
    incident_reports_payload = json.loads(incident_reports_result.output)
    assert incident_reports_payload["total"] == 1
    assert incident_reports_payload["items"][0]["run_id"] == run_id
    assert ops_summary_result.exit_code == 0
    ops_summary_payload = json.loads(ops_summary_result.output)
    assert ops_summary_payload["total_runs"] == 1
    assert ops_summary_payload["review_queue_depth"] == 1
    assert release_readiness_result.exit_code == 0
    release_readiness_payload = json.loads(release_readiness_result.output)
    assert release_readiness_payload["operations"]["total_runs"] == 1
    assert release_evidence_result.exit_code == 0
    release_evidence_payload = json.loads(release_evidence_result.output)
    assert release_evidence_payload["summary"]["can_release"] is True
    assert release_evidence_payload["operations_summary"]["total_runs"] == 1
    assert (release_evidence_dir / "summary.json").exists()
    assert (release_evidence_dir / "evidence_manifest.json").exists()
    assert (release_evidence_dir / "release_readiness.json").exists()
    evidence_manifest = json.loads(
        (release_evidence_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert evidence_manifest["artifacts"]["summary.json"]["media_type"] == "application/json"
    assert retention_result.exit_code == 0
    retention_payload = json.loads(retention_result.output)
    assert retention_payload["total_runs_scanned"] == 1
    assert retention_payload["total_size_bytes"] > 0
    assert generation_receipt_result.exit_code == 0
    generation_receipt_payload = json.loads(generation_receipt_result.output)
    assert generation_receipt_payload["provider"] == "template"
    assert generation_receipt_payload["total_tokens"] > 0
    assert manifest_result.exit_code == 0
    manifest_payload = json.loads(manifest_result.output)
    assert manifest_payload["run_id"] == run_id
    assert manifest_payload["artifacts"]["eval-report.json"]["size_bytes"] > 0
    assert mirror_log_result.exit_code == 0
    mirror_log_payload = json.loads(mirror_log_result.output)
    assert mirror_log_payload[0]["bucket"] == "cli-bucket"
    assert source_audit_result.exit_code == 0
    source_audit_payload = json.loads(source_audit_result.output)
    assert source_audit_payload["source_count"] >= 1
    assert export_result.exit_code == 0
    assert bundle_path.exists()
    with ZipFile(bundle_path) as bundle:
        assert "bundle-manifest.json" in bundle.namelist()
        assert "artifacts/eval-report.json" in bundle.namelist()


def test_cli_job_execution_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    path = tmp_path / "job.yaml"
    path.write_text("name: cli-job-history\ntopic: CLI job history\n", encoding="utf-8")
    report = JobRunner.dry_run_report(load_job_file(path))
    write_job_execution_report(report, job_execution_dir(Settings().artifact_root))
    runner = CliRunner()

    list_result = runner.invoke(app, ["job-executions", "--json"])
    detail_result = runner.invoke(app, ["job-execution", report.execution_id])
    recovery_result = runner.invoke(app, ["job-recovery-plan", report.execution_id])

    assert list_result.exit_code == 0
    list_payload = json.loads(list_result.output)
    assert list_payload["total"] == 1
    assert list_payload["items"][0]["execution_id"] == report.execution_id
    assert detail_result.exit_code == 0
    detail_payload = json.loads(detail_result.output)
    assert detail_payload["name"] == "cli-job-history"
    assert recovery_result.exit_code == 0
    recovery_payload = json.loads(recovery_result.output)
    assert recovery_payload["failed_count"] == 0


def test_cli_worker_jobs_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline_dir = tmp_path / "pipelines"
    pipeline_dir.mkdir()
    (pipeline_dir / "calendar.yaml").write_text(
        """
name: cli-calendar
jobs:
  - name: aws-ai
    topic: AWS AI content operations
    publish: true
    tags: [aws, ai]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONTENTOPS_PIPELINE_DIR", str(pipeline_dir))
    runner = CliRunner()

    result = runner.invoke(app, ["worker-jobs", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total"] == 1
    assert payload["job_count"] == 1
    assert payload["publish_count"] == 1
    assert payload["items"][0]["name"] == "cli-calendar"
    assert payload["items"][0]["jobs"][0]["tags"] == ["aws", "ai"]


def test_cli_approve_many_returns_per_run_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    runner = CliRunner()

    first = runner.invoke(app, ["run", "--topic", "CLI batch first"])
    second = runner.invoke(app, ["run", "--topic", "CLI batch second"])
    first_id = _run_id(first.output)
    second_id = _run_id(second.output)
    approve_result = runner.invoke(
        app,
        ["approve-many", first_id, second_id, "missing-run", "--reviewer", "zack", "--json"],
    )

    assert approve_result.exit_code == 0
    payload = json.loads(approve_result.output)
    assert payload["action"] == "approve"
    assert [item["status"] for item in payload["results"]] == ["ok", "ok", "failed"]
    assert payload["results"][0]["new_status"] == "approved"


def _run_id(output: str) -> str:
    return next(
        line.split(":", 1)[1].strip()
        for line in output.splitlines()
        if line.startswith("Run:")
    )
