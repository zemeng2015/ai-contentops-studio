from __future__ import annotations

from pathlib import Path

from contentops_core.models import ComponentCheck, SystemStatus
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings

RESEARCH_PROVIDERS = {"local", "url", "hybrid", "feed", "discovery", "search"}
GENERATOR_PROVIDERS = {"template", "openai"}
PUBLISHER_PROVIDERS = {"static", "homepage"}
ARTIFACT_STORE_PROVIDERS = {"local", "s3"}


def system_status(settings: Settings, repository: RunRepository) -> SystemStatus:
    checks = [
        _database_check(repository),
        _artifact_store_check(settings),
        _provider_config_check(settings),
        _operator_security_check(settings),
    ]
    return SystemStatus(status=_overall_status(checks), checks=checks)


def _database_check(repository: RunRepository) -> ComponentCheck:
    try:
        repository.ping()
    except Exception as exc:
        return ComponentCheck(
            name="database",
            status="fail",
            message="Database connectivity check failed.",
            fields={"error": str(exc)},
        )
    return ComponentCheck(
        name="database",
        status="ok",
        message="Database is reachable.",
    )


def _artifact_store_check(settings: Settings) -> ComponentCheck:
    if settings.artifact_store_provider not in ARTIFACT_STORE_PROVIDERS:
        return ComponentCheck(
            name="artifact_store",
            status="fail",
            message="Unknown artifact store provider.",
            fields={"provider": settings.artifact_store_provider},
        )
    if settings.artifact_store_provider == "s3":
        if not settings.artifact_s3_bucket:
            return ComponentCheck(
                name="artifact_store",
                status="fail",
                message="S3 artifact storage requires CONTENTOPS_ARTIFACT_S3_BUCKET.",
            )
        return ComponentCheck(
            name="artifact_store",
            status="ok",
            message="S3 artifact mirroring is configured.",
            fields={"provider": "s3", "bucket_configured": True},
        )
    return _local_artifact_store_check(settings.artifact_root)


def _local_artifact_store_check(root: Path) -> ComponentCheck:
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".contentops-healthcheck"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return ComponentCheck(
            name="artifact_store",
            status="fail",
            message="Local artifact root is not writable.",
            fields={"root": str(root), "error": str(exc)},
        )
    return ComponentCheck(
        name="artifact_store",
        status="ok",
        message="Local artifact root is writable.",
        fields={"root": str(root)},
    )


def _provider_config_check(settings: Settings) -> ComponentCheck:
    failures: list[str] = []
    warnings: list[str] = []
    if settings.research_provider not in RESEARCH_PROVIDERS:
        failures.append(f"unknown research provider: {settings.research_provider}")
    if settings.generator_provider not in GENERATOR_PROVIDERS:
        failures.append(f"unknown generator provider: {settings.generator_provider}")
    if settings.publisher_provider not in PUBLISHER_PROVIDERS:
        failures.append(f"unknown publisher provider: {settings.publisher_provider}")
    if settings.generator_provider == "openai" and not settings.openai_api_key:
        failures.append("OpenAI generation requires CONTENTOPS_OPENAI_API_KEY")
    if settings.research_provider == "search" and not settings.research_search_api_key:
        failures.append("search research requires CONTENTOPS_RESEARCH_SEARCH_API_KEY")
    if settings.research_provider == "search" and not settings.research_search_endpoint:
        failures.append("search research requires CONTENTOPS_RESEARCH_SEARCH_ENDPOINT")
    if settings.publisher_provider == "homepage" and settings.homepage_repo_path is None:
        failures.append("homepage publishing requires CONTENTOPS_HOMEPAGE_REPO_PATH")
    if settings.research_provider in {"feed", "discovery"} and not _research_feeds(settings):
        warnings.append("feed/discovery research has no configured feeds")
    if failures:
        return ComponentCheck(
            name="provider_config",
            status="fail",
            message="Provider configuration is invalid.",
            fields={"failures": failures, "warnings": warnings},
        )
    status = "degraded" if warnings else "ok"
    message = "Provider configuration has warnings." if warnings else "Providers are configured."
    return ComponentCheck(
        name="provider_config",
        status=status,
        message=message,
        fields={
            "research_provider": settings.research_provider,
            "research_search_enrich": settings.research_search_enrich,
            "generator_provider": settings.generator_provider,
            "publisher_provider": settings.publisher_provider,
            "warnings": warnings,
        },
    )


def _operator_security_check(settings: Settings) -> ComponentCheck:
    if settings.operator_api_key is None:
        return ComponentCheck(
            name="operator_security",
            status="degraded",
            message="Operator API key is not configured; mutating routes are unprotected.",
        )
    return ComponentCheck(
        name="operator_security",
        status="ok",
        message="Operator API key is configured.",
    )


def _research_feeds(settings: Settings) -> list[str]:
    return [feed.strip() for feed in settings.research_feeds.split(",") if feed.strip()]


def _overall_status(checks: list[ComponentCheck]) -> str:
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        return "fail"
    if "degraded" in statuses:
        return "degraded"
    return "ok"
