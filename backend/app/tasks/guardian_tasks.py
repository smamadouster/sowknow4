"""Guardian probe tasks — lightweight health verification."""
from celery import shared_task
from datetime import datetime, timezone


@shared_task(bind=True, name="app.tasks.guardian_tasks.guardian_ping")
def guardian_ping(self) -> dict:
    return {
        "status": "pong",
        "worker": self.request.hostname,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_id": self.request.id,
    }
