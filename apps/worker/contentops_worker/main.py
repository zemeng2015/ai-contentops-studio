from __future__ import annotations

import typer
import yaml
from contentops_core.factory import build_pipeline
from contentops_core.models import RunRequest
from contentops_core.settings import Settings

app = typer.Typer(help="Run scheduled or YAML-defined ContentOps jobs.")


@app.command()
def run_pipeline(path: str) -> None:
    settings = Settings()
    pipeline = build_pipeline(settings)
    config = yaml.safe_load(open(path, encoding="utf-8"))
    request = RunRequest(
        topic=config["topic"],
        source_urls=config.get("source_urls", []),
        publish=bool(config.get("publish", False)),
    )
    result = pipeline.run(request)
    typer.echo(f"Run {result.run.id}: {result.run.status.value}")

