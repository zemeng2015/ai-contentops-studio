from __future__ import annotations

import argparse
from pathlib import Path

from contentops_core.factory import build_review_service
from contentops_core.models import ReleaseGateReport
from contentops_core.release_gate import (
    release_gate,
    write_release_gate_checklist,
    write_release_gate_report,
)
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate machine-readable release gate evidence.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("release-gate.json"),
        help="JSON file where release gate evidence will be written.",
    )
    parser.add_argument(
        "--checklist-output",
        type=Path,
        default=None,
        help="Optional Markdown file where the deployment checklist will be written.",
    )
    parser.add_argument(
        "--git-sha",
        default=None,
        help="Git SHA that the deployment pipeline is about to release.",
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=100,
        help="Number of recent runs used by release readiness gates.",
    )
    parser.add_argument(
        "--no-require-approval",
        action="store_true",
        help="Report approval status without failing the gate when no approval exists.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when the release gate fails.",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="Persist the release gate report under the artifact root.",
    )
    args = parser.parse_args()

    report = generate_release_gate(
        output=args.output,
        checklist_output=args.checklist_output,
        git_sha=args.git_sha,
        window_size=args.window_size,
        require_approval=not args.no_require_approval,
        record=args.record,
    )
    print(report.model_dump_json(indent=2))
    if args.strict and not report.can_deploy:
        raise SystemExit(1)


def generate_release_gate(
    output: Path,
    *,
    checklist_output: Path | None = None,
    git_sha: str | None = None,
    window_size: int = 100,
    require_approval: bool = True,
    record: bool = False,
) -> ReleaseGateReport:
    settings = Settings()
    repository = RunRepository(settings.database_url)
    review_service = build_review_service(settings)
    report = release_gate(
        settings=settings,
        repository=repository,
        review_service=review_service,
        window_size=window_size,
        git_sha=git_sha,
        require_approval=require_approval,
    )
    if record:
        write_release_gate_report(report, settings.artifact_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if checklist_output is not None:
        write_release_gate_checklist(report, checklist_output)
    return report


if __name__ == "__main__":
    main()
