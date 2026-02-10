from pydantic import BaseModel, EmailStr, validator
from typing import Optional
from datetime import datetime
import enum

class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    SUPERUSER = "superuser"

class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None

class UserCreate(UserBase):
    password: str
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    can_access_confidential: Optional[bool] = None

class UserInDB(UserBase):
    id: str
    role: UserRole
    is_superuser: bool
    can_access_confidential: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class UserPublic(UserBase):
    id: str
    role: UserRole
    
    class Config:
        from_attributes = True
