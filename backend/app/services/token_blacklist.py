"""Redis-backed JWT blacklist helpers."""

import hashlib
import logging

import redis

from app.core.redis_url import safe_redis_url

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None


def _client() -> redis.Redis | None:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        client = redis.from_url(safe_redis_url(), decode_responses=True, socket_timeout=5, socket_connect_timeout=5)
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception as exc:
        logger.warning("Token blacklist Redis unavailable: %s", exc)
        return None


def _key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"blacklist:{digest}"


def blacklist_token(token: str, expires_in_seconds: int) -> bool:
    """Blacklist a JWT until it would naturally expire."""
    client = _client()
    if client is None or expires_in_seconds <= 0:
        return False
    try:
        client.setex(_key(token), expires_in_seconds, "1")
        return True
    except Exception as exc:
        logger.error("Failed to blacklist token: %s", exc)
        return False


def is_token_blacklisted(token: str) -> bool:
    """Return True if the JWT has been explicitly revoked."""
    client = _client()
    if client is None:
        return False
    try:
        return client.exists(_key(token)) > 0
    except Exception as exc:
        logger.error("Failed to check token blacklist: %s", exc)
        return False
