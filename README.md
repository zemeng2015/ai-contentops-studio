# AI ContentOps Studio

[English](README.md) | [中文](README.zh-CN.md)

[![CI](https://github.com/zemeng2015/ai-contentops-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/zemeng2015/ai-contentops-studio/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

AI ContentOps Studio is an open-source platform for turning AI and technical topics into reviewed,
source-backed, publishable articles.

It collects sources, drafts content, evaluates quality, keeps a human review queue, publishes
approved work, and stores receipts so every run can be inspected later.

![AI ContentOps Studio demo walkthrough](docs/assets/demo-walkthrough.gif)

## What You Can Do

- Create technical articles from topics or source URLs.
- Review drafts before they are published.
- Check quality, source coverage, token budget, and incident signals.
- Publish approved content with file hashes, receipts, and rollback hints.
- Run recurring YAML content jobs with execution history and recovery plans.
- Deploy with Docker and AWS-ready Terraform resources.

## Screenshots

![AI ContentOps Studio dashboard](docs/assets/dashboard-screenshot.png)

![AI ContentOps Studio architecture overview](docs/assets/architecture-overview.svg)

## Quick Start

Run the demo with Docker:

```powershell
docker compose up --build -d api
docker compose run --rm demo-seed
```

Open the dashboard:

```text
http://localhost:8000/dashboard
```

The demo seed creates one published run, one approved run, and one run waiting for review.

## Local Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
contentops run --topic "LLM observability for enterprise RAG systems"
contentops runs
contentops doctor
```

Start the API:

```powershell
uvicorn contentops_api.main:app --reload --app-dir apps/api
```

Create a run:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/runs `
  -ContentType "application/json" `
  -Body '{"topic":"AI evaluation for RAG systems","publish":true}'
```

## Core Workflow

```text
Topic or URLs
  -> source research
  -> article planning
  -> draft generation
  -> quality evaluation
  -> human review
  -> publish approved content
  -> verify receipts and release evidence
```

Each run writes inspectable artifacts such as:

- `research.json`
- `request.json`
- `workflow-context.json`
- `draft.md`
- `eval-report.json`
- `scorecard.json`
- `approval.json`
- `publish-receipt.json`
- `publish-verification.json`
- `audit-log.json`

## Features

| Area | Capability |
| --- | --- |
| Research | Local, URL, GitHub, feed, search, and discovery research providers |
| Generation | Template generator by default, optional OpenAI provider |
| Evaluation | Groundedness, source coverage, technical depth, publish readiness |
| Review | Review queue, status filters, batch approve/reject, run comparison |
| Publishing | Static site and homepage publishers, receipts, verification, rollback |
| Observability | Trace artifacts, scorecards, token budgets, incidents, operations summary |
| Scheduling | YAML worker jobs, dry runs, receipts, recovery plans |
| Release Evidence | Deployment manifest, release readiness gate, release approvals, hashed CI evidence manifest |
| Deployment | Docker image, Alembic migrations, S3 mirroring, RDS, EventBridge, CloudWatch |

## CLI Examples

```powershell
contentops demo-seed
contentops queue --status needs_review --json
contentops scorecard <run_id>
contentops source-audit <run_id>
contentops publish-plan <run_id>
contentops approve <run_id> --reviewer "operator"
contentops publish <run_id>
contentops publish-receipt <run_id>
contentops s3-mirror-log <run_id>
contentops release-evidence --output-dir release-evidence
contentops release-approve --decision approved --approver "operator"
contentops release-approvals
contentops release-gate --git-sha <commit_sha> --json --record
contentops release-gates --json
```

`release-evidence` writes system status, deployment preflight, release gates, and
`evidence_manifest.json` with SHA-256 hashes and file metadata for every evidence artifact, so CI
output can be archived and compared during deployment reviews.
When a release approval exists, the evidence bundle also includes `release_approval.json` and the
API response includes `latest_release_approval`, closing the audit loop between review and deploy.

## API Surface

Representative endpoints:

```text
POST /runs
GET  /runs
GET  /dashboard
GET  /dashboard/system-status
GET  /dashboard/release-evidence
GET  /review-queue
GET  /runs/{run_id}/artifacts
GET  /runs/{run_id}/scorecard
GET  /runs/{run_id}/source-audit
GET  /runs/{run_id}/s3-mirror-log
GET  /runs/{run_id}/publish-plan
GET  /runs/{run_id}/publish-receipt
GET  /runs/{run_id}/publish-verification
GET  /ops-summary
GET  /deployment-manifest
GET  /deployment-check
GET  /deployment-env-template
GET  /release-readiness
GET  /release-evidence
GET  /release-evidence/bundle
GET  /release-approvals
POST /release-approvals
GET  /release-gate
GET  /release-gates
GET  /worker-jobs
GET  /job-executions
```

The system status dashboard turns `/ready` and deployment manifest checks into operator-facing
configuration fixes, including missing API keys, scheduled research readiness, artifact storage,
database, and publishing-provider risks.
Use `contentops init-config --profile production --path .env.production` or
`GET /deployment-env-template` to generate the same production environment template.
Use `contentops deployment-check --json` or `GET /deployment-check` as a pre-deploy gate that
combines system readiness, deployment capabilities, release gates, API security, and env-template
placeholder checks.
CI includes `deployment_check.json` inside release evidence and also uploads the standalone
`deployment-check/deployment-check.json` artifact, so deployment reviews can inspect the preflight
gate output without rerunning local commands.
The release evidence dashboard also renders those preflight checks for human review before a
deployment is approved.
Release approval records capture the approver, decision, notes, force flag, release/deployment
status, evidence SHA, and evidence files in `artifacts/release-approvals`.
`release-gate` combines readiness, deployment preflight, approval state, and git SHA matching into a
single CI/CD pass/fail report.
CI uploads `release-gate/release-gate.json` as a non-blocking report; deployment jobs can rerun the
same command with `--strict` after an approval exists.
Use `--record` to store local gate history under `artifacts/release-gates`, which is also exposed
through `/release-gates` and the release evidence dashboard.

## Scheduled Jobs

Worker jobs are defined in YAML:

```yaml
name: daily-ai-roundup
jobs:
  - name: production-llm-systems
    topic: "AI engineering signals for production LLM systems"
    publish: false
    source_urls: []
    tags:
      - ai-engineering
      - portfolio
```

Run a worker job:

```powershell
contentops worker-jobs --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --dry-run --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --receipt-dir artifacts/job-executions
```

Generate review-ready posts from GitHub project repositories:

```powershell
$env:CONTENTOPS_RESEARCH_PROVIDER="github"
$env:CONTENTOPS_RESEARCH_GITHUB_TOKEN="..."
contentops-worker run-pipeline pipelines/project_repository_updates.yaml --dry-run --json
contentops-worker run-pipeline pipelines/project_repository_updates.yaml --receipt-dir artifacts/job-executions
```

Failed worker executions can produce recovery YAML:

```powershell
contentops job-recovery-plan <execution_id> --output recovery.yaml
```

## Configuration

The default configuration runs locally without external credentials:

```text
CONTENTOPS_RESEARCH_PROVIDER=hybrid
CONTENTOPS_GENERATOR_PROVIDER=template
CONTENTOPS_PUBLISHER_PROVIDER=static
CONTENTOPS_DATABASE_URL=sqlite:///contentops.db
CONTENTOPS_ARTIFACT_ROOT=artifacts
```

Use OpenAI generation:

```text
CONTENTOPS_GENERATOR_PROVIDER=openai
CONTENTOPS_OPENAI_API_KEY=...
CONTENTOPS_OPENAI_MODEL=gpt-5-mini
CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true
```

Use GitHub repository research:

```text
CONTENTOPS_RESEARCH_PROVIDER=github
CONTENTOPS_RESEARCH_GITHUB_API_BASE_URL=https://api.github.com
CONTENTOPS_RESEARCH_GITHUB_TOKEN=...
```

Then pass repository URLs in `source_urls`, for example `https://github.com/owner/repo`.
The provider collects repository metadata, README text, open issues, and open pull requests as
reviewable research sources.

Use S3 artifact mirroring:

```text
CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3
CONTENTOPS_ARTIFACT_S3_BUCKET=your-artifact-bucket
CONTENTOPS_ARTIFACT_S3_PREFIX=contentops-artifacts
```

With S3 mirroring enabled, run artifacts, release evidence output, and worker execution receipts
write local `s3-mirror-log.json` records that include the bucket, key, content type, and mirror
status for each object.

Use Postgres/RDS:

```text
CONTENTOPS_DATABASE_URL=postgresql+psycopg://contentops:password@host:5432/contentops
```

Apply migrations:

```powershell
alembic upgrade head
```

Install AWS extras before enabling S3 or Postgres:

```powershell
pip install -e ".[aws]"
```

## Deployment

The repository includes:

- Docker image and Compose profile
- production environment template
- Alembic database migrations
- AWS Terraform skeleton for S3, RDS, ECS task definitions, EventBridge Scheduler, CloudWatch
  dashboard, and alarms

See [Deployment](docs/deployment.md) and [Production Runbook](docs/runbook.md).

## Documentation

- [Demo Walkthrough](docs/demo.md)
- [Showcase Package](docs/showcase.md)
- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [Production Runbook](docs/runbook.md)
- [Evaluation Methodology](docs/eval-methodology.md)
- [Integration Smoke Tests](docs/integration-smoke.md)
- [Contributing](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=zemeng2015/ai-contentops-studio&type=Date)](https://www.star-history.com/#zemeng2015/ai-contentops-studio&Date)

## License

This project is licensed under the [MIT License](LICENSE).
