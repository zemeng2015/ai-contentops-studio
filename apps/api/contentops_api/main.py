from __future__ import annotations

import json
import secrets
from html import escape
from typing import Annotated
from urllib.parse import urlencode
from uuid import uuid4

from contentops_core.diagnostics import (
    deployment_manifest,
    release_readiness,
    system_status,
)
from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.jobs import (
    JobExecutionListResponse,
    JobExecutionReport,
    get_job_execution_report,
    job_execution_dir,
    list_job_execution_reports,
)
from contentops_core.models import (
    ApprovalRecord,
    ArtifactManifest,
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
    PublishRollbackResult,
    PublishVerificationReport,
    ReleaseReadinessReport,
    RetentionReport,
    ReviewBatchRequest,
    ReviewBatchResult,
    RunComparison,
    RunCostReport,
    RunIncidentReport,
    RunListResponse,
    RunMetrics,
    RunRecord,
    RunRequest,
    RunScorecard,
    RunStatus,
    ScorecardListResponse,
    SourceAuditReport,
    SystemStatus,
)
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import RequestResponseEndpoint

settings = Settings()
pipeline = build_pipeline(settings)
repository = RunRepository(settings.database_url)
review_service = build_review_service(settings)

app = FastAPI(
    title="AI ContentOps Studio",
    version="0.1.0",
    description="Research, evaluation, and publishing automation for technical content.",
)


@app.middleware("http")
async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
    request_id = request.headers.get("x-contentops-request-id") or uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["x-contentops-request-id"] = request_id
    return response


@app.exception_handler(HTTPException)
async def http_error_response(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = _request_id(request)
    headers = dict(exc.headers or {})
    headers["x-contentops-request-id"] = request_id
    return JSONResponse(
        status_code=exc.status_code,
        headers=headers,
        content={
            "error": {
                "code": _error_code(exc.status_code),
                "message": str(exc.detail),
                "request_id": request_id,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_response(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        status_code=422,
        headers={"x-contentops-request-id": request_id},
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed.",
                "request_id": request_id,
                "fields": exc.errors(),
            }
        },
    )


async def require_operator(request: Request) -> None:
    configured = settings.operator_api_key
    if configured is None:
        return
    expected = configured.get_secret_value()
    provided = request.headers.get("x-contentops-api-key") or request.query_params.get("api_key")
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Valid operator API key required.")


async def require_read_access(request: Request) -> None:
    if not settings.require_read_api_key:
        return
    allowed_keys = [
        configured.get_secret_value()
        for configured in (settings.read_api_key, settings.operator_api_key)
        if configured is not None
    ]
    if not allowed_keys:
        raise HTTPException(
            status_code=503,
            detail="Read access protection requires a read or operator API key.",
        )
    provided = request.headers.get("x-contentops-api-key") or request.query_params.get("api_key")
    if provided is None or not any(secrets.compare_digest(provided, key) for key in allowed_keys):
        raise HTTPException(status_code=401, detail="Valid read API key required.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", response_model=SystemStatus)
def ready(response: Response) -> SystemStatus:
    status = system_status(settings, repository)
    if status.status == "fail":
        response.status_code = 503
    return status


@app.get(
    "/deployment-manifest",
    response_model=DeploymentManifest,
    dependencies=[Depends(require_read_access)],
)
def get_deployment_manifest() -> DeploymentManifest:
    return deployment_manifest(settings, repository)


@app.get(
    "/release-readiness",
    response_model=ReleaseReadinessReport,
    dependencies=[Depends(require_read_access)],
)
def get_release_readiness(
    window_size: int = Query(default=100, ge=1, le=500),
) -> ReleaseReadinessReport:
    operations = review_service.operations_summary(window_size=window_size)
    return release_readiness(settings, repository, operations)


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_read_access)])
@app.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(require_read_access)])
def dashboard(
    q: str = Query(default=""),
    status: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    api_key: str = Query(default=""),
) -> HTMLResponse:
    status_filter = _parse_status_filter(status)
    runs = repository.list(limit=limit, offset=offset, status=status_filter, query=q)
    total = repository.count(status=status_filter, query=q)
    job_executions = list_job_execution_reports(
        job_execution_dir(settings.artifact_root),
        limit=5,
    )
    published_content = review_service.published_content(limit=5)
    scorecards = review_service.scorecards(limit=5)
    cost_reports = review_service.cost_reports(limit=5)
    incident_reports = review_service.incident_reports(limit=5)
    audit_events = review_service.audit_events(limit=5)
    retention_report = review_service.retention_report()
    operations_summary = review_service.operations_summary()
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
              <p>Review generated research, drafts, evaluation reports, and publishing state.</p>
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
                <label><input type="checkbox" name="publish" value="true"> publish if ready</label>
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
              <h2>Operations Summary</h2>
              <p>Portfolio-wide run health, queue depth, incident severity, and cost posture.</p>
              {_operations_summary_html(operations_summary)}
            </section>
            <section class="hero compact">
              <h2>Artifact Retention</h2>
              <p>Storage hygiene report for old run artifacts that can be archived or pruned.</p>
              {_retention_report_html(retention_report)}
            </section>
            <section class="hero compact">
              <h2>Audit Events</h2>
              <p>Recent approve, publish, reject, and rollback events across all runs.</p>
              {_audit_events_html(audit_events)}
            </section>
            <section class="hero compact">
              <h2>Worker Executions</h2>
              <p>Recent scheduled job receipts for automation audit and incident review.</p>
              {_job_executions_html(job_executions.items)}
            </section>
            <section class="hero compact">
              <h2>Published Content</h2>
              <p>Operational catalog of shipped articles and their evaluation scores.</p>
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


@app.post("/dashboard/runs")
async def dashboard_create_run(
    topic: Annotated[str, Form()],
    _: Annotated[None, Depends(require_operator)],
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


@app.get(
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
    plan_html = ""
    try:
        plan_html = _publish_plan_html(review_service.publish_plan(run_id))
    except (FileNotFoundError, ValueError):
        plan_html = "<p>Publish plan unavailable.</p>"
    source_rows = ""
    if "research.json" in artifacts:
        source_rows = _source_review_rows(review_service.read_artifact(run_id, "research.json"))
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
              {plan_html}
              <h3>Quality Scorecard</h3>
              {_scorecard_html(scorecard)}
              <h3>Token Budget</h3>
              {_cost_report_html(cost_report)}
              <h3>Generation Receipt</h3>
              {_generation_receipt_html(run_id, generation_receipt)}
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
              {source_audit_html}
              <table>
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Status</th>
                    <th>Quality</th>
                    <th>Summary</th>
                  </tr>
                </thead>
                <tbody>{source_rows}</tbody>
              </table>
            </section>
            """,
        )
    )


@app.get(
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


@app.post("/dashboard/runs/{run_id}/publish")
def dashboard_publish_run(
    run_id: str,
    _: Annotated[None, Depends(require_operator)],
) -> RedirectResponse:
    try:
        review_service.publish(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse(f"/dashboard/runs/{run_id}", status_code=303)


@app.post("/dashboard/runs/{run_id}/rollback-publish")
def dashboard_rollback_publish(
    run_id: str,
    _: Annotated[None, Depends(require_operator)],
    actor: Annotated[str, Form()] = "operator",
) -> RedirectResponse:
    try:
        review_service.rollback_publish(run_id, actor=actor)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse(f"/dashboard/runs/{run_id}", status_code=303)


@app.post("/dashboard/runs/{run_id}/approve")
def dashboard_approve_run(
    run_id: str,
    _: Annotated[None, Depends(require_operator)],
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


@app.post("/dashboard/runs/{run_id}/reject")
def dashboard_reject_run(
    run_id: str,
    _: Annotated[None, Depends(require_operator)],
    reviewer: Annotated[str, Form()] = "operator",
    notes: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        review_service.reject(run_id, reviewer=reviewer, notes=notes)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(f"/dashboard/runs/{run_id}", status_code=303)


@app.post("/dashboard/runs/batch-approve")
def dashboard_batch_approve(
    _: Annotated[None, Depends(require_operator)],
    run_ids: Annotated[list[str] | None, Form()] = None,
    reviewer: Annotated[str, Form()] = "operator",
    notes: Annotated[str, Form()] = "",
) -> RedirectResponse:
    selected_run_ids = run_ids or []
    if selected_run_ids:
        review_service.approve_many(selected_run_ids, reviewer=reviewer, notes=notes)
    return RedirectResponse("/dashboard?status=approved", status_code=303)


@app.post("/dashboard/runs/batch-reject")
def dashboard_batch_reject(
    _: Annotated[None, Depends(require_operator)],
    run_ids: Annotated[list[str] | None, Form()] = None,
    reviewer: Annotated[str, Form()] = "operator",
    notes: Annotated[str, Form()] = "",
) -> RedirectResponse:
    selected_run_ids = run_ids or []
    if selected_run_ids:
        review_service.reject_many(selected_run_ids, reviewer=reviewer, notes=notes)
    return RedirectResponse("/dashboard?status=rejected", status_code=303)


@app.post("/dashboard/runs/{run_id}/rerun")
def dashboard_rerun(
    run_id: str,
    _: Annotated[None, Depends(require_operator)],
) -> RedirectResponse:
    request = review_service.request(run_id)
    result = pipeline.run(request)
    return RedirectResponse(f"/dashboard/runs/{result.run.id}", status_code=303)


@app.post("/runs", response_model=RunRecord)
def create_run(
    request: RunRequest,
    _: Annotated[None, Depends(require_operator)],
) -> RunRecord:
    result = pipeline.run(request)
    return result.run


@app.get("/runs", response_model=list[RunRecord], dependencies=[Depends(require_read_access)])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default=""),
    q: str = Query(default=""),
) -> list[RunRecord]:
    return repository.list(
        limit=limit,
        offset=offset,
        status=_parse_status_filter(status),
        query=q,
    )


@app.get(
    "/review-queue",
    response_model=RunListResponse,
    dependencies=[Depends(require_read_access)],
)
def review_queue(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default=RunStatus.NEEDS_REVIEW.value),
    q: str = Query(default=""),
) -> RunListResponse:
    status_filter = _parse_status_filter(status)
    return RunListResponse(
        items=repository.list(
            limit=limit,
            offset=offset,
            status=status_filter,
            query=q,
        ),
        total=repository.count(status=status_filter, query=q),
        limit=limit,
        offset=offset,
    )


@app.get(
    "/job-executions",
    response_model=JobExecutionListResponse,
    dependencies=[Depends(require_read_access)],
)
def list_job_executions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JobExecutionListResponse:
    return list_job_execution_reports(
        job_execution_dir(settings.artifact_root),
        limit=limit,
        offset=offset,
    )


@app.get(
    "/job-executions/{execution_id}",
    response_model=JobExecutionReport,
    dependencies=[Depends(require_read_access)],
)
def get_job_execution(execution_id: str) -> JobExecutionReport:
    try:
        return get_job_execution_report(
            job_execution_dir(settings.artifact_root),
            execution_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/content",
    response_model=PublishedContentListResponse,
    dependencies=[Depends(require_read_access)],
)
def list_published_content(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PublishedContentListResponse:
    return review_service.published_content(limit=limit, offset=offset)


@app.get(
    "/scorecards",
    response_model=ScorecardListResponse,
    dependencies=[Depends(require_read_access)],
)
def list_scorecards(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default=""),
    q: str = Query(default=""),
) -> ScorecardListResponse:
    return review_service.scorecards(
        limit=limit,
        offset=offset,
        status=_parse_status_filter(status),
        query=q,
    )


@app.get(
    "/cost-reports",
    response_model=CostReportListResponse,
    dependencies=[Depends(require_read_access)],
)
def list_cost_reports(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default=""),
    q: str = Query(default=""),
) -> CostReportListResponse:
    return review_service.cost_reports(
        limit=limit,
        offset=offset,
        status=_parse_status_filter(status),
        query=q,
    )


@app.get(
    "/incident-reports",
    response_model=IncidentReportListResponse,
    dependencies=[Depends(require_read_access)],
)
def list_incident_reports(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default=""),
    q: str = Query(default=""),
) -> IncidentReportListResponse:
    return review_service.incident_reports(
        limit=limit,
        offset=offset,
        status=_parse_status_filter(status),
        query=q,
    )


@app.get(
    "/audit-events",
    response_model=AuditEventListResponse,
    dependencies=[Depends(require_read_access)],
)
def list_audit_events(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default=""),
    q: str = Query(default=""),
    action: str = Query(default=""),
) -> AuditEventListResponse:
    return review_service.audit_events(
        limit=limit,
        offset=offset,
        status=_parse_status_filter(status),
        query=q,
        action=action,
    )


@app.get(
    "/retention-report",
    response_model=RetentionReport,
    dependencies=[Depends(require_read_access)],
)
def get_retention_report(
    days: int = Query(default=90, ge=0, le=3650),
    limit: int = Query(default=100, ge=1, le=1000),
) -> RetentionReport:
    return review_service.retention_report(retention_days=days, limit=limit)


@app.get(
    "/ops-summary",
    response_model=OperationsSummary,
    dependencies=[Depends(require_read_access)],
)
def get_ops_summary(
    window_size: int = Query(default=100, ge=1, le=500),
) -> OperationsSummary:
    return review_service.operations_summary(window_size=window_size)


@app.get(
    "/runs/{run_id}",
    response_model=RunRecord,
    dependencies=[Depends(require_read_access)],
)
def get_run(run_id: str) -> RunRecord:
    run = repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get(
    "/runs/{run_id}/artifacts",
    response_model=list[str],
    dependencies=[Depends(require_read_access)],
)
def list_artifacts(run_id: str) -> list[str]:
    try:
        return review_service.list_artifacts(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/runs/{run_id}/artifact-manifest",
    response_model=ArtifactManifest,
    dependencies=[Depends(require_read_access)],
)
def get_artifact_manifest(run_id: str) -> ArtifactManifest:
    try:
        return review_service.artifact_manifest(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/runs/{run_id}/bundle", dependencies=[Depends(require_read_access)])
def get_run_bundle(run_id: str) -> FileResponse:
    try:
        bundle_path = review_service.create_bundle(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        bundle_path,
        media_type="application/zip",
        filename=bundle_path.name,
    )


@app.get(
    "/runs/{run_id}/artifacts/{artifact_name}",
    dependencies=[Depends(require_read_access)],
)
def get_artifact(run_id: str, artifact_name: str) -> Response:
    try:
        content = review_service.read_artifact(run_id, artifact_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    media_type = "application/json" if artifact_name.endswith(".json") else "text/plain"
    return Response(content=content, media_type=media_type)


@app.post("/runs/{run_id}/publish", response_model=RunRecord)
def publish_run(
    run_id: str,
    _: Annotated[None, Depends(require_operator)],
    force: bool = False,
) -> RunRecord:
    try:
        return review_service.publish(run_id, force=force)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/runs/{run_id}/approve", response_model=RunRecord)
def approve_run(
    run_id: str,
    _: Annotated[None, Depends(require_operator)],
    reviewer: str = "operator",
    notes: str = "",
) -> RunRecord:
    try:
        return review_service.approve(run_id, reviewer=reviewer, notes=notes)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/runs/{run_id}/reject", response_model=RunRecord)
def reject_run(
    run_id: str,
    _: Annotated[None, Depends(require_operator)],
    reviewer: str = "operator",
    notes: str = "",
) -> RunRecord:
    try:
        return review_service.reject(run_id, reviewer=reviewer, notes=notes)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/review-queue/batch-approve", response_model=ReviewBatchResult)
def batch_approve_runs(
    request: ReviewBatchRequest,
    _: Annotated[None, Depends(require_operator)],
) -> ReviewBatchResult:
    return review_service.approve_many(
        request.run_ids,
        reviewer=request.reviewer,
        notes=request.notes,
    )


@app.post("/review-queue/batch-reject", response_model=ReviewBatchResult)
def batch_reject_runs(
    request: ReviewBatchRequest,
    _: Annotated[None, Depends(require_operator)],
) -> ReviewBatchResult:
    return review_service.reject_many(
        request.run_ids,
        reviewer=request.reviewer,
        notes=request.notes,
    )


@app.get(
    "/runs/{run_id}/approval",
    response_model=ApprovalRecord | None,
    dependencies=[Depends(require_read_access)],
)
def get_approval(run_id: str) -> ApprovalRecord | None:
    try:
        return review_service.approval(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/runs/{run_id}/publish-receipt",
    response_model=PublishReceipt | None,
    dependencies=[Depends(require_read_access)],
)
def get_publish_receipt(run_id: str) -> PublishReceipt | None:
    try:
        return review_service.publish_receipt(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/runs/{run_id}/publish-verification",
    response_model=PublishVerificationReport,
    dependencies=[Depends(require_read_access)],
)
def get_publish_verification(run_id: str) -> PublishVerificationReport:
    try:
        return review_service.verify_publish(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/runs/{run_id}/generation-receipt",
    response_model=GenerationReceipt | None,
    dependencies=[Depends(require_read_access)],
)
def get_generation_receipt(run_id: str) -> GenerationReceipt | None:
    try:
        return review_service.generation_receipt(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/runs/{run_id}/rollback-publish", response_model=PublishRollbackResult)
def rollback_published_run(
    run_id: str,
    _: Annotated[None, Depends(require_operator)],
    actor: str = "operator",
) -> PublishRollbackResult:
    try:
        return review_service.rollback_publish(run_id, actor=actor)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/runs/{run_id}/audit-log",
    response_model=list[AuditEvent],
    dependencies=[Depends(require_read_access)],
)
def get_audit_log(run_id: str) -> list[AuditEvent]:
    try:
        return review_service.audit_log(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/runs/{run_id}/notifications",
    response_model=list[NotificationDelivery],
    dependencies=[Depends(require_read_access)],
)
def get_notification_log(run_id: str) -> list[NotificationDelivery]:
    try:
        return review_service.notification_log(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/runs/{run_id}/rerun", response_model=RunRecord)
def rerun(
    run_id: str,
    _: Annotated[None, Depends(require_operator)],
    publish: bool | None = None,
) -> RunRecord:
    try:
        request = review_service.request(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if publish is not None:
        request.publish = publish
    return pipeline.run(request).run


@app.get("/runs/{run_id}/publish-plan", dependencies=[Depends(require_read_access)])
def get_publish_plan(run_id: str) -> dict[str, object]:
    try:
        return review_service.publish_plan(run_id).model_dump(mode="json")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/runs/{run_id}/metrics",
    response_model=RunMetrics,
    dependencies=[Depends(require_read_access)],
)
def get_run_metrics(run_id: str) -> RunMetrics:
    try:
        return review_service.metrics(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/runs/{run_id}/scorecard",
    response_model=RunScorecard,
    dependencies=[Depends(require_read_access)],
)
def get_run_scorecard(run_id: str) -> RunScorecard:
    try:
        return review_service.scorecard(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/runs/{run_id}/cost-report",
    response_model=RunCostReport,
    dependencies=[Depends(require_read_access)],
)
def get_run_cost_report(run_id: str) -> RunCostReport:
    try:
        return review_service.cost_report(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/runs/{run_id}/incident-report",
    response_model=RunIncidentReport,
    dependencies=[Depends(require_read_access)],
)
def get_run_incident_report(run_id: str) -> RunIncidentReport:
    try:
        return review_service.incident_report(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/runs/{run_id}/source-audit",
    response_model=SourceAuditReport,
    dependencies=[Depends(require_read_access)],
)
def get_source_audit(run_id: str) -> SourceAuditReport:
    try:
        raw = review_service.read_artifact(run_id, "source-audit.json")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SourceAuditReport.model_validate_json(raw)


@app.get(
    "/runs/{base_run_id}/compare/{candidate_run_id}",
    response_model=RunComparison,
    dependencies=[Depends(require_read_access)],
)
def compare_runs(base_run_id: str, candidate_run_id: str) -> RunComparison:
    try:
        return review_service.compare(base_run_id, candidate_run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", "")
    return str(value) if value else uuid4().hex


def _error_code(status_code: int) -> str:
    labels = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        500: "internal_error",
        503: "service_unavailable",
    }
    return labels.get(status_code, "http_error")


def _parse_status_filter(status: str) -> RunStatus | None:
    normalized = status.strip().casefold()
    if not normalized:
        return None
    try:
        return RunStatus(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown run status: {status}") from exc


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
            <a href="/job-executions/{escape(report.execution_id)}">
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
    """


def _operations_summary_html(summary: OperationsSummary) -> str:
    return f"""
      <p>
        <a href="/ops-summary">Operations summary JSON</a> |
        <a href="/deployment-manifest">Deployment manifest JSON</a> |
        <a href="/release-readiness">Release readiness JSON</a>
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


def _safe_metrics(run_id: str) -> RunMetrics | None:
    try:
        return review_service.metrics(run_id)
    except FileNotFoundError:
        return None


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
