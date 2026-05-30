# AI ContentOps Studio

[English](README.md) | [中文](README.zh-CN.md)

AI ContentOps Studio is a production-shaped platform for technical research automation,
source-grounded content generation, quality evaluation, artifact tracking, and publishing.

It is designed to prove applied AI engineering skills beyond a prompt demo:

- multi-step LLM workflow orchestration
- source-grounded research packets
- content planning before generation
- deterministic quality evaluation
- observable run history and artifacts
- operational scorecards for quality, latency SLOs, and source-count checks
- estimated token budget reports for cost-aware AI operations
- artifact manifests with size, type, timestamp, and content hash metadata
- queryable review queue with status/search filters and pagination
- batch approve/reject workflow for review queues
- explicit approval records before reviewed runs are published
- append-only audit logs for review and publishing actions
- notification delivery logs for review and publishing events, with optional webhook delivery
- source audit reports with scoring, risk reasons, and reviewer recommendations
- publish receipts that audit provider, URL, approval, file hashes, backups, and rollback hints
- optional operator API key protection for mutating API and dashboard actions
- readiness checks and CLI diagnostics for production deployments
- API, CLI, worker, and publisher boundaries
- review dashboard with artifact, source, evaluation, and publish-plan inspection
- run comparison for repeatable quality and source regression review
- YAML-defined worker jobs for scheduled content calendars
- AWS-ready artifact storage and Terraform deployment skeleton
- local-first development with AWS-ready deployment primitives

## What it does

Given a topic, URL, or repository, the system creates a content run:

1. collect, normalize, and audit sources
2. extract engineering signals and claims
3. plan the article angle and outline
4. generate markdown and HTML drafts
5. evaluate groundedness, source coverage, career relevance, and publish readiness
6. keep the run in review, approve or reject it, then publish approved content
7. persist artifacts and run trace for inspection

The first pipeline is intentionally local and deterministic so it can run in CI without API keys.
Provider adapters are separated so OpenAI, search APIs, GitHub, or AWS services can be added
without rewriting the domain layer.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
contentops run --topic "LLM observability for enterprise RAG systems"
contentops runs
contentops doctor
pytest
```

Start the API:

```powershell
uvicorn contentops_api.main:app --reload --app-dir apps/api
```

Then create a run:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/runs `
  -ContentType "application/json" `
  -Body '{"topic":"AI evaluation for RAG systems","publish":true}'
```

## Repository layout

```text
apps/
  api/                     FastAPI service
  cli/                     Typer command line interface
  worker/                  Background worker entrypoint
packages/
  core/                    Domain models, pipeline orchestration, artifact storage
  providers/               Research, model, search, and external system adapters
  evaluators/              Content quality and groundedness checks
  publishing/              Static site and GitHub Pages publishers
  observability/           Structured run tracing
pipelines/                 YAML pipeline definitions
docs/                      Architecture, deployment, and evaluation methodology
infra/                     Docker and AWS deployment notes
tests/                     Unit and integration tests
```

Operational docs:

- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [Production runbook](docs/runbook.md)

## Architecture principles

- The pipeline is stateful and inspectable. Every step writes an artifact.
- External services sit behind provider interfaces.
- Generated content is evaluated before it is published.
- Publishing is a state transition, not a side effect hidden inside generation.
- Local filesystem and SQLite are the default, with S3/RDS/EventBridge-ready boundaries.

## Current MVP

- Local research provider with deterministic source packets
- URL research provider that fetches and normalizes operator-supplied sources
- Feed research provider that discovers sources from RSS/Atom feeds
- Search research provider for Brave-compatible web search APIs, with optional page enrichment
- Discovery research provider that combines feed discovery, operator URLs, and local context
- Source deduplication plus extraction status, quality, and content-length metadata
- Optional OpenAI Responses API generator behind a provider boundary
- Optional homepage publisher for Zack's GitHub Pages portfolio
- Markdown and HTML article generation
- Quality evaluation report
- SQLite run metadata
- Filesystem artifact store
- Static site publisher
- FastAPI `POST /runs` and `GET /runs`
- FastAPI `GET /review-queue` with status/search filters and pagination metadata
- FastAPI artifact review endpoints and `POST /runs/{run_id}/publish`
- FastAPI metrics, scorecard, cost-report, rerun, publish-plan, and run-comparison endpoints
- Worker entrypoint for single-job or batch YAML content calendars
- CLI `contentops run`, `contentops runs`, `contentops show`, `contentops artifacts`, and
  `contentops publish`, plus review commands for metrics, source-audit, rerun, publish-plan,
  and compare
- pytest coverage for pipeline behavior

## Review workflow

Generate first, inspect artifacts, then publish:

```powershell
contentops run --topic "AI quality gates for RAG systems"
contentops artifacts <run_id>
contentops show <run_id> --artifact eval-report.json
contentops export-run <run_id> --output run-evidence.zip
contentops publish-plan <run_id>
contentops metrics <run_id>
contentops scorecard <run_id>
contentops scorecards --status needs_review --json
contentops cost-report <run_id>
contentops cost-reports --status needs_review --json
contentops source-audit <run_id>
contentops compare <base_run_id> <candidate_run_id>
contentops queue --status needs_review --query "rag" --json
contentops manifest <run_id>
contentops audit-log <run_id>
contentops notifications <run_id>
contentops job-executions --json
contentops job-execution <execution_id>
contentops content --json
contentops approve-many <run_id> <run_id> --reviewer "Zack" --json
contentops approve <run_id> --reviewer "Zack" --notes "Ready to publish"
contentops rerun <run_id>
contentops publish <run_id>
contentops publish-receipt <run_id>
contentops rollback-publish <run_id> --actor "Zack"
```

The API exposes the same lifecycle:

```text
GET  /runs/{run_id}/artifacts
GET  /runs/{run_id}/artifact-manifest
GET  /runs/{run_id}/bundle
GET  /runs/{run_id}/artifacts/{artifact_name}
GET  /runs/{run_id}/publish-plan
GET  /runs/{run_id}/metrics
GET  /runs/{run_id}/scorecard
GET  /runs/{run_id}/cost-report
GET  /runs/{run_id}/source-audit
GET  /runs/{run_id}/approval
GET  /runs/{run_id}/publish-receipt
GET  /runs/{run_id}/audit-log
GET  /runs/{run_id}/notifications
GET  /runs/{base_run_id}/compare/{candidate_run_id}
GET  /review-queue?status=needs_review&q=rag&limit=20&offset=0
GET  /job-executions?limit=20&offset=0
GET  /job-executions/{execution_id}
GET  /content?limit=20&offset=0
GET  /scorecards?status=needs_review&q=rag&limit=20&offset=0
GET  /cost-reports?status=needs_review&q=rag&limit=20&offset=0
GET  /ready
POST /review-queue/batch-approve
POST /review-queue/batch-reject
POST /runs/{run_id}/approve
POST /runs/{run_id}/reject
POST /runs/{run_id}/rerun
POST /runs/{run_id}/publish
POST /runs/{run_id}/rollback-publish
```

The API also serves a lightweight dashboard at:

```text
GET /dashboard
```

Run details include a Source Review table so reviewers can inspect source status and extraction
quality before publishing.
Run details also include a Publish Plan that lists file-level changes before the publish action.
Run details include a timeline derived from `trace.json`, including step durations and fields.
Run details link to a downloadable evidence bundle with the run metadata, artifact manifest, and
all run artifacts for interview review or incident handoff.
The dashboard create form accepts optional source URLs, one per line.
The dashboard list supports database-backed status/topic filters, queue counts, and pagination.
The dashboard also surfaces recent worker executions from job receipts so scheduled content runs
can be reviewed from the same operational surface.
It also includes a Published Content catalog with shipped URLs, providers, timestamps, and
evaluation scores for portfolio and operations review.
It also includes Quality Scorecards that combine evaluation readiness, run duration SLOs, and
source-count thresholds for production-style operational review.
Token Budget reports estimate input/output tokens from persisted run artifacts and flag runs that
exceed the configured per-run budget.
Run detail pages can compare two runs to spot evaluation deltas, source-count changes, and source
overlap before publishing.
Reviewed runs must be approved before publishing unless an operator explicitly uses `force=true`.
Each decision is persisted as `approval.json` beside the other run artifacts.
Approval is blocked when the run scorecard fails or the estimated token budget is exceeded, giving
reviewers a governance gate instead of a passive report.
Each successful publish writes `publish-receipt.json`, which records the provider, target URL,
publish plan items, approval record, force flag, timestamp, before/after file hashes, and rollback
hints. Existing publish targets are copied into `publish-backups/` under the run artifact
directory before they are overwritten. Operators can run `contentops rollback-publish` or call
`POST /runs/{run_id}/rollback-publish` to restore backed-up files or delete files created by the
publish.
Review and publishing actions are appended to `audit-log.json` for operational traceability.
They also write `notification-log.json`; if `CONTENTOPS_NOTIFICATION_WEBHOOK_URL` is configured,
the same events are delivered to an external webhook without blocking the review workflow.

## Scheduled worker jobs

The worker can validate or execute YAML-defined content calendars:

```powershell
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --dry-run
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --receipt-dir artifacts/job-executions
```

Every worker execution writes a job receipt JSON file. Receipts include an execution id, dry-run
flag, start/end timestamps, duration, per-job status, run ids, artifact directories, published URLs,
tags, metadata, and errors. By default receipts are written under
`CONTENTOPS_ARTIFACT_ROOT/job-executions`, which is suitable for ECS/EventBridge logs and S3
artifact mirroring.
Receipts are queryable through `contentops job-executions`, `contentops job-execution`, and the
`/job-executions` API endpoints, giving scheduled workers a durable execution history.

Job files support a legacy single-job shape or a production-style batch:

```yaml
name: daily-ai-roundup
jobs:
  - name: production-llm-systems
    topic: "AI engineering signals for production LLM systems"
    publish: true
    source_urls: []
```

## Provider configuration

The default stack runs without external credentials. `hybrid` is fully local unless URLs are
provided; `discovery` also fetches configured RSS/Atom feeds for scheduled research jobs:

```text
CONTENTOPS_RESEARCH_PROVIDER=discovery
CONTENTOPS_RESEARCH_FEEDS=https://export.arxiv.org/api/query?search_query=cat:cs.AI%20OR%20cat:cs.CL%20OR%20cat:cs.LG&start=0&max_results=25&sortBy=submittedDate&sortOrder=descending
CONTENTOPS_RESEARCH_MAX_SOURCES=6
CONTENTOPS_RESEARCH_RETRY_ATTEMPTS=2
CONTENTOPS_RESEARCH_RETRY_BACKOFF_SECONDS=0.1
CONTENTOPS_RESEARCH_SEARCH_ENDPOINT=https://api.search.brave.com/res/v1/web/search
# CONTENTOPS_RESEARCH_SEARCH_API_KEY=
CONTENTOPS_RESEARCH_SEARCH_ENRICH=true
CONTENTOPS_GENERATOR_PROVIDER=template
CONTENTOPS_PUBLISHER_PROVIDER=static
CONTENTOPS_OPENAI_MODEL=gpt-5-mini
CONTENTOPS_OPENAI_TIMEOUT_SECONDS=60
CONTENTOPS_OPENAI_RETRY_ATTEMPTS=2
CONTENTOPS_OPENAI_RETRY_BACKOFF_SECONDS=0.5
CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true
# CONTENTOPS_OPERATOR_API_KEY=
CONTENTOPS_NOTIFICATION_TIMEOUT_SECONDS=5
# CONTENTOPS_NOTIFICATION_WEBHOOK_URL=
CONTENTOPS_LATENCY_SLO_MS=120000
CONTENTOPS_MIN_SOURCE_COUNT=1
CONTENTOPS_TOKEN_BUDGET_PER_RUN=12000
```

Research provider modes:

- `local`: deterministic CI-safe portfolio context
- `url`: fetch and normalize operator-supplied URLs
- `hybrid`: URL sources plus deterministic local context
- `feed`: discover sources from RSS/Atom feeds or Atom search endpoints
- `search`: discover sources from a Brave-compatible web search API and enrich result URLs
- `discovery`: feed discovery plus operator URLs plus local portfolio context

Network-backed research providers retry transient timeouts, connection errors, `429`, and `5xx`
responses according to `CONTENTOPS_RESEARCH_RETRY_ATTEMPTS` and
`CONTENTOPS_RESEARCH_RETRY_BACKOFF_SECONDS`.

Mirror artifacts to S3 in AWS deployments:

```text
CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3
CONTENTOPS_ARTIFACT_S3_BUCKET=your-artifact-bucket
CONTENTOPS_ARTIFACT_S3_PREFIX=contentops-artifacts
```

Install the optional AWS dependency before enabling S3 mirroring:
It also installs the Postgres driver used by RDS deployments.

```powershell
pip install -e ".[aws]"
```

Use Postgres/RDS for run metadata:

```text
CONTENTOPS_DATABASE_URL=postgresql+psycopg://contentops:password@host:5432/contentops
```

Protect write operations in shared environments:

```text
CONTENTOPS_OPERATOR_API_KEY=replace-with-a-long-random-secret
```

When configured, mutating API and dashboard actions require `X-ContentOps-Api-Key` or an
`api_key` query parameter. Read-only endpoints remain available for dashboards and integrations.
Set `CONTENTOPS_REQUIRE_READ_API_KEY=true` to protect dashboard pages, artifact downloads, source
audits, evidence bundles, job receipts, and the published-content catalog with the same operator
key. `/health` and `/ready` remain open for load balancers and deployment probes.
Every API response includes `X-ContentOps-Request-Id`; clients can provide that header to correlate
dashboard/API errors with logs and exported evidence bundles.

Use real source URLs:

```powershell
contentops run --topic "Agent observability" --source-url "https://example.com/article"
```

Use OpenAI generation:

```text
CONTENTOPS_GENERATOR_PROVIDER=openai
CONTENTOPS_OPENAI_API_KEY=...
CONTENTOPS_OPENAI_MODEL=gpt-5-mini
CONTENTOPS_OPENAI_TIMEOUT_SECONDS=60
CONTENTOPS_OPENAI_RETRY_ATTEMPTS=2
CONTENTOPS_OPENAI_RETRY_BACKOFF_SECONDS=0.5
CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true
```

The OpenAI provider retries transient timeouts, connection errors, `429`, and `5xx` responses.
When `CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true`, exhausted provider failures fall back to the
deterministic template generator so scheduled runs can still produce reviewable artifacts.

Publish into the portfolio homepage repository:

```text
CONTENTOPS_PUBLISHER_PROVIDER=homepage
CONTENTOPS_HOMEPAGE_REPO_PATH=C:\Users\wangz\Documents\Codex\2026-05-22\files-mentioned-by-the-user-zackwang\zack-ai-homepage
CONTENTOPS_HOMEPAGE_PUBLIC_BASE_URL=https://zemeng2015.github.io/zack-ai-homepage
```
