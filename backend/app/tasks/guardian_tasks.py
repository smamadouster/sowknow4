"""Guardian probe tasks — lightweight health verification."""
from datetime import UTC, datetime

from celery import shared_task


@shared_task(bind=True, name="app.tasks.guardian_tasks.guardian_ping")
def guardian_ping(self) -> dict:
    return {
        "status": "pong",
        "worker": self.request.hostname,
        "timestamp": datetime.now(UTC).isoformat(),
        "task_id": self.request.id,
    }
