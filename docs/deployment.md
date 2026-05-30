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

## Provider environment variables

```text
CONTENTOPS_RESEARCH_PROVIDER=hybrid
CONTENTOPS_GENERATOR_PROVIDER=template
CONTENTOPS_PUBLISHER_PROVIDER=static
CONTENTOPS_OPENAI_MODEL=gpt-5-mini
CONTENTOPS_OPENAI_API_KEY=
CONTENTOPS_HOMEPAGE_REPO_PATH=
CONTENTOPS_HOMEPAGE_PUBLIC_BASE_URL=https://zemeng2015.github.io/zack-ai-homepage
```
