from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONTENTOPS_", env_file=".env", extra="ignore")

    artifact_root: Path = Path("artifacts")
    artifact_store_provider: str = "local"
    artifact_s3_bucket: str | None = None
    artifact_s3_prefix: str = "contentops-artifacts"
    database_url: str = "sqlite:///contentops.db"
    site_output_dir: Path = Path("site")
    public_base_url: str = "http://localhost:8000/site"
    min_publish_score: float = 0.72
    research_provider: str = "hybrid"
    research_feeds: str = (
        "https://export.arxiv.org/api/query?"
        "search_query=cat:cs.AI%20OR%20cat:cs.CL%20OR%20cat:cs.LG"
        "&start=0&max_results=25&sortBy=submittedDate&sortOrder=descending"
    )
    research_max_sources: int = 6
    research_retry_attempts: int = 2
    research_retry_backoff_seconds: float = 0.1
    research_search_endpoint: str = "https://api.search.brave.com/res/v1/web/search"
    research_search_api_key: str | None = None
    research_search_enrich: bool = True
    generator_provider: str = "template"
    publisher_provider: str = "static"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    openai_timeout_seconds: float = 60.0
    openai_retry_attempts: int = 2
    openai_retry_backoff_seconds: float = 0.5
    openai_fallback_on_failure: bool = True
    operator_api_key: SecretStr | None = None
    homepage_repo_path: Path | None = None
    homepage_public_base_url: str = "https://zemeng2015.github.io/zack-ai-homepage"
