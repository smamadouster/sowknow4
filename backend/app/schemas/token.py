from pydantic import BaseModel
from typing import Optional

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: Optional[str] = None

class TokenPayload(BaseModel):
    sub: str  # user email
    exp: int  # expiration timestamp
    role: str
    user_id: str

class LoginResponse(BaseModel):
    """Response model for login/telegram auth - returns user info, tokens in httpOnly cookies"""
    message: str
    user: Optional[dict] = None  # User info (id, email, full_name, role)
    access_token: Optional[str] = None  # For telegram bot (can't use httpOnly cookies)
