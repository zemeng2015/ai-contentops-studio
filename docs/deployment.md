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

For a production-shaped container start, pass the release profile variables and run migrations at
startup:

```powershell
Copy-Item config/production.env.example .env.production
# Edit .env.production with real bucket, database, provider, and API key values.
docker run --rm -p 8000:8000 --env-file .env.production ai-contentops-studio
```

The same template can be generated from the installed CLI or fetched from the API:

```powershell
contentops init-config --profile production --path .env.production
contentops deployment-check --json
python scripts/generate_deployment_check.py --output deployment-check/deployment-check.json
Invoke-WebRequest http://127.0.0.1:8000/deployment-env-template -OutFile .env.production
Invoke-RestMethod http://127.0.0.1:8000/deployment-check
```

CI runs the same deployment preflight script and uploads `deployment-check.json` as an artifact
next to the release evidence bundle.

`CONTENTOPS_RUN_MIGRATIONS=true` tells the image entrypoint to run `alembic upgrade head` before
starting Uvicorn. The image also includes a `/ready` healthcheck so container platforms can detect
database, artifact store, and provider configuration failures.

## AWS target architecture

- API: ECS Fargate service behind ALB, or Lambda behind API Gateway
- Worker: ECS scheduled task or Lambda invoked by EventBridge
- Artifacts: S3 bucket partitioned by run date
- Metadata: RDS Postgres, exposed to tasks through a Secrets Manager
  `CONTENTOPS_DATABASE_URL`
- Secrets: AWS Secrets Manager for database URLs, model credentials, optional operator keys,
  and optional read-only keys
- Logs and metrics: CloudWatch

The code uses provider and publisher boundaries so local filesystem/SQLite can be replaced by
S3/Postgres without changing the pipeline contract.

The AWS Terraform skeleton lives in `infra/aws/terraform`. It defines the artifact bucket, RDS
Postgres metadata database, database URL secret, ECS task definitions, scheduled worker IAM role,
EventBridge Scheduler rule, log groups, log-derived metrics, CloudWatch alarms, an operations
dashboard, and scheduler group needed for the first production deployment shape.

## Provider environment variables

```text
CONTENTOPS_RESEARCH_PROVIDER=discovery
CONTENTOPS_RESEARCH_FEEDS=https://export.arxiv.org/api/query?search_query=cat:cs.AI%20OR%20cat:cs.CL%20OR%20cat:cs.LG&start=0&max_results=25&sortBy=submittedDate&sortOrder=descending
CONTENTOPS_RESEARCH_MAX_SOURCES=6
CONTENTOPS_RESEARCH_RETRY_ATTEMPTS=2
CONTENTOPS_RESEARCH_RETRY_BACKOFF_SECONDS=0.1
CONTENTOPS_RESEARCH_SEARCH_ENDPOINT=https://api.search.brave.com/res/v1/web/search
CONTENTOPS_RESEARCH_SEARCH_API_KEY=
CONTENTOPS_RESEARCH_SEARCH_ENRICH=true
CONTENTOPS_RESEARCH_GITHUB_API_BASE_URL=https://api.github.com
CONTENTOPS_RESEARCH_GITHUB_TOKEN=
CONTENTOPS_ARTIFACT_STORE_PROVIDER=local
CONTENTOPS_ARTIFACT_S3_BUCKET=
CONTENTOPS_ARTIFACT_S3_PREFIX=contentops-artifacts
CONTENTOPS_DATABASE_URL=sqlite:///contentops.db
CONTENTOPS_GENERATOR_PROVIDER=template
CONTENTOPS_PUBLISHER_PROVIDER=static
CONTENTOPS_OPENAI_MODEL=gpt-5-mini
CONTENTOPS_OPENAI_TIMEOUT_SECONDS=60
CONTENTOPS_OPENAI_RETRY_ATTEMPTS=2
CONTENTOPS_OPENAI_RETRY_BACKOFF_SECONDS=0.5
CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true
CONTENTOPS_OPENAI_API_KEY=
CONTENTOPS_OPERATOR_API_KEY=
CONTENTOPS_READ_API_KEY=
CONTENTOPS_REQUIRE_READ_API_KEY=false
CONTENTOPS_HOMEPAGE_REPO_PATH=
CONTENTOPS_HOMEPAGE_PUBLIC_BASE_URL=https://zemeng2015.github.io/zack-ai-homepage
```

For ECS or Lambda workers, set `CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3` so each local artifact
write is mirrored to S3 under:

```text
s3://$CONTENTOPS_ARTIFACT_S3_BUCKET/$CONTENTOPS_ARTIFACT_S3_PREFIX/<run_id>/<artifact>
```

Release evidence and worker execution receipts use the same bucket and prefix. Their local output
directories include `s3-mirror-log.json`, which records the bucket, key, content type, status, and
error message for every standalone artifact mirror attempt.

For RDS-backed deployments, install the optional AWS dependency so SQLAlchemy can use the
`postgresql+psycopg://` URL:

```powershell
pip install -e ".[aws]"
```

Run schema migrations against the target database before API or worker tasks begin accepting
traffic:

```powershell
$env:CONTENTOPS_DATABASE_URL="postgresql+psycopg://contentops:password@host:5432/contentops"
alembic upgrade head
```

The migration environment reads `CONTENTOPS_DATABASE_URL` through the same settings object used by
the API, CLI, and worker. This keeps SQLite useful for local development while giving RDS/Postgres
deployments an explicit, reviewable schema version history.

## Live provider smoke tests

After provider credentials are injected into the target environment, run the optional smoke tests
to verify external connectivity and response parsing before enabling scheduled jobs:

```powershell
$env:CONTENTOPS_RUN_INTEGRATION="1"
pytest -m integration tests/test_integration_smoke.py
```

Set `CONTENTOPS_OPENAI_API_KEY` for the OpenAI generation smoke test,
`CONTENTOPS_RESEARCH_SEARCH_API_KEY` for the Brave-compatible search smoke test, and
`CONTENTOPS_HOMEPAGE_REPO_PATH` for the read-only homepage publisher plan check.

## Release evidence

Every CI run generates release evidence JSON artifacts that can be attached to release notes or
reviewed during deployment approval:

```powershell
python scripts/generate_release_evidence.py --output-dir release-evidence
```

The evidence bundle includes system status, a redacted deployment manifest, operations summary,
release readiness gates, a summary file with the commit SHA, and `evidence_manifest.json` with
SHA-256 hashes, sizes, media types, and timestamps for the generated evidence artifacts. The
command exits non-zero only when release readiness is `fail`; local-development `warn` states
remain inspectable without blocking ordinary CI.
The same bundle is also available through the product surface:

```powershell
contentops release-evidence --output-dir release-evidence
Invoke-RestMethod http://127.0.0.1:8000/release-evidence
```

The Terraform worker schedule is disabled by default. Enable it only after the container image,
private subnets, database connectivity, and feed configuration are ready:

```bash
terraform apply \
  -var='worker_schedule_enabled=true' \
  -var='worker_schedule_expression=cron(0 13 * * ? *)'
```

For shared API or dashboard deployments, store an operator key in Secrets Manager and pass its ARN
through `operator_api_key_secret_arn`. Once `CONTENTOPS_OPERATOR_API_KEY` is set, mutating routes
require `X-ContentOps-Api-Key` or an `api_key` query parameter.
Set `CONTENTOPS_REQUIRE_READ_API_KEY=true` when dashboard pages, artifacts, source audits, job
receipts, content inventory, or evidence bundles should not be publicly readable. Health and
readiness probes remain unauthenticated. Read routes accept `CONTENTOPS_READ_API_KEY` or the
operator key; mutating routes accept only the operator key.
Set `CONTENTOPS_NOTIFICATION_WEBHOOK_URL` to deliver approve, reject, publish, and rollback events
to an external incident, chat, or workflow system. Delivery attempts are written to
`notification-log.json` beside each run.
In Terraform deployments, pass `operator_api_key_secret_arn`, `read_api_key_secret_arn`,
`openai_api_key_secret_arn`, `notification_webhook_url_secret_arn`,
`require_read_api_key`, and `notification_timeout_seconds` to inject the corresponding ECS task
configuration.

Worker executions write JSON receipts under `CONTENTOPS_ARTIFACT_ROOT/job-executions` unless
`--receipt-dir` is provided. In ECS/EventBridge deployments, keep artifact mirroring enabled so
these receipts are copied to S3 with the rest of the run artifacts and release evidence.
Worker job definitions are discovered from `CONTENTOPS_PIPELINE_DIR` and exposed through
`contentops worker-jobs`, `GET /worker-jobs`, and the dashboard so scheduled calendars can be
reviewed before EventBridge launches them.
In Terraform deployments, set `worker_pipeline_path` to select the scheduled YAML calendar, such as
`pipelines/daily_ai_roundup.yaml` or `pipelines/project_repository_updates.yaml`. Set
`research_provider` with `research_search_api_key_secret_arn` or `research_github_token_secret_arn`
when the scheduled calendar depends on search or GitHub repository sources.
`contentops deployment-manifest` and `contentops release-evidence` also report
`scheduled_research_ready`, including the selected research provider, provider mode, credential
state, and whether the provider can discover or retrieve sources for scheduled automation.
They also report publishing readiness, including static output writability or homepage repository
markers, so a scheduled worker does not reach approval with an unusable publishing target.

The Terraform stack creates a CloudWatch dashboard and three default alarms:

- API log-derived errors
- Worker log-derived failures
- high RDS metadata database connections

Set `alarm_actions` to SNS topic ARNs or incident integrations to page operators. Keep it empty
when you want dashboard evidence and alarm state without live notifications.
