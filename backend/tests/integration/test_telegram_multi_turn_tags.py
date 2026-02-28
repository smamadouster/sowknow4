"""
Integration tests for Telegram bot features:
  - P1-D2a: Multi-turn conversation (session memory → chat session → LLM history)
  - P1-D2b: Hashtag tag parsing from document captions

Tests use mock Telegram Update objects so no live Telegram connection is needed.
"""

import re
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Minimal mock helpers for python-telegram-bot objects
# ---------------------------------------------------------------------------

def _make_user(user_id: int = 12345, first_name: str = "Alice") -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.first_name = first_name
    return user


def _make_message(
    text: str = "",
    caption: str = "",
    document=None,
    photo=None,
) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.document = document
    msg.photo = photo
    msg.chat_id = 99999
    # reply_text and edit_text return coroutines
    sent = MagicMock()
    sent.message_id = 1001
    sent.edit_text = AsyncMock(return_value=None)
    msg.reply_text = AsyncMock(return_value=sent)
    msg.reply_html = AsyncMock(return_value=None)
    return msg


def _make_update(
    text: str = "",
    caption: str = "",
    document=None,
    photo=None,
    user_id: int = 12345,
) -> MagicMock:
    update = MagicMock()
    update.effective_user = _make_user(user_id=user_id)
    update.message = _make_message(
        text=text, caption=caption, document=document, photo=photo
    )
    return update


def _make_context() -> MagicMock:
    ctx = MagicMock()
    ctx.job_queue = MagicMock()
    ctx.job_queue.run_once = MagicMock()
    return ctx


# ---------------------------------------------------------------------------
# Helpers to build common mock responses
# ---------------------------------------------------------------------------

FAKE_TOKEN = "fake-jwt-token-abc123"
FAKE_SESSION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
FAKE_CHAT_SESSION_ID = "11111111-2222-3333-4444-555555555555"


def _redis_session(chat_session_id: str | None = None) -> dict[str, Any]:
    return {
        "access_token": FAKE_TOKEN,
        "user": {"id": "user-uuid", "email": "alice@example.com"},
        "chat_session_id": chat_session_id,
        "pending_file": None,
    }


# ---------------------------------------------------------------------------
# Tests: Multi-turn conversation
# ---------------------------------------------------------------------------

class TestMultiTurnConversation:
    """
    Verify that handle_text_message creates a chat session on first use,
    stores the session_id in Redis, and calls send_chat_message (not search)
    on every subsequent turn so the backend can include conversation history.
    """

    @pytest.mark.asyncio
    async def test_creates_chat_session_on_first_message(self):
        """First text message → create_chat_session called, ID stored in session."""
        from backend.telegram_bot.bot import handle_text_message

        update = _make_update(text="What is the meaning of life?")
        context = _make_context()

        # Session has no chat_session_id yet
        session_data = _redis_session(chat_session_id=None)

        with patch(
            "backend.telegram_bot.bot.session_manager.get_session",
            new=AsyncMock(return_value=session_data),
        ) as mock_get, patch(
            "backend.telegram_bot.bot.session_manager.update_session",
            new=AsyncMock(return_value=True),
        ) as mock_update, patch(
            "backend.telegram_bot.bot.bot_client.create_chat_session",
            new=AsyncMock(return_value={"id": FAKE_CHAT_SESSION_ID}),
        ) as mock_create, patch(
            "backend.telegram_bot.bot.bot_client.send_chat_message",
            new=AsyncMock(
                return_value={
                    "content": "42, of course.",
                    "llm_used": "kimi",
                    "sources": [],
                }
            ),
        ) as mock_send:
            await handle_text_message(update, context)

        # create_chat_session must be called exactly once
        mock_create.assert_awaited_once_with(FAKE_TOKEN)

        # The new session ID must be persisted back to Redis
        mock_update.assert_awaited_once()
        call_kwargs = mock_update.call_args
        stored_data = call_kwargs[0][1]  # second positional arg
        assert stored_data.get("chat_session_id") == FAKE_CHAT_SESSION_ID

        # send_chat_message must be called with the new session ID
        mock_send.assert_awaited_once_with(
            FAKE_CHAT_SESSION_ID,
            "What is the meaning of life?",
            FAKE_TOKEN,
        )

    @pytest.mark.asyncio
    async def test_reuses_existing_chat_session(self):
        """Subsequent messages reuse the stored session ID – no new session created."""
        from backend.telegram_bot.bot import handle_text_message

        update = _make_update(text="Tell me more.")
        context = _make_context()

        # Session already has a chat_session_id
        session_data = _redis_session(chat_session_id=FAKE_CHAT_SESSION_ID)

        with patch(
            "backend.telegram_bot.bot.session_manager.get_session",
            new=AsyncMock(return_value=session_data),
        ), patch(
            "backend.telegram_bot.bot.bot_client.create_chat_session",
            new=AsyncMock(),
        ) as mock_create, patch(
            "backend.telegram_bot.bot.bot_client.send_chat_message",
            new=AsyncMock(
                return_value={"content": "Sure!", "llm_used": "kimi", "sources": []}
            ),
        ) as mock_send:
            await handle_text_message(update, context)

        # create_chat_session must NOT be called when session ID already exists
        mock_create.assert_not_awaited()

        # send_chat_message must use the pre-existing session ID
        mock_send.assert_awaited_once_with(
            FAKE_CHAT_SESSION_ID,
            "Tell me more.",
            FAKE_TOKEN,
        )

    @pytest.mark.asyncio
    async def test_handles_create_session_error_gracefully(self):
        """If session creation fails, user gets an error message and no crash."""
        from backend.telegram_bot.bot import handle_text_message

        update = _make_update(text="Hello?")
        context = _make_context()
        session_data = _redis_session(chat_session_id=None)

        with patch(
            "backend.telegram_bot.bot.session_manager.get_session",
            new=AsyncMock(return_value=session_data),
        ), patch(
            "backend.telegram_bot.bot.bot_client.create_chat_session",
            new=AsyncMock(return_value={"error": "Backend unavailable"}),
        ), patch(
            "backend.telegram_bot.bot.bot_client.send_chat_message",
            new=AsyncMock(),
        ) as mock_send:
            await handle_text_message(update, context)

        # send_chat_message must NOT be called if session creation failed
        mock_send.assert_not_awaited()

        # User must receive an error reply
        update.message.reply_text.assert_awaited_once()
        call_text = update.message.reply_text.call_args[0][0]
        assert "❌" in call_text

    @pytest.mark.asyncio
    async def test_chat_response_with_sources_displayed(self):
        """Sources returned by the backend are included in the reply."""
        from backend.telegram_bot.bot import handle_text_message

        update = _make_update(text="Summarise my invoices")
        context = _make_context()
        session_data = _redis_session(chat_session_id=FAKE_CHAT_SESSION_ID)

        sources = [
            {"document_name": "Invoice_2024.pdf", "document_id": "d1", "chunk_id": "c1", "relevance_score": 0.9},
            {"document_name": "Invoice_2023.pdf", "document_id": "d2", "chunk_id": "c2", "relevance_score": 0.8},
        ]

        with patch(
            "backend.telegram_bot.bot.session_manager.get_session",
            new=AsyncMock(return_value=session_data),
        ), patch(
            "backend.telegram_bot.bot.bot_client.send_chat_message",
            new=AsyncMock(
                return_value={
                    "content": "You have 2 invoices.",
                    "llm_used": "minimax",
                    "sources": sources,
                }
            ),
        ):
            await handle_text_message(update, context)

        # The thinking message is edited with final content
        thinking_mock = update.message.reply_text.return_value
        thinking_mock.edit_text.assert_awaited_once()
        final_text = thinking_mock.edit_text.call_args[0][0]
        assert "Invoice_2024.pdf" in final_text
        assert "Sources" in final_text


# ---------------------------------------------------------------------------
# Tests: Hashtag tag parsing from document captions
# ---------------------------------------------------------------------------

class TestHashtagTagParsing:
    """
    Verify that handle_document_upload parses #hashtags from the message
    caption and stores them in the pending_file session entry, and that
    bucket_callback passes those tags to upload_document.
    """

    def _make_document_file(self):
        doc = MagicMock()
        doc.file_name = "invoice.pdf"
        doc.file_id = "file_abc"

        file_obj = MagicMock()
        file_obj.get_file = AsyncMock(return_value=file_obj)
        file_obj.download_as_bytearray = AsyncMock(return_value=bytearray(b"PDF data"))
        doc.get_file = AsyncMock(return_value=file_obj)
        return doc

    @pytest.mark.asyncio
    async def test_parses_hashtags_from_caption(self):
        """Hashtags in the caption are extracted and stored in pending_file."""
        from backend.telegram_bot.bot import handle_document_upload

        doc = self._make_document_file()
        update = _make_update(caption="#urgent #invoice", document=doc)
        context = _make_context()

        session_data = _redis_session()
        stored_pending: dict[str, Any] = {}

        async def fake_update_session(user_id, updates):
            stored_pending.update(updates)
            return True

        with patch(
            "backend.telegram_bot.bot.session_manager.get_session",
            new=AsyncMock(return_value=session_data),
        ), patch(
            "backend.telegram_bot.bot.session_manager.update_session",
            new=AsyncMock(side_effect=fake_update_session),
        ), patch(
            "backend.telegram_bot.bot.bot_client.check_duplicate",
            new=AsyncMock(return_value={"exists": False, "documents": []}),
        ):
            await handle_document_upload(update, context)

        pending = stored_pending.get("pending_file", {})
        assert pending is not None, "pending_file should be stored in session"
        tags = pending.get("tags", [])
        assert "urgent" in tags, f"Expected 'urgent' in tags, got {tags}"
        assert "invoice" in tags, f"Expected 'invoice' in tags, got {tags}"

    @pytest.mark.asyncio
    async def test_no_hashtags_yields_empty_tags(self):
        """A caption without hashtags stores an empty tags list."""
        from backend.telegram_bot.bot import handle_document_upload

        doc = self._make_document_file()
        update = _make_update(caption="My quarterly report", document=doc)
        context = _make_context()

        session_data = _redis_session()
        stored_pending: dict[str, Any] = {}

        async def fake_update_session(user_id, updates):
            stored_pending.update(updates)
            return True

        with patch(
            "backend.telegram_bot.bot.session_manager.get_session",
            new=AsyncMock(return_value=session_data),
        ), patch(
            "backend.telegram_bot.bot.session_manager.update_session",
            new=AsyncMock(side_effect=fake_update_session),
        ), patch(
            "backend.telegram_bot.bot.bot_client.check_duplicate",
            new=AsyncMock(return_value={"exists": False, "documents": []}),
        ):
            await handle_document_upload(update, context)

        pending = stored_pending.get("pending_file", {})
        assert pending.get("tags", []) == []

    @pytest.mark.asyncio
    async def test_no_caption_yields_empty_tags(self):
        """No caption at all stores an empty tags list (not None / crash)."""
        from backend.telegram_bot.bot import handle_document_upload

        doc = self._make_document_file()
        # caption=None simulates a file sent without any caption text
        update = _make_update(caption=None, document=doc)
        context = _make_context()

        session_data = _redis_session()
        stored_pending: dict[str, Any] = {}

        async def fake_update_session(user_id, updates):
            stored_pending.update(updates)
            return True

        with patch(
            "backend.telegram_bot.bot.session_manager.get_session",
            new=AsyncMock(return_value=session_data),
        ), patch(
            "backend.telegram_bot.bot.session_manager.update_session",
            new=AsyncMock(side_effect=fake_update_session),
        ), patch(
            "backend.telegram_bot.bot.bot_client.check_duplicate",
            new=AsyncMock(return_value={"exists": False, "documents": []}),
        ):
            await handle_document_upload(update, context)

        pending = stored_pending.get("pending_file", {})
        assert pending.get("tags", []) == []

    @pytest.mark.asyncio
    async def test_tags_passed_to_upload_on_bucket_selection(self):
        """When bucket is chosen via callback, stored tags are forwarded to the API."""
        from backend.telegram_bot.bot import bucket_callback

        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "bucket_public"
        query.from_user = _make_user()

        update = MagicMock()
        update.callback_query = query
        context = _make_context()

        session_data = _redis_session()
        session_data["pending_file"] = {
            "file": b"PDF bytes",
            "filename": "report.pdf",
            "tags": ["urgent", "invoice"],
        }

        upload_calls: list[dict] = []

        async def fake_upload(file_bytes, filename, bucket, access_token, tags=None):
            upload_calls.append({"tags": tags})
            return {"document_id": "new-doc-id"}

        with patch(
            "backend.telegram_bot.bot.session_manager.get_session",
            new=AsyncMock(return_value=session_data),
        ), patch(
            "backend.telegram_bot.bot.session_manager.clear_pending_file",
            new=AsyncMock(return_value=True),
        ), patch(
            "backend.telegram_bot.bot.bot_client.upload_document",
            new=AsyncMock(side_effect=fake_upload),
        ):
            await bucket_callback(update, context)

        assert len(upload_calls) == 1, "upload_document should be called once"
        passed_tags = upload_calls[0]["tags"]
        assert passed_tags == ["urgent", "invoice"], (
            f"Expected ['urgent', 'invoice'], got {passed_tags}"
        )

    @pytest.mark.asyncio
    async def test_upload_with_no_tags_passes_none(self):
        """Documents without hashtags send tags=None to the upload API."""
        from backend.telegram_bot.bot import bucket_callback

        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "bucket_public"
        query.from_user = _make_user()

        update = MagicMock()
        update.callback_query = query
        context = _make_context()

        session_data = _redis_session()
        session_data["pending_file"] = {
            "file": b"data",
            "filename": "plain.pdf",
            "tags": [],  # empty list → should become None
        }

        upload_calls: list[dict] = []

        async def fake_upload(file_bytes, filename, bucket, access_token, tags=None):
            upload_calls.append({"tags": tags})
            return {"document_id": "new-doc-id"}

        with patch(
            "backend.telegram_bot.bot.session_manager.get_session",
            new=AsyncMock(return_value=session_data),
        ), patch(
            "backend.telegram_bot.bot.session_manager.clear_pending_file",
            new=AsyncMock(return_value=True),
        ), patch(
            "backend.telegram_bot.bot.bot_client.upload_document",
            new=AsyncMock(side_effect=fake_upload),
        ):
            await bucket_callback(update, context)

        assert upload_calls[0]["tags"] is None


# ---------------------------------------------------------------------------
# Tests: Hashtag regex edge cases (pure unit, no async needed)
# ---------------------------------------------------------------------------

class TestHashtagRegex:
    """Pure-unit tests for the hashtag parsing regex pattern."""

    def _parse_tags(self, caption: str) -> list[str]:
        return re.findall(r"#(\w+)", caption or "")

    def test_single_tag(self):
        assert self._parse_tags("#invoice") == ["invoice"]

    def test_multiple_tags(self):
        result = self._parse_tags("#urgent #invoice #2024")
        assert result == ["urgent", "invoice", "2024"]

    def test_tags_mixed_with_text(self):
        result = self._parse_tags("Please store this #urgent document #invoice")
        assert "urgent" in result
        assert "invoice" in result

    def test_no_tags(self):
        assert self._parse_tags("No tags here at all") == []

    def test_empty_caption(self):
        assert self._parse_tags("") == []

    def test_none_caption(self):
        assert self._parse_tags(None) == []

    def test_tags_are_lowercased_in_bot(self):
        """The upload API receives lowercase tag names (regex is case-preserving,
        lowercase happens in documents.py when writing to DB)."""
        result = self._parse_tags("#URGENT #Invoice")
        # Raw regex preserves case; lowercasing happens server-side
        assert "URGENT" in result
        assert "Invoice" in result
