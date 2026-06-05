from __future__ import annotations

from pathlib import Path

from contentops_core.config_templates import render_env_template
from contentops_core.models import (
    ComponentCheck,
    DeploymentCapability,
    DeploymentCheckItem,
    DeploymentCheckReport,
    DeploymentManifest,
    OperationsSummary,
    ProviderHealthItem,
    ProviderHealthReport,
    ReleaseGateCheck,
    ReleaseReadinessReport,
    SystemStatus,
)
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings

RESEARCH_PROVIDERS = {"local", "url", "hybrid", "feed", "discovery", "search", "github"}
GENERATOR_PROVIDERS = {"template", "openai"}
PUBLISHER_PROVIDERS = {"static", "homepage"}
ARTIFACT_STORE_PROVIDERS = {"local", "s3"}
SCHEDULED_RESEARCH_PROVIDERS = {"feed", "discovery", "search", "github"}


def system_status(settings: Settings, repository: RunRepository) -> SystemStatus:
    checks = [
        _database_check(repository),
        _artifact_store_check(settings),
        _provider_config_check(settings),
        _operator_security_check(settings),
    ]
    return SystemStatus(status=_overall_status(checks), checks=checks)


def provider_health(settings: Settings) -> ProviderHealthReport:
    items = [
        _research_provider_health(settings),
        _generator_provider_health(settings),
        _publisher_provider_health(settings),
    ]
    summary = {
        "pass": sum(1 for item in items if item.status == "pass"),
        "warn": sum(1 for item in items if item.status == "warn"),
        "fail": sum(1 for item in items if item.status == "fail"),
        "scheduled_ready": sum(1 for item in items if item.scheduled_ready),
        "credentialed": sum(1 for item in items if item.credential_configured),
    }
    status = "fail" if summary["fail"] else "warn" if summary["warn"] else "pass"
    return ProviderHealthReport(status=status, items=items, summary=summary)


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


def release_readiness(
    settings: Settings,
    repository: RunRepository,
    operations: OperationsSummary,
) -> ReleaseReadinessReport:
    deployment = deployment_manifest(settings, repository)
    checks = [
        _readiness_gate(deployment),
        _deployment_capability_gate(deployment),
        _incident_gate(operations),
        _quality_gate(operations),
        _budget_gate(operations),
        _security_gate(deployment),
    ]
    status = _release_status(checks)
    return ReleaseReadinessReport(
        status=status,
        can_release=status != "fail",
        checks=checks,
        operations=operations,
        deployment=deployment,
    )


def deployment_check(
    settings: Settings,
    repository: RunRepository,
    operations: OperationsSummary,
    profile: str = "production",
) -> DeploymentCheckReport:
    deployment = deployment_manifest(settings, repository)
    readiness = release_readiness(settings, repository, operations)
    checks = [
        _deployment_status_check(deployment),
        _release_gate_check(readiness),
        _capability_status_check(deployment),
        _security_configuration_check(deployment),
        _production_template_check(profile),
    ]
    status = _deployment_check_status(checks)
    return DeploymentCheckReport(
        profile=profile,
        status=status,
        can_deploy=status != "fail",
        checks=checks,
        deployment=deployment,
        release_readiness=readiness,
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
    health = provider_health(settings)
    research_readiness = _research_provider_readiness(settings)
    publishing_readiness = _publishing_readiness(settings)
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
    if settings.research_provider == "github" and not settings.research_github_api_base_url:
        failures.append("github research requires CONTENTOPS_RESEARCH_GITHUB_API_BASE_URL")
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
    publishing_warnings = publishing_readiness.get("warnings", [])
    if isinstance(publishing_warnings, list):
        warnings.extend(str(warning) for warning in publishing_warnings)
    if settings.research_provider in {"feed", "discovery"} and not _research_feeds(settings):
        warnings.append("feed/discovery research has no configured feeds")
    research_warnings = research_readiness.get("warnings", [])
    if isinstance(research_warnings, list):
        warnings.extend(str(warning) for warning in research_warnings)
    if failures:
        return ComponentCheck(
            name="provider_config",
            status="fail",
            message="Provider configuration is invalid.",
            fields={
                "failures": failures,
                "warnings": warnings,
                "provider_health": health.model_dump(mode="json"),
                "research_readiness": research_readiness,
                "publishing_readiness": publishing_readiness,
            },
        )
    status = "degraded" if warnings else "ok"
    message = "Provider configuration has warnings." if warnings else "Providers are configured."
    return ComponentCheck(
        name="provider_config",
        status=status,
        message=message,
        fields={
            "research_provider": settings.research_provider,
            "provider_health": health.model_dump(mode="json"),
            "research_readiness": research_readiness,
            "publishing_readiness": publishing_readiness,
            "research_retry_attempts": settings.research_retry_attempts,
            "research_retry_backoff_seconds": settings.research_retry_backoff_seconds,
            "research_cache_enabled": settings.research_cache_dir is not None,
            "research_cache_dir": (
                str(settings.research_cache_dir) if settings.research_cache_dir else None
            ),
            "research_cache_ttl_seconds": settings.research_cache_ttl_seconds,
            "research_search_enrich": settings.research_search_enrich,
            "research_github_token_configured": settings.research_github_token is not None,
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


def _research_provider_health(settings: Settings) -> ProviderHealthItem:
    readiness = _research_provider_readiness(settings)
    warnings = _string_list_field(readiness.get("warnings"))
    configured = settings.research_provider in RESEARCH_PROVIDERS
    credential_required = bool(readiness.get("credential_required"))
    credential_configured = bool(readiness.get("credential_configured"))
    scheduled_ready = bool(readiness.get("scheduled_ready"))
    status = "pass"
    if not configured or (credential_required and not credential_configured):
        status = "fail"
    elif warnings or not scheduled_ready:
        status = "warn"
    return ProviderHealthItem(
        name=settings.research_provider,
        category="research",
        status=status,
        mode=str(readiness.get("mode", "unknown")),
        configured=configured,
        credential_required=credential_required,
        credential_configured=credential_configured,
        scheduled_ready=scheduled_ready,
        warnings=warnings,
        evidence={
            "feeds_configured": readiness.get("feeds_configured"),
            "feed_count": len(_research_feeds(settings)),
            "max_sources": settings.research_max_sources,
            "search_endpoint_configured": readiness.get("search_endpoint_configured"),
            "search_enrich": settings.research_search_enrich,
            "github_token_recommended": readiness.get("github_token_recommended"),
            "retry_attempts": settings.research_retry_attempts,
            "retry_backoff_seconds": settings.research_retry_backoff_seconds,
            "cache_enabled": settings.research_cache_dir is not None,
            "cache_ttl_seconds": settings.research_cache_ttl_seconds,
        },
    )


def _generator_provider_health(settings: Settings) -> ProviderHealthItem:
    warnings: list[str] = []
    configured = settings.generator_provider in GENERATOR_PROVIDERS
    credential_required = settings.generator_provider == "openai"
    credential_configured = not credential_required or settings.openai_api_key is not None
    if settings.generator_provider == "template":
        warnings.append("Template generator is deterministic but not a real model provider.")
    if settings.openai_fallback_on_failure and settings.generator_provider == "openai":
        warnings.append("OpenAI generation fallback is enabled; receipts should be reviewed.")
    status = "pass"
    if not configured or not credential_configured:
        status = "fail"
    elif warnings:
        status = "warn"
    return ProviderHealthItem(
        name=settings.generator_provider,
        category="generator",
        status=status,
        mode="llm" if settings.generator_provider == "openai" else "deterministic",
        configured=configured,
        credential_required=credential_required,
        credential_configured=credential_configured,
        scheduled_ready=configured and credential_configured,
        warnings=warnings,
        evidence={
            "model": settings.openai_model if settings.generator_provider == "openai" else "n/a",
            "timeout_seconds": settings.openai_timeout_seconds,
            "retry_attempts": settings.openai_retry_attempts,
            "retry_backoff_seconds": settings.openai_retry_backoff_seconds,
            "fallback_on_failure": settings.openai_fallback_on_failure,
        },
    )


def _publisher_provider_health(settings: Settings) -> ProviderHealthItem:
    readiness = _publishing_readiness(settings)
    warnings = _string_list_field(readiness.get("warnings"))
    configured = settings.publisher_provider in PUBLISHER_PROVIDERS
    ready = bool(readiness.get("ready"))
    status = "fail" if not configured or not ready else "warn" if warnings else "pass"
    return ProviderHealthItem(
        name=settings.publisher_provider,
        category="publisher",
        status=status,
        mode=str(readiness.get("mode", "unknown")),
        configured=configured,
        credential_required=False,
        credential_configured=True,
        scheduled_ready=ready,
        warnings=warnings,
        evidence={
            "target_url": readiness.get("target_url"),
            "output_dir": readiness.get("output_dir"),
            "homepage_repo_path": readiness.get("homepage_repo_path"),
        },
    )


def _string_list_field(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _research_provider_readiness(settings: Settings) -> dict[str, object]:
    provider = settings.research_provider
    warnings: list[str] = []
    credential_required = provider in {"search"}
    credential_configured = _research_provider_credential_configured(settings)
    scheduled_ready = provider in SCHEDULED_RESEARCH_PROVIDERS
    if provider == "search" and not settings.research_search_api_key:
        scheduled_ready = False
    if provider in {"feed", "discovery"} and not _research_feeds(settings):
        scheduled_ready = False
    if provider == "github" and not settings.research_github_token:
        warnings.append(
            "GitHub research can use public unauthenticated API calls, but a token is recommended "
            "for scheduled workers and private repositories."
        )
    if provider in {"local", "hybrid", "url"}:
        warnings.append(
            "Research provider is useful for local/manual runs but does not discover new sources "
            "for scheduled automation."
        )
    return {
        "provider": provider,
        "mode": _research_provider_mode(provider),
        "scheduled_ready": scheduled_ready,
        "credential_required": credential_required,
        "credential_configured": credential_configured,
        "feeds_configured": bool(_research_feeds(settings)),
        "search_endpoint_configured": bool(settings.research_search_endpoint),
        "github_token_recommended": provider == "github",
        "warnings": warnings,
    }


def _research_provider_credential_configured(settings: Settings) -> bool:
    if settings.research_provider == "search":
        return settings.research_search_api_key is not None
    if settings.research_provider == "github":
        return settings.research_github_token is not None
    return True


def _research_provider_mode(provider: str) -> str:
    if provider in {"local", "hybrid", "url"}:
        return "manual"
    if provider in {"feed", "discovery"}:
        return "curated_discovery"
    if provider == "search":
        return "credentialed_open_web"
    if provider == "github":
        return "repository_intelligence"
    return "unknown"


def _publishing_readiness(settings: Settings) -> dict[str, object]:
    provider = settings.publisher_provider
    warnings: list[str] = []
    ready = provider in PUBLISHER_PROVIDERS
    fields: dict[str, object] = {
        "provider": provider,
        "ready": ready,
        "mode": _publisher_mode(provider),
        "target_url": settings.homepage_public_base_url
        if provider == "homepage"
        else settings.public_base_url,
        "warnings": warnings,
    }
    if provider == "static":
        fields["output_dir"] = str(settings.site_output_dir)
        if not _path_is_writable(settings.site_output_dir):
            ready = False
            warnings.append(
                f"Static site output directory is not writable: {settings.site_output_dir}"
            )
    elif provider == "homepage":
        fields["homepage_repo_path"] = str(settings.homepage_repo_path or "")
        if settings.homepage_repo_path is None:
            ready = False
            warnings.append("Homepage publisher requires CONTENTOPS_HOMEPAGE_REPO_PATH.")
        elif not settings.homepage_repo_path.exists():
            ready = False
            warnings.append(
                f"Homepage repository path does not exist: {settings.homepage_repo_path}"
            )
        else:
            index_path = settings.homepage_repo_path / "index.html"
            fields["homepage_index_exists"] = index_path.exists()
            if not index_path.exists():
                ready = False
                warnings.append(f"Homepage index not found: {index_path}")
            else:
                html = index_path.read_text(encoding="utf-8")
                has_post_grid = '<div class="post-grid">' in html
                fields["homepage_post_grid_marker"] = has_post_grid
                if not has_post_grid:
                    ready = False
                    warnings.append(
                        "Homepage index.html does not contain the expected post-grid marker."
                    )
            posts_dir = settings.homepage_repo_path / "posts"
            fields["posts_dir"] = str(posts_dir)
            if not _path_is_writable(posts_dir):
                ready = False
                warnings.append(f"Homepage posts directory is not writable: {posts_dir}")
    fields["ready"] = ready
    return fields


def _publisher_mode(provider: str) -> str:
    if provider == "static":
        return "filesystem_static_site"
    if provider == "homepage":
        return "homepage_repository"
    return "unknown"


def _path_is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".contentops-write-check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError:
        return False
    return True


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
        "research_readiness": _research_provider_readiness(settings),
        "generator_provider": settings.generator_provider,
        "publisher_provider": settings.publisher_provider,
        "publishing_readiness": _publishing_readiness(settings),
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
        "github_credentials_configured": settings.research_github_token is not None,
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
    research_readiness = _research_provider_readiness(settings)
    research_status = "ok" if research_readiness["scheduled_ready"] else "degraded"
    publishing_readiness = _publishing_readiness(settings)
    publishing_status = "ok" if publishing_readiness["ready"] else "fail"
    if status.status == "fail":
        research_status = "fail"
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
            status=publishing_status,
            evidence=[
                f"publisher_provider={settings.publisher_provider}",
                f"mode={publishing_readiness['mode']}",
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
            name="scheduled_research_ready",
            status=research_status,
            evidence=[
                f"research_provider={settings.research_provider}",
                f"mode={research_readiness['mode']}",
                f"scheduled_ready={str(research_readiness['scheduled_ready']).lower()}",
            ],
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


def _readiness_gate(deployment: DeploymentManifest) -> ReleaseGateCheck:
    if deployment.status == "fail":
        return ReleaseGateCheck(
            name="system_readiness",
            status="fail",
            message="Readiness checks are failing.",
            evidence={"status": deployment.status},
        )
    if deployment.status == "degraded":
        return ReleaseGateCheck(
            name="system_readiness",
            status="warn",
            message="Readiness checks are degraded but not failing.",
            evidence={"status": deployment.status},
        )
    return ReleaseGateCheck(
        name="system_readiness",
        status="pass",
        message="Readiness checks are passing.",
        evidence={"status": deployment.status},
    )


def _deployment_capability_gate(deployment: DeploymentManifest) -> ReleaseGateCheck:
    failed = [item.name for item in deployment.capabilities if item.status == "fail"]
    degraded = [item.name for item in deployment.capabilities if item.status == "degraded"]
    if failed:
        return ReleaseGateCheck(
            name="deployment_capabilities",
            status="fail",
            message="One or more deployment capabilities are failing.",
            evidence={"failed": failed, "degraded": degraded},
        )
    if degraded:
        return ReleaseGateCheck(
            name="deployment_capabilities",
            status="warn",
            message="One or more deployment capabilities are degraded.",
            evidence={"degraded": degraded},
        )
    return ReleaseGateCheck(
        name="deployment_capabilities",
        status="pass",
        message="Deployment capabilities are ready.",
    )


def _incident_gate(operations: OperationsSummary) -> ReleaseGateCheck:
    if operations.critical_incidents > 0 or operations.action_required_incidents > 0:
        return ReleaseGateCheck(
            name="incident_posture",
            status="fail",
            message="Open incidents require action before release.",
            evidence={
                "critical_incidents": operations.critical_incidents,
                "action_required_incidents": operations.action_required_incidents,
            },
        )
    if operations.failed_count > 0 or operations.warning_incidents > 0:
        return ReleaseGateCheck(
            name="incident_posture",
            status="warn",
            message="Recent failed runs or warning incidents should be reviewed.",
            evidence={
                "failed_count": operations.failed_count,
                "warning_incidents": operations.warning_incidents,
            },
        )
    return ReleaseGateCheck(
        name="incident_posture",
        status="pass",
        message="No release-blocking incidents are open.",
    )


def _quality_gate(operations: OperationsSummary) -> ReleaseGateCheck:
    if operations.total_runs == 0:
        return ReleaseGateCheck(
            name="quality_posture",
            status="warn",
            message="No runs exist yet, so quality posture is unproven.",
        )
    if operations.quality_pass_rate < 1:
        return ReleaseGateCheck(
            name="quality_posture",
            status="warn",
            message="Some recent runs did not pass quality gates.",
            evidence={"quality_pass_rate": operations.quality_pass_rate},
        )
    return ReleaseGateCheck(
        name="quality_posture",
        status="pass",
        message="Recent runs pass quality gates.",
        evidence={"quality_pass_rate": operations.quality_pass_rate},
    )


def _budget_gate(operations: OperationsSummary) -> ReleaseGateCheck:
    if operations.total_runs == 0:
        return ReleaseGateCheck(
            name="budget_posture",
            status="warn",
            message="No runs exist yet, so budget posture is unproven.",
        )
    if operations.budget_pass_rate < 1:
        return ReleaseGateCheck(
            name="budget_posture",
            status="warn",
            message="Some recent runs exceeded the token budget.",
            evidence={"budget_pass_rate": operations.budget_pass_rate},
        )
    return ReleaseGateCheck(
        name="budget_posture",
        status="pass",
        message="Recent runs pass budget gates.",
        evidence={"budget_pass_rate": operations.budget_pass_rate},
    )


def _security_gate(deployment: DeploymentManifest) -> ReleaseGateCheck:
    protected = bool(deployment.security.get("read_routes_protected"))
    operator_configured = bool(
        deployment.security.get("operator_credentials_configured")
    )
    if not operator_configured:
        return ReleaseGateCheck(
            name="operator_security",
            status="warn",
            message="Operator credentials are not configured.",
            evidence={"read_routes_protected": protected},
        )
    return ReleaseGateCheck(
        name="operator_security",
        status="pass",
        message="Operator credentials are configured.",
        evidence={"read_routes_protected": protected},
    )


def _release_status(checks: list[ReleaseGateCheck]) -> str:
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def _deployment_status_check(deployment: DeploymentManifest) -> DeploymentCheckItem:
    if deployment.status == "fail":
        return DeploymentCheckItem(
            name="system_status",
            status="fail",
            message="System readiness has failing checks.",
            evidence={"status": deployment.status},
        )
    if deployment.status == "degraded":
        return DeploymentCheckItem(
            name="system_status",
            status="warn",
            message="System readiness is degraded; review before deploying.",
            evidence={"status": deployment.status},
        )
    return DeploymentCheckItem(
        name="system_status",
        status="pass",
        message="System readiness is passing.",
        evidence={"status": deployment.status},
    )


def _release_gate_check(readiness: ReleaseReadinessReport) -> DeploymentCheckItem:
    status = "pass" if readiness.status == "pass" else readiness.status
    return DeploymentCheckItem(
        name="release_gates",
        status=status,
        message="Release readiness gates are evaluated.",
        evidence={
            "release_status": readiness.status,
            "can_release": readiness.can_release,
            "gates": {check.name: check.status for check in readiness.checks},
        },
    )


def _capability_status_check(deployment: DeploymentManifest) -> DeploymentCheckItem:
    failed = [item.name for item in deployment.capabilities if item.status == "fail"]
    degraded = [item.name for item in deployment.capabilities if item.status == "degraded"]
    if failed:
        return DeploymentCheckItem(
            name="deployment_capabilities",
            status="fail",
            message="One or more deployment capabilities are failing.",
            evidence={"failed": failed, "degraded": degraded},
        )
    if degraded:
        return DeploymentCheckItem(
            name="deployment_capabilities",
            status="warn",
            message="One or more deployment capabilities are degraded.",
            evidence={"degraded": degraded},
        )
    return DeploymentCheckItem(
        name="deployment_capabilities",
        status="pass",
        message="Deployment capabilities are ready.",
    )


def _security_configuration_check(deployment: DeploymentManifest) -> DeploymentCheckItem:
    operator_configured = bool(deployment.security.get("operator_credentials_configured"))
    read_protected = bool(deployment.security.get("read_routes_protected"))
    if not operator_configured:
        return DeploymentCheckItem(
            name="api_security",
            status="warn",
            message="Operator API key should be configured before shared deployment.",
            evidence={"read_routes_protected": read_protected},
        )
    if not read_protected:
        return DeploymentCheckItem(
            name="api_security",
            status="warn",
            message="Read API key protection is disabled.",
            evidence={"operator_credentials_configured": operator_configured},
        )
    return DeploymentCheckItem(
        name="api_security",
        status="pass",
        message="Operator and read-route protection are configured.",
        evidence={"read_routes_protected": read_protected},
    )


def _production_template_check(profile: str) -> DeploymentCheckItem:
    template = render_env_template(profile)
    placeholders = sorted(
        line.split("=", 1)[0]
        for line in template.splitlines()
        if "replace-with-" in line
    )
    if profile == "production" and placeholders:
        return DeploymentCheckItem(
            name="environment_template",
            status="warn",
            message="Production template contains placeholder values that must be replaced.",
            evidence={"profile": profile, "placeholders": placeholders},
        )
    return DeploymentCheckItem(
        name="environment_template",
        status="pass",
        message="Environment template profile is available.",
        evidence={"profile": profile},
    )


def _deployment_check_status(checks: list[DeploymentCheckItem]) -> str:
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"
