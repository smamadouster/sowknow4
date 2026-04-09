from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AgentStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class Agent:
    agent_id: str
    name: str
    role: str
    plugins: list[str] = field(default_factory=list)
    status: AgentStatus = AgentStatus.HEALTHY
    checks_total: int = 0
    checks_failed: int = 0
    _recent_failures: int = field(default=0, repr=False)

    def record_check(self, success: bool) -> None:
        self.checks_total += 1
        if success:
            self._recent_failures = 0
            self.status = AgentStatus.HEALTHY
        else:
            self.checks_failed += 1
            self._recent_failures += 1
            if self._recent_failures >= 3:
                self.status = AgentStatus.DEGRADED

    def to_dict(self) -> dict:
        return {
            "id": self.agent_id,
            "name": self.name,
            "role": self.role,
            "health": self.status.value,
            "checks_total": self.checks_total,
            "checks_failed": self.checks_failed,
        }


class AgentRegistry:
    def __init__(self, config: list[dict]) -> None:
        self._agents: dict[str, Agent] = {}
        for entry in config:
            agent = Agent(
                agent_id=entry["agent_id"],
                name=entry["name"],
                role=entry["role"],
                plugins=entry.get("plugins", []),
            )
            self._agents[agent.agent_id] = agent

    def get(self, agent_id: str) -> Optional[Agent]:
        return self._agents.get(agent_id)

    def get_by_name(self, name: str) -> Optional[Agent]:
        for agent in self._agents.values():
            if agent.name == name:
                return agent
        return None

    def summary(self) -> list[dict]:
        return [agent.to_dict() for agent in self._agents.values()]
