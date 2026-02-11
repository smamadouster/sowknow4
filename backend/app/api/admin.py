"""
Admin API endpoints for user management, dashboard, stats, and audit logging
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, desc
from datetime import datetime, timedelta
from typing import List, Optional
import uuid
import json

from app.database import get_db
from app.models.user import User, UserRole
from app.models.document import Document, DocumentStatus, DocumentBucket
from app.models.chat import ChatSession
from app.models.processing import ProcessingQueue, TaskStatus, TaskType
from app.models.audit import AuditLog, AuditAction
from app.schemas.admin import (
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
    AdminStatsResponse
)
from app.api.deps import require_admin_only
from app.utils.security import get_password_hash
from app.schemas.user import UserPublic

router = APIRouter(prefix="/admin", tags=["admin"])


def create_audit_log(
    db: Session,
    user_id: uuid.UUID,
    action: AuditAction,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None,
    request: Optional[Request] = None
):
    """Helper function to create audit log entries"""
    try:
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            details=json.dumps(details) if details else None,
            ip_address=request.client.host if request else None,
            user_agent=request.headers.get("user-agent") if request else None
        )
        db.add(audit_entry)
        db.commit()
    except Exception as e:
        # Don't fail the main operation if audit logging fails
        db.rollback()
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
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    List all users with pagination and filtering (Admin only)

    - SuperUser will receive 403 Forbidden
    - Supports search by email or full name
    - Filter by role and active status
    - Returns paginated results
    """
    # Log the admin action
    create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.SYSTEM_ACTION,
        resource_type="user_list",
        details={"page": page, "page_size": page_size, "search": search, "role": role.value if role else None},
        request=request
    )

    # Build query
    query = db.query(User)

    # Apply search filter
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                User.email.ilike(search_pattern),
                User.full_name.ilike(search_pattern)
            )
        )

    # Apply role filter
    if role:
        query = query.filter(User.role == role)

    # Apply active status filter
    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    # Get total count
    total = query.count()

    # Apply pagination
    offset = (page - 1) * page_size
    users = query.order_by(User.created_at.desc()).offset(offset).limit(page_size).all()

    return UserListResponse(
        users=[UserManagementResponse.model_validate(user) for user in users],
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/users/{user_id}", response_model=UserManagementResponse)
async def get_user_details(
    user_id: uuid.UUID,
    current_user: User = Depends(require_admin_only),
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    Get detailed information about a specific user (Admin only)

    - SuperUser will receive 403 Forbidden
    - Returns full user details including permissions
    """
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        # Use generic error message to prevent user enumeration
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    # Log the admin action
    create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.SYSTEM_ACTION,
        resource_type="user",
        resource_id=str(user_id),
        request=request
    )

    return UserManagementResponse.model_validate(user)


@router.post("/users", response_model=UserPublic, status_code=201)
async def create_user(
    user_data: UserCreateByAdmin,
    current_user: User = Depends(require_admin_only),
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    Create a new user (Admin only)

    - SuperUser will receive 403 Forbidden
    - Admin can set initial role and permissions
    - Password must be at least 8 characters
    """
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        # Generic error message to prevent user enumeration
        raise HTTPException(
            status_code=400,
            detail="User with this email already exists"
        )

    # Hash the password
    hashed_password = get_password_hash(user_data.password)

    # Create new user
    new_user = User(
        email=user_data.email,
        hashed_password=hashed_password,
        full_name=user_data.full_name,
        role=user_data.role,
        can_access_confidential=user_data.can_access_confidential,
        is_active=True
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Log the admin action
    create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.USER_CREATED,
        resource_type="user",
        resource_id=str(new_user.id),
        details={
            "email": user_data.email,
            "role": user_data.role.value,
            "can_access_confidential": user_data.can_access_confidential
        },
        request=request
    )

    return UserPublic.from_orm(new_user)


@router.put("/users/{user_id}", response_model=UserManagementResponse)
async def update_user(
    user_id: uuid.UUID,
    updates: UserUpdateByAdmin,
    current_user: User = Depends(require_admin_only),
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    Update user role, status, or permissions (Admin only)

    - SuperUser will receive 403 Forbidden
    - Cannot modify own role (prevents locking yourself out)
    - Ensures at least one admin remains
    """
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    # Prevent self-modification of critical fields
    if user.id == current_user.id and updates.role is not None:
        raise HTTPException(
            status_code=400,
            detail="Cannot modify your own role"
        )

    # Track changes for audit log
    changes = {}

    # Update role
    if updates.role is not None and user.role != updates.role:
        # Check if this would leave no admins
        if user.role == UserRole.ADMIN and updates.role != UserRole.ADMIN:
            admin_count = db.query(func.count(User.id)).filter(User.role == UserRole.ADMIN).scalar()
            if admin_count <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot change role: At least one admin must remain"
                )

        old_role = user.role.value
        user.role = updates.role
        changes["role"] = {"old": old_role, "new": updates.role.value}

    # Update confidential access
    if updates.can_access_confidential is not None and user.can_access_confidential != updates.can_access_confidential:
        user.can_access_confidential = updates.can_access_confidential
        changes["can_access_confidential"] = {"old": not updates.can_access_confidential, "new": updates.can_access_confidential}

    # Update active status
    if updates.is_active is not None and user.is_active != updates.is_active:
        user.is_active = updates.is_active
        changes["is_active"] = {"old": not updates.is_active, "new": updates.is_active}

    # Update full name
    if updates.full_name is not None and user.full_name != updates.full_name:
        user.full_name = updates.full_name
        changes["full_name"] = {"old": user.full_name, "new": updates.full_name}

    if changes:
        db.commit()
        db.refresh(user)

        # Log the admin action
        create_audit_log(
            db=db,
            user_id=current_user.id,
            action=AuditAction.USER_UPDATED,
            resource_type="user",
            resource_id=str(user_id),
            details=changes,
            request=request
        )

    return UserManagementResponse.model_validate(user)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    current_user: User = Depends(require_admin_only),
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    Delete a user (Admin only)

    - SuperUser will receive 403 Forbidden
    - Cannot delete yourself
    - Ensures at least one admin remains
    - User's documents and collections are also deleted (cascade)
    """
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    # Prevent self-deletion
    if user.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete your own account"
        )

    # Check if this would leave no admins
    if user.role == UserRole.ADMIN:
        admin_count = db.query(func.count(User.id)).filter(User.role == UserRole.ADMIN).scalar()
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete user: At least one admin must remain"
            )

    # Store user info for audit before deletion
    user_info = {
        "email": user.email,
        "role": user.role.value,
        "full_name": user.full_name
    }

    # Delete user (cascade will handle related records)
    db.delete(user)
    db.commit()

    # Log the admin action
    create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.USER_DELETED,
        resource_type="user",
        resource_id=str(user_id),
        details=user_info,
        request=request
    )

    return {"message": "User deleted successfully"}


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
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    Get audit log for confidential access and admin actions (Admin only)

    - SuperUser will receive 403 Forbidden
    - View all administrative actions
    - Track confidential document access
    - Filterable by action, resource type, user, and date range
    """
    # Calculate date cutoff
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    # Build query with join to get user email
    query = db.query(
        AuditLog.id,
        AuditLog.user_id,
        AuditLog.action,
        AuditLog.resource_type,
        AuditLog.resource_id,
        AuditLog.details,
        AuditLog.ip_address,
        AuditLog.created_at,
        User.email.label("user_email")
    ).outerjoin(
        User, AuditLog.user_id == User.id
    ).filter(
        AuditLog.created_at >= cutoff_date
    )

    # Apply filters
    if action:
        query = query.filter(AuditLog.action == action)

    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)

    if user_id:
        query = query.filter(AuditLog.user_id == user_id)

    # Get total count
    total = query.count()

    # Apply pagination
    offset = (page - 1) * page_size
    logs = query.order_by(desc(AuditLog.created_at)).offset(offset).limit(page_size).all()

    # Format response
    log_entries = []
    for log in logs:
        log_entries.append(AuditLogEntry(
            id=log.id,
            user_id=log.user_id,
            action=log.action.value,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            details=log.details,
            ip_address=log.ip_address,
            created_at=log.created_at,
            user_email=log.user_email
        ))

    # Log this audit view access
    create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.SYSTEM_ACTION,
        resource_type="audit_log",
        details={"page": page, "page_size": page_size, "filters": {"action": action, "resource_type": resource_type, "user_id": str(user_id) if user_id else None, "days": days}},
        request=request
    )

    return AuditLogResponse(
        logs=log_entries,
        total=total,
        page=page,
        page_size=page_size
    )


# ============================================================================
# SYSTEM STATISTICS ENDPOINTS (Admin Only)
# ============================================================================

@router.get("/stats", response_model=SystemStats)
async def get_system_stats(
    current_user: User = Depends(require_admin_only),
    db: Session = Depends(get_db)
):
    """Get system statistics for admin dashboard (Admin only)"""
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


@router.get("/stats/extended", response_model=AdminStatsResponse)
async def get_extended_admin_stats(
    current_user: User = Depends(require_admin_only),
    db: Session = Depends(get_db)
):
    """Get extended admin statistics including user counts and audit info (Admin only)"""
    # User statistics
    total_users = db.query(func.count(User.id)).scalar()
    active_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar()
    admin_count = db.query(func.count(User.id)).filter(User.role == UserRole.ADMIN).scalar()
    superuser_count = db.query(func.count(User.id)).filter(User.role == UserRole.SUPERUSER).scalar()
    regular_user_count = db.query(func.count(User.id)).filter(User.role == UserRole.USER).scalar()
    confidential_access_users = db.query(func.count(User.id)).filter(User.can_access_confidential == True).scalar()

    # Audit log statistics
    total_audit_logs = db.query(func.count(AuditLog.id)).scalar()

    # Recent admin actions (last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    recent_admin_actions = db.query(func.count(AuditLog.id)).filter(
        AuditLog.created_at >= week_ago
    ).scalar()

    # System health check
    health_status = {
        "database": "healthy",
        "redis": "unknown",
        "gemini": "unknown",
        "ollama": "unknown"
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

    return AdminStatsResponse(
        total_users=total_users,
        active_users=active_users,
        admin_count=admin_count,
        superuser_count=superuser_count,
        regular_user_count=regular_user_count,
        confidential_access_users=confidential_access_users,
        total_audit_logs=total_audit_logs,
        recent_admin_actions=recent_admin_actions,
        system_health=health_status
    )


@router.get("/queue-stats", response_model=QueueStats)
async def get_queue_stats(
    current_user: User = Depends(require_admin_only),
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
    current_user: User = Depends(require_admin_only),
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
    current_user: User = Depends(require_admin_only),
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
