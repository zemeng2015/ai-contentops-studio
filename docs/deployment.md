# Deployment

## Local

```powershell
pip install -e ".[dev]"
contentops run --topic "AI observability for RAG systems" --publish
uvicorn contentops_api.main:app --reload --app-dir apps/api
```

## Docker

```powershell
docker build -f infra/docker/Dockerfile -t ai-contentops-studio .
docker run --rm -p 8000:8000 ai-contentops-studio
```

## AWS target architecture

- API: ECS Fargate service behind ALB, or Lambda behind API Gateway
- Worker: ECS scheduled task or Lambda invoked by EventBridge
- Artifacts: S3 bucket partitioned by run date
- Metadata: RDS Postgres
- Secrets: AWS Secrets Manager
- Logs and metrics: CloudWatch

The code uses provider and publisher boundaries so local filesystem/SQLite can be replaced by
S3/Postgres without changing the pipeline contract.

The AWS Terraform skeleton lives in `infra/aws/terraform`. It defines the artifact bucket, ECS task
definitions, IAM roles, log groups, and scheduler group needed for the first production deployment
shape.

## Provider environment variables

```text
CONTENTOPS_RESEARCH_PROVIDER=discovery
CONTENTOPS_RESEARCH_FEEDS=https://export.arxiv.org/api/query?search_query=cat:cs.AI%20OR%20cat:cs.CL%20OR%20cat:cs.LG&start=0&max_results=25&sortBy=submittedDate&sortOrder=descending
CONTENTOPS_RESEARCH_MAX_SOURCES=6
CONTENTOPS_ARTIFACT_STORE_PROVIDER=local
CONTENTOPS_ARTIFACT_S3_BUCKET=
CONTENTOPS_ARTIFACT_S3_PREFIX=contentops-artifacts
CONTENTOPS_GENERATOR_PROVIDER=template
CONTENTOPS_PUBLISHER_PROVIDER=static
CONTENTOPS_OPENAI_MODEL=gpt-5-mini
CONTENTOPS_OPENAI_API_KEY=
CONTENTOPS_HOMEPAGE_REPO_PATH=
CONTENTOPS_HOMEPAGE_PUBLIC_BASE_URL=https://zemeng2015.github.io/zack-ai-homepage
```

For ECS or Lambda workers, set `CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3` so each local artifact
write is mirrored to S3 under:

```text
s3://$CONTENTOPS_ARTIFACT_S3_BUCKET/$CONTENTOPS_ARTIFACT_S3_PREFIX/<run_id>/<artifact>
```
