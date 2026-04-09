from __future__ import annotations

import pytest
from guardian_hc.agents import Agent, AgentRegistry, AgentStatus


class TestAgentStatus:
    def test_values(self):
        assert AgentStatus.HEALTHY == "healthy"
        assert AgentStatus.DEGRADED == "degraded"
        assert AgentStatus.UNHEALTHY == "unhealthy"

    def test_is_str_enum(self):
        assert isinstance(AgentStatus.HEALTHY, str)


class TestAgent:
    def test_defaults(self):
        agent = Agent(agent_id="a1", name="Watcher", role="monitor")
        assert agent.plugins == []
        assert agent.status == AgentStatus.HEALTHY
        assert agent.checks_total == 0
        assert agent.checks_failed == 0

    def test_record_check_success_increments_total(self):
        agent = Agent(agent_id="a1", name="Watcher", role="monitor")
        agent.record_check(success=True)
        assert agent.checks_total == 1
        assert agent.checks_failed == 0

    def test_record_check_failure_increments_both(self):
        agent = Agent(agent_id="a1", name="Watcher", role="monitor")
        agent.record_check(success=False)
        assert agent.checks_total == 1
        assert agent.checks_failed == 1

    def test_three_consecutive_failures_set_degraded(self):
        agent = Agent(agent_id="a1", name="Watcher", role="monitor")
        agent.record_check(success=False)
        assert agent.status == AgentStatus.HEALTHY
        agent.record_check(success=False)
        assert agent.status == AgentStatus.HEALTHY
        agent.record_check(success=False)
        assert agent.status == AgentStatus.DEGRADED

    def test_success_after_failures_resets_to_healthy(self):
        agent = Agent(agent_id="a1", name="Watcher", role="monitor")
        agent.record_check(success=False)
        agent.record_check(success=False)
        agent.record_check(success=False)
        assert agent.status == AgentStatus.DEGRADED
        agent.record_check(success=True)
        assert agent.status == AgentStatus.HEALTHY

    def test_success_resets_recent_failures_counter(self):
        agent = Agent(agent_id="a1", name="Watcher", role="monitor")
        agent.record_check(success=False)
        agent.record_check(success=False)
        agent.record_check(success=True)
        # Only 2 failures before reset; third failure alone should not degrade
        agent.record_check(success=False)
        agent.record_check(success=False)
        assert agent.status == AgentStatus.HEALTHY
        agent.record_check(success=False)
        assert agent.status == AgentStatus.DEGRADED

    def test_to_dict_format(self):
        agent = Agent(agent_id="a1", name="Watcher", role="monitor")
        d = agent.to_dict()
        assert d["id"] == "a1"
        assert d["name"] == "Watcher"
        assert d["role"] == "monitor"
        assert d["health"] == "healthy"
        assert d["checks_total"] == 0
        assert d["checks_failed"] == 0

    def test_to_dict_health_reflects_status(self):
        agent = Agent(agent_id="a1", name="Watcher", role="monitor")
        agent.record_check(success=False)
        agent.record_check(success=False)
        agent.record_check(success=False)
        d = agent.to_dict()
        assert d["health"] == "degraded"

    def test_plugins_stored(self):
        agent = Agent(agent_id="a1", name="Watcher", role="monitor", plugins=["cpu", "disk"])
        assert agent.plugins == ["cpu", "disk"]


class TestAgentRegistry:
    CONFIG = [
        {"agent_id": "watcher", "name": "Watcher", "role": "monitor", "plugins": ["cpu"]},
        {"agent_id": "healer", "name": "Healer", "role": "repair"},
        {"agent_id": "debugger", "name": "Debugger", "role": "diagnose"},
    ]

    def test_loads_agents_from_config(self):
        registry = AgentRegistry(self.CONFIG)
        assert registry.get("watcher") is not None
        assert registry.get("healer") is not None
        assert registry.get("debugger") is not None

    def test_get_returns_none_for_unknown(self):
        registry = AgentRegistry(self.CONFIG)
        assert registry.get("nonexistent") is None

    def test_get_by_name(self):
        registry = AgentRegistry(self.CONFIG)
        agent = registry.get_by_name("Watcher")
        assert agent is not None
        assert agent.agent_id == "watcher"

    def test_get_by_name_returns_none_for_unknown(self):
        registry = AgentRegistry(self.CONFIG)
        assert registry.get_by_name("Ghost") is None

    def test_summary_returns_list_of_dicts(self):
        registry = AgentRegistry(self.CONFIG)
        summary = registry.summary()
        assert isinstance(summary, list)
        assert len(summary) == 3

    def test_summary_dict_format(self):
        registry = AgentRegistry(self.CONFIG)
        summary = registry.summary()
        ids = {d["id"] for d in summary}
        assert ids == {"watcher", "healer", "debugger"}
        for d in summary:
            assert "id" in d
            assert "name" in d
            assert "role" in d
            assert "health" in d
            assert "checks_total" in d
            assert "checks_failed" in d

    def test_plugins_loaded_from_config(self):
        registry = AgentRegistry(self.CONFIG)
        agent = registry.get("watcher")
        assert agent.plugins == ["cpu"]

    def test_missing_plugins_defaults_to_empty_list(self):
        registry = AgentRegistry(self.CONFIG)
        agent = registry.get("healer")
        assert agent.plugins == []

    def test_empty_config(self):
        registry = AgentRegistry([])
        assert registry.summary() == []
