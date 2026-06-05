from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from contentops_core.models import Draft, EvaluationReport, RunRecord


def upsert_publish_index_entry(
    index_path: Path,
    *,
    provider: str,
    public_url: str,
    run: RunRecord,
    draft: Draft,
    report: EvaluationReport,
) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _read_index(index_path)
    existing_entries = payload.get("entries", [])
    if not isinstance(existing_entries, list):
        existing_entries = []
    entries = [
        entry
        for entry in existing_entries
        if isinstance(entry, dict) and entry.get("run_id") != run.id
    ]
    entries.insert(
        0,
        {
            "run_id": run.id,
            "topic": run.topic,
            "slug": draft.slug,
            "title": draft.title,
            "url": public_url,
            "provider": provider,
            "published_at": datetime.now(UTC).isoformat(),
            "quality": {
                "publish_ready": report.publish_ready,
                "groundedness": report.groundedness,
                "source_coverage": report.source_coverage,
                "source_quality": report.source_quality,
                "career_relevance": report.career_relevance,
                "technical_depth": report.technical_depth,
            },
        },
    )
    payload["schema_version"] = 1
    payload["updated_at"] = datetime.now(UTC).isoformat()
    payload["entries"] = entries
    index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_index(index_path: Path) -> dict[str, object]:
    if not index_path.exists():
        return {"schema_version": 1, "entries": []}
    try:
        payload: Any = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": 1, "entries": []}
    if not isinstance(payload, dict):
        return {"schema_version": 1, "entries": []}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        payload["entries"] = []
    return payload
