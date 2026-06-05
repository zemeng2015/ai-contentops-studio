from __future__ import annotations

import json
from collections.abc import Sequence
from html import escape
from urllib.parse import urlencode

from contentops_core.jobs import (
    JobExecutionAlertDelivery,
    JobExecutionAlertReport,
    JobExecutionReport,
    JobExecutionTrendReport,
    JobRecoveryLineageItem,
    JobRecoveryLineageReport,
    JobRecoveryPlan,
    ScheduledWorkflowReviewPackageItem,
    WorkerDeliverySummaryDelivery,
    WorkerJobCatalogItem,
    WorkerJobReadinessResponse,
    job_execution_summary,
)
from contentops_core.models import (
    ApprovalRecord,
    ArtifactMirrorRecord,
    AuditEvent,
    AuditEventListResponse,
    ConfigAuditReport,
    CostReportListResponse,
    DeploymentManifest,
    GenerationReceipt,
    IncidentReportListResponse,
    IntegrationSmokeRunListResponse,
    NotificationDelivery,
    OperationsSummary,
    OpsBriefDelivery,
    OpsBriefReport,
    OpsTrendReport,
    PublishedContentListResponse,
    PublishPlan,
    PublishReceipt,
    PublishVerificationReport,
    ReleaseApprovalListResponse,
    ReleaseEvidenceBundle,
    ReleaseGateListResponse,
    ReleaseGateReport,
    RetentionArchiveEvidence,
    RetentionArchiveListResponse,
    RetentionReport,
    RunComparison,
    RunCostReport,
    RunIncidentReport,
    RunMetrics,
    RunScorecard,
    ScorecardListResponse,
    SourceAuditReport,
    SourceReviewRecord,
    SystemStatus,
)


def _page(title: str, body: str) -> str:
    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{escape(title)}</title>
        <style>
          body {{
            margin: 0;
            background: #f7f8f6;
            color: #18201e;
            font-family: Inter, system-ui, sans-serif;
            line-height: 1.5;
          }}
          main {{ max-width: 1160px; margin: 0 auto; padding: 36px 24px 64px; }}
          a {{ color: #12594b; font-weight: 800; text-decoration: none; }}
          h1 {{ font-size: 42px; margin: 0 0 24px; }}
          h2 {{ margin-top: 0; }}
          .hero, table, .grid > div {{
            border: 1px solid #d8ddd7;
            border-radius: 8px;
            background: #fff;
            box-shadow: 0 18px 48px rgba(24, 32, 30, 0.08);
          }}
          .hero {{ padding: 24px; margin-bottom: 18px; }}
          .compact {{ padding: 16px; }}
          form {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }}
          .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 10px;
            margin: 18px 0;
          }}
          .metrics div {{
            padding: 14px;
            border: 1px solid #d8ddd7;
            border-radius: 8px;
            background: #f7f8f6;
          }}
          .metrics strong {{ display: block; font-size: 22px; }}
          .metrics span {{ color: #5f6965; font-size: 13px; font-weight: 800; }}
          input, select, textarea {{
            min-width: min(520px, 100%);
            padding: 12px;
            border: 1px solid #d8ddd7;
            border-radius: 6px;
            background: #fff;
          }}
          select {{ min-width: 180px; }}
          textarea {{
            min-height: 92px;
            resize: vertical;
          }}
          button {{
            padding: 12px 16px;
            border: 0;
            border-radius: 6px;
            background: #1f7a68;
            color: #fff;
            font-weight: 900;
            cursor: pointer;
          }}
          table {{ width: 100%; border-collapse: collapse; overflow: hidden; }}
          th, td {{ padding: 14px; border-bottom: 1px solid #edf0ec; text-align: left; }}
          th {{ color: #5f6965; font-size: 13px; text-transform: uppercase; }}
          .pager {{
            display: flex;
            justify-content: flex-end;
            align-items: center;
            gap: 12px;
            margin-top: 14px;
            color: #5f6965;
            font-weight: 800;
          }}
          .pager-link {{
            border: 1px solid #d8ddd7;
            border-radius: 6px;
            padding: 8px 12px;
            background: #fff;
          }}
          .bulk-actions {{
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            align-items: center;
            margin: 14px 0;
          }}
          .grid {{ display: grid; grid-template-columns: 0.4fr 0.6fr; gap: 18px; }}
          .grid > div {{ padding: 22px; min-width: 0; }}
          .grid table {{ border-radius: 0; box-shadow: none; }}
          pre {{ overflow: auto; padding: 16px; background: #101816; color: #e6f0ec; }}
          .pill {{
            display: inline-block;
            border-radius: 999px;
            padding: 3px 8px;
            margin: 2px 4px 2px 0;
            background: #e8f2ef;
            color: #12594b;
            font-size: 12px;
            font-weight: 900;
          }}
          .pill.review {{ background: #fff4de; color: #8a4c00; }}
          .pill.publish {{ background: #e8f2ef; color: #12594b; }}
          .muted {{ color: #5f6965; }}
          .url-list {{ margin: 0; padding-left: 18px; }}
          .url-list li {{ margin: 2px 0; }}
          @media (max-width: 800px) {{
            .grid, .metrics {{ grid-template-columns: 1fr; }}
          }}
        </style>
      </head>
      <body>
        <main>
          <h1>{escape(title)}</h1>
          {body}
        </main>
      </body>
    </html>
    """


def _api_key_query(api_key: str) -> str:
    if not api_key:
        return ""
    return f"?api_key={escape(api_key, quote=True)}"


def _api_key_hidden(api_key: str) -> str:
    if not api_key:
        return ""
    return f'<input type="hidden" name="api_key" value="{escape(api_key, quote=True)}">'


def _status_options(selected: str) -> str:
    statuses = ["", "created", "researching", "planning", "drafting", "evaluating"]
    statuses += ["needs_review", "approved", "rejected", "publishing", "published", "failed"]
    rows: list[str] = []
    normalized = selected.strip().casefold()
    for status in statuses:
        label = "all statuses" if not status else status
        selected_attr = " selected" if status == normalized else ""
        rows.append(
            f'<option value="{escape(status)}"{selected_attr}>{escape(label)}</option>'
        )
    return "\n".join(rows)


def _pagination_html(
    q: str,
    status: str,
    limit: int,
    offset: int,
    total: int,
    api_key: str,
) -> str:
    if total <= limit and offset == 0:
        return ""
    previous_offset = max(offset - limit, 0)
    next_offset = offset + limit
    previous = ""
    next_link = ""
    if offset > 0:
        previous_url = _dashboard_url(q, status, limit, previous_offset, api_key)
        previous = f'<a class="pager-link" href="{previous_url}">Previous</a>'
    if next_offset < total:
        next_url = _dashboard_url(q, status, limit, next_offset, api_key)
        next_link = f'<a class="pager-link" href="{next_url}">Next</a>'
    showing_start = 0 if total == 0 else offset + 1
    showing_end = min(offset + limit, total)
    return f"""
      <nav class="pager">
        <span>Showing {showing_start}-{showing_end} of {total}</span>
        {previous}
        {next_link}
      </nav>
    """


def _dashboard_url(q: str, status: str, limit: int, offset: int, api_key: str) -> str:
    params = {"q": q, "status": status, "limit": str(limit), "offset": str(offset)}
    if api_key:
        params["api_key"] = api_key
    return f"/dashboard?{urlencode(params)}"


def _comparison_html(comparison: RunComparison) -> str:
    deltas = "".join(
        f"""
        <tr>
          <td>{escape(score)}</td>
          <td>{delta:+.3f}</td>
        </tr>
        """
        for score, delta in comparison.evaluation_deltas.items()
        if delta is not None
    )
    summary = "".join(f"<li>{escape(item)}</li>" for item in comparison.summary)
    base_only = ", ".join(comparison.source_overlap.base_only) or "none"
    candidate_only = ", ".join(comparison.source_overlap.candidate_only) or "none"
    return f"""
      <h2>{escape(comparison.base_run_id)} vs {escape(comparison.candidate_run_id)}</h2>
      <p>{escape(comparison.base_topic)} -> {escape(comparison.candidate_topic)}</p>
      <div class="metrics">
        <div><strong>{str(comparison.same_topic).lower()}</strong><span>Same topic</span></div>
        <div><strong>{comparison.source_count_delta:+d}</strong><span>Source delta</span></div>
        <div>
          <strong>{comparison.source_overlap.shared_count}</strong>
          <span>Shared sources</span>
        </div>
        <div>
          <strong>{_duration_label(comparison.duration_delta_ms)}</strong>
          <span>Duration delta</span>
        </div>
      </div>
      <ul>{summary}</ul>
      <table>
        <thead><tr><th>Evaluation score</th><th>Candidate delta</th></tr></thead>
        <tbody>{deltas}</tbody>
      </table>
      <p><strong>Base-only sources:</strong> {escape(base_only)}</p>
      <p><strong>Candidate-only sources:</strong> {escape(candidate_only)}</p>
    """


def _approval_html(approval: ApprovalRecord | None) -> str:
    if approval is None:
        return "<p>No approval decision recorded.</p>"
    return f"""
      <p>
        Decision: <strong>{escape(approval.decision.value)}</strong> |
        Reviewer: <strong>{escape(approval.reviewer)}</strong> |
        At: {escape(approval.decided_at.isoformat())}
      </p>
      <p>{escape(approval.notes or "No notes.")}</p>
    """


def _publish_receipt_html(receipt: PublishReceipt | None) -> str:
    if receipt is None:
        return "<p>No publish receipt recorded.</p>"
    item_rows = "".join(
        f"""
        <tr>
          <td>{escape(item.action)}</td>
          <td>{escape(item.path)}</td>
          <td>{escape(item.description)}</td>
        </tr>
        """
        for item in receipt.plan_items
    )
    change_rows = "".join(
        f"""
        <tr>
          <td>{escape(change.action)}</td>
          <td>{escape(change.path)}</td>
          <td><code>{escape((change.before_sha256 or "none")[:12])}</code></td>
          <td><code>{escape((change.after_sha256 or "none")[:12])}</code></td>
          <td>{escape(change.backup_artifact or "n/a")}</td>
          <td>{escape(change.rollback_hint)}</td>
        </tr>
        """
        for change in receipt.file_changes
    )
    reviewer = receipt.approval.reviewer if receipt.approval is not None else "force"
    metadata_html = ""
    if receipt.plan_metadata:
        metadata_html = (
            "<h4>Publish Metadata</h4>"
            f"<pre>{escape(json.dumps(receipt.plan_metadata, ensure_ascii=False, indent=2))}</pre>"
        )
    return f"""
      <p>
        Provider: <strong>{escape(receipt.provider)}</strong> |
        Reviewer: <strong>{escape(reviewer)}</strong> |
        Force: <strong>{str(receipt.force).lower()}</strong>
      </p>
      <p>URL: <a href="{escape(receipt.url)}">{escape(receipt.url)}</a></p>
      <p>Published at: {escape(receipt.published_at.isoformat())}</p>
      <table>
        <thead><tr><th>Action</th><th>Path</th><th>Description</th></tr></thead>
        <tbody>{item_rows}</tbody>
      </table>
      {metadata_html}
      <h4>File Changes</h4>
      <table>
        <thead>
          <tr>
            <th>Change</th><th>Path</th><th>Before</th><th>After</th><th>Backup</th><th>Rollback</th>
          </tr>
        </thead>
        <tbody>{change_rows}</tbody>
      </table>
    """


def _publish_verification_html(report: PublishVerificationReport) -> str:
    rows = "".join(
        f"""
        <tr>
          <td>{escape(item.path)}</td>
          <td>{_pass_label(item.exists)}</td>
          <td>{_pass_label(item.matches_receipt)}</td>
          <td><code>{escape((item.expected_sha256 or "none")[:12])}</code></td>
          <td><code>{escape((item.actual_sha256 or "none")[:12])}</code></td>
          <td>{escape(item.message)}</td>
        </tr>
        """
        for item in report.items
    )
    return f"""
      <p>
        <a href="/runs/{escape(report.run_id)}/publish-verification">
          Publish verification JSON
        </a> |
        <a href="/runs/{escape(report.run_id)}/publish-recovery-plan">
          Publish recovery plan JSON
        </a>
      </p>
      <p>
        Execute recovery through <code>POST /runs/{escape(report.run_id)}/publish-recovery</code>
        with action <code>rollback</code>.
      </p>
      <p>
        Provider: <strong>{escape(report.provider)}</strong> |
        Verified: <strong>{_pass_label(report.verified)}</strong> |
        URL: <a href="{escape(report.url)}">{escape(report.url)}</a>
      </p>
      <table>
        <thead>
          <tr>
            <th>Path</th><th>Exists</th><th>Hash match</th>
            <th>Expected</th><th>Actual</th><th>Message</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _job_executions_html(reports: list[JobExecutionReport]) -> str:
    if not reports:
        return "<p>No worker executions recorded.</p>"
    rows = "".join(
        f"""
        <tr>
          <td>
            <a href="/dashboard/job-executions/{escape(report.execution_id)}">
              {escape(report.execution_id)}
            </a>
          </td>
          <td>{escape(report.name)}</td>
          <td>{str(report.dry_run).lower()}</td>
          <td>{report.succeeded}/{report.total}</td>
          <td>{report.failed}</td>
          <td>{_duration_label(report.duration_ms)}</td>
          <td>{escape(report.started_at.isoformat())}</td>
        </tr>
        """
        for report in reports
    )
    return f"""
      <p><a href="/job-executions">Job execution JSON</a></p>
      <table>
        <thead>
          <tr>
            <th>Execution</th><th>Name</th><th>Dry run</th><th>Succeeded</th>
            <th>Failed</th><th>Duration</th><th>Started</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p>Failed executions expose <code>/job-executions/&lt;id&gt;/recovery-plan</code>.</p>
    """


def _scheduled_review_packages_html(
    items: list[ScheduledWorkflowReviewPackageItem],
    api_key: str = "",
) -> str:
    if not items:
        return "<p>No scheduled review packages recorded.</p>"
    rows = "".join(
        f"""
        <tr>
          <td><code>{escape(item.id)}</code></td>
          <td>{escape(item.status)}</td>
          <td>{escape(item.verification_status)}</td>
          <td>{item.verification_failed_count}</td>
          <td>{item.artifact_count}</td>
          <td>{str(item.action_required).lower()}</td>
          <td>{escape(str(item.archive_size_bytes))}</td>
          <td>{_scheduled_review_s3_mirror_cell(item)}</td>
          <td>{_scheduled_review_archive_link(item)}</td>
          <td>{_scheduled_review_archive_action(item, api_key)}</td>
          <td>{escape(item.updated_at.isoformat() if item.updated_at else "n/a")}</td>
        </tr>
        """
        for item in items
    )
    return f"""
      <p><a href="/scheduled-reviews">Scheduled review package JSON</a></p>
      <table>
        <thead>
          <tr>
            <th>Package</th><th>Status</th><th>Verification</th><th>Failed</th>
            <th>Artifacts</th><th>Action required</th><th>Zip bytes</th><th>S3 mirror</th>
            <th>Archive</th><th>Action</th><th>Updated</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _scheduled_review_archive_link(item: ScheduledWorkflowReviewPackageItem) -> str:
    if not item.archive_exists:
        return "not available"
    return (
        f'<a href="/scheduled-reviews/{escape(item.id)}/archive">'
        f"{escape(item.archive_path or 'download zip')}</a>"
    )


def _scheduled_review_s3_mirror_cell(item: ScheduledWorkflowReviewPackageItem) -> str:
    if not item.s3_mirror_log_path:
        return escape(item.s3_mirror_status)
    return (
        f"{escape(item.s3_mirror_status)} "
        f'<a href="/scheduled-reviews/{escape(item.id)}/s3-mirror-log">log</a>'
    )


def _scheduled_review_archive_action(
    item: ScheduledWorkflowReviewPackageItem,
    api_key: str,
) -> str:
    label = "Retry S3 mirror" if item.s3_mirror_status == "failed" else "Rebuild archive"
    if not item.archive_exists:
        label = "Create archive"
    action = (
        f"/dashboard/scheduled-reviews/{escape(item.id)}/archive"
        f"{_api_key_query(api_key)}"
    )
    return f"""
      <form method="post" action="{action}">
        {_api_key_hidden(api_key)}
        <button type="submit">{label}</button>
      </form>
    """


def _job_execution_detail_html(
    report: JobExecutionReport,
    recovery_plan: JobRecoveryPlan | None = None,
    recovery_lineage_item: JobRecoveryLineageItem | None = None,
    api_key: str = "",
) -> str:
    release_evidence = report.release_evidence_path or "not recorded"
    release_evidence_status = report.release_evidence_status or "n/a"
    release_evidence_error = report.release_evidence_error or "none"
    delivery_notify_action = (
        f"/dashboard/job-executions/{escape(report.execution_id)}/delivery-summary/notify"
        f"{_api_key_query(api_key)}"
    )
    content_assets = report.content_assets_path or "not recorded"
    content_assets_status = report.content_assets_status or "n/a"
    content_assets_error = report.content_assets_error or "none"
    delivery_summary_status = "ready" if report.delivery_summary_path else "n/a"
    delivery_summary = report.delivery_summary_path or "not recorded"
    delivery_summary_markdown = report.delivery_summary_markdown_path or "not recorded"
    delivery_summary_error = report.delivery_summary_error or "none"
    summary = job_execution_summary(report)
    rows = "".join(
        f"""
        <tr>
          <td>{escape(result.job_name)}</td>
          <td>{_job_intent_label(result.publish)}</td>
          <td>{escape(str(result.status))}</td>
          <td>{_run_link(result.run_id)}</td>
          <td>{escape(result.homepage_handoff_path or "n/a")}</td>
          <td>{escape(result.topic)}</td>
          <td>{_source_urls_html(result.source_urls)}</td>
          <td>{escape(", ".join(result.tags) or "none")}</td>
          <td>{escape(_metadata_label(result.metadata))}</td>
          <td>{escape(result.error or result.homepage_handoff_error or "")}</td>
        </tr>
        """
        for result in report.results
    )
    return f"""
      <h2>{escape(report.name)}</h2>
      <p>
        <a href="/job-executions/{escape(report.execution_id)}">Execution JSON</a> |
        <a href="/job-executions/{escape(report.execution_id)}/recovery-plan">Recovery plan JSON</a>
      </p>
      <form method="post" action="{delivery_notify_action}">
        {_api_key_hidden(api_key)}
        <button type="submit">Notify delivery summary</button>
      </form>
      <div class="metrics">
        <div><strong>{report.total}</strong><span>Total jobs</span></div>
        <div><strong>{report.succeeded}</strong><span>Succeeded</span></div>
        <div><strong>{report.failed}</strong><span>Failed</span></div>
        <div><strong>{summary.generated_runs}</strong><span>Generated runs</span></div>
        <div><strong>{summary.published_runs}</strong><span>Published runs</span></div>
        <div><strong>{summary.homepage_handoff_ready}</strong><span>Handoffs ready</span></div>
        <div><strong>{summary.homepage_handoff_failed}</strong><span>Handoffs failed</span></div>
        <div><strong>{str(report.dry_run).lower()}</strong><span>Dry run</span></div>
        <div><strong>{_duration_label(report.duration_ms)}</strong><span>Duration</span></div>
        <div><strong>{escape(report.started_at.isoformat())}</strong><span>Started</span></div>
        <div><strong>{escape(release_evidence_status)}</strong><span>Evidence status</span></div>
        <div><strong>{len(report.release_evidence_files)}</strong><span>Evidence files</span></div>
        <div><strong>{escape(content_assets_status)}</strong><span>Content assets</span></div>
        <div><strong>{len(report.content_assets_files)}</strong><span>Asset files</span></div>
        <div><strong>{escape(delivery_summary_status)}</strong><span>Delivery summary</span></div>
        <div>
          <strong>{str(summary.action_required).lower()}</strong>
          <span>Action required</span>
        </div>
      </div>
      <p>
        Content assets: <code>{escape(content_assets)}</code><br>
        Content asset files: {escape(", ".join(report.content_assets_files) or "none")}<br>
        Content asset error: {escape(content_assets_error)}<br>
        Delivery summary JSON: <code>{escape(delivery_summary)}</code><br>
        Delivery summary Markdown: <code>{escape(delivery_summary_markdown)}</code><br>
        Delivery summary error: {escape(delivery_summary_error)}<br>
        Release evidence: <code>{escape(release_evidence)}</code><br>
        Evidence error: {escape(release_evidence_error)}
      </p>
      <table>
        <thead>
          <tr>
            <th>Job</th><th>Intent</th><th>Status</th><th>Run</th><th>Handoff</th><th>Topic</th>
            <th>Sources</th><th>Tags</th><th>Metadata</th><th>Error</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      {_job_recovery_lineage_item_html(recovery_lineage_item)}
      {_job_recovery_preview_html(recovery_plan)}
    """


def _job_recovery_lineage_item_html(item: JobRecoveryLineageItem | None) -> str:
    if item is None:
        return ""
    attempt_rows = "".join(
        f"""
        <tr>
          <td><a href="/dashboard/job-executions/{escape(attempt.execution_id)}">
            {escape(attempt.execution_id)}
          </a></td>
          <td>{escape(attempt.status)}</td>
          <td>{attempt.succeeded}/{attempt.total}</td>
          <td>{escape(attempt.actor or "n/a")}</td>
          <td>{escape(attempt.completed_at.isoformat())}</td>
          <td>{escape("; ".join(attempt.errors) or "none")}</td>
        </tr>
        """
        for attempt in item.attempts
    )
    if not attempt_rows:
        attempt_rows = """
        <tr>
          <td colspan="6">
            <span class="muted">No recovery execution has been recorded yet.</span>
          </td>
        </tr>
        """
    return f"""
      <h3>Recovery Lineage</h3>
      <div class="metrics">
        <div><strong>{escape(item.latest_recovery_status)}</strong><span>Status</span></div>
        <div><strong>{item.recovery_attempt_count}</strong><span>Attempts</span></div>
        <div><strong>{item.recovered_job_count}</strong><span>Recovered jobs</span></div>
        <div><strong>{item.unresolved_job_count}</strong><span>Unresolved jobs</span></div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Recovery execution</th><th>Status</th><th>Jobs</th>
            <th>Actor</th><th>Completed</th><th>Errors</th>
          </tr>
        </thead>
        <tbody>{attempt_rows}</tbody>
      </table>
      <h4>Recommended Actions</h4>
      {_remediation_list_html(item.recommended_actions)}
    """


def _job_recovery_preview_html(plan: JobRecoveryPlan | None) -> str:
    if plan is None:
        return ""
    rows = "".join(
        f"""
        <tr>
          <td>{escape(job.name)}</td>
          <td>{_job_intent_label(job.publish)}</td>
          <td>{escape(job.topic)}</td>
          <td>{escape(", ".join(job.tags) or "none")}</td>
          <td>{escape(_metadata_label(job.metadata))}</td>
        </tr>
        """
        for job in plan.jobs
    )
    if not rows:
        rows = """
        <tr>
          <td colspan="5"><span class="muted">No failed jobs are eligible for recovery.</span></td>
        </tr>
        """
    blocked = plan.blocked_reason or "none"
    return f"""
      <h3>Recovery Preview</h3>
      <p>
        Runnable: <strong>{str(plan.runnable).lower()}</strong> |
        Failed jobs: <strong>{plan.failed_count}</strong> |
        Source dry run: <strong>{str(plan.source_dry_run).lower()}</strong> |
        Blocked: <strong>{escape(blocked)}</strong>
      </p>
      <table>
        <thead>
          <tr><th>Job</th><th>Intent</th><th>Topic</th><th>Tags</th><th>Metadata</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _s3_mirror_log_html(records: list[ArtifactMirrorRecord], json_href: str | None = None) -> str:
    if not records:
        return "<p>No S3 mirror records found.</p>"
    mirrored = sum(1 for record in records if record.status == "mirrored")
    failed = len(records) - mirrored
    json_link = f'<p><a href="{escape(json_href)}">S3 mirror log JSON</a></p>' if json_href else ""
    rows = "".join(
        f"""
        <tr>
          <td>{escape(record.artifact_name)}</td>
          <td>{escape(record.status)}</td>
          <td>{escape(record.bucket)}</td>
          <td><code>{escape(record.key)}</code></td>
          <td>{escape(record.content_type)}</td>
          <td>{escape(record.error or "")}</td>
          <td>{escape(record.mirrored_at.isoformat())}</td>
        </tr>
        """
        for record in records
    )
    return f"""
      {json_link}
      <div class="metrics">
        <div><strong>{len(records)}</strong><span>Mirror attempts</span></div>
        <div><strong>{mirrored}</strong><span>Mirrored</span></div>
        <div><strong>{failed}</strong><span>Failed</span></div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Artifact</th><th>Status</th><th>Bucket</th><th>Key</th>
            <th>Type</th><th>Error</th><th>At</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _workflow_context_html(request_json: str) -> str:
    data = json.loads(request_json)
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict) or not metadata:
        return "<p>No workflow metadata recorded for this run.</p>"
    normalized = {
        str(key): str(value)
        for key, value in metadata.items()
        if isinstance(key, str)
    }
    rows = "".join(
        f"""
        <tr>
          <td>{escape(key)}</td>
          <td>{escape(value)}</td>
        </tr>
        """
        for key, value in sorted(normalized.items())
    )
    return f"""
      <div class="metrics">
        <div>
          <strong>{escape(normalized.get("contentops_workflow_name", "manual"))}</strong>
          <span>Workflow</span>
        </div>
        <div>
          <strong>{escape(normalized.get("contentops_job_name", "manual"))}</strong>
          <span>Job</span>
        </div>
        <div>
          <strong>{escape(normalized.get("contentops_publish_intent", "review"))}</strong>
          <span>Intent</span>
        </div>
        <div>
          <strong>{escape(normalized.get("research_provider", "default"))}</strong>
          <span>Research provider</span>
        </div>
      </div>
      <table>
        <thead><tr><th>Metadata</th><th>Value</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _worker_jobs_html(items: list[WorkerJobCatalogItem]) -> str:
    if not items:
        return "<p>No worker job files found.</p>"
    publish_count = sum(item.publish_count for item in items)
    review_count = sum(item.review_count for item in items)
    handoff_count = sum(item.handoff_count for item in items)
    invalid_count = sum(1 for item in items if not item.valid)
    ready_count = sum(1 for item in items if item.readiness_status == "ready")
    job_count = sum(item.total for item in items)
    file_rows = "".join(
        f"""
        <tr>
          <td>{escape(item.path)}</td>
          <td>{escape(item.name)}</td>
          <td>{str(item.valid).lower()}</td>
          <td>{_readiness_label(item.readiness_status)}</td>
          <td>{escape(_schedule_label(item))}</td>
          <td>{escape(_run_policy_label(item))}</td>
          <td>{item.total}</td>
          <td>{item.publish_count}</td>
          <td>{item.review_count}</td>
          <td>{item.handoff_count}</td>
          <td>{escape(", ".join(item.tags) or "none")}</td>
          <td>{escape("; ".join(item.topics[:3]) or "; ".join(item.errors) or "n/a")}</td>
        </tr>
        """
        for item in items
    )
    job_rows = "".join(_worker_job_rows(item) for item in items)
    return f"""
      <p><a href="/worker-jobs">Worker job catalog JSON</a></p>
      <div class="metrics">
        <div><strong>{len(items)}</strong><span>Job files</span></div>
        <div><strong>{job_count}</strong><span>Planned jobs</span></div>
        <div><strong>{review_count}</strong><span>Review first</span></div>
        <div><strong>{publish_count}</strong><span>Auto publish</span></div>
        <div><strong>{handoff_count}</strong><span>Homepage handoffs</span></div>
        <div><strong>{invalid_count}</strong><span>Invalid files</span></div>
        <div><strong>{ready_count}</strong><span>Ready files</span></div>
      </div>
      <h3>Planned Jobs</h3>
      <table>
        <thead>
          <tr>
            <th>File</th><th>Job</th><th>Intent</th><th>Handoff</th><th>Topic</th>
            <th>Sources</th><th>Tags</th><th>Metadata</th>
          </tr>
        </thead>
        <tbody>{job_rows}</tbody>
      </table>
      <h3>Job Files</h3>
      <table>
        <thead>
          <tr>
            <th>File</th><th>Name</th><th>Valid</th><th>Readiness</th>
            <th>Schedule</th><th>Run policy</th><th>Jobs</th>
            <th>Publish</th><th>Review</th><th>Handoffs</th><th>Tags</th><th>Topics</th>
          </tr>
        </thead>
        <tbody>{file_rows}</tbody>
      </table>
    """


def _worker_job_readiness_html(report: WorkerJobReadinessResponse) -> str:
    if not report.items:
        return """
          <h3>Automation Readiness</h3>
          <p>No worker job files are configured for readiness checks.</p>
        """
    rows = "".join(
        f"""
        <tr>
          <td>{escape(item.path)}</td>
          <td>{escape(item.name)}</td>
          <td>{_readiness_label(item.status)}</td>
          <td>{_readiness_checks_html(item.checks)}</td>
        </tr>
        """
        for item in report.items
    )
    return f"""
      <h3>Automation Readiness</h3>
      <p><a href="/worker-jobs/readiness">Worker job readiness JSON</a></p>
      <div class="metrics">
        <div><strong>{report.ready_count}</strong><span>Ready</span></div>
        <div><strong>{report.warning_count}</strong><span>Warning</span></div>
        <div><strong>{report.failed_count}</strong><span>Failed</span></div>
        <div><strong>{str(report.can_schedule).lower()}</strong><span>Can schedule</span></div>
      </div>
      <table>
        <thead><tr><th>File</th><th>Name</th><th>Status</th><th>Checks</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _worker_job_rows(item: WorkerJobCatalogItem) -> str:
    if not item.valid:
        errors = "; ".join(item.errors) or "Invalid job file."
        return f"""
          <tr>
            <td>{escape(item.path)}</td>
            <td>{escape(item.name)}</td>
            <td><span class="pill review">invalid</span></td>
            <td>{escape(errors)}</td>
            <td>n/a</td>
            <td>n/a</td>
            <td>n/a</td>
            <td>n/a</td>
          </tr>
        """
    return "".join(
        f"""
        <tr>
          <td>{escape(item.path)}</td>
          <td>{escape(job.name)}</td>
          <td>{_job_intent_label(job.publish)}</td>
          <td>{_handoff_label(job.homepage_handoff)}</td>
          <td>{escape(job.topic)}</td>
          <td>{_source_urls_html(job.source_urls)}</td>
          <td>{escape(", ".join(job.tags) or "none")}</td>
          <td>{escape(_metadata_label(job.metadata))}</td>
        </tr>
        """
        for job in item.jobs
    )


def _readiness_checks_html(checks: Sequence[object]) -> str:
    if not checks:
        return '<span class="muted">none</span>'
    items = []
    for check in checks:
        name = escape(str(getattr(check, "name", "check")))
        status = escape(str(getattr(check, "status", "unknown")))
        message = escape(str(getattr(check, "message", "")))
        items.append(f"<li><strong>{name}</strong>: {status} - {message}</li>")
    return f"<ul>{''.join(items)}</ul>"


def _readiness_label(status: str) -> str:
    normalized = status or "unknown"
    css_class = "publish" if normalized == "ready" else "review"
    if normalized == "failed":
        css_class = "failed"
    return f'<span class="pill {css_class}">{escape(normalized)}</span>'


def _schedule_label(item: WorkerJobCatalogItem) -> str:
    schedule = item.schedule
    if schedule is None:
        return "not configured"
    enabled = "enabled" if schedule.enabled else "disabled"
    cron = schedule.cron or "no cron"
    return f"{enabled}: {cron} ({schedule.timezone})"


def _run_policy_label(item: WorkerJobCatalogItem) -> str:
    policy = item.run_policy
    if policy is None:
        return "not configured"
    return (
        f"timeout={policy.timeout_minutes}m, "
        f"concurrency={policy.concurrency_policy}, "
        f"retry={policy.retry.max_attempts}x/{policy.retry.backoff_seconds}s"
    )


def _job_intent_label(publish: bool) -> str:
    css_class = "publish" if publish else "review"
    label = "publish if ready" if publish else "review first"
    return f'<span class="pill {css_class}">{label}</span>'


def _handoff_label(homepage_handoff: bool) -> str:
    css_class = "publish" if homepage_handoff else "review"
    label = "homepage handoff" if homepage_handoff else "none"
    return f'<span class="pill {css_class}">{label}</span>'


def _source_urls_html(source_urls: list[str]) -> str:
    if not source_urls:
        return '<span class="muted">none</span>'
    items = "".join(
        f'<li><a href="{escape(url)}">{escape(_short_url(url))}</a></li>'
        for url in source_urls
    )
    return f'<ul class="url-list">{items}</ul>'


def _short_url(url: str) -> str:
    return url.removeprefix("https://").removeprefix("http://").removesuffix("/")


def _metadata_label(metadata: dict[str, str]) -> str:
    if not metadata:
        return "none"
    return "; ".join(f"{key}={value}" for key, value in sorted(metadata.items()))


def _run_link(run_id: str | None) -> str:
    if not run_id:
        return '<span class="muted">n/a</span>'
    escaped_run_id = escape(run_id)
    return f'<a href="/dashboard/runs/{escaped_run_id}">{escaped_run_id}</a>'


def _operations_summary_html(summary: OperationsSummary) -> str:
    return f"""
      <p>
        <a href="/dashboard/system-status">System status dashboard</a> |
        <a href="/dashboard/release-evidence">Release evidence dashboard</a> |
        <a href="/ops-summary">Operations summary JSON</a> |
        <a href="/deployment-manifest">Deployment manifest JSON</a> |
        <a href="/release-readiness">Release readiness JSON</a> |
        <a href="/release-evidence">Release evidence JSON</a>
      </p>
      <div class="metrics">
        <div><strong>{summary.total_runs}</strong><span>Total runs</span></div>
        <div><strong>{summary.review_queue_depth}</strong><span>Needs review</span></div>
        <div><strong>{summary.approved_ready_count}</strong><span>Approved</span></div>
        <div><strong>{summary.published_count}</strong><span>Published</span></div>
        <div><strong>{summary.failed_count}</strong><span>Failed</span></div>
        <div>
          <strong>{summary.action_required_incidents}</strong>
          <span>Incidents</span>
        </div>
        <div><strong>{summary.quality_pass_rate:.0%}</strong><span>Quality pass</span></div>
        <div><strong>{summary.budget_pass_rate:.0%}</strong><span>Budget pass</span></div>
        <div><strong>{_duration_label(summary.avg_duration_ms)}</strong><span>Avg run</span></div>
        <div><strong>{summary.estimated_total_tokens}</strong><span>Window tokens</span></div>
      </div>
    """


def _ops_trends_html(report: OpsTrendReport) -> str:
    rows = "".join(
        f"""
        <tr>
          <td>{escape(bucket.date)}</td>
          <td>{bucket.run_count}</td>
          <td>{bucket.published_count}</td>
          <td>{bucket.failed_count}</td>
          <td>{bucket.review_queue_count}</td>
          <td>{bucket.action_required_incidents}</td>
          <td>{bucket.quality_pass_rate:.0%}</td>
          <td>{bucket.budget_pass_rate:.0%}</td>
          <td>{_duration_label(bucket.avg_duration_ms)}</td>
          <td>{bucket.estimated_total_tokens}</td>
        </tr>
        """
        for bucket in report.buckets
    )
    return f"""
      <p>
        <a href="/ops-trends">Ops trends JSON</a> |
        <a href="/ops-summary">Operations summary JSON</a>
      </p>
      <div class="metrics">
        <div><strong>{report.days}</strong><span>Days</span></div>
        <div><strong>{report.summary.total_runs}</strong><span>Total runs</span></div>
        <div><strong>{report.summary.review_queue_depth}</strong><span>Needs review</span></div>
        <div><strong>{report.summary.failed_count}</strong><span>Failed</span></div>
        <div><strong>{report.summary.quality_pass_rate:.0%}</strong><span>Quality pass</span></div>
        <div><strong>{report.summary.budget_pass_rate:.0%}</strong><span>Budget pass</span></div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Date</th><th>Runs</th><th>Published</th><th>Failed</th>
            <th>Review</th><th>Incidents</th><th>Quality</th>
            <th>Budget</th><th>Avg run</th><th>Tokens</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _ops_brief_html(report: OpsBriefReport) -> str:
    risk_rows = "".join(
        f"""
        <tr>
          <td>{escape(risk.severity.value)}</td>
          <td>{escape(risk.category)}</td>
          <td>{escape(risk.message)}</td>
          <td>{escape(risk.evidence or "")}</td>
        </tr>
        """
        for risk in report.top_risks
    )
    action_rows = "".join(
        f"""
        <tr>
          <td>P{action.priority}</td>
          <td>{escape(action.owner)}</td>
          <td>{escape(action.action)}</td>
          <td>{escape(action.reason)}</td>
        </tr>
        """
        for action in report.recommended_actions
    )
    return f"""
      <p>
        <a href="/ops-brief">Ops brief JSON</a> |
        <a href="/dashboard/ops-trends">Operations trends</a> |
        <a href="/dashboard">Back to dashboard</a>
      </p>
      <div class="metrics">
        <div><strong>{escape(report.status)}</strong><span>Status</span></div>
        <div><strong>{report.summary.total_runs}</strong><span>Total runs</span></div>
        <div><strong>{report.summary.review_queue_depth}</strong><span>Review queue</span></div>
        <div><strong>{report.summary.failed_count}</strong><span>Failed runs</span></div>
        <div>
          <strong>{report.summary.action_required_incidents}</strong>
          <span>Action incidents</span>
        </div>
        <div><strong>{escape(report.provider_health.status)}</strong><span>Providers</span></div>
      </div>
      <p>{escape(report.headline)}</p>
      <h2>Top Risks</h2>
      <table>
        <thead>
          <tr><th>Severity</th><th>Category</th><th>Message</th><th>Evidence</th></tr>
        </thead>
        <tbody>{risk_rows}</tbody>
      </table>
      <h2>Recommended Actions</h2>
      <table>
        <thead>
          <tr><th>Priority</th><th>Owner</th><th>Action</th><th>Reason</th></tr>
        </thead>
        <tbody>{action_rows}</tbody>
      </table>
    """


def _ops_brief_deliveries_html(deliveries: list[OpsBriefDelivery]) -> str:
    if not deliveries:
        return "<p>No ops brief notifications recorded.</p>"
    rows = "".join(
        f"""
        <tr>
          <td>{escape(delivery.delivered_at.isoformat())}</td>
          <td>{escape(delivery.provider)}</td>
          <td>{escape(delivery.status)}</td>
          <td>{escape(delivery.brief_status)}</td>
          <td>{str(delivery.action_required).lower()}</td>
          <td>{escape(delivery.message)}</td>
        </tr>
        """
        for delivery in deliveries[:20]
    )
    return f"""
      <p><a href="/ops-brief/notifications">Ops brief notifications JSON</a></p>
      <table>
        <thead>
          <tr>
            <th>Delivered</th><th>Provider</th><th>Status</th>
            <th>Brief</th><th>Action</th><th>Message</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _job_execution_trends_html(report: JobExecutionTrendReport) -> str:
    latest_success = (
        report.summary.latest_success_at.isoformat() if report.summary.latest_success_at else "n/a"
    )
    latest_failure = (
        report.summary.latest_failure_at.isoformat() if report.summary.latest_failure_at else "n/a"
    )
    failure_rows = "".join(
        f"""
        <tr>
          <td><span class="pill">{escape(reason.category)}</span></td>
          <td>{escape(reason.reason)}</td>
          <td>{reason.count}</td>
          <td>{escape(reason.latest_execution_id or "n/a")}</td>
          <td>{escape(reason.latest_at.isoformat() if reason.latest_at else "n/a")}</td>
          <td>{_remediation_list_html(reason.remediation_steps)}</td>
        </tr>
        """
        for reason in report.summary.top_failure_reasons
    )
    if not failure_rows:
        failure_rows = """
        <tr>
          <td colspan="6"><span class="muted">No worker failure reasons recorded.</span></td>
        </tr>
        """
    rows = "".join(
        f"""
        <tr>
          <td>{escape(bucket.date)}</td>
          <td>{bucket.execution_count}</td>
          <td>{bucket.total_jobs}</td>
          <td>{bucket.generated_runs}</td>
          <td>{bucket.published_runs}</td>
          <td>{bucket.homepage_handoff_ready}</td>
          <td>{bucket.homepage_handoff_failed}</td>
          <td>{bucket.action_required}</td>
          <td>{bucket.success_rate:.0%}</td>
          <td>{bucket.publish_rate:.0%}</td>
          <td>{bucket.handoff_success_rate:.0%}</td>
        </tr>
        """
        for bucket in report.buckets
    )
    return f"""
      <p><a href="/job-executions/trends">Worker execution trends JSON</a></p>
      <div class="metrics">
        <div><strong>{report.days}</strong><span>Days</span></div>
        <div><strong>{report.summary.execution_count}</strong><span>Executions</span></div>
        <div><strong>{report.summary.total_jobs}</strong><span>Jobs</span></div>
        <div><strong>{report.summary.generated_runs}</strong><span>Generated runs</span></div>
        <div><strong>{report.summary.published_runs}</strong><span>Published runs</span></div>
        <div><strong>{report.summary.action_required}</strong><span>Action required</span></div>
        <div><strong>{report.summary.success_rate:.0%}</strong><span>Job success</span></div>
        <div><strong>{report.summary.publish_rate:.0%}</strong><span>Publish rate</span></div>
        <div>
          <strong>{report.summary.handoff_success_rate:.0%}</strong>
          <span>Handoff success</span>
        </div>
        <div>
          <strong>{escape(latest_success)}</strong>
          <span>Latest success</span>
        </div>
        <div>
          <strong>{escape(latest_failure)}</strong>
          <span>Latest action</span>
        </div>
      </div>
      <h2>Failure Diagnostics</h2>
      <table>
        <thead>
          <tr>
            <th>Category</th><th>Reason</th><th>Count</th><th>Latest execution</th>
            <th>Latest at</th><th>Remediation</th>
          </tr>
        </thead>
        <tbody>{failure_rows}</tbody>
      </table>
      <table>
        <thead>
          <tr>
            <th>Date</th><th>Executions</th><th>Jobs</th><th>Generated</th>
            <th>Published</th><th>Handoff ready</th><th>Handoff failed</th>
            <th>Action</th><th>Job success</th><th>Publish rate</th><th>Handoff</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _job_recovery_lineage_html(report: JobRecoveryLineageReport) -> str:
    rows = "".join(
        f"""
        <tr>
          <td>
            <a href="/dashboard/job-executions/{escape(item.source_execution_id)}">
              {escape(item.source_execution_id)}
            </a>
          </td>
          <td>{escape(item.source_execution_name)}</td>
          <td>{escape(item.latest_recovery_status)}</td>
          <td>{item.recovery_attempt_count}</td>
          <td>{item.recovered_job_count}/{item.source_failed_count}</td>
          <td>{item.unresolved_job_count}</td>
          <td>{escape(item.latest_recovery_execution_id or "n/a")}</td>
          <td>{_remediation_list_html(item.recommended_actions)}</td>
        </tr>
        """
        for item in report.items
    )
    if not rows:
        rows = """
        <tr>
          <td colspan="8">
            <span class="muted">No failed worker executions in this window.</span>
          </td>
        </tr>
        """
    return f"""
      <p><a href="/job-executions/recovery-lineage">Worker recovery lineage JSON</a></p>
      <div class="metrics">
        <div><strong>{report.total_failed_executions}</strong><span>Failed executions</span></div>
        <div><strong>{report.recovered_execution_count}</strong><span>Recovered</span></div>
        <div><strong>{report.unrecovered_execution_count}</strong><span>Unresolved</span></div>
        <div><strong>{report.recovery_attempt_count}</strong><span>Recovery attempts</span></div>
        <div>
          <strong>{report.successful_recovery_attempt_count}</strong>
          <span>Successful attempts</span>
        </div>
        <div>
          <strong>{report.failed_recovery_attempt_count}</strong>
          <span>Failed attempts</span>
        </div>
        <div>
          <strong>{str(report.action_required).lower()}</strong>
          <span>Action required</span>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Source execution</th><th>Name</th><th>Status</th><th>Attempts</th>
            <th>Recovered</th><th>Unresolved</th><th>Latest recovery</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _job_execution_alerts_html(report: JobExecutionAlertReport) -> str:
    signal_rows = "".join(
        f"""
        <tr>
          <td><span class="pill">{escape(signal.severity.value)}</span></td>
          <td>{escape(signal.category)}</td>
          <td>{escape(signal.message)}</td>
          <td>{escape(signal.latest_execution_id or "n/a")}</td>
          <td>{escape(signal.latest_at.isoformat() if signal.latest_at else "n/a")}</td>
          <td>{_remediation_list_html(signal.remediation_steps)}</td>
        </tr>
        """
        for signal in report.signals
    )
    if not signal_rows:
        signal_rows = """
        <tr>
          <td colspan="6"><span class="muted">No worker alert signals recorded.</span></td>
        </tr>
        """
    actions = "".join(f"<li>{escape(action)}</li>" for action in report.recommended_actions)
    return f"""
      <p><a href="/job-executions/alerts">Worker execution alerts JSON</a></p>
      <div class="metrics">
        <div><strong>{escape(report.severity.value)}</strong><span>Alert severity</span></div>
        <div>
          <strong>{str(report.action_required).lower()}</strong>
          <span>Action required</span>
        </div>
        <div>
          <strong>{report.trend_summary.action_required}</strong>
          <span>Executions to review</span>
        </div>
        <div><strong>{report.trend_summary.failed_jobs}</strong><span>Failed jobs</span></div>
      </div>
      <p>{escape(report.message)}</p>
      <h2>Recommended Actions</h2>
      <ul>{actions}</ul>
      <h2>Alert Signals</h2>
      <table>
        <thead>
          <tr>
            <th>Severity</th><th>Category</th><th>Message</th>
            <th>Latest execution</th><th>Latest at</th><th>Remediation</th>
          </tr>
        </thead>
        <tbody>{signal_rows}</tbody>
      </table>
    """


def _job_execution_alert_deliveries_html(
    deliveries: list[JobExecutionAlertDelivery],
) -> str:
    rows = "".join(
        f"""
        <tr>
          <td>{escape(delivery.delivered_at.isoformat())}</td>
          <td>{escape(delivery.provider)}</td>
          <td><span class="pill">{escape(delivery.status)}</span></td>
          <td>{escape(delivery.severity.value)}</td>
          <td>{escape(str(delivery.action_required).lower())}</td>
          <td>{escape(delivery.endpoint or "local")}</td>
        </tr>
        """
        for delivery in deliveries[:10]
    )
    if not rows:
        rows = """
        <tr>
          <td colspan="6"><span class="muted">No worker alert notifications recorded.</span></td>
        </tr>
        """
    return f"""
      <p><a href="/job-executions/alerts/notifications">Worker alert notifications JSON</a></p>
      <table>
        <thead>
          <tr>
            <th>Delivered at</th><th>Provider</th><th>Status</th>
            <th>Severity</th><th>Action</th><th>Endpoint</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _worker_delivery_summary_deliveries_html(
    deliveries: list[WorkerDeliverySummaryDelivery],
) -> str:
    rows = "".join(
        f"""
        <tr>
          <td>{escape(delivery.delivered_at.isoformat())}</td>
          <td>{escape(delivery.execution_id)}</td>
          <td>{escape(delivery.provider)}</td>
          <td><span class="pill">{escape(delivery.status)}</span></td>
          <td>{escape(str(delivery.action_required).lower())}</td>
          <td>{escape(delivery.endpoint or "local")}</td>
          <td>{escape(delivery.error or "none")}</td>
        </tr>
        """
        for delivery in deliveries[:10]
    )
    if not rows:
        rows = """
        <tr>
          <td colspan="7">
            <span class="muted">No delivery summary notifications recorded.</span>
          </td>
        </tr>
        """
    return f"""
      <p>
        <a href="/job-executions/delivery-summaries/notifications">
          Delivery summary notifications JSON
        </a>
      </p>
      <table>
        <thead>
          <tr>
            <th>Delivered at</th><th>Execution</th><th>Provider</th><th>Status</th>
            <th>Action</th><th>Endpoint</th><th>Error</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _system_status_html(status: SystemStatus, manifest: DeploymentManifest) -> str:
    recommendations = _system_status_recommendations(status, manifest)
    recommendation_rows = "".join(
        f"""
        <tr>
          <td>{escape(item["area"])}</td>
          <td><span class="pill">{escape(item["severity"])}</span></td>
          <td>{escape(item["action"])}</td>
        </tr>
        """
        for item in recommendations
    )
    if not recommendation_rows:
        recommendation_rows = """
        <tr>
          <td>configuration</td>
          <td><span class="pill">ok</span></td>
          <td>No immediate configuration fixes required.</td>
        </tr>
        """
    check_rows = "".join(
        f"""
        <tr>
          <td>{escape(check.name)}</td>
          <td><span class="pill">{escape(check.status)}</span></td>
          <td>{escape(check.message)}</td>
          <td><pre>{escape(json.dumps(check.fields, ensure_ascii=False, indent=2))}</pre></td>
        </tr>
        """
        for check in status.checks
    )
    capability_rows = "".join(
        f"""
        <tr>
          <td>{escape(capability.name)}</td>
          <td><span class="pill">{escape(capability.status)}</span></td>
          <td>{escape(", ".join(capability.evidence) or "none")}</td>
        </tr>
        """
        for capability in manifest.capabilities
    )
    return f"""
      <p>
        <a href="/ready">System status JSON</a> |
        <a href="/deployment-manifest">Deployment manifest JSON</a> |
        <a href="/deployment-check">Deployment check JSON</a> |
        <a href="/deployment-env-template">Production env template</a>
      </p>
      <div class="metrics">
        <div><strong>{escape(status.status)}</strong><span>System status</span></div>
        <div><strong>{escape(manifest.status)}</strong><span>Deployment status</span></div>
        <div><strong>{len(status.checks)}</strong><span>Component checks</span></div>
        <div><strong>{len(manifest.capabilities)}</strong><span>Capabilities</span></div>
        <div>
          <strong>{escape(str(manifest.runtime.get("database_engine", "n/a")))}</strong>
          <span>Database</span>
        </div>
        <div>
          <strong>{escape(str(manifest.operations.get("artifact_store_provider", "n/a")))}</strong>
          <span>Artifact store</span>
        </div>
      </div>
      <h2>Recommended Fixes</h2>
      <table>
        <thead><tr><th>Area</th><th>Severity</th><th>Action</th></tr></thead>
        <tbody>{recommendation_rows}</tbody>
      </table>
      <h2>Component Checks</h2>
      <table>
        <thead>
          <tr><th>Check</th><th>Status</th><th>Message</th><th>Fields</th></tr>
        </thead>
        <tbody>{check_rows}</tbody>
      </table>
      <h2>Deployment Capabilities</h2>
      <table>
        <thead><tr><th>Capability</th><th>Status</th><th>Evidence</th></tr></thead>
        <tbody>{capability_rows}</tbody>
      </table>
    """


def _config_audit_html(report: ConfigAuditReport) -> str:
    rows = "".join(
        f"""
        <tr>
          <td>{escape(item.name)}</td>
          <td>{escape(item.category)}</td>
          <td><span class="pill">{escape(item.status)}</span></td>
          <td>{str(item.required).lower()}</td>
          <td>{str(item.configured).lower()}</td>
          <td>{escape(item.message)}</td>
        </tr>
        """
        for item in report.items
    )
    return f"""
      <h2>Configuration Audit</h2>
      <p>
        <a href="/config-audit">Config audit JSON</a> |
        Status: <strong>{escape(report.status)}</strong> |
        Redacted: <strong>{str(report.redacted).lower()}</strong>
      </p>
      <table>
        <thead>
          <tr>
            <th>Name</th><th>Category</th><th>Status</th>
            <th>Required</th><th>Configured</th><th>Message</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _system_status_recommendations(
    status: SystemStatus,
    manifest: DeploymentManifest,
) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    for check in status.checks:
        if check.status == "ok":
            continue
        if check.name == "operator_security":
            recommendations.append(
                {
                    "area": "operator security",
                    "severity": check.status,
                    "action": (
                        "Set CONTENTOPS_OPERATOR_API_KEY before exposing mutating routes; "
                        "set CONTENTOPS_REQUIRE_READ_API_KEY=true and CONTENTOPS_READ_API_KEY "
                        "when read dashboards should be protected."
                    ),
                }
            )
            continue
        if check.name == "provider_config":
            recommendations.extend(_provider_recommendations(check.fields, check.status))
            continue
        if check.name == "artifact_store":
            recommendations.append(
                {
                    "area": "artifact store",
                    "severity": check.status,
                    "action": (
                        "Use a writable CONTENTOPS_ARTIFACT_ROOT locally, or set "
                        "CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3 with CONTENTOPS_ARTIFACT_S3_BUCKET "
                        "for deployable artifact mirroring."
                    ),
                }
            )
            continue
        if check.name == "database":
            recommendations.append(
                {
                    "area": "database",
                    "severity": check.status,
                    "action": (
                        "Set CONTENTOPS_DATABASE_URL to a reachable SQLite or PostgreSQL database "
                        "and run the migration command before starting workers."
                    ),
                }
            )
            continue
        recommendations.append(
            {
                "area": check.name,
                "severity": check.status,
                "action": check.message,
            }
        )
    for capability in manifest.capabilities:
        if capability.status == "ok":
            continue
        if capability.name == "scheduled_research_ready":
            recommendations.append(
                {
                    "area": "scheduled research",
                    "severity": capability.status,
                    "action": (
                        "Use CONTENTOPS_RESEARCH_PROVIDER=feed, discovery, search, or github "
                        "for unattended worker runs; configure feeds, search credentials, or a "
                        "GitHub token according to the selected provider."
                    ),
                }
            )
        elif capability.name == "aws_deployment_ready":
            recommendations.append(
                {
                    "area": "aws deployment",
                    "severity": capability.status,
                    "action": (
                        "Use PostgreSQL/RDS instead of local SQLite and configure S3 artifact "
                        "mirroring before treating this deployment as cloud-ready."
                    ),
                }
            )
        elif capability.name == "publishing_recovery":
            recommendations.append(
                {
                    "area": "publishing",
                    "severity": capability.status,
                    "action": (
                        "Verify CONTENTOPS_PUBLISHER_PROVIDER and its target path or homepage "
                        "repository so publish receipts and rollback evidence can be generated."
                    ),
                }
            )
    return _unique_recommendations(recommendations)


def _provider_recommendations(fields: dict[str, object], severity: str) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    failures = fields.get("failures", [])
    if isinstance(failures, list):
        for failure in failures:
            recommendations.append(
                {
                    "area": "provider configuration",
                    "severity": severity,
                    "action": str(failure),
                }
            )
    warnings = fields.get("warnings", [])
    if isinstance(warnings, list):
        for warning in warnings:
            recommendations.append(
                {
                    "area": "provider configuration",
                    "severity": severity,
                    "action": str(warning),
                }
            )
    research = fields.get("research_readiness", {})
    if isinstance(research, dict) and research.get("scheduled_ready") is False:
        recommendations.append(
            {
                "area": "research provider",
                "severity": severity,
                "action": (
                    "Current research provider is not ideal for scheduled automation. "
                    "Use feed/discovery with CONTENTOPS_RESEARCH_FEEDS, search with "
                    "CONTENTOPS_RESEARCH_SEARCH_API_KEY and CONTENTOPS_RESEARCH_SEARCH_ENDPOINT, "
                    "or github with CONTENTOPS_RESEARCH_GITHUB_TOKEN."
                ),
            }
        )
    publishing = fields.get("publishing_readiness", {})
    if isinstance(publishing, dict) and publishing.get("ready") is False:
        recommendations.append(
            {
                "area": "publishing provider",
                "severity": severity,
                "action": (
                    "Fix CONTENTOPS_PUBLISHER_PROVIDER and its target path settings before "
                    "enabling automated publish jobs."
                ),
            }
        )
    return recommendations


def _unique_recommendations(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, str]] = []
    for item in items:
        key = (item["area"], item["severity"], item["action"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _release_evidence_html(bundle: ReleaseEvidenceBundle) -> str:
    summary = bundle.summary
    deploy_status = escape(bundle.deployment_check.status)
    can_deploy = str(bundle.deployment_check.can_deploy).lower()
    worker_alerts = bundle.worker_execution_alerts
    worker_alert_deliveries = bundle.worker_execution_alert_deliveries
    worker_recovery = bundle.worker_recovery_lineage
    worker_trends_summary = bundle.worker_execution_trends.get("summary", {})
    worker_buckets = bundle.worker_execution_trends.get("buckets", [])
    worker_failure_reasons = worker_trends_summary.get("top_failure_reasons", [])
    source_review_latest = {
        item.run_id: item.latest_reviewed_at.isoformat() if item.latest_reviewed_at else "n/a"
        for item in bundle.source_reviews.items
    }
    provider_rows = "".join(
        f"""
        <tr>
          <td>{escape(item.category)}</td>
          <td>{escape(item.name)}</td>
          <td><span class="pill">{escape(item.status)}</span></td>
          <td>{escape(item.mode)}</td>
          <td>{escape(str(item.scheduled_ready).lower())}</td>
          <td>{escape(str(item.credential_configured).lower())}</td>
          <td>{escape("; ".join(item.warnings) or "none")}</td>
        </tr>
        """
        for item in bundle.provider_health.items
    )
    smoke_rows = "".join(
        f"""
        <tr>
          <td>{escape(item.category)}</td>
          <td>{escape(item.name)}</td>
          <td><span class="pill">{escape(item.status)}</span></td>
          <td><code>{escape(item.command)}</code></td>
          <td>{escape(", ".join(item.missing_env) or "none")}</td>
          <td>{escape("; ".join(item.notes) or "none")}</td>
        </tr>
        """
        for item in bundle.integration_smoke_plan.items
    )
    source_review_rows = "".join(
        f"""
        <tr>
          <td>{escape(item.run_id)}</td>
          <td>{escape(item.artifact_path)}</td>
          <td>{item.total}</td>
          <td>{item.include_count}</td>
          <td>{item.exclude_count}</td>
          <td>{item.needs_review_count}</td>
          <td>{escape(source_review_latest[item.run_id])}</td>
        </tr>
        """
        for item in bundle.source_reviews.items
    )
    if not source_review_rows:
        source_review_rows = """
        <tr>
          <td colspan="7"><span class="muted">No source review decisions recorded.</span></td>
        </tr>
        """
    gate_rows = "".join(
        f"""
        <tr>
          <td>{escape(check.name)}</td>
          <td><span class="pill">{escape(check.status)}</span></td>
          <td>{escape(check.message)}</td>
          <td><pre>{escape(json.dumps(check.evidence, ensure_ascii=False, indent=2))}</pre></td>
        </tr>
        """
        for check in bundle.release_readiness.checks
    )
    preflight_rows = "".join(
        f"""
        <tr>
          <td>{escape(check.name)}</td>
          <td><span class="pill">{escape(check.status)}</span></td>
          <td>{escape(check.message)}</td>
          <td><pre>{escape(json.dumps(check.evidence, ensure_ascii=False, indent=2))}</pre></td>
        </tr>
        """
        for check in bundle.deployment_check.checks
    )
    capability_rows = "".join(
        f"""
        <tr>
          <td>{escape(capability.name)}</td>
          <td><span class="pill">{escape(capability.status)}</span></td>
          <td>{escape(", ".join(capability.evidence) or "none")}</td>
        </tr>
        """
        for capability in bundle.deployment_manifest.capabilities
    )
    artifact_rows = "".join(
        f"""
        <tr>
          <td>{escape(name)}</td>
        </tr>
        """
        for name in summary.artifact_files
    )
    if not artifact_rows:
        artifact_rows = '<tr><td><span class="muted">No files recorded.</span></td></tr>'
    handoff_rows = "".join(
        f"""
        <tr>
          <td>{escape(item.run_id)}</td>
          <td>{escape(item.artifact_path)}</td>
          <td>{item.size_bytes}</td>
          <td><code>{escape(item.sha256[:16])}...</code></td>
          <td>{escape(item.updated_at.isoformat())}</td>
        </tr>
        """
        for item in bundle.homepage_handoffs.items
    )
    if not handoff_rows:
        handoff_rows = """
        <tr>
          <td colspan="5"><span class="muted">No homepage handoff bundles recorded.</span></td>
        </tr>
        """
    distribution_rows = "".join(
        f"""
        <tr>
          <td>{escape(item.manifest_path)}</td>
          <td>{item.asset_count}</td>
          <td>{item.size_bytes}</td>
          <td><code>{escape(item.sha256[:16])}...</code></td>
          <td>{escape(str(item.git.get("branch") or "n/a"))}</td>
          <td>{escape(str(item.git.get("dirty", "n/a")).lower())}</td>
          <td>{escape(item.updated_at.isoformat())}</td>
        </tr>
        """
        for item in bundle.content_distribution.items
    )
    if not distribution_rows:
        distribution_rows = """
        <tr>
          <td colspan="7">
            <span class="muted">No content distribution manifests recorded.</span>
          </td>
        </tr>
        """
    publish_verification_rows = "".join(
        f"""
        <tr>
          <td><a href="/dashboard/runs/{escape(item.run_id)}">{escape(item.run_id)}</a></td>
          <td><span class="pill">{escape(str(item.verified).lower())}</span></td>
          <td>{escape(item.provider)}</td>
          <td><a href="{escape(item.url)}">{escape(item.url)}</a></td>
          <td>{item.item_count}</td>
          <td>{item.mismatch_count}</td>
          <td>{item.missing_count}</td>
          <td>{escape(item.artifact_path)}</td>
          <td>{escape(item.verified_at.isoformat())}</td>
        </tr>
        """
        for item in bundle.publish_verifications.items
    )
    if not publish_verification_rows:
        publish_verification_rows = """
        <tr>
          <td colspan="9">
            <span class="muted">No published content verification recorded.</span>
          </td>
        </tr>
        """
    publish_recovery_rows = "".join(
        f"""
        <tr>
          <td><a href="/dashboard/runs/{escape(item.run_id)}">{escape(item.run_id)}</a></td>
          <td>{escape(item.action)}</td>
          <td><span class="pill">{escape(item.status)}</span></td>
          <td>{escape(item.actor)}</td>
          <td>{item.restored_files}</td>
          <td>{item.deleted_files}</td>
          <td>{item.error_count}</td>
          <td>{escape(item.artifact_path)}</td>
          <td>{escape(item.executed_at.isoformat())}</td>
        </tr>
        """
        for item in bundle.publish_recovery_executions.items
    )
    if not publish_recovery_rows:
        publish_recovery_rows = """
        <tr>
          <td colspan="9"><span class="muted">No publish recovery executions recorded.</span></td>
        </tr>
        """
    scheduled_review_rows = "".join(
        f"""
        <tr>
          <td><code>{escape(item.id)}</code></td>
          <td><span class="pill">{escape(item.status)}</span></td>
          <td>{escape(item.verification_status)}</td>
          <td>{item.verification_failed_count}</td>
          <td>{item.artifact_count}</td>
          <td>{escape(str(item.action_required).lower())}</td>
          <td>{escape(item.manifest_path)}</td>
          <td>{escape(item.archive_path or "not available")}</td>
          <td>{item.archive_size_bytes}</td>
          <td>{escape(item.s3_mirror_status)}</td>
          <td>{escape((item.archive_sha256 or "n/a")[:16])}</td>
        </tr>
        """
        for item in bundle.scheduled_review_packages.items
    )
    if not scheduled_review_rows:
        scheduled_review_rows = """
        <tr>
          <td colspan="11">
            <span class="muted">No scheduled review packages recorded.</span>
          </td>
        </tr>
        """
    worker_trend_rows = "".join(
        f"""
        <tr>
          <td>{escape(str(bucket.get("date", "n/a")))}</td>
          <td>{escape(str(bucket.get("execution_count", 0)))}</td>
          <td>{escape(str(bucket.get("generated_runs", 0)))}</td>
          <td>{escape(str(bucket.get("published_runs", 0)))}</td>
          <td>{escape(str(bucket.get("action_required", 0)))}</td>
        </tr>
        """
        for bucket in worker_buckets[-14:]
        if isinstance(bucket, dict)
    )
    if not worker_trend_rows:
        worker_trend_rows = """
        <tr>
          <td colspan="5"><span class="muted">No worker execution trend data recorded.</span></td>
        </tr>
        """
    worker_failure_rows = "".join(
        f"""
        <tr>
          <td>{escape(str(reason.get("category", "worker_failure")))}</td>
          <td>{escape(str(reason.get("reason", "n/a")))}</td>
          <td>{escape(str(reason.get("count", 0)))}</td>
          <td>{escape(str(reason.get("latest_execution_id") or "n/a"))}</td>
          <td>{escape(str(reason.get("latest_at") or "n/a"))}</td>
          <td>{_remediation_list_html(_dict_string_list(reason.get("remediation_steps")))}</td>
        </tr>
        """
        for reason in worker_failure_reasons
        if isinstance(reason, dict)
    )
    if not worker_failure_rows:
        worker_failure_rows = """
        <tr>
          <td colspan="6"><span class="muted">No worker failure reasons recorded.</span></td>
        </tr>
        """
    worker_alert_signal_rows = "".join(
        f"""
        <tr>
          <td>{escape(str(signal.get("severity", "n/a")))}</td>
          <td>{escape(str(signal.get("category", "n/a")))}</td>
          <td>{escape(str(signal.get("message", "n/a")))}</td>
          <td>{escape(str(signal.get("latest_execution_id") or "n/a"))}</td>
          <td>{_remediation_list_html(_dict_string_list(signal.get("remediation_steps")))}</td>
        </tr>
        """
        for signal in worker_alerts.get("signals", [])
        if isinstance(signal, dict)
    )
    if not worker_alert_signal_rows:
        worker_alert_signal_rows = """
        <tr>
          <td colspan="5"><span class="muted">No worker alert signals recorded.</span></td>
        </tr>
        """
    worker_alert_delivery_rows = "".join(
        f"""
        <tr>
          <td>{escape(str(delivery.get("delivered_at", "n/a")))}</td>
          <td>{escape(str(delivery.get("provider", "n/a")))}</td>
          <td>{escape(str(delivery.get("status", "n/a")))}</td>
          <td>{escape(str(delivery.get("severity", "n/a")))}</td>
          <td>{escape(str(delivery.get("action_required", "n/a")).lower())}</td>
        </tr>
        """
        for delivery in worker_alert_deliveries[:10]
        if isinstance(delivery, dict)
    )
    if not worker_alert_delivery_rows:
        worker_alert_delivery_rows = """
        <tr>
          <td colspan="5"><span class="muted">No worker alert notifications recorded.</span></td>
        </tr>
        """
    worker_recovery_rows = "".join(
        f"""
        <tr>
          <td>{escape(str(item.get("source_execution_id", "n/a")))}</td>
          <td>{escape(str(item.get("source_execution_name", "n/a")))}</td>
          <td>{escape(str(item.get("latest_recovery_status", "n/a")))}</td>
          <td>{escape(str(item.get("recovery_attempt_count", 0)))}</td>
          <td>
            {escape(str(item.get("recovered_job_count", 0)))}/
            {escape(str(item.get("source_failed_count", 0)))}
          </td>
          <td>{escape(str(item.get("unresolved_job_count", 0)))}</td>
          <td>{escape(str(item.get("latest_recovery_execution_id") or "n/a"))}</td>
          <td>{_remediation_list_html(_dict_string_list(item.get("recommended_actions")))}</td>
        </tr>
        """
        for item in worker_recovery.get("items", [])
        if isinstance(item, dict)
    )
    if not worker_recovery_rows:
        worker_recovery_rows = """
        <tr>
          <td colspan="8"><span class="muted">No worker recovery lineage recorded.</span></td>
        </tr>
        """
    return f"""
      <p>
        <a href="/release-evidence/bundle">Download evidence bundle</a> |
        <a href="/release-evidence">Release evidence JSON</a> |
        <a href="/deployment-manifest">Deployment manifest JSON</a> |
        <a href="/release-readiness">Release readiness JSON</a>
      </p>
      <div class="metrics">
        <div><strong>{escape(summary.release_status)}</strong><span>Release status</span></div>
        <div><strong>{str(summary.can_release).lower()}</strong><span>Can release</span></div>
        <div><strong>{deploy_status}</strong><span>Deploy status</span></div>
        <div><strong>{can_deploy}</strong><span>Can deploy</span></div>
        <div><strong>{escape(summary.doctor_status)}</strong><span>Doctor status</span></div>
        <div>
          <strong>{escape(bundle.provider_health.status)}</strong>
          <span>Provider health</span>
        </div>
        <div>
          <strong>{escape(bundle.integration_smoke_plan.status)}</strong>
          <span>Smoke plan</span>
        </div>
        <div>
          <strong>{bundle.integration_smoke_runs.summary.total_reports}</strong>
          <span>Smoke runs</span>
        </div>
        <div><strong>{escape(summary.git_sha or "n/a")}</strong><span>Git SHA</span></div>
        <div><strong>{len(summary.artifact_files)}</strong><span>Evidence files</span></div>
        <div><strong>{bundle.homepage_handoffs.total}</strong><span>Homepage handoffs</span></div>
        <div>
          <strong>{bundle.content_distribution.total}</strong>
          <span>Distribution manifests</span>
        </div>
        <div>
          <strong>{bundle.publish_verifications.drift_count}</strong>
          <span>Publish drifts</span>
        </div>
        <div>
          <strong>{bundle.publish_recovery_executions.completed_count}</strong>
          <span>Recovery runs</span>
        </div>
        <div>
          <strong>{bundle.source_reviews.total_decisions}</strong>
          <span>Source reviews</span>
        </div>
        <div>
          <strong>{bundle.source_reviews.needs_review_count}</strong>
          <span>Pending sources</span>
        </div>
        <div>
          <strong>{escape(str(worker_trends_summary.get("execution_count", 0)))}</strong>
          <span>Worker executions</span>
        </div>
        <div>
          <strong>{escape(str(worker_trends_summary.get("action_required", 0)))}</strong>
          <span>Worker actions</span>
        </div>
        <div>
          <strong>{escape(str(worker_recovery.get("unrecovered_execution_count", 0)))}</strong>
          <span>Recovery backlog</span>
        </div>
        <div>
          <strong>{len(bundle.ops_brief_deliveries)}</strong>
          <span>Ops brief deliveries</span>
        </div>
        <div>
          <strong>{bundle.retention_archives.total}</strong>
          <span>Retention archives</span>
        </div>
        <div>
          <strong>{bundle.scheduled_review_packages.total}</strong>
          <span>Scheduled packages</span>
        </div>
        <div><strong>{escape(summary.generated_at.isoformat())}</strong><span>Generated</span></div>
      </div>
      <h2>Operations Brief</h2>
      {_ops_brief_html(bundle.ops_brief)}
      <h2>Ops Brief Notifications</h2>
      {_ops_brief_deliveries_html(bundle.ops_brief_deliveries)}
      <h2>Retention Archives</h2>
      {_retention_archives_html(bundle.retention_archives)}
      <h2>Provider Health</h2>
      <table>
        <thead>
          <tr>
            <th>Category</th><th>Provider</th><th>Status</th><th>Mode</th>
            <th>Scheduled</th><th>Credential</th><th>Warnings</th>
          </tr>
        </thead>
        <tbody>{provider_rows}</tbody>
      </table>
      <h2>Integration Smoke Plan</h2>
      <p>
        Run all: <code>{escape(bundle.integration_smoke_plan.command)}</code>
      </p>
      <table>
        <thead>
          <tr>
            <th>Category</th><th>Provider</th><th>Status</th><th>Selector</th>
            <th>Missing env</th><th>Notes</th>
          </tr>
        </thead>
        <tbody>{smoke_rows}</tbody>
      </table>
      <h2>Integration Smoke Runs</h2>
      {_integration_smoke_runs_html(bundle.integration_smoke_runs)}
      <h2>Deployment Preflight</h2>
      <table>
        <thead>
          <tr><th>Check</th><th>Status</th><th>Message</th><th>Evidence</th></tr>
        </thead>
        <tbody>{preflight_rows}</tbody>
      </table>
      <h2>Release Gate Checks</h2>
      <table>
        <thead>
          <tr><th>Check</th><th>Status</th><th>Message</th><th>Evidence</th></tr>
        </thead>
        <tbody>{gate_rows}</tbody>
      </table>
      <h2>Deployment Capabilities</h2>
      <table>
        <thead><tr><th>Capability</th><th>Status</th><th>Evidence</th></tr></thead>
        <tbody>{capability_rows}</tbody>
      </table>
      <h2>Evidence Files</h2>
      <table>
        <thead><tr><th>File</th></tr></thead>
        <tbody>{artifact_rows}</tbody>
      </table>
      <h2>Homepage Handoffs</h2>
      <table>
        <thead>
          <tr><th>Run</th><th>Artifact</th><th>Size</th><th>SHA256</th><th>Updated</th></tr>
        </thead>
        <tbody>{handoff_rows}</tbody>
      </table>
      <h2>Content Distribution Evidence</h2>
      <table>
        <thead>
          <tr>
            <th>Manifest</th><th>Assets</th><th>Size</th><th>SHA256</th>
            <th>Branch</th><th>Dirty</th><th>Updated</th>
          </tr>
        </thead>
        <tbody>{distribution_rows}</tbody>
      </table>
      <h2>Publish Verification Evidence</h2>
      <table>
        <thead>
          <tr>
            <th>Run</th><th>Verified</th><th>Provider</th><th>URL</th><th>Files</th>
            <th>Mismatches</th><th>Missing</th><th>Artifact</th><th>Verified at</th>
          </tr>
        </thead>
        <tbody>{publish_verification_rows}</tbody>
      </table>
      <h2>Publish Recovery Executions</h2>
      <table>
        <thead>
          <tr>
            <th>Run</th><th>Action</th><th>Status</th><th>Actor</th>
            <th>Restored</th><th>Deleted</th><th>Errors</th><th>Artifact</th><th>Executed</th>
          </tr>
        </thead>
        <tbody>{publish_recovery_rows}</tbody>
      </table>
      <h2>Scheduled Review Package Evidence</h2>
      <table>
        <thead>
          <tr>
            <th>Package</th><th>Status</th><th>Verification</th><th>Failed</th>
            <th>Artifacts</th><th>Action</th><th>Manifest</th><th>Archive</th>
            <th>Zip bytes</th><th>S3 mirror</th><th>SHA256</th>
          </tr>
        </thead>
        <tbody>{scheduled_review_rows}</tbody>
      </table>
      <h2>Source Review Evidence</h2>
      <table>
        <thead>
          <tr>
            <th>Run</th><th>Artifact</th><th>Total</th><th>Include</th>
            <th>Exclude</th><th>Needs review</th><th>Latest</th>
          </tr>
        </thead>
        <tbody>{source_review_rows}</tbody>
      </table>
      <h2>Worker Execution Trends</h2>
      <div class="metrics">
        <div>
          <strong>{escape(str(worker_alerts.get("severity", "info")))}</strong>
          <span>Worker alert</span>
        </div>
        <div>
          <strong>{escape(str(worker_alerts.get("action_required", False)).lower())}</strong>
          <span>Worker action</span>
        </div>
      </div>
      <p>{escape(str(worker_alerts.get("message", "Worker alert report unavailable.")))}</p>
      <table>
        <thead>
          <tr>
            <th>Severity</th><th>Category</th><th>Message</th><th>Latest execution</th>
            <th>Remediation</th>
          </tr>
        </thead>
        <tbody>{worker_alert_signal_rows}</tbody>
      </table>
      <h2>Worker Recovery Lineage</h2>
      <div class="metrics">
        <div>
          <strong>{escape(str(worker_recovery.get("total_failed_executions", 0)))}</strong>
          <span>Failed executions</span>
        </div>
        <div>
          <strong>{escape(str(worker_recovery.get("recovered_execution_count", 0)))}</strong>
          <span>Recovered executions</span>
        </div>
        <div>
          <strong>{escape(str(worker_recovery.get("unrecovered_execution_count", 0)))}</strong>
          <span>Unresolved executions</span>
        </div>
        <div>
          <strong>{escape(str(worker_recovery.get("recovery_attempt_count", 0)))}</strong>
          <span>Recovery attempts</span>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Source execution</th><th>Name</th><th>Status</th><th>Attempts</th>
            <th>Recovered</th><th>Unresolved</th><th>Latest recovery</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>{worker_recovery_rows}</tbody>
      </table>
      <h2>Worker Alert Notifications</h2>
      <table>
        <thead>
          <tr>
            <th>Delivered at</th><th>Provider</th><th>Status</th>
            <th>Severity</th><th>Action</th>
          </tr>
        </thead>
        <tbody>{worker_alert_delivery_rows}</tbody>
      </table>
      <table>
        <thead>
          <tr><th>Date</th><th>Executions</th><th>Generated</th><th>Published</th><th>Action</th></tr>
        </thead>
        <tbody>{worker_trend_rows}</tbody>
      </table>
      <h2>Worker Failure Diagnostics</h2>
      <table>
        <thead>
          <tr>
            <th>Category</th><th>Reason</th><th>Count</th><th>Latest execution</th>
            <th>Latest at</th><th>Remediation</th>
          </tr>
        </thead>
        <tbody>{worker_failure_rows}</tbody>
      </table>
    """


def _release_gate_html(report: ReleaseGateReport) -> str:
    checklist_items = "".join(
        f"<li>{escape(item)}</li>" for item in report.deployment_checklist
    )
    rows = "".join(
        f"""
        <tr>
          <td>{escape(check.name)}</td>
          <td><span class="pill">{escape(check.status)}</span></td>
          <td>{escape(check.message)}</td>
          <td>{_release_gate_remediation_html(check.remediation_steps)}</td>
          <td><pre>{escape(json.dumps(check.evidence, ensure_ascii=False, indent=2))}</pre></td>
        </tr>
        """
        for check in report.checks
    )
    return f"""
      <h2>Deployment Gate</h2>
      <p>
        <a href="/release-gate">Release gate JSON</a> |
        Status: <strong>{escape(report.status)}</strong> |
        Can deploy: <strong>{str(report.can_deploy).lower()}</strong>
      </p>
      <h3>Deployment Checklist</h3>
      <ul>{checklist_items}</ul>
      <table>
        <thead>
          <tr>
            <th>Check</th><th>Status</th><th>Message</th><th>Remediation</th><th>Evidence</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _release_gate_remediation_html(steps: list[str]) -> str:
    return _remediation_list_html(steps)


def _remediation_list_html(steps: list[str]) -> str:
    if not steps:
        return '<span class="muted">No action required.</span>'
    items = "".join(f"<li>{escape(step)}</li>" for step in steps)
    return f"<ul>{items}</ul>"


def _dict_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _release_gate_history_html(reports: ReleaseGateListResponse) -> str:
    summary = reports.summary
    common_failures = ", ".join(
        f"{item.name} ({item.count})" for item in summary.most_common_failed_checks
    )
    if not common_failures:
        common_failures = "No failed checks recorded."
    rows = "".join(
        f"""
        <tr>
          <td>{escape(report.generated_at.isoformat())}</td>
          <td><span class="pill">{escape(report.status)}</span></td>
          <td>{str(report.can_deploy).lower()}</td>
          <td>{escape(report.git_sha or "n/a")}</td>
          <td>{len(report.checks)}</td>
        </tr>
        """
        for report in reports.items
    )
    if not rows:
        rows = """
        <tr>
          <td colspan="5"><span class="muted">No release gate reports recorded.</span></td>
        </tr>
        """
    return f"""
      <h2>Recent Release Gates</h2>
      <p>
        <a href="/release-gates">Release gate history JSON</a> |
        Latest: <strong>{escape(summary.latest_status or "n/a")}</strong> |
        Pass rate: <strong>{summary.pass_rate:.0%}</strong> |
        Blocked: <strong>{summary.blocked_count}</strong> |
        Consecutive failures: <strong>{summary.consecutive_failures}</strong>
      </p>
      <p class="muted">Most common failed checks: {escape(common_failures)}</p>
      <table>
        <thead>
          <tr>
            <th>Generated</th><th>Status</th><th>Can deploy</th><th>Git SHA</th><th>Checks</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _integration_smoke_runs_html(reports: IntegrationSmokeRunListResponse) -> str:
    summary = reports.summary
    rows = "".join(
        f"""
        <tr>
          <td>{escape(report.generated_at.isoformat())}</td>
          <td><span class="pill">{escape(report.status)}</span></td>
          <td>{escape(str(report.integration_enabled).lower())}</td>
          <td>{escape(str(report.dry_run).lower())}</td>
          <td>{escape(", ".join(report.selected) or "all")}</td>
          <td>{len(report.items)}</td>
          <td>{escape(str(report.summary.get("pass", 0)))}</td>
          <td>{escape(str(report.summary.get("skip", 0)))}</td>
          <td>{escape(str(report.summary.get("fail", 0)))}</td>
          <td>{escape(report.artifact_path or "n/a")}</td>
        </tr>
        """
        for report in reports.items
    )
    if not rows:
        rows = """
        <tr>
          <td colspan="10">
            <span class="muted">No integration smoke run reports recorded.</span>
          </td>
        </tr>
        """
    return f"""
      <div class="metrics">
        <div><strong>{summary.total_reports}</strong><span>Total reports</span></div>
        <div><strong>{escape(summary.latest_status or "n/a")}</strong><span>Latest</span></div>
        <div><strong>{summary.pass_count}</strong><span>Pass</span></div>
        <div><strong>{summary.warn_count}</strong><span>Warn</span></div>
        <div><strong>{summary.fail_count}</strong><span>Fail</span></div>
      </div>
      <p><a href="/integration-smoke-runs">Integration smoke run JSON</a></p>
      <table>
        <thead>
          <tr>
            <th>Generated</th><th>Status</th><th>Enabled</th><th>Dry run</th>
            <th>Selected</th><th>Items</th><th>Pass</th><th>Skip</th><th>Fail</th>
            <th>Artifact</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _release_approvals_html(approvals: ReleaseApprovalListResponse, api_key: str) -> str:
    rows = "".join(
        f"""
        <tr>
          <td>{escape(record.decision.value)}</td>
          <td>{escape(record.approver)}</td>
          <td>{escape(record.release_status)}</td>
          <td>{escape(record.deployment_status)}</td>
          <td>{escape(record.git_sha or "n/a")}</td>
          <td>{escape(record.approved_at.isoformat())}</td>
          <td>{escape(record.notes or "")}</td>
        </tr>
        """
        for record in approvals.items
    )
    if not rows:
        rows = """
        <tr>
          <td colspan="7"><span class="muted">No release approvals recorded.</span></td>
        </tr>
        """
    return f"""
      <h2>Release Approval</h2>
      <form method="post" action="/dashboard/release-approval{_api_key_query(api_key)}">
        {_api_key_hidden(api_key)}
        <label>
          Decision
          <select name="decision">
            <option value="approved">Approve release</option>
            <option value="rejected">Reject release</option>
          </select>
        </label>
        <label>Approver <input name="approver" value="operator"></label>
        <label>Notes <input name="notes" placeholder="Approval context or rejection reason"></label>
        <label><input type="checkbox" name="force" value="true"> Force approval</label>
        <button type="submit">Record Decision</button>
      </form>
      <h2>Recent Release Approvals</h2>
      <table>
        <thead>
          <tr>
            <th>Decision</th><th>Approver</th><th>Release</th><th>Deploy</th>
            <th>Git SHA</th><th>Time</th><th>Notes</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _audit_events_html(events: AuditEventListResponse) -> str:
    if not events.items:
        return "<p>No audit events recorded.</p>"
    rows = "".join(
        f"""
        <tr>
          <td><a href="/dashboard/runs/{escape(event.run_id)}">{escape(event.run_id)}</a></td>
          <td>{escape(event.action)}</td>
          <td>{escape(event.actor)}</td>
          <td>{escape(event.previous_status.value if event.previous_status else "n/a")}</td>
          <td>{escape(event.new_status.value if event.new_status else "n/a")}</td>
          <td>{escape(event.occurred_at.isoformat())}</td>
        </tr>
        """
        for event in events.items
    )
    counts = ", ".join(
        f"{escape(action)}={count}" for action, count in sorted(events.action_counts.items())
    )
    return f"""
      <p>
        <a href="/audit-events">Audit events JSON</a> |
        Showing <strong>{len(events.items)}</strong> of <strong>{events.total}</strong> |
        {counts}
      </p>
      <table>
        <thead>
          <tr>
            <th>Run</th><th>Action</th><th>Actor</th><th>Previous</th><th>New</th><th>Time</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _retention_report_html(
    report: RetentionReport,
    archives: RetentionArchiveListResponse | None = None,
) -> str:
    archive_html = _retention_archives_html(archives) if archives is not None else ""
    if not report.candidates:
        return f"""
          <p>
            <a href="/retention-report">Retention report JSON</a> |
            <a href="/retention-archives">Retention archives JSON</a> |
            Scanned <strong>{report.total_runs_scanned}</strong> runs |
            Total size: <strong>{report.total_size_bytes}</strong> bytes |
            No candidates older than <strong>{report.retention_days}</strong> day(s).
          </p>
          {archive_html}
        """
    rows = "".join(
        f"""
        <tr>
          <td><a href="/dashboard/runs/{escape(item.run_id)}">{escape(item.run_id)}</a></td>
          <td>{escape(item.status.value)}</td>
          <td>{item.artifact_count}</td>
          <td>{item.size_bytes}</td>
          <td>{escape(item.updated_at.isoformat())}</td>
        </tr>
        """
        for item in report.candidates[:10]
    )
    return f"""
      <p>
        <a href="/retention-report">Retention report JSON</a> |
        <a href="/retention-archives">Retention archives JSON</a> |
        Candidates: <strong>{report.candidate_count}</strong> |
        Candidate size: <strong>{report.candidate_size_bytes}</strong> bytes
      </p>
      <table>
        <thead>
          <tr><th>Run</th><th>Status</th><th>Artifacts</th><th>Bytes</th><th>Updated</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      {archive_html}
    """


def _retention_archives_html(
    archives: RetentionArchiveListResponse | RetentionArchiveEvidence | None,
) -> str:
    if archives is None or not archives.items:
        return (
            "<p>No retention archives recorded. "
            "S3 mirror status appears after archive creation.</p>"
        )
    rows = "".join(
        f"""
        <tr>
          <td>{escape(item.archive_id)}</td>
          <td>{item.candidate_count}</td>
          <td>{item.archived_size_bytes}</td>
          <td>{escape(str(item.dry_run).lower())}</td>
          <td>{escape(item.s3_mirror_status)}</td>
          <td>{item.s3_mirror_failures}</td>
          <td>{escape(item.created_at.isoformat())}</td>
        </tr>
        """
        for item in archives.items
    )
    return f"""
      <h2>Recent Archives</h2>
      <table>
        <thead>
          <tr>
            <th>Archive</th><th>Candidates</th><th>Bytes</th><th>Dry run</th>
            <th>S3 mirror</th><th>Mirror failures</th><th>Created</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _published_content_html(catalog: PublishedContentListResponse) -> str:
    if not catalog.items:
        return "<p>No published content recorded.</p>"
    rows = "".join(
        f"""
        <tr>
          <td><a href="/dashboard/runs/{escape(item.run_id)}">{escape(item.run_id)}</a></td>
          <td><a href="{escape(item.url)}">{escape(item.title)}</a></td>
          <td>{escape(item.provider)}</td>
          <td>{item.groundedness:.2f}</td>
          <td>{item.source_quality:.2f}</td>
          <td>{item.technical_depth:.2f}</td>
          <td>{escape(item.published_at.isoformat())}</td>
        </tr>
        """
        for item in catalog.items
    )
    return f"""
      <p>
        <a href="/content">Content catalog JSON</a> |
        <a href="/content-assets/feed">RSS feed</a> |
        <a href="/content-assets/promotion-brief">Promotion brief</a> |
        <a href="/content-assets/manifest">Distribution manifest</a>
      </p>
      <table>
        <thead>
          <tr>
            <th>Run</th><th>Title</th><th>Provider</th><th>Grounded</th>
            <th>Source quality</th><th>Depth</th><th>Published</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _scorecards_html(scorecards: ScorecardListResponse) -> str:
    if not scorecards.items:
        return "<p>No scorecards recorded.</p>"
    rows = "".join(
        f"""
        <tr>
          <td><a href="/dashboard/runs/{escape(item.run_id)}">{escape(item.run_id)}</a></td>
          <td>{escape(item.status.value)}</td>
          <td>{escape(item.topic)}</td>
          <td>{_pass_label(item.overall_pass)}</td>
          <td>{_optional_score(item.groundedness)}</td>
          <td>{_optional_score(item.source_quality)}</td>
          <td>{_duration_label(item.total_duration_ms)}</td>
          <td>{item.source_count}</td>
        </tr>
        """
        for item in scorecards.items
    )
    return f"""
      <p>
        <a href="/scorecards">Scorecards JSON</a> |
        Quality pass rate: <strong>{scorecards.quality_pass_rate:.0%}</strong> |
        Avg duration: <strong>{_duration_label(scorecards.avg_duration_ms)}</strong>
      </p>
      <table>
        <thead>
          <tr>
            <th>Run</th><th>Status</th><th>Topic</th><th>Pass</th><th>Grounded</th>
            <th>Source quality</th><th>Duration</th><th>Sources</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _scorecard_html(scorecard: RunScorecard) -> str:
    warnings = "".join(f"<li>{escape(warning)}</li>" for warning in scorecard.warnings)
    return f"""
      <p><a href="/runs/{escape(scorecard.run_id)}/scorecard">Scorecard JSON</a></p>
      <div class="metrics">
        <div><strong>{_pass_label(scorecard.overall_pass)}</strong><span>Overall</span></div>
        <div><strong>{_optional_bool(scorecard.quality_pass)}</strong><span>Quality</span></div>
        <div>
          <strong>{_optional_bool(scorecard.latency_slo_pass)}</strong>
          <span>Latency SLO</span>
        </div>
        <div><strong>{_pass_label(scorecard.sources_slo_pass)}</strong><span>Source SLO</span></div>
        <div><strong>{_duration_label(scorecard.total_duration_ms)}</strong><span>Total</span></div>
        <div><strong>{scorecard.source_count}</strong><span>Sources</span></div>
      </div>
      <table>
        <thead><tr><th>Score</th><th>Value</th></tr></thead>
        <tbody>
          <tr><td>Groundedness</td><td>{_optional_score(scorecard.groundedness)}</td></tr>
          <tr><td>Source coverage</td><td>{_optional_score(scorecard.source_coverage)}</td></tr>
          <tr><td>Source quality</td><td>{_optional_score(scorecard.source_quality)}</td></tr>
          <tr><td>Career relevance</td><td>{_optional_score(scorecard.career_relevance)}</td></tr>
          <tr><td>Technical depth</td><td>{_optional_score(scorecard.technical_depth)}</td></tr>
        </tbody>
      </table>
      <ul>{warnings}</ul>
    """


def _cost_reports_html(cost_reports: CostReportListResponse) -> str:
    if not cost_reports.items:
        return "<p>No cost reports recorded.</p>"
    rows = "".join(
        f"""
        <tr>
          <td><a href="/dashboard/runs/{escape(item.run_id)}">{escape(item.run_id)}</a></td>
          <td>{escape(item.status.value)}</td>
          <td>{escape(item.topic)}</td>
          <td>{_pass_label(item.budget_pass)}</td>
          <td>{item.estimated_total_tokens}</td>
          <td>{item.token_budget}</td>
        </tr>
        """
        for item in cost_reports.items
    )
    return f"""
      <p>
        <a href="/cost-reports">Cost reports JSON</a> |
        Budget pass rate: <strong>{cost_reports.budget_pass_rate:.0%}</strong> |
        Estimated tokens: <strong>{cost_reports.estimated_total_tokens}</strong>
      </p>
      <table>
        <thead>
          <tr>
            <th>Run</th><th>Status</th><th>Topic</th><th>Budget</th>
            <th>Est tokens</th><th>Budget tokens</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _cost_report_html(report: RunCostReport) -> str:
    warnings = "".join(f"<li>{escape(warning)}</li>" for warning in report.warnings)
    return f"""
      <p><a href="/runs/{escape(report.run_id)}/cost-report">Cost report JSON</a></p>
      <div class="metrics">
        <div><strong>{_pass_label(report.budget_pass)}</strong><span>Budget</span></div>
        <div><strong>{report.estimated_input_tokens}</strong><span>Input tokens</span></div>
        <div><strong>{report.estimated_output_tokens}</strong><span>Output tokens</span></div>
        <div><strong>{report.estimated_total_tokens}</strong><span>Total tokens</span></div>
        <div><strong>{report.token_budget}</strong><span>Budget tokens</span></div>
        <div><strong>{escape(report.model)}</strong><span>Model</span></div>
      </div>
      <ul>{warnings}</ul>
    """


def _incident_reports_html(reports: IncidentReportListResponse) -> str:
    if not reports.items:
        return "<p>No incident reports recorded.</p>"
    rows = "".join(
        f"""
        <tr>
          <td><a href="/dashboard/runs/{escape(item.run_id)}">{escape(item.run_id)}</a></td>
          <td>{escape(item.status.value)}</td>
          <td>{escape(item.severity.value)}</td>
          <td>{_pass_label(not item.requires_action)}</td>
          <td>{escape(item.topic)}</td>
        </tr>
        """
        for item in reports.items
    )
    return f"""
      <p>
        <a href="/incident-reports">Incident reports JSON</a> |
        Action required: <strong>{reports.action_required}</strong>
      </p>
      <table>
        <thead>
          <tr><th>Run</th><th>Status</th><th>Severity</th><th>Healthy</th><th>Topic</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _incident_report_html(report: RunIncidentReport) -> str:
    rows = "".join(
        f"""
        <tr>
          <td>{escape(signal.severity.value)}</td>
          <td>{escape(signal.category)}</td>
          <td>{escape(signal.message)}</td>
          <td>{escape(signal.artifact or "n/a")}</td>
        </tr>
        """
        for signal in report.signals
    )
    return f"""
      <p><a href="/runs/{escape(report.run_id)}/incident-report">Incident report JSON</a></p>
      <p>
        Severity: <strong>{escape(report.severity.value)}</strong> |
        Requires action: <strong>{str(report.requires_action).lower()}</strong>
      </p>
      <table>
        <thead><tr><th>Severity</th><th>Category</th><th>Message</th><th>Artifact</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _generation_receipt_html(
    run_id: str,
    receipt: GenerationReceipt | None,
) -> str:
    if receipt is None:
        return "<p>No generation receipt recorded.</p>"
    error = receipt.error or "none"
    return f"""
      <p>
        <a href="/runs/{escape(run_id)}/generation-receipt">Generation receipt JSON</a>
      </p>
      <div class="metrics">
        <div><strong>{escape(receipt.provider)}</strong><span>Provider</span></div>
        <div><strong>{escape(receipt.model)}</strong><span>Model</span></div>
        <div><strong>{escape(receipt.status)}</strong><span>Status</span></div>
        <div><strong>{receipt.attempts}</strong><span>Attempts</span></div>
        <div><strong>{_pass_label(not receipt.fallback_used)}</strong><span>No fallback</span></div>
        <div><strong>{receipt.total_tokens or "n/a"}</strong><span>Total tokens</span></div>
      </div>
      <p>Error: {escape(error)}</p>
    """


def _audit_log_html(events: list[AuditEvent]) -> str:
    if not events:
        return "<p>No audit events recorded.</p>"
    rows = "".join(
        f"""
        <tr>
          <td>{escape(event.action)}</td>
          <td>{escape(event.actor)}</td>
          <td>{escape(event.previous_status.value if event.previous_status else "n/a")}</td>
          <td>{escape(event.new_status.value if event.new_status else "n/a")}</td>
          <td>{escape(event.occurred_at.isoformat())}</td>
        </tr>
        """
        for event in events
    )
    return f"""
      <p><a href="/runs/{escape(events[0].run_id)}/audit-log">Audit JSON</a></p>
      <table>
        <thead>
          <tr><th>Action</th><th>Actor</th><th>From</th><th>To</th><th>At</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _notification_log_html(deliveries: list[NotificationDelivery]) -> str:
    if not deliveries:
        return "<p>No notification deliveries recorded.</p>"
    rows = "".join(
        f"""
        <tr>
          <td>{escape(delivery.action)}</td>
          <td>{escape(delivery.provider)}</td>
          <td>{escape(delivery.status)}</td>
          <td>{escape(str(delivery.status_code or "n/a"))}</td>
          <td>{escape(delivery.endpoint or "local")}</td>
          <td>{escape(delivery.delivered_at.isoformat())}</td>
        </tr>
        """
        for delivery in deliveries
    )
    return f"""
      <p><a href="/runs/{escape(deliveries[0].run_id)}/notifications">Notifications JSON</a></p>
      <table>
        <thead>
          <tr><th>Action</th><th>Provider</th><th>Status</th><th>HTTP</th><th>Endpoint</th><th>At</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    """


def _source_review_rows(research_json: str) -> str:
    data = json.loads(research_json)
    rows: list[str] = []
    for source in data.get("sources", []):
        title = escape(str(source.get("title", "Untitled source")))
        url = source.get("url")
        source_label = f'<a href="{escape(str(url))}">{title}</a>' if url else title
        status = escape(str(source.get("extraction_status", "unknown")))
        quality = float(source.get("extraction_quality", 0))
        summary = escape(str(source.get("summary", ""))[:260])
        rows.append(
            f"""
            <tr>
              <td>{source_label}</td>
              <td>{status}</td>
              <td>{quality:.2f}</td>
              <td>{summary}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def _source_review_table_html(
    run_id: str,
    research_json: str,
    reviews: list[SourceReviewRecord],
    api_key: str = "",
) -> str:
    data = json.loads(research_json)
    review_by_key = {review.source_key: review for review in reviews}
    rows: list[str] = []
    for source in data.get("sources", []):
        title = escape(str(source.get("title", "Untitled source")))
        url = source.get("url")
        canonical_url = str(source.get("canonical_url") or url or title).strip()
        source_key = canonical_url.casefold()
        action_url = (
            f"/dashboard/runs/{escape(run_id)}/source-reviews{_api_key_query(api_key)}"
        )
        source_label = f'<a href="{escape(str(url))}">{title}</a>' if url else title
        status = escape(str(source.get("extraction_status", "unknown")))
        quality = float(source.get("extraction_quality", 0))
        summary = escape(str(source.get("summary", ""))[:220])
        review = review_by_key.get(source_key)
        decision = review.decision.value if review else "unreviewed"
        notes = review.notes if review else ""
        rows.append(
            f"""
            <tr>
              <td>{source_label}</td>
              <td>{status}</td>
              <td>{quality:.2f}</td>
              <td>{escape(decision)}</td>
              <td>{summary}</td>
              <td>
                <form method="post" action="{action_url}">
                  <input type="hidden" name="source_key" value="{escape(source_key)}">
                  <select name="decision">
                    <option value="include">Include</option>
                    <option value="exclude">Exclude</option>
                    <option value="needs_review">Needs review</option>
                  </select>
                  <input name="reviewer" placeholder="Reviewer" value="operator">
                  <input name="notes" placeholder="Notes" value="{escape(notes)}">
                  <button type="submit">Save</button>
                </form>
              </td>
            </tr>
            """
        )
    if not rows:
        return "<p>No sources recorded.</p>"
    return f"""
      <p><a href="/runs/{escape(run_id)}/source-reviews">Source review JSON</a></p>
      <table>
        <thead>
          <tr>
            <th>Source</th>
            <th>Status</th>
            <th>Quality</th>
            <th>Decision</th>
            <th>Summary</th>
            <th>Review</th>
          </tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    """


def _research_provider_metadata_html(research_json: str) -> str:
    data = json.loads(research_json)
    metadata = data.get("provider_metadata")
    if not isinstance(metadata, dict) or not metadata:
        return "<p>No provider metadata recorded for this run.</p>"
    provider = escape(str(metadata.get("provider", "unknown")))
    planned_queries = metadata.get("planned_queries")
    selected_urls = metadata.get("selected_urls")
    project_intelligence = metadata.get("project_intelligence")
    summary_items = [
        ("Provider", provider),
        ("Results", escape(str(metadata.get("result_count", "n/a")))),
        ("Selected", escape(str(metadata.get("selected_count", "n/a")))),
        ("Sources", escape(str(metadata.get("source_count", "n/a")))),
    ]
    summary = "".join(
        f"<div><strong>{value}</strong><span>{escape(label)}</span></div>"
        for label, value in summary_items
        if value != "n/a"
    )
    sections = [
        f'<div class="metrics">{summary}</div>' if summary else "",
    ]
    if isinstance(planned_queries, list) and planned_queries:
        sections.append(
            "<h4>Query Plan</h4><ul>"
            + "".join(f"<li>{escape(str(query))}</li>" for query in planned_queries)
            + "</ul>"
        )
    if isinstance(selected_urls, list) and selected_urls:
        sections.append(
            "<h4>Selected URLs</h4><ul>"
            + "".join(
                f'<li><a href="{escape(str(url))}">{escape(str(url))}</a></li>'
                for url in selected_urls
            )
            + "</ul>"
        )
    if isinstance(project_intelligence, list) and project_intelligence:
        rows = []
        for item in project_intelligence:
            if not isinstance(item, dict):
                continue
            signals = item.get("maturity_signals")
            signal_text = (
                ", ".join(str(signal) for signal in signals)
                if isinstance(signals, list)
                else ""
            )
            rows.append(
                f"""
                <tr>
                  <td>{escape(str(item.get("repository", "unknown")))}</td>
                  <td>{escape(str(item.get("source_count", "0")))}</td>
                  <td>{escape("yes" if item.get("has_readme") else "no")}</td>
                  <td>{escape("yes" if item.get("has_activity") else "no")}</td>
                  <td>{escape(signal_text or "No maturity signals recorded.")}</td>
                </tr>
                """
            )
        if rows:
            sections.append(
                """
                <h4>Project Intelligence</h4>
                <table>
                  <thead>
                    <tr><th>Repository</th><th>Sources</th><th>README</th><th>Activity</th><th>Signals</th></tr>
                  </thead>
                  <tbody>
                """
                + "\n".join(rows)
                + "</tbody></table>"
            )
    return "\n".join(section for section in sections if section)


def _source_audit_html(run_id: str, source_audit_json: str) -> str:
    report = SourceAuditReport.model_validate_json(source_audit_json)
    return f"""
      <p><a href="/runs/{escape(run_id)}/source-audit">Source audit JSON</a></p>
      <div class="metrics">
        <div><strong>{report.average_score:.2f}</strong><span>Avg source score</span></div>
        <div><strong>{report.strong_count}</strong><span>Strong</span></div>
        <div><strong>{report.review_count}</strong><span>Needs review</span></div>
        <div><strong>{report.failed_count}</strong><span>Failed</span></div>
      </div>
    """


def _timeline_rows(metrics: RunMetrics) -> str:
    rows: list[str] = []
    for step in metrics.step_metrics:
        fields = escape(json.dumps(step.fields, ensure_ascii=False))
        rows.append(
            f"""
            <tr>
              <td>{escape(step.step)}</td>
              <td>{escape(step.status)}</td>
              <td>{_duration_label(step.duration_ms)}</td>
              <td><code>{fields}</code></td>
            </tr>
            """
        )
    return "\n".join(rows)


def _avg_duration(metrics: list[RunMetrics | None]) -> str:
    durations = [
        item.total_duration_ms
        for item in metrics
        if item is not None and item.total_duration_ms is not None
    ]
    if not durations:
        return "n/a"
    return _duration_label(int(sum(durations) / len(durations)))


def _duration_label(duration_ms: int | None) -> str:
    if duration_ms is None:
        return "n/a"
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    return f"{duration_ms / 1000:.2f}s"


def _optional_score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _optional_bool(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return _pass_label(value)


def _pass_label(value: bool) -> str:
    return "pass" if value else "fail"


def _publish_plan_html(plan: PublishPlan) -> str:
    provider = escape(plan.provider)
    target_url = escape(plan.target_url)
    ready = escape(str(plan.ready).lower())
    warnings = plan.warnings
    items = plan.items
    warning_html = "".join(f"<li>{escape(str(warning))}</li>" for warning in warnings)
    item_rows = "".join(
        f"""
        <tr>
          <td>{escape(item.action)}</td>
          <td>{escape(item.path)}</td>
          <td>{escape(str(item.exists).lower())}</td>
          <td>{escape(item.description)}</td>
        </tr>
        """
        for item in items
    )
    metadata_html = ""
    if plan.metadata:
        metadata_html = (
            "<h4>Publish Metadata</h4>"
            f"<pre>{escape(json.dumps(plan.metadata, ensure_ascii=False, indent=2))}</pre>"
        )
    return f"""
      <p>Provider: <strong>{provider}</strong> | Ready: <strong>{ready}</strong></p>
      <p>Target: {target_url}</p>
      <ul>{warning_html}</ul>
      {metadata_html}
      <table>
        <thead><tr><th>Action</th><th>Path</th><th>Exists</th><th>Description</th></tr></thead>
        <tbody>{item_rows}</tbody>
      </table>
    """
