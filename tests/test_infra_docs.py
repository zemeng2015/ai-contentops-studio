from __future__ import annotations

from pathlib import Path


def test_terraform_skeleton_contains_core_resources() -> None:
    root = Path("infra/aws/terraform")
    main = (root / "main.tf").read_text(encoding="utf-8")

    assert "aws_s3_bucket" in main
    assert "aws_db_instance" in main
    assert "aws_secretsmanager_secret" in main
    assert "aws_ecs_task_definition" in main
    assert "aws_cloudwatch_log_group" in main
    assert "aws_cloudwatch_log_metric_filter" in main
    assert "aws_cloudwatch_metric_alarm" in main
    assert "aws_cloudwatch_dashboard" in main
    assert "aws_scheduler_schedule_group" in main
    assert "aws_scheduler_schedule" in main
    assert "ecs:RunTask" in main
    assert "iam:PassRole" in main
    assert "CONTENTOPS_DATABASE_URL" in main
    assert "CONTENTOPS_OPERATOR_API_KEY" in main
    assert "CONTENTOPS_READ_API_KEY" in main
    assert "CONTENTOPS_OPENAI_API_KEY" in main
    assert "CONTENTOPS_RUN_MIGRATIONS" in main
    assert "CONTENTOPS_REQUIRE_READ_API_KEY" in main
    assert "CONTENTOPS_NOTIFICATION_WEBHOOK_URL" in main
    assert "WorkerFailureCount" in main
    assert "ApiErrorCount" in main


def test_ci_validates_terraform() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "hashicorp/setup-terraform" in workflow
    assert "terraform fmt -check" in workflow
    assert "terraform validate" in workflow
    assert "scripts/generate_release_evidence.py" in workflow
    assert "actions/upload-artifact" in workflow


def test_docker_image_contains_release_profile() -> None:
    dockerfile = Path("infra/docker/Dockerfile").read_text(encoding="utf-8")
    entrypoint = Path("infra/docker/entrypoint.py").read_text(encoding="utf-8")

    assert "COPY alembic.ini" in dockerfile
    assert "COPY migrations" in dockerfile
    assert "ENTRYPOINT" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "CONTENTOPS_RUN_MIGRATIONS" in entrypoint
    assert "alembic" in entrypoint
    assert "os.execvp" in entrypoint


def test_production_env_template_documents_required_release_settings() -> None:
    template = Path("config/production.env.example").read_text(encoding="utf-8")

    assert "CONTENTOPS_RUN_MIGRATIONS=true" in template
    assert "CONTENTOPS_DATABASE_URL=postgresql+psycopg://" in template
    assert "CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3" in template
    assert "CONTENTOPS_GENERATOR_PROVIDER=openai" in template
    assert "CONTENTOPS_RESEARCH_PROVIDER=discovery" in template
    assert "CONTENTOPS_REQUIRE_READ_API_KEY=true" in template
