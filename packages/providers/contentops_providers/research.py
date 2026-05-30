from __future__ import annotations

from typing import Protocol

from contentops_core.models import Claim, ResearchPacket, RunRequest, Source


class ResearchProvider(Protocol):
    def collect(self, request: RunRequest) -> ResearchPacket:
        """Collect and normalize sources for a content run."""


class LocalResearchProvider:
    """Deterministic research provider for local development and CI.

    Production deployments can replace this with search, GitHub, arXiv, RSS, or internal
    knowledge-base providers while keeping the pipeline contract stable.
    """

    def collect(self, request: RunRequest) -> ResearchPacket:
        topic = request.topic.strip()
        provided_sources = [
            Source(
                title=f"User-provided source {index + 1}",
                url=url,
                publisher="user-input",
                summary=f"Referenced by the operator for research on {topic}.",
                credibility=0.82,
            )
            for index, url in enumerate(request.source_urls)
        ]
        default_sources = [
            Source(
                title="AI engineering pattern library",
                publisher="contentops-local",
                summary=(
                    "Applied AI projects need explicit boundaries between research, planning, "
                    "generation, evaluation, and publishing."
                ),
                credibility=0.78,
            ),
            Source(
                title="Enterprise AI reliability notes",
                publisher="contentops-local",
                summary=(
                    "Teams should evaluate generated content with source coverage, technical "
                    "depth, career relevance, and groundedness before publishing."
                ),
                credibility=0.8,
            ),
            Source(
                title="Portfolio project map",
                publisher="contentops-local",
                summary=(
                    "Zack's portfolio emphasizes RAG systems, LLM evals, data agents, test "
                    "generation, observability, AWS, and production workflows."
                ),
                credibility=0.86,
            ),
        ]
        sources = provided_sources + default_sources
        claims = [
            Claim(
                text=(
                    "A useful AI content tool should keep research, generation, evaluation, "
                    "and publishing as separately inspectable steps."
                ),
                source_title="AI engineering pattern library",
                confidence=0.86,
            ),
            Claim(
                text=(
                    "Content should not be published until source coverage and technical depth "
                    "meet an explicit threshold."
                ),
                source_title="Enterprise AI reliability notes",
                confidence=0.84,
            ),
            Claim(
                text=(
                    "Career-focused content is strongest when it maps industry signals back to "
                    "real portfolio systems."
                ),
                source_title="Portfolio project map",
                confidence=0.88,
            ),
        ]
        return ResearchPacket(
            topic=topic,
            sources=sources,
            claims=claims,
            engineering_signals=[
                "AI workflows are becoming operational systems with artifacts, traces, and gates.",
                "Evaluation should happen before publishing, not after content is already live.",
                "Career content is more credible when it connects trends to implemented projects.",
            ],
            risks=[
                "Unverified generated claims can damage credibility.",
                "A single prompt that owns the full workflow becomes hard to test or govern.",
                "Publishing automation needs review states and rollback-friendly artifacts.",
            ],
            project_implications=[
                "Use llm-eval-observability concepts to grade article quality.",
                "Use the homepage as a publishing target, not as the generation engine.",
                "Design adapters so future AWS, search, and model providers can be swapped in.",
            ],
        )

