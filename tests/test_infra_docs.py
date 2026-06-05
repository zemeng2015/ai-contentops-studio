from __future__ import annotations

from pathlib import Path


def test_terraform_skeleton_contains_core_resources() -> None:
    root = Path("infra/aws/terraform")
    main = (root / "main.tf").read_text(encoding="utf-8")
    variables = (root / "variables.tf").read_text(encoding="utf-8")
    outputs = (root / "outputs.tf").read_text(encoding="utf-8")

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
    assert "CONTENTOPS_RESEARCH_SEARCH_API_KEY" in main
    assert "CONTENTOPS_RESEARCH_GITHUB_TOKEN" in main
    assert "var.worker_pipeline_path" in main
    assert "worker_alert_notifier" in main
    assert "job-execution-alert-notify" in main
    assert "var.worker_alert_window_days" in main
    assert "aws_ecs_task_definition\" \"release_gate" in main
    assert '"release-gate"' in main
    assert '"--record"' in main
    assert "var.release_gate_window_size" in main
    assert "release_gate_schedule_enabled" in variables
    assert "release_gate_schedule_arn" in outputs
    assert "release_gate_task_definition_arn" in outputs
    assert "worker_alert_schedule_enabled" in variables
    assert "worker_alert_notifier_schedule_arn" in outputs
    assert "worker_alert_notifier_task_definition_arn" in outputs
    assert "var.research_provider" in main
    assert "CONTENTOPS_RUN_MIGRATIONS" in main
    assert "CONTENTOPS_REQUIRE_READ_API_KEY" in main
    assert "CONTENTOPS_NOTIFICATION_WEBHOOK_URL" in main
    assert "WorkerFailureCount" in main
    assert "ApiErrorCount" in main
    assert "/job-executions/alerts/notifications" in main


def test_ci_validates_terraform() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in workflow
    assert "actions/checkout@v5" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "hashicorp/setup-terraform@v4" in workflow
    assert "terraform fmt -check" in workflow
    assert "terraform validate" in workflow
    assert "pipelines/project_repository_updates.yaml" in workflow
    assert "scripts/generate_release_evidence.py" in workflow
    assert "scripts/generate_deployment_check.py" in workflow
    assert "scripts/generate_release_gate.py" in workflow
    assert "deployment-check/deployment-check.json" in workflow
    assert "release-gate/release-gate.json" in workflow
    assert "--checklist-output release-gate/deployment-checklist.md" in workflow
    assert "release-gate/deployment-checklist.md" in workflow


def test_scheduled_contentops_workflow_runs_worker_gates() -> None:
    workflow = Path(".github/workflows/scheduled-contentops.yml").read_text(encoding="utf-8")

    assert "name: Scheduled ContentOps" in workflow
    assert "workflow_dispatch:" in workflow
    assert "create_review_issue" in workflow
    assert "create_draft_pr" in workflow
    assert "contents: write" in workflow
    assert "issues: write" in workflow
    assert "pull-requests: write" in workflow
    assert 'cron: "0 0 * * *"' in workflow
    assert 'cron: "30 0 * * 1"' in workflow
    assert "contentops worker-job-readiness --json" in workflow
    assert "pipelines/daily_ai_roundup.yaml" in workflow
    assert "pipelines/project_repository_updates.yaml" in workflow
    assert "--dry-run" in workflow
    assert "--release-evidence-dir artifacts/release-evidence/daily-ai-roundup" in workflow
    assert "contentops job-execution-alert-notify --days 7" in workflow
    assert "artifacts/ops-brief-notification-log.json" in workflow
    assert "daily-ops-brief-notifications.json" in workflow
    assert "project-updates-ops-brief-notifications.json" in workflow
    assert "contentops scheduled-workflow-summary" in workflow
    assert "--pr-metadata-output scheduled-worker/daily-pr-metadata.json" in workflow
    assert "--pr-metadata-output scheduled-worker/project-updates-pr-metadata.json" in workflow
    assert "GITHUB_STEP_SUMMARY" in workflow
    assert "scheduled-worker/daily-review.md" in workflow
    assert "gh issue create" in workflow
    assert "gh pr create" in workflow
    assert "--draft" in workflow
    assert "contentops/scheduled-daily-${GITHUB_RUN_ID}" in workflow
    assert "contentops/scheduled-project-updates-${GITHUB_RUN_ID}" in workflow
    assert "scheduled-reviews/daily-${GITHUB_RUN_ID}.json" in workflow
    assert "daily-review-issue.md" in workflow
    assert "project-updates-review-issue.md" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "CONTENTOPS_NOTIFICATION_WEBHOOK_URL" in workflow


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


def test_showcase_documents_ops_trends_screenshot() -> None:
    asset = Path("docs/assets/ops-trends-dashboard.png")
    readme = Path("README.md").read_text(encoding="utf-8")
    showcase = Path("docs/showcase.md").read_text(encoding="utf-8")

    assert asset.exists()
    assert asset.stat().st_size > 0
    assert "docs/assets/ops-trends-dashboard.png" in readme
    assert "assets/ops-trends-dashboard.png" in showcase


def test_production_env_template_documents_required_release_settings() -> None:
    template = Path("config/production.env.example").read_text(encoding="utf-8")

    assert "CONTENTOPS_RUN_MIGRATIONS=true" in template
    assert "CONTENTOPS_DATABASE_URL=postgresql+psycopg://" in template
    assert "CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3" in template
    assert "CONTENTOPS_GENERATOR_PROVIDER=openai" in template
    assert "CONTENTOPS_RESEARCH_PROVIDER=discovery" in template
    assert "CONTENTOPS_REQUIRE_READ_API_KEY=true" in template


def test_aws_docs_describe_worker_alert_notifier() -> None:
    aws_readme = Path("infra/aws/README.md").read_text(encoding="utf-8")
    deployment = Path("docs/deployment.md").read_text(encoding="utf-8")

    assert "worker alert notifier" in aws_readme
    assert "worker_alert_schedule_enabled=true" in aws_readme
    assert "worker-alert-notification-log.json" in aws_readme
    assert "worker_alert_schedule_expression" in deployment
    assert "worker_execution_alert_deliveries.json" in deployment


def test_aws_docs_describe_release_gate_schedule() -> None:
    aws_readme = Path("infra/aws/README.md").read_text(encoding="utf-8")
    deployment = Path("docs/deployment.md").read_text(encoding="utf-8")

    assert "release gate scheduler" in aws_readme
    assert "release_gate_schedule_enabled=true" in aws_readme
    assert "contentops release-gate --record --json" in deployment
    assert "release_gate_schedule_expression" in deployment
