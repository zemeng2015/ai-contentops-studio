from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class RunTrace:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def add(self, step: str, status: str, **fields: Any) -> None:
        self.events.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "step": step,
                "status": status,
                **fields,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {"events": self.events}

