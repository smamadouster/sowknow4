"""
Base agent for SOWKNOW Swarm v2.

Every swarm agent inherits from BaseAgent and communicates over NATS JetStream.
Agents are discoverable, heartbeat-monitored, and gracefully shut down.
"""

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from nats.js.api import RetentionPolicy

from app.services.messaging import MessagingClient, get_messaging_client

logger = logging.getLogger(__name__)


class AgentStatus(StrEnum):
    """Lifecycle states for a swarm agent."""

    INITIALIZING = "initializing"
    IDLE = "idle"
    BUSY = "busy"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"


class AgentCapability(StrEnum):
    """Well-known agent capabilities."""

    CHAT = "chat"
    SEARCH = "search"
    EMBED = "embed"
    OCR = "ocr"
    EXTRACT = "extract"
    CLASSIFY = "classify"
    SYNTHESIZE = "synthesize"
    ALERT = "alert"
    ADMIN = "admin"


class BaseAgent(ABC):
    """
    Abstract base class for all SOWKNOW swarm agents.

    Subclasses must implement:
        - `capabilities` — list of AgentCapability values
        - `handle_message(msg)` — core processing logic

    Example:
        class SearchAgent(BaseAgent):
            capabilities = [AgentCapability.SEARCH]

            async def handle_message(self, msg: Msg) -> None:
                payload = json.loads(msg.data)
                results = await self.search(payload["query"])
                await msg.respond(json.dumps(results).encode())
    """

    capabilities: list[AgentCapability] = []

    def __init__(
        self,
        agent_type: str,
        messaging: MessagingClient | None = None,
    ) -> None:
        self.agent_id = f"{agent_type}-{uuid.uuid4().hex[:8]}"
        self.agent_type = agent_type
        self.status = AgentStatus.INITIALIZING
        self._messaging = messaging
        self._subscriptions: list[Any] = []
        self._heartbeat_task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def messaging(self) -> MessagingClient:
        if self._messaging is None:
            raise RuntimeError("Messaging client not set. Call start() first.")
        return self._messaging

    def info(self) -> dict[str, Any]:
        """Return serializable agent metadata."""
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "status": self.status.value,
            "capabilities": [c.value for c in self.capabilities],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect messaging, subscribe to subjects, begin heartbeat."""
        logger.info("[%s] Starting agent...", self.agent_id)
        self.status = AgentStatus.INITIALIZING

        if self._messaging is None:
            self._messaging = await get_messaging_client()

        # Ensure swarm streams exist
        await self.messaging.ensure_stream(
            name="SWARM_HEARTBEATS",
            subjects=["swarm.heartbeat.>"],
            retention=RetentionPolicy.LIMITS,
        )
        await self.messaging.ensure_stream(
            name="SWARM_MESSAGES",
            subjects=[f"swarm.agent.{self.agent_id}.>", f"swarm.type.{self.agent_type}.>"],
            retention=RetentionPolicy.WORK_QUEUE,
        )

        # Subscribe to direct messages
        sub = await self.messaging.subscribe(
            subject=f"swarm.agent.{self.agent_id}.task",
            callback=self._on_message,
            durable=f"{self.agent_id}-tasks",
            max_deliver=3,
            ack_wait=60.0,
        )
        self._subscriptions.append(sub)

        # Subscribe to broadcast messages for this agent type
        sub = await self.messaging.subscribe(
            subject=f"swarm.type.{self.agent_type}.broadcast",
            callback=self._on_broadcast,
            durable=f"{self.agent_type}-broadcasts",
            max_deliver=3,
            ack_wait=30.0,
            deliver_group=self.agent_type,
        )
        self._subscriptions.append(sub)

        # Start heartbeat loop
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self.status = AgentStatus.IDLE
        logger.info("[%s] Agent started (caps=%s)", self.agent_id, self.capabilities)

    async def stop(self) -> None:
        """Graceful shutdown: stop heartbeat, unsubscribe, mark stopped."""
        logger.info("[%s] Stopping agent...", self.agent_id)
        self.status = AgentStatus.STOPPING
        self._stop_event.set()

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        self._subscriptions.clear()

        self.status = AgentStatus.STOPPED
        logger.info("[%s] Agent stopped.", self.agent_id)

    # ------------------------------------------------------------------
    # Messaging handlers
    # ------------------------------------------------------------------

    async def _on_message(self, msg: Any) -> None:
        """Handle direct task messages with ack/nack."""
        self.status = AgentStatus.BUSY
        try:
            await self.handle_message(msg)
            await msg.ack()
        except Exception as exc:
            logger.warning("[%s] Task failed: %s", self.agent_id, exc)
            await msg.nak()
        finally:
            self.status = AgentStatus.IDLE

    async def _on_broadcast(self, msg: Any) -> None:
        """Handle broadcast messages (best-effort, no nack on failure)."""
        try:
            await self.handle_broadcast(msg)
            await msg.ack()
        except Exception as exc:
            logger.warning("[%s] Broadcast failed: %s", self.agent_id, exc)
            await msg.ack()  # Don't retry broadcasts

    @abstractmethod
    async def handle_message(self, msg: Any) -> None:
        """Process a direct task message. Must be implemented by subclasses."""
        ...

    async def handle_broadcast(self, msg: Any) -> None:
        """Process a broadcast message. Optional override."""
        pass

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Publish a heartbeat every 10 seconds until stopped."""
        while not self._stop_event.is_set():
            try:
                payload = json.dumps(self.info()).encode()
                await self.messaging.publish(
                    f"swarm.heartbeat.{self.agent_id}",
                    payload,
                )
            except Exception as exc:
                logger.debug("[%s] Heartbeat failed: %s", self.agent_id, exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                pass
