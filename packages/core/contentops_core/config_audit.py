from __future__ import annotations

from pydantic import SecretStr

from contentops_core.models import ConfigAuditItem, ConfigAuditReport
from contentops_core.settings import Settings

PLACEHOLDER_PREFIXES = ("replace-with", "changeme", "example-")


def config_audit(settings: Settings) -> ConfigAuditReport:
    items = [
        _runtime_item("artifact_store_provider", settings.artifact_store_provider, required=True),
        _runtime_item("research_provider", settings.research_provider, required=True),
        _runtime_item("generator_provider", settings.generator_provider, required=True),
        _runtime_item("publisher_provider", settings.publisher_provider, required=True),
        _runtime_item("public_base_url", settings.public_base_url, required=True),
        _secret_item(
            "database_url",
            settings.database_url,
            required=True,
            evidence={"engine": _database_engine(settings.database_url)},
        ),
        _secret_item(
            "artifact_s3_bucket",
            settings.artifact_s3_bucket,
            required=settings.artifact_store_provider == "s3",
            secret=False,
            evidence={"provider": settings.artifact_store_provider},
        ),
        _secret_item(
            "openai_api_key",
            settings.openai_api_key,
            required=settings.generator_provider == "openai",
        ),
        _secret_item(
            "research_search_api_key",
            settings.research_search_api_key,
            required=settings.research_provider == "search",
        ),
        _secret_item(
            "research_github_token",
            settings.research_github_token,
            required=False,
            evidence={
                "recommended": settings.research_provider == "github",
                "provider": settings.research_provider,
            },
        ),
        _secret_item(
            "operator_api_key",
            settings.operator_api_key,
            required=False,
            evidence={"recommended_for_shared_deployments": True},
        ),
        _secret_item(
            "read_api_key",
            settings.read_api_key,
            required=settings.require_read_api_key and settings.operator_api_key is None,
            evidence={"read_routes_protected": settings.require_read_api_key},
        ),
        _secret_item(
            "notification_webhook_url",
            settings.notification_webhook_url,
            required=False,
            evidence={"delivery_enabled": settings.notification_webhook_url is not None},
        ),
        _runtime_item("latency_slo_ms", settings.latency_slo_ms, required=True),
        _runtime_item("min_source_count", settings.min_source_count, required=True),
        _runtime_item("token_budget_per_run", settings.token_budget_per_run, required=True),
    ]
    summary = {
        "pass": sum(1 for item in items if item.status == "pass"),
        "warn": sum(1 for item in items if item.status == "warn"),
        "fail": sum(1 for item in items if item.status == "fail"),
        "required": sum(1 for item in items if item.required),
        "configured": sum(1 for item in items if item.configured),
        "secret": sum(1 for item in items if item.secret),
    }
    return ConfigAuditReport(
        status=_audit_status(items),
        items=items,
        summary=summary,
    )


def _runtime_item(name: str, value: object, *, required: bool) -> ConfigAuditItem:
    configured = value is not None and str(value) != ""
    valid = configured and not _looks_placeholder(str(value))
    status = "pass" if valid else "fail" if required else "warn"
    return ConfigAuditItem(
        name=name,
        category="runtime",
        status=status,
        required=required,
        configured=configured,
        secret=False,
        message=_message(name, status, required),
        evidence={"value": str(value) if configured else None},
    )


def _secret_item(
    name: str,
    value: object,
    *,
    required: bool,
    secret: bool = True,
    evidence: dict[str, object] | None = None,
) -> ConfigAuditItem:
    configured = _configured(value)
    placeholder = _looks_placeholder(_secret_value(value)) if configured else False
    if required and (not configured or placeholder):
        status = "fail"
    elif placeholder:
        status = "warn"
    elif configured:
        status = "pass"
    else:
        status = "warn"
    item_evidence: dict[str, object] = {
        "configured": configured,
        "placeholder": placeholder,
    }
    if evidence:
        item_evidence.update(evidence)
    return ConfigAuditItem(
        name=name,
        category="secret" if secret else "runtime",
        status=status,
        required=required,
        configured=configured,
        secret=secret,
        message=_message(name, status, required),
        evidence=item_evidence,
    )


def _configured(value: object) -> bool:
    if isinstance(value, SecretStr):
        return bool(value.get_secret_value())
    if value is None:
        return False
    return str(value) != ""


def _secret_value(value: object) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return "" if value is None else str(value)


def _looks_placeholder(value: str) -> bool:
    normalized = value.strip().casefold()
    return any(normalized.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _database_engine(database_url: str) -> str:
    if database_url.startswith("sqlite"):
        return "sqlite"
    if database_url.startswith("postgresql"):
        return "postgresql"
    return "unknown"


def _message(name: str, status: str, required: bool) -> str:
    if status == "pass":
        return f"{name} is configured."
    if status == "fail":
        return f"{name} is required and missing or placeholder."
    if required:
        return f"{name} requires review before production use."
    return f"{name} is optional or not configured."


def _audit_status(items: list[ConfigAuditItem]) -> str:
    if any(item.status == "fail" for item in items):
        return "fail"
    if any(item.status == "warn" for item in items):
        return "warn"
    return "pass"
