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
    publish_response = client.post(f"/runs/{run['id']}/publish")

    assert create_response.status_code == 200
    assert artifacts_response.status_code == 200
    assert "eval-report.json" in artifacts_response.json()
    assert artifact_response.status_code == 200
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"


def test_dashboard_renders() -> None:
    client = TestClient(app)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "AI ContentOps Studio" in response.text
    assert "Create run" in response.text
