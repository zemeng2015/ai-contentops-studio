# AWS Notes

This directory is reserved for infrastructure-as-code. The intended production mapping is:

- ECS Fargate service: `contentops-api`
- ECS scheduled task: `contentops-worker`
- RDS Postgres: run metadata
- S3: artifacts and generated static output
- EventBridge: daily/weekly pipeline triggers
- Secrets Manager: model, search, and publishing credentials
- CloudWatch: structured logs and metrics

The first implementation keeps IaC out of the critical path so the application contract can settle
before Terraform or CDK resources are added.

## Terraform skeleton

`terraform/` now contains an AWS-ready baseline for:

- S3 artifact storage with versioning and encryption
- RDS Postgres run metadata storage
- Secrets Manager storage for `CONTENTOPS_DATABASE_URL`
- optional Secrets Manager injection for `CONTENTOPS_OPERATOR_API_KEY`,
  `CONTENTOPS_READ_API_KEY`,
  `CONTENTOPS_OPENAI_API_KEY`,
  `CONTENTOPS_RESEARCH_SEARCH_API_KEY`,
  `CONTENTOPS_RESEARCH_GITHUB_TOKEN`, and `CONTENTOPS_NOTIFICATION_WEBHOOK_URL`
- ECS Fargate task definitions for API and worker
- ECS Fargate task definition for the worker alert notifier
- task execution and artifact access IAM roles
- CloudWatch log groups
- CloudWatch log metric filters for API errors and worker failures
- CloudWatch alarms for API errors, worker failures, and high RDS connections
- CloudWatch operations dashboard for errors, ECS resources, RDS health, and recent failure logs
- EventBridge Scheduler recurring worker run and worker alert notification check

It intentionally stops short of creating public networking and an ALB until the runtime deployment
choice is finalized.
GitHub Actions runs `terraform fmt`, `terraform init -backend=false`, and `terraform validate` on
this directory so infrastructure changes are checked with the same quality gate as application
code.

```bash
cd infra/aws/terraform
terraform init
terraform plan \
  -var='container_image=<account>.dkr.ecr.<region>.amazonaws.com/ai-contentops-studio:latest' \
  -var='vpc_id=vpc-...' \
  -var='private_subnet_ids=["subnet-...","subnet-..."]'
```

The recurring worker schedule is disabled by default. Set `worker_schedule_enabled=true` after the
image, networking, RDS metadata store, and publishing target are ready.
The worker alert notifier schedule is also disabled by default. Set
`worker_alert_schedule_enabled=true` after the worker has produced receipts in S3 and
`notification_webhook_url_secret_arn` is configured when external delivery is required. The notifier
runs `contentops job-execution-alert-notify`, writes `worker-alert-notification-log.json`, and makes
the same receipts visible through `/job-executions/alerts/notifications` and release evidence.
Set `worker_pipeline_path` to choose the scheduled content calendar. For example, use
`pipelines/daily_ai_roundup.yaml` for AI trend monitoring or
`pipelines/project_repository_updates.yaml` for GitHub project update drafts.
Set `research_provider=github` with `research_github_token_secret_arn` for repository intelligence
jobs, or `research_provider=search` with `research_search_api_key_secret_arn` for open-web
discovery jobs.
Set `operator_api_key_secret_arn` to require an operator key for write actions in shared
deployments.
Set `read_api_key_secret_arn` and `require_read_api_key=true` to protect dashboard and artifact
read routes with a read-only key. The operator key also works on read routes, but read keys cannot
perform write actions.
Set `notification_webhook_url_secret_arn` to deliver review and publishing events to an external
webhook while retaining local `notification-log.json` and worker alert delivery receipts.
Tune `latency_slo_ms` and `min_source_count` to make the dashboard and `/scorecards` API reflect
the production quality bar for recurring content runs.
Tune `token_budget_per_run` to make `/cost-reports` useful as a recurring-run budget guardrail.
Set `alarm_actions` to SNS topic ARNs or incident-management integrations if CloudWatch alarms
should notify operators. Leave it empty to create inspectable alarms without paging during early
portfolio demos.
