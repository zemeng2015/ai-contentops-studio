from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

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
        sources = dedupe_sources([self.fetch_source(url) for url in request.source_urls])
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

    def fetch_source(self, url: str) -> Source:
        return self._fetch_source(url)

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
                canonical_url=_normalize_url(url),
                publisher=self._publisher_from_url(url),
                summary=summary,
                credibility=0.78,
                extraction_status="ok",
                extraction_quality=self._score_extraction(title, summary, html),
                content_length=len(_strip_tags(html)),
            )
        except Exception as exc:
            return Source(
                title=f"Unavailable source: {url}",
                url=url,
                canonical_url=_normalize_url(url),
                publisher=self._publisher_from_url(url),
                summary=f"Fetch failed: {exc}",
                credibility=0.25,
                extraction_status="failed",
                extraction_quality=0.15,
                content_length=0,
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

    @staticmethod
    def _score_extraction(title: str, summary: str, html: str) -> float:
        text_length = len(_strip_tags(html))
        score = 0.35
        if title and not title.startswith("http"):
            score += 0.2
        if len(summary) >= 120:
            score += 0.25
        elif len(summary) >= 40:
            score += 0.12
        if text_length >= 1500:
            score += 0.2
        elif text_length >= 400:
            score += 0.1
        return min(round(score, 3), 1.0)


@dataclass(frozen=True)
class FeedEntry:
    title: str
    url: str | None
    summary: str
    publisher: str


class FeedResearchProvider:
    """Discover current sources from RSS or Atom feeds.

    This provider gives scheduled workers a real discovery path without requiring paid search
    credentials. Operators can point it at arXiv, engineering blogs, vendor feeds, or internal
    feeds, then let the pipeline rank candidates against the requested topic.
    """

    def __init__(
        self,
        feeds: list[str],
        max_sources: int = 6,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.feeds = feeds
        self.max_sources = max_sources
        self.timeout_seconds = timeout_seconds

    def collect(self, request: RunRequest) -> ResearchPacket:
        entries = self._discover_entries()
        scored_entries = sorted(
            entries,
            key=lambda entry: self._score_entry(entry, request.topic),
            reverse=True,
        )
        selected = [
            entry
            for entry in scored_entries
            if self._score_entry(entry, request.topic) > 0
        ][: self.max_sources]
        if not selected:
            selected = scored_entries[: self.max_sources]
        sources = dedupe_sources([self._entry_to_source(entry) for entry in selected])
        claims = [
            Claim(
                text=f"{source.title} is a discovered signal for {request.topic}.",
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
                "Scheduled content should discover candidate sources before generation.",
                "Feed ranking keeps the pipeline useful without requiring a manual URL list.",
                "Research feeds make daily AI trend monitoring repeatable and auditable.",
            ],
            risks=[
                "RSS summaries can be short, so reviewers should inspect discovered source links.",
                "Feed relevance depends on configured sources and topic keywords.",
            ],
            project_implications=[
                "Use worker YAML jobs to turn recurring AI research into a content calendar.",
                "Compare reruns to measure whether newly discovered sources improved coverage.",
            ],
        )

    def _discover_entries(self) -> list[FeedEntry]:
        entries: list[FeedEntry] = []
        for feed_url in self.feeds:
            try:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                    headers={"User-Agent": "ai-contentops-studio/0.1"},
                ) as client:
                    response = client.get(feed_url)
                    response.raise_for_status()
                entries.extend(self._parse_feed(response.text, feed_url))
            except Exception:
                entries.append(
                    FeedEntry(
                        title=f"Unavailable feed: {feed_url}",
                        url=feed_url,
                        summary="Feed fetch failed; check provider configuration.",
                        publisher=_publisher_from_url(feed_url),
                    )
                )
        return entries

    @staticmethod
    def _parse_feed(xml_text: str, feed_url: str) -> list[FeedEntry]:
        root = ET.fromstring(xml_text)
        entries: list[FeedEntry] = []
        for item in _xml_elements(root, "item"):
            entries.append(
                FeedEntry(
                    title=_xml_child_text(item, "title") or "Untitled feed item",
                    url=_xml_child_text(item, "link"),
                    summary=_xml_child_text(item, "description") or "",
                    publisher=_publisher_from_url(feed_url),
                )
            )
        for item in _xml_elements(root, "entry"):
            entries.append(
                FeedEntry(
                    title=_xml_child_text(item, "title") or "Untitled feed item",
                    url=_xml_link(item),
                    summary=(
                        _xml_child_text(item, "summary")
                        or _xml_child_text(item, "content")
                        or ""
                    ),
                    publisher=_publisher_from_url(feed_url),
                )
            )
        return entries

    @staticmethod
    def _score_entry(entry: FeedEntry, topic: str) -> float:
        text = f"{entry.title} {entry.summary}".casefold()
        topic_terms = [term for term in re.split(r"\W+", topic.casefold()) if len(term) >= 4]
        ai_terms = [
            "agent",
            "ai",
            "eval",
            "llm",
            "model",
            "observability",
            "rag",
            "retrieval",
            "workflow",
        ]
        topic_score = sum(2.0 for term in topic_terms if term in text)
        ai_score = sum(1.0 for term in ai_terms if term in text)
        summary_score = min(len(entry.summary) / 400, 1.0)
        return topic_score + ai_score + summary_score

    @staticmethod
    def _entry_to_source(entry: FeedEntry) -> Source:
        summary = re.sub(r"\s+", " ", _strip_tags(entry.summary)).strip()
        if not summary:
            summary = "No feed summary was provided."
        return Source(
            title=entry.title[:180],
            url=entry.url,
            canonical_url=_normalize_url(entry.url),
            publisher=entry.publisher,
            summary=summary[:500],
            credibility=0.72,
            extraction_status="feed",
            extraction_quality=0.7 if len(summary) >= 80 else 0.55,
            content_length=len(summary),
        )


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str | None
    snippet: str
    publisher: str


class SearchResearchProvider:
    """Search API backed research provider.

    The default request shape matches Brave Search's web endpoint, while the JSON parser accepts
    common `web.results`, `organic`, and `results` lists so operators can swap compatible search
    services without changing pipeline code.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        max_sources: int = 6,
        timeout_seconds: float = 12.0,
        enrich_results: bool = True,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.max_sources = max_sources
        self.timeout_seconds = timeout_seconds
        self.enrich_results = enrich_results
        self.url_provider = URLResearchProvider(timeout_seconds=timeout_seconds)

    def collect(self, request: RunRequest) -> ResearchPacket:
        results = self._search(request.topic)
        selected = results[: self.max_sources]
        sources = dedupe_sources(self._sources_from_results(selected))
        claims = [
            Claim(
                text=f"{source.title} is a search-discovered source for {request.topic}.",
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
                "Search-backed research expands beyond fixed feeds and manual URLs.",
                "Search snippets should be treated as leads that reviewers can inspect.",
                "Provider boundaries let teams swap search vendors without changing workflow code.",
            ],
            risks=[
                "Search result quality depends on provider ranking and query wording.",
                "Snippets can omit nuance; important sources should be reviewed before publishing.",
            ],
            project_implications=[
                "Use search provider credentials in deployed workers for daily AI monitoring.",
                "Persist search metadata so review and evaluation stay auditable.",
            ],
        )

    def _sources_from_results(self, results: list[SearchResult]) -> list[Source]:
        if not self.enrich_results:
            return [self._result_to_source(result) for result in results]
        return [self._enrich_result(result) for result in results]

    def _enrich_result(self, result: SearchResult) -> Source:
        fallback = self._result_to_source(result)
        if not result.url:
            return fallback
        fetched = self.url_provider.fetch_source(result.url)
        if fetched.extraction_status != "ok":
            return fallback
        return fetched.model_copy(
            update={
                "credibility": max(fetched.credibility, fallback.credibility),
                "extraction_status": "search_enriched",
                "extraction_quality": max(fetched.extraction_quality, fallback.extraction_quality),
            }
        )

    def _search(self, topic: str) -> list[SearchResult]:
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "ai-contentops-studio/0.1",
                    "X-Subscription-Token": self.api_key,
                },
            ) as client:
                response = client.get(
                    self.endpoint,
                    params={"q": topic, "count": self.max_sources},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            return [
                SearchResult(
                    title=f"Search failed for: {topic}",
                    url=self.endpoint,
                    snippet=f"Search provider request failed: {exc}",
                    publisher=_publisher_from_url(self.endpoint),
                )
            ]
        return self._parse_results(payload)

    @staticmethod
    def _parse_results(payload: object) -> list[SearchResult]:
        if not isinstance(payload, dict):
            return []
        raw_results = _search_result_items(payload)
        results: list[SearchResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = _first_string(item, ["url", "link"])
            title = _first_string(item, ["title", "name"]) or url or "Untitled search result"
            snippet = _first_string(item, ["description", "snippet", "summary"]) or ""
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    publisher=_publisher_from_url(url or ""),
                )
            )
        return results

    @staticmethod
    def _result_to_source(result: SearchResult) -> Source:
        summary = re.sub(r"\s+", " ", _strip_tags(result.snippet)).strip()
        if not summary:
            summary = "Search result did not include a snippet."
        return Source(
            title=result.title[:180],
            url=result.url,
            canonical_url=_normalize_url(result.url),
            publisher=result.publisher,
            summary=summary[:500],
            credibility=0.68,
            extraction_status="search",
            extraction_quality=0.68 if len(summary) >= 80 else 0.52,
            content_length=len(summary),
        )


class DiscoveryResearchProvider:
    def __init__(self, feeds: list[str], max_sources: int = 6) -> None:
        self.local = LocalResearchProvider()
        self.url = URLResearchProvider()
        self.feed = FeedResearchProvider(feeds=feeds, max_sources=max_sources)

    def collect(self, request: RunRequest) -> ResearchPacket:
        local_packet = self.local.collect(request)
        feed_packet = self.feed.collect(request)
        url_packet = self.url.collect(request) if request.source_urls else None
        packets = [feed_packet, local_packet]
        if url_packet is not None:
            packets.insert(1, url_packet)
        sources = dedupe_sources([source for packet in packets for source in packet.sources])
        source_titles = {source.title for source in sources}
        claims = [
            claim
            for packet in packets
            for claim in packet.claims
            if claim.source_title in source_titles
        ]
        return ResearchPacket(
            topic=request.topic.strip(),
            sources=sources,
            claims=claims,
            engineering_signals=[
                signal for packet in packets for signal in packet.engineering_signals
            ],
            risks=[risk for packet in packets for risk in packet.risks],
            project_implications=[
                implication for packet in packets for implication in packet.project_implications
            ],
        )


class HybridResearchProvider:
    def __init__(self) -> None:
        self.local = LocalResearchProvider()
        self.url = URLResearchProvider()

    def collect(self, request: RunRequest) -> ResearchPacket:
        local_packet = self.local.collect(request)
        if not request.source_urls:
            return local_packet
        url_packet = self.url.collect(request)
        sources = dedupe_sources(url_packet.sources + local_packet.sources)
        source_titles = {source.title for source in sources}
        claims = [
            claim
            for claim in url_packet.claims + local_packet.claims
            if claim.source_title in source_titles
        ]
        return ResearchPacket(
            topic=local_packet.topic,
            sources=sources,
            claims=claims,
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


def _normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    normalized = url.strip().lower().split("#", 1)[0].split("?", 1)[0]
    return normalized.rstrip("/")


def _publisher_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.removeprefix("www.") if parsed.netloc else "web"


def _xml_elements(root: ET.Element, local_name: str) -> list[ET.Element]:
    return [element for element in root.iter() if _xml_local_name(element.tag) == local_name]


def _xml_child_text(element: ET.Element, local_name: str) -> str | None:
    match = next(
        (child for child in element if _xml_local_name(child.tag) == local_name),
        None,
    )
    if match is None:
        return None
    text = "".join(match.itertext()).strip()
    return re.sub(r"\s+", " ", text).strip() if text else None


def _xml_link(element: ET.Element) -> str | None:
    link = next((child for child in element if _xml_local_name(child.tag) == "link"), None)
    if link is None:
        return None
    if "href" in link.attrib:
        return link.attrib["href"]
    text = "".join(link.itertext()).strip()
    return text or None


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _search_result_items(payload: dict[str, object]) -> list[object]:
    web = payload.get("web")
    if isinstance(web, dict):
        web_results = web.get("results")
        if isinstance(web_results, list):
            return list(web_results)
    for key in ("organic", "results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return list(value)
    return []


def _first_string(item: dict[str, object], keys: list[str]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def dedupe_sources(sources: list[Source]) -> list[Source]:
    by_key: dict[str, Source] = {}
    for source in sources:
        key = source.canonical_url or _normalize_url(source.url)
        if not key:
            key = f"{source.publisher}:{source.title}".lower()
        existing = by_key.get(key)
        if existing is None or _source_rank(source) > _source_rank(existing):
            by_key[key] = source.model_copy(update={"canonical_url": key if source.url else None})
    return list(by_key.values())


def _source_rank(source: Source) -> tuple[float, float, int]:
    return (source.extraction_quality, source.credibility, source.content_length)
