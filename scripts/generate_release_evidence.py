from __future__ import annotations

import argparse
from pathlib import Path

from contentops_core.factory import build_review_service
from contentops_core.models import ReleaseEvidenceBundle
from contentops_core.release_evidence import build_release_evidence, write_release_evidence
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
    print(evidence.model_dump_json(indent=2))
    if evidence.release_readiness.status == "fail":
        raise SystemExit(1)


def generate_release_evidence(output_dir: Path, window_size: int = 100) -> ReleaseEvidenceBundle:
    settings = Settings()
    repository = RunRepository(settings.database_url)
    review_service = build_review_service(settings)
    bundle = build_release_evidence(
        settings=settings,
        repository=repository,
        review_service=review_service,
        window_size=window_size,
    )
    write_release_evidence(bundle, output_dir)
    return bundle


if __name__ == "__main__":
    main()
