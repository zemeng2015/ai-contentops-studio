from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONTENTOPS_", env_file=".env", extra="ignore")

    artifact_root: Path = Path("artifacts")
    database_url: str = "sqlite:///contentops.db"
    site_output_dir: Path = Path("site")
    public_base_url: str = "http://localhost:8000/site"
    min_publish_score: float = 0.72
    research_provider: str = "hybrid"
    generator_provider: str = "template"
    publisher_provider: str = "static"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    homepage_repo_path: Path | None = None
    homepage_public_base_url: str = "https://zemeng2015.github.io/zack-ai-homepage"
