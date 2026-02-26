"""
Admin API endpoints for user management, dashboard, stats, and audit logging
"""

from fastapi import status, APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, and_, or_, desc, select, text
from datetime import datetime, timedelta
from typing import List, Optional
import uuid
import json
import os

from app.database import get_db
from app.models.user import User, UserRole
from app.models.document import Document, DocumentStatus, DocumentBucket
from app.models.chat import ChatSession
from app.models.processing import ProcessingQueue, TaskStatus, TaskType
from app.models.audit import AuditLog, AuditAction
from app.schemas.admin import (
    PasswordReset,
    SystemStats,
    QueueStats,
    AnomalyDocument,
    AnomalyBucketResponse,
    DashboardResponse,
    UserManagementResponse,
    UserListResponse,
    UserUpdateByAdmin,
    UserCreateByAdmin,
    AuditLogResponse,
    AuditLogEntry,
    AdminStatsResponse,
)
from app.api.deps import require_admin_only
from app.utils.security import get_password_hash
from app.schemas.user import UserPublic

router = APIRouter(prefix="/admin", tags=["admin"])


async def create_audit_log(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: AuditAction,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None,
    request: Optional[Request] = None,
):
    """Helper function to create audit log entries."""
    try:
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            details=json.dumps(details) if details else None,
            ip_address=request.client.host if request else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
        db.add(audit_entry)
        await db.commit()
    except Exception as e:
        await db.rollback()
        print(f"Audit logging failed: {str(e)}")


# ============================================================================
# USER MANAGEMENT ENDPOINTS (Admin Only - SuperUser gets 403)
# ============================================================================


@router.get("/users", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by email or name"),
    role: Optional[UserRole] = Query(None, description="Filter by role"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """List all users with pagination and filtering (Admin only)."""
    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.SYSTEM_ACTION,
        resource_type="user_list",
        details={
            "page": page,
            "page_size": page_size,
            "search": search,
            "role": role.value if role else None,
        },
        request=request,
    )

    # Build base query
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)

    if search:
        search_pattern = f"%{search}%"
        condition = or_(User.email.ilike(search_pattern), User.full_name.ilike(search_pattern))
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    if role:
        stmt = stmt.where(User.role == role)
        count_stmt = count_stmt.where(User.role == role)

    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
        count_stmt = count_stmt.where(User.is_active == is_active)

    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        stmt.order_by(User.created_at.desc()).offset(offset).limit(page_size)
    )
    users = result.scalars().all()

    return UserListResponse(
        users=[UserManagementResponse.model_validate(user) for user in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/users/{user_id}", response_model=UserManagementResponse)
async def get_user_details(
    user_id: uuid.UUID,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """Get detailed information about a specific user (Admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.SYSTEM_ACTION,
        resource_type="user",
        resource_id=str(user_id),
        request=request,
    )

    return UserManagementResponse.model_validate(user)


@router.post("/users", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreateByAdmin,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """Create a new user (Admin only)."""
    result = await db.execute(select(User).where(User.email == user_data.email))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User with this email already exists"
        )

    hashed_password = get_password_hash(user_data.password)

    new_user = User(
        email=user_data.email,
        hashed_password=hashed_password,
        full_name=user_data.full_name,
        role=user_data.role,
        can_access_confidential=user_data.can_access_confidential,
        is_active=True,
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.USER_CREATED,
        resource_type="user",
        resource_id=str(new_user.id),
        details={
            "email": user_data.email,
            "role": user_data.role.value,
            "can_access_confidential": user_data.can_access_confidential,
        },
        request=request,
    )

    return UserPublic.from_orm(new_user)


@router.put("/users/{user_id}", response_model=UserManagementResponse)
async def update_user(
    user_id: uuid.UUID,
    updates: UserUpdateByAdmin,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """Update user role, status, or permissions (Admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.id == current_user.id and updates.role is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify your own role")

    changes = {}

    if updates.role is not None and user.role != updates.role:
        if user.role == UserRole.ADMIN and updates.role != UserRole.ADMIN:
            count_result = await db.execute(
                select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
            )
            admin_count = count_result.scalar_one()
            if admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot change role: At least one admin must remain",
                )

        old_role = user.role.value
        user.role = updates.role
        changes["role"] = {"old": old_role, "new": updates.role.value}

    if (
        updates.can_access_confidential is not None
        and user.can_access_confidential != updates.can_access_confidential
    ):
        user.can_access_confidential = updates.can_access_confidential
        changes["can_access_confidential"] = {
            "old": not updates.can_access_confidential,
            "new": updates.can_access_confidential,
        }

    if updates.is_active is not None and user.is_active != updates.is_active:
        user.is_active = updates.is_active
        changes["is_active"] = {"old": not updates.is_active, "new": updates.is_active}

    if updates.full_name is not None and user.full_name != updates.full_name:
        old_name = user.full_name
        user.full_name = updates.full_name
        changes["full_name"] = {"old": old_name, "new": updates.full_name}

    if changes:
        await db.commit()
        await db.refresh(user)

        await create_audit_log(
            db=db,
            user_id=current_user.id,
            action=AuditAction.USER_UPDATED,
            resource_type="user",
            resource_id=str(user_id),
            details=changes,
            request=request,
        )

    return UserManagementResponse.model_validate(user)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """Delete a user (Admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")

    if user.role == UserRole.ADMIN:
        count_result = await db.execute(
            select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
        )
        admin_count = count_result.scalar_one()
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete user: At least one admin must remain",
            )

    user_info = {
        "email": user.email,
        "role": user.role.value,
        "full_name": user.full_name,
    }

    await db.delete(user)
    await db.commit()

    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.USER_DELETED,
        resource_type="user",
        resource_id=str(user_id),
        details=user_info,
        request=request,
    )

    return {"message": "User deleted successfully"}


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: uuid.UUID,
    password_data: PasswordReset,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """Reset a user's password (Admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.hashed_password = get_password_hash(password_data.new_password)
    await db.commit()

    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.USER_UPDATED,
        resource_type="user",
        resource_id=str(user_id),
        details={"action": "password_reset"},
        request=request,
    )

    return {"message": "Password reset successfully"}


# ============================================================================
# AUDIT LOG ENDPOINTS (Admin Only)
# ============================================================================


@router.get("/audit", response_model=AuditLogResponse)
async def get_audit_logs(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    user_id: Optional[uuid.UUID] = Query(None, description="Filter by user ID"),
    days: Optional[int] = Query(30, ge=1, le=365, description="Number of days to look back"),
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """Get audit log for confidential access and admin actions (Admin only)."""
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    stmt = (
        select(
            AuditLog.id,
            AuditLog.user_id,
            AuditLog.action,
            AuditLog.resource_type,
            AuditLog.resource_id,
            AuditLog.details,
            AuditLog.ip_address,
            AuditLog.created_at,
            User.email.label("user_email"),
        )
        .outerjoin(User, AuditLog.user_id == User.id)
        .where(AuditLog.created_at >= cutoff_date)
    )
    count_stmt = (
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.created_at >= cutoff_date)
    )

    if action:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)

    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
        count_stmt = count_stmt.where(AuditLog.resource_type == resource_type)

    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
        count_stmt = count_stmt.where(AuditLog.user_id == user_id)

    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        stmt.order_by(desc(AuditLog.created_at)).offset(offset).limit(page_size)
    )
    logs = result.all()

    log_entries = [
        AuditLogEntry(
            id=log.id,
            user_id=log.user_id,
            action=log.action.value,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            details=log.details,
            ip_address=log.ip_address,
            created_at=log.created_at,
            user_email=log.user_email,
        )
        for log in logs
    ]

    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.SYSTEM_ACTION,
        resource_type="audit_log",
        details={
            "page": page,
            "page_size": page_size,
            "filters": {
                "action": action,
                "resource_type": resource_type,
                "user_id": str(user_id) if user_id else None,
                "days": days,
            },
        },
        request=request,
    )

    return AuditLogResponse(logs=log_entries, total=total, page=page, page_size=page_size)


# ============================================================================
# SYSTEM STATISTICS ENDPOINTS (Admin Only)
# ============================================================================


@router.get("/stats", response_model=SystemStats)
async def get_system_stats(
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
):
    """Get system statistics for admin dashboard (Admin only)."""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    async def count(stmt):
        r = await db.execute(stmt)
        return r.scalar_one()

    total_documents = await count(select(func.count(Document.id)))
    public_documents = await count(
        select(func.count(Document.id)).where(Document.bucket == DocumentBucket.PUBLIC)
    )
    confidential_documents = await count(
        select(func.count(Document.id)).where(Document.bucket == DocumentBucket.CONFIDENTIAL)
    )
    indexed_documents = await count(
        select(func.count(Document.id)).where(Document.status == DocumentStatus.INDEXED)
    )
    processing_documents = await count(
        select(func.count(Document.id)).where(Document.status == DocumentStatus.PROCESSING)
    )
    error_documents = await count(
        select(func.count(Document.id)).where(Document.status == DocumentStatus.ERROR)
    )

    from app.models.document import DocumentTag, DocumentChunk

    total_chunks = await count(select(func.count(DocumentChunk.id)))
    total_tags = await count(select(func.count(DocumentTag.id)))
    uploads_today = await count(
        select(func.count(Document.id)).where(Document.created_at >= today)
    )
    total_users = await count(select(func.count(User.id)))
    active_sessions = await count(
        select(func.count(ChatSession.id)).where(
            ChatSession.updated_at >= datetime.utcnow() - timedelta(hours=24)
        )
    )

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
        active_sessions=active_sessions,
    )


@router.get("/stats/extended", response_model=AdminStatsResponse)
async def get_extended_admin_stats(
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
):
    """Get extended admin statistics (Admin only)."""
    async def count(stmt):
        r = await db.execute(stmt)
        return r.scalar_one()

    total_users = await count(select(func.count(User.id)))
    active_users = await count(select(func.count(User.id)).where(User.is_active == True))
    admin_count = await count(select(func.count(User.id)).where(User.role == UserRole.ADMIN))
    superuser_count = await count(
        select(func.count(User.id)).where(User.role == UserRole.SUPERUSER)
    )
    regular_user_count = await count(
        select(func.count(User.id)).where(User.role == UserRole.USER)
    )
    confidential_access_users = await count(
        select(func.count(User.id)).where(User.can_access_confidential == True)
    )
    total_audit_logs = await count(select(func.count(AuditLog.id)))

    week_ago = datetime.utcnow() - timedelta(days=7)
    recent_admin_actions = await count(
        select(func.count(AuditLog.id)).where(AuditLog.created_at >= week_ago)
    )

    health_status = {
        "database": "healthy",
        "redis": "unknown",
        "gemini": "unknown",
        "ollama": "unknown",
    }

    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        health_status["database"] = "unhealthy"

    try:
        import redis

        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        health_status["redis"] = "healthy"
    except Exception:
        health_status["redis"] = "unhealthy"

    return AdminStatsResponse(
        total_users=total_users,
        active_users=active_users,
        admin_count=admin_count,
        superuser_count=superuser_count,
        regular_user_count=regular_user_count,
        confidential_access_users=confidential_access_users,
        total_audit_logs=total_audit_logs,
        recent_admin_actions=recent_admin_actions,
        system_health=health_status,
    )


@router.get("/queue-stats", response_model=QueueStats)
async def get_queue_stats(
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
):
    """Get processing queue statistics."""
    async def count(stmt):
        r = await db.execute(stmt)
        return r.scalar_one()

    pending_tasks = await count(
        select(func.count(ProcessingQueue.id)).where(
            ProcessingQueue.status == TaskStatus.PENDING
        )
    )
    in_progress_tasks = await count(
        select(func.count(ProcessingQueue.id)).where(
            ProcessingQueue.status == TaskStatus.IN_PROGRESS
        )
    )
    completed_tasks = await count(
        select(func.count(ProcessingQueue.id)).where(
            ProcessingQueue.status == TaskStatus.COMPLETED
        )
    )
    failed_tasks = await count(
        select(func.count(ProcessingQueue.id)).where(
            ProcessingQueue.status == TaskStatus.FAILED
        )
    )

    pending_result = await db.execute(
        select(ProcessingQueue).where(ProcessingQueue.status == TaskStatus.PENDING)
    )
    pending_with_created = pending_result.scalars().all()

    if pending_with_created:
        total_wait_minutes = sum(
            (datetime.utcnow() - task.created_at).total_seconds() / 60
            for task in pending_with_created
        )
        average_wait_time = total_wait_minutes / len(pending_with_created)
    else:
        average_wait_time = None

    longest_result = await db.execute(
        select(ProcessingQueue)
        .where(ProcessingQueue.status == TaskStatus.IN_PROGRESS)
        .order_by(ProcessingQueue.started_at.asc())
        .limit(1)
    )
    longest_running = longest_result.scalar_one_or_none()

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
        longest_running_task=longest_running_task,
    )


@router.get("/anomalies", response_model=AnomalyBucketResponse)
async def get_anomalies(
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
):
    """Get documents stuck in processing for more than 24 hours."""
    cutoff_time = datetime.utcnow() - timedelta(hours=24)

    stuck_result = await db.execute(
        select(Document)
        .join(ProcessingQueue, Document.id == ProcessingQueue.document_id)
        .where(
            Document.status == DocumentStatus.PROCESSING,
            ProcessingQueue.created_at < cutoff_time,
            ProcessingQueue.status.in_([TaskStatus.IN_PROGRESS, TaskStatus.PENDING]),
        )
    )
    stuck_documents = stuck_result.scalars().all()

    anomalies = []
    for doc in stuck_documents:
        task_result = await db.execute(
            select(ProcessingQueue).where(ProcessingQueue.document_id == doc.id).limit(1)
        )
        processing_task = task_result.scalar_one_or_none()

        duration_hours = (datetime.utcnow() - doc.created_at).total_seconds() / 3600

        anomalies.append(
            AnomalyDocument(
                document_id=doc.id,
                filename=doc.filename,
                bucket=doc.bucket.value,
                status=doc.status.value,
                created_at=doc.created_at,
                stuck_duration_hours=round(duration_hours, 2),
                last_task_type=processing_task.task_type.value if processing_task else None,
                error_message=processing_task.error_message if processing_task else None,
            )
        )

    return AnomalyBucketResponse(
        date=datetime.utcnow().isoformat(),
        total_anomalies=len(anomalies),
        anomalies=anomalies,
    )


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
):
    """Get complete admin dashboard data."""
    stats = await get_system_stats(current_user, db)
    queue_stats = await get_queue_stats(current_user, db)

    health_status = {
        "database": "healthy",
        "redis": "unknown",
        "ollama": "unknown",
        "kimi_api": "unknown",
    }

    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        health_status["database"] = "unhealthy"

    try:
        import redis

        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        health_status["redis"] = "healthy"
    except Exception:
        health_status["redis"] = "unhealthy"

    try:
        import httpx

        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{ollama_url}/api/tags", timeout=2.0)
            health_status["ollama"] = "healthy" if response.status_code == 200 else "degraded"
    except Exception:
        health_status["ollama"] = "unreachable"

    if os.getenv("KIMI_API_KEY"):
        health_status["kimi_api"] = "configured"
    else:
        health_status["kimi_api"] = "not_configured"

    return DashboardResponse(
        stats=stats,
        queue_stats=queue_stats,
        system_health=health_status,
        last_updated=datetime.utcnow(),
    )


# ============================================================================
# DEAD LETTER QUEUE ENDPOINTS (Admin Only)
# ============================================================================


@router.get("/failed-tasks")
async def list_failed_tasks(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    task_name: Optional[str] = Query(None, description="Filter by task name"),
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
):
    """List permanently failed Celery tasks in the Dead Letter Queue (Admin only)."""
    from app.models.failed_task import FailedCeleryTask

    stmt = select(FailedCeleryTask)
    count_stmt = select(func.count()).select_from(FailedCeleryTask)

    if task_name:
        condition = FailedCeleryTask.task_name.ilike(f"%{task_name}%")
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    result = await db.execute(
        stmt.order_by(desc(FailedCeleryTask.failed_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": str(item.id),
                "task_name": item.task_name,
                "task_id": item.task_id,
                "exception_type": item.exception_type,
                "exception_message": item.exception_message,
                "retry_count": item.retry_count,
                "failed_at": item.failed_at.isoformat() if item.failed_at else None,
                "metadata": item.task_metadata,
            }
            for item in items
        ],
    }


@router.get("/failed-tasks/{task_id}")
async def get_failed_task(
    task_id: str,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
):
    """Get a single failed task with full traceback (Admin only)."""
    from app.models.failed_task import FailedCeleryTask

    result = await db.execute(
        select(FailedCeleryTask).where(FailedCeleryTask.task_id == task_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Failed task not found")

    return {
        "id": str(item.id),
        "task_name": item.task_name,
        "task_id": item.task_id,
        "args": item.args,
        "kwargs": item.kwargs,
        "exception_type": item.exception_type,
        "exception_message": item.exception_message,
        "traceback": item.traceback,
        "retry_count": item.retry_count,
        "failed_at": item.failed_at.isoformat() if item.failed_at else None,
        "metadata": item.task_metadata,
    }


@router.delete("/failed-tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_failed_task(
    task_id: str,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single failed task from the DLQ (Admin only)."""
    from app.models.failed_task import FailedCeleryTask

    result = await db.execute(
        select(FailedCeleryTask).where(FailedCeleryTask.task_id == task_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Failed task not found")

    await db.delete(item)
    await db.commit()


# ============================================================================
# ALERT TEST ENDPOINT (Admin Only)
# ============================================================================


@router.post("/test-alert")
async def test_alert(
    severity: str = "HIGH",
    current_user: User = Depends(require_admin_only),
):
    """Send a test alert to all configured notification channels."""
    from app.services.alert_service import alert_service

    valid = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}
    if severity.upper() not in valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid severity. Must be one of: {', '.join(sorted(valid))}",
        )

    results = await alert_service.send_alert(
        message="This is a test alert sent from the SOWKNOW admin panel.",
        severity=severity.upper(),
        title="Test Alert",
        metadata={
            "triggered_by": str(current_user.email),
            "admin_id": str(current_user.id),
        },
    )

    return {
        "status": "sent",
        "severity": severity.upper(),
        "channels_attempted": list(results.keys()),
        "results": results,
        "telegram_configured": alert_service.telegram_configured,
        "email_configured": alert_service.email_configured,
    }
