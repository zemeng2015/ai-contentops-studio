# Architecture

AI ContentOps Studio is organized around a run-oriented workflow. A run is the durable unit of
work for research, planning, drafting, evaluation, and publishing.

```mermaid
flowchart LR
  API[FastAPI API] --> Pipeline[ContentOps Pipeline]
  CLI[Typer CLI] --> Pipeline
  Worker[Worker / Scheduler] --> Pipeline
  Pipeline --> Research[Research Provider]
  Pipeline --> Planner[Content Planner]
  Pipeline --> Generator[Content Generator]
  Pipeline --> Evaluator[Evaluation Engine]
  Pipeline --> Publisher[Publishing Adapter]
  Pipeline --> Store[Artifact Store]
  Pipeline --> DB[(SQLite / Postgres)]
  Store --> Artifacts[research.json / source-audit.json / draft.md / eval-report.json / trace.json]
```

## Boundaries

- `apps/api` owns HTTP transport.
- `apps/cli` owns local operator workflows.
- `apps/worker` owns scheduled execution.
- `packages/core` owns domain models and orchestration.
- `packages/providers` owns external data/model adapters.
- `packages/evaluators` owns quality checks.
- `packages/publishing` owns output targets.
- `packages/observability` owns traces and run events.

## Run lifecycle

```text
created -> researching -> planning -> drafting -> evaluating -> needs_review
created -> researching -> planning -> drafting -> evaluating -> publishing -> published
failed
```

Publishing is only allowed after evaluation. In production, `needs_review` becomes the handoff
point for a dashboard review workflow.

## Review workflow

The review service lets an operator inspect artifacts from an existing run and publish that run
later:

- list artifact names for a run
- inspect an artifact manifest with size, media type, timestamp, and sha256 metadata
- read individual artifacts such as `research.json`, `draft.md`, or `eval-report.json`
- publish an existing run after evaluation, with an explicit force option for overrides
- preview file-level publish changes through `PublishPlan` before mutating targets

This separates generation from publication and creates a natural seam for a dashboard or approval
queue.

The FastAPI app includes a lightweight server-rendered dashboard at `/dashboard` so the project has
a usable review surface before a larger React dashboard is introduced.
The dashboard list and `/review-queue` endpoint use repository-level filtering, counting, and
pagination so operators can review larger queues without loading only the most recent local slice.

The dashboard and API expose run metrics derived from `trace.json`: total duration, per-step
durations, source count, source audit score, and publish readiness. This keeps observability tied
to persisted run artifacts rather than transient process logs.
The review layer also builds operational scorecards from run metadata, `trace.json`, and
`eval-report.json`. Scorecards expose quality pass/fail, latency SLO pass/fail, source-count SLO
pass/fail, warnings, and aggregate pass rates through the dashboard, CLI, and `/scorecards` API.
Cost reports estimate input and output tokens from persisted artifacts, compare the estimate
against `CONTENTOPS_TOKEN_BUDGET_PER_RUN`, and expose per-run plus aggregate budget pass rates.
Each drafting step writes `generation-receipt.json`, recording the generator provider, model,
retry attempts, fallback state, and provider usage tokens when available. Cost reports prefer
these provider usage tokens and only fall back to artifact-based estimates when usage is missing.
Each research step also writes `source-audit.json`, which grades every source with reviewer-facing
reasons and recommendations before the draft moves into planning.
The API also exposes `/ready`, and the CLI exposes `contentops doctor`, to report database,
artifact store, provider configuration, and operator-key readiness without exposing secrets.

Each run now persists `request.json`, which enables reproducible reruns through the CLI, API, and
dashboard without relying on operator memory or external logs.
The CLI exposes the same review queue, artifact manifest, source audit, scorecard, and cost-report
surfaces as the API, so operators can script review checks without scraping dashboard HTML.

Run comparison is part of the review layer. It compares duration, source counts, source overlap,
publish readiness, and evaluation score deltas between a base run and a candidate run. This makes
regeneration and prompt/provider changes reviewable instead of subjective.

Approval is also part of the review layer. A generated run normally enters `needs_review`; an
operator can approve or reject it, and the decision is written to `approval.json`. Publishing a
reviewed run requires approval unless the operator uses an explicit force override. This gives the
system a real editorial control point instead of treating publish as a casual button click.
Approval also enforces operational governance: the run scorecard must pass and the estimated token
budget must remain within the configured per-run budget before an approval record is written.
The review queue supports batch approve and reject operations through the API, CLI, and dashboard;
each item returns its own result so one invalid run does not mask the rest of the batch.
Successful publishes write `publish-receipt.json`, which links the public URL back to the run,
publisher, approval record, force flag, publish plan items, before/after file hashes, and rollback
hints. Existing publish targets are backed up under the run artifact directory before they are
overwritten.
Publish verification reads the current target files and compares their hashes against the publish
receipt, producing `publish-verification.json` for drift detection after deploys or manual edits.
Incident reports sit above the review artifacts and aggregate run failures, scorecard warnings,
budget warnings, publish drift, and notification delivery failures into a single severity and
action-required flag. They are exposed through the dashboard, CLI, and API so operational triage
does not require manually opening every JSON artifact first.
The operations summary composes repository status counts with scorecards, cost reports, and
incident reports over a recent-run window. This gives operators one API/CLI/dashboard view for
queue depth, approved-but-unpublished work, failed runs, pass rates, average duration, incident
severity, and estimated token usage.
Operations trends bucket the same run, scorecard, cost, and incident evidence by calendar day.
They are exposed through `/ops-trends`, `contentops ops-trends`, and `/dashboard/ops-trends` so
operators can inspect publishing throughput, quality pass rate, budget posture, and incident
pressure without manually stitching together individual reports.
The deployment manifest reuses readiness checks and adds redacted runtime, security, operations,
and capability evidence. It is intended for release reviews, interview walkthroughs, and
automation that needs to understand deployment posture without exposing secrets.
Release readiness is the final gate above those operational surfaces. It combines readiness
checks, deployment capability status, open incidents, quality pass rates, budget pass rates, and
operator security into a `pass`, `warn`, or `fail` report with a machine-readable `can_release`
decision for CI, runbooks, or manual launch reviews.
Rollback uses that receipt to restore backed-up files or delete files created by the publish, then
records `publish-rollback.json` and a `rollback_publish` audit event.
Review actions append to `audit-log.json`, giving operators an immutable trail of approve, reject,
and publish transitions in addition to the latest run state.
The review service also exposes a global audit event view by scanning recent run audit logs and
sorting events by occurrence time. Operators can filter by run status, topic query, or action
without opening individual run artifact folders first.
The same review and publishing actions produce `notification-log.json` delivery receipts. By
default the local provider records skipped deliveries for auditability; when
`CONTENTOPS_NOTIFICATION_WEBHOOK_URL` is configured, events are posted to an external webhook and
success or failure is recorded without blocking the operator workflow.
Artifact retention reports scan recent run artifact directories, estimate file counts and storage
bytes, and identify runs older than a configured retention window. The report is intentionally
read-only so archive and cleanup decisions can be reviewed before any destructive operation.
Published runs are projected into a content catalog exposed through `/content`, `contentops content`,
and the dashboard. The catalog combines run metadata, publish receipts, URLs, providers, publish
timestamps, and evaluation scores so the platform can be reviewed as a content inventory instead
of a collection of one-off artifacts.
Each run can also be exported as an evidence bundle through `/runs/{id}/bundle` or
`contentops export-run`. The zip contains a bundle manifest plus every run artifact, which makes
generated research, evaluation, traces, approval records, and publishing receipts portable for
portfolio reviews or incident handoffs.

```text
needs_review -> approved -> publishing -> published
needs_review -> rejected
```

## Worker jobs

The worker accepts YAML job files in either a single-job shape or a batch `jobs:` shape. Batch job
files are the production path for content calendars, scheduled digests, daily AI research
roundups, and GitHub repository project updates.

```yaml
name: daily-ai-roundup
jobs:
  - name: production-llm-systems
    topic: "AI engineering signals for production LLM systems"
    publish: true
    source_urls: []
```

The worker supports dry-run validation for deployment checks and JSON output for automation logs:

```powershell
contentops worker-jobs --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --dry-run
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --json
contentops-worker run-pipeline pipelines/project_repository_updates.yaml --dry-run --json
```

The worker job catalog scans `CONTENTOPS_PIPELINE_DIR` and exposes planned calendars through
`GET /worker-jobs`, `contentops worker-jobs`, and the dashboard. Operators can review job count,
publish intent, topics, tags, and invalid YAML before EventBridge or a manual run executes it.

Every worker invocation writes a job execution receipt under `artifact_root/job-executions` by
default. Receipts include execution id, dry-run flag, timestamps, duration, job metadata, run ids,
artifact directories, publish URLs, and per-job errors, giving EventBridge/ECS-triggered runs an
auditable artifact even when stdout logs are rotated.
When a worker job creates a run, its workflow name, job name, tags, publish intent, and custom
metadata are copied into `request.json` and `workflow-context.json` inside the run artifact
directory. This lets reviewers open a run and understand which scheduled workflow produced it
without cross-referencing external logs.
The same receipt history is exposed through `GET /job-executions`, `GET /job-executions/{id}`,
`contentops job-executions`, `contentops job-execution`, and dashboard pages so operator review
does not depend on cloud log retention. The dashboard includes a content calendar view for
planned jobs plus a job execution detail view that links completed jobs back to generated runs,
source URLs, metadata, and recovery-plan JSON.
Failed executions also expose a recovery plan through
`GET /job-executions/{id}/recovery-plan` and `contentops job-recovery-plan`. The plan rebuilds the
failed jobs as a YAML-compatible content calendar while preserving topic, source URLs, publish
intent, tags, and metadata for controlled reruns.

## Production path

Local defaults:

- SQLite for run metadata
- filesystem for artifacts
- static site output directory

AWS-ready equivalents:

- RDS Postgres for run metadata
- S3 for artifacts through optional S3 mirroring
- EventBridge Scheduler for recurring runs
- ECS Fargate or Lambda for API/worker execution
- CloudWatch for logs and metrics
- Secrets Manager for provider credentials

The S3 artifact store keeps the local filesystem copy authoritative and mirrors each write to
S3. Every mirror attempt appends `s3-mirror-log.json` beside the run artifacts with provider,
bucket, key, content type, status, error, and timestamp fields. This makes object-level storage
state auditable even when cloud logs have rotated or a worker fails midway through a run.

The Terraform baseline now provisions an RDS Postgres metadata database and writes a
`postgresql+psycopg://` `CONTENTOPS_DATABASE_URL` into Secrets Manager for ECS task injection.
This keeps local SQLite useful for development while proving the production metadata path has a
real cloud target.

It also provisions an EventBridge Scheduler rule for the worker task. The schedule is disabled by
default so deployments can validate networking, RDS connectivity, and publishing configuration
before recurring content generation is turned on.

## Stage 2 provider boundaries

Research providers:

- `local`: deterministic source packet for CI and offline demos
- `url`: fetches operator-supplied URLs and normalizes title, publisher, and summary
- `hybrid`: combines URL sources with local portfolio context
- `github`: collects GitHub repository metadata, README text, open issues, and open pull requests
- `feed`: discovers candidate sources from configured RSS/Atom feeds or Atom search endpoints
- `search`: discovers candidate sources from a Brave-compatible web search API and enriches
  result URLs with fetched page metadata
- `discovery`: combines feed discovery, operator URLs, and local portfolio context

The search provider is the credentialed production path for open-web discovery. The GitHub
provider is the repository evidence path for launch posts, project writeups, and open-source
activity summaries. The discovery provider is the low-cost recurring path for curated feeds and
operator URLs. These providers let the worker start from a topic, retrieve current entries or
repository activity, rank or normalize the evidence, deduplicate canonical URLs, and persist the
discovered sources into `research.json`.
Network-backed research providers share a bounded retry policy for transient timeouts,
connection errors, `429`, and `5xx` responses so scheduled workers degrade gracefully when an
upstream source is briefly unavailable.

Generation providers:

- `template`: deterministic Markdown/HTML generation for repeatable tests
- `openai`: OpenAI Responses API generation, enabled only when credentials are configured;
  transient provider failures use bounded retry/backoff, and exhausted failures can fall back to
  the deterministic template generator for reviewable scheduled runs

Publishing providers:

- `static`: writes generated content to a local static site directory
- `homepage`: writes posts into Zack's GitHub Pages homepage repository, updates the Writing grid,
  records git branch/dirty state in the publish plan, and emits suggested `git add`, `commit`, and
  `push` commands for the homepage repo handoff. `contentops homepage-handoff` and
  `/runs/{id}/homepage-handoff` package the plan, generated article, eval report, and command list
  into a reviewable zip before the homepage repository is committed.
