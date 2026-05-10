"""Task alarm notification tasks — send Web Push at alarm time."""

import logging

from sqlalchemy import func, select

from app.celery_app import celery_app
from app.core.push import send_task_alarm_push
from app.database import SessionLocal
from app.models.push_subscription import PushSubscription
from app.models.task import Task
from app.services.task_service import task_service

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.task_alarm_tasks.check_task_alarms")
def check_task_alarms() -> dict:
    """Check for tasks with pending alarms and send push notifications."""
    db = SessionLocal()
    try:
        tasks = db.execute(
            select(Task).where(
                Task.alarm_at <= func.now(),
                Task.alarm_triggered == False,
                Task.status.notin_(["completed", "cancelled"]),
            )
        ).scalars().all()

        sent = 0
        failed = 0
        skipped = 0

        for task in tasks:
            # Get user's push subscriptions
            subs = db.execute(
                select(PushSubscription).where(PushSubscription.user_id == task.user_id)
            ).scalars().all()

            if not subs:
                skipped += 1
                # Mark as triggered even if no subscriptions to avoid re-checking
                task.alarm_triggered = True
                db.commit()
                continue

            any_sent = False
            for sub in subs:
                ok = send_task_alarm_push(
                    endpoint=sub.endpoint,
                    p256dh=sub.p256dh,
                    auth=sub.auth,
                    task_title=task.title,
                    task_notes=task.notes,
                )
                if ok:
                    any_sent = True
                else:
                    # Subscription may be expired — delete it
                    db.delete(sub)

            if any_sent:
                sent += 1
            else:
                failed += 1

            task.alarm_triggered = True
            db.commit()

        return {"sent": sent, "failed": failed, "skipped": skipped, "total_checked": len(tasks)}
    except Exception as exc:
        logger.exception("Task alarm check failed")
        return {"sent": 0, "failed": 0, "skipped": 0, "error": str(exc)}
    finally:
        db.close()
