from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from contentops_core.models import RunMetrics, RunRecord, StepMetric, TraceEvent


class MetricsService:
    def run_metrics(self, run: RunRecord) -> RunMetrics:
        events = self._load_events(run)
        started_by_step: dict[str, TraceEvent] = {}
        step_metrics: list[StepMetric] = []
        total_start: datetime | None = None
        total_end: datetime | None = None
        source_count = 0
        publish_ready: bool | None = None

        for event in events:
            total_start = total_start or event.timestamp
            total_end = event.timestamp
            if event.step == "research" and event.status == "completed":
                source_count = int(event.fields.get("sources", 0))
            if event.step == "evaluation" and event.status == "completed":
                value = event.fields.get("publish_ready")
                publish_ready = bool(value) if isinstance(value, bool) else None
            if event.status == "started":
                started_by_step[event.step] = event
                continue
            start = started_by_step.get(event.step)
            duration_ms = None
            if start is not None:
                duration_ms = int((event.timestamp - start.timestamp).total_seconds() * 1000)
            step_metrics.append(
                StepMetric(
                    step=event.step,
                    status=event.status,
                    duration_ms=duration_ms,
                    fields=event.fields,
                )
            )

        total_duration_ms = None
        if total_start is not None and total_end is not None:
            total_duration_ms = int((total_end - total_start).total_seconds() * 1000)
        return RunMetrics(
            run_id=run.id,
            status=run.status,
            total_duration_ms=total_duration_ms,
            source_count=source_count,
            publish_ready=publish_ready,
            step_metrics=step_metrics,
        )

    def _load_events(self, run: RunRecord) -> list[TraceEvent]:
        path = run.artifact_dir / "trace.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        events: list[TraceEvent] = []
        for raw in data.get("events", []):
            if not isinstance(raw, dict):
                continue
            timestamp = raw.get("timestamp")
            step = raw.get("step")
            status = raw.get("status")
            if (
                not isinstance(timestamp, str)
                or not isinstance(step, str)
                or not isinstance(status, str)
            ):
                continue
            fields: dict[str, Any] = {
                key: value
                for key, value in raw.items()
                if key not in {"timestamp", "step", "status"}
            }
            events.append(
                TraceEvent(
                    timestamp=datetime.fromisoformat(timestamp),
                    step=step,
                    status=status,
                    fields=fields,
                )
            )
        return events
