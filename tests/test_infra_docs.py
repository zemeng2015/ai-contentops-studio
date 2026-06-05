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
    assert "aws_sqs_queue" in main
    assert "scheduler_dlq" in main
    assert "dead_letter_config" in main
    assert "sqs:SendMessage" in main
    assert "ApproximateNumberOfMessagesVisible" in main
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
    assert "ops_brief_notifier" in main
    assert "ops-brief-notify" in main
    assert "var.ops_brief_window_days" in main
    assert "var.ops_brief_window_size" in main
    assert "aws_ecs_task_definition\" \"release_gate" in main
    assert '"release-gate"' in main
    assert '"--record"' in main
    assert "var.release_gate_window_size" in main
    assert "aws_ecs_task_definition\" \"retention_archive" in main
    assert '"retention-archive"' in main
    assert "var.retention_archive_days" in main
    assert "var.retention_archive_scan_limit" in main
    assert "release_gate_schedule_enabled" in variables
    assert "release_gate_schedule_arn" in outputs
    assert "release_gate_task_definition_arn" in outputs
    assert "retention_archive_schedule_enabled" in variables
    assert "retention_archive_schedule_arn" in outputs
    assert "retention_archive_task_definition_arn" in outputs
    assert "worker_alert_schedule_enabled" in variables
    assert "worker_alert_notifier_schedule_arn" in outputs
    assert "worker_alert_notifier_task_definition_arn" in outputs
    assert "ops_brief_schedule_enabled" in variables
    assert "ops_brief_notifier_schedule_arn" in outputs
    assert "ops_brief_notifier_task_definition_arn" in outputs
    assert "scheduler_dlq_message_retention_seconds" in variables
    assert "scheduler_dlq_alarm_threshold" in variables
    assert "scheduler_dlq_url" in outputs
    assert "scheduler_dlq_alarm_name" in outputs
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
    assert 'python-version: ${{ matrix.python-version }}' in workflow
    assert 'python-version: ["3.11", "3.12", "3.13"]' in workflow
    assert "fail-fast: false" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "hashicorp/setup-terraform@v4" in workflow
    assert "terraform fmt -check" in workflow
    assert "terraform validate" in workflow
    assert "pipelines/project_repository_updates.yaml" in workflow
    assert "scripts/generate_release_evidence.py" in workflow
    assert "scripts/check_release_evidence_regression.py" in workflow
    assert "scripts/dashboard_smoke.py" in workflow
    assert "scripts/generate_deployment_check.py" in workflow
    assert "scripts/generate_release_gate.py" in workflow
    assert "deployment-check/deployment-check.json" in workflow
    assert "deployment-check-py${{ matrix.python-version }}" in workflow
    assert "release-evidence-py${{ matrix.python-version }}" in workflow
    assert "release-evidence-regression-py${{ matrix.python-version }}" in workflow
    assert "dashboard-smoke-py${{ matrix.python-version }}" in workflow
    assert "release-gate-py${{ matrix.python-version }}" in workflow
    assert "release-gate/release-gate.json" in workflow
    assert "--checklist-output release-gate/deployment-checklist.md" in workflow
    assert "release-gate/deployment-checklist.md" in workflow
    assert "--cov=apps" in workflow
    assert "--cov=packages" in workflow
    assert "--cov-report=xml:coverage.xml" in workflow
    assert "--cov-fail-under=75" in workflow
    assert "coverage-py${{ matrix.python-version }}" in workflow
    assert "Repository security baseline" in workflow
    assert "scripts/check_security_baseline.py" in workflow
    assert "Operations policy baseline" in workflow
    assert "scripts/check_operations_policy.py" in workflow
    assert "Release evidence comparison smoke" in workflow
    assert "scripts/compare_release_evidence.py" in workflow
    assert "python -m pip_audit --skip-editable" in workflow
    assert "Container image vulnerability scan" in workflow
    assert "anchore/scan-action@v7" in workflow
    assert "severity-cutoff: high" in workflow
    assert "container-image-grype.json" in workflow
    assert "Container vulnerability policy gate" in workflow
    assert "scripts/check_container_vulnerability_report.py" in workflow
    assert "security-baseline" in workflow


def test_long_term_ci_plan_documents_quality_roadmap() -> None:
    plan = Path("docs/ci-plan.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "Long-Term CI Plan" in plan
    assert "Python 3.11, 3.12, and 3.13" in plan
    assert "deployment preflight" in plan
    assert "release evidence" in plan
    assert "Status: active" in plan
    assert "coverage reporting" in plan
    assert "rendered dashboard smoke check" in plan
    assert "container image vulnerability scanning" in plan
    assert "Terraform security checks" in plan
    assert "workflow_dispatch" in plan
    assert "scheduled ContentOps artifacts" in plan
    assert "Release And Deployment Readiness" in plan
    assert (
        "Release evidence from the candidate commit" in plan
        or "release evidence from the candidate commit" in plan
    )
    assert "docs/ci-plan.md" in readme


def test_phase_two_ci_scripts_exist() -> None:
    evidence_regression = Path("scripts/check_release_evidence_regression.py").read_text(
        encoding="utf-8"
    )
    dashboard_smoke = Path("scripts/dashboard_smoke.py").read_text(encoding="utf-8")

    assert "DEFAULT_REQUIRED_FILES" in evidence_regression
    assert "release-evidence-regression.json" in evidence_regression
    assert "missing_required_files" in evidence_regression
    assert "DashboardSmokeReport" in dashboard_smoke
    assert "/dashboard/release-evidence" in dashboard_smoke
    assert "/dashboard/system-status" in dashboard_smoke


def test_phase_three_security_baseline_exists() -> None:
    security_script = Path("scripts/check_security_baseline.py").read_text(encoding="utf-8")
    dockerfile = Path("infra/docker/Dockerfile").read_text(encoding="utf-8")

    assert "SecurityBaselineReport" in security_script
    assert "pull_request_target is not allowed" in security_script
    assert "terraform:rds-encryption" in security_script
    assert "terraform:no-wildcard-iam" in security_script
    assert "docker:non-root-user" in security_script
    assert "ci:container-image-vulnerability-scan" in security_script
    assert "ci:container-vulnerability-policy-gate" in security_script
    assert "ci:container-scan-artifact" in security_script
    assert "USER contentops" in dockerfile
    assert "PYTHONDONTWRITEBYTECODE=1" in dockerfile


def test_phase_four_operations_policy_exists() -> None:
    operations_policy = Path("scripts/check_operations_policy.py").read_text(encoding="utf-8")
    scheduled = Path(".github/workflows/scheduled-contentops.yml").read_text(encoding="utf-8")

    assert "OperationsPolicyReport" in operations_policy
    assert "integration-smoke:manual-only" in operations_policy
    assert "scheduled:review-only-execution" in operations_policy
    assert "scheduled:publish-intent-guarded" in operations_policy
    assert "--review-only" in scheduled


def test_phase_five_release_readiness_workflow_exists() -> None:
    workflow = Path(".github/workflows/release-readiness.yml").read_text(encoding="utf-8")
    comparison = Path("scripts/compare_release_evidence.py").read_text(encoding="utf-8")

    assert "name: Release Readiness" in workflow
    assert "workflow_dispatch:" in workflow
    assert "environment: ${{ inputs.environment_name }}" in workflow
    assert "require_approval" in workflow
    assert "scripts/generate_deployment_check.py" in workflow
    assert "scripts/generate_release_evidence.py" in workflow
    assert "scripts/check_release_evidence_regression.py" in workflow
    assert "scripts/compare_release_evidence.py" in workflow
    assert "--strict" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "ReleaseEvidenceComparison" in comparison
    assert "missing_from_candidate" in comparison


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
    assert "contentops release-gate" in workflow
    assert "--no-fail-on-block" in workflow
    assert "daily-release-gate.json" in workflow
    assert "daily-release-gate-checklist.md" in workflow
    assert "project-updates-release-gate.json" in workflow
    assert "project-updates-release-gate-checklist.md" in workflow
    assert "contentops scheduled-workflow-summary" in workflow
    assert "--pr-metadata-output scheduled-worker/daily-pr-metadata.json" in workflow
    assert "--pr-metadata-output scheduled-worker/project-updates-pr-metadata.json" in workflow
    assert "--manifest-output scheduled-worker/daily-review-manifest.json" in workflow
    assert "--manifest-output scheduled-worker/project-updates-review-manifest.json" in workflow
    assert (
        "contentops scheduled-workflow-verify scheduled-worker/daily-review-manifest.json --json"
        in workflow
    )
    assert (
        "contentops scheduled-workflow-verify "
        "scheduled-worker/project-updates-review-manifest.json --json"
        in workflow
    )
    assert "set -o pipefail" in workflow
    assert "daily-review-manifest-verification.json" in workflow
    assert "project-updates-review-manifest-verification.json" in workflow
    assert "contentops scheduled-workflow-archive" in workflow
    assert "scheduled-worker/daily-review-package.zip" in workflow
    assert "scheduled-worker/project-updates-review-package.zip" in workflow
    assert "daily-review-package.json" in workflow
    assert "project-updates-review-package.json" in workflow
    assert "--operations-console-path scheduled-worker/daily-operations-console.json" in workflow
    assert (
        "--operations-console-path scheduled-worker/project-updates-operations-console.json"
        in workflow
    )
    assert "GITHUB_STEP_SUMMARY" in workflow
    assert "scheduled-worker/daily-review.md" in workflow
    assert "gh issue create" in workflow
    assert "gh pr create" in workflow
    assert "--draft" in workflow
    assert "contentops/scheduled-daily-${GITHUB_RUN_ID}" in workflow
    assert "contentops/scheduled-project-updates-${GITHUB_RUN_ID}" in workflow
    assert "scheduled-reviews/daily-${GITHUB_RUN_ID}.json" in workflow
    assert "scheduled-reviews/daily-${GITHUB_RUN_ID}-manifest.json" in workflow
    assert "scheduled-reviews/project-updates-${GITHUB_RUN_ID}-manifest.json" in workflow
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


def test_aws_docs_describe_ops_brief_notifier() -> None:
    aws_readme = Path("infra/aws/README.md").read_text(encoding="utf-8")
    deployment = Path("docs/deployment.md").read_text(encoding="utf-8")

    assert "operations brief notifier" in aws_readme
    assert "ops_brief_schedule_enabled=true" in aws_readme
    assert "ops-brief-notification-log.json" in aws_readme
    assert "ops_brief_schedule_expression" in deployment
    assert "ops_brief_deliveries.json" in deployment


def test_aws_docs_describe_release_gate_schedule() -> None:
    aws_readme = Path("infra/aws/README.md").read_text(encoding="utf-8")
    deployment = Path("docs/deployment.md").read_text(encoding="utf-8")

    assert "release gate scheduler" in aws_readme
    assert "release_gate_schedule_enabled=true" in aws_readme
    assert "contentops release-gate --record --json" in deployment
    assert "release_gate_schedule_expression" in deployment


def test_aws_docs_describe_retention_archive_schedule() -> None:
    aws_readme = Path("infra/aws/README.md").read_text(encoding="utf-8")
    deployment = Path("docs/deployment.md").read_text(encoding="utf-8")

    assert "retention archive scheduler" in aws_readme
    assert "retention_archive_schedule_enabled=true" in aws_readme
    assert "contentops retention-archive" in deployment
    assert "retention_archive_schedule_expression" in deployment
    assert "retention_archives.json" in aws_readme


def test_aws_docs_describe_scheduler_dead_letter_queue() -> None:
    aws_readme = Path("infra/aws/README.md").read_text(encoding="utf-8")
    deployment = Path("docs/deployment.md").read_text(encoding="utf-8")
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")

    assert "EventBridge Scheduler dead-letter queue" in aws_readme
    assert "scheduler_dlq_url" in aws_readme
    assert "scheduler_dlq_alarm_name" in deployment
    assert "failed invocation payloads" in deployment
    assert "dead-letter queue" in architecture
