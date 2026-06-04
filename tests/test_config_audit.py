from __future__ import annotations

from contentops_core.config_audit import config_audit
from contentops_core.settings import Settings
from pydantic import SecretStr


def test_config_audit_redacts_secret_values() -> None:
    report = config_audit(
        Settings(
            generator_provider="openai",
            openai_api_key="sk-test-secret",
            operator_api_key=SecretStr("operator-secret"),
            read_api_key=SecretStr("read-secret"),
        )
    )
    payload = report.model_dump_json()

    assert report.redacted is True
    assert "sk-test-secret" not in payload
    assert "operator-secret" not in payload
    assert "read-secret" not in payload
    openai_item = next(item for item in report.items if item.name == "openai_api_key")
    assert openai_item.configured is True
    assert openai_item.status == "pass"


def test_config_audit_flags_required_missing_provider_secret() -> None:
    report = config_audit(Settings(generator_provider="openai", openai_api_key=None))

    openai_item = next(item for item in report.items if item.name == "openai_api_key")
    assert report.status == "fail"
    assert openai_item.required is True
    assert openai_item.configured is False
    assert openai_item.status == "fail"
