from __future__ import annotations

import json
from html import escape
from urllib.parse import urlencode

from contentops_core.jobs import JobExecutionReport, WorkerJobCatalogItem
from contentops_core.models import (
    ApprovalRecord,
    ArtifactMirrorRecord,
    AuditEvent,
    AuditEventListResponse,
    CostReportListResponse,
    DeploymentManifest,
    GenerationReceipt,
    IncidentReportListResponse,
    NotificationDelivery,
    OperationsSummary,
    PublishedContentListResponse,
    PublishPlan,
    PublishReceipt,
    PublishVerificationReport,
    ReleaseEvidenceBundle,
    RetentionReport,
    RunComparison,
    RunCostReport,
    RunIncidentReport,
    RunMetrics,
    RunScorecard,
    ScorecardListResponse,
    SourceAuditReport,
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
        </a>
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


def _job_execution_detail_html(report: JobExecutionReport) -> str:
    rows = "".join(
        f"""
        <tr>
          <td>{escape(result.job_name)}</td>
          <td>{_job_intent_label(result.publish)}</td>
          <td>{escape(str(result.status))}</td>
          <td>{_run_link(result.run_id)}</td>
          <td>{escape(result.topic)}</td>
          <td>{_source_urls_html(result.source_urls)}</td>
          <td>{escape(", ".join(result.tags) or "none")}</td>
          <td>{escape(_metadata_label(result.metadata))}</td>
          <td>{escape(result.error or "")}</td>
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
      <div class="metrics">
        <div><strong>{report.total}</strong><span>Total jobs</span></div>
        <div><strong>{report.succeeded}</strong><span>Succeeded</span></div>
        <div><strong>{report.failed}</strong><span>Failed</span></div>
        <div><strong>{str(report.dry_run).lower()}</strong><span>Dry run</span></div>
        <div><strong>{_duration_label(report.duration_ms)}</strong><span>Duration</span></div>
        <div><strong>{escape(report.started_at.isoformat())}</strong><span>Started</span></div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Job</th><th>Intent</th><th>Status</th><th>Run</th><th>Topic</th>
            <th>Sources</th><th>Tags</th><th>Metadata</th><th>Error</th>
          </tr>
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
    invalid_count = sum(1 for item in items if not item.valid)
    job_count = sum(item.total for item in items)
    file_rows = "".join(
        f"""
        <tr>
          <td>{escape(item.path)}</td>
          <td>{escape(item.name)}</td>
          <td>{str(item.valid).lower()}</td>
          <td>{item.total}</td>
          <td>{item.publish_count}</td>
          <td>{item.review_count}</td>
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
        <div><strong>{invalid_count}</strong><span>Invalid files</span></div>
      </div>
      <h3>Planned Jobs</h3>
      <table>
        <thead>
          <tr>
            <th>File</th><th>Job</th><th>Intent</th><th>Topic</th>
            <th>Sources</th><th>Tags</th><th>Metadata</th>
          </tr>
        </thead>
        <tbody>{job_rows}</tbody>
      </table>
      <h3>Job Files</h3>
      <table>
        <thead>
          <tr>
            <th>File</th><th>Name</th><th>Valid</th><th>Jobs</th>
            <th>Publish</th><th>Review</th><th>Tags</th><th>Topics</th>
          </tr>
        </thead>
        <tbody>{file_rows}</tbody>
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
          </tr>
        """
    return "".join(
        f"""
        <tr>
          <td>{escape(item.path)}</td>
          <td>{escape(job.name)}</td>
          <td>{_job_intent_label(job.publish)}</td>
          <td>{escape(job.topic)}</td>
          <td>{_source_urls_html(job.source_urls)}</td>
          <td>{escape(", ".join(job.tags) or "none")}</td>
          <td>{escape(_metadata_label(job.metadata))}</td>
        </tr>
        """
        for job in item.jobs
    )


def _job_intent_label(publish: bool) -> str:
    css_class = "publish" if publish else "review"
    label = "publish if ready" if publish else "review first"
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


def _system_status_html(status: SystemStatus, manifest: DeploymentManifest) -> str:
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
        <a href="/deployment-manifest">Deployment manifest JSON</a>
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


def _release_evidence_html(bundle: ReleaseEvidenceBundle) -> str:
    summary = bundle.summary
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
        <div><strong>{escape(summary.doctor_status)}</strong><span>Doctor status</span></div>
        <div><strong>{escape(summary.git_sha or "n/a")}</strong><span>Git SHA</span></div>
        <div><strong>{len(summary.artifact_files)}</strong><span>Evidence files</span></div>
        <div><strong>{escape(summary.generated_at.isoformat())}</strong><span>Generated</span></div>
      </div>
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


def _retention_report_html(report: RetentionReport) -> str:
    if not report.candidates:
        return f"""
          <p>
            <a href="/retention-report">Retention report JSON</a> |
            Scanned <strong>{report.total_runs_scanned}</strong> runs |
            Total size: <strong>{report.total_size_bytes}</strong> bytes |
            No candidates older than <strong>{report.retention_days}</strong> day(s).
          </p>
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
        Candidates: <strong>{report.candidate_count}</strong> |
        Candidate size: <strong>{report.candidate_size_bytes}</strong> bytes
      </p>
      <table>
        <thead>
          <tr><th>Run</th><th>Status</th><th>Artifacts</th><th>Bytes</th><th>Updated</th></tr>
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
      <p><a href="/content">Content catalog JSON</a></p>
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
    return f"""
      <p>Provider: <strong>{provider}</strong> | Ready: <strong>{ready}</strong></p>
      <p>Target: {target_url}</p>
      <ul>{warning_html}</ul>
      <table>
        <thead><tr><th>Action</th><th>Path</th><th>Exists</th><th>Description</th></tr></thead>
        <tbody>{item_rows}</tbody>
      </table>
    """
