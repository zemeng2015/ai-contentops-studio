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
- optional Secrets Manager injection for `CONTENTOPS_OPERATOR_API_KEY`
- ECS Fargate task definitions for API and worker
- task execution and artifact access IAM roles
- CloudWatch log groups
- EventBridge Scheduler recurring worker run

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
Set `operator_api_key_secret_arn` to require an operator key for write actions in shared
deployments.
