from __future__ import annotations

from pathlib import Path

import pytest
from contentops_core.config_templates import render_env_template
from contentops_core.diagnostics import deployment_check
from contentops_core.factory import build_review_service
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings

from scripts.generate_deployment_check import generate_deployment_check
from scripts.generate_release_gate import generate_release_gate


def test_production_env_example_matches_renderer() -> None:
    expected = render_env_template("production")
    actual = Path("config/production.env.example").read_text(encoding="utf-8")

    assert actual == expected
    assert "CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3" in actual
    assert "CONTENTOPS_OPERATOR_API_KEY=replace-with-long-random-operator-key" in actual
    assert "CONTENTOPS_DATABASE_URL=postgresql+psycopg://" in actual


def test_unknown_env_template_profile_fails() -> None:
    try:
        render_env_template("staging")
    except ValueError as exc:
        assert "Unknown config profile" in str(exc)
    else:
        raise AssertionError("Expected unknown config profile to fail.")


def test_deployment_check_reports_template_and_release_gates(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        site_output_dir=tmp_path / "site",
    )
    repository = RunRepository(settings.database_url)
    service = build_review_service(settings)

    report = deployment_check(
        settings,
        repository,
        service.operations_summary(),
        profile="production",
    )

    assert report.profile == "production"
    assert report.status in {"pass", "warn", "fail"}
    assert report.can_deploy is (report.status != "fail")
    assert {check.name for check in report.checks} >= {
        "system_status",
        "release_gates",
        "deployment_capabilities",
        "api_security",
        "environment_template",
    }
    template_check = next(check for check in report.checks if check.name == "environment_template")
    assert template_check.status == "warn"
    assert "CONTENTOPS_OPENAI_API_KEY" in template_check.evidence["placeholders"]


def test_generate_deployment_check_writes_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    output = tmp_path / "deployment-check" / "deployment-check.json"

    report = generate_deployment_check(output)

    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert '"profile": "production"' in text
    assert '"name": "environment_template"' in text
    assert report.profile == "production"


def test_generate_release_gate_writes_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    output = tmp_path / "release-gate" / "release-gate.json"

    report = generate_release_gate(
        output,
        git_sha="ci-sha",
        require_approval=False,
        record=True,
    )

    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert '"git_sha": "ci-sha"' in text
    assert '"name": "release_approval"' in text
    assert report.git_sha == "ci-sha"
    assert report.status in {"pass", "warn", "fail"}
    assert list((tmp_path / "artifacts" / "release-gates").glob("*.json"))
