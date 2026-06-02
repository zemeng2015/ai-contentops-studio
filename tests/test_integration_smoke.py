from __future__ import annotations

import os
from pathlib import Path

import pytest
from contentops_core.models import (
    Claim,
    ContentPlan,
    Draft,
    EvaluationReport,
    ResearchPacket,
    RunRecord,
    RunRequest,
    RunStatus,
    Source,
)
from contentops_core.settings import Settings
from contentops_providers.openai_generator import OpenAIResponsesGenerator
from contentops_providers.research import FeedResearchProvider, SearchResearchProvider
from contentops_publishing.homepage import HomepagePublisher


def _integration_enabled() -> bool:
    return os.getenv("CONTENTOPS_RUN_INTEGRATION") == "1"


def _skip_unless_integration_enabled() -> None:
    if not _integration_enabled():
        pytest.skip("Set CONTENTOPS_RUN_INTEGRATION=1 to run live provider smoke tests.")


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"Set {name} to run this live provider smoke test.")
    return value


@pytest.mark.integration
def test_live_feed_research_provider_discovers_ai_sources() -> None:
    _skip_unless_integration_enabled()
    settings = Settings()
    provider = FeedResearchProvider(
        feeds=[settings.research_feeds.split(",", maxsplit=1)[0]],
        max_sources=2,
        retry_attempts=1,
    )

    packet = provider.collect(RunRequest(topic="AI agent evaluation"))

    assert packet.sources
    assert not packet.sources[0].title.startswith("Unavailable feed:")
    assert packet.sources[0].url is not None
    assert packet.sources[0].extraction_status == "feed"


@pytest.mark.integration
def test_live_search_research_provider_returns_external_sources() -> None:
    _skip_unless_integration_enabled()
    api_key = _require_env("CONTENTOPS_RESEARCH_SEARCH_API_KEY")
    settings = Settings(research_search_api_key=api_key)
    provider = SearchResearchProvider(
        endpoint=settings.research_search_endpoint,
        api_key=api_key,
        max_sources=2,
        enrich_results=False,
        retry_attempts=1,
    )

    packet = provider.collect(RunRequest(topic="LLM evaluation observability"))

    assert packet.sources
    assert not packet.sources[0].title.startswith("Search failed for:")
    assert packet.sources[0].url is not None
    assert packet.sources[0].extraction_status == "search"


@pytest.mark.integration
def test_live_openai_generator_returns_generation_receipt() -> None:
    _skip_unless_integration_enabled()
    api_key = _require_env("CONTENTOPS_OPENAI_API_KEY")
    settings = Settings(openai_api_key=api_key)
    generator = OpenAIResponsesGenerator(
        api_key=api_key,
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
        retry_attempts=1,
        fallback_on_failure=False,
    )

    draft = generator.generate(_sample_research_packet(), _sample_content_plan())
    receipt = generator.generation_receipt()

    assert draft.markdown.strip()
    assert receipt is not None
    assert receipt.provider == "openai"
    assert receipt.model == settings.openai_model
    assert receipt.status == "completed"
    assert receipt.fallback_used is False


@pytest.mark.integration
def test_configured_homepage_publisher_can_plan_real_target(tmp_path: Path) -> None:
    _skip_unless_integration_enabled()
    homepage_path = Path(_require_env("CONTENTOPS_HOMEPAGE_REPO_PATH"))
    if not homepage_path.exists():
        pytest.skip(f"Homepage repository does not exist: {homepage_path}")
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "eval-report.json").write_text(
        '{"publish_ready": true}',
        encoding="utf-8",
    )
    run = RunRecord(
        topic="Integration homepage plan",
        slug="integration-homepage-plan",
        status=RunStatus.NEEDS_REVIEW,
        artifact_dir=artifact_dir,
    )

    plan = HomepagePublisher(
        homepage_path,
        Settings().homepage_public_base_url,
    ).plan(run, _sample_draft(), _sample_report())

    assert plan.provider == "homepage"
    assert plan.target_url.endswith("/posts/integration-homepage-plan.html")
    assert [item.action for item in plan.items] == ["create", "create", "update"]
    assert plan.ready is True


def _sample_research_packet() -> ResearchPacket:
    return ResearchPacket(
        topic="LLM evaluation observability",
        sources=[
            Source(
                title="Evaluation operations guide",
                url="https://example.com/eval-ops",
                publisher="example.com",
                summary=(
                    "A source about LLM evaluation, workflow observability, review queues, "
                    "and production release gates."
                ),
                credibility=0.9,
                extraction_status="integration_sample",
            )
        ],
        claims=[
            Claim(
                text="LLM systems need observable evaluation gates before release.",
                source_title="Evaluation operations guide",
                confidence=0.9,
            )
        ],
        engineering_signals=["Evaluation data should be persisted for release review."],
        risks=["Unreviewed generated content can drift away from source evidence."],
        project_implications=["Expose generation receipts and scorecards in the dashboard."],
    )


def _sample_content_plan() -> ContentPlan:
    return ContentPlan(
        title="LLM Evaluation Observability",
        slug="llm-evaluation-observability",
        audience="Applied AI engineering teams",
        thesis="Production LLM systems need observable evaluation and release gates.",
        outline=["Why observability matters", "Evaluation receipts", "Release review"],
        keywords=["llm", "evaluation", "observability"],
    )


def _sample_draft() -> Draft:
    return Draft(
        title="Integration Homepage Plan",
        slug="integration-homepage-plan",
        markdown="# Integration Homepage Plan",
        html="<html><head></head><body><h1>Integration Homepage Plan</h1></body></html>",
    )


def _sample_report() -> EvaluationReport:
    return EvaluationReport(
        groundedness=0.9,
        source_coverage=0.9,
        source_quality=0.9,
        career_relevance=0.9,
        technical_depth=0.9,
        publish_ready=True,
        findings=["ready"],
    )
