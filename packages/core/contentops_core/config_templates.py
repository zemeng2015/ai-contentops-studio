from __future__ import annotations

DEFAULT_RESEARCH_FEEDS = (
    "https://export.arxiv.org/api/query?"
    "search_query=cat:cs.AI%20OR%20cat:cs.CL%20OR%20cat:cs.LG"
    "&start=0&max_results=25&sortBy=submittedDate&sortOrder=descending"
)


def render_env_template(profile: str = "local") -> str:
    if profile == "local":
        return _join(_local_template_lines())
    if profile == "production":
        return _join(_production_template_lines())
    raise ValueError(f"Unknown config profile: {profile}")


def _join(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def _local_template_lines() -> list[str]:
    return [
        "CONTENTOPS_ARTIFACT_ROOT=artifacts",
        "CONTENTOPS_ARTIFACT_STORE_PROVIDER=local",
        "# CONTENTOPS_ARTIFACT_S3_BUCKET=",
        "CONTENTOPS_ARTIFACT_S3_PREFIX=contentops-artifacts",
        "CONTENTOPS_DATABASE_URL=sqlite:///contentops.db",
        "CONTENTOPS_PIPELINE_DIR=pipelines",
        "CONTENTOPS_SITE_OUTPUT_DIR=site",
        "CONTENTOPS_PUBLIC_BASE_URL=http://localhost:8000/site",
        "CONTENTOPS_MIN_PUBLISH_SCORE=0.72",
        "CONTENTOPS_RESEARCH_PROVIDER=discovery",
        f"CONTENTOPS_RESEARCH_FEEDS={DEFAULT_RESEARCH_FEEDS}",
        "CONTENTOPS_RESEARCH_MAX_SOURCES=6",
        "CONTENTOPS_RESEARCH_RETRY_ATTEMPTS=2",
        "CONTENTOPS_RESEARCH_RETRY_BACKOFF_SECONDS=0.1",
        "# CONTENTOPS_RESEARCH_CACHE_DIR=artifacts/research-cache",
        "CONTENTOPS_RESEARCH_CACHE_TTL_SECONDS=86400",
        "CONTENTOPS_RESEARCH_SEARCH_ENDPOINT=https://api.search.brave.com/res/v1/web/search",
        "# CONTENTOPS_RESEARCH_SEARCH_API_KEY=",
        "CONTENTOPS_RESEARCH_SEARCH_ENRICH=true",
        "CONTENTOPS_RESEARCH_GITHUB_API_BASE_URL=https://api.github.com",
        "# CONTENTOPS_RESEARCH_GITHUB_TOKEN=",
        "CONTENTOPS_GENERATOR_PROVIDER=template",
        "CONTENTOPS_PUBLISHER_PROVIDER=static",
        "CONTENTOPS_OPENAI_MODEL=gpt-5-mini",
        "CONTENTOPS_OPENAI_TIMEOUT_SECONDS=60",
        "CONTENTOPS_OPENAI_RETRY_ATTEMPTS=2",
        "CONTENTOPS_OPENAI_RETRY_BACKOFF_SECONDS=0.5",
        "CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true",
        "# CONTENTOPS_OPENAI_API_KEY=",
        "# CONTENTOPS_OPERATOR_API_KEY=",
        "# CONTENTOPS_READ_API_KEY=",
        "CONTENTOPS_REQUIRE_READ_API_KEY=false",
        "# CONTENTOPS_NOTIFICATION_WEBHOOK_URL=",
        "CONTENTOPS_NOTIFICATION_TIMEOUT_SECONDS=5",
        "CONTENTOPS_LATENCY_SLO_MS=120000",
        "CONTENTOPS_MIN_SOURCE_COUNT=1",
        "CONTENTOPS_TOKEN_BUDGET_PER_RUN=12000",
        "# CONTENTOPS_HOMEPAGE_REPO_PATH=C:\\path\\to\\zack-ai-homepage",
        "# CONTENTOPS_HOMEPAGE_PUBLIC_BASE_URL=https://zemeng2015.github.io/zack-ai-homepage",
    ]


def _production_template_lines() -> list[str]:
    return [
        "# Production template. Replace placeholder values before deployment.",
        "CONTENTOPS_ARTIFACT_ROOT=/data/artifacts",
        "CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3",
        "CONTENTOPS_ARTIFACT_S3_BUCKET=replace-with-artifact-bucket",
        "CONTENTOPS_ARTIFACT_S3_PREFIX=contentops-artifacts",
        "CONTENTOPS_DATABASE_URL=postgresql+psycopg://contentops:replace-with-password@replace-with-host:5432/contentops",
        "CONTENTOPS_RUN_MIGRATIONS=true",
        "CONTENTOPS_PIPELINE_DIR=pipelines",
        "CONTENTOPS_SITE_OUTPUT_DIR=/data/site",
        "CONTENTOPS_PUBLIC_BASE_URL=https://contentops.example.com/site",
        "CONTENTOPS_MIN_PUBLISH_SCORE=0.72",
        "CONTENTOPS_RESEARCH_PROVIDER=discovery",
        f"CONTENTOPS_RESEARCH_FEEDS={DEFAULT_RESEARCH_FEEDS}",
        "CONTENTOPS_RESEARCH_MAX_SOURCES=6",
        "CONTENTOPS_RESEARCH_RETRY_ATTEMPTS=2",
        "CONTENTOPS_RESEARCH_RETRY_BACKOFF_SECONDS=0.1",
        "CONTENTOPS_RESEARCH_CACHE_DIR=/data/artifacts/research-cache",
        "CONTENTOPS_RESEARCH_CACHE_TTL_SECONDS=86400",
        "CONTENTOPS_RESEARCH_SEARCH_ENDPOINT=https://api.search.brave.com/res/v1/web/search",
        "CONTENTOPS_RESEARCH_SEARCH_API_KEY=replace-with-search-key",
        "CONTENTOPS_RESEARCH_SEARCH_ENRICH=true",
        "CONTENTOPS_RESEARCH_GITHUB_API_BASE_URL=https://api.github.com",
        "CONTENTOPS_RESEARCH_GITHUB_TOKEN=replace-with-github-token",
        "CONTENTOPS_GENERATOR_PROVIDER=openai",
        "CONTENTOPS_OPENAI_API_KEY=replace-with-openai-key",
        "CONTENTOPS_OPENAI_MODEL=gpt-5-mini",
        "CONTENTOPS_OPENAI_TIMEOUT_SECONDS=60",
        "CONTENTOPS_OPENAI_RETRY_ATTEMPTS=2",
        "CONTENTOPS_OPENAI_RETRY_BACKOFF_SECONDS=0.5",
        "CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true",
        "CONTENTOPS_PUBLISHER_PROVIDER=homepage",
        "CONTENTOPS_HOMEPAGE_REPO_PATH=/data/homepage",
        "CONTENTOPS_HOMEPAGE_PUBLIC_BASE_URL=https://zemeng2015.github.io/zack-ai-homepage",
        "CONTENTOPS_OPERATOR_API_KEY=replace-with-long-random-operator-key",
        "CONTENTOPS_READ_API_KEY=replace-with-long-random-read-key",
        "CONTENTOPS_REQUIRE_READ_API_KEY=true",
        "CONTENTOPS_NOTIFICATION_WEBHOOK_URL=",
        "CONTENTOPS_NOTIFICATION_TIMEOUT_SECONDS=5",
        "CONTENTOPS_LATENCY_SLO_MS=120000",
        "CONTENTOPS_MIN_SOURCE_COUNT=1",
        "CONTENTOPS_TOKEN_BUDGET_PER_RUN=12000",
    ]
