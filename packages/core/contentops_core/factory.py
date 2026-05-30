from __future__ import annotations

from contentops_evaluators.quality import HeuristicContentEvaluator
from contentops_providers.research import LocalResearchProvider
from contentops_publishing.static_site import StaticSitePublisher

from contentops_core.artifacts import ArtifactStore
from contentops_core.generator import ContentGenerator
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
        research_provider=LocalResearchProvider(),
        planner=ContentPlanner(),
        generator=ContentGenerator(),
        evaluator=HeuristicContentEvaluator(settings.min_publish_score),
        publisher=StaticSitePublisher(settings.site_output_dir, settings.public_base_url),
    )

