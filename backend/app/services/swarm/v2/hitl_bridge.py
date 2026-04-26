"""
Human-in-the-Loop (HITL) Bridge for SOWKNOW Swarm v2.

Publishes tasks that require human approval over NATS JetStream and
subscribes to human responses. Handles timeouts, retries (max_deliver=3),
and escalation.

Typical flow:
    1. Agent → HITLBridge.request_approval(task)
    2. Human operator receives notification (Telegram, email, dashboard)
    3. Human responds via NATS subject `HITL.RESPONSES.{task_id}`
    4. Agent receives approval/denial and continues
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Awaitable, Callable

from nats.js.api import RetentionPolicy

from app.services.messaging import MessagingClient, get_messaging_client

logger = logging.getLogger(__name__)

HITL_STREAM = "HITL_REQUESTS"
HITL_REQUEST_SUBJECT = "hitl.request"
HITL_RESPONSE_SUBJECT_PREFIX = "hitl.response"
DEFAULT_TIMEOUT_SECONDS = 300.0  # 5 minutes


class HITLStatus(StrEnum):
    """Lifecycle of a HITL request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"
    ESCALATED = "escalated"


@dataclass
class HITLRequest:
    """Payload for a human approval request."""

    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    agent_id: str = ""
    action: str = ""  # e.g., "delete_document", "promote_user"
    resource_type: str = ""
    resource_id: str = ""
    reason: str = ""  # Why human review is needed
    payload: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    requested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_bytes(self) -> bytes:
        return json.dumps(self.__dict__, default=str).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> "HITLRequest":
        return cls(**json.loads(data))


@dataclass
class HITLResponse:
    """Payload for a human approval response."""

    task_id: str = ""
    status: HITLStatus = HITLStatus.PENDING
    responder_id: str = ""  # User ID of the human
    comment: str = ""
    responded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_bytes(self) -> bytes:
        return json.dumps(self.__dict__, default=str).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> "HITLResponse":
        d = json.loads(data)
        d["status"] = HITLStatus(d.get("status", "pending"))
        return cls(**d)


class HITLBridge:
    """
    Bridge between swarm agents and human operators.

    Usage:
        bridge = HITLBridge()
        await bridge.connect()

        # Request approval
        req = HITLRequest(agent_id="search-01", action="delete_document", ...)
        resp = await bridge.request_approval(req)

        # Subscribe to all HITL requests (for a dashboard or notifier)
        await bridge.subscribe_requests(on_request)
    """

    def __init__(self, messaging: MessagingClient | None = None) -> None:
        self._messaging = messaging
        self._pending: dict[str, asyncio.Future[HITLResponse]] = {}
        self._subscriptions: list[Any] = []

    @property
    def messaging(self) -> MessagingClient:
        if self._messaging is None:
            raise RuntimeError("Messaging client not set. Call connect() first.")
        return self._messaging

    async def connect(self) -> None:
        """Ensure streams exist and subscribe to response queue."""
        if self._messaging is None:
            self._messaging = await get_messaging_client()

        await self.messaging.ensure_stream(
            name=HITL_STREAM,
            subjects=[f"{HITL_REQUEST_SUBJECT}.>", f"{HITL_RESPONSE_SUBJECT_PREFIX}.>"],
            retention=RetentionPolicy.LIMITS,
            max_msgs=50_000,
        )

        # Subscribe to all responses
        sub = await self.messaging.subscribe(
            subject=f"{HITL_RESPONSE_SUBJECT_PREFIX}.*",
            callback=self._on_response,
            durable="hitl-response-handler",
            max_deliver=3,
            ack_wait=10.0,
        )
        self._subscriptions.append(sub)
        logger.info("HITLBridge connected")

    async def close(self) -> None:
        """Cancel pending futures and unsubscribe."""
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        self._subscriptions.clear()
        logger.info("HITLBridge closed")

    async def request_approval(
        self,
        request: HITLRequest,
        callback: Callable[[HITLResponse], Awaitable[None]] | None = None,
    ) -> HITLResponse:
        """
        Publish a HITL request and await human response.

        Args:
            request: The approval request payload.
            callback: Optional async callback invoked when response arrives
                      (useful for fire-and-forget patterns).

        Returns:
            HITLResponse with status approved/denied/timeout.
        """
        task_id = request.task_id
        self._pending[task_id] = asyncio.Future()

        await self.messaging.publish(
            f"{HITL_REQUEST_SUBJECT}.{task_id}",
            request.to_bytes(),
            headers={"task-id": task_id, "agent-id": request.agent_id},
        )
        logger.info("HITL request published: %s (%s)", task_id, request.action)

        try:
            response = await asyncio.wait_for(
                self._pending[task_id],
                timeout=request.timeout_seconds,
            )
        except asyncio.TimeoutError:
            response = HITLResponse(
                task_id=task_id,
                status=HITLStatus.TIMEOUT,
                comment="No human response within timeout window.",
            )
            logger.warning("HITL timeout: %s", task_id)
        finally:
            self._pending.pop(task_id, None)

        if callback:
            asyncio.create_task(callback(response))

        return response

    async def respond(self, response: HITLResponse) -> None:
        """
        Publish a human response back to the requesting agent.
        Called by dashboards, Telegram bots, or admin panels.
        """
        await self.messaging.publish(
            f"{HITL_RESPONSE_SUBJECT_PREFIX}.{response.task_id}",
            response.to_bytes(),
            headers={"task-id": response.task_id, "status": response.status.value},
        )
        logger.info("HITL response published: %s -> %s", response.task_id, response.status)

    async def subscribe_requests(
        self,
        callback: Callable[[HITLRequest], Awaitable[None]],
        deliver_group: str | None = None,
    ) -> Any:
        """
        Subscribe to incoming HITL requests (for notifiers / dashboards).
        Uses max_deliver=3 so a failed notifier gets retried.
        """
        async def _wrapper(msg: Any) -> None:
            try:
                req = HITLRequest.from_bytes(msg.data)
                await callback(req)
                await msg.ack()
            except Exception as exc:
                logger.warning("HITL request handler failed: %s", exc)
                await msg.nak()

        sub = await self.messaging.subscribe(
            subject=f"{HITL_REQUEST_SUBJECT}.*",
            callback=_wrapper,
            durable="hitl-request-notifier",
            max_deliver=3,
            ack_wait=30.0,
            deliver_group=deliver_group,
        )
        self._subscriptions.append(sub)
        return sub

    async def _on_response(self, msg: Any) -> None:
        """Internal handler for HITL responses."""
        try:
            response = HITLResponse.from_bytes(msg.data)
            fut = self._pending.get(response.task_id)
            if fut and not fut.done():
                fut.set_result(response)
                logger.info("HITL response received: %s -> %s", response.task_id, response.status)
            await msg.ack()
        except Exception as exc:
            logger.warning("HITL response parse failed: %s", exc)
            await msg.nak()
