from __future__ import annotations

from typing import Protocol

import httpx

from contentops_core.models import AuditEvent, NotificationDelivery, RunRecord


class NotificationPublisher(Protocol):
    def notify(self, run: RunRecord, event: AuditEvent) -> NotificationDelivery:
        """Deliver an operator event and return an auditable delivery receipt."""


class LocalNotificationPublisher:
    def notify(self, run: RunRecord, event: AuditEvent) -> NotificationDelivery:
        return NotificationDelivery(
            run_id=run.id,
            action=event.action,
            provider="local",
            status="skipped",
        )


class WebhookNotificationPublisher:
    def __init__(self, endpoint: str, timeout_seconds: float = 5.0) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def notify(self, run: RunRecord, event: AuditEvent) -> NotificationDelivery:
        payload = {
            "run": {
                "id": run.id,
                "topic": run.topic,
                "slug": run.slug,
                "status": run.status.value,
                "published_url": run.published_url,
            },
            "event": event.model_dump(mode="json"),
        }
        try:
            response = httpx.post(
                self.endpoint,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            return NotificationDelivery(
                run_id=run.id,
                action=event.action,
                provider="webhook",
                status="failed",
                endpoint=self.endpoint,
                error=str(exc),
            )
        return NotificationDelivery(
            run_id=run.id,
            action=event.action,
            provider="webhook",
            status="delivered" if response.is_success else "failed",
            endpoint=self.endpoint,
            status_code=response.status_code,
            error=None if response.is_success else response.text[:500],
        )
