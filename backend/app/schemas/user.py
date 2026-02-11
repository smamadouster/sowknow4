from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime
import enum
import re


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    SUPERUSER = "superuser"


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None


class UserCreate(UserBase):
    password: str

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        """
        Validate password complexity requirements.

        Password must:
        - Be at least 8 characters long
        - Contain at least 1 uppercase letter (A-Z)
        - Contain at least 1 lowercase letter (a-z)
        - Contain at least 1 digit (0-9)
        - Contain at least 1 special character (!@#$%^&*()_+-=[]{}|;:,.<>?)

        Raises:
            ValueError: If password does not meet complexity requirements
        """
        if len(v) < 8:
            raise ValueError(
                'Password must be at least 8 characters long'
            )

        if not re.search(r'[A-Z]', v):
            raise ValueError(
                'Password must contain at least 1 uppercase letter (A-Z)'
            )

        if not re.search(r'[a-z]', v):
            raise ValueError(
                'Password must contain at least 1 lowercase letter (a-z)'
            )

        if not re.search(r'\d', v):
            raise ValueError(
                'Password must contain at least 1 digit (0-9)'
            )

        if not re.search(r'[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]', v):
            raise ValueError(
                'Password must contain at least 1 special character '
                '(!@#$%^&*()_+-=[]{}|;:,.<>?)'
            )

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
