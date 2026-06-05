from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReleaseEvidenceComparison:
    status: str
    base_dir: str
    candidate_dir: str
    base_artifact_count: int
    candidate_artifact_count: int
    base_total_bytes: int
    candidate_total_bytes: int
    missing_from_candidate: list[str]
    new_in_candidate: list[str]
    skipped: bool = False
    message: str = ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare candidate release evidence against a previous evidence bundle."
    )
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("release-evidence-comparison/release-evidence-comparison.json"),
    )
    parser.add_argument(
        "--allow-missing-base",
        action="store_true",
        help="Write a skipped report instead of failing when no baseline evidence exists.",
    )
    args = parser.parse_args()

    report = compare_release_evidence(
        args.base_dir,
        args.candidate_dir,
        allow_missing_base=args.allow_missing_base,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(asdict(report), indent=2))
    if report.status != "pass":
        raise SystemExit(1)


def compare_release_evidence(
    base_dir: Path,
    candidate_dir: Path,
    *,
    allow_missing_base: bool = False,
) -> ReleaseEvidenceComparison:
    if not base_dir.exists():
        if allow_missing_base:
            candidate_files = _artifact_files(candidate_dir)
            return ReleaseEvidenceComparison(
                status="pass",
                base_dir=str(base_dir),
                candidate_dir=str(candidate_dir),
                base_artifact_count=0,
                candidate_artifact_count=len(candidate_files),
                base_total_bytes=0,
                candidate_total_bytes=_total_bytes(candidate_dir, candidate_files),
                missing_from_candidate=[],
                new_in_candidate=sorted(candidate_files),
                skipped=True,
                message="Baseline release evidence was not available; comparison skipped.",
            )
        return ReleaseEvidenceComparison(
            status="fail",
            base_dir=str(base_dir),
            candidate_dir=str(candidate_dir),
            base_artifact_count=0,
            candidate_artifact_count=0,
            base_total_bytes=0,
            candidate_total_bytes=0,
            missing_from_candidate=["summary.json", "evidence_manifest.json"],
            new_in_candidate=[],
            message="Baseline release evidence directory does not exist.",
        )
    base_files = _artifact_files(base_dir)
    candidate_files = _artifact_files(candidate_dir)
    missing = sorted(base_files - candidate_files)
    new_files = sorted(candidate_files - base_files)
    base_total = _total_bytes(base_dir, base_files)
    candidate_total = _total_bytes(candidate_dir, candidate_files)
    status = "pass"
    if missing or len(candidate_files) < len(base_files) or candidate_total <= 0:
        status = "fail"
    return ReleaseEvidenceComparison(
        status=status,
        base_dir=str(base_dir),
        candidate_dir=str(candidate_dir),
        base_artifact_count=len(base_files),
        candidate_artifact_count=len(candidate_files),
        base_total_bytes=base_total,
        candidate_total_bytes=candidate_total,
        missing_from_candidate=missing,
        new_in_candidate=new_files,
    )


def _artifact_files(evidence_dir: Path) -> set[str]:
    summary_path = evidence_dir / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return {
            item
            for item in summary.get("artifact_files", [])
            if isinstance(item, str) and item.endswith(".json")
        }
    return {path.name for path in evidence_dir.glob("*.json")}


def _total_bytes(evidence_dir: Path, files: set[str]) -> int:
    return sum(
        (evidence_dir / name).stat().st_size
        for name in files
        if (evidence_dir / name).exists()
    )


if __name__ == "__main__":
    main()
