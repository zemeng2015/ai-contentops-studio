from __future__ import annotations

from pathlib import Path

from contentops_api.main import app, settings
from contentops_core.jobs import (
    JobRunner,
    job_execution_dir,
    load_job_file,
    write_job_execution_report,
)
from fastapi.testclient import TestClient
from pydantic import SecretStr


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")
    ready_response = client.get("/ready")
    manifest_response = client.get("/deployment-manifest")
    release_response = client.get("/release-readiness")

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
    assert release_response.status_code == 200
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
    bundle_response = client.get(f"/runs/{run['id']}/bundle")
    artifact_response = client.get(f"/runs/{run['id']}/artifacts/eval-report.json")
    plan_response = client.get(f"/runs/{run['id']}/publish-plan")
    source_audit_response = client.get(f"/runs/{run['id']}/source-audit")
    metrics_response = client.get(f"/runs/{run['id']}/metrics")
    scorecard_response = client.get(f"/runs/{run['id']}/scorecard")
    scorecards_response = client.get("/scorecards?limit=5")
    cost_report_response = client.get(f"/runs/{run['id']}/cost-report")
    cost_reports_response = client.get("/cost-reports?limit=5")
    incident_report_response = client.get(f"/runs/{run['id']}/incident-report")
    incident_reports_response = client.get("/incident-reports?limit=5")
    ops_summary_response = client.get("/ops-summary")
    release_readiness_response = client.get("/release-readiness")
    release_evidence_response = client.get("/release-evidence")
    retention_response = client.get("/retention-report?days=3650")
    generation_receipt_response = client.get(f"/runs/{run['id']}/generation-receipt")
    rerun_response = client.post(f"/runs/{run['id']}/rerun")
    blocked_publish_response = client.post(f"/runs/{run['id']}/publish")
    approve_response = client.post(f"/runs/{run['id']}/approve?reviewer=zack&notes=ready")
    approval_response = client.get(f"/runs/{run['id']}/approval")
    publish_response = client.post(f"/runs/{run['id']}/publish")
    receipt_response = client.get(f"/runs/{run['id']}/publish-receipt")
    verification_response = client.get(f"/runs/{run['id']}/publish-verification")
    notifications_response = client.get(f"/runs/{run['id']}/notifications")
    content_response = client.get("/content?limit=5")
    audit_response = client.get(f"/runs/{run['id']}/audit-log")
    audit_events_response = client.get("/audit-events?action=publish")

    assert create_response.status_code == 200
    assert artifacts_response.status_code == 200
    assert "eval-report.json" in artifacts_response.json()
    assert manifest_response.status_code == 200
    assert manifest_response.json()["artifacts"]["eval-report.json"]["size_bytes"] > 0
    assert bundle_response.status_code == 200
    assert bundle_response.content.startswith(b"PK")
    assert artifact_response.status_code == 200
    assert plan_response.status_code == 200
    assert plan_response.json()["ready"] is True
    assert source_audit_response.status_code == 200
    assert source_audit_response.json()["source_count"] >= 1
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
    assert release_readiness_response.status_code == 200
    assert release_readiness_response.json()["operations"]["total_runs"] >= 1
    assert release_evidence_response.status_code == 200
    release_evidence_payload = release_evidence_response.json()
    assert release_evidence_payload["summary"]["release_status"] in {"pass", "warn", "fail"}
    assert release_evidence_payload["release_readiness"]["operations"]["total_runs"] >= 1
    assert "deployment_manifest" in release_evidence_payload
    assert retention_response.status_code == 200
    assert retention_response.json()["total_runs_scanned"] >= 1
    assert retention_response.json()["total_size_bytes"] > 0
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
    assert len(receipt_response.json()["file_changes"]) == 3
    assert verification_response.status_code == 200
    assert verification_response.json()["verified"] is True
    assert len(verification_response.json()["items"]) == 3
    assert notifications_response.status_code == 200
    assert [item["action"] for item in notifications_response.json()] == ["approve", "publish"]
    assert content_response.status_code == 200
    assert any(item["run_id"] == run["id"] for item in content_response.json()["items"])
    assert audit_response.status_code == 200
    assert [event["action"] for event in audit_response.json()] == ["approve", "publish"]
    assert audit_events_response.status_code == 200
    audit_events_payload = audit_events_response.json()
    assert audit_events_payload["total"] >= 1
    assert audit_events_payload["action_counts"]["publish"] >= 1
    assert any(item["run_id"] == run["id"] for item in audit_events_payload["items"])


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
    assert changed_count == 3
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
    write_job_execution_report(report, job_execution_dir(settings.artifact_root))

    list_response = client.get("/job-executions?limit=5")
    detail_response = client.get(f"/job-executions/{report.execution_id}")
    recovery_response = client.get(f"/job-executions/{report.execution_id}/recovery-plan")
    dashboard_response = client.get("/dashboard")
    dashboard_detail_response = client.get(
        f"/dashboard/job-executions/{report.execution_id}"
    )

    assert list_response.status_code == 200
    assert any(
        item["execution_id"] == report.execution_id
        for item in list_response.json()["items"]
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["name"] == "api-job-history"
    assert recovery_response.status_code == 200
    assert recovery_response.json()["failed_count"] == 0
    assert dashboard_response.status_code == 200
    assert "Worker Job Catalog" in dashboard_response.text
    assert "Worker Executions" in dashboard_response.text
    assert report.execution_id in dashboard_response.text
    assert dashboard_detail_response.status_code == 200
    assert "Execution JSON" in dashboard_detail_response.text
    assert "API job history" in dashboard_detail_response.text


def test_worker_job_catalog_endpoint(tmp_path: Path) -> None:
    client = TestClient(app)
    original_pipeline_dir = settings.pipeline_dir
    pipeline_dir = tmp_path / "pipelines"
    pipeline_dir.mkdir()
    (pipeline_dir / "calendar.yaml").write_text(
        """
name: portfolio-calendar
jobs:
  - name: ai-roundup
    topic: AI engineering roundup
    publish: true
    tags: [ai, aws]
""",
        encoding="utf-8",
    )
    settings.pipeline_dir = pipeline_dir
    try:
        response = client.get("/worker-jobs")
    finally:
        settings.pipeline_dir = original_pipeline_dir

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["job_count"] == 1
    assert payload["publish_count"] == 1
    assert payload["items"][0]["path"] == "calendar.yaml"
    assert payload["items"][0]["jobs"][0]["topic"] == "AI engineering roundup"


def test_dashboard_worker_jobs_shows_content_calendar(tmp_path: Path) -> None:
    client = TestClient(app)
    original_pipeline_dir = settings.pipeline_dir
    pipeline_dir = tmp_path / "pipelines"
    pipeline_dir.mkdir()
    (pipeline_dir / "project_updates.yaml").write_text(
        """
name: project-updates
jobs:
  - name: github-project-update
    topic: GitHub project update for portfolio readers
    publish: false
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
    assert "github-project-update" in calendar_response.text
    assert "review first" in calendar_response.text
    assert "github.com/zemeng2015/ai-contentops-studio" in calendar_response.text
    assert "research_provider=github" in calendar_response.text


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
    assert "Operations Summary" in response.text
    assert "Audit Events" in response.text
    assert "Artifact Retention" in response.text
    assert "Worker Job Catalog" in response.text


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
    detail_response = client.get(f"/dashboard/runs/{run['id']}")

    assert detail_response.status_code == 200
    assert "Source Review" in detail_response.text
    assert "Publish Plan" in detail_response.text
    assert "Approval" in detail_response.text
    assert "Publish Receipt" in detail_response.text
    assert "Publish Verification" in detail_response.text
    assert "Audit Log" in detail_response.text
    assert "Notification Deliveries" in detail_response.text
    assert "Quality Scorecard" in detail_response.text
    assert "Token Budget" in detail_response.text
    assert "Generation Receipt" in detail_response.text
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
