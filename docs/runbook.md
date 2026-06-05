# Production Runbook

This runbook describes how to operate AI ContentOps Studio as a small production platform, not as
a one-off demo script.

## 1. Preflight

Run these checks before a scheduled worker or manual publish window:

```powershell
contentops doctor --json
contentops ops-summary --json
contentops deployment-manifest
contentops release-readiness --json
contentops worker-jobs --json
contentops worker-job-readiness --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --dry-run --json
contentops-worker run-pipeline pipelines/project_repository_updates.yaml --dry-run --json
```

Expected result:

- `doctor` is `ok` or `degraded` with only intentional local-development warnings.
- `ops-summary` shows no unexpected failed runs or action-required incidents.
- `deployment-manifest` contains no secret values and shows expected runtime providers.
- `release-readiness` is `pass` or expected `warn`; it must not be `fail`.
- `scheduled_research_ready` is `ok` for production worker calendars that depend on live sources.
- `publishing_recovery` is `ok`, proving the configured publishing target can be planned safely.
- `worker-jobs` finds the expected calendars and reports `invalid_count=0`.
- `worker-job-readiness` reports `can_schedule=true` before a cron, EventBridge, or GitHub Actions
  schedule is enabled.
- Worker dry run writes a receipt under `CONTENTOPS_ARTIFACT_ROOT/job-executions`.
- Research and OpenAI retry settings are present when network-backed providers are enabled.

## 2. Daily AI Research Job

Use the worker for recurring content discovery:

```powershell
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --receipt-dir artifacts/job-executions
```

Use the GitHub repository workflow for review-ready project update drafts:

```powershell
$env:CONTENTOPS_RESEARCH_PROVIDER="github"
$env:CONTENTOPS_RESEARCH_GITHUB_TOKEN="..."
contentops-worker run-pipeline pipelines/project_repository_updates.yaml --receipt-dir artifacts/job-executions
```

For GitHub-hosted automation, use the `Scheduled ContentOps` workflow. It runs daily for
`pipelines/daily_ai_roundup.yaml`, weekly for `pipelines/project_repository_updates.yaml`, and can
be started manually with `workflow_dispatch`. Keep `dry_run_only=true` until repository secrets are
configured and the uploaded `scheduled-contentops-*` artifacts show the expected receipts, release
evidence, and alert notification log.
For a manual review loop, set `create_review_issue=true` on the workflow dispatch. The workflow
creates a GitHub issue with the same review packet shown in the Actions step summary plus a link to
the run, giving reviewers a durable place to approve follow-up work or request changes.
Set `create_draft_pr=true` only when the run should open a draft PR. The workflow commits
`scheduled-reviews/*.md`, PR metadata JSON, and a `*-manifest.json` review package index on a
`contentops/scheduled-*` branch. The manifest lists worker receipts, delivery summaries, release
evidence paths, content asset paths, homepage handoffs, published URLs, and the Operations Console
snapshot, with size, media type, SHA-256, and missing-file metadata for each local artifact. The
workflow uses the generated PR metadata as the draft PR title and body. Leave this disabled for
unattended cron runs unless every scheduled execution should create a review branch.
Use `contentops scheduled-workflow-verify <manifest.json> --json` before merging a scheduled
review PR to confirm every indexed artifact still exists and matches its recorded size and
SHA-256.
Use `contentops scheduled-workflow-archive <manifest.json> <package.zip> --json` when a reviewer
or release manager needs one downloadable evidence package. The command reruns verification first
and refuses to archive drifted or missing artifacts.

For feed, URL, discovery, or search-backed workers, set `CONTENTOPS_RESEARCH_CACHE_DIR` to a
durable artifact path and tune `CONTENTOPS_RESEARCH_CACHE_TTL_SECONDS` so repeated scheduled runs
reuse recent URL extracts instead of refetching unchanged pages.

After the worker runs:

```powershell
contentops worker-jobs --json
contentops job-executions --json
contentops job-execution <execution_id>
contentops job-execution-summary <execution_id>
contentops job-execution-trends --days 14
contentops scheduled-workflow-summary `
  --output artifacts/scheduled-workflow-review.md `
  --pr-metadata-output artifacts/scheduled-pr-metadata.json `
  --manifest-output artifacts/scheduled-review-manifest.json
contentops scheduled-workflow-verify artifacts/scheduled-review-manifest.json --json
contentops scheduled-workflow-archive artifacts/scheduled-review-manifest.json artifacts/scheduled-review-package.zip --json
contentops job-recovery-plan <execution_id> --output recovery.yaml
```

Review the worker catalog before execution, then inspect the execution receipt for per-job failures,
run ids, artifact directories, publish URLs, duration, and the post-run release evidence path.
Use `contentops job-execution-summary <execution_id>` or
`GET /job-executions/{execution_id}/summary` to scan generated runs, published runs, handoff
readiness, release evidence readiness, and whether operator action is required.
Use `contentops scheduled-workflow-summary` after a GitHub Actions or cron run to generate the
same review packet shown in the Actions step summary. It lists published URLs, homepage handoff
zip files, delivery summaries, release evidence paths, content distribution asset status, the
Operations Console summary, failure reasons, and next actions for the latest worker receipts. Use
the `PR Handoff` section as the starting PR title and checklist when publishing generated site or
homepage changes. The `--pr-metadata-output` JSON file is the machine-readable version for a later
draft PR creation step and includes the same Operations Console summary plus content asset fields.
The scheduled GitHub workflow also uploads `daily-operations-console.json` or
`project-updates-operations-console.json` as structured artifact data.
Use `GET /scheduled-reviews` or `/dashboard/scheduled-reviews` to review the persisted scheduled
package inventory from the artifact root. The dashboard shows manifest status, verification
failures, action-required state, ZIP size, ZIP hash, S3 mirror status, and archive download links
for release review.
Use `contentops job-execution-trends --days 14`, `GET /job-executions/trends?days=14`, or
`/dashboard/job-execution-trends` to check recurring automation success, publish, handoff, and
action-required rates before changing the EventBridge schedule. The trend view also lists the
latest successful execution, latest action-required execution, and top failure reasons so operators
can separate provider failures, homepage handoff failures, and release evidence failures quickly.
Use `contentops job-execution-alerts --days 14` or `GET /job-executions/alerts?days=14` when the
scheduler should return a single severity, action-required flag, and recommended actions for
on-call review. Use `contentops job-execution-alert-notify --days 14` or
`POST /job-executions/alerts/notify?days=14` to write an auditable delivery receipt; with no webhook
configured the receipt is local and skipped, while a configured webhook records delivered or failed.
Top failure reasons and alert signals include remediation steps for provider failures, homepage
handoff failures, release evidence failures, dry-run receipts, and generic recovery-plan reruns.
Use the failure `category` field in job execution trends and release evidence to separate
provider, publishing, content distribution, delivery summary, homepage handoff, and release
evidence failures before choosing a recovery path.
The same trend, alert, recovery lineage, and notification payloads are written to release evidence
as `worker_execution_trends.json`, `worker_execution_alerts.json`,
`worker_recovery_lineage.json`, and `worker_execution_alert_deliveries.json`, so compare the
dashboard with the latest CI evidence bundle when investigating scheduled automation regressions.
Release evidence also writes `scheduled_review_packages.json`, which records recent scheduled
review manifest status, verification failures, archive readiness, ZIP hashes, S3 mirror status,
and action-required state for audit handoff.
The release gate fails when any package verification status is `fail`, and warns when verified
manifests do not yet have an archive ZIP. It also fails when package S3 mirroring failed. Use
`/dashboard/scheduled-reviews` to inspect the package and rerun
`contentops scheduled-workflow-archive` before promotion. API operators can use
`POST /scheduled-reviews/{package_id}/archive` or the dashboard archive action for the same rebuild
and mirror retry when shell access is not available.
In AWS, mirror `artifacts/job-executions` to S3 with the rest of the artifact tree.
For non-dry-run worker executions, open the receipt's `release_evidence_path` to review the same
deployment preflight, release readiness, homepage handoff inventory, and evidence manifest produced
for CI/CD release reviews.
Before connecting a YAML pipeline to GitHub Actions schedules, EventBridge, cron, or another
runner, execute `contentops worker-job-readiness --json`. Treat `failed_count > 0` as a scheduling
blocker. Warnings should be reviewed by an operator, especially disabled schedules, one-attempt
retry policies, very short timeouts, or `allow` concurrency on publishing jobs.
Open `delivery_summary_markdown_path` when an operator needs the short human-readable outcome of a
scheduled run. The Markdown summary lists published URLs, content distribution status, release
evidence status, failures, and recommended actions; release evidence stores recent summaries in
`worker_delivery_summaries.json` for deployment review.
Check `worker-delivery-summary-notification-log.json` beside the worker receipts to confirm whether
the summary notification was skipped locally, delivered to the configured webhook, or failed. A
configured `CONTENTOPS_NOTIFICATION_WEBHOOK_URL` receives both the JSON summary and Markdown body.
Use `contentops job-execution-delivery-notify <execution_id>`, the dashboard execution detail
button, or `POST /job-executions/{execution_id}/delivery-summary/notify` when a stakeholder needs
the latest summary resent. Use `GET /job-executions/delivery-summaries/notifications` to audit the
delivery history without opening artifact files.
Check `ops-brief-notification-log.json` under the artifact root after non-dry-run worker
executions. The worker sends the operations brief before writing final release evidence, and
`ops_brief_deliveries.json` confirms whether the brief notification was skipped locally, delivered,
or failed for the same evidence window.
When a scheduled execution publishes content, check `content_assets_status` in the same receipt.
`generated` means the worker refreshed `feed.xml`, `sitemap.xml`, `promotion-brief.md`, and
`content-distribution-manifest.json` before release evidence was built; `failed` means the publish
index or publishing target needs repair before deployment.
If a scheduled job declares `homepage_handoff: true`, inspect `homepage_handoff_path` on that job
result before committing the personal homepage repository. A populated `homepage_handoff_error`
usually means the homepage publisher is not configured or the target path is not a git repository.
After reviewing a successful scheduled execution, use the dashboard job execution detail page or
`POST /job-executions/{execution_id}/approve-runs` to approve every generated run from that
execution as one operator action.
Then use the same dashboard detail page or `POST /job-executions/{execution_id}/publish-runs` to
publish approved runs from the execution. The response is per-run, so keep any failed item in the
review queue and inspect its run detail before retrying or forcing publication.
After a publish, confirm `contentops-publish-index.json` changed with the generated post and eval
report. Commit or deploy that JSON catalog with the site output because homepage aggregation,
search indexing, RSS generation, and promotion scripts can use it as the authoritative published
content feed.
For manual publishing outside the worker, generate distribution assets:

```powershell
contentops content-assets --output-dir site
```

Review `promotion-brief.md` before posting externally, and deploy `feed.xml` plus `sitemap.xml`
with the site when the published content should be discoverable by feed readers, search crawlers,
or automation.
Inspect `content-distribution-manifest.json` for the generated file hashes and suggested git
commands before committing the distribution assets.
Operators can also generate the same files from the dashboard Published Content section or by
calling `POST /content-assets`, then download them from `/content-assets/feed`,
`/content-assets/sitemap`, `/content-assets/promotion-brief`, and `/content-assets/manifest`.
The next release evidence run will include `content_distribution.json`; confirm it lists the
expected manifest hash and git status before shipping a site update.
If `contentops release-gate` reports `content_distribution=warn`, commit or intentionally stage the
generated feed, sitemap, promotion brief, and manifest before deployment. If it reports `fail`,
regenerate distribution assets because the manifest is incomplete.
If the gate reports `publish_verification=fail`, run `contentops verify-publish <run_id>` for each
drifting run in `publish_verifications.json`, then restore the expected target files, republish the
approved content, or roll the run back before regenerating release evidence.
If the gate reports `retention_archive_governance=warn`, run
`contentops retention-archive --days 90` before cleanup and regenerate release evidence. If it
reports `fail`, inspect the archive `s3-mirror-log.json` and fix S3 bucket, IAM, or network
configuration before rerunning the archive.
Use `/dashboard/retention` when you want the same lifecycle in one operator view: candidate
counts, archive receipts, S3 mirror status, and the release gate governance check.
Use `contentops publish-recovery-plan <run_id>` or
`GET /runs/{id}/publish-recovery-plan` before changing files. The plan writes
`publish-recovery-plan.json` and classifies each target file as `ok`, `missing`, or `mismatch` with
recommended restore, republish, or rollback actions.
To remove a drifted publish through the governed recovery path, run
`contentops run-publish-recovery <run_id> --action rollback --actor <name>` or call
`POST /runs/{id}/publish-recovery` with `{"action":"rollback"}`. This writes
`publish-recovery-execution.json` and uses the existing rollback audit and notification path.
The next release evidence bundle will include `publish_recovery_executions.json`; review it to
confirm the recovery action completed and did not leave rollback errors before approving another
deployment.
When preparing a deployment handoff, run
`contentops release-gate --git-sha <sha> --json --record --checklist-output release-gate-checklist.md`
and review the Markdown checklist with the JSON report. The checklist translates failed or warning
gate checks into operator actions, so it should be attached to the release review alongside the
release evidence archive.
For S3-backed runs, inspect each run's `s3-mirror-log.json` to confirm the bucket/key path and
whether any artifact mirror attempt failed before the worker completed.
Worker receipt directories and release evidence directories also write `s3-mirror-log.json` when
`CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3`, so scheduled execution receipts and deployment evidence
can be traced to exact S3 keys.
Use `contentops s3-mirror-log <run_id>`, `GET /runs/{id}/s3-mirror-log`, or the dashboard run
detail page to inspect run-level mirror records without opening the artifact directory manually.
When failures occur, inspect the recovery plan before rerunning it with
`contentops-worker run-pipeline recovery.yaml`. For an operator-driven recovery loop, use
`contentops job-recovery-plan <execution_id> --run --actor <name> --notes <reason>`,
`POST /job-executions/{execution_id}/recovery-runs`, or the dashboard job execution detail page to
run only failed jobs and write a new audited worker receipt. Recovery job metadata records
`recovery_source_execution_id`, `recovery_actor`, and `recovery_notes`. Recovery plans expose
`runnable`, `blocked_reason`, and `source_dry_run`; use the dashboard preview to confirm which jobs
will rerun. Dry-run receipts are schedule previews and are intentionally blocked from recovery
execution. Use `contentops job-recovery-lineage --days 14`,
`GET /job-executions/recovery-lineage`, or `/dashboard/job-execution-trends` to verify whether the
failed execution is recovered, partially recovered, or still waiting for a recovery attempt.
The Operations Brief uses the same lineage: unrecovered worker backlog is raised as a
`worker_recovery` risk, while fully recovered worker failures remain visible as warnings for
release review.

## 3. CloudWatch Operations

For AWS deployments, inspect the Terraform-created CloudWatch dashboard before and after scheduled
worker windows:

- API and worker log-derived error metrics should remain at zero.
- RDS metadata database connections should stay below the configured threshold.
- ECS CPU and memory should leave enough headroom for retries and source enrichment.
- Recent API and worker failure log tables should be empty or explainable.

If `alarm_actions` is configured, API error, worker failure, and RDS connection alarms page the
configured SNS or incident-management targets. When an alarm fires, first inspect
`/dashboard/operations`, `/dashboard/system-status`, `/dashboard/release-evidence`,
`/ops-summary`, `/job-executions`, and the relevant CloudWatch log table before rerunning or
rolling back content. Use `/dashboard/operations` as the high-level operator console across daily
briefs, worker health, release gates, and retention governance. Use `/release-evidence`
when an automation or deployment script needs the same evidence in JSON form, or
`/release-evidence/bundle` when a reviewer needs a downloadable evidence package.
The system status dashboard includes recommended fixes for degraded or failed checks, including
the environment variables needed for API protection, scheduled research, artifact mirroring, and
publishing readiness.

## 4. Review Queue

List content awaiting operator review:

```powershell
contentops queue --status needs_review --json
```

For each candidate:

```powershell
contentops manifest <run_id>
contentops incident-report <run_id>
contentops source-audit <run_id> --json
contentops metrics <run_id>
contentops scorecard <run_id>
contentops cost-report <run_id>
contentops generation-receipt <run_id>
contentops show <run_id> --artifact eval-report.json
```

Approval is blocked when the scorecard fails or the cost report exceeds the configured token
budget. Reject the run with notes, tune the source/provider configuration, or rerun with a narrower
topic before trying to approve again.

```powershell
contentops approve <run_id> --reviewer "Zack" --notes "Sources and evaluation reviewed."
```

Reject weak runs with an explicit reason:

```powershell
contentops reject <run_id> --reviewer "Zack" --notes "Needs stronger source coverage."
```

## 5. Publish

Preview the publish changes:

```powershell
contentops publish-plan <run_id>
```

Publish only approved runs:

```powershell
contentops publish <run_id>
contentops publish-receipt <run_id>
contentops verify-publish <run_id>
contentops notifications <run_id>
```

Confirm that `publish-receipt.json` includes provider, URL, approval, file changes, backup
artifacts, and rollback hints. Confirm that `notification-log.json` recorded local skipped
deliveries or webhook delivery status for approve/publish events. Confirm that publish
verification passes so current target files still match the receipt hashes.

## 6. Published Content Inventory

Track shipped content as an operational catalog:

```powershell
contentops content --json
contentops scorecards --json
contentops cost-reports --json
contentops audit-events --json
contentops retention-report --days 90 --json
contentops retention-archive --days 90
contentops retention-archives
contentops operations-console --days 14 --json
contentops ops-summary --json
contentops ops-trends --days 14 --json
contentops release-readiness --json
```

The same catalog is available from:

```text
GET /content?limit=20&offset=0
GET /job-executions/{execution_id}/recovery-plan
GET /job-executions/recovery-lineage
GET /scorecards?limit=20&offset=0
GET /cost-reports?limit=20&offset=0
GET /audit-events?limit=20&offset=0
GET /retention-report?days=90&limit=100
POST /retention-archives?days=90&limit=100
GET /retention-archives?limit=20&offset=0
GET /incident-reports?limit=20&offset=0
GET /operations-console?days=14&window_size=100
GET /ops-summary?window_size=100
GET /ops-trends?days=14&window_size=500
GET /deployment-manifest
GET /release-readiness?window_size=100
```

Use it to review shipped URLs, providers, publish timestamps, evaluation scores, pass rates,
latency SLOs, and source-count SLOs.
Use the operations console when you need one machine-readable report covering the daily brief,
worker automation alerts, release gate status, retention governance, and queue pressure. Use
operations trends when you need a daily view of publishing throughput, failed runs, quality rate,
budget posture, and action-required incidents.
Use the retention report to estimate artifact storage usage and identify runs old enough for
manual archive or cleanup review. Use retention archives to create a non-destructive zip plus
JSON receipt before any cleanup; release evidence includes recent archive receipts in
`retention_archives.json`.
Cost reports prefer provider usage tokens from `generation-receipt.json`. When usage is missing,
they fall back to artifact-based estimates; use those estimates as a budget guardrail and
correlate with provider billing dashboards for financial reporting.

## 7. Evidence Export

Export a run for portfolio review, incident handoff, or offline audit:

```powershell
contentops export-run <run_id> --output run-evidence.zip
```

The zip contains `bundle-manifest.json` and every run artifact, including request, research,
source audit, draft, evaluation, trace, approval, audit log, and publish receipt when present.

## 8. Rollback

If a publish needs to be undone:

```powershell
contentops rollback-publish <run_id> --actor "Zack"
contentops audit-log <run_id>
contentops audit-events --action rollback_publish --json
```

Rollback restores backed-up files or deletes newly created files according to the publish receipt.
It then writes `publish-rollback.json`, appends a `rollback_publish` audit event, clears the
published URL, and returns the run to an approved or reviewable state.

## 9. Incident Checks

When a scheduled job fails:

1. Inspect `contentops job-executions --json`.
2. Open the failed `contentops job-execution <execution_id>` receipt.
3. Generate `contentops job-recovery-plan <execution_id> --output recovery.yaml`.
4. Run `contentops incident-reports --json` and `contentops incident-report <run_id>`.
5. Check whether failures are research, generation, evaluation, publish, notification, or storage related.
6. Run `contentops doctor --json`.
7. Export the affected run with `contentops export-run <run_id> --output incident.zip`.
8. Run `contentops verify-publish <run_id>` for published runs to detect target drift.
9. Run `contentops release-readiness --json` to confirm whether the issue blocks release.
10. Fix provider credentials, source URLs, publish target state, webhook state, or approval status.
11. Rerun from the recovery plan or the prior request:

```powershell
contentops-worker run-pipeline recovery.yaml
contentops rerun <run_id>
```

## 10. Production Environment Notes

Recommended AWS-backed setup:

- API and worker on ECS Fargate or Lambda.
- RDS Postgres for run metadata.
- S3 artifact mirroring for run artifacts, worker receipts, and evidence bundles, with
  `s3-mirror-log.json` receipts retained locally for object-level audit trails.
- EventBridge Scheduler for daily AI research jobs.
- Secrets Manager for OpenAI, search provider, database, and operator API keys.
- Optional webhook endpoint for review and publishing notifications.
- CloudWatch alarms for failed worker tasks and API `5xx` responses.
- `CONTENTOPS_LATENCY_SLO_MS` and `CONTENTOPS_MIN_SOURCE_COUNT` tuned for the content workflow.
- `CONTENTOPS_TOKEN_BUDGET_PER_RUN` tuned to the expected article length and model provider.

Mutating API and dashboard operations should use `CONTENTOPS_OPERATOR_API_KEY` in shared
deployments.
Use `CONTENTOPS_REQUIRE_READ_API_KEY=true` when generated artifacts, source audits, job execution
receipts, content inventory, or evidence bundles are not safe for public read access. Prefer a
dedicated `CONTENTOPS_READ_API_KEY` for dashboards and integrations that should never mutate runs;
the operator key can still read but remains the only key accepted for writes.
Capture `X-ContentOps-Request-Id` from failed API or dashboard requests and include it in incident
notes so application responses, logs, and exported evidence bundles can be correlated.
