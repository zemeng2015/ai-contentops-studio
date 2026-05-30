from __future__ import annotations

from pathlib import Path

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

    result = runner.invoke(app, ["run-pipeline", str(path), "--dry-run"])

    assert result.exit_code == 0
    assert "Loaded 2 job(s)" in result.output
    assert "roundup: AI platform weekly roundup" in result.output
    assert "evals: LLM evaluation checklist" in result.output


def test_worker_dry_run_can_emit_json(tmp_path: Path) -> None:
    path = tmp_path / "jobs.yaml"
    path.write_text("name: one\ntopic: AI systems\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["run-pipeline", str(path), "--dry-run", "--json"])

    assert result.exit_code == 0
    assert '"topic": "AI systems"' in result.output
