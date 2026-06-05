from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_REQUIRED_FILES = {
    "content_calendar_lineage.json",
    "content_distribution.json",
    "deployment_check.json",
    "deployment_manifest.json",
    "doctor.json",
    "evidence_manifest.json",
    "homepage_handoffs.json",
    "integration_smoke_plan.json",
    "integration_smoke_runs.json",
    "operations_console.json",
    "operations_summary.json",
    "ops_brief.json",
    "ops_brief_deliveries.json",
    "provider_health.json",
    "publish_recovery_executions.json",
    "publish_verifications.json",
    "release_readiness.json",
    "retention_archives.json",
    "scheduled_review_packages.json",
    "source_reviews.json",
    "summary.json",
    "worker_delivery_summaries.json",
    "worker_delivery_summary_deliveries.json",
    "worker_execution_alert_deliveries.json",
    "worker_execution_alerts.json",
    "worker_execution_trends.json",
    "worker_recovery_lineage.json",
}


@dataclass(frozen=True)
class EvidenceRegressionReport:
    status: str
    evidence_dir: str
    artifact_count: int
    manifest_artifact_count: int
    total_bytes: int
    missing_required_files: list[str]
    orphan_json_files: list[str]
    min_artifacts: int


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check release evidence for accidental artifact loss."
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("release-evidence"),
        help="Directory produced by scripts/generate_release_evidence.py.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("release-evidence-regression/release-evidence-regression.json"),
        help="JSON file where the regression report will be written.",
    )
    parser.add_argument(
        "--min-artifacts",
        type=int,
        default=len(DEFAULT_REQUIRED_FILES),
        help="Minimum number of JSON artifacts expected in the release evidence directory.",
    )
    args = parser.parse_args()

    report = check_release_evidence_regression(
        args.evidence_dir,
        min_artifacts=args.min_artifacts,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(asdict(report), indent=2))
    if report.status != "pass":
        raise SystemExit(1)


def check_release_evidence_regression(
    evidence_dir: Path,
    *,
    min_artifacts: int = len(DEFAULT_REQUIRED_FILES),
) -> EvidenceRegressionReport:
    summary_path = evidence_dir / "summary.json"
    manifest_path = evidence_dir / "evidence_manifest.json"
    if not summary_path.exists() or not manifest_path.exists():
        missing = [
            path.name for path in (summary_path, manifest_path) if not path.exists()
        ]
        return EvidenceRegressionReport(
            status="fail",
            evidence_dir=str(evidence_dir),
            artifact_count=0,
            manifest_artifact_count=0,
            total_bytes=0,
            missing_required_files=missing,
            orphan_json_files=[],
            min_artifacts=min_artifacts,
        )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_files = {
        item
        for item in summary.get("artifact_files", [])
        if isinstance(item, str) and item.endswith(".json")
    }
    json_files = {path.name for path in evidence_dir.glob("*.json")}
    manifest_artifacts = {
        key for key in manifest.get("artifacts", {}) if isinstance(key, str)
    }
    missing_required = sorted(DEFAULT_REQUIRED_FILES - json_files)
    orphan_json_files = sorted(json_files - artifact_files - {"s3-mirror-log.json"})
    total_bytes = sum((evidence_dir / item).stat().st_size for item in json_files)
    status = "pass"
    if (
        missing_required
        or len(json_files) < min_artifacts
        or len(manifest_artifacts) < min_artifacts - 1
        or total_bytes <= 0
    ):
        status = "fail"
    return EvidenceRegressionReport(
        status=status,
        evidence_dir=str(evidence_dir),
        artifact_count=len(json_files),
        manifest_artifact_count=len(manifest_artifacts),
        total_bytes=total_bytes,
        missing_required_files=missing_required,
        orphan_json_files=orphan_json_files,
        min_artifacts=min_artifacts,
    )


if __name__ == "__main__":
    main()
