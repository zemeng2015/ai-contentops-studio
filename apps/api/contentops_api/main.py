from __future__ import annotations

from contentops_core.factory import build_pipeline
from contentops_core.models import RunRecord, RunRequest
from contentops_core.repository import RunRepository
from contentops_core.settings import Settings
from fastapi import FastAPI, HTTPException

settings = Settings()
pipeline = build_pipeline(settings)
repository = RunRepository(settings.database_url)

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

