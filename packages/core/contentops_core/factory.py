from __future__ import annotations

from contentops_evaluators.quality import HeuristicContentEvaluator
from contentops_providers.openai_generator import OpenAIResponsesGenerator
from contentops_providers.research import (
    HybridResearchProvider,
    LocalResearchProvider,
    URLResearchProvider,
)
from contentops_publishing.homepage import HomepagePublisher
from contentops_publishing.static_site import StaticSitePublisher

from contentops_core.artifacts import ArtifactStore
from contentops_core.generator import ContentGenerator, DraftGenerator
from contentops_core.pipeline import ContentOpsPipeline
from contentops_core.planner import ContentPlanner
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings


def build_pipeline(settings: Settings | None = None) -> ContentOpsPipeline:
    settings = settings or Settings()
    repository = RunRepository(settings.database_url)
    artifact_store = ArtifactStore(settings.artifact_root)
    return ContentOpsPipeline(
        repository=repository,
        artifact_store=artifact_store,
        research_provider=_build_research_provider(settings),
        planner=ContentPlanner(),
        generator=_build_generator(settings),
        evaluator=HeuristicContentEvaluator(settings.min_publish_score),
        publisher=_build_publisher(settings),
    )


def _build_research_provider(
    settings: Settings,
) -> LocalResearchProvider | URLResearchProvider | HybridResearchProvider:
    if settings.research_provider == "local":
        return LocalResearchProvider()
    if settings.research_provider == "url":
        return URLResearchProvider()
    return HybridResearchProvider()


def _build_generator(settings: Settings) -> DraftGenerator:
    if settings.generator_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("CONTENTOPS_OPENAI_API_KEY is required for OpenAI generation.")
        return OpenAIResponsesGenerator(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
    return ContentGenerator()


def _build_publisher(settings: Settings) -> StaticSitePublisher | HomepagePublisher:
    if settings.publisher_provider == "homepage":
        if settings.homepage_repo_path is None:
            raise ValueError("CONTENTOPS_HOMEPAGE_REPO_PATH is required for homepage publishing.")
        return HomepagePublisher(settings.homepage_repo_path, settings.homepage_public_base_url)
    return StaticSitePublisher(settings.site_output_dir, settings.public_base_url)
