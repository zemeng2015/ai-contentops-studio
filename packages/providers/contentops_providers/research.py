from __future__ import annotations

import re
from typing import Protocol

import httpx
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


class URLResearchProvider:
    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self.timeout_seconds = timeout_seconds

    def collect(self, request: RunRequest) -> ResearchPacket:
        sources = [self._fetch_source(url) for url in request.source_urls]
        claims = [
            Claim(
                text=f"{source.title} is relevant to {request.topic} because {source.summary}",
                source_title=source.title,
                confidence=source.credibility,
            )
            for source in sources
        ]
        return ResearchPacket(
            topic=request.topic.strip(),
            sources=sources,
            claims=claims,
            engineering_signals=[
                "Source material should be normalized before content planning.",
                (
                    "Generated articles should cite concrete source titles instead of vague "
                    "web claims."
                ),
                "A research artifact lets reviewers inspect what the model actually saw.",
            ],
            risks=[
                "Fetched pages may contain marketing copy, stale claims, or unrelated boilerplate.",
                "Network failures should degrade gracefully instead of blocking local development.",
            ],
            project_implications=[
                "Add source credibility and extraction quality to evaluation reports.",
                "Keep raw source metadata in artifacts for auditability.",
            ],
        )

    def _fetch_source(self, url: str) -> Source:
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "ai-contentops-studio/0.1"},
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                if "charset=" not in response.headers.get("content-type", "").lower():
                    response.encoding = "utf-8"
            html = response.text
            title = self._extract_title(html) or url
            summary = self._extract_summary(html)
            return Source(
                title=title[:180],
                url=url,
                publisher=self._publisher_from_url(url),
                summary=summary,
                credibility=0.78,
            )
        except Exception as exc:
            return Source(
                title=f"Unavailable source: {url}",
                url=url,
                publisher=self._publisher_from_url(url),
                summary=f"Fetch failed: {exc}",
                credibility=0.25,
            )

    @staticmethod
    def _extract_title(html: str) -> str | None:
        match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        return re.sub(r"\s+", " ", _strip_tags(match.group(1))).strip()

    @staticmethod
    def _extract_summary(html: str) -> str:
        meta = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            flags=re.IGNORECASE,
        )
        if meta:
            return re.sub(r"\s+", " ", meta.group(1)).strip()[:500]
        text = _strip_tags(html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:500] if text else "No readable page text extracted."

    @staticmethod
    def _publisher_from_url(url: str) -> str:
        match = re.match(r"https?://([^/]+)", url)
        return match.group(1).removeprefix("www.") if match else "web"


class HybridResearchProvider:
    def __init__(self) -> None:
        self.local = LocalResearchProvider()
        self.url = URLResearchProvider()

    def collect(self, request: RunRequest) -> ResearchPacket:
        local_packet = self.local.collect(request)
        if not request.source_urls:
            return local_packet
        url_packet = self.url.collect(request)
        return ResearchPacket(
            topic=local_packet.topic,
            sources=url_packet.sources + local_packet.sources,
            claims=url_packet.claims + local_packet.claims,
            engineering_signals=url_packet.engineering_signals + local_packet.engineering_signals,
            risks=url_packet.risks + local_packet.risks,
            project_implications=(
                url_packet.project_implications + local_packet.project_implications
            ),
        )


def _strip_tags(html: str) -> str:
    without_scripts = re.sub(
        r"<(script|style)[^>]*>.*?</\1>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return re.sub(r"<[^>]+>", " ", without_scripts)
