from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from slugify import slugify


class RunStatus(StrEnum):
    CREATED = "created"
    RESEARCHING = "researching"
    PLANNING = "planning"
    DRAFTING = "drafting"
    EVALUATING = "evaluating"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class Source(BaseModel):
    title: str
    url: str | None = None
    canonical_url: str | None = None
    publisher: str = "unknown"
    summary: str
    credibility: float = Field(ge=0, le=1, default=0.75)
    extraction_status: str = "synthetic"
    extraction_quality: float = Field(ge=0, le=1, default=0.75)
    content_length: int = Field(ge=0, default=0)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Claim(BaseModel):
    text: str
    source_title: str
    confidence: float = Field(ge=0, le=1, default=0.8)


class ResearchPacket(BaseModel):
    topic: str
    sources: list[Source]
    claims: list[Claim]
    engineering_signals: list[str]
    risks: list[str]
    project_implications: list[str]


class SourceAssessment(BaseModel):
    source_title: str
    canonical_url: str | None = None
    publisher: str
    discovery_method: str
    score: float = Field(ge=0, le=1)
    grade: str
    reasons: list[str]
    recommendation: str


class SourceAuditReport(BaseModel):
    topic: str
    source_count: int
    average_score: float = Field(ge=0, le=1)
    strong_count: int = 0
    review_count: int = 0
    failed_count: int = 0
    assessments: list[SourceAssessment]


class ContentPlan(BaseModel):
    title: str
    slug: str
    audience: str
    thesis: str
    outline: list[str]
    keywords: list[str]


class Draft(BaseModel):
    title: str
    slug: str
    markdown: str
    html: str


class EvaluationReport(BaseModel):
    groundedness: float = Field(ge=0, le=1)
    source_coverage: float = Field(ge=0, le=1)
    source_quality: float = Field(ge=0, le=1, default=1.0)
    career_relevance: float = Field(ge=0, le=1)
    technical_depth: float = Field(ge=0, le=1)
    publish_ready: bool
    findings: list[str]


class PublishPlanItem(BaseModel):
    path: str
    action: str
    exists: bool
    description: str


class PublishPlan(BaseModel):
    provider: str
    target_url: str
    ready: bool
    items: list[PublishPlanItem]
    warnings: list[str] = Field(default_factory=list)


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalRecord(BaseModel):
    run_id: str
    decision: ApprovalDecision
    reviewer: str
    notes: str = ""
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewBatchRequest(BaseModel):
    run_ids: list[str] = Field(min_length=1)
    reviewer: str = "operator"
    notes: str = ""


class ReviewActionResult(BaseModel):
    run_id: str
    action: str
    status: str
    new_status: RunStatus | None = None
    error: str | None = None


class ReviewBatchResult(BaseModel):
    action: str
    results: list[ReviewActionResult]


class PublishFileChange(BaseModel):
    path: str
    action: str
    existed_before: bool
    exists_after: bool
    before_sha256: str | None = None
    after_sha256: str | None = None
    backup_artifact: str | None = None
    rollback_hint: str


class PublishReceipt(BaseModel):
    run_id: str
    provider: str
    url: str
    plan_items: list[PublishPlanItem]
    file_changes: list[PublishFileChange] = Field(default_factory=list)
    approval: ApprovalRecord | None = None
    force: bool = False
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PublishRollbackResult(BaseModel):
    run_id: str
    restored_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    skipped_files: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    rolled_back_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AuditEvent(BaseModel):
    run_id: str
    action: str
    actor: str = "system"
    previous_status: RunStatus | None = None
    new_status: RunStatus | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TraceEvent(BaseModel):
    timestamp: datetime
    step: str
    status: str
    fields: dict[str, Any] = Field(default_factory=dict)


class StepMetric(BaseModel):
    step: str
    status: str
    duration_ms: int | None = None
    fields: dict[str, Any] = Field(default_factory=dict)


class RunMetrics(BaseModel):
    run_id: str
    status: RunStatus
    total_duration_ms: int | None = None
    source_count: int = 0
    publish_ready: bool | None = None
    step_metrics: list[StepMetric]


class ComponentCheck(BaseModel):
    name: str
    status: str
    message: str
    fields: dict[str, Any] = Field(default_factory=dict)


class SystemStatus(BaseModel):
    status: str
    checks: list[ComponentCheck]


class SourceOverlap(BaseModel):
    base_count: int
    candidate_count: int
    shared_count: int
    base_only: list[str] = Field(default_factory=list)
    candidate_only: list[str] = Field(default_factory=list)


class RunComparison(BaseModel):
    base_run_id: str
    candidate_run_id: str
    base_topic: str
    candidate_topic: str
    same_topic: bool
    duration_delta_ms: int | None
    source_count_delta: int
    publish_ready_changed: bool
    evaluation_deltas: dict[str, float | None]
    source_overlap: SourceOverlap
    summary: list[str]


class RunRequest(BaseModel):
    topic: str
    source_urls: list[str] = Field(default_factory=list)
    publish: bool = False


class RunRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    topic: str
    slug: str
    status: RunStatus = RunStatus.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    artifact_dir: Path
    published_url: str | None = None
    error: str | None = None

    @classmethod
    def create(cls, request: RunRequest, artifact_root: Path) -> RunRecord:
        slug = slugify(request.topic)[:72] or "content-run"
        run_id = uuid4().hex[:12]
        return cls(
            id=run_id,
            topic=request.topic,
            slug=slug,
            artifact_dir=artifact_root / f"{datetime.now(UTC):%Y%m%d}-{slug}-{run_id}",
        )

    def touch(self, status: RunStatus) -> RunRecord:
        self.status = status
        self.updated_at = datetime.now(UTC)
        return self


class RunListResponse(BaseModel):
    items: list[RunRecord]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class ArtifactMetadata(BaseModel):
    name: str
    size_bytes: int = Field(ge=0)
    media_type: str
    sha256: str
    updated_at: datetime


class ArtifactManifest(BaseModel):
    run_id: str
    artifacts: dict[str, ArtifactMetadata] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
