from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str | None = None


class TokenPayload(BaseModel):
    sub: str  # user email
    exp: int  # expiration timestamp
    role: str
    user_id: str


class LoginResponse(BaseModel):
    """Response model for login/telegram auth - returns user info, tokens in httpOnly cookies"""

    message: str
    user: dict | None = None  # User info (id, email, full_name, role)
    access_token: str | None = None  # For telegram bot (can't use httpOnly cookies)
