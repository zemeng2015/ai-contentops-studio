from __future__ import annotations

from contentops_api.main import app, settings
from fastapi.testclient import TestClient
from pydantic import SecretStr


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")
    ready_response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
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


def test_run_artifact_and_publish_endpoints() -> None:
    client = TestClient(app)

    create_response = client.post("/runs", json={"topic": "API review workflow"})
    run = create_response.json()
    artifacts_response = client.get(f"/runs/{run['id']}/artifacts")
    manifest_response = client.get(f"/runs/{run['id']}/artifact-manifest")
    artifact_response = client.get(f"/runs/{run['id']}/artifacts/eval-report.json")
    plan_response = client.get(f"/runs/{run['id']}/publish-plan")
    metrics_response = client.get(f"/runs/{run['id']}/metrics")
    rerun_response = client.post(f"/runs/{run['id']}/rerun")
    blocked_publish_response = client.post(f"/runs/{run['id']}/publish")
    approve_response = client.post(f"/runs/{run['id']}/approve?reviewer=zack&notes=ready")
    approval_response = client.get(f"/runs/{run['id']}/approval")
    publish_response = client.post(f"/runs/{run['id']}/publish")
    receipt_response = client.get(f"/runs/{run['id']}/publish-receipt")
    audit_response = client.get(f"/runs/{run['id']}/audit-log")

    assert create_response.status_code == 200
    assert artifacts_response.status_code == 200
    assert "eval-report.json" in artifacts_response.json()
    assert manifest_response.status_code == 200
    assert manifest_response.json()["artifacts"]["eval-report.json"]["size_bytes"] > 0
    assert artifact_response.status_code == 200
    assert plan_response.status_code == 200
    assert plan_response.json()["ready"] is True
    assert metrics_response.status_code == 200
    assert metrics_response.json()["source_count"] >= 1
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
    assert audit_response.status_code == 200
    assert [event["action"] for event in audit_response.json()] == ["approve", "publish"]


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
    assert "Audit Log" in detail_response.text
    assert "Manifest JSON" in detail_response.text
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
