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

