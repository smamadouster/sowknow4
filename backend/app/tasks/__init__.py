# Celery tasks initialization
from app.tasks import document_tasks
from app.tasks import anomaly_tasks

__all__ = ["document_tasks", "anomaly_tasks"]
