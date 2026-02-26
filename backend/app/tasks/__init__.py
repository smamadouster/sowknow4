# Celery tasks initialization
from app.tasks import document_tasks
from app.tasks import anomaly_tasks
from app.tasks import embedding_tasks
from app.tasks import report_tasks

__all__ = ["document_tasks", "anomaly_tasks", "embedding_tasks", "report_tasks"]
