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

![AI ContentOps Studio operations trends](docs/assets/ops-trends-dashboard.png)

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
- `publish-recovery-plan.json`
- `publish-recovery-execution.json`
- `audit-log.json`

## Features

| Area | Capability |
| --- | --- |
| Research | Local, URL, GitHub, feed, search, and discovery research providers |
| Generation | Template generator by default, optional OpenAI provider |
| Evaluation | Groundedness, source coverage, technical depth, publish readiness |
| Review | Review queue, status filters, batch approve/reject, run comparison |
| Publishing | Static site and git-aware homepage publishers, publish index, receipts, verification, rollback |
| Observability | Trace artifacts, scorecards, token budgets, incidents, operations summary |
| Scheduling | YAML worker jobs, dry runs, receipts, recovery plans |
| Release Evidence | Deployment manifest, release readiness gate, release approvals, hashed CI evidence manifest |
| Deployment | Docker image, Alembic migrations, S3 mirroring, RDS, EventBridge, CloudWatch |

## CLI Examples

```powershell
contentops demo-seed
contentops queue --status needs_review --json
contentops config-audit --json
contentops scorecard <run_id>
contentops source-audit <run_id>
contentops source-review <run_id> --source-key "https://example.com/source" --decision include
contentops source-reviews <run_id>
contentops publish-plan <run_id>
contentops approve <run_id> --reviewer "operator"
contentops publish <run_id>
contentops publish-receipt <run_id>
contentops publish-recovery-plan <run_id>
contentops run-publish-recovery <run_id> --action rollback --actor "operator"
contentops content-assets --output-dir site
contentops homepage-handoff <run_id> --output homepage-handoff.zip
contentops s3-mirror-log <run_id>
contentops release-evidence --output-dir release-evidence
contentops operations-console --days 14 --json
contentops provider-health --json
contentops release-approve --decision approved --approver "operator"
contentops release-approvals
contentops release-gate --git-sha <commit_sha> --json --record --checklist-output release-gate-checklist.md
contentops release-gates --json
contentops ops-brief --days 14 --json
contentops ops-brief-notify --days 14
contentops ops-brief-notifications
contentops ops-trends --days 14 --json
contentops retention-report --days 90 --json
contentops retention-archive --days 90
contentops retention-archives
```

`release-evidence` writes system status, deployment preflight, release gates, homepage handoff
inventory, content distribution manifests, publish verification summaries, publish recovery
execution summaries, source review summaries, worker execution trends, the daily operations brief,
the machine-readable operations console, retention archive receipts, and `evidence_manifest.json`
with SHA-256 hashes and file metadata for every evidence artifact, so CI output can be archived and
compared during deployment reviews.
The operations console combines the daily brief, worker health, release gate, retention
governance, and review queue into one JSON report for dashboards, CI checks, and external operator
automation.
The operations brief rolls provider health, worker alerts, run incidents, quality, budget, and
review queue pressure into a headline, top risks, and recommended actions for daily triage.
`contentops ops-brief-notify` sends that brief to the configured notification webhook and records
the attempt in `ops-brief-notification-log.json`; release evidence includes those receipts in
`ops_brief_deliveries.json`.
When a release approval exists, the evidence bundle also includes `release_approval.json` and the
API response includes `latest_release_approval`, closing the audit loop between review and deploy.
Source review decisions are operational gates, not just notes: excluded sources are removed from
the scorecard's effective source count, and `needs_review` source decisions block approval until a
reviewer resolves them. Pending source reviews also mark release evidence as not releasable and
make the deployment gate fail until the review is resolved.

## API Surface

Representative endpoints:

```text
POST /runs
GET  /runs
GET  /dashboard
GET  /dashboard/operations
GET  /dashboard/retention
GET  /dashboard/ops-brief
GET  /dashboard/ops-trends
GET  /dashboard/system-status
GET  /dashboard/release-evidence
GET  /review-queue
GET  /runs/{run_id}/artifacts
GET  /runs/{run_id}/scorecard
GET  /runs/{run_id}/source-audit
GET  /runs/{run_id}/source-reviews
POST /runs/{run_id}/source-reviews
GET  /runs/{run_id}/s3-mirror-log
GET  /runs/{run_id}/publish-plan
GET  /runs/{run_id}/publish-receipt
GET  /runs/{run_id}/publish-verification
GET  /runs/{run_id}/publish-recovery-plan
POST /runs/{run_id}/publish-recovery
GET  /runs/{run_id}/homepage-handoff
GET  /operations-console
GET  /ops-summary
GET  /ops-brief
POST /ops-brief/notify
GET  /ops-brief/notifications
GET  /ops-trends
GET  /content
POST /content-assets
GET  /content-assets/feed
GET  /content-assets/promotion-brief
GET  /content-assets/manifest
GET  /config-audit
GET  /provider-health
GET  /retention-report
POST /retention-archives
GET  /retention-archives
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
GET  /job-executions/trends
GET  /job-executions/{execution_id}/summary
POST /job-executions/{execution_id}/approve-runs
POST /job-executions/{execution_id}/publish-runs
```

The system status dashboard turns `/ready` and deployment manifest checks into operator-facing
configuration fixes, including missing API keys, scheduled research readiness, artifact storage,
database, and publishing-provider risks.
`config-audit` exposes a redacted runtime and secret posture report, so production operators can
verify required providers and credentials without leaking secret values.
Use `contentops init-config --profile production --path .env.production` or
`GET /deployment-env-template` to generate the same production environment template.
Use `contentops deployment-check --json` or `GET /deployment-check` as a pre-deploy gate that
combines system readiness, deployment capabilities, release gates, API security, and env-template
placeholder checks.
Use `contentops provider-health --json` or `GET /provider-health` to inspect research,
generation, and publishing provider posture, including credentials, scheduled readiness, retries,
cache configuration, and provider-specific warnings.
CI includes `deployment_check.json` inside release evidence and also uploads the standalone
`deployment-check/deployment-check.json` artifact, so deployment reviews can inspect the preflight
gate output without rerunning local commands.
The release evidence dashboard also renders those preflight checks for human review before a
deployment is approved.
Release approval records capture the approver, decision, notes, force flag, release/deployment
status, evidence SHA, and evidence files in `artifacts/release-approvals`.
`release-gate` combines readiness, deployment preflight, redacted configuration audit, approval
state, publish drift detection, content distribution readiness, and git SHA matching into a single
CI/CD pass/fail report.
Each check includes `remediation_steps`, giving operators concrete next actions when approval,
configuration, source governance, publish verification, content distribution, or deployment
preflight blocks a release.
The report also includes a human deployment checklist, and the CLI can write it with
`--checklist-output` for release review packets.
CI uploads `release-gate/release-gate.json` and `release-gate/deployment-checklist.md` as a
non-blocking report; deployment jobs can rerun the same command with `--strict` after an approval
exists.
Use `--record` to store local gate history under `artifacts/release-gates`, which is also exposed
through `/release-gates` and the release evidence dashboard. The history response includes a
rollup with pass rate, blocked deployments, consecutive failures, and the most common failed
checks, so operators can see whether release health is improving or degrading without opening
individual reports.

## Scheduled Jobs

Worker jobs are defined in YAML:

```yaml
name: daily-ai-roundup
schedule:
  enabled: true
  cron: "0 8 * * *"
  timezone: Asia/Shanghai
run_policy:
  timeout_minutes: 45
  concurrency_policy: forbid
  retry:
    max_attempts: 2
    backoff_seconds: 300
jobs:
  - name: production-llm-systems
    topic: "AI engineering signals for production LLM systems"
    publish: true
    homepage_handoff: true
    source_urls: []
    tags:
      - ai-engineering
      - portfolio
```

Run a worker job:

```powershell
contentops worker-jobs --json
contentops worker-job-readiness --json
contentops job-execution-summary <execution_id>
contentops job-execution-trends --days 14
contentops job-execution-alerts --days 14
contentops job-execution-alert-notify --days 14
contentops job-execution-alert-notifications
contentops job-execution-delivery-notify <execution_id>
contentops job-execution-delivery-notifications
contentops scheduled-workflow-summary `
  --output artifacts/scheduled-workflow-review.md `
  --pr-metadata-output artifacts/scheduled-pr-metadata.json `
  --manifest-output artifacts/scheduled-review-manifest.json
contentops scheduled-workflow-verify artifacts/scheduled-review-manifest.json --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --dry-run --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --receipt-dir artifacts/job-executions
```

`contentops worker-job-readiness` evaluates every YAML job file before it is wired into recurring
automation. It checks schedule presence, cron shape, timezone, timeout, retry policy, concurrency
policy, and whether publishing jobs create homepage handoff evidence. Use it as the preflight gate
before connecting the same YAML to GitHub Actions schedules, EventBridge, cron, or another runner.
This repository also includes `.github/workflows/scheduled-contentops.yml`, which runs the same
readiness gate, worker dry-run, scheduled execution, worker alert notification, ops brief receipt
archival, and artifact upload for the daily AI roundup and weekly project repository update
pipelines. Trigger it manually with
`workflow_dispatch` for a dry-run, then set repository secrets such as
`CONTENTOPS_RESEARCH_SEARCH_API_KEY`, `CONTENTOPS_RESEARCH_GITHUB_TOKEN`,
`CONTENTOPS_OPENAI_API_KEY`, and `CONTENTOPS_NOTIFICATION_WEBHOOK_URL` before relying on scheduled
live runs.
After a scheduled run, `contentops scheduled-workflow-summary` turns recent worker receipts into a
human-readable review packet with published URLs, homepage handoff artifacts, release evidence,
content distribution assets, failure reasons, the Operations Console snapshot, and next actions.
The scheduled workflow appends that Markdown to the GitHub Actions step summary and uploads it with
the rest of the worker artifacts, including a standalone `*-operations-console.json` report. The
packet also includes a suggested PR title and checklist so homepage or publishing changes can move
into a normal review PR without reconstructing the evidence by hand. Use `--pr-metadata-output` to
write the same PR title, body, Operations Console summary, content asset status, checklist, and
source execution ids as JSON for GitHub Actions or release tooling.
When manually starting `Scheduled ContentOps`, set `create_review_issue=true` to open a GitHub
issue containing the same review packet and a link back to the Actions run. This gives reviewers a
normal issue thread for follow-up before homepage or publishing changes are accepted.
Set `create_draft_pr=true` on a manual run to create a draft PR that commits the generated
scheduled review Markdown, PR metadata, and scheduled review manifest under `scheduled-reviews/`.
The manifest indexes worker receipts, delivery summaries, release evidence directories, content
asset paths, homepage handoffs, published URLs, and the Operations Console snapshot with file size,
media type, and SHA-256 metadata for audit review. Scheduled cron runs do not open PRs
automatically.
`contentops scheduled-workflow-verify` reloads that manifest, recomputes artifact metadata, and
fails when files are missing or hashes drift, making the review package suitable for pre-merge
automation.

Executed worker jobs automatically write post-run release evidence under
`artifacts/release-evidence/job-executions/<execution_id>` and record the evidence path, status,
and file list in the job execution receipt. Use `--release-evidence-dir` to choose a specific
evidence directory, or `--skip-release-evidence` for local smoke tests that should only write the
worker receipt. Worker execution trends and alerts also report the latest successful execution, the
latest action-required execution, the most common failure reasons, severity, and recommended actions
so recurring automation issues can be triaged from the dashboard or release evidence bundle. Each
top failure reason and alert signal includes `remediation_steps`, pointing operators to provider,
homepage handoff, release evidence, dry-run, or recovery-plan fixes. Failure reasons also include
stable categories such as `provider_failure`,
`content_distribution`, `delivery_summary`, `homepage_handoff`, and `release_evidence`, so
operators can group recurring issues by failure domain instead of reading raw logs.
notification attempts write `worker-alert-notification-log.json` beside worker execution receipts,
recording whether delivery was skipped locally, delivered to a webhook, or failed.
Non-dry-run executions also write `<execution_id>-delivery-summary.json` and
`<execution_id>-delivery-summary.md` beside the receipt. The summary lists published items,
distribution asset status, release evidence status, failures, and recommended next actions, and
release evidence records recent summaries in `worker_delivery_summaries.json`. The worker writes an
auditable `worker-delivery-summary-notification-log.json` after each summary; when
`CONTENTOPS_NOTIFICATION_WEBHOOK_URL` is configured, the JSON summary plus Markdown body are posted
to the webhook. Use `--skip-delivery-notification` for local runs that should not notify.
Worker executions also notify the operations brief before the final release evidence bundle is
written, so `ops_brief_deliveries.json` captures the actual post-run delivery attempt. Use
`--skip-ops-brief-notification` when a local run should generate evidence without sending or
recording the brief notification.
Operators can resend a delivery summary with `contentops job-execution-delivery-notify` or
`POST /job-executions/{execution_id}/delivery-summary/notify`, and review delivery history through
`contentops job-execution-delivery-notifications` or
`GET /job-executions/delivery-summaries/notifications`.
Set `homepage_handoff: true` on a job when the homepage publisher is configured and the scheduled
run should prepare a reviewable GitHub Pages handoff zip after the draft is generated. The handoff
path and any handoff error are stored on that job's execution result, and the post-run release
evidence indexes the zip in `homepage_handoffs.json`.
When a scheduled execution publishes content, the worker also refreshes `feed.xml`,
`promotion-brief.md`, and `content-distribution-manifest.json` from the publish index before it
builds release evidence. The receipt records the content asset path, generated files, status, and
any generation error, so recurring publishing jobs leave both content and distribution evidence.
The dashboard job execution detail page and `POST /job-executions/{execution_id}/approve-runs`
can approve every run generated by a scheduled worker execution in one reviewed action. After
approval, `POST /job-executions/{execution_id}/publish-runs` publishes the approved, publish-ready
runs and returns per-run success or failure results.

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
contentops job-recovery-plan <execution_id> --run --actor zack --notes "Retry provider timeout"
```

The API and dashboard can also run the recovery plan directly with
`POST /job-executions/{execution_id}/recovery-runs` or the job execution detail page. Recovery
executions write normal worker receipts and preserve `recovery_source_execution_id`,
`recovery_actor`, and `recovery_notes` metadata so reruns remain auditable. Recovery plans expose
`runnable`, `blocked_reason`, and `source_dry_run`; dashboard previews show the jobs that will be
retried, and dry-run receipts are blocked from recovery execution.

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
reviewable research sources. It also writes project intelligence metadata, such as README
availability, activity evidence, and repository maturity signals.
Research providers normalize canonical URLs, merge duplicates, classify source types, and attach
authority/relevance scores so `research.json` and `source-audit.json` explain why a source is
strong, weak, or needs reviewer spot-checking.
Set `CONTENTOPS_RESEARCH_CACHE_DIR` to enable URL fetch caching for direct URL research and search
result enrichment. `CONTENTOPS_RESEARCH_CACHE_TTL_SECONDS` controls how long cached page extracts
can be reused, reducing repeated network calls during scheduled worker reruns.

Publishing adapters also maintain `contentops-publish-index.json` beside the target site. This
machine-readable catalog records published article URLs, run ids, providers, timestamps, and
quality scores so a homepage, search indexer, RSS generator, or promotion workflow can consume
published content without scraping HTML.
Scheduled worker publishes refresh `feed.xml`, `promotion-brief.md`, and
`content-distribution-manifest.json` automatically. Operators can also run
`contentops content-assets` after manual publishing to regenerate the same assets for newsletters,
search indexing, or social promotion. The manifest includes asset hashes, git status, and suggested
`git add`, `commit`, and `push` commands for the site repository.
The search provider records its planned query variants, selected URLs, result counts, and
enrichment mode in `research.json`, which makes recurring web research easier to audit.

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
- AWS Terraform skeleton for S3, RDS, ECS task definitions, EventBridge Scheduler, worker alerts,
  ops brief notifications, release gate checks, retention archives, CloudWatch dashboard, and
  alarms

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
