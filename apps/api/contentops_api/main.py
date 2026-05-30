from __future__ import annotations

from contentops_core.factory import build_pipeline, build_review_service
from contentops_core.models import RunRecord, RunRequest
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings
from fastapi import FastAPI, HTTPException, Response

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
