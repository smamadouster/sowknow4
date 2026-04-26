"""
Flock Alerter for SOWKNOW Swarm v2.

Publishes and subscribes to alert streams over NATS JetStream.
Provides rate-limited, deduplicated alerting for agents, services,
and operational events.

Alert subjects:
    ALERTS.INFO.{source}
    ALERTS.WARNING.{source}
    ALERTS.ERROR.{source}
    ALERTS.CRITICAL.{source}
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Awaitable, Callable

from nats.js.api import RetentionPolicy

from app.services.messaging import MessagingClient, get_messaging_client

logger = logging.getLogger(__name__)

ALERT_STREAM = "SOWKNOW_ALERTS"
ALERT_SUBJECT_PREFIX = "alerts"
DEFAULT_RATE_LIMIT_SECONDS = 60.0


class AlertLevel(StrEnum):
    """Severity levels for swarm alerts."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AlertEvent:
    """Standard alert envelope."""

    level: AlertLevel
    source: str  # e.g., "search-agent", "postgres", "celery-worker"
    message: str
    alert_id: str = field(default_factory=lambda: hashlib.sha256(str(time.time()).encode()).hexdigest()[:16])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_bytes(self) -> bytes:
        return json.dumps(self.__dict__, default=str).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> "AlertEvent":
        d = json.loads(data)
        d["level"] = AlertLevel(d.get("level", "info"))
        return cls(**d)

    def dedup_key(self) -> str:
        """Return a key for short-term deduplication."""
        return hashlib.sha256(
            f"{self.source}:{self.message}:{self.level}".encode()
        ).hexdigest()


class FlockAlerter:
    """
    Publish and subscribe to swarm alerts with rate limiting.

    Usage:
        alerter = FlockAlerter()
        await alerter.connect()

        await alerter.alert(AlertLevel.ERROR, "search-agent", "Index timeout")

        await alerter.subscribe(AlertLevel.ERROR, on_error)
    """

    def __init__(
        self,
        messaging: MessagingClient | None = None,
        rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
    ) -> None:
        self._messaging = messaging
        self._rate_limit_seconds = rate_limit_seconds
        self._last_seen: dict[str, float] = {}  # dedup_key → unix_timestamp
        self._subscriptions: list[Any] = []

    @property
    def messaging(self) -> MessagingClient:
        if self._messaging is None:
            raise RuntimeError("Messaging client not set. Call connect() first.")
        return self._messaging

    async def connect(self) -> None:
        """Ensure alert stream exists."""
        if self._messaging is None:
            self._messaging = await get_messaging_client()

        subjects = [f"{ALERT_SUBJECT_PREFIX}.{level.value}.>" for level in AlertLevel]
        await self.messaging.ensure_stream(
            name=ALERT_STREAM,
            subjects=subjects,
            retention=RetentionPolicy.LIMITS,
            max_msgs=100_000,
        )
        logger.info("FlockAlerter connected")

    async def close(self) -> None:
        """Unsubscribe from alert streams."""
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        self._subscriptions.clear()
        logger.info("FlockAlerter closed")

    def _is_rate_limited(self, event: AlertEvent) -> bool:
        """Check if this alert was recently sent (deduplication)."""
        key = event.dedup_key()
        now = time.time()
        last = self._last_seen.get(key, 0)
        if now - last < self._rate_limit_seconds:
            return True
        self._last_seen[key] = now
        return False

    async def alert(
        self,
        level: AlertLevel,
        source: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Publish an alert event.

        Returns:
            True if published, False if rate-limited/deduplicated.
        """
        event = AlertEvent(
            level=level,
            source=source,
            message=message,
            metadata=metadata or {},
        )

        if self._is_rate_limited(event):
            logger.debug("Alert rate-limited: %s/%s", source, level)
            return False

        await self.messaging.publish(
            f"{ALERT_SUBJECT_PREFIX}.{level.value}.{source}",
            event.to_bytes(),
            headers={"level": level.value, "source": source},
        )
        logger.info("Alert published [%s] %s: %s", level.value, source, message)
        return True

    async def subscribe(
        self,
        level: AlertLevel,
        callback: Callable[[AlertEvent], Awaitable[None]],
        source_filter: str | None = None,
        deliver_group: str | None = None,
    ) -> Any:
        """
        Subscribe to alerts at a given level.

        Args:
            level: Severity level to subscribe to.
            callback: Async handler for AlertEvent.
            source_filter: Optional wildcard source (e.g., "search-*").
            deliver_group: Load-balance across multiple subscribers.
        """
        subject = f"{ALERT_SUBJECT_PREFIX}.{level.value}.{source_filter or '*'}"

        async def _wrapper(msg: Any) -> None:
            try:
                event = AlertEvent.from_bytes(msg.data)
                await callback(event)
                await msg.ack()
            except Exception as exc:
                logger.warning("Alert handler failed: %s", exc)
                await msg.nak()

        sub = await self.messaging.subscribe(
            subject=subject,
            callback=_wrapper,
            durable=f"alerter-{level.value}",
            max_deliver=3,
            ack_wait=30.0,
            deliver_group=deliver_group,
        )
        self._subscriptions.append(sub)
        logger.info("Subscribed to alerts: %s", subject)
        return sub

    async def info(self, source: str, message: str, metadata: dict[str, Any] | None = None) -> bool:
        """Convenience: publish INFO alert."""
        return await self.alert(AlertLevel.INFO, source, message, metadata)

    async def warning(self, source: str, message: str, metadata: dict[str, Any] | None = None) -> bool:
        """Convenience: publish WARNING alert."""
        return await self.alert(AlertLevel.WARNING, source, message, metadata)

    async def error(self, source: str, message: str, metadata: dict[str, Any] | None = None) -> bool:
        """Convenience: publish ERROR alert."""
        return await self.alert(AlertLevel.ERROR, source, message, metadata)

    async def critical(self, source: str, message: str, metadata: dict[str, Any] | None = None) -> bool:
        """Convenience: publish CRITICAL alert."""
        return await self.alert(AlertLevel.CRITICAL, source, message, metadata)
