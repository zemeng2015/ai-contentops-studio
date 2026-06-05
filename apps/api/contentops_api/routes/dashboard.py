from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from html import escape
from pathlib import Path
from typing import Annotated

from contentops_core.config_audit import config_audit
from contentops_core.diagnostics import (
    deployment_manifest,
    list_integration_smoke_reports,
    system_status,
)
from contentops_core.jobs import (
    JobExecutionAlertReport,
    JobExecutionReport,
    JobExecutionTrendReport,
    JobRunner,
    archive_scheduled_workflow_review_package,
    content_calendar_brief,
    content_calendar_lineage,
    content_calendar_run_request,
    get_job_execution_report,
    get_scheduled_workflow_review_package,
    job_execution_alert_notification_log,
    job_execution_alert_report,
    job_execution_dir,
    job_execution_run_ids,
    job_execution_trends,
    job_recovery_lineage,
    job_recovery_plan,
    list_job_execution_reports,
    list_scheduled_workflow_review_packages,
    list_worker_job_catalog,
    notify_job_execution_alert,
    notify_worker_delivery_summary,
    worker_delivery_summary_notification_log,
    worker_job_readiness,
)
from contentops_core.models import (
    ArtifactMirrorRecord,
    ReleaseApprovalDecision,
    ReleaseApprovalRequest,
    ReleaseGateReport,
    RunMetrics,
    RunRequest,
    RunStatus,
    SourceReviewDecision,
    SourceReviewRequest,
)
from contentops_core.operations_console import build_operations_console
from contentops_core.ops_brief import (
    build_ops_brief,
    notify_ops_brief,
    ops_brief_notification_log,
)
from contentops_core.pipeline import ContentOpsPipeline
from contentops_core.release_approvals import approve_release, list_release_approvals
from contentops_core.release_evidence import build_release_evidence
from contentops_core.release_gate import list_release_gate_reports, release_gate
from contentops_core.repository import RunRepository
from contentops_core.review import ReviewService
from contentops_core.settings import Settings
from contentops_publishing.publish_index import write_distribution_assets
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from contentops_api.views import (
    _api_key_hidden,
    _api_key_query,
    _approval_html,
    _audit_events_html,
    _audit_log_html,
    _avg_duration,
    _comparison_html,
    _config_audit_html,
    _content_calendar_brief_html,
    _content_calendar_lineage_html,
    _cost_report_html,
    _cost_reports_html,
    _duration_label,
    _generation_receipt_html,
    _incident_report_html,
    _incident_reports_html,
    _integration_smoke_runs_html,
    _job_execution_alert_deliveries_html,
    _job_execution_alerts_html,
    _job_execution_detail_html,
    _job_execution_trends_html,
    _job_executions_html,
    _job_recovery_lineage_html,
    _notification_log_html,
    _operations_summary_html,
    _ops_brief_deliveries_html,
    _ops_brief_html,
    _ops_trends_html,
    _page,
    _pagination_html,
    _publish_plan_html,
    _publish_receipt_html,
    _publish_verification_html,
    _published_content_html,
    _release_approvals_html,
    _release_evidence_html,
    _release_gate_history_html,
    _release_gate_html,
    _research_provider_metadata_html,
    _retention_report_html,
    _s3_mirror_log_html,
    _scheduled_review_packages_html,
    _scorecard_html,
    _scorecards_html,
    _source_audit_html,
    _source_review_table_html,
    _status_options,
    _system_status_html,
    _timeline_rows,
    _worker_delivery_summary_deliveries_html,
    _worker_job_readiness_html,
    _worker_jobs_html,
    _workflow_context_html,
)

ReadAccessDependency = Callable[[Request], Awaitable[None]]
OperatorDependency = Callable[[Request], Awaitable[None]]
StatusParser = Callable[[str], RunStatus | None]


def build_dashboard_router(
    *,
    settings: Settings,
    pipeline: ContentOpsPipeline,
    repository: RunRepository,
    review_service: ReviewService,
    require_read_access: ReadAccessDependency,
    require_operator: OperatorDependency,
    parse_status_filter: StatusParser,
) -> APIRouter:
    router = APIRouter()

    def _safe_metrics(run_id: str) -> RunMetrics | None:
        try:
            return review_service.metrics(run_id)
        except FileNotFoundError:
            return None

    @router.get("/", response_class=HTMLResponse, dependencies=[Depends(require_read_access)])
    @router.get(
        "/dashboard",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard(
        q: str = Query(default=""),
        status: str = Query(default=""),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        api_key: str = Query(default=""),
    ) -> HTMLResponse:
        status_filter = parse_status_filter(status)
        runs = repository.list(limit=limit, offset=offset, status=status_filter, query=q)
        total = repository.count(status=status_filter, query=q)
        job_executions = list_job_execution_reports(
            job_execution_dir(settings.artifact_root),
            limit=5,
        )
        scheduled_review_packages = list_scheduled_workflow_review_packages(
            settings.artifact_root,
            limit=5,
        )
        worker_jobs = list_worker_job_catalog(settings.pipeline_dir)
        calendar_brief = content_calendar_brief(
            settings.pipeline_dir,
            job_execution_dir(settings.artifact_root),
            limit=5,
        )
        published_content = review_service.published_content(limit=5)
        scorecards = review_service.scorecards(limit=5)
        cost_reports = review_service.cost_reports(limit=5)
        incident_reports = review_service.incident_reports(limit=5)
        audit_events = review_service.audit_events(limit=5)
        retention_report = review_service.retention_report()
        retention_archives = review_service.retention_archives(limit=5)
        smoke_runs = list_integration_smoke_reports(settings.artifact_root, limit=5)
        retention_archive_action = f"/dashboard/retention/archive{_api_key_query(api_key)}"
        operations_summary = review_service.operations_summary()
        ops_brief = build_ops_brief(
            settings=settings,
            review_service=review_service,
            window_size=100,
        )
        metrics = [_safe_metrics(run.id) for run in runs]
        completed = sum(
            1 for item in metrics if item is not None and item.total_duration_ms is not None
        )
        published = sum(1 for run in runs if run.status.value == "published")
        needs_review = repository.count(status=RunStatus.NEEDS_REVIEW)
        approved = repository.count(status=RunStatus.APPROVED)
        avg_duration = _avg_duration(metrics)
        pagination = _pagination_html(q, status, limit, offset, total, api_key)
        rows = "\n".join(
            f"""
            <tr>
              <td><input type="checkbox" name="run_ids" value="{escape(run.id)}"></td>
              <td><a href="/dashboard/runs/{escape(run.id)}">{escape(run.id)}</a></td>
              <td>{escape(run.status.value)}</td>
              <td>{escape(run.topic)}</td>
              <td>{escape(run.updated_at.isoformat())}</td>
            </tr>
            """
            for run in runs
        )
        return HTMLResponse(
            _page(
                "AI ContentOps Studio",
                f"""
                <section class="hero">
                  <p>
                    Review generated research, drafts, evaluation reports, and publishing state.
                  </p>
                  <div class="metrics">
                    <div><strong>{total}</strong><span>Matching runs</span></div>
                    <div><strong>{needs_review}</strong><span>Needs review</span></div>
                    <div><strong>{approved}</strong><span>Approved</span></div>
                    <div><strong>{published}</strong><span>Published on page</span></div>
                    <div><strong>{completed}</strong><span>Traced</span></div>
                    <div><strong>{avg_duration}</strong><span>Avg duration</span></div>
                  </div>
                  <form method="post" action="/dashboard/runs{_api_key_query(api_key)}">
                    <input name="topic" placeholder="Run topic" required>
                    <textarea
                      name="source_urls"
                      placeholder="Optional source URLs, one per line"
                    ></textarea>
                    <label>
                      <input type="checkbox" name="publish" value="true"> publish if ready
                    </label>
                    <button type="submit">Create run</button>
                  </form>
                </section>
                <section class="hero compact">
                  <form method="get" action="/dashboard">
                    <input name="q" placeholder="Filter by topic or run id" value="{escape(q)}">
                    <select name="status">
                      {_status_options(status)}
                    </select>
                    <input type="hidden" name="limit" value="{limit}">
                    {_api_key_hidden(api_key)}
                    <button type="submit">Filter runs</button>
                  </form>
                </section>
                <form method="post" action="/dashboard/runs/batch-approve{_api_key_query(api_key)}">
                  <div class="bulk-actions">
                    <input name="reviewer" placeholder="Reviewer" value="operator">
                    <input name="notes" placeholder="Batch review notes">
                    <button type="submit">Approve selected</button>
                    <button
                      type="submit"
                      formaction="/dashboard/runs/batch-reject{_api_key_query(api_key)}"
                    >Reject selected</button>
                  </div>
                  <table>
                    <thead>
                      <tr>
                        <th>Select</th><th>Run</th><th>Status</th><th>Topic</th><th>Updated</th>
                      </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                  </table>
                </form>
                {pagination}
                <section class="hero compact">
                  <h2>Ops Brief</h2>
                  <p>Daily operational risks, provider health, and recommended actions.</p>
                  <p><a href="/dashboard/ops-brief">Open ops brief</a></p>
                  {_ops_brief_html(ops_brief)}
                </section>
                <section class="hero compact">
                  <h2>Operations Summary</h2>
                  <p>
                    Portfolio-wide run health, queue depth, incident severity, and cost posture.
                  </p>
                  <p><a href="/dashboard/operations">Open operations console</a></p>
                  <p><a href="/dashboard/ops-trends">Open operations trends</a></p>
                  {_operations_summary_html(operations_summary)}
                </section>
                <section class="hero compact">
                  <h2>Integration Smoke</h2>
                  <p>
                    Recent live provider validation reports for feed, search, OpenAI, and
                    homepage paths.
                  </p>
                  <p><a href="/dashboard/integration-smoke">Open integration smoke history</a></p>
                  {_integration_smoke_runs_html(smoke_runs)}
                </section>
                <section class="hero compact">
                  <h2>Artifact Retention</h2>
                  <p>
                    Storage hygiene report for old run artifacts that can be archived or pruned.
                  </p>
                  <p><a href="/dashboard/retention">Open retention lifecycle</a></p>
                  <form method="post" action="{retention_archive_action}">
                    <input name="days" value="90" placeholder="Retention days">
                    <input name="limit" value="100" placeholder="Scan limit">
                    <button type="submit">Create archive</button>
                  </form>
                  {_retention_report_html(retention_report, retention_archives)}
                </section>
                <section class="hero compact">
                  <h2>Audit Events</h2>
                  <p>Recent approve, publish, reject, and rollback events across all runs.</p>
                  {_audit_events_html(audit_events)}
                </section>
                <section class="hero compact">
                  <h2>Worker Job Catalog</h2>
                  <p>Planned YAML content calendars and publish/review intent before execution.</p>
                  <p><a href="/dashboard/worker-jobs">Open content calendar</a></p>
                  <div class="metrics">
                    <div><strong>{escape(calendar_brief.status)}</strong><span>Calendar</span></div>
                    <div>
                      <strong>{calendar_brief.planned_jobs}</strong><span>Planned jobs</span>
                    </div>
                    <div>
                      <strong>{calendar_brief.publish_intent}</strong><span>Publish intent</span>
                    </div>
                    <div>
                      <strong>{calendar_brief.recent_success_rate:.0%}</strong>
                      <span>Worker success</span>
                    </div>
                  </div>
                  {_worker_jobs_html(worker_jobs.items)}
                </section>
                <section class="hero compact">
                  <h2>Worker Executions</h2>
                  <p>Recent scheduled job receipts for automation audit and incident review.</p>
                  <p><a href="/dashboard/job-execution-trends">Open worker execution trends</a></p>
                  {_job_executions_html(job_executions.items)}
                </section>
                <section class="hero compact">
                  <h2>Scheduled Review Packages</h2>
                  <p>
                    Recent review manifests, verification results, and downloadable evidence ZIPs.
                  </p>
                  <p><a href="/dashboard/scheduled-reviews">Open scheduled review packages</a></p>
                  {_scheduled_review_packages_html(scheduled_review_packages.items, api_key)}
                </section>
                <section class="hero compact">
                  <h2>Published Content</h2>
                  <p>Operational catalog of shipped articles and their evaluation scores.</p>
                  <form method="post" action="/dashboard/content-assets{_api_key_query(api_key)}">
                    {_api_key_hidden(api_key)}
                    <input name="title" value="AI ContentOps Studio" placeholder="Feed title">
                    <input
                      name="description"
                      value="Reviewed AI and technical content."
                      placeholder="Feed description"
                    >
                    <button type="submit">Generate distribution assets</button>
                  </form>
                  {_published_content_html(published_content)}
                </section>
                <section class="hero compact">
                  <h2>Quality Scorecards</h2>
                  <p>Operational SLO and quality view for recent AI content runs.</p>
                  {_scorecards_html(scorecards)}
                </section>
                <section class="hero compact">
                  <h2>Token Budgets</h2>
                  <p>Estimated token usage for recent runs, derived from persisted artifacts.</p>
                  {_cost_reports_html(cost_reports)}
                </section>
                <section class="hero compact">
                  <h2>Incident Reports</h2>
                  <p>Recent run health signals for failed, drifting, or degraded content runs.</p>
                  {_incident_reports_html(incident_reports)}
                </section>
                """,
            )
        )


    @router.get(
        "/dashboard/scheduled-reviews",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard_scheduled_reviews(
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        api_key: str = Query(default=""),
    ) -> HTMLResponse:
        packages = list_scheduled_workflow_review_packages(
            settings.artifact_root,
            limit=limit,
            offset=offset,
        )
        archive_ready_count = sum(1 for item in packages.items if item.archive_exists)
        verified_count = sum(
            1 for item in packages.items if item.verification_status == "pass"
        )
        return HTMLResponse(
            _page(
                "Scheduled Review Packages",
                f"""
                <section class="hero compact">
                  <p><a href="/dashboard{_api_key_query(api_key)}">Back to dashboard</a></p>
                  <p>
                    Review package manifests, verification status, and archive ZIPs generated by
                    scheduled ContentOps workflows.
                  </p>
                  <div class="metrics">
                    <div><strong>{packages.total}</strong><span>Total packages</span></div>
                    <div><strong>{len(packages.items)}</strong><span>Shown</span></div>
                    <div><strong>{archive_ready_count}</strong><span>Archives ready</span></div>
                    <div><strong>{verified_count}</strong><span>Verified</span></div>
                  </div>
                  {_scheduled_review_packages_html(packages.items, api_key)}
                </section>
                """,
            )
        )

    @router.post(
        "/dashboard/scheduled-reviews/{package_id}/archive",
        dependencies=[Depends(require_operator)],
    )
    def dashboard_archive_scheduled_review(
        package_id: str,
        api_key: str = Query(default=""),
    ) -> RedirectResponse:
        try:
            item = get_scheduled_workflow_review_package(settings.artifact_root, package_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        s3_bucket: str | None = None
        if settings.artifact_store_provider == "s3":
            if not settings.artifact_s3_bucket:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "CONTENTOPS_ARTIFACT_S3_BUCKET is required for S3 scheduled "
                        "review mirroring."
                    ),
                )
            s3_bucket = settings.artifact_s3_bucket
        try:
            archive_scheduled_workflow_review_package(
                Path(item.manifest_path),
                s3_bucket=s3_bucket,
                s3_prefix=settings.artifact_s3_prefix,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(
            f"/dashboard/scheduled-reviews{_api_key_query(api_key)}",
            status_code=303,
        )


    @router.post(
        "/dashboard/content-assets",
        dependencies=[Depends(require_operator)],
    )
    def dashboard_generate_content_assets(
        title: Annotated[str, Form()] = "AI ContentOps Studio",
        description: Annotated[str, Form()] = "Reviewed AI and technical content.",
        api_key: str = Query(default=""),
    ) -> RedirectResponse:
        target_dir = _publisher_target_dir(settings)
        index_path = target_dir / "contentops-publish-index.json"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail=f"Publish index not found: {index_path}")
        write_distribution_assets(
            index_path,
            target_dir,
            channel_title=title,
            channel_description=description,
            channel_url=_publisher_public_url(settings),
        )
        return RedirectResponse(f"/dashboard{_api_key_query(api_key)}", status_code=303)


    @router.post(
        "/dashboard/retention-archives",
        dependencies=[Depends(require_operator)],
    )
    def dashboard_create_retention_archive(
        days: Annotated[int, Form()] = 90,
        limit: Annotated[int, Form()] = 100,
        api_key: str = Query(default=""),
    ) -> RedirectResponse:
        review_service.retention_archive(retention_days=days, limit=limit)
        return RedirectResponse(f"/dashboard{_api_key_query(api_key)}", status_code=303)


    @router.get(
        "/dashboard/operations",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard_operations(
        days: int = Query(default=14, ge=1, le=90),
        window_size: int = Query(default=100, ge=1, le=500),
        api_key: str = Query(default=""),
    ) -> HTMLResponse:
        report = build_operations_console(
            settings=settings,
            repository=repository,
            review_service=review_service,
            days=days,
            window_size=window_size,
        )
        return HTMLResponse(
            _page(
                "Operations Console",
                f"""
                <section class="hero compact">
                  <p><a href="/dashboard{_api_key_query(api_key)}">Back to dashboard</a></p>
                  <h2>Operations Console</h2>
                  <p>
                    One operator view for daily risk, worker automation, release gates,
                    artifact retention, and portfolio health.
                  </p>
                  <div class="metrics">
                    <div>
                      <strong>{escape(report.summary.brief_status)}</strong>
                      <span>Brief status</span>
                    </div>
                    <div>
                      <strong>{report.summary.review_queue_depth}</strong>
                      <span>Review queue</span>
                    </div>
                    <div>
                      <strong>{report.summary.action_required_incidents}</strong>
                      <span>Incidents</span>
                    </div>
                    <div>
                      <strong>{escape(report.summary.release_gate_status)}</strong>
                      <span>Release gate</span>
                    </div>
                    <div>
                      <strong>{escape(report.summary.retention_gate_status)}</strong>
                      <span>Retention gate</span>
                    </div>
                    <div>
                      <strong>{report.summary.worker_success_rate:.0%}</strong>
                      <span>Worker success</span>
                    </div>
                  </div>
                  <p>
                    <a href="/operations-console">Operations console JSON</a> |
                    <a href="/dashboard/ops-brief">Ops brief</a> |
                    <a href="/dashboard/ops-trends">Operations trends</a> |
                    <a href="/dashboard/job-execution-trends">Worker health</a> |
                    <a href="/dashboard/retention">Retention lifecycle</a> |
                    <a href="/dashboard/release-evidence">Release evidence</a> |
                    <a href="/dashboard/system-status">System status</a>
                  </p>
                </section>
                <section class="hero compact">
                  <h2>Operations Summary</h2>
                  {_operations_summary_html(report.operations_summary)}
                </section>
                <section class="hero compact">
                  <h2>Daily Brief</h2>
                  {_ops_brief_html(report.ops_brief)}
                </section>
                <section class="hero compact">
                  <h2>Worker Automation</h2>
                  {_job_execution_trends_html(
                    JobExecutionTrendReport.model_validate(report.worker_execution_trends)
                  )}
                  <h2>Worker Alerts</h2>
                  {_job_execution_alerts_html(
                    JobExecutionAlertReport.model_validate(report.worker_execution_alerts)
                  )}
                </section>
                <section class="hero compact">
                  <h2>Release Gate</h2>
                  {_release_gate_html(ReleaseGateReport.model_validate(report.release_gate))}
                </section>
                <section class="hero compact">
                  <h2>Retention Governance</h2>
                  {_retention_report_html(report.retention_report, report.retention_archives)}
                </section>
                """,
            )
        )


    @router.get(
        "/dashboard/retention",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard_retention(
        days: int = Query(default=90, ge=0, le=3650),
        limit: int = Query(default=100, ge=1, le=1000),
        api_key: str = Query(default=""),
    ) -> HTMLResponse:
        report = review_service.retention_report(retention_days=days, limit=limit)
        archives = review_service.retention_archives(limit=20)
        gate = release_gate(
            settings=settings,
            repository=repository,
            review_service=review_service,
            require_approval=False,
        )
        retention_gate = next(
            check for check in gate.checks if check.name == "retention_archive_governance"
        )
        retention_archive_action = f"/dashboard/retention/archive{_api_key_query(api_key)}"
        return HTMLResponse(
            _page(
                "Retention Lifecycle",
                f"""
                <section class="hero compact">
                  <p><a href="/dashboard{_api_key_query(api_key)}">Back to dashboard</a></p>
                  <h2>Retention Lifecycle</h2>
                  <p>
                    Review old artifact candidates, create non-destructive archives, and confirm
                    release gate governance before any cleanup.
                  </p>
                  <div class="metrics">
                    <div><strong>{report.total_runs_scanned}</strong><span>Runs scanned</span></div>
                    <div>
                      <strong>{report.candidate_count}</strong><span>Archive candidates</span>
                    </div>
                    <div>
                      <strong>{report.candidate_size_bytes}</strong><span>Candidate bytes</span>
                    </div>
                    <div><strong>{archives.total}</strong><span>Archive receipts</span></div>
                    <div>
                      <strong>{escape(retention_gate.status)}</strong><span>Gate status</span>
                    </div>
                  </div>
                  <form method="get" action="/dashboard/retention">
                    <input name="days" value="{days}" placeholder="Retention days">
                    <input name="limit" value="{limit}" placeholder="Scan limit">
                    {_api_key_hidden(api_key)}
                    <button type="submit">Refresh report</button>
                  </form>
                  <form method="post" action="{retention_archive_action}">
                    <input name="days" value="{days}" placeholder="Retention days">
                    <input name="limit" value="{limit}" placeholder="Scan limit">
                    <button type="submit">Create archive</button>
                  </form>
                  <h2>Governance</h2>
                  {_release_gate_html(gate)}
                  <h2>Retention Report</h2>
                  {_retention_report_html(report, archives)}
                </section>
                """,
            )
        )


    @router.post(
        "/dashboard/retention/archive",
        dependencies=[Depends(require_operator)],
    )
    def dashboard_retention_create_archive(
        days: Annotated[int, Form()] = 90,
        limit: Annotated[int, Form()] = 100,
        api_key: str = Query(default=""),
    ) -> RedirectResponse:
        review_service.retention_archive(retention_days=days, limit=limit)
        query = _api_key_query(api_key)
        separator = "&" if query else "?"
        return RedirectResponse(
            f"/dashboard/retention{query}{separator}days={days}&limit={limit}",
            status_code=303,
        )


    @router.get(
        "/dashboard/ops-brief",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard_ops_brief(
        days: int = Query(default=14, ge=1, le=90),
        window_size: int = Query(default=100, ge=1, le=500),
        api_key: str = Query(default=""),
    ) -> HTMLResponse:
        report = build_ops_brief(
            settings=settings,
            review_service=review_service,
            days=days,
            window_size=window_size,
        )
        deliveries = ops_brief_notification_log(settings.artifact_root)
        return HTMLResponse(
            _page(
                "Operations Brief",
                f"""
                <section class="hero compact">
                  <p><a href="/dashboard{_api_key_query(api_key)}">Back to dashboard</a></p>
                  <h2>Daily Operations Brief</h2>
                  <p>
                    Actionable summary of provider health, worker alerts, incidents,
                    quality, budget, and review queue posture.
                  </p>
                  <form method="post" action="/dashboard/ops-brief/notify{_api_key_query(api_key)}">
                    <button type="submit">Notify ops brief</button>
                  </form>
                  {_ops_brief_html(report)}
                  <h2>Notification History</h2>
                  {_ops_brief_deliveries_html(deliveries)}
                </section>
                """,
            )
        )


    @router.post(
        "/dashboard/ops-brief/notify",
        dependencies=[Depends(require_operator)],
    )
    def dashboard_notify_ops_brief(api_key: str = Query(default="")) -> RedirectResponse:
        notify_ops_brief(
            settings=settings,
            review_service=review_service,
            endpoint=settings.notification_webhook_url,
            timeout_seconds=settings.notification_timeout_seconds,
        )
        return RedirectResponse(
            f"/dashboard/ops-brief{_api_key_query(api_key)}",
            status_code=303,
        )


    @router.get(
        "/dashboard/ops-trends",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard_ops_trends(
        days: int = Query(default=14, ge=1, le=90),
        window_size: int = Query(default=500, ge=1, le=1000),
        api_key: str = Query(default=""),
    ) -> HTMLResponse:
        report = review_service.operations_trends(days=days, window_size=window_size)
        return HTMLResponse(
            _page(
                "Operations Trends",
                f"""
                <section class="hero compact">
                  <p><a href="/dashboard{_api_key_query(api_key)}">Back to dashboard</a></p>
                  <h2>Operations Trends</h2>
                  <p>
                    Daily run health, publishing throughput, quality, budget,
                    and incident posture.
                  </p>
                  {_ops_trends_html(report)}
                </section>
                """,
            )
        )


    @router.get(
        "/dashboard/job-execution-trends",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard_job_execution_trends(
        days: int = Query(default=14, ge=1, le=90),
        api_key: str = Query(default=""),
    ) -> HTMLResponse:
        report = job_execution_trends(job_execution_dir(settings.artifact_root), days=days)
        alerts = job_execution_alert_report(job_execution_dir(settings.artifact_root), days=days)
        recovery_lineage = job_recovery_lineage(
            job_execution_dir(settings.artifact_root),
            days=days,
        )
        deliveries = job_execution_alert_notification_log(job_execution_dir(settings.artifact_root))
        summary_deliveries = worker_delivery_summary_notification_log(
            job_execution_dir(settings.artifact_root)
        )
        notify_action = (
            f"/dashboard/job-execution-alerts/notify{_api_key_query(api_key)}"
        )
        return HTMLResponse(
            _page(
                "Worker Execution Trends",
                f"""
                <section class="hero compact">
                  <p><a href="/dashboard{_api_key_query(api_key)}">Back to dashboard</a></p>
                  <h2>Worker Execution Trends</h2>
                  <p>
                    Daily automation execution health, generated runs, publishing,
                    handoff readiness, and action-required posture.
                  </p>
                  <form method="post" action="{notify_action}">
                    {_api_key_hidden(api_key)}
                    <input type="hidden" name="days" value="{days}">
                    <button type="submit">Notify worker alert</button>
                  </form>
                  {_job_execution_alerts_html(alerts)}
                  <h2>Worker Alert Notifications</h2>
                  {_job_execution_alert_deliveries_html(deliveries)}
                  <h2>Delivery Summary Notifications</h2>
                  {_worker_delivery_summary_deliveries_html(summary_deliveries)}
                  <h2>Recovery Lineage</h2>
                  {_job_recovery_lineage_html(recovery_lineage)}
                  {_job_execution_trends_html(report)}
                </section>
                """,
            )
        )

    @router.post(
        "/dashboard/job-execution-alerts/notify",
        dependencies=[Depends(require_operator)],
    )
    def dashboard_notify_job_execution_alerts(
        days: Annotated[int, Form()] = 14,
        api_key: str = Query(default=""),
    ) -> RedirectResponse:
        notify_job_execution_alert(
            job_execution_dir(settings.artifact_root),
            days=days,
            endpoint=settings.notification_webhook_url,
            timeout_seconds=settings.notification_timeout_seconds,
        )
        return RedirectResponse(
            f"/dashboard/job-execution-trends{_api_key_query(api_key)}",
            status_code=303,
        )

    @router.post(
        "/dashboard/job-executions/{execution_id}/delivery-summary/notify",
        dependencies=[Depends(require_operator)],
    )
    def dashboard_notify_worker_delivery_summary(
        execution_id: str,
        api_key: str = Query(default=""),
    ) -> RedirectResponse:
        report = get_job_execution_report(job_execution_dir(settings.artifact_root), execution_id)
        notify_worker_delivery_summary(
            report,
            endpoint=settings.notification_webhook_url,
            timeout_seconds=settings.notification_timeout_seconds,
        )
        return RedirectResponse(
            f"/dashboard/job-executions/{escape(execution_id)}{_api_key_query(api_key)}",
            status_code=303,
        )


    @router.get(
        "/dashboard/worker-jobs",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard_worker_jobs(api_key: str = Query(default="")) -> HTMLResponse:
        worker_jobs = list_worker_job_catalog(settings.pipeline_dir)
        readiness = worker_job_readiness(settings.pipeline_dir)
        calendar_brief = content_calendar_brief(
            settings.pipeline_dir,
            job_execution_dir(settings.artifact_root),
            limit=10,
        )
        calendar_lineage = content_calendar_lineage(
            settings.pipeline_dir,
            repository.list(limit=200),
        )
        return HTMLResponse(
            _page(
                "Content Calendar",
                f"""
                <p><a href="/dashboard{_api_key_query(api_key)}">Back to dashboard</a></p>
                <section class="hero">
                  <h2>Worker Job Catalog</h2>
                  <p>
                    Review scheduled content jobs before automation runs them. GitHub project
                    update jobs should stay in review mode until a human approves the generated
                    article.
                  </p>
                  {_content_calendar_brief_html(calendar_brief, api_key)}
                  {_content_calendar_lineage_html(calendar_lineage)}
                  {_worker_job_readiness_html(readiness)}
                  {_worker_jobs_html(worker_jobs.items)}
                </section>
                """,
            )
        )

    @router.get(
        "/dashboard/system-status",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard_system_status(api_key: str = Query(default="")) -> HTMLResponse:
        status = system_status(settings, repository)
        manifest = deployment_manifest(settings, repository)
        audit = config_audit(settings)
        return HTMLResponse(
            _page(
                "System Status",
                f"""
                <p><a href="/dashboard{_api_key_query(api_key)}">Back to dashboard</a></p>
                <section class="hero">
                  <p>
                    Operator-facing readiness view for provider configuration, storage,
                    database, security, and deployment capabilities.
                  </p>
                  {_config_audit_html(audit)}
                  {_system_status_html(status, manifest)}
                </section>
                """,
            )
        )

    @router.get(
        "/dashboard/release-evidence",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard_release_evidence(
        api_key: str = Query(default=""),
        window_size: int = Query(default=100, ge=1, le=500),
    ) -> HTMLResponse:
        bundle = build_release_evidence(
            settings=settings,
            repository=repository,
            review_service=review_service,
            window_size=window_size,
        )
        gate = release_gate(
            settings=settings,
            repository=repository,
            review_service=review_service,
            window_size=window_size,
        )
        approvals = list_release_approvals(settings.artifact_root, limit=10)
        gate_history = list_release_gate_reports(settings.artifact_root, limit=10)
        return HTMLResponse(
            _page(
                "Release Evidence",
                f"""
                <p><a href="/dashboard{_api_key_query(api_key)}">Back to dashboard</a></p>
                <section class="hero">
                  <p>
                    Human-readable release evidence for deployment review and audit handoff.
                  </p>
                  {_release_gate_html(gate)}
                  {_release_gate_history_html(gate_history)}
                  {_release_evidence_html(bundle)}
                  {_release_approvals_html(approvals, api_key)}
                </section>
                """,
            )
        )

    @router.get(
        "/dashboard/integration-smoke",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard_integration_smoke(
        api_key: str = Query(default=""),
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> HTMLResponse:
        smoke_runs = list_integration_smoke_reports(
            settings.artifact_root,
            limit=limit,
            offset=offset,
        )
        return HTMLResponse(
            _page(
                "Integration Smoke",
                f"""
                <p><a href="/dashboard{_api_key_query(api_key)}">Back to dashboard</a></p>
                <section class="hero">
                  <p>
                    Review recorded provider smoke reports before enabling live automation or
                    approving a production release.
                  </p>
                  {_integration_smoke_runs_html(smoke_runs)}
                </section>
                """,
            )
        )


    @router.get(
        "/dashboard/job-executions/{execution_id}",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard_job_execution_detail(
        execution_id: str,
        api_key: str = Query(default=""),
    ) -> HTMLResponse:
        try:
            report = get_job_execution_report(
                job_execution_dir(settings.artifact_root),
                execution_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        recovery_plan = job_recovery_plan(
            job_execution_dir(settings.artifact_root),
            execution_id,
        )
        recovery_lineage = job_recovery_lineage(
            job_execution_dir(settings.artifact_root),
            days=90,
        )
        recovery_lineage_item = next(
            (
                item
                for item in recovery_lineage.items
                if item.source_execution_id == report.execution_id
            ),
            None,
        )
        execution_run_ids = job_execution_run_ids(report)
        execution_review_forms = ""
        if execution_run_ids:
            approval_action = (
                f"/dashboard/job-executions/{escape(report.execution_id)}/approve-runs"
                f"{_api_key_query(api_key)}"
            )
            publish_action = (
                f"/dashboard/job-executions/{escape(report.execution_id)}/publish-runs"
                f"{_api_key_query(api_key)}"
            )
            execution_review_forms = f"""
              <h3>Execution Review</h3>
              <form method="post" action="{approval_action}">
                {_api_key_hidden(api_key)}
                <input name="reviewer" placeholder="Reviewer" value="operator">
                <input name="notes" placeholder="Approval notes">
                <button type="submit">Approve generated runs</button>
              </form>
              <form method="post" action="{publish_action}">
                {_api_key_hidden(api_key)}
                <label>
                  <input type="checkbox" name="force" value="true"> force publish
                </label>
                <button type="submit">Publish approved runs</button>
              </form>
            """
        recovery_action = (
            f"/dashboard/job-executions/{escape(report.execution_id)}/recovery-runs"
            f"{_api_key_query(api_key)}"
        )
        recovery_form = f"""
          <h3>Recovery</h3>
          <form method="post" action="{recovery_action}">
            {_api_key_hidden(api_key)}
            <input name="actor" placeholder="Operator" value="operator">
            <input name="notes" placeholder="Recovery notes">
            <button type="submit">Run recovery jobs</button>
          </form>
        """
        return HTMLResponse(
            _page(
                f"Job Execution {report.execution_id}",
                f"""
                <p><a href="/dashboard{_api_key_query(api_key)}">Back to dashboard</a></p>
                <section class="hero">
                  {_job_execution_detail_html(
                    report,
                    recovery_plan,
                    recovery_lineage_item,
                    api_key,
                  )}
                  {execution_review_forms}
                  {recovery_form}
                  <h3>S3 Mirror Log</h3>
                  {_s3_mirror_log_html(_job_execution_s3_mirror_log(report))}
                </section>
                """,
            )
        )


    @router.post(
        "/dashboard/job-executions/{execution_id}/recovery-runs",
        dependencies=[Depends(require_operator)],
    )
    def dashboard_run_job_recovery(
        execution_id: str,
        api_key: str = Query(default=""),
        actor: Annotated[str, Form()] = "operator",
        notes: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        try:
            plan = job_recovery_plan(
                job_execution_dir(settings.artifact_root),
                execution_id,
                actor=actor,
                notes=notes,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not plan.runnable:
            raise HTTPException(
                status_code=409,
                detail=plan.blocked_reason or "Recovery plan has no failed jobs to rerun.",
            )
        recovery_report = JobRunner(pipeline).run(
            plan.to_job_file(),
            receipt_dir=job_execution_dir(settings.artifact_root),
        )
        return RedirectResponse(
            f"/dashboard/job-executions/{recovery_report.execution_id}{_api_key_query(api_key)}",
            status_code=303,
        )


    @router.post(
        "/dashboard/job-executions/{execution_id}/approve-runs",
        dependencies=[Depends(require_operator)],
    )
    def dashboard_approve_job_execution_runs(
        execution_id: str,
        api_key: str = Query(default=""),
        reviewer: Annotated[str, Form()] = "operator",
        notes: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        try:
            report = get_job_execution_report(
                job_execution_dir(settings.artifact_root),
                execution_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        review_service.approve_many(
            job_execution_run_ids(report),
            reviewer=reviewer,
            notes=notes,
        )
        return RedirectResponse(
            f"/dashboard/job-executions/{execution_id}{_api_key_query(api_key)}",
            status_code=303,
        )


    @router.post(
        "/dashboard/job-executions/{execution_id}/publish-runs",
        dependencies=[Depends(require_operator)],
    )
    def dashboard_publish_job_execution_runs(
        execution_id: str,
        api_key: str = Query(default=""),
        force: Annotated[bool, Form()] = False,
    ) -> RedirectResponse:
        try:
            report = get_job_execution_report(
                job_execution_dir(settings.artifact_root),
                execution_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        review_service.publish_many(job_execution_run_ids(report), force=force)
        return RedirectResponse(
            f"/dashboard/job-executions/{execution_id}{_api_key_query(api_key)}",
            status_code=303,
        )


    @router.post("/dashboard/runs", dependencies=[Depends(require_operator)])
    async def dashboard_create_run(
        topic: Annotated[str, Form()],
        source_urls: Annotated[str, Form()] = "",
        publish: Annotated[bool, Form()] = False,
    ) -> RedirectResponse:
        parsed_source_urls = [
            line.strip()
            for line in source_urls.replace(",", "\n").splitlines()
            if line.strip()
        ]
        result = pipeline.run(
            RunRequest(topic=topic, source_urls=parsed_source_urls, publish=publish)
        )
        return RedirectResponse(f"/dashboard/runs/{result.run.id}", status_code=303)


    @router.post(
        "/dashboard/content-calendar/runs",
        dependencies=[Depends(require_operator)],
    )
    def dashboard_create_content_calendar_run(
        workflow_name: Annotated[str, Form()],
        job_name: Annotated[str, Form()],
        api_key: str = Query(default=""),
    ) -> RedirectResponse:
        try:
            request = content_calendar_run_request(
                settings.pipeline_dir,
                workflow_name=workflow_name,
                job_name=job_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        result = pipeline.run(request)
        return RedirectResponse(
            f"/dashboard/runs/{result.run.id}{_api_key_query(api_key)}",
            status_code=303,
        )
    
    
    @router.get(
        "/dashboard/runs/{run_id}",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard_run_detail(run_id: str, api_key: str = Query(default="")) -> HTMLResponse:
        run = repository.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        manifest = review_service.artifact_manifest(run_id)
        artifacts = sorted(manifest.artifacts)
        artifact_rows = "\n".join(
            f"""
            <tr>
              <td><a href="/runs/{escape(run_id)}/artifacts/{escape(name)}">{escape(name)}</a></td>
              <td>{manifest.artifacts[name].size_bytes}</td>
              <td>{escape(manifest.artifacts[name].media_type)}</td>
              <td><code>{escape(manifest.artifacts[name].sha256[:12])}</code></td>
            </tr>
            """
            for name in artifacts
        )
        eval_report = "{}"
        if "eval-report.json" in artifacts:
            eval_report = review_service.read_artifact(run_id, "eval-report.json")
        metrics = review_service.metrics(run_id)
        scorecard = review_service.scorecard(run_id)
        cost_report = review_service.cost_report(run_id)
        generation_receipt = review_service.generation_receipt(run_id)
        incident_report = review_service.incident_report(run_id)
        timeline_rows = _timeline_rows(metrics)
        workflow_context_html = ""
        if "workflow-context.json" in artifacts:
            workflow_context_html = _workflow_context_html(
                review_service.read_artifact(run_id, "workflow-context.json")
            )
        elif "request.json" in artifacts:
            workflow_context_html = _workflow_context_html(
                review_service.read_artifact(run_id, "request.json")
            )
        plan_html = ""
        try:
            plan_html = _publish_plan_html(review_service.publish_plan(run_id))
        except (FileNotFoundError, ValueError):
            plan_html = "<p>Publish plan unavailable.</p>"
        source_review_html = ""
        research_provider_html = ""
        if "research.json" in artifacts:
            research_json = review_service.read_artifact(run_id, "research.json")
            research_provider_html = _research_provider_metadata_html(research_json)
            source_review_html = _source_review_table_html(
                run_id,
                research_json,
                review_service.source_reviews(run_id),
                api_key,
            )
        source_audit_html = ""
        if "source-audit.json" in artifacts:
            source_audit_html = _source_audit_html(
                run_id,
                review_service.read_artifact(run_id, "source-audit.json"),
            )
        approval_html = _approval_html(review_service.approval(run_id))
        receipt_html = _publish_receipt_html(review_service.publish_receipt(run_id))
        verification_html = ""
        if run.status == RunStatus.PUBLISHED:
            try:
                verification_html = _publish_verification_html(
                    review_service.verify_publish(run_id)
                )
            except (FileNotFoundError, ValueError):
                verification_html = "<p>Publish verification unavailable.</p>"
        audit_html = _audit_log_html(review_service.audit_log(run_id))
        notification_html = _notification_log_html(review_service.notification_log(run_id))
        mirror_log_html = _s3_mirror_log_html(
            review_service.s3_mirror_log(run_id),
            f"/runs/{escape(run_id)}/s3-mirror-log",
        )
        approve_action = f"/dashboard/runs/{escape(run_id)}/approve{_api_key_query(api_key)}"
        reject_action = f"/dashboard/runs/{escape(run_id)}/reject{_api_key_query(api_key)}"
        rerun_action = f"/dashboard/runs/{escape(run_id)}/rerun{_api_key_query(api_key)}"
        rollback_action = (
            f"/dashboard/runs/{escape(run_id)}/rollback-publish{_api_key_query(api_key)}"
        )
        publish_action = (
            f'<form method="post" action="/dashboard/runs/{escape(run_id)}/publish'
            f'{_api_key_query(api_key)}">'
            '<button type="submit">Publish run</button></form>'
        )
        return HTMLResponse(
            _page(
                f"Run {run.id}",
                f"""
                <p><a href="/dashboard{_api_key_query(api_key)}">Back to dashboard</a></p>
                <section class="hero">
                  <h2>{escape(run.topic)}</h2>
                  <p>Status: <strong>{escape(run.status.value)}</strong></p>
                  <p>Published URL: {escape(run.published_url or "not published")}</p>
                  <div class="metrics">
                    <div><strong>{_duration_label(metrics.total_duration_ms)}</strong><span>Total</span></div>
                    <div><strong>{metrics.source_count}</strong><span>Sources</span></div>
                    <div>
                      <strong>{str(metrics.publish_ready).lower()}</strong>
                      <span>Publish ready</span>
                    </div>
                  </div>
                  <h3>Publish Plan</h3>
                  <p>
                    <a href="/runs/{escape(run_id)}/homepage-handoff">
                      Download homepage handoff
                    </a>
                  </p>
                  {plan_html}
                  <h3>Workflow Context</h3>
                  {workflow_context_html}
                  <h3>Quality Scorecard</h3>
                  {_scorecard_html(scorecard)}
                  <h3>Token Budget</h3>
                  {_cost_report_html(cost_report)}
                  <h3>Generation Receipt</h3>
                  {_generation_receipt_html(run_id, generation_receipt)}
                  <h3>S3 Mirror Log</h3>
                  {mirror_log_html}
                  <h3>Incident Report</h3>
                  {_incident_report_html(incident_report)}
                  <h3>Approval</h3>
                  {approval_html}
                  <form method="post" action="{approve_action}">
                    <input name="reviewer" placeholder="Reviewer" value="operator">
                    <input name="notes" placeholder="Approval notes">
                    <button type="submit">Approve run</button>
                  </form>
                  <form method="post" action="{reject_action}">
                    <input name="reviewer" placeholder="Reviewer" value="operator">
                    <input name="notes" placeholder="Rejection notes">
                    <button type="submit">Reject run</button>
                  </form>
                  {publish_action}
                  <h3>Publish Receipt</h3>
                  {receipt_html}
                  <h3>Publish Verification</h3>
                  {verification_html}
                  <form method="post" action="{rollback_action}">
                    <input name="actor" placeholder="Actor" value="operator">
                    <button type="submit">Rollback publish</button>
                  </form>
                  <h3>Audit Log</h3>
                  {audit_html}
                  <h3>Notification Deliveries</h3>
                  {notification_html}
                  <form method="post" action="{rerun_action}">
                    <button type="submit">Rerun with same request</button>
                  </form>
                  <form method="get" action="/dashboard/compare">
                    <input type="hidden" name="base_run_id" value="{escape(run_id)}">
                    <input name="candidate_run_id" placeholder="Candidate run id to compare">
                    <button type="submit">Compare runs</button>
                  </form>
                </section>
                <section class="grid">
                  <div>
                    <h3>Artifacts</h3>
                    <p><a href="/runs/{escape(run_id)}/artifact-manifest">Manifest JSON</a></p>
                    <p><a href="/runs/{escape(run_id)}/bundle">Download evidence bundle</a></p>
                    <table>
                      <thead><tr><th>Name</th><th>Bytes</th><th>Type</th><th>SHA</th></tr></thead>
                      <tbody>{artifact_rows}</tbody>
                    </table>
                  </div>
                  <div>
                    <h3>Evaluation</h3>
                    <pre>{escape(eval_report)}</pre>
                  </div>
                </section>
                <section class="hero">
                  <h3>Run Timeline</h3>
                  <table>
                    <thead>
                      <tr><th>Step</th><th>Status</th><th>Duration</th><th>Fields</th></tr>
                    </thead>
                    <tbody>{timeline_rows}</tbody>
                  </table>
                </section>
                <section class="hero">
                  <h3>Source Review</h3>
                  <h4>Research Provider</h4>
                  {research_provider_html}
                  {source_audit_html}
                  {source_review_html}
                </section>
                """,
            )
        )
    
    
    @router.get(
        "/dashboard/compare",
        response_class=HTMLResponse,
        dependencies=[Depends(require_read_access)],
    )
    def dashboard_compare(base_run_id: str, candidate_run_id: str) -> HTMLResponse:
        try:
            comparison = review_service.compare(base_run_id, candidate_run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return HTMLResponse(
            _page(
                "Run Comparison",
                f"""
                <p><a href="/dashboard/runs/{escape(base_run_id)}">Back to base run</a></p>
                <section class="hero">
                  {_comparison_html(comparison)}
                </section>
                """,
            )
        )
    
    
    @router.post("/dashboard/runs/{run_id}/publish", dependencies=[Depends(require_operator)])
    def dashboard_publish_run(
        run_id: str,
    ) -> RedirectResponse:
        try:
            review_service.publish(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(f"/dashboard/runs/{run_id}", status_code=303)
    
    
    @router.post(
        "/dashboard/runs/{run_id}/source-reviews",
        dependencies=[Depends(require_operator)],
    )
    def dashboard_review_source(
        run_id: str,
        source_key: Annotated[str, Form()],
        decision: Annotated[SourceReviewDecision, Form()],
        reviewer: Annotated[str, Form()] = "operator",
        notes: Annotated[str, Form()] = "",
        api_key: str = Query(default=""),
    ) -> RedirectResponse:
        try:
            review_service.review_source(
                run_id,
                SourceReviewRequest(
                    source_key=source_key,
                    decision=decision,
                    reviewer=reviewer,
                    notes=notes,
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(
            f"/dashboard/runs/{run_id}{_api_key_query(api_key)}",
            status_code=303,
        )


    @router.post(
        "/dashboard/runs/{run_id}/rollback-publish",
        dependencies=[Depends(require_operator)],
    )
    def dashboard_rollback_publish(
        run_id: str,
        actor: Annotated[str, Form()] = "operator",
    ) -> RedirectResponse:
        try:
            review_service.rollback_publish(run_id, actor=actor)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(f"/dashboard/runs/{run_id}", status_code=303)
    
    
    @router.post("/dashboard/runs/{run_id}/approve", dependencies=[Depends(require_operator)])
    def dashboard_approve_run(
        run_id: str,
        reviewer: Annotated[str, Form()] = "operator",
        notes: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        try:
            review_service.approve(run_id, reviewer=reviewer, notes=notes)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(f"/dashboard/runs/{run_id}", status_code=303)
    
    
    @router.post("/dashboard/runs/{run_id}/reject", dependencies=[Depends(require_operator)])
    def dashboard_reject_run(
        run_id: str,
        reviewer: Annotated[str, Form()] = "operator",
        notes: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        try:
            review_service.reject(run_id, reviewer=reviewer, notes=notes)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse(f"/dashboard/runs/{run_id}", status_code=303)


    @router.post("/dashboard/release-approval", dependencies=[Depends(require_operator)])
    def dashboard_release_approval(
        decision: Annotated[ReleaseApprovalDecision, Form()],
        api_key: str = Query(default=""),
        approver: Annotated[str, Form()] = "operator",
        notes: Annotated[str, Form()] = "",
        force: Annotated[bool, Form()] = False,
    ) -> RedirectResponse:
        try:
            approve_release(
                settings=settings,
                repository=repository,
                review_service=review_service,
                request=ReleaseApprovalRequest(
                    decision=decision,
                    approver=approver,
                    notes=notes,
                    force=force,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(
            f"/dashboard/release-evidence{_api_key_query(api_key)}",
            status_code=303,
        )
    
    
    @router.post("/dashboard/runs/batch-approve", dependencies=[Depends(require_operator)])
    def dashboard_batch_approve(
        run_ids: Annotated[list[str] | None, Form()] = None,
        reviewer: Annotated[str, Form()] = "operator",
        notes: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        selected_run_ids = run_ids or []
        if selected_run_ids:
            review_service.approve_many(selected_run_ids, reviewer=reviewer, notes=notes)
        return RedirectResponse("/dashboard?status=approved", status_code=303)
    
    
    @router.post("/dashboard/runs/batch-reject", dependencies=[Depends(require_operator)])
    def dashboard_batch_reject(
        run_ids: Annotated[list[str] | None, Form()] = None,
        reviewer: Annotated[str, Form()] = "operator",
        notes: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        selected_run_ids = run_ids or []
        if selected_run_ids:
            review_service.reject_many(selected_run_ids, reviewer=reviewer, notes=notes)
        return RedirectResponse("/dashboard?status=rejected", status_code=303)
    
    
    @router.post("/dashboard/runs/{run_id}/rerun", dependencies=[Depends(require_operator)])
    def dashboard_rerun(
        run_id: str,
    ) -> RedirectResponse:
        request = review_service.request(run_id)
        result = pipeline.run(request)
        return RedirectResponse(f"/dashboard/runs/{result.run.id}", status_code=303)


    return router


def _publisher_target_dir(settings: Settings) -> Path:
    if settings.publisher_provider == "homepage":
        if settings.homepage_repo_path is None:
            raise HTTPException(
                status_code=409,
                detail="CONTENTOPS_HOMEPAGE_REPO_PATH is required for homepage content assets.",
            )
        return settings.homepage_repo_path
    return settings.site_output_dir


def _publisher_public_url(settings: Settings) -> str:
    if settings.publisher_provider == "homepage":
        return settings.homepage_public_base_url
    return settings.public_base_url


def _job_execution_s3_mirror_log(report: JobExecutionReport) -> list[ArtifactMirrorRecord]:
    if not report.receipt_path:
        return []
    path = Path(report.receipt_path)
    mirror_log_path = path.parent / "s3-mirror-log.json"
    if not mirror_log_path.exists():
        return []
    data = json.loads(mirror_log_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [
        ArtifactMirrorRecord.model_validate(item)
        for item in data
        if isinstance(item, dict) and item.get("artifact_name") == path.name
    ]
