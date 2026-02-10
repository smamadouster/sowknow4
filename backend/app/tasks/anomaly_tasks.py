"""
Celery tasks for anomaly detection and scheduled reports
"""
from celery import shared_task
from app.celery_app import celery_app
import logging
from datetime import datetime, timedelta
from typing import List

logger = logging.getLogger(__name__)


@shared_task(name="app.tasks.anomaly_tasks.daily_anomaly_report")
def daily_anomaly_report():
    """
    Generate daily anomaly report for documents stuck in processing > 24h
    Scheduled to run at 09:00 AM daily via Celery Beat

    Returns:
        dict with anomaly report data
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.models.processing import ProcessingQueue, TaskType, TaskStatus

    db = SessionLocal()
    try:
        # Find documents stuck in processing for > 24 hours
        cutoff_time = datetime.utcnow() - timedelta(hours=24)

        stuck_documents = db.query(Document).join(
            ProcessingQueue,
            Document.id == ProcessingQueue.document_id
        ).filter(
            Document.status == DocumentStatus.PROCESSING,
            ProcessingQueue.created_at < cutoff_time,
            ProcessingQueue.status.in_([TaskStatus.IN_PROGRESS, TaskStatus.PENDING])
        ).all()

        anomalies = []
        for doc in stuck_documents:
            processing_task = db.query(ProcessingQueue).filter(
                ProcessingQueue.document_id == doc.id
            ).first()

            duration_hours = (datetime.utcnow() - doc.created_at).total_seconds() / 3600

            anomaly = {
                "document_id": str(doc.id),
                "filename": doc.filename,
                "bucket": doc.bucket.value,
                "status": doc.status.value,
                "created_at": doc.created_at.isoformat(),
                "stuck_duration_hours": round(duration_hours, 2),
                "last_task_type": processing_task.task_type.value if processing_task else None,
                "error_message": processing_task.error_message if processing_task else None
            }
            anomalies.append(anomaly)

        report = {
            "date": datetime.utcnow().isoformat(),
            "total_anomalies": len(anomalies),
            "anomalies": anomalies
        }

        logger.info(f"Daily anomaly report generated: {len(anomalies)} anomalies found")

        if anomalies:
            logger.warning(f"Found {len(anomalies)} documents stuck in processing > 24h")

        return report

    except Exception as e:
        logger.error(f"Error generating anomaly report: {str(e)}")
        raise

    finally:
        db.close()


@shared_task(name="app.tasks.anomaly_tasks.system_health_check")
def system_health_check():
    """
    Perform system health checks and log any issues

    Returns:
        dict with system health status
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.models.processing import ProcessingQueue, TaskStatus
    import redis
    import os

    db = SessionLocal()
    health_status = {
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {}
    }

    try:
        # Check database connection
        try:
            db.execute("SELECT 1")
            health_status["checks"]["database"] = {"status": "healthy", "message": "Database accessible"}
        except Exception as e:
            health_status["checks"]["database"] = {"status": "unhealthy", "message": str(e)}

        # Check Redis connection
        try:
            r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
            r.ping()
            health_status["checks"]["redis"] = {"status": "healthy", "message": "Redis accessible"}
        except Exception as e:
            health_status["checks"]["redis"] = {"status": "unhealthy", "message": str(e)}

        # Check Ollama connection
        try:
            import httpx
            ollama_url = os.getenv("LOCAL_LLM_URL", "http://localhost:11434")
            response = httpx.get(f"{ollama_url}/api/tags", timeout=5)
            if response.status_code == 200:
                health_status["checks"]["ollama"] = {"status": "healthy", "message": "Ollama accessible"}
            else:
                health_status["checks"]["ollama"] = {"status": "degraded", "message": f"Status {response.status_code}"}
        except Exception as e:
            health_status["checks"]["ollama"] = {"status": "unhealthy", "message": str(e)}

        # Check document queue depth
        try:
            pending_count = db.query(ProcessingQueue).filter(
                ProcessingQueue.status == TaskStatus.PENDING
            ).count()
            processing_count = db.query(ProcessingQueue).filter(
                ProcessingQueue.status == TaskStatus.IN_PROGRESS
            ).count()

            if pending_count > 100:
                health_status["checks"]["queue_depth"] = {
                    "status": "warning",
                    "message": f"{pending_count} pending documents",
                    "pending": pending_count,
                    "processing": processing_count
                }
            else:
                health_status["checks"]["queue_depth"] = {
                    "status": "healthy",
                    "pending": pending_count,
                    "processing": processing_count
                }
        except Exception as e:
            health_status["checks"]["queue_depth"] = {"status": "error", "message": str(e)}

        logger.info(f"System health check completed: {health_status}")
        return health_status

    except Exception as e:
        logger.error(f"Error during health check: {str(e)}")
        health_status["overall_status"] = "error"
        health_status["error"] = str(e)
        return health_status

    finally:
        db.close()


@shared_task(name="app.tasks.anomaly_tasks.check_api_costs")
def check_api_costs(daily_budget_threshold: float = 10.0):
    """
    Check daily API costs and alert if approaching threshold

    Args:
        daily_budget_threshold: Daily budget threshold in USD

    Returns:
        dict with cost tracking data
    """
    # This will be implemented when cost tracking is added
    return {
        "status": "info",
        "message": "Cost tracking not yet implemented",
        "threshold": daily_budget_threshold
    }
