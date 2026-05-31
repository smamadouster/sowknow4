"""
Rollback Monitor — §3.4 Priority & Rollback Plan

Tracks the metrics that trigger tier-model rollbacks during phased rollout.
All counters are Redis-backed with 24-hour rolling windows so they survive
restarts and can be queried from the status endpoint.

Rollback triggers monitored:
  • >10% JSON parse failure rate  → revert standard tier
  • Latency >3s (standard/simple) → revert standard/simple tier
  • Cost per report >$0.50        → revert complex tier
  • TTFT >8s (complex)            → revert complex tier
  • Heir satisfaction score drop  → revert primary model

Usage:
    from app.services.rollback_monitor import rollback_monitor
    rollback_monitor.record_latency(tier="standard", latency_ms=1200)
    rollback_monitor.record_json_parse(tier="standard", success=True)
    rollback_monitor.record_report_cost(cost_usd=0.32)
    status = rollback_monitor.get_status()
"""

import logging
import os
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds from §3.4 blueprint
# ---------------------------------------------------------------------------

ROLLBACK_THRESHOLDS = {
    "json_parse_failure_rate_pct": 10.0,  # >10% failures → revert standard
    "latency_ms": 3_000,  # >3s → revert standard/simple
    "report_cost_usd": 0.50,  # >$0.50 → revert complex
    "ttft_ms": 8_000,  # >8s → revert complex
    "satisfaction_score_min": 4.0,  # <4.0/5 → revert primary model
}

# Redis TTL for rolling windows (24 hours)
_WINDOW_TTL = 86_400


def _get_redis() -> Any | None:
    """Lazy Redis import to avoid startup dependency issues."""
    try:
        from app.core.redis_url import safe_redis_url
        import redis as _redis

        return _redis.from_url(safe_redis_url(), socket_timeout=2, decode_responses=True)
    except Exception as exc:
        logger.debug("RollbackMonitor: Redis unavailable (%s)", exc)
        return None


class RollbackMonitor:
    """
    Rolling-window metric tracker for rollback-trigger detection.

    Uses Redis sorted sets with millisecond timestamps as scores.  Older entries
    are automatically evicted by TTL.  If Redis is unavailable the monitor
    silently no-ops (fail-open) so it never blocks the request path.
    """

    def __init__(self) -> None:
        self._thresholds = ROLLBACK_THRESHOLDS.copy()

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def _zadd(self, key: str, value: str) -> None:
        """Add an entry to a Redis sorted set with current timestamp as score."""
        redis = _get_redis()
        if redis is None:
            return
        try:
            now = time.time()
            redis.zadd(key, {value: now})
            redis.expire(key, _WINDOW_TTL)
        except Exception as exc:
            logger.debug("RollbackMonitor._zadd failed: %s", exc)

    def _zcount(self, key: str) -> int:
        """Count entries in a Redis sorted set within the rolling window."""
        redis = _get_redis()
        if redis is None:
            return 0
        try:
            now = time.time()
            window_start = now - _WINDOW_TTL
            return redis.zcount(key, window_start, now)
        except Exception as exc:
            logger.debug("RollbackMonitor._zcount failed: %s", exc)
            return 0

    def _zrange(self, key: str, count: int = 100) -> list[str]:
        """Get recent entries from a Redis sorted set."""
        redis = _get_redis()
        if redis is None:
            return []
        try:
            return redis.zrevrange(key, 0, count - 1)
        except Exception as exc:
            logger.debug("RollbackMonitor._zrange failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Public recording API
    # ------------------------------------------------------------------

    def record_latency(self, tier: str, latency_ms: float) -> None:
        """Record an LLM call latency for the given tier."""
        self._zadd(f"rollback:latency:{tier}", str(latency_ms))
        if latency_ms > self._thresholds["latency_ms"]:
            logger.warning(
                "[ROLLBACK-TRIGGER] tier=%s latency=%.0fms exceeds threshold=%.0fms",
                tier,
                latency_ms,
                self._thresholds["latency_ms"],
            )

    def record_ttft(self, tier: str, ttft_ms: float) -> None:
        """Record time-to-first-token for the given tier."""
        self._zadd(f"rollback:ttft:{tier}", str(ttft_ms))
        if ttft_ms > self._thresholds["ttft_ms"]:
            logger.warning(
                "[ROLLBACK-TRIGGER] tier=%s ttft=%.0fms exceeds threshold=%.0fms",
                tier,
                ttft_ms,
                self._thresholds["ttft_ms"],
            )

    def record_json_parse(self, tier: str, success: bool) -> None:
        """Record a JSON parse attempt outcome for the given tier."""
        key = f"rollback:json_ok:{tier}" if success else f"rollback:json_fail:{tier}"
        self._zadd(key, str(time.time()))
        if not success:
            fail_rate = self._json_failure_rate(tier)
            if fail_rate > self._thresholds["json_parse_failure_rate_pct"]:
                logger.critical(
                    "[ROLLBACK-TRIGGER] tier=%s json_parse_failure_rate=%.1f%% exceeds threshold=%.1f%%",
                    tier,
                    fail_rate,
                    self._thresholds["json_parse_failure_rate_pct"],
                )

    def record_report_cost(self, cost_usd: float) -> None:
        """Record the cost of a comprehensive report generation."""
        self._zadd("rollback:report_cost", str(cost_usd))
        if cost_usd > self._thresholds["report_cost_usd"]:
            logger.warning(
                "[ROLLBACK-TRIGGER] report_cost=$%.3f exceeds threshold=$%.2f",
                cost_usd,
                self._thresholds["report_cost_usd"],
            )

    def record_satisfaction(self, score: float, user_role: str = "user") -> None:
        """Record a user satisfaction score (1–5 scale)."""
        self._zadd(f"rollback:satisfaction:{user_role}", str(score))
        if score < self._thresholds["satisfaction_score_min"]:
            logger.warning(
                "[ROLLBACK-TRIGGER] satisfaction_score=%.1f below threshold=%.1f (user_role=%s)",
                score,
                self._thresholds["satisfaction_score_min"],
                user_role,
            )

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------

    def _json_failure_rate(self, tier: str) -> float:
        """Calculate JSON parse failure rate % for a tier over the rolling window."""
        ok = self._zcount(f"rollback:json_ok:{tier}")
        fail = self._zcount(f"rollback:json_fail:{tier}")
        total = ok + fail
        if total == 0:
            return 0.0
        return (fail / total) * 100.0

    def _percentile(self, key: str, p: float) -> float:
        """Approximate percentile from Redis sorted-set values."""
        values = [float(v) for v in self._zrange(key, count=1000) if v]
        if not values:
            return 0.0
        values.sort()
        idx = int(len(values) * p / 100)
        idx = min(idx, len(values) - 1)
        return values[idx]

    def _average(self, key: str) -> float:
        """Average value from Redis sorted-set entries."""
        values = [float(v) for v in self._zrange(key, count=1000) if v]
        if not values:
            return 0.0
        return sum(values) / len(values)

    # ------------------------------------------------------------------
    # Status / querying
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """
        Return current rollback status including metrics and active triggers.

        Returns:
            Dictionary with:
            - thresholds: current threshold values
            - tiers: per-tier metrics (latency_p95, latency_avg, ttft_p95, json_failure_rate)
            - reports: report cost metrics (avg_cost, max_cost)
            - satisfaction: average satisfaction score by role
            - triggers: list of active rollback triggers
            - rollback_actions: recommended actions for active triggers
        """
        tiers = ["simple", "standard", "complex"]
        tier_metrics: dict[str, dict[str, Any]] = {}
        triggers: list[dict[str, Any]] = []
        rollback_actions: list[str] = []

        for tier in tiers:
            lat_p95 = self._percentile(f"rollback:latency:{tier}", 95)
            lat_avg = self._average(f"rollback:latency:{tier}")
            ttft_p95 = self._percentile(f"rollback:ttft:{tier}", 95)
            json_rate = self._json_failure_rate(tier)

            tier_metrics[tier] = {
                "latency_p95_ms": round(lat_p95, 1),
                "latency_avg_ms": round(lat_avg, 1),
                "ttft_p95_ms": round(ttft_p95, 1),
                "json_parse_failure_rate_pct": round(json_rate, 2),
                "request_count": self._zcount(f"rollback:latency:{tier}"),
            }

            # Check triggers
            if json_rate > self._thresholds["json_parse_failure_rate_pct"]:
                triggers.append(
                    {
                        "tier": tier,
                        "metric": "json_parse_failure_rate",
                        "value": round(json_rate, 2),
                        "threshold": self._thresholds["json_parse_failure_rate_pct"],
                    }
                )
                if tier == "standard":
                    rollback_actions.append(
                        "ROLLBACK: Set OPENROUTER_TIER_STANDARD=qwen/qwen3.5-plus-20260420"
                    )

            if lat_p95 > self._thresholds["latency_ms"]:
                triggers.append(
                    {
                        "tier": tier,
                        "metric": "latency_p95",
                        "value": round(lat_p95, 1),
                        "threshold": self._thresholds["latency_ms"],
                    }
                )
                if tier in ("standard", "simple"):
                    rollback_actions.append(
                        f"ROLLBACK: Set OPENROUTER_TIER_{tier.upper()}=qwen/qwen3.5-plus-20260420"
                        if tier == "standard"
                        else "ROLLBACK: Set OPENROUTER_TIER_SIMPLE=qwen/qwen3.5-plus-20260420"
                    )

            if ttft_p95 > self._thresholds["ttft_ms"] and tier == "complex":
                triggers.append(
                    {
                        "tier": tier,
                        "metric": "ttft_p95",
                        "value": round(ttft_p95, 1),
                        "threshold": self._thresholds["ttft_ms"],
                    }
                )
                rollback_actions.append(
                    "ROLLBACK: Set OPENROUTER_TIER_COMPLEX=deepseek/deepseek-v4-pro"
                )

        # Report costs
        costs = [float(v) for v in self._zrange("rollback:report_cost", count=100)]
        report_metrics = {
            "avg_cost_usd": round(sum(costs) / len(costs), 4) if costs else 0.0,
            "max_cost_usd": round(max(costs), 4) if costs else 0.0,
            "count": len(costs),
        }
        if costs and max(costs) > self._thresholds["report_cost_usd"]:
            triggers.append(
                {
                    "tier": "complex",
                    "metric": "report_cost",
                    "value": round(max(costs), 4),
                    "threshold": self._thresholds["report_cost_usd"],
                }
            )
            rollback_actions.append(
                "ROLLBACK: Set OPENROUTER_TIER_COMPLEX=deepseek/deepseek-v4-pro"
            )

        # Satisfaction
        satisfaction: dict[str, float] = {}
        for role in ("user", "superuser", "admin"):
            scores = [float(v) for v in self._zrange(f"rollback:satisfaction:{role}", count=100)]
            if scores:
                satisfaction[role] = round(sum(scores) / len(scores), 2)
                if satisfaction[role] < self._thresholds["satisfaction_score_min"]:
                    triggers.append(
                        {
                            "role": role,
                            "metric": "satisfaction_score",
                            "value": satisfaction[role],
                            "threshold": self._thresholds["satisfaction_score_min"],
                        }
                    )
                    rollback_actions.append(
                        "ROLLBACK: Revert OPENROUTER_MODEL to previous value"
                    )

        # Deduplicate rollback actions
        seen: set[str] = set()
        deduped_actions: list[str] = []
        for action in rollback_actions:
            if action not in seen:
                seen.add(action)
                deduped_actions.append(action)

        return {
            "thresholds": self._thresholds,
            "tiers": tier_metrics,
            "reports": report_metrics,
            "satisfaction": satisfaction,
            "triggers": triggers,
            "rollback_actions": deduped_actions,
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }

    def get_rollback_recommendations(self) -> list[str]:
        """Return a concise list of recommended rollback actions."""
        status = self.get_status()
        return status.get("rollback_actions", [])


# Singleton
rollback_monitor = RollbackMonitor()
