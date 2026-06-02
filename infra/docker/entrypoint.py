from __future__ import annotations

import os
import subprocess
import sys


def main() -> None:
    command = sys.argv[1:] or [
        "uvicorn",
        "contentops_api.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    if _enabled(os.getenv("CONTENTOPS_RUN_MIGRATIONS")):
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
        )
    os.execvp(command[0], command)


def _enabled(value: str | None) -> bool:
    return value is not None and value.strip().casefold() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
