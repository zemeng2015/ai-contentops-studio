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

