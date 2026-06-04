from __future__ import annotations

from pathlib import Path
from subprocess import run

import pytest
from contentops_core.factory import build_pipeline
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
from contentops_providers.research import (
    DiscoveryResearchProvider,
    FeedResearchProvider,
    GitHubResearchProvider,
    HybridResearchProvider,
    SearchResearchProvider,
    URLResearchProvider,
)
from contentops_publishing.homepage import HomepagePublisher


def test_hybrid_research_includes_url_and_local_context(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(self: URLResearchProvider, url: str) -> Source:
        return Source(
            title="Fetched source",
            url=url,
            publisher="example.com",
            summary="Fetched source summary.",
            credibility=0.9,
        )

    monkeypatch.setattr(URLResearchProvider, "_fetch_source", fake_fetch)
    packet = HybridResearchProvider().collect(
        request=RunRequest(
            topic="Agent observability",
            source_urls=["https://example.com/article"],
        )
    )

    assert packet.sources[0].title == "Fetched source"
    assert len(packet.sources) == 4
    assert any(source.title == "Portfolio project map" for source in packet.sources)
    assert any("Fetched source" in claim.source_title for claim in packet.claims)


def test_homepage_publisher_updates_post_grid(tmp_path: Path) -> None:
    homepage = tmp_path / "homepage"
    (homepage / "posts").mkdir(parents=True)
    _init_git_repo(homepage)
    (homepage / "index.html").write_text(
        '<html><body><section id="writing"><div class="post-grid"></div></section></body></html>',
        encoding="utf-8",
    )
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "eval-report.json").write_text('{"publish_ready": true}', encoding="utf-8")
    run = RunRecord(
        topic="Topic",
        slug="topic",
        status=RunStatus.PUBLISHING,
        artifact_dir=artifact_dir,
    )
    draft = Draft(
        title="Generated Article",
        slug="generated-article",
        markdown="# x",
        html="<html><head></head><body>x</body></html>",
    )
    report = EvaluationReport(
        groundedness=0.9,
        source_coverage=0.9,
        career_relevance=0.9,
        technical_depth=0.9,
        publish_ready=True,
        findings=["ready"],
    )

    url = HomepagePublisher(homepage, "https://example.com").publish(run, draft, report)

    assert url == "https://example.com/posts/generated-article.html"
    assert (homepage / "posts" / "generated-article.html").exists()
    assert 'href="posts/generated-article.html"' in (homepage / "index.html").read_text(
        encoding="utf-8"
    )


def test_homepage_publisher_plan_describes_file_changes(tmp_path: Path) -> None:
    homepage = tmp_path / "homepage"
    (homepage / "posts").mkdir(parents=True)
    _init_git_repo(homepage)
    (homepage / "index.html").write_text(
        '<html><body><section id="writing"><div class="post-grid"></div></section></body></html>',
        encoding="utf-8",
    )
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    run = RunRecord(
        topic="Topic",
        slug="topic",
        status=RunStatus.NEEDS_REVIEW,
        artifact_dir=artifact_dir,
    )
    draft = Draft(
        title="Generated Article",
        slug="generated-article",
        markdown="# x",
        html="<html><head></head><body>x</body></html>",
    )
    report = EvaluationReport(
        groundedness=0.9,
        source_coverage=0.9,
        source_quality=0.9,
        career_relevance=0.9,
        technical_depth=0.9,
        publish_ready=True,
        findings=["ready"],
    )

    plan = HomepagePublisher(homepage, "https://example.com").plan(run, draft, report)

    assert plan.provider == "homepage"
    assert plan.ready is True
    assert plan.target_url == "https://example.com/posts/generated-article.html"
    assert [item.action for item in plan.items] == ["create", "create", "update"]
    assert plan.metadata["relative_paths"] == [
        "posts/generated-article.html",
        "posts/generated-article.eval.json",
        "index.html",
    ]
    assert plan.metadata["git"]["is_repository"] is True
    assert plan.metadata["git"]["dirty"] is True
    assert 'git -C "' in plan.metadata["suggested_commands"][0]


def test_homepage_publisher_requires_git_repository(tmp_path: Path) -> None:
    homepage = tmp_path / "homepage"
    (homepage / "posts").mkdir(parents=True)
    (homepage / "index.html").write_text(
        '<html><body><section id="writing"><div class="post-grid"></div></section></body></html>',
        encoding="utf-8",
    )
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    run = RunRecord(
        topic="Topic",
        slug="topic",
        status=RunStatus.NEEDS_REVIEW,
        artifact_dir=artifact_dir,
    )
    draft = Draft(
        title="Generated Article",
        slug="generated-article",
        markdown="# x",
        html="<html><head></head><body>x</body></html>",
    )
    report = EvaluationReport(
        groundedness=0.9,
        source_coverage=0.9,
        source_quality=0.9,
        career_relevance=0.9,
        technical_depth=0.9,
        publish_ready=True,
        findings=["ready"],
    )

    plan = HomepagePublisher(homepage, "https://example.com").plan(run, draft, report)

    assert plan.ready is False
    assert "Homepage target must be a git repository." in plan.warnings
    assert plan.metadata["git"]["is_repository"] is False


def test_openai_provider_requires_api_key(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        generator_provider="openai",
    )

    with pytest.raises(ValueError, match="CONTENTOPS_OPENAI_API_KEY"):
        build_pipeline(settings)


def _init_git_repo(path: Path) -> None:
    run(["git", "-C", str(path), "init"], check=True, capture_output=True)


def test_openai_generator_retries_transient_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "output_text": "# Generated\n\nSources: Test source",
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            }

    class FakeClient:
        calls = 0

        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(
            self,
            url: str,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakeResponse:
            FakeClient.calls += 1
            assert url == "https://api.openai.com/v1/responses"
            assert headers["Authorization"] == "Bearer secret"
            if FakeClient.calls == 1:
                raise TimeoutError("temporary model timeout")
            return FakeResponse()

    monkeypatch.setattr("contentops_providers.openai_generator.httpx.Client", FakeClient)

    generator = OpenAIResponsesGenerator(
        api_key="secret",
        model="gpt-5-mini",
        retry_attempts=2,
        retry_backoff_seconds=0,
    )
    draft = generator.generate(_sample_research_packet(), _sample_content_plan())
    receipt = generator.generation_receipt()

    assert FakeClient.calls == 2
    assert draft.markdown.startswith("# Generated")
    assert receipt is not None
    assert receipt.provider == "openai"
    assert receipt.model == "gpt-5-mini"
    assert receipt.status == "completed"
    assert receipt.attempts == 2
    assert receipt.fallback_used is False
    assert receipt.total_tokens == 120


def test_openai_generator_can_fallback_after_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(
            self,
            url: str,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> object:
            raise TimeoutError("model provider unavailable")

    monkeypatch.setattr("contentops_providers.openai_generator.httpx.Client", FakeClient)

    generator = OpenAIResponsesGenerator(
        api_key="secret",
        model="gpt-5-mini",
        retry_attempts=2,
        retry_backoff_seconds=0,
        fallback_on_failure=True,
    )
    draft = generator.generate(_sample_research_packet(), _sample_content_plan())
    receipt = generator.generation_receipt()

    assert draft.title == "AI Workflow Reliability"
    assert "The useful version of AI automation" in draft.markdown
    assert receipt is not None
    assert receipt.status == "fallback"
    assert receipt.fallback_used is True
    assert receipt.error is not None


def test_search_research_provider_requires_api_key(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        research_provider="search",
    )

    with pytest.raises(ValueError, match="CONTENTOPS_RESEARCH_SEARCH_API_KEY"):
        build_pipeline(settings)


def test_github_research_provider_can_be_selected(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        research_provider="github",
    )

    pipeline = build_pipeline(settings)

    assert isinstance(pipeline.research_provider, GitHubResearchProvider)


def test_search_research_parses_brave_style_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        headers = {"content-type": "text/html; charset=utf-8"}
        encoding = "utf-8"

        def __init__(self, payload: dict[str, object] | None = None, text: str = "") -> None:
            self._payload = payload or {}
            self.text = text

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self._payload

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, params: dict[str, object] | None = None) -> FakeResponse:
            if params is not None:
                assert params["q"] == "Agent evaluation"
                return FakeResponse(
                    payload={
                        "web": {
                            "results": [
                                {
                                    "title": "Agent evaluation platform",
                                    "url": "https://example.com/agents?ref=search",
                                    "description": (
                                        "A detailed article about agent evaluation, workflow "
                                        "tracing, and production reliability."
                                    ),
                                },
                                {
                                    "title": "LLM release notes",
                                    "url": "https://example.com/releases",
                                    "description": "New model release.",
                                },
                            ]
                        }
                    }
                )
            if url == "https://example.com/agents?ref=search":
                return FakeResponse(
                    text=(
                        "<html><head><title>Agent evaluation deep dive</title>"
                        '<meta name="description" content="A field guide to agent '
                        "evaluation, trace inspection, regression gates, production "
                        'reliability, and reviewer workflows."></head><body>'
                        + ("workflow traces and evaluator evidence " * 120)
                        + "</body></html>"
                    )
                )
            return FakeResponse(
                text="<html><head><title>LLM release notes</title></head><body>short</body></html>"
            )

    monkeypatch.setattr("contentops_providers.research.httpx.Client", FakeClient)

    packet = SearchResearchProvider(
        endpoint="https://search.example.com",
        api_key="secret",
        max_sources=2,
    ).collect(RunRequest(topic="Agent evaluation"))

    assert len(packet.sources) == 2
    assert packet.sources[0].title == "Agent evaluation deep dive"
    assert packet.sources[0].canonical_url == "https://example.com/agents"
    assert packet.sources[0].extraction_status == "search_enriched"
    assert packet.sources[0].extraction_quality > 0.68
    assert packet.sources[0].publisher == "example.com"


def test_search_research_falls_back_when_enrichment_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        headers = {"content-type": "application/json"}
        text = ""
        encoding = "utf-8"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "web": {
                    "results": [
                        {
                            "title": "Workflow reliability",
                            "url": "https://offline.example.com/report",
                            "description": (
                                "Search snippet about workflow reliability, evaluation, and "
                                "operator review."
                            ),
                        }
                    ]
                }
            }

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, params: dict[str, object] | None = None) -> FakeResponse:
            if params is not None:
                return FakeResponse()
            raise TimeoutError(f"{url} is unavailable")

    monkeypatch.setattr("contentops_providers.research.httpx.Client", FakeClient)

    packet = SearchResearchProvider(
        endpoint="https://search.example.com",
        api_key="secret",
        max_sources=1,
    ).collect(RunRequest(topic="Workflow reliability"))

    assert packet.sources[0].title == "Workflow reliability"
    assert packet.sources[0].extraction_status == "search"
    assert packet.sources[0].summary.startswith("Search snippet")


def test_github_research_collects_repository_readme_and_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64

    readme = base64.b64encode(
        b"# AI ContentOps Studio\n\n"
        b"A production-minded content operations platform for researching, "
        b"generating, evaluating, and publishing AI engineering articles."
    ).decode("ascii")

    class FakeResponse:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self._payload

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            headers = kwargs["headers"]
            assert isinstance(headers, dict)
            assert headers["Authorization"] == "Bearer github-token"
            assert headers["Accept"] == "application/vnd.github+json"

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(
            self,
            url: str,
            params: dict[str, object] | None = None,
        ) -> FakeResponse:
            if url.endswith("/repos/zemeng2015/ai-contentops-studio"):
                return FakeResponse(
                    {
                        "html_url": "https://github.com/zemeng2015/ai-contentops-studio",
                        "description": "AI content operations platform",
                        "language": "Python",
                        "stargazers_count": 7,
                        "forks_count": 1,
                        "open_issues_count": 3,
                    }
                )
            if url.endswith("/repos/zemeng2015/ai-contentops-studio/readme"):
                return FakeResponse(
                    {
                        "html_url": (
                            "https://github.com/zemeng2015/ai-contentops-studio/blob/main/"
                            "README.md"
                        ),
                        "content": readme,
                    }
                )
            if url.endswith("/repos/zemeng2015/ai-contentops-studio/issues"):
                assert params == {"state": "open", "per_page": 2}
                return FakeResponse(
                    [
                        {"title": "Add provider replay tests"},
                        {"title": "Improve dashboard source review"},
                    ]
                )
            if url.endswith("/repos/zemeng2015/ai-contentops-studio/pulls"):
                assert params == {"state": "open", "per_page": 2}
                return FakeResponse([{"title": "Ship GitHub research provider"}])
            raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("contentops_providers.research.httpx.Client", FakeClient)

    packet = GitHubResearchProvider(
        token="github-token",
        max_items=2,
        retry_backoff_seconds=0,
    ).collect(
        RunRequest(
            topic="AI content operations",
            source_urls=["https://github.com/zemeng2015/ai-contentops-studio"],
        )
    )

    titles = {source.title for source in packet.sources}
    assert "GitHub repository: zemeng2015/ai-contentops-studio" in titles
    assert "README: zemeng2015/ai-contentops-studio" in titles
    assert "GitHub issues: zemeng2015/ai-contentops-studio" in titles
    assert "GitHub pull requests: zemeng2015/ai-contentops-studio" in titles
    readme_source = next(source for source in packet.sources if source.title.startswith("README"))
    assert readme_source.extraction_status == "github_readme"
    assert "production-minded content operations platform" in readme_source.summary


def test_github_research_reports_missing_repository_urls() -> None:
    packet = GitHubResearchProvider().collect(RunRequest(topic="Portfolio launch"))

    assert packet.sources[0].extraction_status == "missing_input"
    assert "source_urls" in packet.sources[0].summary


def test_url_research_records_extraction_quality(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        headers = {"content-type": "text/html"}
        text = (
            "<html><head><title>Useful AI Source</title>"
            '<meta name="description" content="A long enough source summary about AI '
            'workflow evaluation, artifact review, source grounding, and publication gates.">'
            "</head><body><main>"
            + ("technical article content " * 120)
            + "</main></body></html>"
        )
        encoding = "utf-8"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("contentops_providers.research.httpx.Client", FakeClient)

    packet = URLResearchProvider().collect(
        RunRequest(topic="Source quality", source_urls=["https://example.com/post?ref=x#top"])
    )

    assert packet.sources[0].title == "Useful AI Source"
    assert packet.sources[0].canonical_url == "https://example.com/post"
    assert packet.sources[0].extraction_status == "ok"
    assert packet.sources[0].extraction_quality >= 0.85
    assert packet.sources[0].content_length > 1000


def test_url_research_retries_transient_fetch_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        headers = {"content-type": "text/html; charset=utf-8"}
        text = (
            "<html><head><title>Retry recovered source</title>"
            '<meta name="description" content="Recovered after a transient timeout.">'
            "</head><body>"
            + ("recovered source content " * 30)
            + "</body></html>"
        )
        encoding = "utf-8"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        calls = 0

        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str) -> FakeResponse:
            FakeClient.calls += 1
            if FakeClient.calls == 1:
                raise TimeoutError("temporary timeout")
            return FakeResponse()

    monkeypatch.setattr("contentops_providers.research.httpx.Client", FakeClient)

    packet = URLResearchProvider(
        retry_attempts=2,
        retry_backoff_seconds=0,
    ).collect(RunRequest(topic="Retry", source_urls=["https://example.com/retry"]))

    assert FakeClient.calls == 2
    assert packet.sources[0].title == "Retry recovered source"
    assert packet.sources[0].extraction_status == "ok"


def test_feed_research_discovers_and_ranks_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        text = """
        <rss><channel>
          <item>
            <title>LLM evaluation workflow patterns</title>
            <link>https://example.com/evals</link>
            <description>Evaluation gates for agent workflow reliability.</description>
          </item>
          <item>
            <title>Database release notes</title>
            <link>https://example.com/db</link>
            <description>Storage maintenance notes.</description>
          </item>
        </channel></rss>
        """

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("contentops_providers.research.httpx.Client", FakeClient)

    packet = FeedResearchProvider(
        feeds=["https://example.com/rss.xml"],
        max_sources=1,
    ).collect(RunRequest(topic="LLM evaluation workflow"))

    assert len(packet.sources) == 1
    assert packet.sources[0].title == "LLM evaluation workflow patterns"
    assert packet.sources[0].extraction_status == "feed"
    assert packet.sources[0].canonical_url == "https://example.com/evals"


def test_discovery_research_combines_feed_url_and_local_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch(self: URLResearchProvider, url: str) -> Source:
        return Source(
            title="Operator source",
            url=url,
            canonical_url=url,
            publisher="operator",
            summary="Operator supplied source for the run.",
            credibility=0.95,
            extraction_status="ok",
            extraction_quality=0.95,
        )

    class FakeFeedProvider(FeedResearchProvider):
        def collect(self, request: RunRequest) -> ResearchPacket:
            return ResearchPacket(
                topic=request.topic,
                sources=[
                    Source(
                        title="Discovered agent source",
                        url="https://example.com/agent",
                        canonical_url="https://example.com/agent",
                        publisher="example.com",
                        summary="Agent reliability and evaluation workflow signal.",
                        extraction_status="feed",
                    )
                ],
                claims=[
                    Claim(
                        text="Discovered agent source is relevant.",
                        source_title="Discovered agent source",
                    )
                ],
                engineering_signals=["Feed discovery works."],
                risks=["Feeds require curation."],
                project_implications=["Automate daily research jobs."],
            )

    monkeypatch.setattr(URLResearchProvider, "_fetch_source", fake_fetch)
    monkeypatch.setattr("contentops_providers.research.FeedResearchProvider", FakeFeedProvider)

    packet = DiscoveryResearchProvider(feeds=["https://example.com/rss.xml"]).collect(
        RunRequest(
            topic="Agent workflow evaluation",
            source_urls=["https://example.com/operator"],
        )
    )

    titles = {source.title for source in packet.sources}
    assert "Discovered agent source" in titles
    assert "Operator source" in titles
    assert "Portfolio project map" in titles


def _sample_research_packet() -> ResearchPacket:
    return ResearchPacket(
        topic="AI workflow reliability",
        sources=[
            Source(
                title="Test source",
                publisher="example.com",
                summary="A source about AI workflow reliability.",
                credibility=0.9,
            )
        ],
        claims=[
            Claim(
                text="AI workflows need evaluation gates.",
                source_title="Test source",
                confidence=0.9,
            )
        ],
        engineering_signals=["Model calls should be observable and resilient."],
        risks=["Transient provider failures can interrupt publishing."],
        project_implications=["Add retry and fallback controls to model providers."],
    )


def _sample_content_plan() -> ContentPlan:
    return ContentPlan(
        title="AI Workflow Reliability",
        slug="ai-workflow-reliability",
        audience="Applied AI engineering hiring managers",
        thesis="Reliable AI content systems need model provider controls.",
        outline=["Provider resilience", "Fallbacks", "Review"],
        keywords=["ai", "workflow", "reliability"],
    )
