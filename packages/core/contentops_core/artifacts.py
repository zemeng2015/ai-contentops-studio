from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from contentops_core.models import ArtifactManifest, RunRecord


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def prepare(self, run: RunRecord) -> None:
        run.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.write_json(run, "manifest.json", ArtifactManifest(run_id=run.id))

    def write_json(self, run: RunRecord, name: str, payload: BaseModel | dict[str, Any]) -> Path:
        path = run.artifact_dir / name
        if isinstance(payload, BaseModel):
            data = payload.model_dump(mode="json")
        else:
            data = payload
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def write_text(self, run: RunRecord, name: str, text: str) -> Path:
        path = run.artifact_dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def read_text(self, run: RunRecord, name: str) -> str:
        return (run.artifact_dir / name).read_text(encoding="utf-8")

