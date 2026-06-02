from __future__ import annotations

import secrets
from html import escape
from typing import Annotated
from uuid import uuid4

from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.jobs import (
    job_execution_dir,
    list_job_execution_reports,
)
from contentops_core.models import (
    ApprovalRecord,
    ArtifactManifest,
    AuditEvent,
    GenerationReceipt,
    NotificationDelivery,
    PublishReceipt,
    PublishRollbackResult,
    PublishVerificationReport,
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
    SourceAuditReport,
)
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import RequestResponseEndpoint

from contentops_api.routes.ops import build_ops_router
from contentops_api.views import (
    _api_key_hidden,
    _api_key_query,
    _approval_html,
    _audit_events_html,
    _audit_log_html,
    _avg_duration,
    _comparison_html,
    _cost_report_html,
    _cost_reports_html,
    _duration_label,
    _generation_receipt_html,
    _incident_report_html,
    _incident_reports_html,
    _job_executions_html,
    _notification_log_html,
    _operations_summary_html,
    _page,
    _pagination_html,
    _publish_plan_html,
    _publish_receipt_html,
    _publish_verification_html,
    _published_content_html,
    _retention_report_html,
    _scorecard_html,
    _scorecards_html,
    _source_audit_html,
    _source_review_rows,
    _status_options,
    _timeline_rows,
)

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


def _parse_status_filter(status: str) -> RunStatus | None:
    normalized = status.strip().casefold()
    if not normalized:
        return None
    try:
        return RunStatus(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown run status: {status}") from exc


app.include_router(
    build_ops_router(
        settings=settings,
        repository=repository,
        review_service=review_service,
        require_read_access=require_read_access,
        parse_status_filter=_parse_status_filter,
    )
)


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


def _safe_metrics(run_id: str) -> RunMetrics | None:
    try:
        return review_service.metrics(run_id)
    except FileNotFoundError:
        return None
