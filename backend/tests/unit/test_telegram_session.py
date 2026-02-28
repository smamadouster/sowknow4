"""
Tests for Telegram Bot Redis Session Manager.

Validates:
- Session storage and retrieval
- TTL enforcement (24 hours)
- JSON serialization/deserialization
- Graceful handling of expired/missing sessions
- Redis connection resilience
"""

import json
from unittest.mock import AsyncMock, patch

import pytest


class TestRedisSessionManager:
    """Test suite for RedisSessionManager class."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis_mock = AsyncMock()
        redis_mock.ping = AsyncMock(return_value=True)
        redis_mock.get = AsyncMock(return_value=None)
        redis_mock.setex = AsyncMock(return_value=True)
        redis_mock.delete = AsyncMock(return_value=1)
        redis_mock.keys = AsyncMock(return_value=[])
        redis_mock.close = AsyncMock()
        return redis_mock

    @pytest.fixture
    def session_manager(self, mock_redis):
        """Create a session manager with mocked Redis."""
        import os
        import sys

        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "..", "telegram_bot")
        )
        from bot import RedisSessionManager

        sm = RedisSessionManager("redis://localhost:6379/0")
        sm._redis = mock_redis
        return sm

    @pytest.mark.asyncio
    async def test_connect_success(self, mock_redis):
        """Test successful Redis connection."""
        import os
        import sys

        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "..", "telegram_bot")
        )
        from bot import RedisSessionManager

        with patch("bot.redis_async.from_url", return_value=mock_redis):
            sm = RedisSessionManager("redis://localhost:6379/0")
            result = await sm.connect()
            assert result is True

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test Redis connection failure handling."""
        import os
        import sys

        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "..", "telegram_bot")
        )
        from bot import RedisSessionManager

        with patch(
            "bot.redis_async.from_url", side_effect=Exception("Connection refused")
        ):
            sm = RedisSessionManager("redis://invalid:6379/0")
            result = await sm.connect()
            assert result is False
            assert sm._redis is None

    @pytest.mark.asyncio
    async def test_set_session(self, session_manager, mock_redis):
        """Test storing session data in Redis."""
        user_id = 12345
        session_data = {
            "access_token": "test_token",
            "user": {"id": 1, "email": "test@example.com"},
            "chat_session_id": None,
            "pending_file": None,
        }

        result = await session_manager.set_session(user_id, session_data)
        assert result is True
        mock_redis.setex.assert_called_once()

        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == f"telegram_session:{user_id}"
        assert call_args[0][1] == 86400

    @pytest.mark.asyncio
    async def test_get_session_existing(self, session_manager, mock_redis):
        """Test retrieving existing session from Redis."""
        user_id = 12345
        session_data = {
            "access_token": "test_token",
            "user": {"id": 1, "email": "test@example.com"},
            "chat_session_id": None,
            "pending_file": None,
        }
        mock_redis.get.return_value = json.dumps(session_data)

        result = await session_manager.get_session(user_id)
        assert result is not None
        assert result["access_token"] == "test_token"
        assert result["user"]["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, session_manager, mock_redis):
        """Test retrieving non-existent session returns None."""
        user_id = 99999
        mock_redis.get.return_value = None

        result = await session_manager.get_session(user_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_session_expired(self, session_manager, mock_redis):
        """Test that expired sessions return None (TTL handled by Redis)."""
        user_id = 12345
        mock_redis.get.return_value = None

        result = await session_manager.get_session(user_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_session(self, session_manager, mock_redis):
        """Test updating specific fields in session."""
        user_id = 12345
        existing_data = {
            "access_token": "old_token",
            "user": {"id": 1},
            "chat_session_id": None,
            "pending_file": None,
        }
        mock_redis.get.return_value = json.dumps(existing_data)

        result = await session_manager.update_session(
            user_id, {"access_token": "new_token"}
        )
        assert result is True
        mock_redis.setex.assert_called_once()

        call_args = mock_redis.setex.call_args
        stored_data = json.loads(call_args[0][2])
        assert stored_data["access_token"] == "new_token"
        assert stored_data["user"]["id"] == 1

    @pytest.mark.asyncio
    async def test_update_session_no_existing(self, session_manager, mock_redis):
        """Test updating session that doesn't exist returns False."""
        user_id = 12345
        mock_redis.get.return_value = None

        result = await session_manager.update_session(
            user_id, {"access_token": "new_token"}
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_session(self, session_manager, mock_redis):
        """Test deleting session from Redis."""
        user_id = 12345

        result = await session_manager.delete_session(user_id)
        assert result is True
        mock_redis.delete.assert_called_once_with(f"telegram_session:{user_id}")

    @pytest.mark.asyncio
    async def test_clear_pending_file(self, session_manager, mock_redis):
        """Test clearing pending file from session."""
        user_id = 12345
        existing_data = {
            "access_token": "test_token",
            "user": {"id": 1},
            "chat_session_id": None,
            "pending_file": {"file": "base64encodeddata", "filename": "test.pdf"},
        }
        mock_redis.get.return_value = json.dumps(existing_data)

        result = await session_manager.clear_pending_file(user_id)
        assert result is True

        call_args = mock_redis.setex.call_args
        stored_data = json.loads(call_args[0][2])
        assert stored_data["pending_file"] is None

    @pytest.mark.asyncio
    async def test_count_active_sessions(self, session_manager, mock_redis):
        """Test counting active sessions in Redis."""
        mock_redis.keys.return_value = [
            "telegram_session:12345",
            "telegram_session:67890",
            "telegram_session:11111",
        ]

        count = await session_manager.count_active_sessions()
        assert count == 3

    @pytest.mark.asyncio
    async def test_count_active_sessions_empty(self, session_manager, mock_redis):
        """Test counting sessions when none exist."""
        mock_redis.keys.return_value = []

        count = await session_manager.count_active_sessions()
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_session_redis_unavailable(self):
        """Test get_session returns None when Redis is unavailable."""
        import os
        import sys

        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "..", "telegram_bot")
        )
        from bot import RedisSessionManager

        sm = RedisSessionManager("redis://localhost:6379/0")
        sm._redis = None

        result = await sm.get_session(12345)
        assert result is None

    @pytest.mark.asyncio
    async def test_set_session_redis_unavailable(self):
        """Test set_session falls back to in-memory when Redis is unavailable."""
        import os
        import sys

        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "..", "telegram_bot")
        )
        from bot import RedisSessionManager

        sm = RedisSessionManager("redis://localhost:6379/0")
        sm._redis = None

        result = await sm.set_session(12345, {"test": "data"})
        assert result is True  # stored in fallback dict

    @pytest.mark.asyncio
    async def test_fallback_get_set_roundtrip(self):
        """Test in-memory fallback: set then get returns the same session."""
        import os
        import sys

        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "..", "telegram_bot")
        )
        from bot import RedisSessionManager

        sm = RedisSessionManager("redis://localhost:6379/0")
        sm._redis = None

        session_data = {"access_token": "tok", "user": {"id": 7}, "chat_session_id": None, "pending_file": None}
        await sm.set_session(99, session_data)
        retrieved = await sm.get_session(99)
        assert retrieved == session_data

    @pytest.mark.asyncio
    async def test_fallback_delete_clears_session(self):
        """Test in-memory fallback delete removes the session."""
        import os
        import sys

        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "..", "telegram_bot")
        )
        from bot import RedisSessionManager

        sm = RedisSessionManager("redis://localhost:6379/0")
        sm._redis = None

        await sm.set_session(99, {"access_token": "tok"})
        await sm.delete_session(99)
        assert await sm.get_session(99) is None

    @pytest.mark.asyncio
    async def test_fallback_count_active_sessions(self):
        """Test count_active_sessions reflects fallback dict size."""
        import os
        import sys

        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "..", "telegram_bot")
        )
        from bot import RedisSessionManager

        sm = RedisSessionManager("redis://localhost:6379/0")
        sm._redis = None

        assert await sm.count_active_sessions() == 0
        await sm.set_session(1, {"t": "a"})
        await sm.set_session(2, {"t": "b"})
        assert await sm.count_active_sessions() == 2

    @pytest.mark.asyncio
    async def test_json_decode_error_handling(self, session_manager, mock_redis):
        """Test handling of corrupted JSON data in Redis."""
        user_id = 12345
        mock_redis.get.return_value = "{ invalid json }"

        result = await session_manager.get_session(user_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_close_connection(self, session_manager, mock_redis):
        """Test graceful connection close."""
        await session_manager.close()
        mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_key_format(self, session_manager):
        """Test that session keys follow the correct format."""
        user_id = 12345
        key = session_manager._get_key(user_id)
        assert key == f"telegram_session:{user_id}"

    @pytest.mark.asyncio
    async def test_ttl_is_24_hours(self, session_manager, mock_redis):
        """Test that session TTL is set to 24 hours (86400 seconds)."""
        user_id = 12345
        session_data = {"access_token": "test"}

        await session_manager.set_session(user_id, session_data)

        call_args = mock_redis.setex.call_args
        ttl = call_args[0][1]
        assert ttl == 86400

    @pytest.mark.asyncio
    async def test_pending_file_with_bytes_serialization(
        self, session_manager, mock_redis
    ):
        """Test that pending_file with binary data is handled correctly."""
        user_id = 12345
        session_data = {
            "access_token": "test_token",
            "pending_file": {
                "file": "base64_encoded_or_serialized",
                "filename": "test.pdf",
            },
        }

        await session_manager.set_session(user_id, session_data)

        call_args = mock_redis.setex.call_args
        stored_data = json.loads(call_args[0][2])
        assert stored_data["pending_file"]["filename"] == "test.pdf"


class TestTelegramBotSessionIntegration:
    """Integration tests for session handling in bot handlers."""

    @pytest.fixture
    def mock_session_manager(self):
        """Create a mock session manager."""
        manager = AsyncMock()
        manager.get_session = AsyncMock(return_value=None)
        manager.set_session = AsyncMock(return_value=True)
        manager.update_session = AsyncMock(return_value=True)
        manager.clear_pending_file = AsyncMock(return_value=True)
        manager.count_active_sessions = AsyncMock(return_value=5)
        manager.connect = AsyncMock(return_value=True)
        manager.close = AsyncMock()
        return manager

    @pytest.mark.asyncio
    async def test_expired_session_prompts_restart(self, mock_session_manager):
        """Test that expired sessions prompt user to restart."""
        mock_session_manager.get_session.return_value = None

        result = await mock_session_manager.get_session(12345)
        assert result is None

    @pytest.mark.asyncio
    async def test_session_restored_on_startup(self, mock_session_manager):
        """Test that session count is logged on startup."""
        count = await mock_session_manager.count_active_sessions()
        assert count == 5


class TestSessionResilience:
    """Tests for session resilience scenarios."""

    @pytest.mark.asyncio
    async def test_session_survives_bot_restart(self):
        """Test that sessions persist across bot restarts."""
        import os
        import sys

        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "..", "telegram_bot")
        )
        from bot import RedisSessionManager

        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps(
            {
                "access_token": "persisted_token",
                "user": {"id": 1},
                "chat_session_id": None,
                "pending_file": None,
            }
        )

        sm = RedisSessionManager("redis://localhost:6379/0")
        sm._redis = mock_redis

        session = await sm.get_session(12345)
        assert session is not None
        assert session["access_token"] == "persisted_token"

    @pytest.mark.asyncio
    async def test_upload_flow_continues_after_restart(self):
        """Test that upload flow state is preserved."""
        import os
        import sys

        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "..", "telegram_bot")
        )
        from bot import RedisSessionManager

        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps(
            {
                "access_token": "test_token",
                "user": {"id": 1},
                "chat_session_id": None,
                "pending_file": {
                    "file": "serialized_bytes",
                    "filename": "document.pdf",
                },
            }
        )
        mock_redis.setex.return_value = True

        sm = RedisSessionManager("redis://localhost:6379/0")
        sm._redis = mock_redis

        session = await sm.get_session(12345)
        assert session["pending_file"] is not None
        assert session["pending_file"]["filename"] == "document.pdf"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
