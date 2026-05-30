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
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --dry-run --json
```

Expected result:

- `doctor` is `ok` or `degraded` with only intentional local-development warnings.
- `ops-summary` shows no unexpected failed runs or action-required incidents.
- `deployment-manifest` contains no secret values and shows expected runtime providers.
- `release-readiness` is `pass` or expected `warn`; it must not be `fail`.
- Worker dry run writes a receipt under `CONTENTOPS_ARTIFACT_ROOT/job-executions`.
- Research and OpenAI retry settings are present when network-backed providers are enabled.

## 2. Daily AI Research Job

Use the worker for recurring content discovery:

```powershell
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --receipt-dir artifacts/job-executions
```

After the worker runs:

```powershell
contentops job-executions --json
contentops job-execution <execution_id>
contentops job-recovery-plan <execution_id> --output recovery.yaml
```

Review the execution receipt for per-job failures, run ids, artifact directories, publish URLs, and
duration. In AWS, mirror `artifacts/job-executions` to S3 with the rest of the artifact tree.
When failures occur, inspect the recovery plan before rerunning it with
`contentops-worker run-pipeline recovery.yaml`.

## 3. Review Queue

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

## 4. Publish

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

## 5. Published Content Inventory

Track shipped content as an operational catalog:

```powershell
contentops content --json
contentops scorecards --json
contentops cost-reports --json
contentops audit-events --json
contentops retention-report --days 90 --json
contentops ops-summary --json
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
GET /deployment-manifest
GET /release-readiness?window_size=100
```

Use it to review shipped URLs, providers, publish timestamps, evaluation scores, pass rates,
latency SLOs, and source-count SLOs.
Use the retention report to estimate artifact storage usage and identify runs old enough for
manual archive or cleanup review.
Cost reports prefer provider usage tokens from `generation-receipt.json`. When usage is missing,
they fall back to artifact-based estimates; use those estimates as a budget guardrail and
correlate with provider billing dashboards for financial reporting.

## 6. Evidence Export

Export a run for portfolio review, incident handoff, or offline audit:

```powershell
contentops export-run <run_id> --output run-evidence.zip
```

The zip contains `bundle-manifest.json` and every run artifact, including request, research,
source audit, draft, evaluation, trace, approval, audit log, and publish receipt when present.

## 7. Rollback

If a publish needs to be undone:

```powershell
contentops rollback-publish <run_id> --actor "Zack"
contentops audit-log <run_id>
contentops audit-events --action rollback_publish --json
```

Rollback restores backed-up files or deletes newly created files according to the publish receipt.
It then writes `publish-rollback.json`, appends a `rollback_publish` audit event, clears the
published URL, and returns the run to an approved or reviewable state.

## 8. Incident Checks

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

## 9. Production Environment Notes

Recommended AWS-backed setup:

- API and worker on ECS Fargate or Lambda.
- RDS Postgres for run metadata.
- S3 artifact mirroring for run artifacts, worker receipts, and evidence bundles.
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
