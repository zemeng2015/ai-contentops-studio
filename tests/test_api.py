from __future__ import annotations

import json
from pathlib import Path
from subprocess import run

import pytest
from contentops_api.main import app, settings
from contentops_api.routes.dashboard import build_dashboard_router
from contentops_api.routes.ops import build_ops_router
from contentops_api.routes.runs import build_runs_router
from contentops_core.diagnostics import integration_smoke_dir, run_integration_smoke
from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.jobs import (
    JobExecutionReport,
    JobRunner,
    JobRunResult,
    create_scheduled_workflow_review_archive,
    job_execution_dir,
    load_job_file,
    scheduled_workflow_review_report,
    verify_scheduled_workflow_review_manifest,
    write_job_execution_report,
    write_scheduled_workflow_pr_metadata,
    write_scheduled_workflow_review_manifest,
    write_scheduled_workflow_review_markdown,
)
from contentops_core.models import ArtifactMirrorRecord, RunStatus
from contentops_core.release_gate import release_gate, write_release_gate_report
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")
    ready_response = client.get("/ready")
    manifest_response = client.get("/deployment-manifest")
    config_audit_response = client.get("/config-audit")
    provider_health_response = client.get("/provider-health")
    smoke_plan_response = client.get("/integration-smoke-plan")
    smoke_runs_response = client.get("/integration-smoke-runs")
    deployment_check_response = client.get("/deployment-check")
    env_template_response = client.get("/deployment-env-template")
    release_response = client.get("/release-readiness")
    release_bundle_response = client.get("/release-evidence/bundle")
    release_approvals_response = client.get("/release-approvals")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-contentops-request-id"]
    assert ready_response.status_code == 200
    ready_payload = ready_response.json()
    assert ready_payload["status"] in {"ok", "degraded"}
    assert {check["name"] for check in ready_payload["checks"]} >= {
        "database",
        "artifact_store",
        "provider_config",
        "operator_security",
    }
    assert "operator_api_key" not in ready_response.text
    assert manifest_response.status_code == 200
    manifest_payload = manifest_response.json()
    assert manifest_payload["status"] in {"ok", "degraded"}
    assert manifest_payload["runtime"]["database_engine"] in {"sqlite", "postgresql"}
    assert "openai_api_key" not in manifest_response.text
    assert config_audit_response.status_code == 200
    config_payload = config_audit_response.json()
    assert config_payload["redacted"] is True
    assert "items" in config_payload
    assert provider_health_response.status_code == 200
    assert {item["category"] for item in provider_health_response.json()["items"]} >= {
        "research",
        "generator",
        "publisher",
    }
    assert smoke_plan_response.status_code == 200
    smoke_payload = smoke_plan_response.json()
    assert smoke_payload["command"] == "pytest -m integration tests/test_integration_smoke.py"
    assert {item["name"] for item in smoke_payload["items"]} >= {
        "feed",
        "search",
        "openai",
        "homepage",
    }
    assert smoke_runs_response.status_code == 200
    assert "summary" in smoke_runs_response.json()
    assert "openai_api_key" in config_audit_response.text
    assert "sk-" not in config_audit_response.text
    assert deployment_check_response.status_code == 200
    deployment_check_payload = deployment_check_response.json()
    assert deployment_check_payload["profile"] == "production"
    assert deployment_check_payload["status"] in {"pass", "warn", "fail"}
    assert "environment_template" in {
        check["name"] for check in deployment_check_payload["checks"]
    }
    assert env_template_response.status_code == 200
    assert "CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3" in env_template_response.text
    assert "CONTENTOPS_OPERATOR_API_KEY=replace-with-long-random-operator-key" in (
        env_template_response.text
    )
    assert release_response.status_code == 200
    assert release_bundle_response.status_code == 200
    assert release_bundle_response.content.startswith(b"PK")
    assert release_approvals_response.status_code == 200
    assert "items" in release_approvals_response.json()
    release_payload = release_response.json()
    assert release_payload["status"] in {"pass", "warn", "fail"}
    assert isinstance(release_payload["can_release"], bool)
    assert {check["name"] for check in release_payload["checks"]} >= {
        "system_readiness",
        "incident_posture",
        "operator_security",
    }


def test_ready_endpoint_reports_invalid_provider() -> None:
    client = TestClient(app)
    original_provider = settings.generator_provider
    settings.generator_provider = "missing"
    try:
        response = client.get("/ready")
    finally:
        settings.generator_provider = original_provider

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "fail"
    provider_check = next(
        check for check in payload["checks"] if check["name"] == "provider_config"
    )
    assert provider_check["status"] == "fail"
    assert "unknown generator provider" in provider_check["fields"]["failures"][0]


def test_ready_endpoint_reports_read_protection_without_key() -> None:
    client = TestClient(app)
    original_key = settings.operator_api_key
    original_read_key = settings.read_api_key
    original_read_required = settings.require_read_api_key
    settings.operator_api_key = None
    settings.read_api_key = None
    settings.require_read_api_key = True
    try:
        response = client.get("/ready")
    finally:
        settings.operator_api_key = original_key
        settings.read_api_key = original_read_key
        settings.require_read_api_key = original_read_required

    assert response.status_code == 503
    security_check = next(
        check for check in response.json()["checks"] if check["name"] == "operator_security"
    )
    assert security_check["status"] == "fail"
    assert security_check["fields"]["read_routes_protected"] is True


def test_release_approval_api_and_dashboard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app)
    original_artifact_root = settings.artifact_root
    original_pipeline_dir = settings.pipeline_dir
    monkeypatch.setenv("CONTENTOPS_GIT_SHA", "api-release-sha")
    settings.artifact_root = tmp_path / "artifacts"
    settings.pipeline_dir = tmp_path / "pipelines"
    try:
        write_release_gate_report(
            release_gate(
                settings=settings,
                repository=RunRepository(settings.database_url),
                review_service=build_review_service(settings),
                git_sha="api-history-sha",
                require_approval=False,
            ),
            settings.artifact_root,
        )
        blocked_gate_response = client.get("/release-gate?git_sha=api-release-sha")
        create_response = client.post(
            "/release-approvals",
            json={
                "decision": "approved",
                "approver": "zack",
                "notes": "API approval record.",
                "force": True,
                "window_size": 100,
            },
        )
        list_response = client.get("/release-approvals")
        gate_history_response = client.get("/release-gates")
        gate_response = client.get("/release-gate?git_sha=api-release-sha")
        dashboard_response = client.get("/dashboard/release-evidence")
        evidence_response = client.get("/release-evidence")
        evidence_bundle_response = client.get("/release-evidence/bundle")
        dashboard_post_response = client.post(
            "/dashboard/release-approval",
            data={
                "decision": "rejected",
                "approver": "zack",
                "notes": "Hold deployment.",
            },
            follow_redirects=False,
        )
    finally:
        settings.artifact_root = original_artifact_root
        settings.pipeline_dir = original_pipeline_dir

    assert blocked_gate_response.status_code == 409
    assert create_response.status_code == 200
    approval = create_response.json()
    assert approval["decision"] == "approved"
    assert approval["approver"] == "zack"
    assert "deployment_check.json" in approval["evidence_files"]
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert gate_history_response.status_code == 200
    assert gate_history_response.json()["total"] == 1
    assert gate_history_response.json()["items"][0]["git_sha"] == "api-history-sha"
    assert gate_history_response.json()["summary"]["total_reports"] == 1
    assert "summary" in gate_history_response.json()
    assert gate_response.status_code in {200, 409}
    gate_payload = gate_response.json()
    assert gate_payload["latest_release_approval"]["approval_id"] == approval["approval_id"]
    assert gate_payload["git_sha"] == "api-release-sha"
    assert gate_payload["deployment_checklist"]
    assert gate_payload["config_audit"]["redacted"] is True
    assert "configuration_audit" in {check["name"] for check in gate_payload["checks"]}
    assert all("remediation_steps" in check for check in gate_payload["checks"])
    assert evidence_response.status_code == 200
    evidence_payload = evidence_response.json()
    assert evidence_payload["latest_release_approval"]["approval_id"] == approval["approval_id"]
    assert "release_approval.json" in evidence_payload["summary"]["artifact_files"]
    assert "source_reviews.json" in evidence_payload["summary"]["artifact_files"]
    assert "content_calendar_lineage.json" in evidence_payload["summary"]["artifact_files"]
    assert "content_calendar_lineage" in evidence_payload
    assert evidence_payload["source_reviews"]["total_decisions"] >= 0
    assert evidence_payload["publish_verifications"]["total"] >= 0
    assert evidence_bundle_response.status_code == 200
    assert b"release_approval.json" in evidence_bundle_response.content
    assert dashboard_response.status_code == 200
    assert "Release Approval" in dashboard_response.text
    assert "Deployment Checklist" in dashboard_response.text
    assert "Release Risk Summary" in dashboard_response.text
    assert "Risk posture" in dashboard_response.text
    assert "Open risks" in dashboard_response.text
    assert "Open gate checks" in dashboard_response.text
    assert 'href="#release-gate-checks"' in dashboard_response.text
    assert "<th>Operate</th>" in dashboard_response.text
    assert "Publish Verification Evidence" in dashboard_response.text
    assert "Publish Recovery Executions" in dashboard_response.text
    assert "Content Calendar Lineage Evidence" in dashboard_response.text
    assert "Calendar actions" in dashboard_response.text
    assert "Calendar runs" in dashboard_response.text
    assert "Provider Health" in dashboard_response.text
    assert "Integration Smoke Plan" in dashboard_response.text
    assert "Remediation" in dashboard_response.text
    assert "Recent Release Gates" in dashboard_response.text
    assert "Pass rate:" in dashboard_response.text
    assert "Most common failed checks:" in dashboard_response.text
    assert "api-history-sha" in dashboard_response.text
    assert "Recent Release Approvals" in dashboard_response.text
    assert "API approval record." in dashboard_response.text
    assert dashboard_post_response.status_code == 303


def test_publish_recovery_api_rolls_back_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app)
    original_artifact_root = settings.artifact_root
    original_database_url = settings.database_url
    original_site_output_dir = settings.site_output_dir
    settings.artifact_root = tmp_path / "artifacts"
    settings.database_url = f"sqlite:///{tmp_path / 'contentops.db'}"
    settings.site_output_dir = tmp_path / "site"
    try:
        create_response = client.post("/runs", json={"topic": "API publish recovery"})
        run_id = create_response.json()["id"]
        client.post(f"/runs/{run_id}/approve?reviewer=zack")
        client.post(f"/runs/{run_id}/publish")
        receipt = client.get(f"/runs/{run_id}/publish-receipt").json()
        target = Path(receipt["file_changes"][0]["path"])
        target.write_text("api drift", encoding="utf-8")
        plan_response = client.get(f"/runs/{run_id}/publish-recovery-plan")
        execute_response = client.post(
            f"/runs/{run_id}/publish-recovery",
            json={
                "action": "rollback",
                "actor": "zack",
                "notes": "API drift recovery.",
            },
        )
    finally:
        settings.artifact_root = original_artifact_root
        settings.database_url = original_database_url
        settings.site_output_dir = original_site_output_dir

    assert plan_response.status_code == 200
    assert plan_response.json()["runnable"] is True
    assert execute_response.status_code == 200
    payload = execute_response.json()
    assert payload["status"] == "completed"
    assert payload["action"] == "rollback"
    assert payload["rollback"]["errors"] == []


def test_read_routes_can_require_operator_key() -> None:
    client = TestClient(app)
    run = client.post("/runs", json={"topic": "Read route protection"}).json()
    original_key = settings.operator_api_key
    original_read_key = settings.read_api_key
    original_read_required = settings.require_read_api_key
    settings.operator_api_key = SecretStr("read-secret")
    settings.read_api_key = None
    settings.require_read_api_key = True
    try:
        health_response = client.get("/health")
        blocked_runs_response = client.get("/runs")
        blocked_dashboard_response = client.get("/dashboard")
        allowed_runs_response = client.get(
            "/runs",
            headers={"x-contentops-api-key": "read-secret"},
        )
        allowed_run_response = client.get(f"/runs/{run['id']}?api_key=read-secret")
    finally:
        settings.operator_api_key = original_key
        settings.read_api_key = original_read_key
        settings.require_read_api_key = original_read_required

    assert health_response.status_code == 200
    assert blocked_runs_response.status_code == 401
    assert blocked_dashboard_response.status_code == 401
    assert blocked_runs_response.json()["error"]["code"] == "unauthorized"
    assert blocked_runs_response.json()["error"]["request_id"] == (
        blocked_runs_response.headers["x-contentops-request-id"]
    )
    assert allowed_runs_response.status_code == 200
    assert allowed_run_response.status_code == 200
    assert allowed_run_response.json()["id"] == run["id"]


def test_read_routes_accept_dedicated_read_key_without_write_access() -> None:
    client = TestClient(app)
    original_key = settings.operator_api_key
    original_read_key = settings.read_api_key
    original_read_required = settings.require_read_api_key
    settings.operator_api_key = SecretStr("write-secret")
    settings.read_api_key = SecretStr("read-secret")
    settings.require_read_api_key = True
    try:
        read_response = client.get("/runs", headers={"x-contentops-api-key": "read-secret"})
        blocked_write_response = client.post(
            "/runs",
            headers={"x-contentops-api-key": "read-secret"},
            json={"topic": "Read key cannot write"},
        )
        write_response = client.post(
            "/runs",
            headers={"x-contentops-api-key": "write-secret"},
            json={"topic": "Write key can write"},
        )
    finally:
        settings.operator_api_key = original_key
        settings.read_api_key = original_read_key
        settings.require_read_api_key = original_read_required

    assert read_response.status_code == 200
    assert blocked_write_response.status_code == 401
    assert write_response.status_code == 200


def test_api_preserves_client_request_id_on_errors() -> None:
    client = TestClient(app)

    response = client.get(
        "/runs/missing-run",
        headers={"x-contentops-request-id": "req-test-123"},
    )

    assert response.status_code == 404
    assert response.headers["x-contentops-request-id"] == "req-test-123"
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "Run not found",
        "request_id": "req-test-123",
    }


def test_run_artifact_and_publish_endpoints() -> None:
    client = TestClient(app)

    create_response = client.post("/runs", json={"topic": "API review workflow"})
    run = create_response.json()
    artifacts_response = client.get(f"/runs/{run['id']}/artifacts")
    manifest_response = client.get(f"/runs/{run['id']}/artifact-manifest")
    mirror_log_path = Path(run["artifact_dir"]) / "s3-mirror-log.json"
    mirror_log_path.write_text(
        json.dumps(
            [
                {
                    "run_id": run["id"],
                    "artifact_name": "eval-report.json",
                    "provider": "s3",
                    "bucket": "api-bucket",
                    "key": f"contentops/{run['id']}/eval-report.json",
                    "content_type": "application/json",
                    "status": "mirrored",
                }
            ]
        ),
        encoding="utf-8",
    )
    mirror_log_response = client.get(f"/runs/{run['id']}/s3-mirror-log")
    bundle_response = client.get(f"/runs/{run['id']}/bundle")
    artifact_response = client.get(f"/runs/{run['id']}/artifacts/eval-report.json")
    plan_response = client.get(f"/runs/{run['id']}/publish-plan")
    source_audit_response = client.get(f"/runs/{run['id']}/source-audit")
    source_reviews_empty_response = client.get(f"/runs/{run['id']}/source-reviews")
    review_source_response = client.post(
        f"/runs/{run['id']}/source-reviews",
        json={
            "source_key": "AI engineering pattern library",
            "decision": "include",
            "reviewer": "zack",
            "notes": "Useful grounding source.",
        },
    )
    source_reviews_response = client.get(f"/runs/{run['id']}/source-reviews")
    metrics_response = client.get(f"/runs/{run['id']}/metrics")
    scorecard_response = client.get(f"/runs/{run['id']}/scorecard")
    scorecards_response = client.get("/scorecards?limit=5")
    cost_report_response = client.get(f"/runs/{run['id']}/cost-report")
    cost_reports_response = client.get("/cost-reports?limit=5")
    incident_report_response = client.get(f"/runs/{run['id']}/incident-report")
    incident_reports_response = client.get("/incident-reports?limit=5")
    ops_summary_response = client.get("/ops-summary")
    operations_console_response = client.get("/operations-console?days=7")
    ops_brief_response = client.get("/ops-brief?days=7")
    ops_brief_notify_response = client.post("/ops-brief/notify?days=7")
    ops_brief_notifications_response = client.get("/ops-brief/notifications")
    ops_trends_response = client.get("/ops-trends?days=7")
    worker_alerts_response = client.get("/job-executions/alerts?days=7")
    worker_alert_notify_response = client.post("/job-executions/alerts/notify?days=7")
    worker_alert_notifications_response = client.get("/job-executions/alerts/notifications")
    worker_delivery_notifications_response = client.get(
        "/job-executions/delivery-summaries/notifications"
    )
    release_readiness_response = client.get("/release-readiness")
    release_evidence_response = client.get("/release-evidence")
    retention_response = client.get("/retention-report?days=3650")
    retention_archive_response = client.post("/retention-archives?days=0")
    retention_archives_response = client.get("/retention-archives")
    generation_receipt_response = client.get(f"/runs/{run['id']}/generation-receipt")
    rerun_response = client.post(f"/runs/{run['id']}/rerun")
    blocked_publish_response = client.post(f"/runs/{run['id']}/publish")
    approve_response = client.post(f"/runs/{run['id']}/approve?reviewer=zack&notes=ready")
    approval_response = client.get(f"/runs/{run['id']}/approval")
    publish_response = client.post(f"/runs/{run['id']}/publish")
    receipt_response = client.get(f"/runs/{run['id']}/publish-receipt")
    verification_response = client.get(f"/runs/{run['id']}/publish-verification")
    recovery_plan_response = client.get(f"/runs/{run['id']}/publish-recovery-plan")
    notifications_response = client.get(f"/runs/{run['id']}/notifications")
    content_response = client.get("/content?limit=5")
    content_assets_response = client.post("/content-assets?title=API%20Feed")
    feed_response = client.get("/content-assets/feed")
    sitemap_response = client.get("/content-assets/sitemap")
    promotion_brief_response = client.get("/content-assets/promotion-brief")
    distribution_manifest_response = client.get("/content-assets/manifest")
    dashboard_response = client.get("/dashboard")
    audit_response = client.get(f"/runs/{run['id']}/audit-log")
    audit_events_response = client.get("/audit-events?action=publish")

    assert create_response.status_code == 200
    assert artifacts_response.status_code == 200
    assert "eval-report.json" in artifacts_response.json()
    assert manifest_response.status_code == 200
    assert manifest_response.json()["artifacts"]["eval-report.json"]["size_bytes"] > 0
    assert mirror_log_response.status_code == 200
    assert mirror_log_response.json()[0]["bucket"] == "api-bucket"
    assert mirror_log_response.json()[0]["status"] == "mirrored"
    assert bundle_response.status_code == 200
    assert bundle_response.content.startswith(b"PK")
    assert artifact_response.status_code == 200
    assert plan_response.status_code == 200
    assert plan_response.json()["ready"] is True
    assert source_audit_response.status_code == 200
    assert source_audit_response.json()["source_count"] >= 1
    assert source_reviews_empty_response.status_code == 200
    assert source_reviews_empty_response.json() == []
    assert review_source_response.status_code == 200
    assert review_source_response.json()["decision"] == "include"
    assert review_source_response.json()["reviewer"] == "zack"
    assert source_reviews_response.status_code == 200
    assert source_reviews_response.json()[0]["notes"] == "Useful grounding source."
    assert metrics_response.status_code == 200
    assert metrics_response.json()["source_count"] >= 1
    assert scorecard_response.status_code == 200
    assert scorecard_response.json()["overall_pass"] is True
    assert scorecard_response.json()["source_count"] >= 1
    assert scorecards_response.status_code == 200
    assert any(item["run_id"] == run["id"] for item in scorecards_response.json()["items"])
    assert cost_report_response.status_code == 200
    assert cost_report_response.json()["estimated_total_tokens"] > 0
    assert cost_report_response.json()["budget_pass"] is True
    assert cost_reports_response.status_code == 200
    assert any(item["run_id"] == run["id"] for item in cost_reports_response.json()["items"])
    assert incident_report_response.status_code == 200
    assert incident_report_response.json()["severity"] in {"info", "warning", "critical"}
    assert incident_reports_response.status_code == 200
    assert any(item["run_id"] == run["id"] for item in incident_reports_response.json()["items"])
    assert ops_summary_response.status_code == 200
    assert ops_summary_response.json()["total_runs"] >= 1
    assert "needs_review" in ops_summary_response.json()["status_counts"]
    assert operations_console_response.status_code == 200
    assert operations_console_response.json()["summary"]["status"] in {"pass", "warn", "fail"}
    assert operations_console_response.json()["summary"]["release_gate_status"] in {
        "pass",
        "warn",
        "fail",
    }
    assert ops_brief_response.status_code == 200
    assert ops_brief_response.json()["days"] == 7
    assert ops_brief_response.json()["summary"]["total_runs"] >= 1
    assert ops_brief_response.json()["recommended_actions"]
    assert ops_brief_notify_response.status_code == 200
    assert ops_brief_notify_response.json()["status"] in {"skipped", "delivered", "failed"}
    assert ops_brief_notifications_response.status_code == 200
    assert ops_brief_notifications_response.json()
    assert ops_trends_response.status_code == 200
    assert ops_trends_response.json()["days"] == 7
    assert ops_trends_response.json()["summary"]["total_runs"] >= 1
    assert any(bucket["run_count"] >= 1 for bucket in ops_trends_response.json()["buckets"])
    assert worker_alerts_response.status_code == 200
    assert worker_alerts_response.json()["severity"] in {"info", "warning", "critical"}
    assert worker_alert_notify_response.status_code == 200
    assert worker_alert_notify_response.json()["status"] in {"skipped", "delivered", "failed"}
    assert worker_alert_notifications_response.status_code == 200
    assert worker_alert_notifications_response.json()
    assert worker_delivery_notifications_response.status_code == 200
    assert release_readiness_response.status_code == 200
    assert release_readiness_response.json()["operations"]["total_runs"] >= 1
    assert release_evidence_response.status_code == 200
    release_evidence_payload = release_evidence_response.json()
    assert release_evidence_payload["summary"]["release_status"] in {"pass", "warn", "fail"}
    assert release_evidence_payload["release_readiness"]["operations"]["total_runs"] >= 1
    assert "deployment_manifest" in release_evidence_payload
    assert "operations_console" in release_evidence_payload
    assert release_evidence_payload["operations_console"]["summary"]["release_gate_status"] == (
        "not_evaluated"
    )
    assert "ops_brief" in release_evidence_payload
    assert "ops_brief_deliveries" in release_evidence_payload
    assert "retention_archives" in release_evidence_payload
    assert "worker_execution_trends" in release_evidence_payload
    assert "worker_execution_alerts" in release_evidence_payload
    assert "worker_execution_alert_deliveries" in release_evidence_payload
    assert "publish_recovery_executions" in release_evidence_payload
    assert "source_reviews" in release_evidence_payload
    assert release_evidence_payload["source_reviews"]["total_decisions"] >= 1
    assert release_evidence_payload["deployment_check"]["profile"] == "production"
    assert retention_response.status_code == 200
    assert retention_response.json()["total_runs_scanned"] >= 1
    assert retention_response.json()["total_size_bytes"] > 0
    assert retention_archive_response.status_code == 200
    assert retention_archive_response.json()["candidate_count"] >= 1
    assert run["id"] in retention_archive_response.json()["run_ids"]
    assert retention_archives_response.status_code == 200
    assert retention_archives_response.json()["total"] >= 1
    assert generation_receipt_response.status_code == 200
    assert generation_receipt_response.json()["provider"] == "template"
    assert generation_receipt_response.json()["total_tokens"] > 0
    assert rerun_response.status_code == 200
    assert rerun_response.json()["id"] != run["id"]
    assert rerun_response.json()["topic"] == run["topic"]
    assert blocked_publish_response.status_code == 409
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"
    assert approval_response.status_code == 200
    assert approval_response.json()["reviewer"] == "zack"
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"
    assert receipt_response.status_code == 200
    assert receipt_response.json()["url"] == publish_response.json()["published_url"]
    assert receipt_response.json()["approval"]["reviewer"] == "zack"
    assert len(receipt_response.json()["file_changes"]) == 4
    assert any(
        change["path"].endswith("contentops-publish-index.json")
        for change in receipt_response.json()["file_changes"]
    )
    assert verification_response.status_code == 200
    assert verification_response.json()["verified"] is True
    assert len(verification_response.json()["items"]) == 4
    assert recovery_plan_response.status_code == 200
    assert recovery_plan_response.json()["recommended_action"] == "none"
    assert notifications_response.status_code == 200
    notification_actions = [item["action"] for item in notifications_response.json()]
    assert "source_review" in notification_actions
    assert "approve" in notification_actions
    assert "publish" in notification_actions
    assert content_response.status_code == 200
    assert any(item["run_id"] == run["id"] for item in content_response.json()["items"])
    assert content_assets_response.status_code == 200
    assert content_assets_response.json()["feed"].endswith("feed.xml")
    assert content_assets_response.json()["sitemap"].endswith("sitemap.xml")
    assert content_assets_response.json()["promotion_brief"].endswith("promotion-brief.md")
    assert content_assets_response.json()["manifest"].endswith(
        "content-distribution-manifest.json"
    )
    assert feed_response.status_code == 200
    assert b"API Feed" in feed_response.content
    assert sitemap_response.status_code == 200
    assert b"sitemap" in sitemap_response.content
    assert promotion_brief_response.status_code == 200
    assert b"Promotion Brief" in promotion_brief_response.content
    assert distribution_manifest_response.status_code == 200
    assert distribution_manifest_response.json()["manifest_type"] == "content_distribution"
    assert dashboard_response.status_code == 200
    assert "Generate distribution assets" in dashboard_response.text
    assert "Distribution manifest" in dashboard_response.text
    assert audit_response.status_code == 200
    audit_actions = [event["action"] for event in audit_response.json()]
    assert "source_review" in audit_actions
    assert "approve" in audit_actions
    assert "publish" in audit_actions
    assert audit_events_response.status_code == 200
    audit_events_payload = audit_events_response.json()
    assert audit_events_payload["total"] >= 1
    assert audit_events_payload["action_counts"]["publish"] >= 1
    assert any(item["run_id"] == run["id"] for item in audit_events_payload["items"])


def test_homepage_handoff_endpoint_and_dashboard_link(tmp_path: Path) -> None:
    homepage = tmp_path / "homepage"
    (homepage / "posts").mkdir(parents=True)
    _init_git_repo(homepage)
    (homepage / "index.html").write_text(
        '<html><body><section id="writing"><div class="post-grid"></div></section></body></html>',
        encoding="utf-8",
    )
    local_settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        publisher_provider="homepage",
        homepage_repo_path=homepage,
        homepage_public_base_url="https://example.com",
    )
    local_pipeline = build_pipeline(local_settings)
    local_repository = RunRepository(local_settings.database_url)
    local_review_service = build_review_service(local_settings)
    local_app = FastAPI()

    async def allow_read(_request: Request) -> None:
        return None

    async def allow_operator(_request: Request) -> None:
        return None

    def parse_status(status: str) -> RunStatus | None:
        if not status:
            return None
        try:
            return RunStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown run status: {status}") from exc

    local_app.include_router(
        build_runs_router(
            pipeline=local_pipeline,
            repository=local_repository,
            review_service=local_review_service,
            require_read_access=allow_read,
            require_operator=allow_operator,
            parse_status_filter=parse_status,
        )
    )
    local_app.include_router(
        build_dashboard_router(
            settings=local_settings,
            pipeline=local_pipeline,
            repository=local_repository,
            review_service=local_review_service,
            require_read_access=allow_read,
            require_operator=allow_operator,
            parse_status_filter=parse_status,
        )
    )
    client = TestClient(local_app)

    create_response = client.post("/runs", json={"topic": "API homepage handoff"})
    run_payload = create_response.json()
    handoff_response = client.get(f"/runs/{run_payload['id']}/homepage-handoff")
    dashboard_response = client.get(f"/dashboard/runs/{run_payload['id']}")

    assert create_response.status_code == 200
    assert handoff_response.status_code == 200
    assert handoff_response.content.startswith(b"PK")
    assert dashboard_response.status_code == 200
    assert "Download homepage handoff" in dashboard_response.text
    assert "Publish Metadata" in dashboard_response.text


def test_publish_rollback_endpoint_restores_run_state() -> None:
    client = TestClient(app)

    create_response = client.post("/runs", json={"topic": "API rollback workflow"})
    run = create_response.json()
    client.post(f"/runs/{run['id']}/approve?reviewer=zack&notes=ready")
    client.post(f"/runs/{run['id']}/publish")
    rollback_response = client.post(f"/runs/{run['id']}/rollback-publish?actor=zack")
    audit_response = client.get(f"/runs/{run['id']}/audit-log")

    assert rollback_response.status_code == 200
    assert rollback_response.json()["errors"] == []
    rollback_payload = rollback_response.json()
    changed_count = len(rollback_payload["deleted_files"]) + len(rollback_payload["restored_files"])
    assert changed_count == 4
    assert audit_response.status_code == 200
    assert [event["action"] for event in audit_response.json()] == [
        "approve",
        "publish",
        "rollback_publish",
    ]


def test_compare_endpoint() -> None:
    client = TestClient(app)

    base_response = client.post("/runs", json={"topic": "API comparison workflow"})
    candidate_response = client.post(
        "/runs",
        json={
            "topic": "API comparison workflow",
            "source_urls": ["https://example.com/comparison-workflow"],
        },
    )
    base = base_response.json()
    candidate = candidate_response.json()
    compare_response = client.get(f"/runs/{base['id']}/compare/{candidate['id']}")

    assert compare_response.status_code == 200
    payload = compare_response.json()
    assert payload["base_run_id"] == base["id"]
    assert payload["candidate_run_id"] == candidate["id"]
    assert payload["same_topic"] is True
    assert payload["source_count_delta"] >= 1


def test_review_queue_filters_and_paginates() -> None:
    client = TestClient(app)

    client.post("/runs", json={"topic": "Review queue searchable"})
    response = client.get("/review-queue?q=searchable&status=needs_review&limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert len(payload["items"]) == 1
    assert payload["items"][0]["status"] == "needs_review"
    assert "searchable" in payload["items"][0]["topic"].lower()


def test_job_execution_endpoints_and_dashboard(tmp_path: Path) -> None:
    client = TestClient(app)
    path = tmp_path / "job.yaml"
    path.write_text("name: api-job-history\ntopic: API job history\n", encoding="utf-8")
    report = JobRunner.dry_run_report(load_job_file(path))
    report.release_evidence_path = str(tmp_path / "release-evidence")
    report.release_evidence_status = "warn"
    report.release_evidence_files = ["summary.json", "homepage_handoffs.json"]
    report.content_assets_path = str(tmp_path / "site")
    report.content_assets_status = "generated"
    report.content_assets_files = ["feed.xml", "sitemap.xml", "promotion-brief.md"]
    report.delivery_summary_path = str(tmp_path / "delivery-summary.json")
    report.delivery_summary_markdown_path = str(tmp_path / "delivery-summary.md")
    write_job_execution_report(report, job_execution_dir(settings.artifact_root))
    assert report.receipt_path is not None
    receipt_path = Path(report.receipt_path)
    (receipt_path.parent / "s3-mirror-log.json").write_text(
        json.dumps(
            [
                {
                    "run_id": f"job-executions/{receipt_path.stem}",
                    "artifact_name": receipt_path.name,
                    "provider": "s3",
                    "bucket": "job-bucket",
                    "key": f"contentops/job-executions/{receipt_path.stem}/{receipt_path.name}",
                    "content_type": "application/json",
                    "status": "mirrored",
                }
            ]
        ),
        encoding="utf-8",
    )

    list_response = client.get("/job-executions?limit=5")
    trends_response = client.get("/job-executions/trends?days=1")
    detail_response = client.get(f"/job-executions/{report.execution_id}")
    summary_response = client.get(f"/job-executions/{report.execution_id}/summary")
    delivery_notify_response = client.post(
        f"/job-executions/{report.execution_id}/delivery-summary/notify"
    )
    delivery_notifications_response = client.get(
        "/job-executions/delivery-summaries/notifications"
    )
    recovery_response = client.get(f"/job-executions/{report.execution_id}/recovery-plan")
    dashboard_response = client.get("/dashboard")
    dashboard_detail_response = client.get(
        f"/dashboard/job-executions/{report.execution_id}"
    )
    dashboard_delivery_notify_response = client.post(
        f"/dashboard/job-executions/{report.execution_id}/delivery-summary/notify",
        follow_redirects=False,
    )

    assert list_response.status_code == 200
    assert any(
        item["execution_id"] == report.execution_id
        for item in list_response.json()["items"]
    )
    assert trends_response.status_code == 200
    assert trends_response.json()["summary"]["execution_count"] >= 1
    assert detail_response.status_code == 200
    assert detail_response.json()["name"] == "api-job-history"
    assert summary_response.status_code == 200
    assert summary_response.json()["total_jobs"] == 1
    assert summary_response.json()["generated_runs"] == 0
    assert delivery_notify_response.status_code == 200
    assert delivery_notify_response.json()["execution_id"] == report.execution_id
    assert delivery_notifications_response.status_code == 200
    assert any(
        item["execution_id"] == report.execution_id
        for item in delivery_notifications_response.json()
    )
    assert recovery_response.status_code == 200
    assert recovery_response.json()["failed_count"] == 0
    assert dashboard_response.status_code == 200
    assert "Worker Job Catalog" in dashboard_response.text
    assert "Worker Executions" in dashboard_response.text
    assert report.execution_id in dashboard_response.text
    assert dashboard_detail_response.status_code == 200
    assert "Execution JSON" in dashboard_detail_response.text
    assert "API job history" in dashboard_detail_response.text
    assert "Recovery Preview" in dashboard_detail_response.text
    assert "Source dry run" in dashboard_detail_response.text
    assert "Dry-run worker receipts are schedule previews" in dashboard_detail_response.text
    assert "Evidence status" in dashboard_detail_response.text
    assert "Content assets" in dashboard_detail_response.text
    assert "feed.xml" in dashboard_detail_response.text
    assert "Delivery summary" in dashboard_detail_response.text
    assert "delivery-summary.md" in dashboard_detail_response.text
    assert "Generated runs" in dashboard_detail_response.text
    assert "Action required" in dashboard_detail_response.text
    assert "homepage_handoffs.json" in detail_response.text
    assert str(tmp_path / "release-evidence") in dashboard_detail_response.text
    assert "S3 Mirror Log" in dashboard_detail_response.text
    assert "job-bucket" in dashboard_detail_response.text
    assert "Run recovery jobs" in dashboard_detail_response.text
    assert "Notify delivery summary" in dashboard_detail_response.text
    assert dashboard_delivery_notify_response.status_code == 303


def test_scheduled_review_package_endpoints_and_dashboard(tmp_path: Path) -> None:
    client = TestClient(app)
    original_artifact_root = settings.artifact_root
    try:
        settings.artifact_root = tmp_path / "artifacts"
        path = tmp_path / "job.yaml"
        path.write_text("name: scheduled-api\ntopic: Scheduled API package\n", encoding="utf-8")
        report = JobRunner.dry_run_report(load_job_file(path))
        write_job_execution_report(report, job_execution_dir(settings.artifact_root))
        scheduled_dir = settings.artifact_root / "scheduled"
        scheduled_dir.mkdir(parents=True)
        operations_console_path = scheduled_dir / "daily-operations-console.json"
        operations_console_path.write_text(
            json.dumps({"summary": {"status": "pass"}}),
            encoding="utf-8",
        )
        review = scheduled_workflow_review_report(
            job_execution_dir(settings.artifact_root),
            limit=5,
            operations_console={"status": "pass"},
        )
        markdown_path = write_scheduled_workflow_review_markdown(
            review,
            scheduled_dir / "daily-review.md",
        )
        metadata_path = write_scheduled_workflow_pr_metadata(
            review,
            scheduled_dir / "daily-pr-metadata.json",
        )
        manifest_path = write_scheduled_workflow_review_manifest(
            review,
            scheduled_dir / "daily-review-manifest.json",
            review_markdown_path=markdown_path,
            pr_metadata_path=metadata_path,
            operations_console_path=operations_console_path,
        )
        verification_path = scheduled_dir / "daily-review-manifest-verification.json"
        verification_path.write_text(
            verify_scheduled_workflow_review_manifest(manifest_path).model_dump_json(indent=2),
            encoding="utf-8",
        )
        archive_report = create_scheduled_workflow_review_archive(
            manifest_path,
            scheduled_dir / "daily-review-package.zip",
        )
        (scheduled_dir / "daily-review-package.json").write_text(
            archive_report.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (scheduled_dir / "s3-mirror-log.json").write_text(
            json.dumps(
                [
                    ArtifactMirrorRecord(
                        run_id="scheduled-reviews/api-package",
                        artifact_name="daily-review-package.zip",
                        provider="s3",
                        bucket="contentops-artifacts",
                        key="contentops-artifacts/scheduled-reviews/api-package.zip",
                        content_type="application/zip",
                        status="mirrored",
                    ).model_dump(mode="json")
                ]
            ),
            encoding="utf-8",
        )

        list_response = client.get("/scheduled-reviews")
        dashboard_response = client.get("/dashboard")
        dashboard_packages_response = client.get("/dashboard/scheduled-reviews")

        assert list_response.status_code == 200
        payload = list_response.json()
        assert payload["total"] == 1
        item = payload["items"][0]
        assert item["status"] == "archived"
        assert item["verification_status"] == "pass"
        assert item["archive_exists"] is True
        assert item["archive_sha256"] == archive_report.archive_sha256
        archive_response = client.get(f"/scheduled-reviews/{item['id']}/archive")
        mirror_log_response = client.get(f"/scheduled-reviews/{item['id']}/s3-mirror-log")
        rebuild_response = client.post(f"/scheduled-reviews/{item['id']}/archive")
        dashboard_rebuild_response = client.post(
            f"/dashboard/scheduled-reviews/{item['id']}/archive",
            follow_redirects=False,
        )
        assert archive_response.status_code == 200
        assert archive_response.headers["content-type"] == "application/zip"
        assert mirror_log_response.status_code == 200
        assert mirror_log_response.json()[0]["artifact_name"] == "daily-review-package.zip"
        assert rebuild_response.status_code == 200
        assert rebuild_response.json()["status"] == "archived"
        assert dashboard_rebuild_response.status_code == 303
        assert dashboard_rebuild_response.headers["location"] == "/dashboard/scheduled-reviews"
        assert dashboard_response.status_code == 200
        assert "Scheduled Review Packages" in dashboard_response.text
        assert item["id"] in dashboard_response.text
        assert dashboard_packages_response.status_code == 200
        assert "Archives ready" in dashboard_packages_response.text
        assert "daily-review-package.zip" in dashboard_packages_response.text
        assert f"/scheduled-reviews/{item['id']}/s3-mirror-log" in dashboard_packages_response.text
        assert "Rebuild archive" in dashboard_packages_response.text
    finally:
        settings.artifact_root = original_artifact_root


def test_job_execution_recovery_can_be_run_from_api_and_dashboard(
    tmp_path: Path,
) -> None:
    client = TestClient(app)
    original_artifact_root = settings.artifact_root
    original_site_output_dir = settings.site_output_dir
    settings.artifact_root = tmp_path / "artifacts"
    settings.site_output_dir = tmp_path / "site"
    failed = JobExecutionReport(
        name="api-recovery",
        total=1,
        succeeded=0,
        failed=1,
        results=[
            JobRunResult(
                job_name="failed-roundup",
                topic="API recovery rerun",
                status="failed",
                error="provider timeout",
            )
        ],
    )
    try:
        write_job_execution_report(failed, job_execution_dir(settings.artifact_root))

        recovery_response = client.post(
            f"/job-executions/{failed.execution_id}/recovery-runs",
            params={"actor": "zack", "notes": "Retry provider timeout."},
        )
        dashboard_response = client.post(
            f"/dashboard/job-executions/{failed.execution_id}/recovery-runs",
            data={"actor": "dashboard-operator", "notes": "Retry from dashboard."},
            follow_redirects=False,
        )
        lineage_response = client.get("/job-executions/recovery-lineage?days=1")
        dashboard_trends_response = client.get("/dashboard/job-execution-trends?days=1")
        source_dashboard_response = client.get(
            f"/dashboard/job-executions/{failed.execution_id}"
        )
        dashboard_execution_id = dashboard_response.headers["location"].rsplit("/", 1)[-1]
        dashboard_detail = client.get(f"/job-executions/{dashboard_execution_id}")
    finally:
        settings.artifact_root = original_artifact_root
        settings.site_output_dir = original_site_output_dir

    assert recovery_response.status_code == 200
    recovery_payload = recovery_response.json()
    assert recovery_payload["name"] == "api-recovery-recovery"
    assert recovery_payload["total"] == 1
    assert recovery_payload["succeeded"] == 1
    assert recovery_payload["results"][0]["metadata"]["recovery_source_execution_id"] == (
        failed.execution_id
    )
    assert recovery_payload["results"][0]["metadata"]["recovery_actor"] == "zack"
    assert recovery_payload["results"][0]["metadata"]["recovery_notes"] == (
        "Retry provider timeout."
    )
    assert dashboard_response.status_code == 303
    assert "/dashboard/job-executions/" in dashboard_response.headers["location"]
    assert dashboard_detail.status_code == 200
    dashboard_metadata = dashboard_detail.json()["results"][0]["metadata"]
    assert dashboard_metadata["recovery_actor"] == "dashboard-operator"
    assert dashboard_metadata["recovery_notes"] == "Retry from dashboard."
    assert lineage_response.status_code == 200
    lineage_payload = lineage_response.json()
    assert lineage_payload["recovery_attempt_count"] == 2
    lineage_item = next(
        item
        for item in lineage_payload["items"]
        if item["source_execution_id"] == failed.execution_id
    )
    assert lineage_item["latest_recovery_status"] == "recovered"
    assert lineage_item["recovered_job_count"] == 1
    assert dashboard_trends_response.status_code == 200
    assert "Recovery Lineage" in dashboard_trends_response.text
    assert source_dashboard_response.status_code == 200
    assert "Recovery Lineage" in source_dashboard_response.text
    assert "dashboard-operator" in source_dashboard_response.text


def test_dry_run_job_execution_recovery_is_blocked(tmp_path: Path) -> None:
    client = TestClient(app)
    original_artifact_root = settings.artifact_root
    settings.artifact_root = tmp_path / "artifacts"
    path = tmp_path / "job.yaml"
    path.write_text("name: dry-run-recovery\ntopic: Dry run recovery\n", encoding="utf-8")
    report = JobRunner.dry_run_report(load_job_file(path))
    try:
        write_job_execution_report(report, job_execution_dir(settings.artifact_root))

        plan_response = client.get(f"/job-executions/{report.execution_id}/recovery-plan")
        run_response = client.post(f"/job-executions/{report.execution_id}/recovery-runs")
    finally:
        settings.artifact_root = original_artifact_root

    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    assert plan_payload["source_dry_run"] is True
    assert plan_payload["runnable"] is False
    assert "Dry-run" in plan_payload["blocked_reason"]
    assert run_response.status_code == 409
    assert "Dry-run" in run_response.text


def test_worker_job_catalog_endpoint(tmp_path: Path) -> None:
    client = TestClient(app)
    original_pipeline_dir = settings.pipeline_dir
    pipeline_dir = tmp_path / "pipelines"
    pipeline_dir.mkdir()
    (pipeline_dir / "calendar.yaml").write_text(
        """
name: portfolio-calendar
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
  - name: ai-roundup
    topic: AI engineering roundup
    publish: true
    homepage_handoff: true
    tags: [ai, aws]
""",
        encoding="utf-8",
    )
    settings.pipeline_dir = pipeline_dir
    try:
        response = client.get("/worker-jobs")
        readiness_response = client.get("/worker-jobs/readiness")
    finally:
        settings.pipeline_dir = original_pipeline_dir

    assert response.status_code == 200
    assert readiness_response.status_code == 200
    payload = response.json()
    readiness_payload = readiness_response.json()
    assert payload["total"] == 1
    assert payload["job_count"] == 1
    assert payload["publish_count"] == 1
    assert payload["handoff_count"] == 1
    assert payload["ready_count"] == 1
    assert payload["items"][0]["path"] == "calendar.yaml"
    assert payload["items"][0]["readiness_status"] == "ready"
    assert payload["items"][0]["handoff_count"] == 1
    assert payload["items"][0]["jobs"][0]["homepage_handoff"] is True
    assert payload["items"][0]["jobs"][0]["topic"] == "AI engineering roundup"
    assert readiness_payload["can_schedule"] is True
    assert readiness_payload["items"][0]["status"] == "ready"


def test_content_calendar_endpoint_returns_operator_brief(tmp_path: Path) -> None:
    client = TestClient(app)
    original_pipeline_dir = settings.pipeline_dir
    original_artifact_root = settings.artifact_root
    pipeline_dir = tmp_path / "pipelines"
    pipeline_dir.mkdir()
    (pipeline_dir / "calendar.yaml").write_text(
        """
name: api-calendar
schedule:
  enabled: true
  cron: "0 8 * * *"
jobs:
  - name: api-launch
    topic: API launch content operations
    publish: true
    homepage_handoff: true
    tags: [api, launch]
""",
        encoding="utf-8",
    )
    settings.pipeline_dir = pipeline_dir
    settings.artifact_root = tmp_path / "artifacts"
    try:
        response = client.get("/content-calendar")
    finally:
        settings.pipeline_dir = original_pipeline_dir
        settings.artifact_root = original_artifact_root

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["planned_workflows"] == 1
    assert payload["planned_jobs"] == 1
    assert payload["publish_intent"] == 1
    assert payload["tag_coverage"] == {"api": 1, "launch": 1}
    assert payload["next_items"][0]["job_name"] == "api-launch"


def test_content_calendar_run_endpoint_creates_lineaged_run(tmp_path: Path) -> None:
    pipeline_dir = tmp_path / "pipelines"
    pipeline_dir.mkdir()
    (pipeline_dir / "calendar.yaml").write_text(
        """
name: api-calendar
jobs:
  - name: api-launch
    topic: API launch content operations
    publish: false
    source_urls:
      - https://example.com/source
    tags: [api, launch]
""",
        encoding="utf-8",
    )
    local_settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        pipeline_dir=pipeline_dir,
        site_output_dir=tmp_path / "site",
    )
    local_pipeline = build_pipeline(local_settings)
    local_repository = RunRepository(local_settings.database_url)
    local_review_service = build_review_service(local_settings)
    local_app = FastAPI()

    async def allow_read(_request: Request) -> None:
        return None

    async def allow_operator(_request: Request) -> None:
        return None

    def parse_status(status: str) -> RunStatus | None:
        if not status:
            return None
        return RunStatus(status)

    local_app.include_router(
        build_ops_router(
            settings=local_settings,
            pipeline=local_pipeline,
            repository=local_repository,
            review_service=local_review_service,
            require_read_access=allow_read,
            require_operator=allow_operator,
            parse_status_filter=parse_status,
        )
    )
    local_app.include_router(
        build_dashboard_router(
            settings=local_settings,
            pipeline=local_pipeline,
            repository=local_repository,
            review_service=local_review_service,
            require_read_access=allow_read,
            require_operator=allow_operator,
            parse_status_filter=parse_status,
        )
    )
    client = TestClient(local_app)

    response = client.post(
        "/content-calendar/runs",
        params={"workflow_name": "api-calendar", "job_name": "api-launch"},
    )
    dashboard_response = client.post(
        "/dashboard/content-calendar/runs",
        data={"workflow_name": "api-calendar", "job_name": "api-launch"},
        follow_redirects=False,
    )
    lineage_response = client.get("/content-calendar/lineage")
    calendar_page_response = client.get("/dashboard/worker-jobs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["topic"] == "API launch content operations"
    request_payload = json.loads(
        (Path(payload["artifact_dir"]) / "request.json").read_text(encoding="utf-8")
    )
    assert request_payload["metadata"]["contentops_calendar_item_key"] == (
        "api-calendar/api-launch"
    )
    assert dashboard_response.status_code == 303
    assert "/dashboard/runs/" in dashboard_response.headers["location"]
    assert lineage_response.status_code == 200
    lineage_payload = lineage_response.json()
    assert lineage_payload["tracked_run_count"] == 2
    assert lineage_payload["items"][0]["latest_run_status"] == "needs_review"
    assert lineage_payload["items"][0]["latest_run_id"]
    assert calendar_page_response.status_code == 200
    assert "Calendar Lineage" in calendar_page_response.text
    assert "api-calendar/api-launch" in calendar_page_response.text


def test_dashboard_worker_jobs_shows_content_calendar(tmp_path: Path) -> None:
    client = TestClient(app)
    original_pipeline_dir = settings.pipeline_dir
    pipeline_dir = tmp_path / "pipelines"
    pipeline_dir.mkdir()
    (pipeline_dir / "project_updates.yaml").write_text(
        """
name: project-updates
schedule:
  enabled: true
  cron: "30 8 * * 1"
  timezone: Asia/Shanghai
run_policy:
  timeout_minutes: 60
  concurrency_policy: forbid
  retry:
    max_attempts: 2
    backoff_seconds: 300
jobs:
  - name: github-project-update
    topic: GitHub project update for portfolio readers
    publish: false
    homepage_handoff: true
    source_urls:
      - https://github.com/zemeng2015/ai-contentops-studio
    tags: [github, portfolio]
    metadata:
      research_provider: github
      content_type: project update
""",
        encoding="utf-8",
    )
    settings.pipeline_dir = pipeline_dir
    try:
        dashboard_response = client.get("/dashboard")
        calendar_response = client.get("/dashboard/worker-jobs")
    finally:
        settings.pipeline_dir = original_pipeline_dir

    assert dashboard_response.status_code == 200
    assert calendar_response.status_code == 200
    assert "Open content calendar" in dashboard_response.text
    assert "Content Calendar" in calendar_response.text
    assert "Automation Readiness" in calendar_response.text
    assert "ready" in calendar_response.text
    assert "github-project-update" in calendar_response.text
    assert "Homepage handoffs" in calendar_response.text
    assert "Create run" in calendar_response.text
    assert "review first" in calendar_response.text
    assert "github.com/zemeng2015/ai-contentops-studio" in calendar_response.text
    assert "research_provider=github" in calendar_response.text


def test_dashboard_run_detail_shows_workflow_context(tmp_path: Path) -> None:
    client = TestClient(app)
    path = tmp_path / "workflow.yaml"
    path.write_text(
        """
name: dashboard-project-updates
jobs:
  - name: dashboard-repo-update
    topic: Dashboard workflow context run
    tags: [github, dashboard]
    metadata:
      research_provider: github
      content_type: project update
""",
        encoding="utf-8",
    )
    report = JobRunner(build_pipeline(settings)).run(load_job_file(path))
    run_id = report.results[0].run_id
    assert run_id is not None

    response = client.get(f"/dashboard/runs/{run_id}")

    assert response.status_code == 200
    assert "Workflow Context" in response.text
    assert "dashboard-project-updates" in response.text
    assert "dashboard-repo-update" in response.text
    assert "content_type" in response.text
    assert "project update" in response.text


def test_review_queue_batch_approve_returns_per_run_results() -> None:
    client = TestClient(app)

    first = client.post("/runs", json={"topic": "Batch approve first"}).json()
    second = client.post("/runs", json={"topic": "Batch approve second"}).json()
    response = client.post(
        "/review-queue/batch-approve",
        json={
            "run_ids": [first["id"], second["id"], "missing-run"],
            "reviewer": "zack",
            "notes": "Batch ready.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "approve"
    assert [item["status"] for item in payload["results"]] == ["ok", "ok", "failed"]
    assert payload["results"][0]["new_status"] == "approved"
    assert "Run not found" in payload["results"][2]["error"]


def test_job_execution_runs_can_be_batch_approved() -> None:
    client = TestClient(app)

    first = client.post("/runs", json={"topic": "Execution approve first"}).json()
    second = client.post("/runs", json={"topic": "Execution approve second"}).json()
    report = JobExecutionReport(
        name="execution-approval",
        total=2,
        succeeded=2,
        failed=0,
        results=[
            JobRunResult(
                job_name="first",
                topic=first["topic"],
                status=first["status"],
                run_id=first["id"],
            ),
            JobRunResult(
                job_name="second",
                topic=second["topic"],
                status=second["status"],
                run_id=second["id"],
            ),
        ],
    )
    write_job_execution_report(report, job_execution_dir(settings.artifact_root))

    response = client.post(
        f"/job-executions/{report.execution_id}/approve-runs",
        json={"reviewer": "zack", "notes": "Reviewed from execution."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "approve"
    assert [item["status"] for item in payload["results"]] == ["ok", "ok"]
    assert client.get(f"/runs/{first['id']}").json()["status"] == "approved"
    assert client.get(f"/runs/{second['id']}").json()["status"] == "approved"


def test_job_execution_runs_can_be_batch_published() -> None:
    client = TestClient(app)

    first = client.post("/runs", json={"topic": "Execution publish first"}).json()
    second = client.post("/runs", json={"topic": "Execution publish second"}).json()
    client.post(f"/runs/{first['id']}/approve?reviewer=zack&notes=ready")
    client.post(f"/runs/{second['id']}/approve?reviewer=zack&notes=ready")
    report = JobExecutionReport(
        name="execution-publish",
        total=2,
        succeeded=2,
        failed=0,
        results=[
            JobRunResult(
                job_name="first",
                topic=first["topic"],
                status=first["status"],
                run_id=first["id"],
            ),
            JobRunResult(
                job_name="second",
                topic=second["topic"],
                status=second["status"],
                run_id=second["id"],
            ),
        ],
    )
    write_job_execution_report(report, job_execution_dir(settings.artifact_root))

    response = client.post(
        f"/job-executions/{report.execution_id}/publish-runs",
        json={"force": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "publish"
    assert [item["status"] for item in payload["results"]] == ["ok", "ok"]
    assert client.get(f"/runs/{first['id']}").json()["status"] == "published"
    assert client.get(f"/runs/{second['id']}").json()["status"] == "published"
    assert client.get(f"/runs/{first['id']}/publish-receipt").json()["url"]


def test_dashboard_renders() -> None:
    client = TestClient(app)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "AI ContentOps Studio" in response.text
    assert "Create run" in response.text
    assert "Optional source URLs" in response.text
    assert "Published Content" in response.text
    assert "Quality Scorecards" in response.text
    assert "Token Budgets" in response.text
    assert "Incident Reports" in response.text
    assert "Ops Brief" in response.text
    assert "Open ops brief" in response.text
    assert "Operations Summary" in response.text
    assert "Open operations console" in response.text
    assert "Open operations trends" in response.text
    assert "Integration Smoke" in response.text
    assert "Open integration smoke history" in response.text
    assert "System status dashboard" in response.text
    assert "Release evidence dashboard" in response.text
    assert "Audit Events" in response.text
    assert "Artifact Retention" in response.text
    assert "Open retention lifecycle" in response.text
    assert "Create archive" in response.text
    assert "Worker Job Catalog" in response.text


def test_dashboard_operations_console_renders() -> None:
    client = TestClient(app)

    response = client.get("/dashboard/operations?days=7&window_size=100")

    assert response.status_code == 200
    assert "Operations Console" in response.text
    assert "Brief status" in response.text
    assert "Review queue" in response.text
    assert "Release gate" in response.text
    assert "Retention gate" in response.text
    assert "Worker success" in response.text
    assert "Daily Brief" in response.text
    assert "Worker Automation" in response.text
    assert "Retention Governance" in response.text
    assert "Retention lifecycle" in response.text


def test_dashboard_integration_smoke_history_renders() -> None:
    output_path = integration_smoke_dir(settings.artifact_root) / "api-smoke-test.json"
    run_integration_smoke(
        settings,
        selected=["openai"],
        output_path=output_path,
        dry_run=True,
    )
    client = TestClient(app)

    api_response = client.get("/integration-smoke-runs")
    dashboard_response = client.get("/dashboard/integration-smoke")

    assert api_response.status_code == 200
    payload = api_response.json()
    assert payload["summary"]["total_reports"] >= 1
    assert any(item["artifact_path"] == str(output_path) for item in payload["items"])
    assert dashboard_response.status_code == 200
    assert "Integration Smoke" in dashboard_response.text
    assert "api-smoke-test.json" in dashboard_response.text


def test_operations_console_endpoint_renders_machine_readable_report() -> None:
    client = TestClient(app)

    response = client.get("/operations-console?days=7&window_size=100")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["status"] in {"pass", "warn", "fail"}
    assert payload["summary"]["brief_status"] in {"pass", "warn", "fail"}
    assert payload["summary"]["release_gate_status"] in {"pass", "warn", "fail"}
    assert "ops_brief" in payload
    assert "worker_execution_trends" in payload
    assert "retention_report" in payload


def test_dashboard_retention_lifecycle_renders() -> None:
    client = TestClient(app)

    response = client.get("/dashboard/retention?days=90&limit=100")
    archive_response = client.post(
        "/dashboard/retention/archive",
        data={"days": "0", "limit": "100"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Retention Lifecycle" in response.text
    assert "Archive candidates" in response.text
    assert "Archive receipts" in response.text
    assert "Gate status" in response.text
    assert "retention_archive_governance" in response.text
    assert "S3 mirror" in response.text
    assert archive_response.status_code == 303
    assert archive_response.headers["location"].startswith("/dashboard/retention")


def test_dashboard_ops_trends_renders() -> None:
    client = TestClient(app)

    response = client.get("/dashboard/ops-trends?days=7")

    assert response.status_code == 200
    assert "Operations Trends" in response.text
    assert "Ops trends JSON" in response.text
    assert "Quality" in response.text
    assert "Budget" in response.text


def test_dashboard_ops_brief_renders() -> None:
    client = TestClient(app)

    response = client.get("/dashboard/ops-brief?days=7")

    assert response.status_code == 200
    assert "Operations Brief" in response.text
    assert "Ops brief JSON" in response.text
    assert "Notify ops brief" in response.text
    assert "Notification History" in response.text
    assert "Top Risks" in response.text
    assert "Recommended Actions" in response.text

    notify_response = client.post("/dashboard/ops-brief/notify", follow_redirects=False)

    assert notify_response.status_code == 303


def test_dashboard_job_execution_trends_renders() -> None:
    client = TestClient(app)

    response = client.get("/dashboard/job-execution-trends?days=7")

    assert response.status_code == 200
    assert "Worker Execution Trends" in response.text
    assert "Worker execution trends JSON" in response.text
    assert "Worker execution alerts JSON" in response.text
    assert "Notify worker alert" in response.text
    assert "Worker Alert Notifications" in response.text
    assert "Alert Signals" in response.text
    assert "Handoff success" in response.text
    assert "Failure Diagnostics" in response.text
    assert "Latest execution" in response.text
    assert "Remediation" in response.text


def test_dashboard_system_status_renders() -> None:
    client = TestClient(app)

    response = client.get("/dashboard/system-status")

    assert response.status_code == 200
    assert "System Status" in response.text
    assert "Configuration Audit" in response.text
    assert "Recommended Fixes" in response.text
    assert "Component Checks" in response.text
    assert "Deployment Capabilities" in response.text
    assert "provider_config" in response.text
    assert "operator_security" in response.text
    assert "CONTENTOPS_OPERATOR_API_KEY" in response.text
    assert "CONTENTOPS_RESEARCH_PROVIDER" in response.text
    assert "Deployment check JSON" in response.text
    assert "Config audit JSON" in response.text
    assert "Production env template" in response.text
    assert "System status JSON" in response.text


def test_dashboard_release_evidence_renders() -> None:
    client = TestClient(app)

    response = client.get("/dashboard/release-evidence")

    assert response.status_code == 200
    assert "Release Evidence" in response.text
    assert "Operations Brief" in response.text
    assert "Ops Brief Notifications" in response.text
    assert "Retention Archives" in response.text
    assert "Deployment Gate" in response.text
    assert "Integration Smoke Runs" in response.text
    assert "Deployment Preflight" in response.text
    assert "Release Gate Checks" in response.text
    assert "Release Risk Summary" in response.text
    assert "Risk posture" in response.text
    assert "Open risks" in response.text
    assert "<th>Open</th>" in response.text
    assert "<th>Operate</th>" in response.text
    assert 'id="release-gate-checks"' in response.text
    assert 'id="content-calendar-lineage-evidence"' in response.text
    assert 'href="/dashboard/job-execution-trends"' in response.text
    assert "Notify worker alert" in response.text
    assert 'name="days" value="14"' in response.text
    assert "Deployment Capabilities" in response.text
    assert "Evidence Files" in response.text
    assert "Homepage Handoffs" in response.text
    assert "Content Calendar Lineage Evidence" in response.text
    assert "Content calendar lineage JSON" in response.text
    assert "Calendar actions" in response.text
    assert "Scheduled Review Package Evidence" in response.text
    assert "Source Review Evidence" in response.text
    assert "Worker Execution Trends" in response.text
    assert "Worker alert" in response.text
    assert "Worker Alert Notifications" in response.text
    assert "Worker Failure Diagnostics" in response.text
    assert "Remediation" in response.text
    assert "Download evidence bundle" in response.text
    assert "environment_template" in response.text
    assert "evidence_manifest.json" in response.text
    assert "integration_smoke_runs.json" in response.text


def test_dashboard_filters_runs() -> None:
    client = TestClient(app)

    client.post("/runs", json={"topic": "Dashboard filter needle"})
    response = client.get("/dashboard?q=filter%20needle&status=needs_review")

    assert response.status_code == 200
    assert "Dashboard filter needle" in response.text
    assert "Filter runs" in response.text
    assert "Matching runs" in response.text


def test_dashboard_run_detail_shows_source_review() -> None:
    client = TestClient(app)

    create_response = client.post("/runs", json={"topic": "Dashboard source review"})
    run = create_response.json()
    research_path = Path(run["artifact_dir"]) / "research.json"
    research_payload = json.loads(research_path.read_text(encoding="utf-8"))
    research_payload["provider_metadata"] = {
        "provider": "search",
        "planned_queries": [
            "Dashboard source review",
            "Dashboard source review production architecture",
        ],
        "result_count": 3,
        "selected_count": 2,
        "selected_urls": ["https://example.com/research"],
    }
    research_path.write_text(json.dumps(research_payload), encoding="utf-8")
    detail_response = client.get(f"/dashboard/runs/{run['id']}")

    assert detail_response.status_code == 200
    assert "Source Review" in detail_response.text
    assert "Research Provider" in detail_response.text
    assert "Query Plan" in detail_response.text
    assert "Dashboard source review production architecture" in detail_response.text
    assert "Selected URLs" in detail_response.text
    assert "https://example.com/research" in detail_response.text
    assert "Source review JSON" in detail_response.text
    assert "Needs review" in detail_response.text
    assert "Publish Plan" in detail_response.text
    assert "Approval" in detail_response.text
    assert "Publish Receipt" in detail_response.text
    assert "Publish Verification" in detail_response.text
    assert "Audit Log" in detail_response.text
    assert "Notification Deliveries" in detail_response.text
    assert "Quality Scorecard" in detail_response.text
    assert "Token Budget" in detail_response.text
    assert "Generation Receipt" in detail_response.text
    assert "S3 Mirror Log" in detail_response.text
    assert "Incident Report" in detail_response.text
    assert "Manifest JSON" in detail_response.text
    assert "Download evidence bundle" in detail_response.text
    assert "Run Timeline" in detail_response.text
    assert "Rerun with same request" in detail_response.text
    assert "Compare runs" in detail_response.text
    assert "extraction" not in detail_response.text.lower()


def test_dashboard_create_accepts_source_urls() -> None:
    client = TestClient(app)

    response = client.post(
        "/dashboard/runs",
        data={
            "topic": "Dashboard URL research",
            "source_urls": "https://example.com/one\nhttps://example.com/two",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303


def test_dashboard_can_approve_run() -> None:
    client = TestClient(app)

    create_response = client.post("/runs", json={"topic": "Dashboard approval workflow"})
    run = create_response.json()
    response = client.post(
        f"/dashboard/runs/{run['id']}/approve",
        data={"reviewer": "zack", "notes": "Ready."},
        follow_redirects=False,
    )
    approval_response = client.get(f"/runs/{run['id']}/approval")

    assert response.status_code == 303
    assert approval_response.status_code == 200
    assert approval_response.json()["decision"] == "approved"


def test_dashboard_can_approve_runs_from_job_execution() -> None:
    client = TestClient(app)

    first = client.post("/runs", json={"topic": "Dashboard execution approve first"}).json()
    second = client.post("/runs", json={"topic": "Dashboard execution approve second"}).json()
    report = JobExecutionReport(
        name="dashboard-execution-approval",
        total=2,
        succeeded=2,
        failed=0,
        results=[
            JobRunResult(
                job_name="first",
                topic=first["topic"],
                status=first["status"],
                run_id=first["id"],
            ),
            JobRunResult(
                job_name="second",
                topic=second["topic"],
                status=second["status"],
                run_id=second["id"],
            ),
        ],
    )
    write_job_execution_report(report, job_execution_dir(settings.artifact_root))

    detail = client.get(f"/dashboard/job-executions/{report.execution_id}")
    response = client.post(
        f"/dashboard/job-executions/{report.execution_id}/approve-runs",
        data={"reviewer": "zack", "notes": "Approved execution."},
        follow_redirects=False,
    )

    assert detail.status_code == 200
    assert "Execution Review" in detail.text
    assert "Approve generated runs" in detail.text
    assert response.status_code == 303
    assert client.get(f"/runs/{first['id']}").json()["status"] == RunStatus.APPROVED.value
    assert client.get(f"/runs/{second['id']}").json()["status"] == RunStatus.APPROVED.value


def test_dashboard_can_publish_runs_from_job_execution() -> None:
    client = TestClient(app)

    first = client.post("/runs", json={"topic": "Dashboard execution publish first"}).json()
    second = client.post("/runs", json={"topic": "Dashboard execution publish second"}).json()
    client.post(f"/runs/{first['id']}/approve?reviewer=zack&notes=ready")
    client.post(f"/runs/{second['id']}/approve?reviewer=zack&notes=ready")
    report = JobExecutionReport(
        name="dashboard-execution-publish",
        total=2,
        succeeded=2,
        failed=0,
        results=[
            JobRunResult(
                job_name="first",
                topic=first["topic"],
                status=first["status"],
                run_id=first["id"],
            ),
            JobRunResult(
                job_name="second",
                topic=second["topic"],
                status=second["status"],
                run_id=second["id"],
            ),
        ],
    )
    write_job_execution_report(report, job_execution_dir(settings.artifact_root))

    detail = client.get(f"/dashboard/job-executions/{report.execution_id}")
    response = client.post(
        f"/dashboard/job-executions/{report.execution_id}/publish-runs",
        data={},
        follow_redirects=False,
    )

    assert detail.status_code == 200
    assert "Publish approved runs" in detail.text
    assert response.status_code == 303
    assert client.get(f"/runs/{first['id']}").json()["status"] == RunStatus.PUBLISHED.value
    assert client.get(f"/runs/{second['id']}").json()["status"] == RunStatus.PUBLISHED.value


def test_dashboard_can_batch_reject_runs() -> None:
    client = TestClient(app)

    first = client.post("/runs", json={"topic": "Dashboard batch reject first"}).json()
    second = client.post("/runs", json={"topic": "Dashboard batch reject second"}).json()
    response = client.post(
        "/dashboard/runs/batch-reject",
        data={
            "run_ids": [first["id"], second["id"]],
            "reviewer": "zack",
            "notes": "Not ready as a set.",
        },
        follow_redirects=False,
    )
    first_record = client.get(f"/runs/{first['id']}").json()
    second_record = client.get(f"/runs/{second['id']}").json()

    assert response.status_code == 303
    assert first_record["status"] == "rejected"
    assert second_record["status"] == "rejected"


def test_dashboard_publish_requires_approval() -> None:
    client = TestClient(app)

    create_response = client.post("/runs", json={"topic": "Dashboard blocked publish"})
    run = create_response.json()
    response = client.post(
        f"/dashboard/runs/{run['id']}/publish",
        follow_redirects=False,
    )

    assert response.status_code == 409
    assert "approved before publishing" in response.text


def test_rejected_run_requires_force_to_publish() -> None:
    client = TestClient(app)

    create_response = client.post("/runs", json={"topic": "Rejected publish workflow"})
    run = create_response.json()
    reject_response = client.post(f"/runs/{run['id']}/reject?reviewer=zack&notes=not-ready")
    publish_response = client.post(f"/runs/{run['id']}/publish")
    force_publish_response = client.post(f"/runs/{run['id']}/publish?force=true")

    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"
    assert publish_response.status_code == 409
    assert force_publish_response.status_code == 200


def test_operator_api_key_protects_mutations() -> None:
    client = TestClient(app)
    original_key = settings.operator_api_key
    settings.operator_api_key = SecretStr("test-secret")
    try:
        blocked_response = client.post("/runs", json={"topic": "Protected mutation"})
        allowed_response = client.post(
            "/runs",
            json={"topic": "Protected mutation"},
            headers={"X-ContentOps-Api-Key": "test-secret"},
        )
        read_response = client.get("/runs")
    finally:
        settings.operator_api_key = original_key

    assert blocked_response.status_code == 401
    assert allowed_response.status_code == 200
    assert read_response.status_code == 200


def _init_git_repo(path: Path) -> None:
    run(["git", "-C", str(path), "init"], check=True, capture_output=True)
