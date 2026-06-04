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

After the worker runs:

```powershell
contentops worker-jobs --json
contentops job-executions --json
contentops job-execution <execution_id>
contentops job-execution-summary <execution_id>
contentops job-execution-trends --days 14
contentops job-recovery-plan <execution_id> --output recovery.yaml
```

Review the worker catalog before execution, then inspect the execution receipt for per-job failures,
run ids, artifact directories, publish URLs, duration, and the post-run release evidence path.
Use `contentops job-execution-summary <execution_id>` or
`GET /job-executions/{execution_id}/summary` to scan generated runs, published runs, handoff
readiness, release evidence readiness, and whether operator action is required.
Use `contentops job-execution-trends --days 14`, `GET /job-executions/trends?days=14`, or
`/dashboard/job-execution-trends` to check recurring automation success, publish, handoff, and
action-required rates before changing the EventBridge schedule. The trend view also lists the
latest successful execution, latest action-required execution, and top failure reasons so operators
can separate provider failures, homepage handoff failures, and release evidence failures quickly.
The same trend payload is written to release evidence as `worker_execution_trends.json`, so compare
the dashboard with the latest CI evidence bundle when investigating scheduled automation regressions.
In AWS, mirror `artifacts/job-executions` to S3 with the rest of the artifact tree.
For non-dry-run worker executions, open the receipt's `release_evidence_path` to review the same
deployment preflight, release readiness, homepage handoff inventory, and evidence manifest produced
for CI/CD release reviews.
If a scheduled job declares `homepage_handoff: true`, inspect `homepage_handoff_path` on that job
result before committing the personal homepage repository. A populated `homepage_handoff_error`
usually means the homepage publisher is not configured or the target path is not a git repository.
After reviewing a successful scheduled execution, use the dashboard job execution detail page or
`POST /job-executions/{execution_id}/approve-runs` to approve every generated run from that
execution as one operator action.
Then use the same dashboard detail page or `POST /job-executions/{execution_id}/publish-runs` to
publish approved runs from the execution. The response is per-run, so keep any failed item in the
review queue and inspect its run detail before retrying or forcing publication.
For S3-backed runs, inspect each run's `s3-mirror-log.json` to confirm the bucket/key path and
whether any artifact mirror attempt failed before the worker completed.
Worker receipt directories and release evidence directories also write `s3-mirror-log.json` when
`CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3`, so scheduled execution receipts and deployment evidence
can be traced to exact S3 keys.
Use `contentops s3-mirror-log <run_id>`, `GET /runs/{id}/s3-mirror-log`, or the dashboard run
detail page to inspect run-level mirror records without opening the artifact directory manually.
When failures occur, inspect the recovery plan before rerunning it with
`contentops-worker run-pipeline recovery.yaml`.

## 3. CloudWatch Operations

For AWS deployments, inspect the Terraform-created CloudWatch dashboard before and after scheduled
worker windows:

- API and worker log-derived error metrics should remain at zero.
- RDS metadata database connections should stay below the configured threshold.
- ECS CPU and memory should leave enough headroom for retries and source enrichment.
- Recent API and worker failure log tables should be empty or explainable.

If `alarm_actions` is configured, API error, worker failure, and RDS connection alarms page the
configured SNS or incident-management targets. When an alarm fires, first inspect
`/dashboard/system-status`, `/dashboard/release-evidence`, `/ops-summary`, `/job-executions`, and
the relevant CloudWatch log table before rerunning or rolling back content. Use `/release-evidence`
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
contentops ops-summary --json
contentops ops-trends --days 14 --json
contentops release-readiness --json
```

The same catalog is available from:

```text
GET /content?limit=20&offset=0
GET /job-executions/{execution_id}/recovery-plan
GET /scorecards?limit=20&offset=0
GET /cost-reports?limit=20&offset=0
GET /audit-events?limit=20&offset=0
GET /retention-report?days=90&limit=100
GET /incident-reports?limit=20&offset=0
GET /ops-summary?window_size=100
GET /ops-trends?days=14&window_size=500
GET /deployment-manifest
GET /release-readiness?window_size=100
```

Use it to review shipped URLs, providers, publish timestamps, evaluation scores, pass rates,
latency SLOs, and source-count SLOs.
Use operations trends when you need a daily view of publishing throughput, failed runs, quality
rate, budget posture, and action-required incidents.
Use the retention report to estimate artifact storage usage and identify runs old enough for
manual archive or cleanup review.
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
