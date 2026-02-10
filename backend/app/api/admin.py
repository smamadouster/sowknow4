"""
Admin API endpoints for dashboard, stats, and anomaly monitoring
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timedelta
from typing import List

from app.database import get_db
from app.models.user import User, UserRole
from app.models.document import Document, DocumentStatus, DocumentBucket
from app.models.chat import ChatSession
from app.models.processing import ProcessingQueue, TaskStatus, TaskType
from app.schemas.admin import (
    SystemStats,
    QueueStats,
    AnomalyDocument,
    AnomalyBucketResponse,
    DashboardResponse
)
from app.utils.security import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=SystemStats)
async def get_system_stats(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get system statistics for admin dashboard"""
    # Get today's date
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Document counts
    total_documents = db.query(func.count(Document.id)).scalar()
    public_documents = db.query(func.count(Document.id)).filter(
        Document.bucket == DocumentBucket.PUBLIC
    ).scalar()
    confidential_documents = db.query(func.count(Document.id)).filter(
        Document.bucket == DocumentBucket.CONFIDENTIAL
    ).scalar()
    indexed_documents = db.query(func.count(Document.id)).filter(
        Document.status == DocumentStatus.INDEXED
    ).scalar()
    processing_documents = db.query(func.count(Document.id)).filter(
        Document.status == DocumentStatus.PROCESSING
    ).scalar()
    error_documents = db.query(func.count(Document.id)).filter(
        Document.status == DocumentStatus.ERROR
    ).scalar()

    # Get chunk and tag counts from their respective tables
    from app.models.document import DocumentTag, DocumentChunk
    total_chunks = db.query(func.count(DocumentChunk.id)).scalar()
    total_tags = db.query(func.count(DocumentTag.id)).scalar()

    # Uploads today
    uploads_today = db.query(func.count(Document.id)).filter(
        Document.created_at >= today
    ).scalar()

    # User count
    total_users = db.query(func.count(User.id)).scalar()

    # Active sessions (last 24 hours)
    active_sessions = db.query(func.count(ChatSession.id)).filter(
        ChatSession.updated_at >= datetime.utcnow() - timedelta(hours=24)
    ).scalar()

    return SystemStats(
        total_documents=total_documents,
        public_documents=public_documents,
        confidential_documents=confidential_documents,
        indexed_documents=indexed_documents,
        processing_documents=processing_documents,
        error_documents=error_documents,
        total_chunks=total_chunks,
        total_tags=total_tags,
        uploads_today=uploads_today,
        total_users=total_users,
        active_sessions=active_sessions
    )


@router.get("/queue-stats", response_model=QueueStats)
async def get_queue_stats(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get processing queue statistics"""
    # Count tasks by status
    pending_tasks = db.query(func.count(ProcessingQueue.id)).filter(
        ProcessingQueue.status == TaskStatus.PENDING
    ).scalar()
    in_progress_tasks = db.query(func.count(ProcessingQueue.id)).filter(
        ProcessingQueue.status == TaskStatus.IN_PROGRESS
    ).scalar()
    completed_tasks = db.query(func.count(ProcessingQueue.id)).filter(
        ProcessingQueue.status == TaskStatus.COMPLETED
    ).scalar()
    failed_tasks = db.query(func.count(ProcessingQueue.id)).filter(
        ProcessingQueue.status == TaskStatus.FAILED
    ).scalar()

    # Calculate average wait time for pending tasks
    pending_with_created = db.query(ProcessingQueue).filter(
        ProcessingQueue.status == TaskStatus.PENDING
    ).all()

    if pending_with_created:
        total_wait_minutes = sum(
            (datetime.utcnow() - task.created_at).total_seconds() / 60
            for task in pending_with_created
        )
        average_wait_time = total_wait_minutes / len(pending_with_created)
    else:
        average_wait_time = None

    # Find longest running task
    longest_running = db.query(ProcessingQueue).filter(
        ProcessingQueue.status == TaskStatus.IN_PROGRESS
    ).order_by(ProcessingQueue.started_at.asc()).first()

    longest_running_task = None
    if longest_running and longest_running.started_at:
        duration = (datetime.utcnow() - longest_running.started_at).total_seconds() / 60
        longest_running_task = f"{longest_running.task_type.value} - {duration:.1f}m"

    return QueueStats(
        pending_tasks=pending_tasks,
        in_progress_tasks=in_progress_tasks,
        completed_tasks=completed_tasks,
        failed_tasks=failed_tasks,
        average_wait_time=average_wait_time,
        longest_running_task=longest_running_task
    )


@router.get("/anomalies", response_model=AnomalyBucketResponse)
async def get_anomalies(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Get documents stuck in processing for more than 24 hours

    This is the same report generated by the daily Celery Beat task
    """
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

        anomalies.append(AnomalyDocument(
            document_id=doc.id,
            filename=doc.filename,
            bucket=doc.bucket.value,
            status=doc.status.value,
            created_at=doc.created_at,
            stuck_duration_hours=round(duration_hours, 2),
            last_task_type=processing_task.task_type.value if processing_task else None,
            error_message=processing_task.error_message if processing_task else None
        ))

    return AnomalyBucketResponse(
        date=datetime.utcnow().isoformat(),
        total_anomalies=len(anomalies),
        anomalies=anomalies
    )


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get complete admin dashboard data"""
    stats = await get_system_stats(current_user, db)
    queue_stats = await get_queue_stats(current_user, db)

    # System health check
    health_status = {
        "database": "healthy",
        "redis": "unknown",
        "ollama": "unknown",
        "moonshot_api": "unknown"
    }

    # Check database
    try:
        db.execute("SELECT 1")
    except:
        health_status["database"] = "unhealthy"

    # Check Redis
    try:
        import redis
        import os
        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        health_status["redis"] = "healthy"
    except:
        health_status["redis"] = "unhealthy"

    # Check Ollama
    try:
        import httpx
        ollama_url = os.getenv("LOCAL_LLM_URL", "http://localhost:11434")
        response = httpx.get(f"{ollama_url}/api/tags", timeout=2)
        if response.status_code == 200:
            health_status["ollama"] = "healthy"
        else:
            health_status["ollama"] = "degraded"
    except:
        health_status["ollama"] = "unreachable"

    # Check Moonshot API
    if os.getenv("MOONSHOT_API_KEY"):
        health_status["moonshot_api"] = "configured"
    else:
        health_status["moonshot_api"] = "not_configured"

    return DashboardResponse(
        stats=stats,
        queue_stats=queue_stats,
        system_health=health_status,
        last_updated=datetime.utcnow()
    )
