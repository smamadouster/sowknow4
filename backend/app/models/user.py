from sqlalchemy import Column, String, Boolean, UUID, Enum
from sqlalchemy.orm import relationship
import uuid
from app.models.base import Base, TimestampMixin
import enum

class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    SUPERUSER = "superuser"

class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = {"schema": "sowknow"}
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False)
    is_superuser = Column(Boolean, default=False)
    can_access_confidential = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    # Relationships
    collections = relationship("Collection", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User {self.email} ({self.role})>"
