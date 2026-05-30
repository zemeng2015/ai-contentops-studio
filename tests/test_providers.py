from __future__ import annotations

from pathlib import Path

import pytest
from contentops_core.factory import build_pipeline
from contentops_core.models import Draft, EvaluationReport, RunRecord, RunRequest, RunStatus, Source
from contentops_core.settings import Settings
from contentops_providers.research import HybridResearchProvider, URLResearchProvider
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
    assert any(source.title == "Portfolio project map" for source in packet.sources)
    assert any("Fetched source" in claim.source_title for claim in packet.claims)


def test_homepage_publisher_updates_post_grid(tmp_path: Path) -> None:
    homepage = tmp_path / "homepage"
    (homepage / "posts").mkdir(parents=True)
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


def test_openai_provider_requires_api_key(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'contentops.db'}",
        generator_provider="openai",
    )

    with pytest.raises(ValueError, match="CONTENTOPS_OPENAI_API_KEY"):
        build_pipeline(settings)
