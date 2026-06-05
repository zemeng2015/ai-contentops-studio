from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.jobs import (
    JobExecutionReport,
    JobRunResult,
    job_execution_dir,
    notify_worker_delivery_summary,
    write_job_execution_delivery_summary,
    write_job_execution_report,
)
from contentops_core.models import ReleaseApprovalDecision, ReleaseApprovalRequest, RunRequest
from contentops_core.release_approvals import approve_release
from contentops_core.release_evidence import create_release_evidence_archive
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings

from scripts.generate_release_evidence import generate_release_evidence


def test_generate_release_evidence_writes_operational_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setenv("CONTENTOPS_GIT_SHA", "test-sha")
    output_dir = tmp_path / "release-evidence"

    bundle = generate_release_evidence(output_dir)

    expected_files = {
        "content_distribution.json",
        "doctor.json",
        "deployment_check.json",
        "deployment_manifest.json",
        "evidence_manifest.json",
        "homepage_handoffs.json",
        "operations_summary.json",
        "ops_brief.json",
        "ops_brief_deliveries.json",
        "provider_health.json",
        "publish_recovery_executions.json",
        "publish_verifications.json",
        "release_readiness.json",
        "retention_archives.json",
        "source_reviews.json",
        "summary.json",
        "worker_execution_alert_deliveries.json",
        "worker_execution_alerts.json",
        "worker_execution_trends.json",
        "worker_delivery_summary_deliveries.json",
        "worker_delivery_summaries.json",
    }
    assert {path.name for path in output_dir.glob("*.json")} == expected_files
    assert bundle.summary.git_sha == "test-sha"
    assert bundle.summary.release_status in {"pass", "warn", "fail"}
    readiness = json.loads((output_dir / "release_readiness.json").read_text(encoding="utf-8"))
    deployment_check = json.loads(
        (output_dir / "deployment_check.json").read_text(encoding="utf-8")
    )
    manifest = json.loads((output_dir / "deployment_manifest.json").read_text(encoding="utf-8"))
    evidence_manifest = json.loads(
        (output_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    worker_trends = json.loads(
        (output_dir / "worker_execution_trends.json").read_text(encoding="utf-8")
    )
    worker_alerts = json.loads(
        (output_dir / "worker_execution_alerts.json").read_text(encoding="utf-8")
    )
    worker_alert_deliveries = json.loads(
        (output_dir / "worker_execution_alert_deliveries.json").read_text(encoding="utf-8")
    )
    worker_delivery_summaries = json.loads(
        (output_dir / "worker_delivery_summaries.json").read_text(encoding="utf-8")
    )
    worker_summary_deliveries = json.loads(
        (output_dir / "worker_delivery_summary_deliveries.json").read_text(encoding="utf-8")
    )
    source_reviews = json.loads(
        (output_dir / "source_reviews.json").read_text(encoding="utf-8")
    )
    publish_verifications = json.loads(
        (output_dir / "publish_verifications.json").read_text(encoding="utf-8")
    )
    publish_recovery_executions = json.loads(
        (output_dir / "publish_recovery_executions.json").read_text(encoding="utf-8")
    )
    provider_health = json.loads(
        (output_dir / "provider_health.json").read_text(encoding="utf-8")
    )
    ops_brief = json.loads((output_dir / "ops_brief.json").read_text(encoding="utf-8"))
    ops_brief_deliveries = json.loads(
        (output_dir / "ops_brief_deliveries.json").read_text(encoding="utf-8")
    )
    retention_archives = json.loads(
        (output_dir / "retention_archives.json").read_text(encoding="utf-8")
    )
    assert readiness["deployment"]["runtime"]["database_engine"] == "sqlite"
    assert deployment_check["profile"] == "production"
    assert "environment_template" in {check["name"] for check in deployment_check["checks"]}
    assert "checks" in manifest
    assert "operator_api_key" not in json.dumps(manifest).casefold()
    assert set(bundle.summary.artifact_files) == expected_files
    assert evidence_manifest["metadata"]["bundle_type"] == "release_evidence"
    assert set(evidence_manifest["artifacts"]) == expected_files - {"evidence_manifest.json"}
    assert worker_trends["summary"]["execution_count"] == 0
    assert worker_trends["summary"]["top_failure_reasons"] == []
    assert worker_alerts["severity"] == "info"
    assert worker_alert_deliveries == []
    assert worker_summary_deliveries == []
    assert worker_delivery_summaries["total"] == 0
    assert source_reviews["total_runs"] == 0
    assert source_reviews["total_decisions"] == 0
    assert publish_verifications["total"] == 0
    assert publish_verifications["drift_count"] == 0
    assert publish_recovery_executions["total"] == 0
    assert {item["category"] for item in provider_health["items"]} >= {
        "research",
        "generator",
        "publisher",
    }
    assert bundle.worker_execution_alerts["severity"] == "info"
    assert bundle.source_reviews.total_decisions == 0
    assert bundle.publish_verifications.total == 0
    assert bundle.publish_recovery_executions.total == 0
    assert bundle.provider_health.status in {"pass", "warn", "fail"}
    assert ops_brief["status"] in {"pass", "warn", "fail"}
    assert ops_brief_deliveries == []
    assert retention_archives["total"] == 0
    assert bundle.ops_brief.status in {"pass", "warn", "fail"}
    assert bundle.ops_brief.recommended_actions
    assert bundle.ops_brief_deliveries == []
    assert bundle.retention_archives.total == 0
    assert bundle.worker_execution_alert_deliveries == []
    assert bundle.worker_delivery_summary_deliveries == []
    assert bundle.worker_execution_trends["summary"]["execution_count"] == 0
    assert bundle.worker_delivery_summaries.total == 0
    summary_sha = hashlib.sha256((output_dir / "summary.json").read_bytes()).hexdigest()
    assert evidence_manifest["artifacts"]["summary.json"]["sha256"] == summary_sha


def test_release_evidence_indexes_publish_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    settings = Settings()
    pipeline = build_pipeline(settings)
    service = build_review_service(settings)
    result = pipeline.run(RunRequest(topic="Release evidence publish verification"))
    service.approve(result.run.id, reviewer="zack")
    service.publish(result.run.id)
    output_dir = tmp_path / "release-evidence"

    bundle = generate_release_evidence(output_dir)

    payload = json.loads(
        (output_dir / "publish_verifications.json").read_text(encoding="utf-8")
    )
    evidence_manifest = json.loads(
        (output_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert bundle.publish_verifications.total == 1
    assert bundle.publish_verifications.verified_count == 1
    assert bundle.publish_verifications.drift_count == 0
    assert bundle.publish_verifications.items[0].run_id == result.run.id
    assert payload["items"][0]["verified"] is True
    assert payload["items"][0]["artifact_path"].endswith("publish-verification.json")
    assert "publish_verifications.json" in bundle.summary.artifact_files
    assert evidence_manifest["artifacts"]["publish_verifications.json"]["media_type"] == (
        "application/json"
    )


def test_release_evidence_indexes_publish_recovery_executions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    settings = Settings()
    pipeline = build_pipeline(settings)
    service = build_review_service(settings)
    result = pipeline.run(RunRequest(topic="Release evidence publish recovery"))
    service.approve(result.run.id, reviewer="zack")
    service.publish(result.run.id)
    receipt = service.publish_receipt(result.run.id)
    assert receipt is not None
    Path(receipt.file_changes[0].path).write_text("manual drift", encoding="utf-8")
    service.execute_publish_recovery(
        result.run.id,
        action="rollback",
        actor="zack",
        notes="Evidence recovery.",
    )
    output_dir = tmp_path / "release-evidence"

    bundle = generate_release_evidence(output_dir)

    payload = json.loads(
        (output_dir / "publish_recovery_executions.json").read_text(encoding="utf-8")
    )
    evidence_manifest = json.loads(
        (output_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert bundle.publish_recovery_executions.total == 1
    assert bundle.publish_recovery_executions.completed_count == 1
    assert bundle.publish_recovery_executions.error_count == 0
    assert bundle.publish_recovery_executions.items[0].run_id == result.run.id
    assert payload["items"][0]["action"] == "rollback"
    assert payload["items"][0]["actor"] == "zack"
    assert payload["items"][0]["artifact_path"].endswith("publish-recovery-execution.json")
    assert "publish_recovery_executions.json" in bundle.summary.artifact_files
    assert evidence_manifest["artifacts"]["publish_recovery_executions.json"][
        "media_type"
    ] == "application/json"


def test_release_evidence_indexes_content_distribution_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(site_dir))
    distribution_manifest = site_dir / "content-distribution-manifest.json"
    distribution_manifest.write_text(
        json.dumps(
            {
                "manifest_type": "content_distribution",
                "output_dir": str(site_dir),
                "assets": [
                    {"relative_path": "feed.xml", "sha256": "feed-sha"},
                    {"relative_path": "promotion-brief.md", "sha256": "brief-sha"},
                ],
                "git": {"is_repository": True, "branch": "main", "dirty": True},
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "release-evidence"

    bundle = generate_release_evidence(output_dir)

    payload = json.loads((output_dir / "content_distribution.json").read_text(encoding="utf-8"))
    evidence_manifest = json.loads(
        (output_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    expected_sha = hashlib.sha256(distribution_manifest.read_bytes()).hexdigest()
    assert bundle.content_distribution.total == 1
    assert bundle.content_distribution.items[0].manifest_path == (
        "content-distribution-manifest.json"
    )
    assert bundle.content_distribution.items[0].asset_count == 2
    assert bundle.content_distribution.items[0].sha256 == expected_sha
    assert payload["items"][0]["git"]["branch"] == "main"
    assert "content_distribution.json" in bundle.summary.artifact_files
    assert evidence_manifest["artifacts"]["content_distribution.json"]["media_type"] == (
        "application/json"
    )


def test_release_evidence_indexes_worker_delivery_summaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    receipt_dir = job_execution_dir(artifact_root)
    report = JobExecutionReport(
        name="delivery-calendar",
        total=1,
        succeeded=1,
        failed=0,
        content_assets_status="generated",
        release_evidence_status="warn",
        results=[
            JobRunResult(
                job_name="daily-ai",
                topic="Daily AI publishing",
                publish=True,
                run_id="run-delivery",
                status="published",
                published_url="https://example.com/daily-ai",
            )
        ],
    )
    write_job_execution_report(report, receipt_dir)
    write_job_execution_delivery_summary(report)
    notify_worker_delivery_summary(report)
    output_dir = tmp_path / "release-evidence"

    bundle = generate_release_evidence(output_dir)

    payload = json.loads(
        (output_dir / "worker_delivery_summaries.json").read_text(encoding="utf-8")
    )
    assert payload["total"] == 1
    assert payload["items"][0]["execution_id"] == report.execution_id
    assert payload["items"][0]["published_runs"] == 1
    assert payload["items"][0]["content_assets_status"] == "generated"
    assert payload["items"][0]["release_evidence_status"] == "warn"
    assert payload["items"][0]["markdown_path"].endswith("-delivery-summary.md")
    deliveries = json.loads(
        (output_dir / "worker_delivery_summary_deliveries.json").read_text(encoding="utf-8")
    )
    assert deliveries[0]["execution_id"] == report.execution_id
    assert deliveries[0]["status"] == "skipped"
    assert bundle.worker_delivery_summaries.total == 1
    assert bundle.worker_delivery_summary_deliveries[0]["execution_id"] == report.execution_id
    assert "worker_delivery_summaries.json" in bundle.summary.artifact_files
    assert "worker_delivery_summary_deliveries.json" in bundle.summary.artifact_files


def test_release_evidence_indexes_homepage_handoff_bundles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    run_artifact_dir = artifact_root / "run-homepage"
    run_artifact_dir.mkdir(parents=True)
    handoff_path = run_artifact_dir / "run-homepage-homepage-handoff.zip"
    handoff_path.write_bytes(b"homepage handoff evidence")
    output_dir = tmp_path / "release-evidence"

    bundle = generate_release_evidence(output_dir)

    handoffs = json.loads((output_dir / "homepage_handoffs.json").read_text(encoding="utf-8"))
    evidence_manifest = json.loads(
        (output_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    expected_sha = hashlib.sha256(handoff_path.read_bytes()).hexdigest()
    assert bundle.homepage_handoffs.total == 1
    assert bundle.homepage_handoffs.items[0].run_id == "run-homepage"
    assert bundle.homepage_handoffs.items[0].artifact_path == (
        "run-homepage/run-homepage-homepage-handoff.zip"
    )
    assert bundle.homepage_handoffs.items[0].sha256 == expected_sha
    assert handoffs["items"][0]["sha256"] == expected_sha
    assert "homepage_handoffs.json" in bundle.summary.artifact_files
    assert evidence_manifest["artifacts"]["homepage_handoffs.json"]["media_type"] == (
        "application/json"
    )


def test_release_evidence_indexes_source_review_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    run_artifact_dir = artifact_root / "20260605-source-review-run-abc123"
    run_artifact_dir.mkdir(parents=True)
    (run_artifact_dir / "source-review.json").write_text(
        json.dumps(
            [
                {
                    "source_key": "https://example.com/keep",
                    "source_title": "Keep",
                    "decision": "include",
                    "reviewer": "zack",
                    "notes": "Good evidence.",
                    "decided_at": "2026-06-05T00:00:00Z",
                },
                {
                    "source_key": "https://example.com/drop",
                    "source_title": "Drop",
                    "decision": "exclude",
                    "reviewer": "zack",
                    "notes": "Too generic.",
                    "decided_at": "2026-06-05T00:01:00Z",
                },
                {
                    "source_key": "https://example.com/check",
                    "source_title": "Check",
                    "decision": "needs_review",
                    "reviewer": "zack",
                    "notes": "Needs owner confirmation.",
                    "decided_at": "2026-06-05T00:02:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "release-evidence"

    bundle = generate_release_evidence(output_dir)

    payload = json.loads((output_dir / "source_reviews.json").read_text(encoding="utf-8"))
    evidence_manifest = json.loads(
        (output_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert bundle.source_reviews.total_runs == 1
    assert bundle.source_reviews.total_decisions == 3
    assert bundle.source_reviews.include_count == 1
    assert bundle.source_reviews.exclude_count == 1
    assert bundle.source_reviews.needs_review_count == 1
    assert bundle.source_reviews.items[0].run_id == "abc123"
    assert payload["items"][0]["artifact_path"] == (
        "20260605-source-review-run-abc123/source-review.json"
    )
    assert "source_reviews.json" in bundle.summary.artifact_files
    assert evidence_manifest["artifacts"]["source_reviews.json"]["media_type"] == (
        "application/json"
    )


def test_release_evidence_includes_worker_execution_trends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    settings = Settings()
    receipt = JobExecutionReport(
        name="release-evidence-worker",
        total=1,
        succeeded=1,
        failed=0,
        release_evidence_path="release-evidence",
        results=[
            JobRunResult(
                job_name="published",
                topic="Published worker content",
                publish=True,
                run_id="run-worker",
                status="published",
                published_url="https://example.com/worker",
            )
        ],
    )
    write_job_execution_report(receipt, job_execution_dir(settings.artifact_root))
    output_dir = tmp_path / "release-evidence"

    bundle = generate_release_evidence(output_dir)

    trends = json.loads(
        (output_dir / "worker_execution_trends.json").read_text(encoding="utf-8")
    )
    evidence_manifest = json.loads(
        (output_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert bundle.worker_execution_trends["summary"]["execution_count"] == 1
    assert trends["summary"]["published_runs"] == 1
    assert trends["summary"]["top_failure_reasons"] == []
    assert bundle.worker_execution_alerts["action_required"] is False
    assert "worker_execution_trends.json" in bundle.summary.artifact_files
    assert "worker_execution_alerts.json" in bundle.summary.artifact_files
    assert "worker_execution_alert_deliveries.json" in bundle.summary.artifact_files
    assert evidence_manifest["artifacts"]["worker_execution_trends.json"]["media_type"] == (
        "application/json"
    )


def test_release_evidence_includes_latest_release_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    monkeypatch.setenv("CONTENTOPS_GIT_SHA", "approval-sha")
    settings = Settings()
    repository = RunRepository(settings.database_url)
    output_dir = tmp_path / "release-evidence"

    approval = approve_release(
        settings=settings,
        repository=repository,
        review_service=build_review_service(settings),
        request=ReleaseApprovalRequest(
            decision=ReleaseApprovalDecision.APPROVED,
            approver="zack",
            notes="Evidence reviewed.",
        ),
    )
    bundle = generate_release_evidence(output_dir)

    approval_payload = json.loads(
        (output_dir / "release_approval.json").read_text(encoding="utf-8")
    )
    evidence_manifest = json.loads(
        (output_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )

    assert bundle.latest_release_approval is not None
    assert bundle.latest_release_approval.approval_id == approval.approval_id
    assert "release_approval.json" in bundle.summary.artifact_files
    assert approval_payload["approval_id"] == approval.approval_id
    assert evidence_manifest["artifacts"]["release_approval.json"]["media_type"] == (
        "application/json"
    )


def test_create_release_evidence_archive_writes_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setenv("CONTENTOPS_GIT_SHA", "archive-sha")
    bundle = generate_release_evidence(tmp_path / "release-evidence")
    archive_path = create_release_evidence_archive(bundle, tmp_path / "release-evidence.zip")

    assert archive_path.exists()
    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert names == set(bundle.summary.artifact_files)
        summary = json.loads(archive.read("summary.json"))
        assert summary["git_sha"] == "archive-sha"


def test_generate_release_evidence_mirrors_to_s3_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads: list[dict[str, object]] = []

    class FakeS3Client:
        def upload_file(
            self,
            filename: str,
            bucket: str,
            key: str,
            ExtraArgs: dict[str, str],
        ) -> None:
            uploads.append(
                {
                    "filename": filename,
                    "bucket": bucket,
                    "key": key,
                    "extra_args": ExtraArgs,
                }
            )

    class FakeBoto3:
        @staticmethod
        def client(service: str) -> FakeS3Client:
            assert service == "s3"
            return FakeS3Client()

    monkeypatch.setattr("contentops_core.artifacts.importlib.import_module", lambda name: FakeBoto3)
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CONTENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'contentops.db'}")
    monkeypatch.setenv("CONTENTOPS_SITE_OUTPUT_DIR", str(tmp_path / "site"))
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_STORE_PROVIDER", "s3")
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_S3_BUCKET", "evidence-bucket")
    monkeypatch.setenv("CONTENTOPS_ARTIFACT_S3_PREFIX", "contentops-prod")
    monkeypatch.setenv("GITHUB_SHA", "release-sha")
    output_dir = tmp_path / "release-evidence"

    generate_release_evidence(output_dir)

    mirror_log = json.loads((output_dir / "s3-mirror-log.json").read_text(encoding="utf-8"))
    assert uploads
    assert {item["bucket"] for item in uploads} == {"evidence-bucket"}
    assert "contentops-prod/release-evidence/release-sha/summary.json" in {
        item["key"] for item in uploads
    }
    assert "contentops-prod/release-evidence/release-sha/deployment_check.json" in {
        item["key"] for item in uploads
    }
    assert mirror_log[0]["provider"] == "s3"
    assert {record["status"] for record in mirror_log} == {"mirrored"}
