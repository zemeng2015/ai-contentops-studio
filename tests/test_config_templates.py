from __future__ import annotations

from pathlib import Path

from contentops_core.config_templates import render_env_template


def test_production_env_example_matches_renderer() -> None:
    expected = render_env_template("production")
    actual = Path("config/production.env.example").read_text(encoding="utf-8")

    assert actual == expected
    assert "CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3" in actual
    assert "CONTENTOPS_OPERATOR_API_KEY=replace-with-long-random-operator-key" in actual
    assert "CONTENTOPS_DATABASE_URL=postgresql+psycopg://" in actual


def test_unknown_env_template_profile_fails() -> None:
    try:
        render_env_template("staging")
    except ValueError as exc:
        assert "Unknown config profile" in str(exc)
    else:
        raise AssertionError("Expected unknown config profile to fail.")
