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
- explicit approval records before reviewed runs are published
- API, CLI, worker, and publisher boundaries
- review dashboard with artifact, source, evaluation, and publish-plan inspection
- run comparison for repeatable quality and source regression review
- YAML-defined worker jobs for scheduled content calendars
- AWS-ready artifact storage and Terraform deployment skeleton
- local-first development with AWS-ready deployment primitives

## What it does

Given a topic, URL, or repository, the system creates a content run:

1. collect and normalize sources
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
- FastAPI artifact review endpoints and `POST /runs/{run_id}/publish`
- FastAPI metrics, rerun, publish-plan, and run-comparison endpoints
- Worker entrypoint for single-job or batch YAML content calendars
- CLI `contentops run`, `contentops runs`, `contentops show`, `contentops artifacts`, and
  `contentops publish`, plus review commands for metrics, rerun, publish-plan, and compare
- pytest coverage for pipeline behavior

## Review workflow

Generate first, inspect artifacts, then publish:

```powershell
contentops run --topic "AI quality gates for RAG systems"
contentops artifacts <run_id>
contentops show <run_id> --artifact eval-report.json
contentops publish-plan <run_id>
contentops metrics <run_id>
contentops compare <base_run_id> <candidate_run_id>
contentops approve <run_id> --reviewer "Zack" --notes "Ready to publish"
contentops rerun <run_id>
contentops publish <run_id>
```

The API exposes the same lifecycle:

```text
GET  /runs/{run_id}/artifacts
GET  /runs/{run_id}/artifacts/{artifact_name}
GET  /runs/{run_id}/publish-plan
GET  /runs/{run_id}/metrics
GET  /runs/{run_id}/approval
GET  /runs/{base_run_id}/compare/{candidate_run_id}
POST /runs/{run_id}/approve
POST /runs/{run_id}/reject
POST /runs/{run_id}/rerun
POST /runs/{run_id}/publish
```

The API also serves a lightweight dashboard at:

```text
GET /dashboard
```

Run details include a Source Review table so reviewers can inspect source status and extraction
quality before publishing.
Run details also include a Publish Plan that lists file-level changes before the publish action.
Run details include a timeline derived from `trace.json`, including step durations and fields.
The dashboard create form accepts optional source URLs, one per line.
The dashboard list supports status/topic filters, and run detail pages can compare two runs to
spot evaluation deltas, source-count changes, and source overlap before publishing.
Reviewed runs must be approved before publishing unless an operator explicitly uses `force=true`.
Each decision is persisted as `approval.json` beside the other run artifacts.

## Scheduled worker jobs

The worker can validate or execute YAML-defined content calendars:

```powershell
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --dry-run
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --json
```

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
CONTENTOPS_GENERATOR_PROVIDER=template
CONTENTOPS_PUBLISHER_PROVIDER=static
```

Research provider modes:

- `local`: deterministic CI-safe portfolio context
- `url`: fetch and normalize operator-supplied URLs
- `hybrid`: URL sources plus deterministic local context
- `feed`: discover sources from RSS/Atom feeds or Atom search endpoints
- `discovery`: feed discovery plus operator URLs plus local portfolio context

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

Use real source URLs:

```powershell
contentops run --topic "Agent observability" --source-url "https://example.com/article"
```

Use OpenAI generation:

```text
CONTENTOPS_GENERATOR_PROVIDER=openai
CONTENTOPS_OPENAI_API_KEY=...
CONTENTOPS_OPENAI_MODEL=gpt-5-mini
```

Publish into the portfolio homepage repository:

```text
CONTENTOPS_PUBLISHER_PROVIDER=homepage
CONTENTOPS_HOMEPAGE_REPO_PATH=C:\Users\wangz\Documents\Codex\2026-05-22\files-mentioned-by-the-user-zackwang\zack-ai-homepage
CONTENTOPS_HOMEPAGE_PUBLIC_BASE_URL=https://zemeng2015.github.io/zack-ai-homepage
```
