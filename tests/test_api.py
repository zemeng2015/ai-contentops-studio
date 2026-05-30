from __future__ import annotations

from contentops_api.main import app
from fastapi.testclient import TestClient


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_run_artifact_and_publish_endpoints() -> None:
    client = TestClient(app)

    create_response = client.post("/runs", json={"topic": "API review workflow"})
    run = create_response.json()
    artifacts_response = client.get(f"/runs/{run['id']}/artifacts")
    artifact_response = client.get(f"/runs/{run['id']}/artifacts/eval-report.json")
    plan_response = client.get(f"/runs/{run['id']}/publish-plan")
    metrics_response = client.get(f"/runs/{run['id']}/metrics")
    rerun_response = client.post(f"/runs/{run['id']}/rerun")
    blocked_publish_response = client.post(f"/runs/{run['id']}/publish")
    approve_response = client.post(f"/runs/{run['id']}/approve?reviewer=zack&notes=ready")
    approval_response = client.get(f"/runs/{run['id']}/approval")
    publish_response = client.post(f"/runs/{run['id']}/publish")

    assert create_response.status_code == 200
    assert artifacts_response.status_code == 200
    assert "eval-report.json" in artifacts_response.json()
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


def test_dashboard_run_detail_shows_source_review() -> None:
    client = TestClient(app)

    create_response = client.post("/runs", json={"topic": "Dashboard source review"})
    run = create_response.json()
    detail_response = client.get(f"/dashboard/runs/{run['id']}")

    assert detail_response.status_code == 200
    assert "Source Review" in detail_response.text
    assert "Publish Plan" in detail_response.text
    assert "Approval" in detail_response.text
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
