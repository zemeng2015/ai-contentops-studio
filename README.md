# AI ContentOps Studio

[English](README.md) | [中文](README.zh-CN.md)

[![CI](https://github.com/zemeng2015/ai-contentops-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/zemeng2015/ai-contentops-studio/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

AI ContentOps Studio is a production-shaped platform for AI-assisted technical research,
source-grounded article generation, quality evaluation, release evidence, and publishing
operations.

In plain English: this is a tool that helps a person or team turn AI/tech topics into reviewed,
source-backed articles. It finds or accepts sources, drafts the article, checks quality, keeps a
review queue, publishes approved work, and records evidence so people can trust what happened.

It is built as a portfolio-grade Applied AI Engineering project: not a prompt demo, but a
small operating system for repeatable content workflows with API, CLI, dashboard, worker jobs,
audit trails, quality gates, and AWS-ready deployment boundaries.

## Why This Project

Most content-generation demos stop at "send prompt, get article." This project shows the parts a
real team needs after the first successful prompt:

- research sources are captured and audited
- generation is traceable and reviewable
- quality, latency, cost, incidents, and release readiness are measured
- publishing is gated by approval and creates receipts
- scheduled jobs leave execution evidence and recovery plans
- local development works without credentials, while provider boundaries are ready for OpenAI,
  search APIs, S3, RDS, ECS, and EventBridge

## Table of Contents

- [Features](#features)
- [Demo](#demo)
- [What The GUI Shows](#what-the-gui-shows)
- [Showcase Package](#showcase-package)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Review And Operations Workflow](#review-and-operations-workflow)
- [API And CLI](#api-and-cli)
- [Worker Jobs](#worker-jobs)
- [How To Run It Automatically](#how-to-run-it-automatically)
- [How To Promote This Project](#how-to-promote-this-project)
- [Provider Configuration](#provider-configuration)
- [Testing](#testing)
- [Roadmap](#roadmap)
- [Star History](#star-history)
- [License](#license)

## Features

For non-technical readers, the product does five practical jobs:

1. turns a topic into a draft article
2. keeps links, sources, and generated files together
3. tells the reviewer whether the article looks safe to publish
4. publishes only approved content
5. records logs, receipts, and release evidence for later review

| Area | Capability |
| --- | --- |
| Research | Local, URL, feed, search, and discovery research providers with source normalization |
| Generation | Template generator by default, optional OpenAI generator behind a provider interface |
| Evaluation | Groundedness, source coverage, source quality, career relevance, and publish readiness |
| Review | Review queue, status/search filters, batch approve/reject, run comparison, dashboard detail pages |
| Governance | Approval records, audit logs, operator API key protection, read API key protection |
| Publishing | Static site and homepage publishers, publish plans, receipts, verification, rollback |
| Observability | Trace artifacts, scorecards, token budget reports, incident reports, operation summary |
| Release Evidence | Deployment manifest, release readiness gate, CI-generated evidence artifacts |
| Scheduling | YAML worker jobs, dry runs, execution receipts, job catalog, recovery plans |
| Deployment | Docker profile, startup migrations, Alembic, S3 artifact mirroring, Terraform skeleton |

## Demo

```powershell
docker compose up --build -d api
docker compose run --rm demo-seed
```

Open:

```text
http://localhost:8000/dashboard
```

The seed command creates published, approved, and needs-review runs so you can inspect the
dashboard, artifacts, receipts, scorecards, incidents, release evidence, and static site output
immediately.

More details: [Demo Walkthrough](docs/demo.md)

## What The GUI Shows

The main dashboard is the operator workspace. A reviewer can create new content runs, filter the
review queue, approve or reject articles, inspect quality signals, check worker jobs, and review
published content from one place.

![AI ContentOps Studio dashboard](docs/assets/dashboard-screenshot.png)

## Showcase Package

For a fast portfolio review, start with the curated [Showcase Package](docs/showcase.md). It
includes:

- a clean dashboard screenshot
- a one-page architecture diagram
- three sample article outputs
- a two-minute demo script
- interview talking points and promotion checklist

![AI ContentOps Studio architecture overview](docs/assets/architecture-overview.svg)

## Quick Start

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

Create a run through HTTP:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/runs `
  -ContentType "application/json" `
  -Body '{"topic":"AI evaluation for RAG systems","publish":true}'
```

## Architecture

```text
apps/
  api/                     FastAPI service and review dashboard
  cli/                     Typer command line interface
  worker/                  Scheduled YAML worker entrypoint
packages/
  core/                    Domain models, orchestration, storage, diagnostics
  providers/               Research, model, search, and external-system adapters
  evaluators/              Quality and groundedness checks
  publishing/              Static site and homepage publishers
  observability/           Structured run tracing
pipelines/                 YAML content calendars
docs/                      Architecture, deployment, demo, runbook, integration docs
infra/                     Terraform and deployment skeleton
tests/                     Unit and integration tests
```

Core design principles:

- Every pipeline step writes inspectable artifacts.
- Generated content is evaluated before publication.
- Publishing is an explicit state transition with receipts and rollback hints.
- External services sit behind provider interfaces.
- Local defaults are deterministic; production paths are AWS-ready.

Read more:

- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [Production Runbook](docs/runbook.md)
- [Integration Smoke Tests](docs/integration-smoke.md)

## Review And Operations Workflow

AI ContentOps Studio treats each article as an auditable run:

1. collect and normalize sources
2. extract engineering signals and claims
3. plan article angle and outline
4. generate Markdown and HTML drafts
5. evaluate quality, source coverage, and publish readiness
6. hold the run for review
7. approve, reject, publish, verify, or roll back
8. export evidence for release review or incident handoff

Useful commands:

```powershell
contentops demo-seed
contentops queue --status needs_review --json
contentops artifacts <run_id>
contentops show <run_id> --artifact eval-report.json
contentops scorecard <run_id>
contentops cost-report <run_id>
contentops source-audit <run_id>
contentops publish-plan <run_id>
contentops approve <run_id> --reviewer "Zack" --notes "Ready to publish"
contentops publish <run_id>
contentops publish-receipt <run_id>
contentops verify-publish <run_id>
contentops rollback-publish <run_id> --actor "Zack"
contentops export-run <run_id> --output run-evidence.zip
```

Operations and release checks:

```powershell
contentops doctor --json
contentops ops-summary --json
contentops deployment-manifest
contentops release-readiness --json
contentops release-evidence --output-dir release-evidence
```

## API And CLI

Representative API endpoints:

```text
POST /runs
GET  /runs
GET  /review-queue?status=needs_review&q=rag
GET  /runs/{run_id}/artifacts
GET  /runs/{run_id}/artifact-manifest
GET  /runs/{run_id}/bundle
GET  /runs/{run_id}/scorecard
GET  /runs/{run_id}/cost-report
GET  /runs/{run_id}/source-audit
GET  /runs/{run_id}/publish-plan
GET  /runs/{run_id}/publish-receipt
GET  /runs/{run_id}/publish-verification
GET  /runs/{run_id}/incident-report
GET  /runs/{run_id}/audit-log
GET  /runs/{base_run_id}/compare/{candidate_run_id}
GET  /content
GET  /scorecards
GET  /cost-reports
GET  /incident-reports
GET  /audit-events
GET  /retention-report
GET  /worker-jobs
GET  /job-executions
GET  /job-executions/{execution_id}/recovery-plan
GET  /ops-summary
GET  /deployment-manifest
GET  /release-readiness
GET  /release-evidence
GET  /ready
```

Dashboard:

```text
GET /dashboard
```

The dashboard includes review queues, run detail pages, source review, publish plans, scorecards,
token budgets, incident reports, audit events, retention reports, worker job catalogs, and worker
execution receipts.

## Worker Jobs

The worker validates and executes YAML-defined content calendars:

```powershell
contentops worker-jobs --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --dry-run --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --receipt-dir artifacts/job-executions
```

Example calendar:

```yaml
name: daily-ai-roundup
jobs:
  - name: production-llm-systems
    topic: "AI engineering signals for production LLM systems"
    publish: true
    source_urls: []
    tags:
      - ai-engineering
      - portfolio
```

Worker executions write receipts under `CONTENTOPS_ARTIFACT_ROOT/job-executions`. Failed receipts
can be converted into rerunnable recovery calendars:

```powershell
contentops job-executions --json
contentops job-execution <execution_id>
contentops job-recovery-plan <execution_id> --output recovery.yaml
```

## How To Run It Automatically

To make the project run on a real schedule, you need to connect four pieces:

1. **Choose the schedule**  
   Edit `pipelines/daily_ai_roundup.yaml` with the topics you want to publish or review every day.

2. **Choose the AI and research providers**  
   Keep the default local/template mode for demos, or set OpenAI/search API keys for real generated
   articles:

   ```text
   CONTENTOPS_GENERATOR_PROVIDER=openai
   CONTENTOPS_OPENAI_API_KEY=...
   CONTENTOPS_RESEARCH_PROVIDER=discovery
   ```

3. **Run the worker on a schedule**  
   Local option:

   ```powershell
   contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --receipt-dir artifacts/job-executions
   ```

   Production option: deploy the Terraform stack and enable EventBridge Scheduler:

   ```bash
   terraform apply \
     -var='worker_schedule_enabled=true' \
     -var='worker_schedule_expression=cron(0 13 * * ? *)'
   ```

4. **Connect publishing and notifications**  
   Configure the static/homepage publisher, protect the dashboard with API keys, and optionally set
   `CONTENTOPS_NOTIFICATION_WEBHOOK_URL` so approvals, publishes, and failures can notify you.

Recommended first automation path:

- run the worker once per day
- keep `publish: false` until you trust the outputs
- review articles in `/dashboard`
- approve and publish manually
- later turn on selected `publish: true` jobs

## How To Promote This Project

This project is strongest when presented as a real AI operations system, not just a content tool.

Good promotion angles:

- **LinkedIn post:** "I built an AI ContentOps platform that turns technical topics into reviewed,
  source-backed articles with approval gates, audit logs, worker jobs, and AWS observability."
- **Resume bullet:** "Built a production-style AI ContentOps platform with FastAPI, Typer,
  SQLAlchemy, Docker, Terraform, CloudWatch, scheduled workers, quality evaluation, and release
  evidence."
- **Portfolio page:** show the dashboard screenshot, explain the workflow in five steps, and link
  to the GitHub repo.
- **Demo video:** record a 2-3 minute walkthrough: create run, inspect sources, approve, publish,
  view receipt, show CloudWatch/Terraform evidence.
- **GitHub topics:** add `ai-engineering`, `llmops`, `fastapi`, `content-automation`,
  `terraform`, `aws`, `observability`, `portfolio-project`.

Suggested next polish items for promotion:

- add a short animated GIF of the dashboard workflow
- add 2-3 example generated articles
- add a one-page architecture diagram
- publish a blog post explaining how the system was designed

## Provider Configuration

The default stack runs locally without external credentials:

```text
CONTENTOPS_RESEARCH_PROVIDER=hybrid
CONTENTOPS_GENERATOR_PROVIDER=template
CONTENTOPS_PUBLISHER_PROVIDER=static
CONTENTOPS_DATABASE_URL=sqlite:///contentops.db
CONTENTOPS_ARTIFACT_ROOT=artifacts
```

Optional OpenAI generation:

```text
CONTENTOPS_GENERATOR_PROVIDER=openai
CONTENTOPS_OPENAI_API_KEY=...
CONTENTOPS_OPENAI_MODEL=gpt-5-mini
CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true
```

Optional S3 artifact mirroring:

```text
CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3
CONTENTOPS_ARTIFACT_S3_BUCKET=your-artifact-bucket
CONTENTOPS_ARTIFACT_S3_PREFIX=contentops-artifacts
```

Optional Postgres/RDS:

```text
CONTENTOPS_DATABASE_URL=postgresql+psycopg://contentops:password@host:5432/contentops
alembic upgrade head
```

Install AWS extras before enabling S3 or Postgres:

```powershell
pip install -e ".[aws]"
```

See [config/production.env.example](config/production.env.example) for the production environment
profile.

## Testing

```powershell
python -m ruff check .
python -m mypy apps packages tests
python -m pytest
```

Optional live provider smoke tests:

```powershell
$env:CONTENTOPS_RUN_INTEGRATION="1"
pytest -m integration tests/test_integration_smoke.py
```

The CI workflow also validates Docker image builds, Terraform formatting/validation, database
migrations, worker dry runs, release evidence generation, linting, type checking, and tests.

## Roadmap

- GitHub repository research provider
- richer dashboard filtering and saved views
- multi-tenant workspace configuration
- queue-backed worker execution
- deployable ECS/EventBridge reference environment

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=zemeng2015/ai-contentops-studio&type=Date)](https://www.star-history.com/#zemeng2015/ai-contentops-studio&Date)

## License

This project is licensed under the [MIT License](LICENSE).
