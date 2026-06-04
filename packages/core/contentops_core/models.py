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


class GenerationReceipt(BaseModel):
    provider: str
    model: str
    status: str
    attempts: int = Field(ge=0, default=1)
    fallback_used: bool = False
    input_tokens: int | None = Field(ge=0, default=None)
    output_tokens: int | None = Field(ge=0, default=None)
    total_tokens: int | None = Field(ge=0, default=None)
    error: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    plan_metadata: dict[str, Any] = Field(default_factory=dict)
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


class PublishVerificationItem(BaseModel):
    path: str
    expected_sha256: str | None = None
    actual_sha256: str | None = None
    exists: bool
    matches_receipt: bool
    message: str


class PublishVerificationReport(BaseModel):
    run_id: str
    provider: str
    url: str
    verified: bool
    items: list[PublishVerificationItem]
    verified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PublishedContentItem(BaseModel):
    run_id: str
    topic: str
    slug: str
    title: str
    url: str
    provider: str
    published_at: datetime
    publish_ready: bool
    groundedness: float
    source_coverage: float
    source_quality: float
    career_relevance: float
    technical_depth: float


class PublishedContentListResponse(BaseModel):
    items: list[PublishedContentItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class AuditEvent(BaseModel):
    run_id: str
    action: str
    actor: str = "system"
    previous_status: RunStatus | None = None
    new_status: RunStatus | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AuditEventListResponse(BaseModel):
    items: list[AuditEvent]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    action_counts: dict[str, int] = Field(default_factory=dict)


class NotificationDelivery(BaseModel):
    delivery_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    run_id: str
    action: str
    provider: str
    status: str
    endpoint: str | None = None
    status_code: int | None = None
    error: str | None = None
    delivered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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


class RunScorecard(BaseModel):
    run_id: str
    status: RunStatus
    topic: str
    slug: str
    published_url: str | None = None
    source_count: int = 0
    total_duration_ms: int | None = None
    latency_slo_ms: int
    min_source_count: int
    publish_ready: bool | None = None
    groundedness: float | None = None
    source_coverage: float | None = None
    source_quality: float | None = None
    career_relevance: float | None = None
    technical_depth: float | None = None
    quality_pass: bool | None = None
    latency_slo_pass: bool | None = None
    sources_slo_pass: bool
    overall_pass: bool
    warnings: list[str] = Field(default_factory=list)


class ScorecardListResponse(BaseModel):
    items: list[RunScorecard]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    quality_pass_rate: float = Field(ge=0, le=1)
    avg_duration_ms: int | None = None


class RunCostReport(BaseModel):
    run_id: str
    status: RunStatus
    topic: str
    slug: str
    model: str
    estimated_input_tokens: int = Field(ge=0)
    estimated_output_tokens: int = Field(ge=0)
    estimated_total_tokens: int = Field(ge=0)
    token_budget: int = Field(ge=1)
    budget_pass: bool
    warnings: list[str] = Field(default_factory=list)


class CostReportListResponse(BaseModel):
    items: list[RunCostReport]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    budget_pass_rate: float = Field(ge=0, le=1)
    estimated_total_tokens: int = Field(ge=0)


class IncidentSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class RunIncidentSignal(BaseModel):
    severity: IncidentSeverity
    category: str
    message: str
    artifact: str | None = None


class RunIncidentReport(BaseModel):
    run_id: str
    status: RunStatus
    topic: str
    severity: IncidentSeverity
    requires_action: bool
    signals: list[RunIncidentSignal] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IncidentReportListResponse(BaseModel):
    items: list[RunIncidentReport]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    action_required: int = Field(ge=0)


class OperationsSummary(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    window_size: int = Field(ge=1)
    total_runs: int = Field(ge=0)
    status_counts: dict[str, int] = Field(default_factory=dict)
    review_queue_depth: int = Field(ge=0)
    approved_ready_count: int = Field(ge=0)
    published_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    action_required_incidents: int = Field(ge=0)
    critical_incidents: int = Field(ge=0)
    warning_incidents: int = Field(ge=0)
    quality_pass_rate: float = Field(ge=0, le=1)
    budget_pass_rate: float = Field(ge=0, le=1)
    avg_duration_ms: int | None = None
    estimated_total_tokens: int = Field(ge=0)


class OpsTrendBucket(BaseModel):
    date: str
    run_count: int = Field(ge=0)
    published_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    review_queue_count: int = Field(ge=0)
    action_required_incidents: int = Field(ge=0)
    quality_pass_rate: float = Field(ge=0, le=1)
    budget_pass_rate: float = Field(ge=0, le=1)
    avg_duration_ms: int | None = None
    estimated_total_tokens: int = Field(ge=0)


class OpsTrendReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    days: int = Field(ge=1)
    window_size: int = Field(ge=1)
    buckets: list[OpsTrendBucket]
    summary: OperationsSummary


class RetentionCandidate(BaseModel):
    run_id: str
    status: RunStatus
    topic: str
    updated_at: datetime
    artifact_dir: str
    artifact_count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    reason: str


class RetentionReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    retention_days: int = Field(ge=0)
    total_runs_scanned: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    candidate_size_bytes: int = Field(ge=0)
    candidates: list[RetentionCandidate] = Field(default_factory=list)


class ComponentCheck(BaseModel):
    name: str
    status: str
    message: str
    fields: dict[str, Any] = Field(default_factory=dict)


class ConfigAuditItem(BaseModel):
    name: str
    category: str
    status: str
    required: bool = False
    configured: bool = False
    secret: bool = False
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class ConfigAuditReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str
    items: list[ConfigAuditItem]
    redacted: bool = True
    summary: dict[str, int] = Field(default_factory=dict)


class SystemStatus(BaseModel):
    status: str
    checks: list[ComponentCheck]


class DeploymentCapability(BaseModel):
    name: str
    status: str
    evidence: list[str] = Field(default_factory=list)


class DeploymentManifest(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str
    runtime: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)
    operations: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[DeploymentCapability] = Field(default_factory=list)
    checks: list[ComponentCheck] = Field(default_factory=list)


class ReleaseGateCheck(BaseModel):
    name: str
    status: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class ReleaseReadinessReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str
    can_release: bool
    checks: list[ReleaseGateCheck]
    operations: OperationsSummary
    deployment: DeploymentManifest


class ReleaseEvidenceSummary(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    git_sha: str | None = None
    doctor_status: str
    release_status: str
    can_release: bool
    artifact_files: list[str] = Field(default_factory=list)


class HomepageHandoffEvidenceItem(BaseModel):
    run_id: str
    artifact_path: str
    size_bytes: int
    sha256: str
    updated_at: datetime


class HomepageHandoffEvidence(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    total: int
    items: list[HomepageHandoffEvidenceItem] = Field(default_factory=list)


class ReleaseEvidenceBundle(BaseModel):
    summary: ReleaseEvidenceSummary
    doctor: SystemStatus
    deployment_manifest: DeploymentManifest
    operations_summary: OperationsSummary
    release_readiness: ReleaseReadinessReport
    deployment_check: DeploymentCheckReport
    homepage_handoffs: HomepageHandoffEvidence
    latest_release_approval: ReleaseApprovalRecord | None = None


class DeploymentCheckItem(BaseModel):
    name: str
    status: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class DeploymentCheckReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    profile: str
    status: str
    can_deploy: bool
    checks: list[DeploymentCheckItem]
    deployment: DeploymentManifest
    release_readiness: ReleaseReadinessReport


class ReleaseApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ReleaseApprovalRequest(BaseModel):
    decision: ReleaseApprovalDecision
    approver: str = "operator"
    notes: str = ""
    force: bool = False
    window_size: int = Field(ge=1, default=100)


class ReleaseApprovalRecord(BaseModel):
    approval_id: str
    release_id: str
    decision: ReleaseApprovalDecision
    approver: str
    notes: str = ""
    force: bool = False
    git_sha: str | None = None
    release_status: str
    deployment_status: str
    can_release: bool
    can_deploy: bool
    evidence_sha256: str
    evidence_files: list[str] = Field(default_factory=list)
    approved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReleaseApprovalListResponse(BaseModel):
    items: list[ReleaseApprovalRecord]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class ReleaseGateItem(BaseModel):
    name: str
    status: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class ReleaseGateReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str
    can_deploy: bool
    git_sha: str | None = None
    checks: list[ReleaseGateItem]
    release_evidence: ReleaseEvidenceSummary
    latest_release_approval: ReleaseApprovalRecord | None = None
    config_audit: ConfigAuditReport | None = None


class ReleaseGateListResponse(BaseModel):
    items: list[ReleaseGateReport]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


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
    metadata: dict[str, str] = Field(default_factory=dict)


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


class ArtifactMirrorRecord(BaseModel):
    run_id: str
    artifact_name: str
    provider: str
    bucket: str
    key: str
    content_type: str
    status: str
    error: str | None = None
    mirrored_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
