from pydantic import BaseModel, EmailStr, validator
from uuid import UUID
from datetime import datetime
from typing import Optional, List
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


class UserManagementResponse(BaseModel):
    """User management response"""
    id: UUID
    email: EmailStr
    full_name: Optional[str] = None
    role: UserRole
    is_active: bool
    can_access_confidential: bool
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """Paginated user list response"""
    users: List[UserManagementResponse]
    total: int
    page: int
    page_size: int


class UserUpdateByAdmin(BaseModel):
    """Admin-only user update schema"""
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    can_access_confidential: Optional[bool] = None
    is_active: Optional[bool] = None

    @validator('role')
    def validate_role_change(cls, v, values):
        """Prevent role changes that would leave no admin"""
        # This will be validated in the endpoint
        return v


class UserCreateByAdmin(BaseModel):
    """Admin-only user creation schema"""
    email: EmailStr
    full_name: Optional[str] = None
    password: str
    role: UserRole = UserRole.USER
    can_access_confidential: bool = False

    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v


class AuditLogEntry(BaseModel):
    """Audit log entry"""
    id: UUID
    user_id: Optional[UUID] = None
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    details: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime
    user_email: Optional[str] = None  # Joined from user table

    class Config:
        from_attributes = True


class AuditLogResponse(BaseModel):
    """Audit log response with pagination"""
    logs: List[AuditLogEntry]
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
    """Admin password reset schema"""
    new_password: str

    @validator('new_password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v
