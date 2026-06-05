from __future__ import annotations

import hashlib
import json
from pathlib import Path
from subprocess import run
from zipfile import ZipFile

import pytest
from contentops_cli.main import app
from contentops_core.diagnostics import integration_smoke_dir, write_integration_smoke_report
from contentops_core.jobs import (
    JobExecutionReport,
    JobRunner,
    JobRunResult,
    job_execution_dir,
    load_job_file,
    write_job_execution_report,
)
from contentops_core.models import (
    ArtifactMirrorRecord,
    IntegrationSmokeRunItem,
    IntegrationSmokeRunReport,
)
from contentops_core.settings import Settings
from typer.testing import CliRunner


def _write_cli_smoke_pass(artifact_root: Path) -> None:
    report = IntegrationSmokeRunReport(
        status="pass",
        integration_enabled=True,
        selected=["feed"],
        items=[
            IntegrationSmokeRunItem(
                name="feed",
                category="research",
                status="pass",
                command="pytest -m integration tests/test_integration_smoke.py -k feed",
                exit_code=0,
            )
        ],
        summary={"pass": 1, "fail": 0, "skip": 0, "planned": 0},
    )
    write_integration_smoke_report(
        report,
        integration_smoke_dir(artifact_root) / "cli-smoke-pass.json",
    )


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
    config_audit_result = runner.invoke(app, ["config-audit", "--json"])
    provider_health_result = runner.invoke(app, ["provider-health", "--json"])
    smoke_plan_result = runner.invoke(app, ["integration-smoke-plan", "--json"])
    smoke_run_output = tmp_path / "smoke-run.json"
    smoke_run_result = runner.invoke(
        app,
        [
            "integration-smoke-run",
            "--selector",
            "openai",
            "--output",
            str(smoke_run_output),
            "--json",
        ],
    )
    smoke_record_result = runner.invoke(
        app,
        [
            "integration-smoke-run",
            "--selector",
            "feed",
            "--dry-run",
            "--record",
            "--json",
        ],
    )
    smoke_history_result = runner.invoke(app, ["integration-smoke-runs", "--json"])
    manifest_result = runner.invoke(app, ["deployment-manifest"])
    deployment_check_result = runner.invoke(app, ["deployment-check", "--json"])
    release_result = runner.invoke(app, ["release-readiness", "--json"])

    assert result.exit_code == 0
    assert config_audit_result.exit_code == 0
    assert provider_health_result.exit_code == 0
    assert smoke_plan_result.exit_code == 0
    assert smoke_run_result.exit_code == 0
    assert smoke_record_result.exit_code == 0
    assert smoke_history_result.exit_code == 0
    assert smoke_run_output.exists()
    payload = json.loads(result.output)
    config_payload = json.loads(config_audit_result.output)
    provider_payload = json.loads(provider_health_result.output)
    smoke_payload = json.loads(smoke_plan_result.output)
    smoke_run_payload = json.loads(smoke_run_result.output)
    smoke_record_payload = json.loads(smoke_record_result.output)
    smoke_history_payload = json.loads(smoke_history_result.output)
    assert config_payload["redacted"] is True
    assert "items" in config_payload
    assert {item["category"] for item in provider_payload["items"]} >= {
        "research",
        "generator",
        "publisher",
    }
    assert smoke_payload["status"] == "warn"
    assert smoke_payload["command"] == "pytest -m integration tests/test_integration_smoke.py"
    assert any(
        item["name"] == "feed" and "CONTENTOPS_RUN_INTEGRATION" in item["missing_env"]
        for item in smoke_payload["items"]
    )
    assert smoke_run_payload["items"][0]["name"] == "openai"
    assert smoke_run_payload["items"][0]["status"] == "skip"
    assert smoke_record_payload["items"][0]["status"] == "planned"
    assert smoke_history_payload["summary"]["total_reports"] == 1
    assert smoke_history_payload["items"][0]["artifact_path"]
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
    assert deployment_check_result.exit_code == 0
    deployment_check_payload = json.loads(deployment_check_result.output)
    assert deployment_check_payload["profile"] == "production"
    assert deployment_check_payload["status"] in {"pass", "warn"}
    assert "environment_template" in {
        item["name"] for item in deployment_check_payload["checks"]
    }
    assert release_result.exit_code == 0
    release_payload = json.loads(release_result.output)
    assert release_payload["status"] in {"pass", "warn"}
    assert release_payload["can_release"] is True


def test_cli_release_approval_records_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    monkeypatch.setenv("CONTENTOPS_GIT_SHA", "cli-release-sha")
    homepage = tmp_path / "homepage"
    homepage.mkdir()
    monkeypatch.setenv("CONTENTOPS_RUN_INTEGRATION", "1")
    monkeypatch.setenv("CONTENTOPS_OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("CONTENTOPS_RESEARCH_SEARCH_API_KEY", "test-search")
    monkeypatch.setenv("CONTENTOPS_HOMEPAGE_REPO_PATH", str(homepage))
    _write_cli_smoke_pass(tmp_path / "artifacts")
    runner = CliRunner()

    approval_result = runner.invoke(
        app,
        [
            "release-approve",
            "--decision",
            "approved",
            "--approver",
            "zack",
            "--notes",
            "CLI approval record.",
        ],
    )
    list_result = runner.invoke(app, ["release-approvals"])
    evidence_dir = tmp_path / "release-evidence"
    evidence_result = runner.invoke(
        app,
        ["release-evidence", "--output-dir", str(evidence_dir)],
    )

    assert approval_result.exit_code == 0
    approval_payload = json.loads(approval_result.output)
    gate_result = runner.invoke(
        app,
        [
            "release-gate",
            "--git-sha",
            approval_payload["git_sha"],
            "--json",
            "--record",
            "--checklist-output",
            str(tmp_path / "release-gate-checklist.md"),
        ],
    )
    gate_history_result = runner.invoke(app, ["release-gates", "--json"])
    assert approval_payload["decision"] == "approved"
    assert approval_payload["approver"] == "zack"
    assert "deployment_check.json" in approval_payload["evidence_files"]
    assert list_result.exit_code == 0
    list_payload = json.loads(list_result.output)
    assert list_payload["total"] == 1
    assert list_payload["items"][0]["notes"] == "CLI approval record."
    assert evidence_result.exit_code == 0
    evidence_payload = json.loads(evidence_result.output)
    assert evidence_payload["latest_release_approval"]["approval_id"] == (
        approval_payload["approval_id"]
    )
    assert (evidence_dir / "release_approval.json").exists()
    assert gate_result.exit_code == 0
    gate_payload = json.loads(gate_result.output)
    assert gate_payload["can_deploy"] is True
    assert gate_payload["deployment_checklist"]
    assert gate_payload["latest_release_approval"]["approval_id"] == (
        approval_payload["approval_id"]
    )
    assert (tmp_path / "release-gate-checklist.md").exists()
    assert "Release Gate Deployment Checklist" in (
        tmp_path / "release-gate-checklist.md"
    ).read_text(encoding="utf-8")
    assert gate_history_result.exit_code == 0
    gate_history_payload = json.loads(gate_history_result.output)
    assert gate_history_payload["total"] == 1
    assert gate_history_payload["items"][0]["git_sha"] == approval_payload["git_sha"]
    assert gate_history_payload["summary"]["total_reports"] == 1
    assert gate_history_payload["summary"]["pass_count"] == 1


def test_cli_release_gate_prints_remediation_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    runner = CliRunner()

    result = runner.invoke(app, ["release-gate", "--git-sha", "missing-approval-sha"])

    assert result.exit_code != 0
    assert "fix:" in result.output
    assert "Deployment checklist:" in result.output
    assert "release-approve" in result.output
    assert "Traceback" not in result.output


def test_cli_init_config_supports_production_profile(tmp_path: Path) -> None:
    runner = CliRunner()
    path = tmp_path / ".env.production"

    result = runner.invoke(app, ["init-config", "--path", str(path), "--profile", "production"])
    second_result = runner.invoke(
        app,
        ["init-config", "--path", str(path), "--profile", "production"],
    )
    invalid_result = runner.invoke(
        app,
        ["init-config", "--path", str(tmp_path / ".env.bad"), "--profile", "staging"],
    )

    assert result.exit_code == 0
    assert "production profile" in result.output
    content = path.read_text(encoding="utf-8")
    assert "CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3" in content
    assert "CONTENTOPS_DATABASE_URL=postgresql+psycopg://" in content
    assert "CONTENTOPS_OPERATOR_API_KEY=replace-with-long-random-operator-key" in content
    assert second_result.exit_code != 0
    assert "File already exists" in second_result.output
    assert invalid_result.exit_code != 0
    assert "Unknown config profile" in invalid_result.output
    assert "Traceback" not in invalid_result.output


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
    recovery_plan_result = runner.invoke(app, ["publish-recovery-plan", run_id])
    content_result = runner.invoke(app, ["content", "--json"])
    content_assets_dir = tmp_path / "content-assets"
    content_assets_result = runner.invoke(
        app,
        ["content-assets", "--output-dir", str(content_assets_dir), "--title", "Zack AI Notes"],
    )
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
    assert recovery_plan_result.exit_code == 0
    assert '"recommended_action": "none"' in recovery_plan_result.output
    assert content_result.exit_code == 0
    assert run_id in content_result.output
    assert '"provider": "static"' in content_result.output
    assert content_assets_result.exit_code == 0
    assert "feed.xml" in content_assets_result.output
    assert "promotion-brief.md" in content_assets_result.output
    assert "content-distribution-manifest.json" in content_assets_result.output
    assert "Zack AI Notes" in (content_assets_dir / "feed.xml").read_text(encoding="utf-8")
    assert "CLI approval publish" in (content_assets_dir / "promotion-brief.md").read_text(
        encoding="utf-8"
    )
    distribution_manifest = json.loads(
        (content_assets_dir / "content-distribution-manifest.json").read_text(encoding="utf-8")
    )
    assert distribution_manifest["manifest_type"] == "content_distribution"
    assert {asset["relative_path"] for asset in distribution_manifest["assets"]} == {
        "feed.xml",
        "promotion-brief.md",
        "content-distribution-manifest.json",
    }
    assert "git -C" in distribution_manifest["suggested_commands"][0]
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


def test_cli_run_publish_recovery_rolls_back_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    runner = CliRunner()

    run_result = runner.invoke(app, ["run", "--topic", "CLI publish recovery"])
    run_id = next(
        line.split(":", 1)[1].strip()
        for line in run_result.output.splitlines()
        if line.startswith("Run:")
    )
    runner.invoke(app, ["approve", run_id, "--reviewer", "zack"])
    runner.invoke(app, ["publish", run_id])
    target = next((tmp_path / "site").glob("*.html"))
    target.write_text("manual drift", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run-publish-recovery",
            run_id,
            "--action",
            "rollback",
            "--actor",
            "zack",
            "--notes",
            "CLI drift recovery.",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "completed"
    assert payload["action"] == "rollback"
    assert payload["rollback"]["errors"] == []
    assert next(artifact_root.rglob("publish-recovery-execution.json")).exists()


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
    operations_console_result = runner.invoke(app, ["operations-console", "--days", "7", "--json"])
    ops_brief_result = runner.invoke(app, ["ops-brief", "--days", "7", "--json"])
    ops_brief_notify_result = runner.invoke(app, ["ops-brief-notify", "--days", "7"])
    ops_brief_notifications_result = runner.invoke(app, ["ops-brief-notifications"])
    ops_trends_result = runner.invoke(app, ["ops-trends", "--days", "7", "--json"])
    release_readiness_result = runner.invoke(app, ["release-readiness", "--json"])
    release_evidence_dir = tmp_path / "release-evidence"
    release_evidence_result = runner.invoke(
        app,
        ["release-evidence", "--output-dir", str(release_evidence_dir)],
    )
    retention_result = runner.invoke(app, ["retention-report", "--days", "3650", "--json"])
    retention_archive_dir = tmp_path / "retention-archives"
    retention_archive_result = runner.invoke(
        app,
        [
            "retention-archive",
            "--days",
            "0",
            "--output-dir",
            str(retention_archive_dir),
        ],
    )
    retention_archives_result = runner.invoke(app, ["retention-archives"])
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
    assert operations_console_result.exit_code == 0
    operations_console_payload = json.loads(operations_console_result.output)
    assert operations_console_payload["summary"]["status"] in {"pass", "warn", "fail"}
    assert operations_console_payload["summary"]["release_gate_status"] in {
        "pass",
        "warn",
        "fail",
    }
    assert ops_brief_result.exit_code == 0
    ops_brief_payload = json.loads(ops_brief_result.output)
    assert ops_brief_payload["days"] == 7
    assert ops_brief_payload["summary"]["total_runs"] == 1
    assert ops_brief_payload["recommended_actions"]
    assert ops_brief_notify_result.exit_code == 0
    ops_brief_notify_payload = json.loads(ops_brief_notify_result.output)
    assert ops_brief_notify_payload["status"] == "skipped"
    assert ops_brief_notify_payload["brief_status"] in {"pass", "warn", "fail"}
    assert ops_brief_notifications_result.exit_code == 0
    ops_brief_notifications_payload = json.loads(ops_brief_notifications_result.output)
    assert ops_brief_notifications_payload[0]["delivery_id"] == (
        ops_brief_notify_payload["delivery_id"]
    )
    assert ops_trends_result.exit_code == 0
    ops_trends_payload = json.loads(ops_trends_result.output)
    assert ops_trends_payload["days"] == 7
    assert ops_trends_payload["summary"]["total_runs"] == 1
    assert any(bucket["run_count"] == 1 for bucket in ops_trends_payload["buckets"])
    assert release_readiness_result.exit_code == 0
    release_readiness_payload = json.loads(release_readiness_result.output)
    assert release_readiness_payload["operations"]["total_runs"] == 1
    assert release_evidence_result.exit_code == 0
    release_evidence_payload = json.loads(release_evidence_result.output)
    assert release_evidence_payload["summary"]["can_release"] is True
    assert release_evidence_payload["operations_console"]["summary"]["release_gate_status"] == (
        "not_evaluated"
    )
    assert release_evidence_payload["operations_summary"]["total_runs"] == 1
    assert release_evidence_payload["ops_brief"]["summary"]["total_runs"] == 1
    assert release_evidence_payload["ops_brief_deliveries"]
    assert "retention_archives" in release_evidence_payload
    assert release_evidence_payload["deployment_check"]["profile"] == "production"
    assert release_evidence_payload["content_distribution"]["total"] >= 0
    assert release_evidence_payload["publish_recovery_executions"]["total"] >= 0
    assert release_evidence_payload["publish_verifications"]["total"] >= 0
    assert release_evidence_payload["homepage_handoffs"]["total"] == 0
    assert release_evidence_payload["source_reviews"]["total_decisions"] == 0
    assert release_evidence_payload["worker_execution_trends"]["summary"]["execution_count"] >= 0
    assert (release_evidence_dir / "summary.json").exists()
    assert (release_evidence_dir / "content_distribution.json").exists()
    assert (release_evidence_dir / "operations_console.json").exists()
    assert (release_evidence_dir / "publish_recovery_executions.json").exists()
    assert (release_evidence_dir / "publish_verifications.json").exists()
    assert (release_evidence_dir / "deployment_check.json").exists()
    assert (release_evidence_dir / "homepage_handoffs.json").exists()
    assert (release_evidence_dir / "source_reviews.json").exists()
    assert (release_evidence_dir / "worker_execution_trends.json").exists()
    assert (release_evidence_dir / "ops_brief.json").exists()
    assert (release_evidence_dir / "ops_brief_deliveries.json").exists()
    assert (release_evidence_dir / "retention_archives.json").exists()
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
    assert retention_archive_result.exit_code == 0
    retention_archive_payload = json.loads(retention_archive_result.output)
    assert retention_archive_payload["candidate_count"] == 1
    assert retention_archive_payload["run_ids"] == [run_id]
    assert Path(retention_archive_payload["archive_path"]).exists()
    assert retention_archives_result.exit_code == 0
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


def test_retention_archive_mirrors_to_s3_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    runner = CliRunner()

    run_result = runner.invoke(app, ["run", "--topic", "Retention archive mirror"])
    archive_dir = tmp_path / "retention-archives"
    mirrored_names: list[str] = []

    def fake_mirror_files_to_s3(
        paths: list[Path],
        *,
        bucket: str,
        prefix: str,
        collection_id: str,
    ) -> list[ArtifactMirrorRecord]:
        mirrored_names.extend(path.name for path in paths)
        return [
            ArtifactMirrorRecord(
                run_id=collection_id,
                artifact_name=path.name,
                provider="s3",
                bucket=bucket,
                key=f"{prefix}/{collection_id}/{path.name}",
                content_type="application/octet-stream",
                status="mirrored",
            )
            for path in paths
        ]

    monkeypatch.setattr("contentops_core.review.mirror_files_to_s3", fake_mirror_files_to_s3)
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_STORE_PROVIDER", "s3")
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_S3_BUCKET", "contentops-test-bucket")
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_S3_PREFIX", "contentops-artifacts")

    archive_result = runner.invoke(
        app,
        [
            "retention-archive",
            "--days",
            "0",
            "--output-dir",
            str(archive_dir),
        ],
    )

    assert run_result.exit_code == 0
    assert archive_result.exit_code == 0
    payload = json.loads(archive_result.output)
    assert payload["s3_mirror_status"] == "mirrored"
    assert payload["s3_mirror_failures"] == 0
    assert (archive_dir / "s3-mirror-log.json").exists()
    assert any(name.endswith(".zip") for name in mirrored_names)
    assert any(name.endswith("-retention-archive.json") for name in mirrored_names)


def test_scheduled_review_archive_mirrors_to_s3_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    runner = CliRunner()
    path = tmp_path / "job.yaml"
    path.write_text(
        "name: mirrored-scheduled\ntopic: Mirrored scheduled review\n",
        encoding="utf-8",
    )
    report = JobRunner.dry_run_report(load_job_file(path))
    write_job_execution_report(report, job_execution_dir(Settings().artifact_root))
    manifest_path = tmp_path / "daily-review-manifest.json"
    review_path = tmp_path / "daily-review.md"
    metadata_path = tmp_path / "daily-pr-metadata.json"
    operations_path = tmp_path / "daily-operations-console.json"
    operations_path.write_text("{}", encoding="utf-8")
    runner.invoke(
        app,
        [
            "scheduled-workflow-summary",
            "--output",
            str(review_path),
            "--pr-metadata-output",
            str(metadata_path),
            "--manifest-output",
            str(manifest_path),
            "--operations-console-path",
            str(operations_path),
        ],
    )
    runner.invoke(app, ["scheduled-workflow-verify", str(manifest_path), "--json"])
    verification_path = tmp_path / "daily-review-manifest-verification.json"
    verification_path.write_text(
        runner.invoke(app, ["scheduled-workflow-verify", str(manifest_path), "--json"]).output,
        encoding="utf-8",
    )
    mirrored_names: list[str] = []

    def fake_mirror_files_to_s3(
        paths: list[Path],
        *,
        bucket: str,
        prefix: str,
        collection_id: str,
    ) -> list[ArtifactMirrorRecord]:
        mirrored_names.extend(path.name for path in paths)
        return [
            ArtifactMirrorRecord(
                run_id=collection_id,
                artifact_name=path.name,
                provider="s3",
                bucket=bucket,
                key=f"{prefix}/{collection_id}/{path.name}",
                content_type="application/octet-stream",
                status="mirrored",
            )
            for path in paths
        ]

    monkeypatch.setattr("contentops_core.jobs.mirror_files_to_s3", fake_mirror_files_to_s3)
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_STORE_PROVIDER", "s3")
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_S3_BUCKET", "contentops-test-bucket")
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_S3_PREFIX", "contentops-artifacts")

    archive_result = runner.invoke(
        app,
        [
            "scheduled-workflow-archive",
            str(manifest_path),
            str(tmp_path / "daily-review-package.zip"),
            "--json",
        ],
    )

    assert archive_result.exit_code == 0
    payload = json.loads(archive_result.output)
    assert payload["s3_mirror_status"] == "mirrored"
    assert payload["s3_mirror_failures"] == 0
    assert (tmp_path / "s3-mirror-log.json").exists()
    assert "daily-review-manifest.json" in mirrored_names
    assert "daily-review-manifest-verification.json" in mirrored_names
    assert "daily-review-package.json" in mirrored_names
    assert "daily-review-package.zip" in mirrored_names


def test_cli_source_review_records_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_STATIC_SITE_DIR", str(tmp_path / "site"))

    runner = CliRunner()
    run_result = runner.invoke(app, ["run", "--topic", "CLI source review workflow"])
    run_id = _run_id(run_result.output)
    review_result = runner.invoke(
        app,
        [
            "source-review",
            run_id,
            "--source-key",
            "AI engineering pattern library",
            "--decision",
            "include",
            "--reviewer",
            "zack",
            "--notes",
            "Keep this source.",
        ],
    )
    reviews_result = runner.invoke(app, ["source-reviews", run_id])

    assert review_result.exit_code == 0
    assert '"decision": "include"' in review_result.output
    assert reviews_result.exit_code == 0
    reviews = json.loads(reviews_result.output)
    assert reviews[0]["source_title"] == "AI engineering pattern library"
    assert reviews[0]["notes"] == "Keep this source."


def test_cli_homepage_handoff_exports_zip(
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
    monkeypatch.setenv("CONTENTOPS_PUBLISHER_PROVIDER", "homepage")
    monkeypatch.setenv("CONTENTOPS_HOMEPAGE_REPO_PATH", str(homepage))
    monkeypatch.setenv("CONTENTOPS_HOMEPAGE_PUBLIC_BASE_URL", "https://example.com")
    runner = CliRunner()

    run_result = runner.invoke(app, ["run", "--topic", "CLI homepage handoff"])
    run_id = next(
        line.split(":", 1)[1].strip()
        for line in run_result.output.splitlines()
        if line.startswith("Run:")
    )
    output = tmp_path / "handoff.zip"
    handoff_result = runner.invoke(
        app,
        ["homepage-handoff", run_id, "--output", str(output)],
    )

    assert handoff_result.exit_code == 0
    assert output.exists()
    with ZipFile(output) as bundle:
        assert "handoff-manifest.json" in bundle.namelist()
        assert "publish-plan.json" in bundle.namelist()
        assert "suggested-git-commands.txt" in bundle.namelist()


def test_cli_job_execution_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    path = tmp_path / "job.yaml"
    path.write_text("name: cli-job-history\ntopic: CLI job history\n", encoding="utf-8")
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "feed.xml").write_text("<rss />", encoding="utf-8")
    (site_dir / "promotion-brief.md").write_text("# Promotion", encoding="utf-8")
    (site_dir / "content-distribution-manifest.json").write_text("{}", encoding="utf-8")
    report = JobRunner.dry_run_report(load_job_file(path))
    report.content_assets_path = str(site_dir)
    report.content_assets_status = "generated"
    report.content_assets_files = [
        "feed.xml",
        "promotion-brief.md",
        "content-distribution-manifest.json",
    ]
    write_job_execution_report(report, job_execution_dir(Settings().artifact_root))
    runner = CliRunner()

    list_result = runner.invoke(app, ["job-executions", "--json"])
    text_list_result = runner.invoke(app, ["job-executions"])
    detail_result = runner.invoke(app, ["job-execution", report.execution_id])
    summary_result = runner.invoke(app, ["job-execution-summary", report.execution_id])
    trends_result = runner.invoke(app, ["job-execution-trends", "--days", "1"])
    alerts_result = runner.invoke(app, ["job-execution-alerts", "--days", "1"])
    notify_result = runner.invoke(app, ["job-execution-alert-notify", "--days", "1"])
    notifications_result = runner.invoke(app, ["job-execution-alert-notifications"])
    delivery_notify_result = runner.invoke(
        app,
        ["job-execution-delivery-notify", report.execution_id],
    )
    delivery_notifications_result = runner.invoke(
        app,
        ["job-execution-delivery-notifications"],
    )
    scheduled_summary_result = runner.invoke(app, ["scheduled-workflow-summary", "--json"])
    scheduled_summary_markdown = tmp_path / "scheduled-review.md"
    scheduled_pr_metadata = tmp_path / "scheduled-pr-metadata.json"
    scheduled_review_manifest = tmp_path / "scheduled-review-manifest.json"
    scheduled_operations_console = tmp_path / "scheduled-operations-console.json"
    scheduled_operations_console.write_text("{}", encoding="utf-8")
    scheduled_summary_output_result = runner.invoke(
        app,
        [
            "scheduled-workflow-summary",
            "--output",
            str(scheduled_summary_markdown),
            "--pr-metadata-output",
            str(scheduled_pr_metadata),
            "--manifest-output",
            str(scheduled_review_manifest),
            "--operations-console-path",
            str(scheduled_operations_console),
        ],
    )
    recovery_result = runner.invoke(app, ["job-recovery-plan", report.execution_id])
    recovery_run_result = runner.invoke(app, ["job-recovery-plan", report.execution_id, "--run"])

    assert list_result.exit_code == 0
    list_payload = json.loads(list_result.output)
    assert list_payload["total"] == 1
    assert list_payload["items"][0]["execution_id"] == report.execution_id
    assert text_list_result.exit_code == 0
    assert "action_required=" in text_list_result.output
    assert detail_result.exit_code == 0
    detail_payload = json.loads(detail_result.output)
    assert detail_payload["name"] == "cli-job-history"
    assert summary_result.exit_code == 0
    summary_payload = json.loads(summary_result.output)
    assert summary_payload["total_jobs"] == 1
    assert summary_payload["generated_runs"] == 0
    assert trends_result.exit_code == 0
    trends_payload = json.loads(trends_result.output)
    assert trends_payload["summary"]["execution_count"] == 1
    assert trends_payload["summary"]["latest_failure_at"] is not None
    assert trends_payload["summary"]["top_failure_reasons"] == [
        {
            "category": "dry_run_preview",
            "reason": "dry run: execution did not generate persisted runs",
            "count": 1,
            "latest_execution_id": report.execution_id,
            "latest_at": trends_payload["summary"]["latest_failure_at"],
            "remediation_steps": [
                "Rerun the worker without `--dry-run` when a real execution is intended.",
                "Use dry-run receipts only for schedule validation, not release readiness.",
            ],
        }
    ]
    assert alerts_result.exit_code == 0
    alerts_payload = json.loads(alerts_result.output)
    assert alerts_payload["severity"] == "warning"
    assert alerts_payload["action_required"] is True
    assert alerts_payload["signals"][0]["category"] == "worker_action_required"
    assert alerts_payload["signals"][0]["remediation_steps"]
    assert notify_result.exit_code == 0
    notify_payload = json.loads(notify_result.output)
    assert notify_payload["status"] == "skipped"
    assert notify_payload["action_required"] is True
    assert notifications_result.exit_code == 0
    notifications_payload = json.loads(notifications_result.output)
    assert notifications_payload[0]["delivery_id"] == notify_payload["delivery_id"]
    assert delivery_notify_result.exit_code == 0
    delivery_notify_payload = json.loads(delivery_notify_result.output)
    assert delivery_notify_payload["execution_id"] == report.execution_id
    assert delivery_notify_payload["status"] == "skipped"
    assert delivery_notifications_result.exit_code == 0
    delivery_notifications_payload = json.loads(delivery_notifications_result.output)
    assert delivery_notifications_payload[0]["delivery_id"] == (
        delivery_notify_payload["delivery_id"]
    )
    assert scheduled_summary_result.exit_code == 0
    scheduled_summary_payload = json.loads(scheduled_summary_result.output)
    assert scheduled_summary_payload["operations_console_summary"]["status"] in {
        "pass",
        "warn",
        "fail",
    }
    assert scheduled_summary_payload["content_assets_count"] == 1
    assert scheduled_summary_payload["items"][0]["content_assets_status"] == "generated"
    assert scheduled_summary_payload["items"][0]["execution_id"] == report.execution_id
    assert scheduled_summary_payload["items"][0]["pr_title"].startswith(
        "Publish scheduled ContentOps output"
    )
    assert scheduled_summary_payload["items"][0]["pr_checklist"]
    assert scheduled_summary_output_result.exit_code == 0
    assert "Scheduled ContentOps Review" in scheduled_summary_markdown.read_text(
        encoding="utf-8"
    )
    assert "Operations Console" in scheduled_summary_markdown.read_text(encoding="utf-8")
    assert "Distribution Assets" in scheduled_summary_markdown.read_text(encoding="utf-8")
    assert "PR Handoff" in scheduled_summary_markdown.read_text(encoding="utf-8")
    pr_metadata_payload = json.loads(scheduled_pr_metadata.read_text(encoding="utf-8"))
    review_manifest_payload = json.loads(scheduled_review_manifest.read_text(encoding="utf-8"))
    assert pr_metadata_payload["title"].startswith("Review scheduled ContentOps output")
    assert pr_metadata_payload["operations_console_summary"]["status"] in {
        "pass",
        "warn",
        "fail",
    }
    assert "Review generated feed, promotion brief, and distribution manifest." in (
        pr_metadata_payload["body"]
    )
    assert pr_metadata_payload["checklist"]
    assert review_manifest_payload["manifest_type"] == "scheduled_workflow_review"
    assert review_manifest_payload["operations_console_path"] == str(
        scheduled_operations_console
    )
    assert review_manifest_payload["content_assets_paths"] == [str(tmp_path / "site")]
    assert review_manifest_payload["worker_receipt_paths"]
    assert review_manifest_payload["metadata"]["hash_algorithm"] == "sha256"
    assert review_manifest_payload["artifacts"][str(scheduled_summary_markdown)][
        "sha256"
    ] == hashlib.sha256(scheduled_summary_markdown.read_bytes()).hexdigest()
    assert review_manifest_payload["artifacts"][str(scheduled_pr_metadata)]["exists"] is True
    assert review_manifest_payload["artifacts"][str(scheduled_operations_console)][
        "media_type"
    ] == "application/json"
    scheduled_verify_result = runner.invoke(
        app,
        ["scheduled-workflow-verify", str(scheduled_review_manifest), "--json"],
    )
    assert scheduled_verify_result.exit_code == 0
    scheduled_verify_payload = json.loads(scheduled_verify_result.output)
    assert scheduled_verify_payload["status"] == "pass"
    scheduled_review_archive = tmp_path / "scheduled-review-package.zip"
    scheduled_archive_result = runner.invoke(
        app,
        [
            "scheduled-workflow-archive",
            str(scheduled_review_manifest),
            str(scheduled_review_archive),
            "--json",
        ],
    )
    assert scheduled_archive_result.exit_code == 0
    scheduled_archive_payload = json.loads(scheduled_archive_result.output)
    assert scheduled_archive_payload["status"] == "pass"
    assert scheduled_archive_payload["archive_sha256"] == hashlib.sha256(
        scheduled_review_archive.read_bytes()
    ).hexdigest()
    with ZipFile(scheduled_review_archive) as archive:
        archive_names = set(archive.namelist())
    assert "scheduled-review-package.json" in archive_names
    assert "scheduled-review-manifest.json" in archive_names
    assert any(name.endswith("/content-distribution-manifest.json") for name in archive_names)
    scheduled_summary_markdown.write_text("drift", encoding="utf-8")
    scheduled_verify_drift_result = runner.invoke(
        app,
        ["scheduled-workflow-verify", str(scheduled_review_manifest), "--json"],
    )
    assert scheduled_verify_drift_result.exit_code != 0
    scheduled_verify_drift_payload = json.loads(scheduled_verify_drift_result.output)
    assert scheduled_verify_drift_payload["status"] == "fail"
    scheduled_archive_drift_result = runner.invoke(
        app,
        [
            "scheduled-workflow-archive",
            str(scheduled_review_manifest),
            str(tmp_path / "drifted-scheduled-review-package.zip"),
            "--json",
        ],
    )
    assert scheduled_archive_drift_result.exit_code != 0
    assert "verification failed" in scheduled_archive_drift_result.output
    assert recovery_result.exit_code == 0
    recovery_payload = json.loads(recovery_result.output)
    assert recovery_payload["failed_count"] == 0
    assert recovery_payload["source_dry_run"] is True
    assert recovery_payload["runnable"] is False
    assert recovery_run_result.exit_code != 0
    assert "Dry-run" in recovery_run_result.output


def test_cli_job_recovery_plan_can_run_failed_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    failed = JobExecutionReport(
        name="cli-recovery",
        total=1,
        succeeded=0,
        failed=1,
        results=[
            JobRunResult(
                job_name="failed-roundup",
                topic="CLI recovery rerun",
                status="failed",
                error="provider timeout",
            )
        ],
    )
    write_job_execution_report(failed, job_execution_dir(Settings().artifact_root))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "job-recovery-plan",
            failed.execution_id,
            "--run",
            "--actor",
            "zack",
            "--notes",
            "Retry provider timeout.",
        ],
    )
    lineage_result = runner.invoke(app, ["job-recovery-lineage", "--days", "1"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["name"] == "cli-recovery-recovery"
    assert payload["total"] == 1
    assert payload["succeeded"] == 1
    assert payload["results"][0]["metadata"]["recovery_source_execution_id"] == (
        failed.execution_id
    )
    assert payload["results"][0]["metadata"]["recovery_actor"] == "zack"
    assert payload["results"][0]["metadata"]["recovery_notes"] == "Retry provider timeout."
    assert lineage_result.exit_code == 0
    lineage_payload = json.loads(lineage_result.output)
    assert lineage_payload["recovery_attempt_count"] == 1
    lineage_item = next(
        item
        for item in lineage_payload["items"]
        if item["source_execution_id"] == failed.execution_id
    )
    assert lineage_item["latest_recovery_status"] == "recovered"


def test_cli_worker_jobs_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline_dir = tmp_path / "pipelines"
    pipeline_dir.mkdir()
    (pipeline_dir / "calendar.yaml").write_text(
        """
name: cli-calendar
schedule:
  enabled: true
  cron: "0 8 * * *"
  timezone: Asia/Shanghai
run_policy:
  timeout_minutes: 45
  concurrency_policy: forbid
  retry:
    max_attempts: 2
    backoff_seconds: 300
jobs:
  - name: aws-ai
    topic: AWS AI content operations
    publish: true
    homepage_handoff: true
    tags: [aws, ai]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONTENTOPS_PIPELINE_DIR", str(pipeline_dir))
    runner = CliRunner()

    result = runner.invoke(app, ["worker-jobs", "--json"])
    readiness_result = runner.invoke(app, ["worker-job-readiness", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total"] == 1
    assert payload["job_count"] == 1
    assert payload["publish_count"] == 1
    assert payload["handoff_count"] == 1
    assert payload["items"][0]["name"] == "cli-calendar"
    assert payload["items"][0]["readiness_status"] == "ready"
    assert payload["items"][0]["jobs"][0]["homepage_handoff"] is True
    assert payload["items"][0]["jobs"][0]["tags"] == ["aws", "ai"]
    assert readiness_result.exit_code == 0
    readiness_payload = json.loads(readiness_result.output)
    assert readiness_payload["can_schedule"] is True
    assert readiness_payload["items"][0]["status"] == "ready"


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


def _init_git_repo(path: Path) -> None:
    run(["git", "-C", str(path), "init"], check=True, capture_output=True)
