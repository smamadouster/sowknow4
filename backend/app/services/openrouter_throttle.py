"""Provider-aware dynamic throttling for OpenRouter.

Implements Tier C from the LLM Architecture Audit Blueprint:
- Per-tier rate limits (free / standard / pro)
- RPM + RPD tracking via Redis
- Adaptive backoff: 50% RPM reduction for 2 minutes after a 429
- Warning logs when free-tier fallback is triggered

Blueprint reference: §2.3 Rate-Limit & Throttling Review
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# OpenRouter tier limits from blueprint §2.3
OPENROUTER_RATE_LIMITS: dict[str, dict[str, int]] = {
    "free": {"rpm": 10, "rpd": 200},
    "standard": {"rpm": 100, "rpd": 2000},
    "pro": {"rpm": 500, "rpd": 10000},
}

# Adaptive backoff: reduce RPM by this fraction after a 429
ADAPTIVE_BACKOFF_FACTOR = 0.5
# How long the adaptive backoff lasts (seconds)
ADAPTIVE_BACKOFF_TTL_SECONDS = 120

REDIS_KEY_PREFIX = "sowknow:openrouter:throttle"

# Models considered "pro" tier (frontier / highest cost)
_PRO_MODELS = {
    "anthropic/claude-3.5-sonnet",
    "anthropic/claude-3.5-sonnet-20241022",
    "deepseek/deepseek-v4-pro",
    "deepseek/deepseek-v4-flash",
    "moonshotai/kimi-k2.6",
}

# Models considered "free" tier (anything with :free suffix is auto-detected)
_FREE_SUFFIX = ":free"


def _detect_tier(model: str) -> str:
    """Map a model identifier to its provider tier for rate-limiting."""
    if _FREE_SUFFIX in model:
        return "free"
    if model in _PRO_MODELS:
        return "pro"
    return "standard"


class OpenRouterThrottle:
    """Dynamic throttling with adaptive backoff for OpenRouter API calls."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client

    def _get_redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        try:
            from app.services.openrouter_service import _get_redis_client

            return _get_redis_client()
        except Exception:
            return None

    @staticmethod
    def _rpm_key(tier: str, bucket: str) -> str:
        return f"{REDIS_KEY_PREFIX}:rpm:{tier}:{bucket}"

    @staticmethod
    def _rpd_key(tier: str, bucket: str) -> str:
        return f"{REDIS_KEY_PREFIX}:rpd:{tier}:{bucket}"

    @staticmethod
    def _backoff_key(tier: str) -> str:
        return f"{REDIS_KEY_PREFIX}:backoff:{tier}"

    def _current_buckets(self) -> tuple[str, str]:
        """Return (minute_bucket, day_bucket) strings for Redis keys."""
        now = datetime.now(timezone.utc)
        minute_bucket = now.strftime("%Y%m%d%H%M")
        day_bucket = now.strftime("%Y%m%d")
        return minute_bucket, day_bucket

    def _effective_limit(self, tier: str, limit_type: str) -> int:
        """Return the effective limit, accounting for adaptive backoff."""
        base = OPENROUTER_RATE_LIMITS.get(tier, OPENROUTER_RATE_LIMITS["standard"])[
            limit_type
        ]
        redis = self._get_redis()
        if redis is None:
            return base

        backoff_key = self._backoff_key(tier)
        try:
            if redis.exists(backoff_key):
                return int(base * ADAPTIVE_BACKOFF_FACTOR)
        except Exception:
            pass
        return base

    def check_allowed(self, model: str) -> bool:
        """
        Pre-flight check: are we still under the rate limit for this model's tier?

        Returns True if the call is allowed, False if it would exceed RPM/RPD.
        """
        tier = _detect_tier(model)
        minute_bucket, day_bucket = self._current_buckets()
        redis = self._get_redis()

        if redis is None:
            # Redis unavailable — fail-open to avoid breaking chat
            return True

        try:
            rpm_key = self._rpm_key(tier, minute_bucket)
            rpd_key = self._rpd_key(tier, day_bucket)

            rpm_used = int(redis.get(rpm_key) or 0)
            rpd_used = int(redis.get(rpd_key) or 0)

            rpm_limit = self._effective_limit(tier, "rpm")
            rpd_limit = self._effective_limit(tier, "rpd")

            if rpm_used >= rpm_limit or rpd_used >= rpd_limit:
                logger.warning(
                    "OpenRouter throttle BLOCKED tier=%s model=%s rpm=%d/%d rpd=%d/%d",
                    tier,
                    model,
                    rpm_used,
                    rpm_limit,
                    rpd_used,
                    rpd_limit,
                )
                return False

            return True
        except Exception as exc:
            logger.warning("OpenRouter throttle check failed, allowing call: %s", exc)
            return True

    def record_request(self, model: str) -> None:
        """Increment RPM and RPD counters after a successful API call."""
        tier = _detect_tier(model)
        minute_bucket, day_bucket = self._current_buckets()
        redis = self._get_redis()

        if redis is None:
            return

        try:
            rpm_key = self._rpm_key(tier, minute_bucket)
            rpd_key = self._rpd_key(tier, day_bucket)

            pipe = redis.pipeline()
            pipe.incr(rpm_key)
            pipe.expire(rpm_key, 60)
            pipe.incr(rpd_key)
            pipe.expire(rpd_key, 86_400)
            pipe.execute()
        except Exception as exc:
            logger.warning("OpenRouter throttle record_request failed: %s", exc)

    def record_429(self, model: str) -> None:
        """
        Activate adaptive backoff after receiving a 429.

        Reduces the effective RPM limit by 50% for 2 minutes.
        Logs a warning so the Admin knows when free-tier fallback is involved.
        """
        tier = _detect_tier(model)
        redis = self._get_redis()

        is_free = tier == "free"
        msg = (
            f"OpenRouter 429 received — adaptive backoff activated "
            f"(tier={tier}, model={model}, rpm reduced by 50% for {ADAPTIVE_BACKOFF_TTL_SECONDS}s)"
        )
        if is_free:
            msg += " [FREE-TIER FALLBACK]"
        logger.warning(msg)

        if redis is None:
            return

        try:
            backoff_key = self._backoff_key(tier)
            redis.setex(backoff_key, ADAPTIVE_BACKOFF_TTL_SECONDS, "1")
        except Exception as exc:
            logger.warning("OpenRouter throttle record_429 failed: %s", exc)

    def get_status(self, model: str) -> dict[str, Any]:
        """Return current throttle status for a model's tier."""
        tier = _detect_tier(model)
        minute_bucket, day_bucket = self._current_buckets()
        redis = self._get_redis()

        rpm_used = 0
        rpd_used = 0
        in_backoff = False

        if redis is not None:
            try:
                rpm_used = int(redis.get(self._rpm_key(tier, minute_bucket)) or 0)
                rpd_used = int(redis.get(self._rpd_key(tier, day_bucket)) or 0)
                in_backoff = bool(redis.exists(self._backoff_key(tier)))
            except Exception:
                pass

        rpm_limit = self._effective_limit(tier, "rpm")
        rpd_limit = self._effective_limit(tier, "rpd")

        return {
            "tier": tier,
            "model": model,
            "rpm": {"used": rpm_used, "limit": rpm_limit},
            "rpd": {"used": rpd_used, "limit": rpd_limit},
            "adaptive_backoff_active": in_backoff,
        }


# Singleton instance
openrouter_throttle = OpenRouterThrottle()
