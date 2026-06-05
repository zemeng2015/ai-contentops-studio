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
It also includes disabled-by-default scheduled tasks for worker alerts, operations briefs, release
gates, and retention archive creation so operational checks can be enabled gradually. Scheduler
targets share an encrypted SQS dead-letter queue and DLQ depth alarm, which gives missed ECS task
invocations a concrete recovery path instead of relying only on log discovery.

## Provider environment variables

```text
CONTENTOPS_RESEARCH_PROVIDER=discovery
CONTENTOPS_RESEARCH_FEEDS=https://export.arxiv.org/api/query?search_query=cat:cs.AI%20OR%20cat:cs.CL%20OR%20cat:cs.LG&start=0&max_results=25&sortBy=submittedDate&sortOrder=descending
CONTENTOPS_RESEARCH_MAX_SOURCES=6
CONTENTOPS_RESEARCH_RETRY_ATTEMPTS=2
CONTENTOPS_RESEARCH_RETRY_BACKOFF_SECONDS=0.1
CONTENTOPS_RESEARCH_CACHE_DIR=/data/artifacts/research-cache
CONTENTOPS_RESEARCH_CACHE_TTL_SECONDS=86400
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

`CONTENTOPS_RESEARCH_CACHE_DIR` enables persistent URL extraction caching for URL research and
search-result enrichment. Keep it on durable worker storage in production so recurring jobs can
reuse recent extracts and reduce repeated external provider calls.

When publishing to a static site or homepage repository, preserve
`contentops-publish-index.json` with the rest of the site output. It is updated on every publish
and should be committed or deployed with the generated post, eval report, and homepage index so
downstream automation can discover published content from a stable JSON contract.
Run `contentops content-assets --output-dir <site-output>` after approved publishes to generate
`feed.xml` and `promotion-brief.md` from the same index. Deploy `feed.xml` with the site if RSS or
search discovery matters, and archive the promotion brief with release evidence when a reviewer
needs to approve external distribution copy.
The command also writes `content-distribution-manifest.json`, which records file hashes, git
status, and suggested commit commands for the generated distribution assets.
The API exposes the same workflow through `POST /content-assets` and read endpoints under
`/content-assets/*`, so deployed operators can generate and download distribution files without
shell access to the container.

For ECS or Lambda workers, set `CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3` so each local artifact
write is mirrored to S3 under:

```text
s3://$CONTENTOPS_ARTIFACT_S3_BUCKET/$CONTENTOPS_ARTIFACT_S3_PREFIX/<run_id>/<artifact>
```

Release evidence and worker execution receipts use the same bucket and prefix. Their local output
directories include `s3-mirror-log.json`, which records the bucket, key, content type, status, and
error message for every standalone artifact mirror attempt.
When distribution assets have been generated, release evidence also writes
`content_distribution.json` so deployment reviewers can verify the RSS feed, promotion brief, and
distribution manifest were prepared with file hashes before the site is deployed.
When `CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3` is configured, `contentops retention-archive` mirrors
retention zip files and archive receipts to S3 and writes a local `s3-mirror-log.json`. The AWS
retention archive scheduler runs the same command with `retention_archive_schedule_expression`,
`retention_archive_days`, and `retention_archive_scan_limit`; keep
`retention_archive_schedule_enabled=false` until the database and S3 artifact bucket are stable.
The same S3 settings are used by `contentops scheduled-workflow-archive`, which mirrors scheduled
review manifests, verification reports, package indexes, and archive ZIPs. Each package directory
keeps its own `s3-mirror-log.json`, and the scheduled review dashboard surfaces the mirror status
beside the package download link.

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
contentops integration-smoke-plan --json
```

```powershell
$env:CONTENTOPS_RUN_INTEGRATION="1"
pytest -m integration tests/test_integration_smoke.py
```

`GET /integration-smoke-plan` exposes the same readiness plan through the API for deployment
automation. Treat missing environment values as a warning until the operator intentionally opts
into live tests with `CONTENTOPS_RUN_INTEGRATION=1`.
Set `CONTENTOPS_OPENAI_API_KEY` for the OpenAI generation smoke test,
`CONTENTOPS_RESEARCH_SEARCH_API_KEY` for the Brave-compatible search smoke test, and
`CONTENTOPS_HOMEPAGE_REPO_PATH` for the read-only homepage publisher plan check. The homepage
target must be a git repository; publish plans include branch, dirty-state, relative paths, and
suggested `git add`, `commit`, and `push` commands for the generated post.

## Release evidence

Every CI run generates release evidence JSON artifacts that can be attached to release notes or
reviewed during deployment approval:

```powershell
python scripts/generate_release_evidence.py --output-dir release-evidence
```

The evidence bundle includes system status, deployment preflight checks, a redacted deployment
manifest, operations summary, release readiness gates, homepage handoff inventory, worker execution
trends, scheduled review package inventory, a summary file with the commit SHA, and
`evidence_manifest.json` with SHA-256 hashes, sizes, media types, and timestamps for the generated
evidence artifacts. The command exits non-zero only when release readiness is `fail`;
local-development `warn` states remain inspectable without blocking ordinary CI.
When homepage handoff zip files exist under the artifact root, `homepage_handoffs.json` records
their run id, relative artifact path, size, SHA-256 digest, and update time so personal homepage
publishing packages remain part of the release review trail.
`worker_execution_trends.json` records recent scheduled automation success, publish, handoff,
action-required rates, latest success/failure timestamps, and top failure reasons so release
reviewers can see whether recurring content operations are healthy and why they degraded. Top
failure reasons include `remediation_steps` so reviewers can move from diagnosis to recovery
without reverse-engineering the worker receipt.
`worker_execution_alerts.json` condenses the same worker signal into severity, action-required
state, alert signals, signal-level remediation steps, and recommended actions for release managers
or on-call handoff.
`worker_recovery_lineage.json` links failed worker executions to recovery attempts and marks each
source execution as recovered, partially recovered, or not started. The release gate fails when
this lineage still has an unrecovered backlog and downgrades fully recovered worker failures to a
warning so reviewers can inspect the closed-loop evidence before promotion.
`worker_execution_alert_deliveries.json` records worker alert notification receipts so release
reviewers can distinguish healthy no-op checks, local skipped delivery, successful webhook delivery,
and failed notification attempts.
If a release approval has been recorded, the same bundle includes `release_approval.json` and the
API response exposes it as `latest_release_approval`.
The same bundle is also available through the product surface:

```powershell
contentops release-evidence --output-dir release-evidence
Invoke-RestMethod http://127.0.0.1:8000/release-evidence
```

Record a deployment approval or rejection after reviewing the evidence:

```powershell
contentops release-approve --decision approved --approver "operator" --notes "Ready to deploy"
Invoke-RestMethod http://127.0.0.1:8000/release-approvals
```

Approvals are stored as JSON under `artifacts/release-approvals` with the approver, decision,
notes, release/deployment gate status, force flag, evidence SHA, and evidence file list. Approved
decisions require release readiness and deployment preflight to pass unless `--force` or
`force=true` is used, which keeps emergency releases explicit and auditable.

Use the release gate in deployment automation after the approval is recorded:

```powershell
contentops release-gate --git-sha $env:GITHUB_SHA --json --record --checklist-output release-gate-checklist.md
contentops release-gate --no-fail-on-block --json --record --checklist-output release-gate-checklist.md
Invoke-RestMethod "http://127.0.0.1:8000/release-gate?git_sha=$env:GITHUB_SHA"
```

The gate fails when release readiness fails, deployment preflight fails, required configuration
audit items are missing, published files drift from their receipts, distribution manifests are
incomplete, scheduled review package verification failed, scheduled review package S3 mirroring
failed, retention archive S3 mirroring failed, recent worker automation has failed jobs, no
approval exists, the latest approval rejects deployment, or the approval git SHA does not match the
commit being released.
It warns when published content has no distribution evidence, generated distribution files are
still dirty in git, recent worker automation requires operator review, live provider smoke tests
are not fully ready, recent smoke evidence is only a dry-run or missing, scheduled review manifests
are verified but missing archive ZIPs, or old artifact candidates exist without a non-dry-run
retention archive receipt.
Every release gate check also includes `remediation_steps`, so failed API, CLI, and dashboard
reports can point operators to the next command or review action instead of only exposing raw
status.
Release evidence also writes `publish_verifications.json`, which summarizes recent published run
verification status and links back to each run's `publish-verification.json` artifact.
CI also uploads a non-blocking `release-gate/release-gate.json` report with
`--no-require-approval`, plus `release-gate/deployment-checklist.md` with the human deployment
steps derived from the same gate checks. Review the checklist before promoting a build, then use
the default `--fail-on-block` behavior in an actual deployment job once approval is required.
Scheduled ContentOps runs use `--no-fail-on-block` to archive a release gate snapshot and checklist
even when the gate reports `fail`, so review packages still contain deployment posture evidence.
Review `provider_health.json` in release evidence or run `contentops provider-health --json`
before enabling scheduled jobs. Search research should show configured credentials, feed/discovery
providers should show scheduled readiness, and GitHub research should record whether a token is
configured for higher API limits or private repositories. Each provider health item includes
`remediation_steps`, so missing keys, feed URLs, homepage paths, or live model settings can be
fixed directly from the evidence bundle.
Review `integration_smoke_plan.json` in the same evidence bundle to confirm the live provider smoke
selectors and missing environment variables before opting into external smoke tests.
Review `integration_smoke_runs.json` beside it to inspect recent recorded smoke run history,
including dry-run plans, skipped providers, and failed live validations.
Review `ops_brief.json` or run `contentops ops-brief --days 14 --json` after each scheduled
execution window. It summarizes provider health, worker alerts, run incidents, quality, budget,
and review queue pressure into a status, top risks, and recommended operator actions.
Run `contentops ops-brief-notify --days 14` or call `POST /ops-brief/notify` when the brief should
be sent to the configured notification webhook. The delivery attempt is written to
`ops-brief-notification-log.json` and copied into release evidence as `ops_brief_deliveries.json`.
Recorded gate reports are stored under `artifacts/release-gates` and can be inspected through
`contentops release-gates --json` or `GET /release-gates`. Both surfaces include a release gate
history summary with pass rate, blocked deployment count, consecutive failures, latest status, and
the most common failed checks. Use that summary during deployment reviews to spot recurring
approval, configuration, source governance, or preflight failures before they become release
incidents.

The Terraform worker schedule is disabled by default. Enable it only after the container image,
private subnets, database connectivity, and feed configuration are ready:

```bash
terraform apply \
  -var='worker_schedule_enabled=true' \
  -var='worker_schedule_expression=cron(0 13 * * ? *)'
```

If a scheduled invocation fails before ECS starts the task, inspect the Terraform
`scheduler_dlq_url` output and the `scheduler_dlq_alarm_name` CloudWatch alarm. The DLQ retains
failed invocation payloads so operators can distinguish IAM, subnet, ECS capacity, and task
definition failures from application-level worker errors.

For repository-hosted automation before a full AWS rollout, enable the `Scheduled ContentOps`
GitHub Actions workflow. It runs `contentops worker-job-readiness --json`, worker dry-runs, live
worker executions, alert notification, ops brief receipt archival, and artifact upload for the
daily and weekly YAML calendars.
Use `workflow_dispatch` with `dry_run_only=true` for the first runs, then add repository secrets
for live providers and notifications before relying on scheduled executions.
When a reviewer should explicitly triage a run, dispatch the workflow with
`create_review_issue=true`. The workflow uses the repository `GITHUB_TOKEN` with `issues: write` to
open a review issue containing the scheduled summary and the Actions run URL. Keep that switch off
for unattended schedules unless the team wants every run to become a tracked review item.
Dispatch with `create_draft_pr=true` when the scheduled review should become a draft PR. The
workflow uses `contents: write` and `pull-requests: write` to create a `contentops/scheduled-*`
branch, commit the review Markdown, PR metadata JSON, and review manifest under
`scheduled-reviews/`, and open a draft PR using the generated PR title and body. The manifest
indexes worker receipts, delivery summaries, release evidence, content asset paths, homepage
handoffs, published URLs, and the Operations Console snapshot with size, media type, SHA-256, and
missing-file metadata. Keep this manual until the team is comfortable with automatic publishing
review branches.
The workflow verifies that manifest immediately with `contentops scheduled-workflow-verify`; rerun
the same command before merging if a review branch is updated after creation.
It then runs `contentops scheduled-workflow-archive` to upload a ZIP package containing the
manifest, verification report, package index, receipts, release evidence, content assets, and
homepage handoff files. Treat this ZIP as the portable review artifact for release notes or audit
handoff. In S3 artifact mode, this command also mirrors the package files and writes
`s3-mirror-log.json` so archive storage can be audited independently from GitHub Actions artifacts.
When those scheduled artifacts are retained under the configured artifact root, operators can use
`GET /scheduled-reviews` or `/dashboard/scheduled-reviews` to inspect verification status and
download the archive ZIP without opening the raw Actions artifact browser. Release evidence copies
the same package inventory, including S3 mirror status, into `scheduled_review_packages.json`.
Operators can trigger `POST /scheduled-reviews/{package_id}/archive` or the dashboard archive
action to rebuild the ZIP and retry S3 mirroring from the API layer. Use
`GET /scheduled-reviews/{package_id}/s3-mirror-log` or the dashboard log link to inspect the
mirrored bucket, key, status, and error for each package object.

For shared API or dashboard deployments, store an operator key in Secrets Manager and pass its ARN
through `operator_api_key_secret_arn`. Once `CONTENTOPS_OPERATOR_API_KEY` is set, mutating routes
require `X-ContentOps-Api-Key` or an `api_key` query parameter.
Run `contentops config-audit --json` or open `/config-audit` before sharing the deployment. The
audit reports runtime provider choices and required secret readiness while redacting all secret
values. The same redacted audit is embedded in `contentops release-gate --json`, and required
configuration failures block deployment.
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
`--receipt-dir` is provided. Non-dry-run executions also generate post-run release evidence under
`CONTENTOPS_ARTIFACT_ROOT/release-evidence/job-executions/<execution_id>` unless
`--release-evidence-dir` or `--skip-release-evidence` is provided. The worker receipt records the
evidence path, release status, evidence files, and any evidence generation error so scheduled
automation can be audited from a single JSON record.
The worker also writes a delivery summary in JSON and Markdown beside the receipt. Use the Markdown
file for human review or notification handoff, and use `worker_delivery_summaries.json` in release
evidence to verify recent scheduled publishing outcomes during deployment reviews.
When `CONTENTOPS_NOTIFICATION_WEBHOOK_URL` is configured, the worker posts that delivery summary to
the webhook and records the result in `worker-delivery-summary-notification-log.json`; release
evidence mirrors the log as `worker_delivery_summary_deliveries.json`.
The worker also sends the operations brief before the final release evidence bundle is written.
That delivery receipt is stored in `ops-brief-notification-log.json`, copied into scheduled
workflow artifacts, and mirrored into release evidence as `ops_brief_deliveries.json`. Use
`--skip-ops-brief-notification` for local runs that should keep the brief notification disabled.
When a worker execution publishes content, it also regenerates the content distribution assets in
the configured publishing target before release evidence is generated. The same receipt records the
asset path, status, generated filenames, and errors, and release evidence includes the resulting
content distribution manifest for CI/CD review.
In ECS/EventBridge deployments, keep artifact mirroring enabled so these receipts are copied to S3
with the rest of the run artifacts and release evidence.
Terraform also defines a disabled-by-default worker alert notifier task. Enable
`worker_alert_schedule_enabled=true` after the recurring worker is writing receipts, and tune
`worker_alert_schedule_expression` plus `worker_alert_window_days` to run
`contentops job-execution-alert-notify` after the worker schedule. The notifier records
`worker-alert-notification-log.json`; release evidence mirrors those receipts in
`worker_execution_alert_deliveries.json`. Release evidence also writes
`worker_recovery_lineage.json`, which the release gate uses to block unrecovered worker backlog.
Terraform also defines a disabled-by-default operations brief notifier task. Enable
`ops_brief_schedule_enabled=true` after the recurring worker is writing useful run history, and
tune `ops_brief_schedule_expression`, `ops_brief_window_days`, and `ops_brief_window_size` to run
`contentops ops-brief-notify` after the worker schedule. The notifier records
`ops-brief-notification-log.json`; release evidence mirrors those receipts in
`ops_brief_deliveries.json`.
Terraform also defines a disabled-by-default release gate scheduler. Enable
`release_gate_schedule_enabled=true` after release approvals and source review governance are part
of the operating rhythm, and tune `release_gate_schedule_expression`, `release_gate_window_size`,
and `release_gate_require_approval` for the deployment environment. The task runs
`contentops release-gate --record --json`, records release gate reports under the artifact root,
and exits non-zero when deployment is blocked, making release readiness visible in EventBridge and
CloudWatch.
Worker job definitions are discovered from `CONTENTOPS_PIPELINE_DIR` and exposed through
`contentops worker-jobs`, `GET /worker-jobs`, and the dashboard so scheduled calendars can be
reviewed before EventBridge launches them.
Jobs that set `homepage_handoff: true` generate a homepage handoff zip after a successful run when
`CONTENTOPS_PUBLISHER_PROVIDER=homepage` is configured. The worker receipt stores the handoff path
or error for each job, and the post-run release evidence records those zip files in
`homepage_handoffs.json`.
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
