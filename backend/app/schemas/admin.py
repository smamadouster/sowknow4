from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, List


class SystemStats(BaseModel):
    """System statistics for admin dashboard"""
    total_documents: int
    public_documents: int
    confidential_documents: int
    indexed_documents: int
    processing_documents: int
    error_documents: int
    total_chunks: int
    total_tags: int
    uploads_today: int
    total_users: int
    active_sessions: int


class QueueStats(BaseModel):
    """Processing queue statistics"""
    pending_tasks: int
    in_progress_tasks: int
    completed_tasks: int
    failed_tasks: int
    average_wait_time: Optional[float] = None  # in minutes
    longest_running_task: Optional[str] = None


class AnomalyDocument(BaseModel):
    """Documents stuck in processing for >24h"""
    document_id: UUID
    filename: str
    bucket: str
    status: str
    created_at: datetime
    stuck_duration_hours: float
    last_task_type: Optional[str] = None
    error_message: Optional[str] = None


class AnomalyBucketResponse(BaseModel):
    """Daily anomaly report response"""
    date: str
    total_anomalies: int
    anomalies: List[AnomalyDocument]


class DashboardResponse(BaseModel):
    """Complete admin dashboard data"""
    stats: SystemStats
    queue_stats: QueueStats
    system_health: dict
    last_updated: datetime
