from __future__ import annotations

from typing import Protocol

from contentops_core.models import Draft, EvaluationReport, ResearchPacket


class ContentEvaluator(Protocol):
    def evaluate(self, packet: ResearchPacket, draft: Draft) -> EvaluationReport:
        """Score generated content before publishing."""


class HeuristicContentEvaluator:
    def __init__(self, min_publish_score: float = 0.72) -> None:
        self.min_publish_score = min_publish_score

    def evaluate(self, packet: ResearchPacket, draft: Draft) -> EvaluationReport:
        markdown = draft.markdown.lower()
        cited_sources = sum(1 for source in packet.sources if source.title.lower() in markdown)
        source_coverage = cited_sources / max(len(packet.sources), 1)
        grounded_claims = sum(
            1 for claim in packet.claims if claim.source_title.lower() in markdown
        )
        groundedness = grounded_claims / max(len(packet.claims), 1)
        career_terms = ["portfolio", "project", "rag", "eval", "aws", "observability", "system"]
        career_relevance = min(1.0, sum(1 for term in career_terms if term in markdown) / 5)
        depth_terms = ["boundary", "evaluation", "artifact", "trace", "workflow", "publishing"]
        technical_depth = min(1.0, sum(1 for term in depth_terms if term in markdown) / 5)
        scores = [groundedness, source_coverage, career_relevance, technical_depth]
        publish_ready = min(scores) >= self.min_publish_score
        findings: list[str] = []
        if source_coverage < self.min_publish_score:
            findings.append("Improve source coverage before publishing.")
        if groundedness < self.min_publish_score:
            findings.append("Tie claims back to source titles more explicitly.")
        if career_relevance < self.min_publish_score:
            findings.append("Connect the article more clearly to portfolio positioning.")
        if technical_depth < self.min_publish_score:
            findings.append("Add more implementation detail or architectural judgment.")
        if not findings:
            findings.append("Content is ready for review or publication.")
        return EvaluationReport(
            groundedness=round(groundedness, 3),
            source_coverage=round(source_coverage, 3),
            career_relevance=round(career_relevance, 3),
            technical_depth=round(technical_depth, 3),
            publish_ready=publish_ready,
            findings=findings,
        )
