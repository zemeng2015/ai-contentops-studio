from __future__ import annotations

from contentops_evaluators.quality import HeuristicContentEvaluator
from contentops_providers.openai_generator import OpenAIResponsesGenerator
from contentops_providers.research import (
    DiscoveryResearchProvider,
    FeedResearchProvider,
    GitHubResearchProvider,
    HybridResearchProvider,
    LocalResearchProvider,
    SearchResearchProvider,
    URLResearchProvider,
)
from contentops_publishing.homepage import HomepagePublisher
from contentops_publishing.static_site import StaticSitePublisher

from contentops_core.artifacts import ArtifactStore, ArtifactWriter, S3MirroringArtifactStore
from contentops_core.generator import ContentGenerator, DraftGenerator
from contentops_core.notifications import LocalNotificationPublisher, WebhookNotificationPublisher
from contentops_core.pipeline import ContentOpsPipeline
from contentops_core.planner import ContentPlanner
from contentops_core.repository import RunRepository
from contentops_core.review import ReviewService
from contentops_core.settings import Settings


def build_pipeline(settings: Settings | None = None) -> ContentOpsPipeline:
    settings = settings or Settings()
    repository = RunRepository(settings.database_url)
    artifact_store = _build_artifact_store(settings)
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
) -> (
    LocalResearchProvider
    | URLResearchProvider
    | HybridResearchProvider
    | FeedResearchProvider
    | DiscoveryResearchProvider
    | SearchResearchProvider
    | GitHubResearchProvider
):
    if settings.research_provider == "local":
        return LocalResearchProvider()
    if settings.research_provider == "url":
        return URLResearchProvider(
            retry_attempts=settings.research_retry_attempts,
            retry_backoff_seconds=settings.research_retry_backoff_seconds,
        )
    if settings.research_provider == "feed":
        return FeedResearchProvider(
            feeds=_research_feeds(settings),
            max_sources=settings.research_max_sources,
            retry_attempts=settings.research_retry_attempts,
            retry_backoff_seconds=settings.research_retry_backoff_seconds,
        )
    if settings.research_provider == "search":
        if not settings.research_search_api_key:
            raise ValueError("CONTENTOPS_RESEARCH_SEARCH_API_KEY is required for search research.")
        return SearchResearchProvider(
            endpoint=settings.research_search_endpoint,
            api_key=settings.research_search_api_key,
            max_sources=settings.research_max_sources,
            enrich_results=settings.research_search_enrich,
            retry_attempts=settings.research_retry_attempts,
            retry_backoff_seconds=settings.research_retry_backoff_seconds,
        )
    if settings.research_provider == "github":
        return GitHubResearchProvider(
            api_base_url=settings.research_github_api_base_url,
            token=settings.research_github_token,
            max_items=settings.research_max_sources,
            retry_attempts=settings.research_retry_attempts,
            retry_backoff_seconds=settings.research_retry_backoff_seconds,
        )
    if settings.research_provider == "discovery":
        return DiscoveryResearchProvider(
            feeds=_research_feeds(settings),
            max_sources=settings.research_max_sources,
            retry_attempts=settings.research_retry_attempts,
            retry_backoff_seconds=settings.research_retry_backoff_seconds,
        )
    return HybridResearchProvider(
        retry_attempts=settings.research_retry_attempts,
        retry_backoff_seconds=settings.research_retry_backoff_seconds,
    )


def _research_feeds(settings: Settings) -> list[str]:
    return [feed.strip() for feed in settings.research_feeds.split(",") if feed.strip()]


def _build_artifact_store(settings: Settings) -> ArtifactWriter:
    if settings.artifact_store_provider == "s3":
        if not settings.artifact_s3_bucket:
            raise ValueError("CONTENTOPS_ARTIFACT_S3_BUCKET is required for S3 artifact storage.")
        return S3MirroringArtifactStore(
            root=settings.artifact_root,
            bucket=settings.artifact_s3_bucket,
            prefix=settings.artifact_s3_prefix,
        )
    return ArtifactStore(settings.artifact_root)


def _build_generator(settings: Settings) -> DraftGenerator:
    if settings.generator_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("CONTENTOPS_OPENAI_API_KEY is required for OpenAI generation.")
        return OpenAIResponsesGenerator(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout_seconds=settings.openai_timeout_seconds,
            retry_attempts=settings.openai_retry_attempts,
            retry_backoff_seconds=settings.openai_retry_backoff_seconds,
            fallback_on_failure=settings.openai_fallback_on_failure,
        )
    return ContentGenerator()


def _build_publisher(settings: Settings) -> StaticSitePublisher | HomepagePublisher:
    if settings.publisher_provider == "homepage":
        if settings.homepage_repo_path is None:
            raise ValueError("CONTENTOPS_HOMEPAGE_REPO_PATH is required for homepage publishing.")
        return HomepagePublisher(settings.homepage_repo_path, settings.homepage_public_base_url)
    return StaticSitePublisher(settings.site_output_dir, settings.public_base_url)


def build_review_service(settings: Settings | None = None) -> ReviewService:
    settings = settings or Settings()
    return ReviewService(
        repository=RunRepository(settings.database_url),
        publisher=_build_publisher(settings),
        notifier=_build_notifier(settings),
        latency_slo_ms=settings.latency_slo_ms,
        min_source_count=settings.min_source_count,
        token_budget_per_run=settings.token_budget_per_run,
        model=settings.openai_model if settings.generator_provider == "openai" else "template",
    )


def _build_notifier(
    settings: Settings,
) -> LocalNotificationPublisher | WebhookNotificationPublisher:
    if settings.notification_webhook_url:
        return WebhookNotificationPublisher(
            endpoint=settings.notification_webhook_url,
            timeout_seconds=settings.notification_timeout_seconds,
        )
    return LocalNotificationPublisher()
