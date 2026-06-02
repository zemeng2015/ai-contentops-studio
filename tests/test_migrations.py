from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_alembic_upgrade_creates_current_run_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "contentops.db"
    env = {
        **os.environ,
        "CONTENTOPS_DATABASE_URL": f"sqlite:///{database_path}",
    }

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=False,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]: row[2]
            for row in connection.execute("PRAGMA table_info(runs)").fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(runs)").fetchall()
        }

    assert columns == {
        "id": "VARCHAR(32)",
        "topic": "TEXT",
        "slug": "VARCHAR(120)",
        "status": "VARCHAR(32)",
        "artifact_dir": "TEXT",
        "published_url": "TEXT",
        "error": "TEXT",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    }
    assert {"ix_runs_slug", "ix_runs_status"}.issubset(indexes)
