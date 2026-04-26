"""
Agent registry for SOWKNOW Swarm v2.

Uses NATS JetStream KV (or a lightweight stream fallback) to track active
agents, their capabilities, and health status. Provides discovery and
load-balancing primitives.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from nats.js.api import RetentionPolicy

from app.services.messaging import MessagingClient, get_messaging_client

logger = logging.getLogger(__name__)

AGENT_REGISTRY_BUCKET = "swarm_registry"
AGENT_REGISTRY_STREAM = "SWARM_REGISTRY"
HEARTBEAT_TIMEOUT_SECONDS = 35  # 3 missed heartbeats + margin


class AgentRegistry:
    """
    Central registry for swarm agents backed by NATS.

    Operations:
        - register(agent_info)   → publish to registry
        - discover(capability)   → return matching agents
        - deregister(agent_id)   → remove from registry
        - health_check()         → mark stale agents offline
    """

    def __init__(self, messaging: MessagingClient | None = None) -> None:
        self._messaging = messaging
        self._kv: Any | None = None

    @property
    def messaging(self) -> MessagingClient:
        if self._messaging is None:
            raise RuntimeError("Messaging client not set.")
        return self._messaging

    async def _ensure_kv(self) -> Any:
        """Lazy-init the KV bucket."""
        if self._kv is not None:
            return self._kv
        try:
            self._kv = await self.messaging.js.create_key_value(
                bucket=AGENT_REGISTRY_BUCKET,
                history=5,
                ttl=timedelta(hours=1),
            )
        except Exception:
            # Bucket may already exist
            self._kv = await self.messaging.js.key_value(AGENT_REGISTRY_BUCKET)
        return self._kv

    async def connect(self) -> None:
        """Initialize messaging and ensure registry stream exists."""
        if self._messaging is None:
            self._messaging = await get_messaging_client()

        await self.messaging.ensure_stream(
            name=AGENT_REGISTRY_STREAM,
            subjects=["swarm.registry.>"],
            retention=RetentionPolicy.LIMITS,
            max_msgs=10_000,
        )
        await self._ensure_kv()
        logger.info("AgentRegistry initialized")

    async def register(self, agent_info: dict[str, Any]) -> None:
        """Register or update an agent in the KV store."""
        agent_id = agent_info["agent_id"]
        payload = json.dumps(agent_info).encode()
        kv = await self._ensure_kv()
        await kv.put(agent_id, payload)
        logger.debug("Registered agent: %s", agent_id)

    async def deregister(self, agent_id: str) -> None:
        """Remove an agent from the registry."""
        kv = await self._ensure_kv()
        try:
            await kv.delete(agent_id)
            logger.info("Deregistered agent: %s", agent_id)
        except Exception:
            logger.debug("Agent %s not found in registry", agent_id)

    async def get(self, agent_id: str) -> dict[str, Any] | None:
        """Fetch a single agent's metadata."""
        kv = await self._ensure_kv()
        try:
            entry = await kv.get(agent_id)
            return json.loads(entry.value)
        except Exception:
            return None

    async def discover(
        self,
        capability: str | None = None,
        agent_type: str | None = None,
        healthy_only: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Discover agents matching optional filters.

        Args:
            capability: Filter by capability (e.g., "search", "chat").
            agent_type: Filter by agent type (e.g., "search-agent").
            healthy_only: Exclude agents whose heartbeat is stale.

        Returns:
            List of agent info dicts.
        """
        kv = await self._ensure_kv()
        agents: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        keys = await kv.keys()
        async for key in keys:
            try:
                entry = await kv.get(key)
                info = json.loads(entry.value)
            except Exception:
                continue

            if capability and capability not in info.get("capabilities", []):
                continue
            if agent_type and info.get("agent_type") != agent_type:
                continue
            if healthy_only:
                last_ts = info.get("timestamp")
                if last_ts:
                    try:
                        last = datetime.fromisoformat(last_ts)
                        if (now - last).total_seconds() > HEARTBEAT_TIMEOUT_SECONDS:
                            continue
                    except Exception:
                        continue
            agents.append(info)

        return agents

    async def health_check(self) -> list[str]:
        """
        Scan registry and return IDs of stale agents.
        Callers may decide to deregister them.
        """
        stale: list[str] = []
        kv = await self._ensure_kv()
        now = datetime.now(timezone.utc)

        keys = await kv.keys()
        async for key in keys:
            try:
                entry = await kv.get(key)
                info = json.loads(entry.value)
                last_ts = info.get("timestamp")
                if last_ts:
                    last = datetime.fromisoformat(last_ts)
                    if (now - last).total_seconds() > HEARTBEAT_TIMEOUT_SECONDS:
                        stale.append(info.get("agent_id", key))
            except Exception:
                continue

        if stale:
            logger.warning("Stale agents detected: %s", stale)
        return stale
