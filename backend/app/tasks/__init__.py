# Celery tasks initialization
from app.tasks import anomaly_tasks, document_tasks, embedding_tasks, report_tasks

__all__ = ["document_tasks", "anomaly_tasks", "embedding_tasks", "report_tasks"]
