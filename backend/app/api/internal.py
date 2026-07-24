"""
Internal API endpoints — authenticated by BOT_API_KEY only.

These endpoints are designed for machine-to-machine use over trusted networks
(e.g., Tailscale). No OAuth2, no cookies, no CSRF.
"""

import hmac
import logging
import os

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents_common import is_upload_paused_async
from app.limiter import limiter
from app.api.documents_upload import _do_upload_document, _upload_semaphore
from app.database import get_db
from app.models.user import User
from app.schemas.document import DocumentUploadResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

BOT_API_KEY = os.getenv("BOT_API_KEY", "")
BOT_USER_EMAIL = os.getenv("BOT_USER_EMAIL", "")


async def _get_bot_user(db: AsyncSession) -> User:
    """Look up the bot user by BOT_USER_EMAIL. Raises 500 if not configured or not found."""
    if not BOT_USER_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="BOT_USER_EMAIL not configured",
        )
    result = await db.execute(select(User).where(User.email == BOT_USER_EMAIL))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Bot user not found — check BOT_USER_EMAIL configuration",
        )
    return user


def _validate_api_key(key: str) -> None:
    """Validate the provided API key against BOT_API_KEY. Raises 401 on mismatch."""
    if not BOT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="BOT_API_KEY not configured on server",
        )
    if not hmac.compare_digest(key, BOT_API_KEY):
        logger.warning("Invalid bot API key on internal endpoint")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


@router.post("/upload", response_model=DocumentUploadResponse)
@limiter.limit("20/minute")
async def internal_upload(
    request: Request,
    file: UploadFile = File(...),
    bucket: str = Form("public"),
    title: str | None = Form(None),
    tags: str | None = Form(None),
    document_type: str | None = Form(None),
    x_bot_api_key: str = Header(..., alias="X-Bot-Api-Key"),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """
    Upload a document via API key only (no user login required).

    Intended for machine-to-machine use over Tailscale.
    Uploads are attributed to the user specified by BOT_USER_EMAIL.
    """
    _validate_api_key(x_bot_api_key)
    bot_user = await _get_bot_user(db)

    # The bot endpoint must honor the same pause/backpressure gate as the
    # user-facing upload endpoints (was bypassed: the key holder could
    # enqueue unboundedly during an admin pause or pipeline red state).
    paused, reason = await is_upload_paused_async()
    if paused:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Uploads temporarily paused: {reason}",
        )

    logger.info(f"Internal upload: file={file.filename}, bucket={bucket}, bot_user={bot_user.email}")

    async with _upload_semaphore:
        return await _do_upload_document(
            file=file,
            bucket=bucket,
            title=title,
            tags=tags,
            document_type=document_type,
            transcript=None,
            x_bot_api_key=x_bot_api_key,
            current_user=bot_user,
            db=db,
        )
