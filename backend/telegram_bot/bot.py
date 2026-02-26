"""
SOWKNOW Telegram Bot
Provides mobile-first interface for document upload and knowledge queries

ARCHITECTURE: Redis-backed session storage for resilience
- Sessions survive bot restarts
- Key format: telegram:user_context:{telegram_user_id}  (stored as telegram_session:{id})
- TTL: 24 hours (86400 seconds)
- Class alias: UserContextStore = RedisSessionManager (backward-compatible)
"""

import base64
import os
import logging
import sys
import json
import re
from datetime import datetime
from typing import Optional, Dict, Any, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from network_utils import ResilientAsyncClient, CircuitBreakerOpenError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.ext import CallbackQueryHandler, ConversationHandler
import redis.asyncio as redis_async

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
BOT_API_KEY = os.getenv("BOT_API_KEY", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 86400  # 24 hours
SESSION_KEY_PREFIX = "telegram_session:"

(SELECTING_BUCKET, CHECKING_DUPLICATE) = range(2)

# ---------------------------------------------------------------------------
# Media-group (album) accumulator
# When a user selects multiple files in Telegram, each file arrives as a
# separate message sharing the same media_group_id.  We buffer them for
# MEDIA_GROUP_WINDOW seconds, then show ONE bucket-selection keyboard for
# the whole batch.
# ---------------------------------------------------------------------------
import asyncio as _asyncio

MEDIA_GROUP_WINDOW = 2.0  # seconds to wait for stragglers

# _media_groups[media_group_id] = {"files": [...], "task": asyncio.Task, "context": ctx, "user": user}
_media_groups: dict = {}

_SENSITIVE_HEADERS = {"authorization", "x-bot-api-key"}


def _redact_headers(headers: dict) -> dict:
    """Return a copy of headers with sensitive values redacted for logging."""
    return {
        k: "***REDACTED***" if k.lower() in _SENSITIVE_HEADERS else v
        for k, v in headers.items()
    }


class RedisSessionManager:
    """
    Redis-backed session storage for Telegram bot user contexts.

    Ensures sessions survive bot restarts, preventing upload flow interruptions.
    Uses same Redis instance as token blacklisting for consistency.
    """

    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._redis: Optional[redis_async.Redis] = None
        # In-memory fallback when Redis is unavailable.
        # Sessions survive the current process but are lost on restart.
        self._fallback: Dict[int, Dict[str, Any]] = {}

    async def connect(self) -> bool:
        """Initialize Redis connection. Returns True if successful."""
        try:
            self._redis = redis_async.from_url(
                self._redis_url, decode_responses=True, encoding="utf-8"
            )
            await self._redis.ping()
            logger.info("Redis session storage connected successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self._redis = None
            return False

    async def close(self) -> None:
        """Close Redis connection gracefully."""
        if self._redis:
            await self._redis.close()
            logger.info("Redis session storage connection closed")

    def _get_key(self, telegram_user_id: int) -> str:
        """Generate Redis key for user session."""
        return f"{SESSION_KEY_PREFIX}{telegram_user_id}"

    @staticmethod
    def _encode_session(session_data: Dict[str, Any]) -> str:
        """JSON-serialize session, base64-encoding any bytes values (e.g. pending_file.file)."""
        def _encode(obj):
            if isinstance(obj, (bytes, bytearray)):
                return {"__b64__": base64.b64encode(obj).decode("ascii")}
            if isinstance(obj, dict):
                return {k: _encode(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_encode(i) for i in obj]
            return obj
        return json.dumps(_encode(session_data))

    @staticmethod
    def _decode_session(raw: str) -> Dict[str, Any]:
        """Reverse _encode_session — restore base64 markers back to bytes."""
        def _decode(obj):
            if isinstance(obj, dict):
                if "__b64__" in obj:
                    return base64.b64decode(obj["__b64__"])
                return {k: _decode(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_decode(i) for i in obj]
            return obj
        return _decode(json.loads(raw))

    async def get_session(self, telegram_user_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve user session from Redis, or in-memory fallback if Redis is down.

        Returns None if session doesn't exist or has expired.
        """
        if not self._redis:
            return self._fallback.get(telegram_user_id)

        try:
            key = self._get_key(telegram_user_id)
            data = await self._redis.get(key)
            if data:
                return self._decode_session(data)
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode session for user {telegram_user_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to get session for user {telegram_user_id}: {e}")
            return None

    async def set_session(
        self, telegram_user_id: int, session_data: Dict[str, Any]
    ) -> bool:
        """
        Store user session in Redis with 24-hour TTL.
        Falls back to in-memory storage when Redis is unavailable (sessions
        remain functional but will be lost on bot restart).

        Returns True if session was stored (Redis or fallback), False on error.
        """
        if not self._redis:
            logger.warning(
                f"Redis unavailable — storing session for user {telegram_user_id} "
                "in memory only (not persistent across restarts)"
            )
            self._fallback[telegram_user_id] = session_data
            return True

        try:
            key = self._get_key(telegram_user_id)
            data = self._encode_session(session_data)
            await self._redis.setex(key, SESSION_TTL_SECONDS, data)
            logger.debug(f"Session stored for user {telegram_user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to set session for user {telegram_user_id}: {e}")
            return False

    async def delete_session(self, telegram_user_id: int) -> bool:
        """Delete user session from Redis (or in-memory fallback)."""
        if not self._redis:
            self._fallback.pop(telegram_user_id, None)
            return True

        try:
            key = self._get_key(telegram_user_id)
            await self._redis.delete(key)
            logger.debug(f"Session deleted for user {telegram_user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session for user {telegram_user_id}: {e}")
            return False

    async def update_session(
        self, telegram_user_id: int, updates: Dict[str, Any]
    ) -> bool:
        """
        Update specific fields in user session while preserving others.

        Returns True if successful, False otherwise.
        """
        current = await self.get_session(telegram_user_id)
        if current is None:
            logger.warning(f"No session to update for user {telegram_user_id}")
            return False

        current.update(updates)
        return await self.set_session(telegram_user_id, current)

    async def count_active_sessions(self) -> int:
        """
        Count active sessions in Redis (or in-memory fallback).

        Used on startup to report session restoration status.
        """
        if not self._redis:
            return len(self._fallback)

        try:
            keys = await self._redis.keys(f"{SESSION_KEY_PREFIX}*")
            return len(keys)
        except Exception as e:
            logger.error(f"Failed to count sessions: {e}")
            return 0

    async def clear_pending_file(self, telegram_user_id: int) -> bool:
        """Clear pending file from session without deleting entire session."""
        return await self.update_session(telegram_user_id, {"pending_file": None})


# Backward-compatible alias required by audit spec (C2-P1)
UserContextStore = RedisSessionManager

session_manager = RedisSessionManager(REDIS_URL)


def user_context_get(telegram_user_id: int) -> Optional[Dict[str, Any]]:
    """Synchronous wrapper for backward compatibility (not recommended for new code)."""
    import asyncio

    loop = asyncio.get_event_loop()
    if loop.is_running():
        logger.warning(
            "user_context_get called from async context - use await session_manager.get_session() instead"
        )
        return None
    return loop.run_until_complete(session_manager.get_session(telegram_user_id))


# Track document processing status updates
# Format: {document_id: {"chat_id": int, "message_id": int, "status": str, "check_count": int}}
document_tracking = {}

# Adaptive polling configuration
MAX_STATUS_CHECKS = (
    240  # Maximum checks: 4 minutes @ 5s + 16 minutes @ 15s = 20 minutes total
)
PHASE_1_CHECKS = 48  # First 48 checks every 5 seconds (4 minutes) - initial processing
PHASE_2_INTERVAL = 15  # Then check every 15 seconds for slower processing stages

# Celery time limits for reference (from celery_app.py):
# - task_soft_time_limit: 300s (5 minutes)
# - task_time_limit: 600s (10 minutes)
# We allow extra time for queue delays and retries


class TelegramBotClient:
    def __init__(self):
        self.base_url = BACKEND_URL
        self._client = ResilientAsyncClient(
            base_url=BACKEND_URL,
            max_attempts=3,
            min_wait=1,
            max_wait=10,
            timeout=60.0,
            enable_circuit_breaker=True,
        )

    async def close(self) -> None:
        await self._client.close()

    async def login(self, telegram_user_id: int) -> dict:
        try:
            response = await self._client.post(
                "/api/v1/auth/telegram",
                json={"telegram_user_id": telegram_user_id},
                headers={"X-Bot-Api-Key": BOT_API_KEY},
            )
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable. Please try again later."}
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return {"error": str(e)}

    async def check_duplicate(self, filename: str, access_token: str) -> dict:
        try:
            response = await self._client.get(
                f"/api/v1/documents?search={filename}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if response.status_code == 404:
                return {"exists": False, "documents": []}
            response.raise_for_status()
            data = response.json()
            return {
                "exists": len(data.get("documents", [])) > 0,
                "documents": data.get("documents", []),
            }
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable", "exists": False}
        except Exception as e:
            logger.error(f"Check duplicate error: {str(e)}")
            return {"error": str(e), "exists": False}

    async def upload_document(
        self,
        file_bytes: bytes,
        filename: str,
        bucket: str,
        access_token: str,
        tags: Optional[List[str]] = None,
    ) -> dict:
        try:
            files = {"file": (filename, file_bytes)}
            data: Dict[str, Any] = {"bucket": bucket}
            if tags:
                data["tags"] = ",".join(tags)
            headers = {"Authorization": f"Bearer {access_token}"}
            if BOT_API_KEY:
                headers["X-Bot-Api-Key"] = BOT_API_KEY
                logger.info(f"X-Bot-Api-Key header added (length: {len(BOT_API_KEY)})")
            else:
                logger.error("BOT_API_KEY is empty! Cannot authenticate upload.")

            logger.info(
                f"Uploading document: {filename} ({len(file_bytes)} bytes) to bucket: {bucket}"
            )
            logger.info(f"Backend URL: {self.base_url}/api/v1/documents/upload")
            logger.debug(f"Headers: {_redact_headers(headers)}")
            logger.info(f"BOT_API_KEY present: {bool(BOT_API_KEY)}")

            response = await self._client.post(
                "/api/v1/documents/upload",
                files=files,
                data=data,
                headers=headers,
            )
            logger.info(f"Upload response status: {response.status_code}")
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable. Please try again later."}
        except Exception as e:
            logger.error(f"Upload error: {str(e)}")
            return {"error": str(e)}

    async def get_document_status(self, document_id: str, access_token: str) -> dict:
        """Get the current status of a document"""
        try:
            response = await self._client.get(
                f"/api/v1/documents/{document_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable"}
        except Exception as e:
            logger.error(f"Get document status error: {str(e)}")
            return {"error": str(e)}

    async def search(self, query: str, access_token: str) -> dict:
        try:
            response = await self._client.post(
                "/api/v1/search",
                json={"query": query, "limit": 5},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable. Please try again later."}
        except Exception as e:
            logger.error(f"Search error: {str(e)}")
            return {"error": str(e)}

    async def create_chat_session(self, access_token: str) -> dict:
        """Create a new backend chat session for multi-turn conversation."""
        try:
            title = f"Telegram Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            response = await self._client.post(
                "/api/v1/chat/sessions",
                json={"title": title},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable. Please try again later."}
        except Exception as e:
            logger.error(f"Create chat session error: {str(e)}")
            return {"error": str(e)}

    async def send_chat_message(
        self, session_id: str, content: str, access_token: str
    ) -> dict:
        """Send a message to an existing chat session (non-streaming).

        Conversation history is managed server-side by the backend using the
        ``session_id``.  Each call automatically includes all prior turns.
        """
        try:
            response = await self._client.post(
                f"/api/v1/chat/sessions/{session_id}/message?stream=false",
                json={"content": content},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable. Please try again later."}
        except Exception as e:
            logger.error(f"Chat error: {str(e)}")
            return {"error": str(e)}

    def get_circuit_breaker_status(self) -> dict:
        return self._client.get_circuit_breaker_status() or {}


bot_client = TelegramBotClient()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    login_result = await bot_client.login(user.id)

    if "error" in login_result:
        await update.message.reply_html(
            f"👋 <b>Welcome to SOWKNOW!</b>\n\n❌ Error: {login_result['error']}"
        )
        return

    session_data = {
        "access_token": login_result.get("access_token"),
        "user": login_result.get("user"),
        "chat_session_id": None,
        "pending_file": None,
    }
    await session_manager.set_session(user.id, session_data)

    welcome_text = f"""👋 <b>Welcome to SOWKNOW, {user.first_name}!</b>

📚 Your personal knowledge assistant:

📤 <b>Upload Documents</b>
• Send me any file (PDF, images, docs)
• I'll ask if you want it PUBLIC or CONFIDENTIAL
• I'll check for duplicates

🔍 <b>Search Knowledge</b>
• Just ask me anything

💬 <b>Chat</b>
• Conversational AI powered by MiniMax

📌 Commands:
/start - Show this message
/help - Get help"""

    keyboard = [
        [InlineKeyboardButton("📤 Upload Document", callback_data="upload_prompt")],
        [InlineKeyboardButton("🔍 Search", callback_data="search_prompt")],
        [InlineKeyboardButton("💬 Chat", callback_data="chat_prompt")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_html(welcome_text, reply_markup=reply_markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = """📖 <b>SOWKNOW Bot Help</b>

<b>Document Upload:</b>
• Send any file directly
• I'll ask if you want PUBLIC or CONFIDENTIAL
• I'll check for duplicates first

<b>Search:</b>
• Type your question
• Or use /search your query

<b>Chat:</b>
• Just type your question!

<b>Examples:</b>
• "What did I learn about solar energy?"
• "Show me all my documents"
• family photos

❓ Need help? Contact admin."""

    await update.message.reply_html(help_text)


async def _flush_media_group(media_group_id: str, chat_id: int, context) -> None:
    """Called after MEDIA_GROUP_WINDOW seconds — process all buffered files as a batch."""
    await _asyncio.sleep(MEDIA_GROUP_WINDOW)

    group = _media_groups.pop(media_group_id, None)
    if not group:
        return

    user = group["user"]
    files = group["files"]  # list of {"file_bytes": bytes, "filename": str, "tags": list}

    session = await session_manager.get_session(user.id)
    if not session:
        await context.bot.send_message(chat_id, "❌ Session expired. Please use /start again.")
        return

    # Duplicate check for each file
    summary_lines = []
    for f in files:
        dup = await bot_client.check_duplicate(f["filename"], session["access_token"])
        flag = "⚠️ dup" if dup.get("exists") else "✅"
        summary_lines.append(f"{flag} {f['filename']}")

    count = len(files)
    summary = "\n".join(f"📄 {line}" for line in summary_lines)

    await session_manager.update_session(user.id, {"pending_batch": files, "pending_file": None})

    keyboard = [
        [InlineKeyboardButton("📄 Public", callback_data="bucket_public")],
        [InlineKeyboardButton("🔒 Confidential", callback_data="bucket_confidential")],
        [InlineKeyboardButton("❌ Cancel", callback_data="bucket_cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id,
        f"📦 <b>{count} file{'s' if count > 1 else ''} ready</b>\n\n{summary}\n\n"
        f"🔐 Where should {'these files' if count > 1 else 'this file'} go?",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def handle_document_upload(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    session = await session_manager.get_session(user.id)
    if not session:
        await update.message.reply_text("❌ Please use /start first to authenticate.")
        return

    document = update.message.document
    photo = update.message.photo

    if document:
        file = document
        filename = document.file_name
    elif photo:
        file = photo[-1]
        filename = f"photo_{file.file_id}.jpg"
    else:
        return

    # Parse hashtags from caption
    caption = update.message.caption or ""
    parsed_tags: List[str] = re.findall(r"#(\w+)", caption)

    try:
        file_obj = await file.get_file()
        file_bytes = bytes(await file_obj.download_as_bytearray())
    except Exception as e:
        logger.error(f"File download error: {str(e)}")
        await update.message.reply_text(f"❌ Error downloading file: {str(e)}")
        return

    media_group_id = update.message.media_group_id

    # ── BATCH MODE: multiple files selected together ──────────────────────────
    if media_group_id:
        if media_group_id not in _media_groups:
            _media_groups[media_group_id] = {
                "files": [],
                "user": user,
                "task": None,
            }
            await update.message.reply_text(
                f"📦 <b>Receiving files…</b>", parse_mode="HTML"
            )
        group = _media_groups[media_group_id]
        group["files"].append({"file_bytes": file_bytes, "filename": filename, "tags": parsed_tags})

        # Cancel previous timer and restart it (wait for last file in group)
        if group["task"] and not group["task"].done():
            group["task"].cancel()
        group["task"] = _asyncio.ensure_future(
            _flush_media_group(media_group_id, update.message.chat_id, context)
        )
        return

    # ── SINGLE FILE MODE ──────────────────────────────────────────────────────
    await session_manager.update_session(
        user.id,
        {
            "pending_file": {
                "file": file_bytes,
                "filename": filename,
                "tags": parsed_tags,
            },
            "pending_batch": None,
        },
    )

    await update.message.reply_text(
        f"📄 <b>{filename}</b>\n\n⏳ Checking for duplicates...", parse_mode="HTML"
    )

    session = await session_manager.get_session(user.id)
    if not session:
        await update.message.reply_text("❌ Session expired. Please use /start again.")
        return

    duplicate_check = await bot_client.check_duplicate(filename, session["access_token"])

    if duplicate_check.get("exists"):
        dupes = duplicate_check.get("documents", [])
        dupe_list = "\n".join([f"• {d.get('title', d.get('original_filename', 'Untitled'))}" for d in dupes[:3]])
        await update.message.reply_text(
            f"⚠️ <b>Duplicate found!</b>\n\nSimilar documents:\n{dupe_list}\n\n"
            f"Do you still want to upload this file?",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"✅ No duplicates found!\n\n<b>{filename}</b>\n\n🔐 Where should this file go?",
            parse_mode="HTML",
        )

    keyboard = [
        [InlineKeyboardButton("📄 Public", callback_data="bucket_public")],
        [InlineKeyboardButton("🔒 Confidential", callback_data="bucket_confidential")],
        [InlineKeyboardButton("❌ Cancel", callback_data="bucket_cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Choose visibility:", reply_markup=reply_markup)


async def bucket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user

    session = await session_manager.get_session(user.id)
    if not session:
        await query.edit_message_text("❌ Session expired. Please use /start again.")
        return

    pending = session.get("pending_file")
    pending_batch = session.get("pending_batch")

    if not pending and not pending_batch:
        await query.edit_message_text("❌ No file pending. Please upload a file first.")
        return

    bucket_data = query.data

    if bucket_data == "bucket_cancel":
        await session_manager.update_session(user.id, {"pending_file": None, "pending_batch": None})
        await query.edit_message_text("❌ Upload cancelled.")
        return

    bucket = "confidential" if bucket_data == "bucket_confidential" else "public"
    bucket_emoji = "🔒" if bucket == "confidential" else "📄"

    # ── BATCH UPLOAD ──────────────────────────────────────────────────────────
    if pending_batch:
        count = len(pending_batch)
        await query.edit_message_text(
            f"⏳ Uploading {count} file{'s' if count > 1 else ''} to {bucket_emoji} {bucket}..."
        )
        await session_manager.update_session(user.id, {"pending_batch": None, "pending_file": None})

        success, failed = 0, 0
        for item in pending_batch:
            res = await bot_client.upload_document(
                file_bytes=item["file_bytes"],
                filename=item["filename"],
                bucket=bucket,
                access_token=session["access_token"],
                tags=item.get("tags") or None,
            )
            if "error" in res:
                failed += 1
                logger.error(f"Batch upload failed for {item['filename']}: {res['error']}")
            else:
                success += 1
                doc_id = res.get("document_id", "N/A")
                file_size_mb = len(item["file_bytes"]) / (1024 * 1024)
                estimated_time = max(30, int(30 + file_size_mb * 5))
                msg = await query.message.reply_text(
                    f"✅ <b>{item['filename']}</b>\n"
                    f"🆔 {doc_id} • {bucket_emoji} {bucket}\n"
                    f"⏱️ Est. {estimated_time // 60}m {estimated_time % 60}s",
                    parse_mode="HTML",
                )
                document_tracking[doc_id] = {
                    "chat_id": query.message.chat_id,
                    "message_id": msg.message_id,
                    "filename": item["filename"],
                    "bucket_emoji": bucket_emoji,
                    "access_token": session["access_token"],
                    "last_status": "processing",
                    "check_count": 0,
                }
                context.job_queue.run_once(
                    check_document_status, when=5, data=doc_id,
                    name=f"status_check_{doc_id}",
                )

        summary = f"✅ {success} uploaded"
        if failed:
            summary += f", ❌ {failed} failed"
        await query.edit_message_text(f"📦 Batch complete: {summary}")
        return

    # ── SINGLE FILE UPLOAD ────────────────────────────────────────────────────
    await query.edit_message_text(
        f"⏳ Uploading {bucket_emoji} {pending['filename']}..."
    )

    result = await bot_client.upload_document(
        file_bytes=pending["file"],
        filename=pending["filename"],
        bucket=bucket,
        access_token=session["access_token"],
        tags=pending.get("tags") or None,
    )

    await session_manager.clear_pending_file(user.id)

    if "error" in result:
        await query.edit_message_text(f"❌ Upload failed: {result['error']}")
    else:
        document_id = result.get("document_id", "N/A")
        file_size_mb = len(pending["file"]) / (1024 * 1024)

        # Estimate processing time based on file size
        # Base: 30s for small files, + 5s per MB for larger files
        estimated_time = max(30, int(30 + file_size_mb * 5))

        # Store message info for status updates
        message = await query.edit_message_text(
            f"✅ <b>Document uploaded!</b>\n\n"
            f"📁 {bucket_emoji} {pending['filename']}\n"
            f"📦 Size: {file_size_mb:.1f} MB\n"
            f"🆔 ID: {document_id}\n"
            f"📊 Status: processing\n"
            f"⏱️ Est. time: {estimated_time // 60}m {estimated_time % 60}s\n\n"
            f"🔄 Processing in progress...",
            parse_mode="HTML",
        )
        # Track document for status updates
        document_tracking[document_id] = {
            "chat_id": query.message.chat_id,
            "message_id": message.message_id if message else query.message.message_id,
            "filename": pending["filename"],
            "bucket_emoji": bucket_emoji,
            "access_token": session["access_token"],
            "last_status": "processing",
            "check_count": 0,
        }
        logger.info(
            f"Started tracking document {document_id} ({file_size_mb:.1f} MB, est. {estimated_time}s)"
        )
        # Schedule status check
        context.job_queue.run_once(
            check_document_status,
            when=5,  # Check after 5 seconds
            data=document_id,
            name=f"status_check_{document_id}",
        )


async def handle_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    text = update.message.text

    if not text or text.startswith("/"):
        return

    session = await session_manager.get_session(user.id)
    if not session:
        await update.message.reply_text("❌ Please use /start first.")
        return

    # Handle text-based bucket selection (fallback for button clicks)
    if text.lower() in ["public", "confidential", "yes", "no"]:
        pending = session.get("pending_file")
        if pending:
            bucket = "public" if text.lower() in ["public", "yes"] else "confidential"
            bucket_emoji = "📄" if bucket == "public" else "🔒"

            status_message = await update.message.reply_text(
                f"⏳ Uploading {bucket_emoji} {pending['filename']}..."
            )

            result = await bot_client.upload_document(
                file_bytes=pending["file"],
                filename=pending["filename"],
                bucket=bucket,
                access_token=session["access_token"],
                tags=pending.get("tags") or None,
            )

            await session_manager.clear_pending_file(user.id)

            if "error" in result:
                await status_message.edit_text(f"❌ Upload failed: {result['error']}")
            else:
                document_id = result.get("document_id", "N/A")
                await status_message.edit_text(
                    f"✅ <b>Document uploaded!</b>\n\n"
                    f"📁 {bucket_emoji} {pending['filename']}\n"
                    f"🆔 ID: {document_id}\n"
                    f"📊 Status: processing\n\n"
                    f"🔄 Processing in progress...",
                    parse_mode="HTML",
                )
                # Track document for status updates
                document_tracking[document_id] = {
                    "chat_id": update.message.chat_id,
                    "message_id": status_message.message_id,
                    "filename": pending["filename"],
                    "bucket_emoji": bucket_emoji,
                    "access_token": session["access_token"],
                    "last_status": "processing",
                    "check_count": 0,
                }
                # Schedule status check
                context.job_queue.run_once(
                    check_document_status,
                    when=5,  # Check after 5 seconds
                    data=document_id,
                    name=f"status_check_{document_id}",
                )
            return

    # --- Multi-turn conversation via backend chat session ---
    # The backend manages full conversation history using the session_id.
    # We create one session per user (stored in Redis) and reuse it so
    # every subsequent message automatically gets the prior context.
    chat_session_id = session.get("chat_session_id")
    if not chat_session_id:
        session_result = await bot_client.create_chat_session(session["access_token"])
        if "error" in session_result:
            await update.message.reply_text(
                "❌ Could not start conversation. Please use /start again."
            )
            return
        chat_session_id = session_result.get("id")
        await session_manager.update_session(user.id, {"chat_session_id": chat_session_id})
        logger.info(f"Created chat session {chat_session_id} for user {user.id}")

    thinking_msg = await update.message.reply_text("💭 Thinking...")
    result = await bot_client.send_chat_message(
        chat_session_id, text, session["access_token"]
    )

    if "error" in result:
        await thinking_msg.edit_text(f"❌ Error: {result['error']}")
        return

    content = result.get("content", "")
    llm_used = result.get("llm_used", "")
    sources = result.get("sources") or []

    response_parts = [content]
    if sources:
        source_list = "\n".join(
            [f"• {s.get('document_name', 'Unknown')}" for s in sources[:3]]
        )
        response_parts.append(f"\n\n📚 <b>Sources:</b>\n{source_list}")
    if llm_used:
        response_parts.append(f"\n\n🤖 {llm_used}")

    await thinking_msg.edit_text("".join(response_parts), parse_mode="HTML")


async def upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📤 <b>Upload a Document</b>\n\n"
        "Send me any file!\n\n"
        "I'll ask if you want:\n"
        "• 📄 Public - visible to all\n"
        "• 🔒 Confidential - admin only\n\n"
        "I'll also check for duplicates!",
        parse_mode="HTML",
    )


async def search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔍 <b>Search</b>\n\nType your question!", parse_mode="HTML"
    )


async def chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💬 <b>Chat Mode</b>\n\nJust type your question!", parse_mode="HTML"
    )


async def check_completed_documents(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Background job to check documents that may have completed after polling stopped.
    Runs every 60 seconds to catch documents that finished processing.
    """
    if not document_tracking:
        return

    # Process a copy of the keys to avoid modification during iteration
    document_ids = list(document_tracking.keys())

    for document_id in document_ids:
        if document_id not in document_tracking:
            continue

        tracking_info = document_tracking[document_id]
        check_count = tracking_info.get("check_count", 0)
        last_status = tracking_info.get("last_status", "")

        # Only check documents that have exceeded the polling phase (check_count >= MAX_STATUS_CHECKS)
        # and are still in processing/pending state
        if check_count < MAX_STATUS_CHECKS or last_status in ["indexed", "error"]:
            continue

        access_token = tracking_info["access_token"]
        chat_id = tracking_info["chat_id"]
        message_id = tracking_info["message_id"]
        filename = tracking_info["filename"]
        bucket_emoji = tracking_info["bucket_emoji"]

        # Check current status
        result = await bot_client.get_document_status(document_id, access_token)

        if "error" in result:
            continue

        current_status = result.get("status", "unknown")

        if current_status == "indexed":
            status_text = (
                f"✅ <b>Document ready!</b>\n\n"
                f"📁 {bucket_emoji} {filename}\n"
                f"🆔 ID: {document_id}\n"
                f"📊 Status: {current_status}\n\n"
                f"✨ Your document has been processed and is ready for search!"
            )
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=status_text,
                    parse_mode="HTML",
                )
                logger.info(f"Sent completion notification for document {document_id}")
            except Exception as e:
                logger.error(
                    f"Failed to send completion notification for {document_id}: {e}"
                )
            del document_tracking[document_id]

        elif current_status == "error":
            error_details = result.get("document_metadata", {}).get(
                "processing_error", "Unknown error"
            )
            status_text = (
                f"❌ <b>Processing failed</b>\n\n"
                f"📁 {bucket_emoji} {filename}\n"
                f"🆔 ID: {document_id}\n"
                f"📊 Status: {current_status}\n\n"
                f"⚠️ There was an error processing your document.\n\n"
                f"<code>{error_details[:100]}{'...' if len(error_details) > 100 else ''}</code>\n\n"
                f"Please try uploading again."
            )
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=status_text,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(
                    f"Failed to send error notification for {document_id}: {e}"
                )
            del document_tracking[document_id]


async def check_document_status(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check document processing status and update user with adaptive polling"""
    document_id = context.job.data

    if document_id not in document_tracking:
        logger.warning(f"Document {document_id} not found in tracking")
        return

    tracking_info = document_tracking[document_id]
    chat_id = tracking_info["chat_id"]
    message_id = tracking_info["message_id"]
    filename = tracking_info["filename"]
    bucket_emoji = tracking_info["bucket_emoji"]
    access_token = tracking_info["access_token"]
    last_status = tracking_info["last_status"]
    check_count = tracking_info["check_count"]

    # Increment check count using the correct value
    check_count += 1
    document_tracking[document_id]["check_count"] = check_count

    # Calculate elapsed time for user-friendly messaging
    elapsed_minutes = (
        (check_count * 5) / 60
        if check_count <= PHASE_1_CHECKS
        else (PHASE_1_CHECKS * 5 + (check_count - PHASE_1_CHECKS) * PHASE_2_INTERVAL)
        / 60
    )

    # Check if we've exceeded maximum checks (timeout)
    if check_count >= MAX_STATUS_CHECKS:
        status_text = (
            f"⏱️ <b>Processing in progress...</b>\n\n"
            f"📁 {bucket_emoji} {filename}\n"
            f"🆔 ID: {document_id}\n"
            f"📊 Status: still processing (~{elapsed_minutes:.0f} min elapsed)\n\n"
            f"⏳ Large documents can take 10-15 minutes to process. "
            f"You'll be notified when complete!\n\n"
            f"💡 <i>You can start searching once processing finishes.</i>"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=status_text,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(
                f"Failed to update timeout message for document {document_id}: {e}"
            )
        # Keep tracking but stop polling - document will complete asynchronously
        logger.info(
            f"Document {document_id} tracking stopped after {check_count} checks, still processing"
        )
        return

    # Get current document status
    result = await bot_client.get_document_status(document_id, access_token)

    if "error" in result:
        logger.error(
            f"Failed to get status for document {document_id}: {result['error']}"
        )
        # Retry after appropriate interval based on phase
        next_check = 5 if check_count <= PHASE_1_CHECKS else PHASE_2_INTERVAL
        context.job_queue.run_once(
            check_document_status,
            when=next_check,
            data=document_id,
            name=f"status_check_{document_id}_retry",
        )
        return

    current_status = result.get("status", "unknown")

    # Handle completion states first (indexed or error)
    if current_status == "indexed":
        status_text = (
            f"✅ <b>Document ready!</b>\n\n"
            f"📁 {bucket_emoji} {filename}\n"
            f"🆔 ID: {document_id}\n"
            f"📊 Status: {current_status}\n\n"
            f"✨ Your document has been processed and is ready for search!"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=status_text,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(
                f"Failed to update completion message for document {document_id}: {e}"
            )
        # Remove from tracking - we're done
        del document_tracking[document_id]
        logger.info(
            f"Document {document_id} completed successfully after {check_count} checks"
        )
        return

    if current_status == "error":
        error_details = result.get("document_metadata", {}).get(
            "processing_error", "Unknown error"
        )
        status_text = (
            f"❌ <b>Processing failed</b>\n\n"
            f"📁 {bucket_emoji} {filename}\n"
            f"🆔 ID: {document_id}\n"
            f"📊 Status: {current_status}\n\n"
            f"⚠️ There was an error processing your document.\n\n"
            f"<code>{error_details[:100]}{'...' if len(error_details) > 100 else ''}</code>\n\n"
            f"Please try uploading again."
        )
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=status_text,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(
                f"Failed to update error message for document {document_id}: {e}"
            )
        del document_tracking[document_id]
        logger.error(
            f"Document {document_id} failed after {check_count} checks: {error_details}"
        )
        return

    # Only update message if status changed (for pending/processing states)
    if current_status != last_status:
        document_tracking[document_id]["last_status"] = current_status

        # Show progress with elapsed time
        if current_status in ["processing", "pending", "uploading"]:
            status_text = (
                f"✅ <b>Document uploaded!</b>\n\n"
                f"📁 {bucket_emoji} {filename}\n"
                f"🆔 ID: {document_id}\n"
                f"📊 Status: {current_status}\n"
                f"⏱️ Elapsed: ~{elapsed_minutes:.0f} min\n\n"
                f"🔄 Processing in progress..."
            )
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=status_text,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning(
                    f"Failed to update progress message for document {document_id}: {e}"
                )

    # Schedule next check with adaptive interval
    if current_status in ["processing", "pending", "uploading"]:
        # Phase 1: Check every 5 seconds for first 48 checks (4 minutes)
        # Phase 2: Check every 15 seconds after that (for longer processing)
        next_interval = 5 if check_count < PHASE_1_CHECKS else PHASE_2_INTERVAL

        context.job_queue.run_once(
            check_document_status,
            when=next_interval,
            data=document_id,
            name=f"status_check_{document_id}",
        )
    else:
        # Unknown status - stop tracking
        logger.warning(f"Document {document_id} has unknown status: {current_status}")
        del document_tracking[document_id]


async def post_init(application: Application) -> None:
    """Initialize Redis session storage and log restored sessions."""
    connected = await session_manager.connect()
    if connected:
        active_count = await session_manager.count_active_sessions()
        logger.info(
            f"✅ Redis session storage initialized. {active_count} active session(s) restored from Redis."
        )
    else:
        logger.warning(
            "⚠️ Redis session storage unavailable. Using in-memory fallback — "
            "sessions are functional but will be lost on bot restart."
        )


async def post_shutdown(application: Application) -> None:
    """Clean up Redis connection on shutdown."""
    await session_manager.close()
    logger.info("Redis session storage shut down complete.")


def _validate_required_env_vars() -> bool:
    """Validate all required environment variables are present before startup."""
    required = {
        "TELEGRAM_BOT_TOKEN": BOT_TOKEN,
        "BOT_API_KEY": BOT_API_KEY,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        for name in missing:
            logger.error(f"Required environment variable not set: {name}")
            print(f"ERROR: {name} environment variable is not set!")
        print("Please set all required environment variables and restart the bot.")
        print("See .env.example for the list of required variables.")
        return False
    return True


def _validate_bot_token(token: str) -> bool:
    """Pre-flight check: verify the token is accepted by the Telegram Bot API.

    Calls GET /bot{token}/getMe synchronously before starting the event loop.
    Returns True on success, False on 401 (invalid/revoked token).
    Network errors are treated as transient and return True (let polling handle it).
    """
    try:
        import httpx
        resp = httpx.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            bot_username = data.get("result", {}).get("username", "unknown")
            logger.info(f"Token valid — bot username: @{bot_username}")
            return True
        elif resp.status_code == 401:
            logger.error("=" * 60)
            logger.error("TELEGRAM BOT TOKEN IS INVALID (401 Unauthorized)")
            logger.error("The token was rejected by api.telegram.org.")
            logger.error("")
            logger.error("To fix:")
            logger.error("  1. Open Telegram and message @BotFather")
            logger.error("  2. Send /mybots → select your bot → API Token")
            logger.error("     OR send /newbot to create a fresh bot")
            logger.error("  3. Copy the new token")
            logger.error("  4. Edit /var/docker/sowknow4/.env:")
            logger.error("       TELEGRAM_BOT_TOKEN=<new token>")
            logger.error("  5. Run: docker compose restart telegram-bot")
            logger.error("=" * 60)
            print("ERROR: TELEGRAM_BOT_TOKEN is invalid. See logs for fix instructions.")
            return False
        else:
            logger.warning(
                f"Unexpected response from Telegram API: HTTP {resp.status_code} — "
                "proceeding anyway (may be a transient issue)."
            )
            return True
    except Exception as exc:
        logger.warning(
            f"Could not reach Telegram API for pre-flight check: {exc} — "
            "proceeding anyway."
        )
        return True


def main() -> None:
    if not _validate_required_env_vars():
        # Exit cleanly (code 0) — this is a config error, not a crash.
        # With restart: on-failure, exit code 0 will NOT trigger a restart.
        sys.exit(0)

    if not _validate_bot_token(BOT_TOKEN):
        # Token rejected by Telegram — exit cleanly, no restart loop.
        sys.exit(0)

    logger.info("Initializing Telegram bot...")

    try:
        application = (
            Application.builder()
            .token(BOT_TOKEN)
            .post_init(post_init)
            .post_shutdown(post_shutdown)
            .build()
        )
        logger.info(f"Job queue enabled: {application.job_queue is not None}")
    except Exception as e:
        logger.error(f"Failed to build application: {e}")
        print(f"ERROR: Failed to initialize bot: {e}")
        return

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(CallbackQueryHandler(bucket_callback, pattern="^bucket_"))

    application.add_handler(
        CallbackQueryHandler(upload_callback, pattern="^upload_prompt")
    )
    application.add_handler(
        CallbackQueryHandler(search_callback, pattern="^search_prompt")
    )
    application.add_handler(CallbackQueryHandler(chat_callback, pattern="^chat_prompt"))

    application.add_handler(
        MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document_upload)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )

    logger.info("SOWKNOW Telegram Bot handlers registered")

    # Add error handlers for polling
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error(f"Exception while handling an update: {context.error}")

    application.add_error_handler(error_handler)

    # Schedule background completion checker (runs every 60 seconds)
    if application.job_queue:
        application.job_queue.run_repeating(
            check_completed_documents,
            interval=60,  # Check every 60 seconds
            first=60,  # Start after 60 seconds
            name="completion_checker",
        )
        logger.info("Scheduled completion checker job (runs every 60s)")

    # Start polling with error handling
    try:
        logger.info("Starting SOWKNOW Telegram Bot polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Polling error: {e}")
        print(f"ERROR: Bot polling failed: {e}")


if __name__ == "__main__":
    main()
