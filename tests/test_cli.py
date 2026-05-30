from __future__ import annotations

from pathlib import Path

import pytest
from contentops_cli.main import app
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

    assert approve_result.exit_code == 0
    assert "Status: approved" in approve_result.output
    assert publish_result.exit_code == 0
    assert "Status: published" in publish_result.output
    assert receipt_result.exit_code == 0
    assert '"provider": "static"' in receipt_result.output
    assert '"reviewer": "zack"' in receipt_result.output
