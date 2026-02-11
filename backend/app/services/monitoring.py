"""
Comprehensive monitoring service for SOWKNOW infrastructure.

Provides health checks, queue depth monitoring, cost tracking,
and alerting capabilities per PRD requirements.
"""
import os
import asyncio
import logging
import psutil
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from collections import defaultdict
from threading import Lock
import redis
import httpx

logger = logging.getLogger(__name__)


@dataclass
class APICostRecord:
    """Track API costs for Gemini and other services."""
    timestamp: datetime
    service: str  # 'gemini', 'hunyuan', 'moonshot', etc.
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
    triggered_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    notification_sent: bool = False


class CostTracker:
    """Track API costs with daily caps and budgeting."""

    # Pricing (as of 2025)
    GEMINI_PRICING = {
        "gemini-2.0-flash-exp": {
            "input": 0.00001,  # per 1K tokens
            "output": 0.00005,  # per 1K tokens
            "cache_read": 0.000001,  # per 1K cached tokens
        },
        "gemini-1.5-flash": {
            "input": 0.000075,
            "output": 0.00015,
            "cache_read": 0.000015,
        },
    }

    def __init__(self, daily_budget_usd: float = 5.0):
        """
        Initialize cost tracker.

        Args:
            daily_budget_usd: Daily budget cap in USD (default: $5.00)
        """
        self._daily_budget = daily_budget_usd
        self._cost_records: List[APICostRecord] = []
        self._lock = Lock()
        self._daily_totals: Dict[str, float] = defaultdict(float)

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
            service: Service name ('gemini', 'hunyuan', etc.)
            operation: Operation type ('chat', 'embedding', 'ocr', etc.)
            model: Model identifier
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cached_tokens: Number of cached tokens read

        Returns:
            Cost in USD
        """
        cost = 0.0

        if service == "gemini":
            pricing = self.GEMINI_PRICING.get(model, self.GEMINI_PRICING["gemini-2.0-flash-exp"])
            cost = (
                (input_tokens / 1000) * pricing["input"] +
                (output_tokens / 1000) * pricing["output"] +
                (cached_tokens / 1000) * pricing.get("cache_read", 0)
            )
        elif service == "hunyuan":
            # Hunyuan OCR pricing (example - update with actual)
            cost = 0.001  # Fixed cost per OCR call
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
            f"API cost recorded: {service}.{operation} = ${cost:.6f} "
            f"(in: {input_tokens}, out: {output_tokens})"
        )

        return cost

    def get_daily_cost(self, service: Optional[str] = None) -> float:
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

    def get_daily_cost_breakdown(self) -> Dict[str, float]:
        """Get cost breakdown by service for today."""
        today = datetime.now().date()
        breakdown: Dict[str, float] = defaultdict(float)

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

    def get_stats(self, days: int = 7) -> Dict[str, Any]:
        """
        Get cost statistics for the specified period.

        Args:
            days: Number of days to include

        Returns:
            Dictionary with cost statistics
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        daily_costs: Dict[str, float] = defaultdict(float)
        service_totals: Dict[str, float] = defaultdict(float)
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


class QueueMonitor:
    """Monitor Celery queue depth and processing metrics."""

    def __init__(self, redis_url: str):
        """
        Initialize queue monitor.

        Args:
            redis_url: Redis connection URL
        """
        self._redis_url = redis_url
        self._redis_client: Optional[redis.Redis] = None
        self._lock = Lock()

    def _get_redis(self) -> redis.Redis:
        """Get or create Redis client."""
        if self._redis_client is None:
            with self._lock:
                if self._redis_client is None:
                    self._redis_client = redis.from_url(
                        self._redis_url,
                        decode_responses=True
                    )
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
            key = f"celery"  # Default Celery key format
            # Try different key patterns
            depth = r.llen(key)
            if depth == 0:
                depth = r.scard(f"{key}:dequeued")
            return depth
        except Exception as e:
            logger.error(f"Failed to get queue depth: {e}")
            return 0

    def get_all_queue_depths(self) -> Dict[str, int]:
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

    def get_worker_status(self) -> Dict[str, Any]:
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
    def get_memory_usage() -> Dict[str, Any]:
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
    def get_cpu_usage() -> Dict[str, Any]:
        """Get current CPU usage statistics."""
        return {
            "percent": psutil.cpu_percent(interval=0.1),
            "count": psutil.cpu_count(),
            "freq": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None,
        }

    @staticmethod
    def get_disk_usage(path: str = "/") -> Dict[str, Any]:
        """Get disk usage statistics."""
        try:
            disk = psutil.disk_usage(path)
            return {
                "path": path,
                "total_gb": round(disk.total / (1024 ** 3), 2),
                "used_gb": round(disk.used / (1024 ** 3), 2),
                "free_gb": round(disk.free / (1024 ** 3), 2),
                "percent": disk.percent,
                "alert_high": disk.percent > 85,
            }
        except Exception as e:
            logger.error(f"Failed to get disk usage: {e}")
            return {"error": str(e)}

    @staticmethod
    def get_container_stats() -> Dict[str, Any]:
        """
        Get Docker container stats.

        Returns:
            Dictionary with container resource usage
        """
        try:
            import subprocess
            result = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            containers = []
            for line in lines:
                parts = line.split('\t')
                if len(parts) >= 3:
                    containers.append({
                        "name": parts[0],
                        "cpu_percent": parts[1],
                        "memory": parts[2],
                    })
            return {"containers": containers}
        except Exception as e:
            logger.error(f"Failed to get container stats: {e}")
            return {"error": str(e)}


class AlertManager:
    """Manage monitoring alerts and notifications."""

    def __init__(self):
        self._alerts: Dict[str, AlertConfig] = {}
        self._alert_states: Dict[str, AlertState] = {}
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

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Get list of currently triggered alerts."""
        active = []
        with self._lock:
            for name, state in self._alert_states.items():
                if state.triggered_at is not None:
                    config = self._alerts.get(name)
                    active.append({
                        "name": name,
                        "triggered_at": state.triggered_at.isoformat(),
                        "threshold": config.threshold if config else None,
                    })
        return active


# Global instances
_cost_tracker: Optional[CostTracker] = None
_queue_monitor: Optional[QueueMonitor] = None
_alert_manager = AlertManager()


def get_cost_tracker() -> CostTracker:
    """Get or create global cost tracker instance."""
    global _cost_tracker
    if _cost_tracker is None:
        daily_budget = float(os.getenv("GEMINI_DAILY_BUDGET_USD", "5.0"))
        _cost_tracker = CostTracker(daily_budget_usd=daily_budget)
    return _cost_tracker


def get_queue_monitor() -> QueueMonitor:
    """Get or create global queue monitor instance."""
    global _queue_monitor
    if _queue_monitor is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _queue_monitor = QueueMonitor(redis_url=redis_url)
    return _queue_monitor


def get_alert_manager() -> AlertManager:
    """Get global alert manager instance."""
    return _alert_manager


def setup_default_alerts() -> None:
    """Set up default monitoring alerts per PRD requirements."""
    manager = get_alert_manager()

    defaults = [
        AlertConfig("memory_high", 80.0, "gt", 300),
        AlertConfig("disk_high", 85.0, "gt", 300),
        AlertConfig("queue_congested", 100.0, "gt", 300),
        AlertConfig("cost_over_budget", 0.0, "gt", 60),
    ]

    for config in defaults:
        manager.register_alert(config)
