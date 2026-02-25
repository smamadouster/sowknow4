"""
Unit tests for UserContextStore (RedisSessionManager) in the Telegram bot.

Verifies:
- Redis-backed session storage (mock Redis)
- 24-hour TTL enforcement
- JSON serialisation / deserialisation
- Graceful in-memory fallback when Redis is unavailable
- Active session count reporting used on startup
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(redis_ok: bool = True):
    """
    Return a UserContextStore (RedisSessionManager) with a mocked Redis
    connection.  When redis_ok=False the store falls back to in-memory dict.
    """
    import sys
    import os

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "telegram_bot"))

    from bot import UserContextStore  # noqa: E402

    store = UserContextStore.__new__(UserContextStore)
    store._redis_url = "redis://localhost:6379/0"
    store._fallback = {}

    if redis_ok:
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        store._redis = mock_redis
    else:
        store._redis = None  # triggers in-memory fallback path

    return store


# ---------------------------------------------------------------------------
# Tests: Redis-backed path (mock Redis)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_session_serialises_to_json():
    """set_session must JSON-serialise data and call Redis SETEX with 86400 TTL."""
    store = _make_store(redis_ok=True)
    session_data = {"chat_session_id": "abc", "uploaded_files": []}

    store._redis.setex = AsyncMock(return_value=True)

    await store.set_session(12345, session_data)

    store._redis.setex.assert_awaited_once()
    call_args = store._redis.setex.call_args
    key, ttl, value = call_args[0]
    assert "12345" in key
    assert ttl == 86400  # 24-hour TTL
    assert json.loads(value) == session_data


@pytest.mark.asyncio
async def test_get_session_deserialises_from_redis():
    """get_session must deserialise JSON returned by Redis."""
    store = _make_store(redis_ok=True)
    payload = {"chat_session_id": "xyz", "role": "user"}

    store._redis.get = AsyncMock(return_value=json.dumps(payload))

    result = await store.get_session(99)
    assert result == payload


@pytest.mark.asyncio
async def test_cache_miss_returns_none():
    """get_session returns None when key is absent in Redis."""
    store = _make_store(redis_ok=True)
    store._redis.get = AsyncMock(return_value=None)

    result = await store.get_session(404)
    assert result is None


# ---------------------------------------------------------------------------
# Tests: in-memory fallback when Redis is unavailable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_set_and_get():
    """When Redis is down, sessions are stored in the in-memory fallback dict."""
    store = _make_store(redis_ok=False)
    data = {"key": "value"}

    await store.set_session(1, data)
    result = await store.get_session(1)

    assert result is not None
    assert result["key"] == "value"


@pytest.mark.asyncio
async def test_fallback_delete():
    """clear_session removes entry from in-memory fallback."""
    store = _make_store(redis_ok=False)
    await store.set_session(2, {"foo": "bar"})
    await store.delete_session(2)

    result = await store.get_session(2)
    assert result is None


# ---------------------------------------------------------------------------
# Tests: UserContextStore alias
# ---------------------------------------------------------------------------

def test_user_context_store_alias_is_redis_session_manager():
    """UserContextStore must be an alias for RedisSessionManager."""
    import sys
    import os

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "telegram_bot"))
    from bot import UserContextStore, RedisSessionManager  # noqa: E402

    assert UserContextStore is RedisSessionManager
