from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from contentops_core.diagnostics import deployment_manifest, release_readiness, system_status
from contentops_core.factory import build_review_service
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate machine-readable release evidence for CI/CD review."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("release-evidence"),
        help="Directory where JSON evidence files will be written.",
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=100,
        help="Number of recent runs used by release readiness gates.",
    )
    args = parser.parse_args()

    evidence = generate_release_evidence(args.output_dir, args.window_size)
    print(json.dumps(evidence, indent=2))
    if evidence["release_readiness"]["status"] == "fail":
        raise SystemExit(1)


def generate_release_evidence(output_dir: Path, window_size: int = 100) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    repository = RunRepository(settings.database_url)
    review_service = build_review_service(settings)

    doctor = system_status(settings, repository)
    manifest = deployment_manifest(settings, repository)
    operations = review_service.operations_summary(window_size=window_size)
    readiness = release_readiness(settings, repository, operations)

    payloads: dict[str, Any] = {
        "doctor": doctor.model_dump(mode="json"),
        "deployment_manifest": manifest.model_dump(mode="json"),
        "operations_summary": operations.model_dump(mode="json"),
        "release_readiness": readiness.model_dump(mode="json"),
    }
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "git_sha": os.getenv("GITHUB_SHA") or os.getenv("CONTENTOPS_GIT_SHA"),
        "doctor_status": doctor.status,
        "release_status": readiness.status,
        "can_release": readiness.can_release,
        "artifact_files": [f"{name}.json" for name in [*payloads, "summary"]],
    }
    payloads["summary"] = summary

    for name, payload in payloads.items():
        _write_json(output_dir / f"{name}.json", payload)
    return summary | {"release_readiness": payloads["release_readiness"]}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
