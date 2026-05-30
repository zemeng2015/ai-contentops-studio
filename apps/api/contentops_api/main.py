from __future__ import annotations

from html import escape
from typing import Annotated

from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.models import RunRecord, RunRequest
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings
from fastapi import FastAPI, Form, HTTPException, Response
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
def dashboard() -> HTMLResponse:
    runs = repository.list(limit=50)
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
              <form method="post" action="/dashboard/runs">
                <input name="topic" placeholder="Run topic" required>
                <label><input type="checkbox" name="publish" value="true"> publish if ready</label>
                <button type="submit">Create run</button>
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
    publish: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    result = pipeline.run(RunRequest(topic=topic, publish=publish))
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
              {publish_action}
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
            """,
        )
    )


@app.post("/dashboard/runs/{run_id}/publish")
def dashboard_publish_run(run_id: str) -> RedirectResponse:
    review_service.publish(run_id)
    return RedirectResponse(f"/dashboard/runs/{run_id}", status_code=303)


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
          form {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }}
          input[type="text"], input[name="topic"] {{
            min-width: min(520px, 100%);
            padding: 12px;
            border: 1px solid #d8ddd7;
            border-radius: 6px;
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
          @media (max-width: 800px) {{ .grid {{ grid-template-columns: 1fr; }} }}
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
