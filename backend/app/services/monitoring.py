"""
Comprehensive monitoring service for SOWKNOW infrastructure.

Provides health checks, queue depth monitoring, cost tracking,
cost ceiling enforcement, and alerting capabilities per PRD requirements.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any

import psutil

try:
    from prometheus_client import Histogram

    _prometheus_available = True
except ImportError:
    Histogram = None  # type: ignore[assignment,misc]
    _prometheus_available = False
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock

import redis

logger = logging.getLogger(__name__)

# Prometheus histogram for OCR confidence — labelled by engine method
sowknow_ocr_confidence: Any = None
if _prometheus_available and Histogram is not None:
    try:
        sowknow_ocr_confidence = Histogram(
            "sowknow_ocr_confidence",
            "OCR confidence score distribution by engine",
            ["method"],  # labels: "tesseract", "paddle"
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        )
    except Exception:
        pass  # Already registered in test environments


@dataclass
class APICostRecord:
    """Track API costs for MiniMax and other services."""

    timestamp: datetime
    service: str  # 'minimax', 'paddleocr', 'tesseract', 'moonshot', etc.
    operation: str  # 'chat', 'embedding', 'ocr', etc.
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class AlertConfig:
    """Configuration for monitoring alerts."""

    name: str
    threshold: float
    comparison: str = "gt"  # 'gt', 'lt', 'eq'
    duration_seconds: int = 300  # 5 minutes default
    enabled: bool = True


@dataclass
class AlertState:
    """Track alert state to prevent duplicate notifications."""

    alert_name: str
    triggered_at: datetime | None = None
    resolved_at: datetime | None = None
    notification_sent: bool = False


class CostTracker:
    """Track API costs with daily caps and budgeting."""

    # Pricing (as of 2026-04-27) — per 1K tokens
    OPENROUTER_PRICING = {
        # DeepSeek (primary)
        "deepseek/deepseek-v4-pro": {
            "input": 0.00174,   # $1.74 per 1M
            "output": 0.00348,  # $3.48 per 1M
        },
        "deepseek/deepseek-v4-flash": {
            "input": 0.00014,
            "output": 0.00028,
        },
        # Qwen (standard tier)
        "qwen/qwen3.5-plus": {
            "input": 0.00026,
            "output": 0.00200,
        },
        "qwen/qwen3-235b-a22b:free": {
            "input": 0.0,
            "output": 0.0,
        },
        # Legacy / fallback
        "moonshotai/kimi-k2.6": {
            "input": 0.000745,
            "output": 0.004655,
        },
        "moonshotai/kimi-k2.5": {
            "input": 0.00044,
            "output": 0.00200,
        },
        # MiniMax (direct)
        "minimax/minimax-m2.7": {
            "input": 0.00030,
            "output": 0.00120,
        },
        "minimax/minimax-m2.5": {
            "input": 0.00015,
            "output": 0.00095,
        },
        "MiniMax-M2.7": {
            "input": 0.00030,
            "output": 0.00120,
        },
        "MiniMax-M2.5": {
            "input": 0.00015,
            "output": 0.00095,
        },
        # Older references
        "minimax/minimax-01": {
            "input": 0.00055,
            "output": 0.0022,
        },
        "openai/gpt-4o": {
            "input": 0.0025,
            "output": 0.01,
        },
        "openai/gpt-4o-mini": {
            "input": 0.00015,
            "output": 0.0006,
        },
        "anthropic/claude-3.5-sonnet": {
            "input": 0.003,
            "output": 0.015,
        },
    }

    # OCR pricing — PaddleOCR cloud reference rates (local usage is always free)
    OCR_PRICING = {
        "base": 0.001,  # $0.001/page — standard 1024×1024 mode
        "large": 0.002,  # $0.002/page — high-res 1280×1280 mode
        "gundam": 0.003,  # $0.003/page — multi-pass mode
    }

    # Local engines are always free (open-source, CPU-based)
    LOCAL_OCR_ENGINES = {"paddleocr": 0.0, "paddle": 0.0, "tesseract": 0.0, "none": 0.0}

    def __init__(self, daily_budget_usd: float = 5.0):
        """
        Initialize cost tracker.

        Args:
            daily_budget_usd: Daily budget cap in USD (default: $5.00)
        """
        self._daily_budget = daily_budget_usd
        self._cost_records: list[APICostRecord] = []
        self._lock = Lock()
        self._daily_totals: dict[str, float] = defaultdict(float)

    def record_api_call(
        self,
        service: str,
        operation: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
    ) -> float:
        """
        Record an API call and return its cost.

        Args:
            service: Service name ('minimax', 'paddleocr', 'tesseract', etc.)
            operation: Operation type ('chat', 'embedding', 'ocr', etc.)
            model: Model identifier
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cached_tokens: Number of cached tokens read

        Returns:
            Cost in USD
        """
        cost = 0.0

        if service == "openrouter":
            pricing = self.OPENROUTER_PRICING.get(model, self.OPENROUTER_PRICING.get("deepseek/deepseek-v4-pro"))
            cost = (input_tokens / 1000) * pricing["input"] + (output_tokens / 1000) * pricing["output"]
        elif service == "minimax":
            pricing = self.OPENROUTER_PRICING.get(model, self.OPENROUTER_PRICING.get("minimax/minimax-m2.7"))
            cost = (input_tokens / 1000) * pricing["input"] + (output_tokens / 1000) * pricing["output"]
        elif service in ("paddleocr", "tesseract"):
            # Local OCR - no API cost, just compute resources
            cost = 0.0  # Free open source OCR
        else:
            # Default cost calculation
            cost = 0.0001

        record = APICostRecord(
            timestamp=datetime.now(),
            service=service,
            operation=operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )

        with self._lock:
            self._cost_records.append(record)
            today = datetime.now().date()
            key = f"{today.isoformat()}_{service}"
            self._daily_totals[key] += cost

        logger.debug(
            f"API cost recorded: {service}.{operation} ({model}) = ${cost:.6f} (in: {input_tokens}, out: {output_tokens})"
        )

        return cost

    def get_daily_cost(self, service: str | None = None) -> float:
        """
        Get total cost for today.

        Args:
            service: Optional service name to filter by

        Returns:
            Total cost in USD for today
        """
        today = datetime.now().date()
        total = 0.0

        with self._lock:
            for record in self._cost_records:
                if record.timestamp.date() == today:
                    if service is None or record.service == service:
                        total += record.cost_usd

        return total

    def get_daily_cost_breakdown(self) -> dict[str, float]:
        """Get cost breakdown by service for today."""
        today = datetime.now().date()
        breakdown: dict[str, float] = defaultdict(float)

        with self._lock:
            for record in self._cost_records:
                if record.timestamp.date() == today:
                    breakdown[record.service] += record.cost_usd

        return dict(breakdown)

    def is_over_budget(self) -> bool:
        """Check if daily budget has been exceeded."""
        return self.get_daily_cost() > self._daily_budget

    def get_remaining_budget(self) -> float:
        """Get remaining daily budget."""
        return max(0, self._daily_budget - self.get_daily_cost())

    def get_stats(self, days: int = 7) -> dict[str, Any]:
        """
        Get cost statistics for the specified period.

        Args:
            days: Number of days to include

        Returns:
            Dictionary with cost statistics
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        daily_costs: dict[str, float] = defaultdict(float)
        service_totals: dict[str, float] = defaultdict(float)
        total_cost = 0.0

        with self._lock:
            for record in self._cost_records:
                if record.timestamp >= cutoff_date:
                    date_key = record.timestamp.date().isoformat()
                    daily_costs[date_key] += record.cost_usd
                    service_totals[record.service] += record.cost_usd
                    total_cost += record.cost_usd

        return {
            "period_days": days,
            "total_cost_usd": round(total_cost, 4),
            "average_daily_cost": round(total_cost / days, 4) if days > 0 else 0,
            "daily_costs": dict(sorted(daily_costs.items())),
            "service_breakdown": dict(service_totals),
            "daily_budget": self._daily_budget,
            "today_cost": self.get_daily_cost(),
            "budget_remaining": self.get_remaining_budget(),
            "over_budget": self.is_over_budget(),
        }

    def track_ocr_operation(
        self,
        method: str,
        mode: str = "base",
        pages: int = 1,
    ) -> float:
        """
        Track an OCR operation and record its cost.

        Args:
            method: OCR engine used ("paddle", "paddleocr", "tesseract")
            mode: Resolution mode ("base", "large", "gundam")
            pages: Number of pages processed

        Returns:
            Cost in USD (0.0 for local engines)
        """
        cost = self._record_cost(method, mode, pages)
        logger.debug(f"OCR cost tracked: {method}/{mode} × {pages} page(s) = ${cost:.4f}")
        return cost

    def _record_cost(self, method: str, mode: str, pages: int) -> float:
        """Record OCR cost and append to internal cost records."""
        # Local engines are free
        if method.lower() in self.LOCAL_OCR_ENGINES:
            cost_per_page = 0.0
        else:
            cost_per_page = self.OCR_PRICING.get(mode, 0.001)
        total = cost_per_page * pages

        record = APICostRecord(
            timestamp=datetime.now(),
            service="ocr",
            operation=f"{method}/{mode}",
            cost_usd=total,
        )
        with self._lock:
            self._cost_records.append(record)
        return total


class CostCeiling:
    """Enforce hard and soft cost ceilings on LLM consumption.

    Features:
    - Daily budget cap (hard ceiling: reject calls when exceeded)
    - Tier budget allocation (complex/standard/simple each get a % of daily budget)
    - Per-request token limit (reject unreasonably large requests)
    - Emergency circuit breaker (auto-shutoff when spike detected)
    - Rolling window rate limit (calls per minute)
    """

    DEFAULT_TIER_BUDGET_PCT = {
        "complex": 0.50,
        "standard": 0.35,
        "simple": 0.15,
    }

    # Max tokens per request by tier (hard limit to prevent runaway costs)
    MAX_TOKENS_PER_REQUEST = {
        "complex": 32_768,
        "standard": 16_384,
        "simple": 8_192,
    }

    def __init__(
        self,
        daily_budget_usd: float | None = None,
        tier_budget_pct: dict[str, float] | None = None,
        max_calls_per_minute: int = 120,
        emergency_spike_multiplier: float = 3.0,
    ):
        self._daily_budget = daily_budget_usd or float(os.getenv("OPENROUTER_DAILY_BUDGET_USD", "5.0"))
        self._tier_budget_pct = tier_budget_pct or self.DEFAULT_TIER_BUDGET_PCT
        self._max_calls_per_minute = max_calls_per_minute
        self._emergency_spike_multiplier = emergency_spike_multiplier

        self._call_times: list[datetime] = []
        self._tier_spent_today: dict[str, float] = defaultdict(float)
        self._emergency_triggered: bool = False
        self._emergency_triggered_at: datetime | None = None
        self._lock = Lock()

    def _estimate_cost(self, service: str, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate the cost of a prospective API call."""
        pricing = CostTracker.OPENROUTER_PRICING.get(model, CostTracker.OPENROUTER_PRICING.get("deepseek/deepseek-v4-pro"))
        return (input_tokens / 1000) * pricing.get("input", 0.001) + (output_tokens / 1000) * pricing.get("output", 0.003)

    def _is_rate_limited(self) -> bool:
        """Check if calls per minute exceed threshold."""
        now = datetime.now()
        window_start = now - timedelta(minutes=1)
        with self._lock:
            self._call_times = [t for t in self._call_times if t > window_start]
            return len(self._call_times) >= self._max_calls_per_minute

    def _check_emergency_spike(self, estimated_cost: float) -> bool:
        """Detect cost spikes that might indicate a runaway loop or attack."""
        tracker = get_cost_tracker()
        today_cost = tracker.get_daily_cost()
        hour_ago = datetime.now() - timedelta(hours=1)

        with self._lock:
            recent_cost = sum(
                r.cost_usd for r in tracker._cost_records
                if r.timestamp > hour_ago
            )

        # Trigger emergency if this single call costs more than N× the average hourly spend
        avg_hourly = today_cost / max(1, (datetime.now().hour + 1))
        if estimated_cost > avg_hourly * self._emergency_spike_multiplier and avg_hourly > 0.01:
            self._emergency_triggered = True
            self._emergency_triggered_at = datetime.now()
            logger.critical(
                f"EMERGENCY CIRCUIT BREAKER: Call cost ${estimated_cost:.4f} exceeds "
                f"{self._emergency_spike_multiplier}× avg hourly (${avg_hourly:.4f}). "
                f"Blocking LLM calls for 5 minutes."
            )
            return True
        return False

    def check_call_allowed(
        self,
        service: str,
        model: str,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        tier: str = "standard",
    ) -> bool:
        """Check if a prospective LLM call is within budget.

        Returns True if allowed, False if it would exceed any ceiling.
        """
        # 1. Emergency circuit breaker
        if self._emergency_triggered:
            if self._emergency_triggered_at and (datetime.now() - self._emergency_triggered_at) < timedelta(minutes=5):
                logger.warning("CostCeiling: Emergency circuit breaker active — call blocked")
                return False
            else:
                self._emergency_triggered = False
                logger.info("CostCeiling: Emergency circuit breaker reset")

        # 2. Rate limiting
        if self._is_rate_limited():
            logger.warning("CostCeiling: Rate limit exceeded — call blocked")
            return False

        # 3. Per-request token ceiling
        max_tokens = self.MAX_TOKENS_PER_REQUEST.get(tier, 16_384)
        if estimated_input_tokens + estimated_output_tokens > max_tokens:
            logger.warning(
                f"CostCeiling: Token ceiling exceeded ({estimated_input_tokens}+{estimated_output_tokens} > {max_tokens}) — call blocked"
            )
            return False

        # 4. Daily budget ceiling
        tracker = get_cost_tracker()
        today_cost = tracker.get_daily_cost()
        if today_cost >= self._daily_budget:
            logger.warning(f"CostCeiling: Daily budget exhausted (${today_cost:.4f} / ${self._daily_budget:.4f}) — call blocked")
            return False

        # 5. Tier budget ceiling
        tier_pct = self._tier_budget_pct.get(tier, 0.35)
        tier_budget = self._daily_budget * tier_pct
        tier_spent = tracker.get_daily_cost(service) + self._tier_spent_today.get(tier, 0.0)
        estimated_cost = self._estimate_cost(service, model, estimated_input_tokens, estimated_output_tokens)

        if tier_spent + estimated_cost > tier_budget:
            logger.warning(
                f"CostCeiling: Tier '{tier}' budget exhausted (${tier_spent:.4f} + ${estimated_cost:.4f} > ${tier_budget:.4f}) — call blocked"
            )
            return False

        # 6. Emergency spike detection
        if self._check_emergency_spike(estimated_cost):
            return False

        # All checks passed — record the call
        with self._lock:
            self._call_times.append(datetime.now())
            self._tier_spent_today[tier] += estimated_cost

        logger.debug(
            f"CostCeiling: Call approved ({service}/{model}, tier={tier}, est=${estimated_cost:.4f}, "
            f"today=${today_cost:.4f}, tier_spent=${tier_spent:.4f})"
        )
        return True

    def get_status(self) -> dict[str, Any]:
        """Get current ceiling status for health/monitoring endpoints."""
        tracker = get_cost_tracker()
        today_cost = tracker.get_daily_cost()
        return {
            "daily_budget_usd": self._daily_budget,
            "today_spent_usd": round(today_cost, 4),
            "remaining_usd": round(max(0, self._daily_budget - today_cost), 4),
            "emergency_triggered": self._emergency_triggered,
            "emergency_triggered_at": self._emergency_triggered_at.isoformat() if self._emergency_triggered_at else None,
            "tier_budgets": {
                tier: {
                    "budget_usd": round(self._daily_budget * pct, 4),
                    "spent_usd": round(tracker.get_daily_cost("openrouter") * pct + self._tier_spent_today.get(tier, 0.0), 4),
                    "pct": pct,
                }
                for tier, pct in self._tier_budget_pct.items()
            },
            "rate_limit": {
                "max_calls_per_minute": self._max_calls_per_minute,
                "calls_in_last_minute": len(self._call_times),
            },
        }

    def reset_emergency(self) -> None:
        """Manually reset emergency circuit breaker (admin use)."""
        self._emergency_triggered = False
        self._emergency_triggered_at = None
        logger.info("CostCeiling: Emergency circuit breaker manually reset")


class QueueMonitor:
    """Monitor Celery queue depth and processing metrics."""

    def __init__(self, redis_url: str):
        """
        Initialize queue monitor.

        Args:
            redis_url: Redis connection URL
        """
        self._redis_url = redis_url
        self._redis_client: redis.Redis | None = None
        self._lock = Lock()

    def _get_redis(self) -> redis.Redis:
        """Get or create Redis client."""
        if self._redis_client is None:
            with self._lock:
                if self._redis_client is None:
                    self._redis_client = redis.from_url(self._redis_url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5)
        return self._redis_client

    def get_queue_depth(self, queue_name: str = "celery") -> int:
        """
        Get current queue depth.

        Args:
            queue_name: Name of the Celery queue

        Returns:
            Number of tasks in the queue
        """
        try:
            r = self._get_redis()
            key = "celery"  # Default Celery key format
            # Try different key patterns
            depth = r.llen(key)
            if depth == 0:
                depth = r.scard(f"{key}:dequeued")
            return depth
        except Exception as e:
            logger.error(f"Failed to get queue depth: {e}")
            return 0

    def get_all_queue_depths(self) -> dict[str, int]:
        """Get depths for all Celery queues."""
        depths = {}
        try:
            r = self._get_redis()
            # Scan for Celery-related keys
            for key in r.scan_iter("celery*"):
                key_str = key if isinstance(key, str) else key.decode()
                if "dequeued" not in key_str:
                    try:
                        depth = r.llen(key_str)
                        if depth > 0:
                            depths[key_str] = depth
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Failed to scan queues: {e}")

        return depths

    def is_queue_congested(self, threshold: int = 100) -> bool:
        """
        Check if queue is congested.

        Args:
            threshold: Congestion threshold (default: 100 per PRD)

        Returns:
            True if queue depth exceeds threshold
        """
        return self.get_queue_depth() > threshold

    def get_worker_status(self) -> dict[str, Any]:
        """
        Get status of active workers.

        Returns:
            Dictionary with worker information
        """
        try:
            r = self._get_redis()
            # Get active workers from Celery
            active_keys = r.scan_iter("celery-task-meta-*")
            active = sum(1 for _ in active_keys)

            return {
                "active_tasks": active,
                "queue_depth": self.get_queue_depth(),
                "congested": self.is_queue_congested(),
            }
        except Exception as e:
            logger.error(f"Failed to get worker status: {e}")
            return {
                "active_tasks": 0,
                "queue_depth": 0,
                "congested": False,
            }


class SystemMonitor:
    """Monitor system resources including memory, CPU, and disk."""

    @staticmethod
    def get_memory_usage() -> dict[str, Any]:
        """Get current memory usage statistics."""
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        return {
            "total_mb": round(mem.total / (1024 * 1024), 2),
            "available_mb": round(mem.available / (1024 * 1024), 2),
            "used_mb": round(mem.used / (1024 * 1024), 2),
            "percent": mem.percent,
            "swap_total_mb": round(swap.total / (1024 * 1024), 2),
            "swap_used_mb": round(swap.used / (1024 * 1024), 2),
            "swap_percent": swap.percent,
            "alert_high": mem.percent > 80,
        }

    @staticmethod
    def get_cpu_usage() -> dict[str, Any]:
        """Get current CPU usage statistics."""
        return {
            "percent": psutil.cpu_percent(interval=0.1),
            "count": psutil.cpu_count(),
            "freq": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None,
        }

    @staticmethod
    def get_disk_usage(path: str = "/") -> dict[str, Any]:
        """Get disk usage statistics."""
        try:
            disk = psutil.disk_usage(path)
            return {
                "path": path,
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent,
                "alert_high": disk.percent > 85,
            }
        except Exception as e:
            logger.error(f"Failed to get disk usage: {e}")
            return {"error": str(e)}

    @staticmethod
    def get_container_stats() -> dict[str, Any]:
        """
        Get Docker container stats.

        Returns:
            Dictionary with container resource usage
        """
        try:
            import subprocess

            result = subprocess.run(
                [
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{.Name}}\t{{.MemUsage}}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = result.stdout.strip().split("\n")
            containers = []
            total_sowknow_mb = 0.0

            for line in lines:
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    name = parts[0]
                    mem_str = parts[1]

                    mem_mb = SystemMonitor._parse_memory_string(mem_str)

                    if "sowknow" in name.lower():
                        total_sowknow_mb += mem_mb

                    containers.append(
                        {
                            "name": name,
                            "memory_mb": mem_mb,
                            "memory_str": mem_str,
                        }
                    )
            return {
                "containers": containers,
                "total_sowknow_mb": round(total_sowknow_mb, 2),
                "total_sowknow_gb": round(total_sowknow_mb / 1024, 2),
            }
        except Exception as e:
            logger.error(f"Failed to get container stats: {e}")
            return {"error": str(e)}

    @staticmethod
    def _parse_memory_string(mem_str: str) -> float:
        """Parse memory string like '1.5GiB' or '512MiB' to MB."""
        import re

        match = re.match(r"([\d.]+)\s*([KMGT]i?B)", mem_str.strip())
        if not match:
            return 0.0
        value = float(match.group(1))
        unit = match.group(2).upper()

        multipliers = {
            "B": 1 / 1024,
            "KB": 1 / 1024,
            "MB": 1,
            "GB": 1024,
            "TB": 1024 * 1024,
            "KIB": 1 / 1024,
            "MIB": 1,
            "GIB": 1024,
            "TIB": 1024 * 1024,
        }
        return value * multipliers.get(unit, 1)


class AlertManager:
    """Manage monitoring alerts and notifications."""

    def __init__(self):
        self._alerts: dict[str, AlertConfig] = {}
        self._alert_states: dict[str, AlertState] = {}
        self._lock = Lock()

    def register_alert(self, config: AlertConfig) -> None:
        """Register a new alert configuration."""
        with self._lock:
            self._alerts[config.name] = config
            if config.name not in self._alert_states:
                self._alert_states[config.name] = AlertState(alert_name=config.name)

    def check_alert(self, name: str, current_value: float) -> bool:
        """
        Check if an alert should be triggered.

        Args:
            name: Alert name
            current_value: Current value to check against threshold

        Returns:
            True if alert is triggered
        """
        config = self._alerts.get(name)
        if not config or not config.enabled:
            return False

        state = self._alert_states.get(name)
        if not state:
            return False

        triggered = False
        if config.comparison == "gt":
            triggered = current_value > config.threshold
        elif config.comparison == "lt":
            triggered = current_value < config.threshold
        elif config.comparison == "eq":
            triggered = abs(current_value - config.threshold) < 0.001

        if triggered and state.triggered_at is None:
            state.triggered_at = datetime.now()
            logger.warning(f"Alert triggered: {name} (value: {current_value}, threshold: {config.threshold})")
            return True
        elif not triggered and state.triggered_at is not None:
            state.resolved_at = datetime.now()
            state.triggered_at = None
            state.notification_sent = False
            logger.info(f"Alert resolved: {name}")

        return False

    def get_active_alerts(self) -> list[dict[str, Any]]:
        """Get list of currently triggered alerts."""
        active = []
        with self._lock:
            for name, state in self._alert_states.items():
                if state.triggered_at is not None:
                    config = self._alerts.get(name)
                    active.append(
                        {
                            "name": name,
                            "triggered_at": state.triggered_at.isoformat(),
                            "threshold": config.threshold if config else None,
                        }
                    )
        return active


# Global instances
_cost_tracker: CostTracker | None = None
_queue_monitor: QueueMonitor | None = None
_alert_manager = AlertManager()
_cost_ceiling: CostCeiling | None = None


def get_cost_tracker() -> CostTracker:
    """Get or create global cost tracker instance."""
    global _cost_tracker
    if _cost_tracker is None:
        daily_budget = float(os.getenv("OPENROUTER_DAILY_BUDGET_USD", "5.0"))
        _cost_tracker = CostTracker(daily_budget_usd=daily_budget)
    return _cost_tracker


def get_cost_ceiling() -> CostCeiling:
    """Get or create global cost ceiling instance."""
    global _cost_ceiling
    if _cost_ceiling is None:
        daily_budget = float(os.getenv("OPENROUTER_DAILY_BUDGET_USD", "5.0"))
        _cost_ceiling = CostCeiling(daily_budget_usd=daily_budget)
    return _cost_ceiling


def get_queue_monitor() -> QueueMonitor:
    """Get or create global queue monitor instance."""
    global _queue_monitor
    if _queue_monitor is None:
        from app.core.redis_url import safe_redis_url

        _queue_monitor = QueueMonitor(redis_url=safe_redis_url())
    return _queue_monitor


def get_alert_manager() -> AlertManager:
    """Get global alert manager instance."""
    return _alert_manager


def setup_default_alerts() -> None:
    """Set up default monitoring alerts per PRD requirements."""
    manager = get_alert_manager()

    defaults = [
        AlertConfig("sowknow_memory_gb", 6.0, "gt", 300),  # PRD: SOWKNOW containers >6GB
        AlertConfig("vps_memory_percent", 80.0, "gt", 300),  # PRD: VPS memory >80%
        AlertConfig("disk_high", 85.0, "gt", 300),
        AlertConfig("queue_congested", 100.0, "gt", 300),
        AlertConfig("cost_over_budget", 0.0, "gt", 60),
        AlertConfig("error_rate_high", 5.0, "gt", 300),  # PRD: 5xx error rate >5%
    ]

    for config in defaults:
        manager.register_alert(config)
