from __future__ import annotations

import json
from html import escape
from typing import Annotated

from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.models import PublishPlan, RunComparison, RunMetrics, RunRecord, RunRequest
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings
from fastapi import FastAPI, Form, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, RedirectResponse

settings = Settings()
pipeline = build_pipeline(settings)
repository = RunRepository(settings.database_url)
review_service = build_review_service(settings)

app = FastAPI(
    title="AI ContentOps Studio",
    version="0.1.0",
    description="Research, evaluation, and publishing automation for technical content.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    q: str = Query(default=""),
    status: str = Query(default=""),
) -> HTMLResponse:
    all_runs = repository.list(limit=100)
    runs = _filter_runs(all_runs, q, status)[:50]
    metrics = [_safe_metrics(run.id) for run in runs]
    completed = sum(
        1 for item in metrics if item is not None and item.total_duration_ms is not None
    )
    published = sum(1 for run in runs if run.status.value == "published")
    avg_duration = _avg_duration(metrics)
    rows = "\n".join(
        f"""
        <tr>
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
                <div><strong>{len(runs)}</strong><span>Runs</span></div>
                <div><strong>{published}</strong><span>Published</span></div>
                <div><strong>{completed}</strong><span>Traced</span></div>
                <div><strong>{avg_duration}</strong><span>Avg duration</span></div>
              </div>
              <form method="post" action="/dashboard/runs">
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
                <button type="submit">Filter runs</button>
              </form>
            </section>
            <table>
              <thead><tr><th>Run</th><th>Status</th><th>Topic</th><th>Updated</th></tr></thead>
              <tbody>{rows}</tbody>
            </table>
            """,
        )
    )


@app.post("/dashboard/runs")
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


@app.get("/dashboard/runs/{run_id}", response_class=HTMLResponse)
def dashboard_run_detail(run_id: str) -> HTMLResponse:
    run = repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    artifacts = review_service.list_artifacts(run_id)
    artifact_links = "\n".join(
        f'<li><a href="/runs/{escape(run_id)}/artifacts/{escape(name)}">{escape(name)}</a></li>'
        for name in artifacts
    )
    eval_report = "{}"
    if "eval-report.json" in artifacts:
        eval_report = review_service.read_artifact(run_id, "eval-report.json")
    metrics = review_service.metrics(run_id)
    timeline_rows = _timeline_rows(metrics)
    plan_html = ""
    try:
        plan_html = _publish_plan_html(review_service.publish_plan(run_id))
    except (FileNotFoundError, ValueError):
        plan_html = "<p>Publish plan unavailable.</p>"
    source_rows = ""
    if "research.json" in artifacts:
        source_rows = _source_review_rows(review_service.read_artifact(run_id, "research.json"))
    publish_action = (
        f'<form method="post" action="/dashboard/runs/{escape(run_id)}/publish">'
        '<button type="submit">Publish run</button></form>'
    )
    return HTMLResponse(
        _page(
            f"Run {run.id}",
            f"""
            <p><a href="/dashboard">Back to dashboard</a></p>
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
              {publish_action}
              <form method="post" action="/dashboard/runs/{escape(run_id)}/rerun">
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
                <ul>{artifact_links}</ul>
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


@app.get("/dashboard/compare", response_class=HTMLResponse)
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
def dashboard_publish_run(run_id: str) -> RedirectResponse:
    review_service.publish(run_id)
    return RedirectResponse(f"/dashboard/runs/{run_id}", status_code=303)


@app.post("/dashboard/runs/{run_id}/rerun")
def dashboard_rerun(run_id: str) -> RedirectResponse:
    request = review_service.request(run_id)
    result = pipeline.run(request)
    return RedirectResponse(f"/dashboard/runs/{result.run.id}", status_code=303)


@app.post("/runs", response_model=RunRecord)
def create_run(request: RunRequest) -> RunRecord:
    result = pipeline.run(request)
    return result.run


@app.get("/runs", response_model=list[RunRecord])
def list_runs(limit: int = 20) -> list[RunRecord]:
    return repository.list(limit=limit)


@app.get("/runs/{run_id}", response_model=RunRecord)
def get_run(run_id: str) -> RunRecord:
    run = repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/runs/{run_id}/artifacts", response_model=list[str])
def list_artifacts(run_id: str) -> list[str]:
    try:
        return review_service.list_artifacts(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/runs/{run_id}/artifacts/{artifact_name}")
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
def publish_run(run_id: str, force: bool = False) -> RunRecord:
    try:
        return review_service.publish(run_id, force=force)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/runs/{run_id}/rerun", response_model=RunRecord)
def rerun(run_id: str, publish: bool | None = None) -> RunRecord:
    try:
        request = review_service.request(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if publish is not None:
        request.publish = publish
    return pipeline.run(request).run


@app.get("/runs/{run_id}/publish-plan")
def get_publish_plan(run_id: str) -> dict[str, object]:
    try:
        return review_service.publish_plan(run_id).model_dump(mode="json")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/runs/{run_id}/metrics", response_model=RunMetrics)
def get_run_metrics(run_id: str) -> RunMetrics:
    try:
        return review_service.metrics(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/runs/{base_run_id}/compare/{candidate_run_id}", response_model=RunComparison)
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
            grid-template-columns: repeat(4, minmax(0, 1fr));
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
          .grid {{ display: grid; grid-template-columns: 0.4fr 0.6fr; gap: 18px; }}
          .grid > div {{ padding: 22px; min-width: 0; }}
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


def _filter_runs(runs: list[RunRecord], query: str, status: str) -> list[RunRecord]:
    normalized_query = query.strip().casefold()
    normalized_status = status.strip().casefold()
    filtered: list[RunRecord] = []
    for run in runs:
        matches_query = not normalized_query or (
            normalized_query in run.id.casefold()
            or normalized_query in run.topic.casefold()
            or normalized_query in run.slug.casefold()
        )
        matches_status = not normalized_status or run.status.value == normalized_status
        if matches_query and matches_status:
            filtered.append(run)
    return filtered


def _status_options(selected: str) -> str:
    statuses = ["", "created", "researching", "planning", "drafting", "evaluating"]
    statuses += ["needs_review", "publishing", "published", "failed"]
    rows: list[str] = []
    normalized = selected.strip().casefold()
    for status in statuses:
        label = "all statuses" if not status else status
        selected_attr = " selected" if status == normalized else ""
        rows.append(
            f'<option value="{escape(status)}"{selected_attr}>{escape(label)}</option>'
        )
    return "\n".join(rows)


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
