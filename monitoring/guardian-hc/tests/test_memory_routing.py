"""Memory-critical routing: undeclared containers must NEVER be restarted.

2026-07-30: sowknow-embed-server-2 was not declared in config.services, so
the memory check fell into an unconditional heal branch and the container
was restarted every patrol — its torch allocator pins the working set at
~100% of the cgroup limit by design, so the restart healed nothing and
took the replica offline mid-search.
"""

import pytest

from guardian_hc.core import GuardianHC, GuardianConfig, ServiceConfig


def _results():
    return {"level": "standard", "checks": [], "healed": 0, "failed": 0, "events": []}


def _critical(container):
    return {"container": container, "mem_pct": 99.9, "severity": "critical", "needs_healing": True}


@pytest.fixture
def guardian() -> GuardianHC:
    return GuardianHC(GuardianConfig(
        app_name="TestApp",
        services=[
            ServiceConfig(name="postgres", container="sowknow-postgres",
                          auto_heal={"restart": False}),
            ServiceConfig(name="redis", container="sowknow-redis",
                          auto_heal={"restart": True}),
        ],
        alerts={},
    ))


async def test_undeclared_container_alerts_and_never_heals(guardian, monkeypatch):
    healed = []

    async def fake_try_heal(*args, **kwargs):
        healed.append(args)

    monkeypatch.setattr(guardian, "_try_heal_container", fake_try_heal)
    results = _results()
    await guardian._handle_memory_critical(_critical("sowknow-embed-server-2"), "standard", results)

    assert healed == []
    assert results["healed"] == 0
    assert results["failed"] == 1
    assert len(results["events"]) == 1
    event = results["events"][0]
    assert event.check_type == "memory_critical"
    assert event.container == "sowknow-embed-server-2"
    assert event.heal_attempted is False
    assert "undeclared" in event.summary


async def test_declared_no_restart_alerts_without_heal(guardian, monkeypatch):
    healed = []

    async def fake_try_heal(*args, **kwargs):
        healed.append(args)

    monkeypatch.setattr(guardian, "_try_heal_container", fake_try_heal)
    results = _results()
    await guardian._handle_memory_critical(_critical("sowknow-postgres"), "standard", results)

    assert healed == []
    assert results["failed"] == 1
    assert len(results["events"]) == 1
    assert results["events"][0].service == "postgres"
    assert "auto-heal disabled" in results["events"][0].summary


async def test_declared_with_restart_routes_to_tracked_heal(guardian, monkeypatch):
    healed = []

    async def fake_try_heal(svc, reason, results):
        healed.append((svc.container, reason))

    monkeypatch.setattr(guardian, "_try_heal_container", fake_try_heal)
    results = _results()
    await guardian._handle_memory_critical(_critical("sowknow-redis"), "standard", results)

    assert healed == [("sowknow-redis", "memory_critical")]
    assert results["events"] == []
    assert results["failed"] == 0
