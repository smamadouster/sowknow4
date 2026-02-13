"""
Audit log model for tracking admin actions and confidential access
"""
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Enum as SQLEnum, func
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin, GUIDType
from app.models.user import User, UserRole
import enum
import uuid


class AuditAction(str, enum.Enum):
    """Types of audit actions"""
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"
    USER_ROLE_CHANGED = "user_role_changed"
    USER_STATUS_CHANGED = "user_status_changed"
    CONFIDENTIAL_ACCESSED = "confidential_accessed"
    CONFIDENTIAL_UPLOADED = "confidential_uploaded"
    CONFIDENTIAL_DELETED = "confidential_deleted"
    ADMIN_LOGIN = "admin_login"
    SETTINGS_CHANGED = "settings_changed"
    SYSTEM_ACTION = "system_action"


class AuditLog(Base, TimestampMixin):
    """
    Audit log for tracking all admin actions and confidential access
    """
    __tablename__ = "audit_logs"
    __table_args__ = {"schema": "sowknow"}

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    user_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.users.id"), nullable=True, index=True)
    action = Column(SQLEnum(AuditAction), nullable=False, index=True)
    resource_type = Column(String(100), nullable=False, index=True)  # e.g., "user", "document", "system"
    resource_id = Column(String(255), nullable=True, index=True)  # ID of affected resource
    details = Column(Text, nullable=True)  # JSON string with additional details
    ip_address = Column(String(45), nullable=True)  # IPv6 compatible
    user_agent = Column(String(512), nullable=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self):
        return f"<AuditLog {self.action.value} by {self.user_id} at {self.created_at}>"
