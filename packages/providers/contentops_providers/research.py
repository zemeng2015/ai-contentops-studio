from __future__ import annotations

import base64
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx
from contentops_core.models import Claim, ResearchPacket, RunRequest, Source

QueryParams = dict[str, str | int | float | bool | None]


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
    def __init__(
        self,
        timeout_seconds: float = 12.0,
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.1,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds

    def collect(self, request: RunRequest) -> ResearchPacket:
        sources = dedupe_sources(
            [self.fetch_source(url) for url in request.source_urls],
            topic=request.topic,
        )
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
                response = _get_with_retries(
                    client,
                    url,
                    retry_attempts=self.retry_attempts,
                    retry_backoff_seconds=self.retry_backoff_seconds,
                )
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
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.1,
    ) -> None:
        self.feeds = feeds
        self.max_sources = max_sources
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds

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
        sources = dedupe_sources(
            [self._entry_to_source(entry) for entry in selected],
            topic=request.topic,
        )
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
                    response = _get_with_retries(
                        client,
                        feed_url,
                        retry_attempts=self.retry_attempts,
                        retry_backoff_seconds=self.retry_backoff_seconds,
                    )
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
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.1,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.max_sources = max_sources
        self.timeout_seconds = timeout_seconds
        self.enrich_results = enrich_results
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.url_provider = URLResearchProvider(
            timeout_seconds=timeout_seconds,
            retry_attempts=retry_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )

    def collect(self, request: RunRequest) -> ResearchPacket:
        results = self._search(request.topic)
        selected = results[: self.max_sources]
        sources = dedupe_sources(self._sources_from_results(selected), topic=request.topic)
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
                response = _get_with_retries(
                    client,
                    self.endpoint,
                    params={"q": topic, "count": self.max_sources},
                    retry_attempts=self.retry_attempts,
                    retry_backoff_seconds=self.retry_backoff_seconds,
                )
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


@dataclass(frozen=True)
class GitHubRepositoryRef:
    owner: str
    repo: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


class GitHubResearchProvider:
    """Collect repository context from GitHub for source-backed content planning."""

    def __init__(
        self,
        api_base_url: str = "https://api.github.com",
        token: str | None = None,
        max_items: int = 5,
        timeout_seconds: float = 12.0,
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.1,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.token = token
        self.max_items = max(max_items, 1)
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds

    def collect(self, request: RunRequest) -> ResearchPacket:
        refs = [
            repo_ref
            for source_url in request.source_urls
            if (repo_ref := _github_repo_from_ref(source_url)) is not None
        ]
        if not refs:
            sources = [
                Source(
                    title="No GitHub repositories provided",
                    publisher="github",
                    summary=(
                        "GitHub research needs source_urls such as "
                        "https://github.com/owner/repo or owner/repo."
                    ),
                    credibility=0.35,
                    extraction_status="missing_input",
                    extraction_quality=0.2,
                )
            ]
        else:
            sources = dedupe_sources(
                [source for repo_ref in refs for source in self._collect_repo_sources(repo_ref)],
                topic=request.topic,
            )
        claims = [
            Claim(
                text=f"{source.title} provides repository evidence for {request.topic}.",
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
                "Repository metadata helps connect content strategy to shipped software.",
                (
                    "README and issue context expose product positioning, maturity, and "
                    "roadmap signals."
                ),
                (
                    "GitHub-backed research can turn open-source activity into reviewable "
                    "content inputs."
                ),
            ],
            risks=[
                "Public repository metadata may omit private architecture and operational context.",
                (
                    "Open issues and pull requests can be noisy unless reviewers inspect the "
                    "source links."
                ),
                "GitHub API rate limits should be managed with a token in scheduled deployments.",
            ],
            project_implications=[
                "Use repository README, issue, and pull request signals to generate launch posts.",
                (
                    "Compare GitHub evidence with evaluation reports before publishing "
                    "portfolio content."
                ),
                "Configure worker jobs with repository source_urls for repeatable product updates.",
            ],
        )

    def _collect_repo_sources(self, repo_ref: GitHubRepositoryRef) -> list[Source]:
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                headers=self._headers(),
            ) as client:
                repo = self._get_json(client, f"/repos/{repo_ref.full_name}")
                readme = self._get_optional_json(client, f"/repos/{repo_ref.full_name}/readme")
                issues = self._get_optional_json(
                    client,
                    f"/repos/{repo_ref.full_name}/issues",
                    params={"state": "open", "per_page": self.max_items},
                )
                pulls = self._get_optional_json(
                    client,
                    f"/repos/{repo_ref.full_name}/pulls",
                    params={"state": "open", "per_page": self.max_items},
                )
            sources = [self._repo_source(repo_ref, repo)]
            if isinstance(readme, dict):
                sources.append(self._readme_source(repo_ref, readme))
            if isinstance(issues, list):
                sources.append(self._activity_source(repo_ref, issues, "issues"))
            if isinstance(pulls, list):
                sources.append(self._activity_source(repo_ref, pulls, "pull requests"))
            return sources
        except Exception as exc:
            return [
                Source(
                    title=f"Unavailable GitHub repository: {repo_ref.full_name}",
                    url=f"https://github.com/{repo_ref.full_name}",
                    canonical_url=f"https://github.com/{repo_ref.full_name}".lower(),
                    publisher="github",
                    summary=f"GitHub fetch failed: {exc}",
                    credibility=0.28,
                    extraction_status="failed",
                    extraction_quality=0.15,
                )
            ]

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ai-contentops-studio/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get_json(
        self,
        client: httpx.Client,
        path: str,
        *,
        params: QueryParams | None = None,
    ) -> object:
        response = _get_with_retries(
            client,
            f"{self.api_base_url}{path}",
            params=params,
            retry_attempts=self.retry_attempts,
            retry_backoff_seconds=self.retry_backoff_seconds,
        )
        return response.json()

    def _get_optional_json(
        self,
        client: httpx.Client,
        path: str,
        *,
        params: QueryParams | None = None,
    ) -> object | None:
        try:
            return self._get_json(client, path, params=params)
        except Exception:
            return None

    @staticmethod
    def _repo_source(repo_ref: GitHubRepositoryRef, payload: object) -> Source:
        repo = payload if isinstance(payload, dict) else {}
        html_url = _string_value(repo, "html_url") or f"https://github.com/{repo_ref.full_name}"
        description = _string_value(repo, "description") or "No repository description provided."
        language = _string_value(repo, "language") or "unknown language"
        stars = _number_value(repo, "stargazers_count")
        forks = _number_value(repo, "forks_count")
        open_issues = _number_value(repo, "open_issues_count")
        summary = (
            f"{description} Primary language: {language}. "
            f"Stars: {stars}. Forks: {forks}. Open issues: {open_issues}."
        )
        return Source(
            title=f"GitHub repository: {repo_ref.full_name}",
            url=html_url,
            canonical_url=_normalize_url(html_url),
            publisher="github",
            summary=summary[:500],
            credibility=0.86,
            extraction_status="github_repo",
            extraction_quality=0.82,
            content_length=len(summary),
        )

    @staticmethod
    def _readme_source(repo_ref: GitHubRepositoryRef, payload: dict[str, object]) -> Source:
        html_url = _string_value(payload, "html_url") or f"https://github.com/{repo_ref.full_name}"
        text = _decode_github_content(_string_value(payload, "content") or "")
        summary = _markdown_excerpt(text)
        if not summary:
            summary = "README exists but no readable text was extracted."
        return Source(
            title=f"README: {repo_ref.full_name}",
            url=html_url,
            canonical_url=_normalize_url(html_url),
            publisher="github",
            summary=summary[:700],
            credibility=0.84,
            extraction_status="github_readme",
            extraction_quality=0.86 if len(summary) >= 160 else 0.62,
            content_length=len(text),
        )

    @staticmethod
    def _activity_source(
        repo_ref: GitHubRepositoryRef,
        payload: list[object],
        label: str,
    ) -> Source:
        items = [item for item in payload if isinstance(item, dict)]
        titles: list[str] = []
        for item in items:
            title = _string_value(item, "title")
            if title is not None:
                titles.append(title)
        summary = (
            f"Open {label}: "
            + "; ".join(titles[:5])
            if titles
            else f"No open {label} returned by GitHub."
        )
        return Source(
            title=f"GitHub {label}: {repo_ref.full_name}",
            url=f"https://github.com/{repo_ref.full_name}",
            canonical_url=f"https://github.com/{repo_ref.full_name}/{label.replace(' ', '-')}",
            publisher="github",
            summary=summary[:500],
            credibility=0.7 if titles else 0.58,
            extraction_status=f"github_{label.replace(' ', '_')}",
            extraction_quality=0.72 if titles else 0.5,
            content_length=len(summary),
        )


class DiscoveryResearchProvider:
    def __init__(
        self,
        feeds: list[str],
        max_sources: int = 6,
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.1,
    ) -> None:
        self.local = LocalResearchProvider()
        self.url = URLResearchProvider(
            retry_attempts=retry_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        self.feed = FeedResearchProvider(
            feeds=feeds,
            max_sources=max_sources,
            retry_attempts=retry_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )

    def collect(self, request: RunRequest) -> ResearchPacket:
        local_packet = self.local.collect(request)
        feed_packet = self.feed.collect(request)
        url_packet = self.url.collect(request) if request.source_urls else None
        packets = [feed_packet, local_packet]
        if url_packet is not None:
            packets.insert(1, url_packet)
        sources = dedupe_sources(
            [source for packet in packets for source in packet.sources],
            topic=request.topic,
        )
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
    def __init__(
        self,
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.1,
    ) -> None:
        self.local = LocalResearchProvider()
        self.url = URLResearchProvider(
            retry_attempts=retry_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )

    def collect(self, request: RunRequest) -> ResearchPacket:
        local_packet = self.local.collect(request)
        if not request.source_urls:
            return local_packet
        url_packet = self.url.collect(request)
        sources = dedupe_sources(url_packet.sources + local_packet.sources, topic=request.topic)
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


def _get_with_retries(
    client: httpx.Client,
    url: str,
    *,
    params: QueryParams | None = None,
    retry_attempts: int,
    retry_backoff_seconds: float,
) -> httpx.Response:
    attempts = max(retry_attempts, 1)
    for attempt in range(attempts):
        try:
            response = client.get(url, params=params) if params is not None else client.get(url)
            response.raise_for_status()
            return response
        except Exception as exc:
            if attempt == attempts - 1 or not _is_retryable_http_error(exc):
                raise
            delay = max(retry_backoff_seconds, 0) * (2**attempt)
            if delay:
                time.sleep(delay)
    raise RuntimeError(f"Unable to fetch {url}")


def _is_retryable_http_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or status_code >= 500
    return isinstance(
        exc,
        (
            TimeoutError,
            ConnectionError,
            httpx.TimeoutException,
            httpx.TransportError,
        ),
    )


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


def _github_repo_from_ref(value: str) -> GitHubRepositoryRef | None:
    text = value.strip().removesuffix(".git")
    if not text:
        return None
    if re.fullmatch(r"[\w.-]+/[\w.-]+", text):
        owner, repo = text.split("/", 1)
        return GitHubRepositoryRef(owner=owner, repo=repo)
    parsed = urlparse(text)
    if parsed.netloc.lower().removeprefix("www.") != "github.com":
        return None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None
    return GitHubRepositoryRef(owner=parts[0], repo=parts[1].removesuffix(".git"))


def _decode_github_content(value: str) -> str:
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return ""
    try:
        return base64.b64decode(compact).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _markdown_excerpt(markdown: str) -> str:
    without_fences = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    without_links = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", without_fences)
    without_markup = re.sub(r"[#*_>`~|]", " ", without_links)
    without_urls = re.sub(r"https?://\S+", " ", without_markup)
    return re.sub(r"\s+", " ", without_urls).strip()


def _string_value(item: dict[str, object], key: str) -> str | None:
    value = item.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _number_value(item: dict[str, object], key: str) -> int:
    value = item.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def dedupe_sources(sources: list[Source], topic: str = "") -> list[Source]:
    by_key: dict[str, Source] = {}
    for source in sources:
        source = enrich_source(source, topic=topic)
        key = source.canonical_url or _normalize_url(source.url)
        if not key:
            key = f"{source.publisher}:{source.title}".lower()
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = source.model_copy(update={"canonical_url": key if source.url else None})
            continue
        duplicate_count = existing.duplicate_count + source.duplicate_count
        if _source_rank(source) > _source_rank(existing):
            by_key[key] = source.model_copy(
                update={
                    "canonical_url": key if source.url else None,
                    "duplicate_count": duplicate_count,
                }
            )
        else:
            by_key[key] = existing.model_copy(update={"duplicate_count": duplicate_count})
    return list(by_key.values())


def enrich_source(source: Source, topic: str = "") -> Source:
    publisher = source.publisher
    if publisher in {"unknown", "web"} and source.url:
        publisher = _publisher_from_url(source.url)
    source_type = _source_type(source, publisher)
    authority_score = _authority_score(source, publisher, source_type)
    relevance_score = _relevance_score(source, topic)
    credibility = _credibility_score(source, authority_score, relevance_score)
    canonical_url = source.canonical_url or _normalize_url(source.url)
    return source.model_copy(
        update={
            "canonical_url": canonical_url,
            "publisher": publisher,
            "source_type": source_type,
            "authority_score": authority_score,
            "relevance_score": relevance_score,
            "credibility": credibility,
        }
    )


def _source_rank(source: Source) -> tuple[int, int, float, float, float, float, int]:
    return (
        _status_rank(source.extraction_status),
        _type_rank(source.source_type),
        source.extraction_quality,
        source.authority_score,
        source.relevance_score,
        source.credibility,
        source.content_length,
    )


def _status_rank(status: str) -> int:
    if status in {"ok", "search_enriched", "github_repo", "github_readme"}:
        return 3
    if status.startswith("github_") or status == "feed":
        return 2
    if status in {"search", "synthetic"}:
        return 1
    return 0


def _type_rank(source_type: str) -> int:
    ranks = {
        "official_docs": 7,
        "repository": 6,
        "research_paper": 6,
        "engineering_blog": 5,
        "web_source": 4,
        "web_discovery": 3,
        "operator_context": 2,
        "local_context": 1,
    }
    return ranks.get(source_type, 0)


def _source_type(source: Source, publisher: str) -> str:
    status = source.extraction_status
    canonical_url = source.canonical_url or _normalize_url(source.url) or ""
    if publisher in {"contentops-local", "user-input", "operator"}:
        return "operator_context" if publisher != "contentops-local" else "local_context"
    if status.startswith("github") or "github.com" in canonical_url:
        return "repository"
    if "arxiv.org" in canonical_url or "doi.org" in canonical_url:
        return "research_paper"
    if "/docs" in canonical_url or publisher in {
        "aws.amazon.com",
        "docs.aws.amazon.com",
        "docs.github.com",
        "openai.com",
        "platform.openai.com",
    }:
        return "official_docs"
    if "blog" in canonical_url or publisher.startswith(("engineering.", "developer.")):
        return "engineering_blog"
    if status == "feed" or status == "search":
        return "web_discovery"
    return "web_source"


def _authority_score(source: Source, publisher: str, source_type: str) -> float:
    base_scores = {
        "official_docs": 0.92,
        "repository": 0.86,
        "research_paper": 0.88,
        "engineering_blog": 0.78,
        "operator_context": 0.82,
        "local_context": 0.76,
        "web_discovery": 0.64,
        "web_source": 0.62,
    }
    score = base_scores.get(source_type, 0.55)
    if source.extraction_status == "failed":
        score = min(score, 0.3)
    if source.url and source.url.startswith("https://"):
        score += 0.04
    if publisher.endswith((".gov", ".edu")):
        score += 0.08
    return min(round(score, 3), 1.0)


def _relevance_score(source: Source, topic: str) -> float:
    text = f"{source.title} {source.summary}".casefold()
    topic_terms = [term for term in re.split(r"\W+", topic.casefold()) if len(term) >= 4]
    if not topic_terms:
        return 0.5
    matched = sum(1 for term in set(topic_terms) if term in text)
    base = matched / len(set(topic_terms))
    ai_terms = {"agent", "eval", "llm", "model", "observability", "rag", "workflow"}
    ai_bonus = min(sum(1 for term in ai_terms if term in text) * 0.04, 0.16)
    summary_bonus = 0.08 if len(source.summary) >= 120 else 0.0
    return min(round(base * 0.78 + ai_bonus + summary_bonus, 3), 1.0)


def _credibility_score(source: Source, authority_score: float, relevance_score: float) -> float:
    if source.extraction_status == "failed":
        return min(source.credibility, 0.3)
    score = (
        source.credibility * 0.35
        + authority_score * 0.35
        + relevance_score * 0.15
        + source.extraction_quality * 0.15
    )
    return min(round(score, 3), 1.0)
