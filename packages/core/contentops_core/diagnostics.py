from __future__ import annotations

from pathlib import Path

from contentops_core.models import (
    ComponentCheck,
    DeploymentCapability,
    DeploymentManifest,
    SystemStatus,
)
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


def deployment_manifest(
    settings: Settings,
    repository: RunRepository,
) -> DeploymentManifest:
    status = system_status(settings, repository)
    return DeploymentManifest(
        status=status.status,
        runtime=_runtime_fields(settings),
        security=_security_fields(settings),
        operations=_operations_fields(settings),
        capabilities=_capabilities(settings, status),
        checks=status.checks,
    )


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
    if settings.openai_timeout_seconds <= 0:
        failures.append("OpenAI timeout must be greater than 0")
    if settings.openai_retry_attempts < 1:
        failures.append("OpenAI retry attempts must be at least 1")
    if settings.openai_retry_backoff_seconds < 0:
        failures.append("OpenAI retry backoff cannot be negative")
    if settings.research_provider == "search" and not settings.research_search_api_key:
        failures.append("search research requires CONTENTOPS_RESEARCH_SEARCH_API_KEY")
    if settings.research_provider == "search" and not settings.research_search_endpoint:
        failures.append("search research requires CONTENTOPS_RESEARCH_SEARCH_ENDPOINT")
    if settings.research_retry_attempts < 1:
        failures.append("research retry attempts must be at least 1")
    if settings.research_retry_backoff_seconds < 0:
        failures.append("research retry backoff cannot be negative")
    if settings.notification_timeout_seconds <= 0:
        failures.append("notification timeout must be greater than 0")
    if settings.latency_slo_ms <= 0:
        failures.append("latency SLO must be greater than 0")
    if settings.min_source_count < 1:
        failures.append("minimum source count must be at least 1")
    if settings.token_budget_per_run < 1:
        failures.append("token budget per run must be at least 1")
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
            "research_retry_attempts": settings.research_retry_attempts,
            "research_retry_backoff_seconds": settings.research_retry_backoff_seconds,
            "research_search_enrich": settings.research_search_enrich,
            "generator_provider": settings.generator_provider,
            "openai_timeout_seconds": settings.openai_timeout_seconds,
            "openai_retry_attempts": settings.openai_retry_attempts,
            "openai_retry_backoff_seconds": settings.openai_retry_backoff_seconds,
            "openai_fallback_on_failure": settings.openai_fallback_on_failure,
            "publisher_provider": settings.publisher_provider,
            "notification_webhook_configured": settings.notification_webhook_url is not None,
            "notification_timeout_seconds": settings.notification_timeout_seconds,
            "latency_slo_ms": settings.latency_slo_ms,
            "min_source_count": settings.min_source_count,
            "token_budget_per_run": settings.token_budget_per_run,
            "warnings": warnings,
        },
    )


def _operator_security_check(settings: Settings) -> ComponentCheck:
    read_key_configured = settings.read_api_key is not None
    operator_key_configured = settings.operator_api_key is not None
    if settings.require_read_api_key and not (read_key_configured or operator_key_configured):
        return ComponentCheck(
            name="operator_security",
            status="fail",
            message=(
                "Read-route API key protection requires CONTENTOPS_READ_API_KEY "
                "or CONTENTOPS_OPERATOR_API_KEY."
            ),
            fields={"read_routes_protected": True, "read_api_key_configured": False},
        )
    if not operator_key_configured:
        return ComponentCheck(
            name="operator_security",
            status="degraded",
            message="Operator API key is not configured; mutating routes are unprotected.",
            fields={
                "read_routes_protected": settings.require_read_api_key,
                "read_api_key_configured": read_key_configured,
            },
        )
    read_message = " Read routes are also protected." if settings.require_read_api_key else ""
    return ComponentCheck(
        name="operator_security",
        status="ok",
        message=f"Operator API key is configured.{read_message}",
        fields={
            "read_routes_protected": settings.require_read_api_key,
            "read_api_key_configured": read_key_configured,
        },
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


def _runtime_fields(settings: Settings) -> dict[str, object]:
    return {
        "database_engine": _database_engine(settings.database_url),
        "artifact_store_provider": settings.artifact_store_provider,
        "artifact_s3_bucket_configured": settings.artifact_s3_bucket is not None,
        "research_provider": settings.research_provider,
        "generator_provider": settings.generator_provider,
        "publisher_provider": settings.publisher_provider,
        "public_base_url": settings.public_base_url,
        "homepage_public_base_url": settings.homepage_public_base_url,
    }


def _security_fields(settings: Settings) -> dict[str, object]:
    return {
        "operator_credentials_configured": settings.operator_api_key is not None,
        "read_credentials_configured": settings.read_api_key is not None,
        "read_routes_protected": settings.require_read_api_key,
        "model_credentials_configured": settings.openai_api_key is not None,
        "search_credentials_configured": settings.research_search_api_key is not None,
        "notification_webhook_configured": settings.notification_webhook_url is not None,
    }


def _operations_fields(settings: Settings) -> dict[str, object]:
    return {
        "latency_slo_ms": settings.latency_slo_ms,
        "min_source_count": settings.min_source_count,
        "token_budget_per_run": settings.token_budget_per_run,
        "research_retry_attempts": settings.research_retry_attempts,
        "openai_retry_attempts": settings.openai_retry_attempts,
        "openai_fallback_on_failure": settings.openai_fallback_on_failure,
        "notification_timeout_seconds": settings.notification_timeout_seconds,
    }


def _capabilities(
    settings: Settings,
    status: SystemStatus,
) -> list[DeploymentCapability]:
    cloud_status = "ok"
    if settings.database_url.startswith("sqlite"):
        cloud_status = "degraded"
    if status.status == "fail":
        cloud_status = "fail"
    return [
        DeploymentCapability(
            name="run_orchestration",
            status="ok",
            evidence=["POST /runs", "contentops run", "contentops-worker run-pipeline"],
        ),
        DeploymentCapability(
            name="review_governance",
            status="ok",
            evidence=[
                "approval.json",
                "audit-log.json",
                "scorecard approval gate",
                "token budget approval gate",
            ],
        ),
        DeploymentCapability(
            name="publishing_recovery",
            status="ok",
            evidence=[
                "publish-receipt.json",
                "publish-verification.json",
                "publish-rollback.json",
            ],
        ),
        DeploymentCapability(
            name="incident_operations",
            status="ok",
            evidence=["/incident-reports", "/ops-summary", "contentops incident-report"],
        ),
        DeploymentCapability(
            name="aws_deployment_ready",
            status=cloud_status,
            evidence=["Terraform ECS/RDS/S3/EventBridge baseline", "Docker API image"],
        ),
    ]


def _database_engine(database_url: str) -> str:
    if database_url.startswith("sqlite"):
        return "sqlite"
    if database_url.startswith("postgresql"):
        return "postgresql"
    return database_url.split(":", 1)[0] or "unknown"
