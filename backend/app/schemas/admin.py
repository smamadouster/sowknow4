import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, validator

from app.schemas.user import UserRole


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
    average_wait_time: float | None = None  # in minutes
    longest_running_task: str | None = None


class AnomalyDocument(BaseModel):
    """Documents stuck in processing for >24h"""

    document_id: UUID
    filename: str
    bucket: str
    status: str
    created_at: datetime
    stuck_duration_hours: float
    last_task_type: str | None = None
    error_message: str | None = None


class AnomalyBucketResponse(BaseModel):
    """Daily anomaly report response"""

    date: str
    total_anomalies: int
    anomalies: list[AnomalyDocument]


class DashboardResponse(BaseModel):
    """Complete admin dashboard data"""

    stats: SystemStats
    queue_stats: QueueStats
    system_health: dict
    last_updated: datetime


class UserManagementResponse(BaseModel):
    """User management response"""

    id: UUID
    email: EmailStr
    full_name: str | None = None
    role: UserRole
    is_active: bool
    can_access_confidential: bool
    created_at: datetime
    updated_at: datetime
    last_login: datetime | None = None

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """Paginated user list response"""

    users: list[UserManagementResponse]
    total: int
    page: int
    page_size: int


class UserUpdateByAdmin(BaseModel):
    """Admin-only user update schema"""

    full_name: str | None = None
    role: UserRole | None = None
    can_access_confidential: bool | None = None
    is_active: bool | None = None

    @validator("role")
    def validate_role_change(cls, v, values):
        """Prevent role changes that would leave no admin"""
        # This will be validated in the endpoint
        return v


class UserCreateByAdmin(BaseModel):
    """Admin-only user creation schema"""

    email: EmailStr
    full_name: str | None = None
    password: str
    role: UserRole = UserRole.USER
    can_access_confidential: bool = False

    @validator("password")
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class AuditLogEntry(BaseModel):
    """Audit log entry"""

    id: UUID
    user_id: UUID | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    details: str | None = None
    ip_address: str | None = None
    created_at: datetime
    user_email: str | None = None  # Joined from user table

    class Config:
        from_attributes = True


class AuditLogResponse(BaseModel):
    """Audit log response with pagination"""

    logs: list[AuditLogEntry]
    total: int
    page: int
    page_size: int


class AdminStatsResponse(BaseModel):
    """Enhanced admin statistics"""

    total_users: int
    active_users: int
    admin_count: int
    superuser_count: int
    regular_user_count: int
    confidential_access_users: int
    total_audit_logs: int
    recent_admin_actions: int
    system_health: dict


class PasswordReset(BaseModel):
    """Admin password reset schema — enforces same complexity as user registration."""

    new_password: str

    @validator("new_password")
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least 1 uppercase letter (A-Z)")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least 1 lowercase letter (a-z)")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least 1 digit (0-9)")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]", v):
            raise ValueError(
                "Password must contain at least 1 special character (!@#$%^&*()_+-=[]{}|;:,.<>?)"
            )
        return v


class PipelineStageStats(BaseModel):
    """Counts and throughput for a single pipeline stage."""

    stage: str
    pending: int
    running: int
    failed: int
    throughput_per_hour: int
    throughput_per_10min: int
    health: str = "green"  # green | yellow | red


class PipelineStatsResponse(BaseModel):
    """Full pipeline funnel snapshot."""

    stages: list[PipelineStageStats]
    total_active: int  # sum of all running counts
    bottleneck_stage: str | None  # stage with highest pending count, or None
    overall_health: str = "green"  # green | yellow | red


class UploadsHistoryPoint(BaseModel):
    day: str  # "YYYY-MM-DD"
    count: int


class UploadsHistoryResponse(BaseModel):
    history: list[UploadsHistoryPoint]


class ArticlesHistoryPoint(BaseModel):
    day: str  # "YYYY-MM-DD"
    count: int


class ArticlesHistoryResponse(BaseModel):
    history: list[ArticlesHistoryPoint]


class ArticlesStats(BaseModel):
    total_articles: int
    indexed_articles: int
    pending_articles: int
    generating_articles: int
    error_articles: int
