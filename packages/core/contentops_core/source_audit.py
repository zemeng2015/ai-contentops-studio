from __future__ import annotations

from contentops_core.models import ResearchPacket, Source, SourceAssessment, SourceAuditReport


def audit_sources(packet: ResearchPacket) -> SourceAuditReport:
    assessments = [_assess_source(source) for source in packet.sources]
    source_count = len(assessments)
    average_score = (
        round(sum(assessment.score for assessment in assessments) / source_count, 3)
        if source_count
        else 0.0
    )
    return SourceAuditReport(
        topic=packet.topic,
        source_count=source_count,
        average_score=average_score,
        strong_count=sum(1 for assessment in assessments if assessment.grade == "strong"),
        review_count=sum(1 for assessment in assessments if assessment.grade == "review"),
        failed_count=sum(1 for assessment in assessments if assessment.grade == "failed"),
        assessments=assessments,
    )


def _assess_source(source: Source) -> SourceAssessment:
    score = _source_score(source)
    grade = _grade_source(source, score)
    reasons = _source_reasons(source)
    return SourceAssessment(
        source_title=source.title,
        canonical_url=source.canonical_url or source.url,
        publisher=source.publisher,
        discovery_method=source.extraction_status,
        score=score,
        grade=grade,
        reasons=reasons,
        recommendation=_recommendation(grade, reasons),
    )


def _source_score(source: Source) -> float:
    content_score = min(source.content_length / 1500, 1.0)
    status_bonus = 0.08 if source.extraction_status in {"ok", "search_enriched"} else 0.0
    score = (
        source.extraction_quality * 0.35
        + source.credibility * 0.25
        + source.authority_score * 0.18
        + source.relevance_score * 0.12
        + content_score * 0.1
        + status_bonus
    )
    return min(round(score, 3), 1.0)


def _grade_source(source: Source, score: float) -> str:
    if source.extraction_status == "failed":
        return "failed"
    if score >= 0.78:
        return "strong"
    if score >= 0.55:
        return "usable"
    return "review"


def _source_reasons(source: Source) -> list[str]:
    reasons: list[str] = []
    if source.extraction_status == "failed":
        reasons.append("Source fetch failed.")
    elif source.extraction_status == "search":
        reasons.append("Only search snippet content is available.")
    elif source.extraction_status == "search_enriched":
        reasons.append("Search result was enriched with fetched page content.")
    elif source.extraction_status == "feed":
        reasons.append("Source came from feed discovery.")
    if source.source_type in {"official_docs", "repository", "research_paper"}:
        reasons.append(f"Source type is high-authority: {source.source_type}.")
    if source.authority_score < 0.55:
        reasons.append("Authority score is low.")
    if source.relevance_score < 0.35:
        reasons.append("Topic relevance is weak.")
    if source.duplicate_count > 1:
        reasons.append(f"{source.duplicate_count} duplicate source records were merged.")
    if source.extraction_quality < 0.55:
        reasons.append("Extraction quality is low.")
    if source.credibility < 0.55:
        reasons.append("Credibility score is low.")
    if source.content_length < 300:
        reasons.append("Readable content is short.")
    if not reasons:
        reasons.append("Source has enough extracted content for review.")
    return reasons


def _recommendation(grade: str, reasons: list[str]) -> str:
    if grade == "strong":
        return "Use as a primary cited source."
    if grade == "usable":
        return "Use with reviewer spot-checking."
    if grade == "failed":
        return "Replace or retry before publication."
    if any("Only search snippet" in reason for reason in reasons):
        return "Open the URL or enable enrichment before relying on it."
    return "Review manually before publication."
