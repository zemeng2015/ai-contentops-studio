from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from contentops_core.models import (
    ReleaseApprovalDecision,
    ReleaseApprovalListResponse,
    ReleaseApprovalRecord,
    ReleaseApprovalRequest,
)
from contentops_core.release_evidence import build_release_evidence
from contentops_core.repository import RunRepository
from contentops_core.review import ReviewService
from contentops_core.settings import Settings


def approve_release(
    *,
    settings: Settings,
    repository: RunRepository,
    review_service: ReviewService,
    request: ReleaseApprovalRequest,
    git_sha: str | None = None,
) -> ReleaseApprovalRecord:
    bundle = build_release_evidence(
        settings=settings,
        repository=repository,
        review_service=review_service,
        window_size=request.window_size,
        git_sha=git_sha,
    )
    if request.decision == ReleaseApprovalDecision.APPROVED and not request.force:
        if not bundle.summary.can_release:
            raise ValueError(
                "Release readiness must pass before approval. Use force=true to override."
            )
        if not bundle.deployment_check.can_deploy:
            raise ValueError(
                "Deployment preflight must pass before approval. Use force=true to override."
            )
    record = ReleaseApprovalRecord(
        approval_id=_approval_id(bundle.summary.git_sha),
        release_id=_release_id(bundle.summary.git_sha),
        decision=request.decision,
        approver=request.approver,
        notes=request.notes,
        force=request.force,
        git_sha=bundle.summary.git_sha,
        release_status=bundle.summary.release_status,
        deployment_status=bundle.deployment_check.status,
        can_release=bundle.summary.can_release,
        can_deploy=bundle.deployment_check.can_deploy,
        evidence_sha256=_evidence_sha256(bundle.model_dump(mode="json")),
        evidence_files=bundle.summary.artifact_files,
    )
    _write_release_approval(settings.artifact_root, record)
    return record


def list_release_approvals(
    artifact_root: Path,
    *,
    limit: int = 20,
    offset: int = 0,
) -> ReleaseApprovalListResponse:
    records = sorted(
        (_read_release_approval(path) for path in _approval_dir(artifact_root).glob("*.json")),
        key=lambda record: record.approved_at,
        reverse=True,
    )
    return ReleaseApprovalListResponse(
        items=records[offset : offset + limit],
        total=len(records),
        limit=limit,
        offset=offset,
    )


def latest_release_approval(artifact_root: Path) -> ReleaseApprovalRecord | None:
    response = list_release_approvals(artifact_root, limit=1)
    return response.items[0] if response.items else None


def _write_release_approval(artifact_root: Path, record: ReleaseApprovalRecord) -> Path:
    directory = _approval_dir(artifact_root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record.approval_id}.json"
    path.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def _read_release_approval(path: Path) -> ReleaseApprovalRecord:
    return ReleaseApprovalRecord.model_validate_json(path.read_text(encoding="utf-8"))


def _approval_dir(artifact_root: Path) -> Path:
    return artifact_root / "release-approvals"


def _release_id(git_sha: str | None) -> str:
    return _safe_marker(git_sha or "local")


def _approval_id(git_sha: str | None) -> str:
    marker = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{_release_id(git_sha)}-{marker}-{uuid4().hex[:8]}"


def _safe_marker(value: str) -> str:
    return "".join(char if char.isalnum() or char in ".-_" else "-" for char in value)


def _evidence_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
