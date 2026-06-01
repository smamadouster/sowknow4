"""Per-user LLM token quotas with role-aware budgets.

Prevents a single Admin or Super User from exhausting the global daily budget,
which would break Chat for all other users (including heirs).

Blueprint reference: §2.3 Rate-Limit & Throttling Review
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# Role-aware daily token budgets (blueprint §2.3)
ROLE_QUOTAS: dict[str, dict[str, int]] = {
    "admin": {"tokens_per_day": 100_000, "concurrent": 3, "max_input_tokens": 50_000},
    "superuser": {"tokens_per_day": 40_000, "concurrent": 2, "max_input_tokens": 20_000},
    "user": {"tokens_per_day": 15_000, "concurrent": 1, "max_input_tokens": 5_000},
}

REDIS_KEY_PREFIX = "sowknow:user_quota"


class QuotaExceededError(Exception):
    """Raised when a user exceeds their daily LLM token budget."""

    def __init__(self, user_id: str, role: str, used: int, limit: int) -> None:
        self.user_id = user_id
        self.role = role
        self.used = used
        self.limit = limit
        super().__init__(
            f"Quota exceeded for user {user_id} ({role}): "
            f"{used:,} / {limit:,} tokens used today."
        )


class UserQuotaManager:
    """Tracks per-user daily LLM token consumption via Redis."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client

    def _key(self, user_id: str) -> str:
        today = datetime.now(timezone.utc).date().isoformat()
        return f"{REDIS_KEY_PREFIX}:{today}:{user_id}"

    def _get_redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        # Lazy import to avoid circular deps at module load time
        from app.services.openrouter_service import _get_redis_client

        return _get_redis_client()

    def get_quota(self, role: str) -> dict[str, int]:
        """Return the quota configuration for a role."""
        return ROLE_QUOTAS.get(role, ROLE_QUOTAS["user"])

    def check_and_consume(
        self,
        user_id: str,
        role: str,
        estimated_tokens: int,
    ) -> dict[str, Any]:
        """
        Check if the user has enough quota remaining and atomically consume it.

        Admin has total priority — quota limits are enforced for superuser and
        general user roles only. Admin usage is still tracked in Redis for
        observability.

        Args:
            user_id: Unique user identifier.
            role: User role (admin, superuser, user).
            estimated_tokens: Estimated tokens for this request.

        Returns:
            Dict with ``allowed`` (bool), ``used``, ``limit``, ``remaining``.

        Raises:
            QuotaExceededError: If the user has exceeded their daily budget.
        """
        # ── Admin total priority: bypass quota limits ──
        if role == "admin":
            redis = self._get_redis()
            if redis is not None:
                key = self._key(user_id)
                pipe = redis.pipeline()
                pipe.incrby(key, estimated_tokens)
                pipe.expire(key, 86_400)  # 24 hours
                pipe.execute()
                logger.info(
                    "Admin quota tracked (unlimited) user=%s estimated=%d",
                    user_id, estimated_tokens,
                )
            return {"allowed": True, "used": 0, "limit": -1, "remaining": -1}

        quota = self.get_quota(role)
        limit = quota["tokens_per_day"]
        max_input = quota["max_input_tokens"]

        if estimated_tokens > max_input:
            logger.warning(
                "User %s (%s) request exceeds max_input_tokens: %d > %d",
                user_id, role, estimated_tokens, max_input,
            )
            # Blueprint §2.3: hard block on max_input_tokens to prevent
            # runaway prompts from exhausting the daily budget.
            raise QuotaExceededError(
                user_id, role,
                used=estimated_tokens, limit=max_input,
            )

        redis = self._get_redis()
        if redis is None:
            # Redis unavailable — allow through (fail-open to avoid breaking chat)
            logger.warning("Redis unavailable for quota check; allowing request")
            return {"allowed": True, "used": 0, "limit": limit, "remaining": limit}

        key = self._key(user_id)
        pipe = redis.pipeline()
        pipe.incrby(key, estimated_tokens)
        pipe.expire(key, 86_400)  # 24 hours
        results = pipe.execute()
        used = int(results[0])

        remaining = limit - used
        if remaining < 0:
            # Roll back the increment since we're rejecting
            redis.decrby(key, estimated_tokens)
            raise QuotaExceededError(user_id, role, used, limit)

        logger.info(
            "Quota check user=%s role=%s used=%d limit=%d remaining=%d",
            user_id, role, used, limit, remaining,
        )
        return {"allowed": True, "used": used, "limit": limit, "remaining": remaining}

    def get_usage(self, user_id: str) -> dict[str, Any]:
        """Return current quota usage for a user."""
        redis = self._get_redis()
        key = self._key(user_id)
        used = 0
        if redis is not None:
            val = redis.get(key)
            if val is not None:
                used = int(val)
        return {"used": used}


# Singleton instance
user_quota_manager = UserQuotaManager()
