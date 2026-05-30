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


class ArtifactManifest(BaseModel):
    run_id: str
    artifacts: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
