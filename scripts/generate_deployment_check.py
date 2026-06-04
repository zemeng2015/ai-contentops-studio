from __future__ import annotations

import argparse
from pathlib import Path

from contentops_core.diagnostics import deployment_check
from contentops_core.factory import build_review_service
from contentops_core.models import DeploymentCheckReport
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate machine-readable deployment preflight evidence."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("deployment-check.json"),
        help="JSON file where deployment preflight evidence will be written.",
    )
    parser.add_argument(
        "--profile",
        default="production",
        choices=["local", "production"],
        help="Environment template profile to include in deployment checks.",
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=100,
        help="Number of recent runs used by release readiness gates.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when deployment checks fail.",
    )
    args = parser.parse_args()

    report = generate_deployment_check(args.output, args.profile, args.window_size)
    print(report.model_dump_json(indent=2))
    if args.strict and not report.can_deploy:
        raise SystemExit(1)


def generate_deployment_check(
    output: Path,
    profile: str = "production",
    window_size: int = 100,
) -> DeploymentCheckReport:
    settings = Settings()
    repository = RunRepository(settings.database_url)
    review_service = build_review_service(settings)
    report = deployment_check(
        settings,
        repository,
        review_service.operations_summary(window_size=window_size),
        profile=profile,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    main()
