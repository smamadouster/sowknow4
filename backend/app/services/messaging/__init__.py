"""
NATS JetStream messaging client for SOWKNOW.

Provides connection management, stream/consumer helpers, and
graceful lifecycle handling for distributed agent communication.
"""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

import nats
from nats.aio.client import Client as NatsClient
from nats.js.api import ConsumerConfig, PubAck, RetentionPolicy, StreamConfig, StreamInfo
from nats.js.client import JetStreamContext

logger = logging.getLogger(__name__)

NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")


class MessagingClient:
    """
    Async NATS + JetStream client with auto-reconnect and graceful shutdown.

    Usage:
        client = MessagingClient()
        await client.connect()
        sub = await client.subscribe("tasks.new", handle_task)
        await client.publish("tasks.new", b"payload")
        await client.close()
    """

    def __init__(self, url: str = NATS_URL) -> None:
        self.url = url
        self._nc: NatsClient | None = None
        self._js: JetStreamContext | None = None
        self._subscriptions: list[Any] = []

    @property
    def nc(self) -> NatsClient:
        if self._nc is None:
            raise RuntimeError("NATS not connected. Call connect() first.")
        return self._nc

    @property
    def js(self) -> JetStreamContext:
        if self._js is None:
            raise RuntimeError("JetStream not initialized. Call connect() first.")
        return self._js

    async def connect(self) -> None:
        """Connect to NATS and initialize JetStream."""
        self._nc = await nats.connect(
            self.url,
            reconnect_time_wait=2,
            max_reconnect_attempts=10,
            name="sowknow-messaging",
        )
        self._js = self._nc.jetstream()
        logger.info("NATS connected to %s", self.url)

    async def close(self) -> None:
        """Unsubscribe all consumers and close the connection."""
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        self._subscriptions.clear()
        if self._nc:
            await self._nc.close()
            self._nc = None
            self._js = None
        logger.info("NATS disconnected")

    async def ensure_stream(
        self,
        name: str,
        subjects: list[str],
        retention: RetentionPolicy = RetentionPolicy.WORK_QUEUE,
        max_msgs: int = 100_000,
    ) -> StreamInfo:
        """Idempotent stream creation. Updates if it already exists."""
        config = StreamConfig(
            name=name,
            subjects=subjects,
            retention=retention,
            max_msgs=max_msgs,
        )
        try:
            info = await self._js.update_stream(config)
            logger.debug("Stream updated: %s", name)
        except Exception:
            info = await self._js.add_stream(config)
            logger.info("Stream created: %s", name)
        return info

    async def subscribe(
        self,
        subject: str,
        callback: Callable[[Any], Awaitable[None]],
        durable: str | None = None,
        max_deliver: int = 3,
        ack_wait: float = 30.0,
        deliver_group: str | None = None,
    ) -> Any:
        """
        Subscribe to a JetStream subject with proper ConsumerConfig.

        SECURITY: max_deliver is passed via ConsumerConfig (not a raw kwarg)
        to comply with nats-py >= 2.7 JetStream API.
        """
        config = ConsumerConfig(
            durable_name=durable,
            max_deliver=max_deliver,
            ack_wait=ack_wait,
            deliver_group=deliver_group,
        )
        sub = await self._js.subscribe(
            subject,
            cb=callback,
            config=config,
        )
        self._subscriptions.append(sub)
        logger.info("Subscribed to %s (durable=%s)", subject, durable)
        return sub

    async def publish(
        self,
        subject: str,
        payload: bytes,
        headers: dict[str, str] | None = None,
    ) -> PubAck:
        """Publish a message to a JetStream subject."""
        return await self._js.publish(subject, payload, headers=headers)

    async def request(
        self,
        subject: str,
        payload: bytes,
        timeout: float = 5.0,
    ) -> Any:
        """Send a request and wait for a reply."""
        return await self.nc.request(subject, payload, timeout=timeout)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_messaging_client: MessagingClient | None = None


async def get_messaging_client() -> MessagingClient:
    """Get or create the shared messaging client."""
    global _messaging_client
    if _messaging_client is None:
        _messaging_client = MessagingClient()
        await _messaging_client.connect()
    return _messaging_client


async def close_messaging_client() -> None:
    """Close the shared messaging client."""
    global _messaging_client
    if _messaging_client:
        await _messaging_client.close()
        _messaging_client = None
