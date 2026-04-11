"""InfrastructurePlugin — wraps all v1 checkers and healers in the v2 plugin interface.

Zero behavior change: this plugin delegates every check and heal to the
existing v1 checker/healer implementations.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from guardian_hc.plugin import (
    CheckContext,
    CheckResult,
    GuardianPlugin,
    HealResult,
    Severity,
)
from guardian_hc.checks.containers import ContainerChecker
from guardian_hc.checks.http_health import HttpHealthChecker
from guardian_hc.checks.tcp_health import TcpHealthChecker
from guardian_hc.checks.disk import DiskChecker
from guardian_hc.checks.memory import MemoryChecker
from guardian_hc.checks.ssl_check import SslChecker
from guardian_hc.checks.config_drift import ConfigDriftChecker
from guardian_hc.checks.network_health import NetworkHealthChecker
from guardian_hc.checks.celery_health import CeleryHealthChecker
from guardian_hc.checks.vps_load import VpsLoadChecker
from guardian_hc.checks.ollama_health import OllamaChecker
from guardian_hc.healers.container_healer import ContainerHealer
from guardian_hc.healers.disk_healer import DiskHealer
from guardian_hc.healers.ssl_healer import SslHealer
from guardian_hc.healers.memory_healer import MemoryHealer
from guardian_hc.healers.network_healer import NetworkHealer


# ---------------------------------------------------------------------------
# Patrol level → check category mapping
# ---------------------------------------------------------------------------
#
# oom_events and restart_rate run on EVERY patrol level because a container
# can start crash-looping between two standard patrols (10m) and we want to
# alert within one critical patrol (2m). Both checks are cheap:
#   - oom_events: one `docker events` subprocess call, filtered to event=oom
#   - restart_rate: in-memory sliding window of RestartCount per container

PATROL_CHECKS: dict[str, list[str]] = {
    "critical": ["containers", "api_health", "oom_events", "restart_rate"],
    "standard": ["containers", "api_health", "disk", "memory", "network", "celery", "vps_load", "oom_events", "restart_rate"],
    "deep": ["containers", "api_health", "disk", "memory", "network", "celery", "vps_load", "ssl", "config_drift", "oom_events", "restart_rate"],
}


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class InfrastructurePlugin(GuardianPlugin):
    """Wraps all existing v1 checkers and healers under the v2 plugin interface."""

    name = "infrastructure"
    enabled = True

    def __init__(self, config: dict) -> None:
        self._config = config
        self._services = config.get("services", [])

        # Instantiate checkers
        self._container_checker = ContainerChecker()
        self._disk_checker = DiskChecker(config.get("disk"))
        self._memory_checker = MemoryChecker()
        self._ssl_checker = SslChecker(config.get("ssl"))
        self._config_drift_checker = ConfigDriftChecker(config)  # receives full config dict
        self._network_checker = NetworkHealthChecker(config.get("network"))
        self._celery_checker = CeleryHealthChecker(config.get("celery"))
        self._vps_checker = VpsLoadChecker(config.get("vps_load"))
        self._ollama_checker = OllamaChecker(config.get("ollama"))

        # Instantiate healers
        self._container_healer = ContainerHealer()
        self._disk_healer = DiskHealer(config.get("disk"))
        self._memory_healer = MemoryHealer()
        self._ssl_healer = SslHealer(config.get("ssl"))
        self._network_healer = NetworkHealer({"compose_file": config.get("compose_file", "./docker-compose.yml")})

        # OOM + restart-rate sliding-window state (in-memory, wiped on Guardian restart)
        #   _oom_events: container_name -> list[datetime] of OOM events in the window
        #   _restart_history: container_name -> list[(datetime, RestartCount)] samples
        #   _last_oom_poll: upper bound from the previous docker-events poll; used as
        #                   the `--since` of the next call to avoid double-counting
        self._oom_events: dict[str, list[datetime]] = {}
        self._restart_history: dict[str, list[tuple[datetime, int]]] = {}
        self._last_oom_poll: datetime | None = None
        # Alert thresholds (keep conservative; adjust via config if needed)
        self._oom_window_minutes = 15
        self._oom_alert_threshold = 2  # N OOMs in window → alert
        self._restart_window_minutes = 10
        self._restart_alert_threshold = 3  # N restarts in window → alert

    # ------------------------------------------------------------------
    # check()
    # ------------------------------------------------------------------

    async def check(self, context: CheckContext) -> list[CheckResult]:
        level = context.patrol_level
        active = set(PATROL_CHECKS.get(level, PATROL_CHECKS["standard"]))
        results: list[CheckResult] = []

        # --- containers + api_health ---
        if "containers" in active or "api_health" in active:
            for svc in self._services:
                if "containers" in active:
                    results.extend(await self._check_container(svc))
                if "api_health" in active:
                    results.extend(await self._check_api_health(svc))

        # --- disk ---
        if "disk" in active:
            results.extend(await self._check_disk())

        # --- memory ---
        if "memory" in active:
            results.extend(await self._check_memory())

        # --- network ---
        if "network" in active:
            results.extend(await self._check_network())

        # --- celery ---
        if "celery" in active:
            results.extend(await self._check_celery())

        # --- vps_load ---
        if "vps_load" in active:
            results.extend(await self._check_vps_load())

        # --- ssl ---
        if "ssl" in active:
            results.extend(await self._check_ssl())

        # --- config_drift ---
        if "config_drift" in active:
            results.extend(await self._check_config_drift())

        # --- oom_events ---
        if "oom_events" in active:
            results.extend(await self._check_oom_events())

        # --- restart_rate ---
        if "restart_rate" in active:
            results.extend(await self._check_restart_rate())

        return results

    # ------------------------------------------------------------------
    # Individual check helpers
    # ------------------------------------------------------------------

    async def _check_container(self, svc) -> list[CheckResult]:
        raw = await self._container_checker.check(svc.container)
        status = raw.get("status", "unknown")
        ok = status == "running"
        return [
            CheckResult(
                plugin=self.name,
                module="Infrastructure",
                check_name=f"container_{svc.name}",
                status="pass" if ok else "fail",
                severity=Severity.INFO if ok else Severity.CRITICAL,
                summary=f"{svc.container} is {status}",
                details=raw,
                needs_healing=not ok,
                heal_hint=f"restart:{svc.container}" if not ok else None,
            )
        ]

    async def _check_api_health(self, svc) -> list[CheckResult]:
        results: list[CheckResult] = []
        hc = svc.health_check or {}

        # HTTP check
        if "http" in hc:
            http_cfg = hc["http"]
            url = http_cfg.get("url", "")
            timeout = http_cfg.get("timeout", 10)
            raw = await HttpHealthChecker.check(url, timeout)
            ok = raw.get("healthy", False)
            results.append(
                CheckResult(
                    plugin=self.name,
                    module="Infrastructure",
                    check_name=f"http_{svc.name}",
                    status="pass" if ok else "fail",
                    severity=Severity.INFO if ok else Severity.HIGH,
                    summary=f"HTTP {url}: {'OK' if ok else 'FAILED'} ({raw.get('status_code', 'N/A')})",
                    details=raw,
                    needs_healing=not ok,
                    heal_hint=f"restart:{svc.container}" if not ok else None,
                )
            )

        # TCP check
        if "tcp" in hc:
            tcp_cfg = hc["tcp"]
            host = tcp_cfg.get("host", "")
            port = tcp_cfg.get("port", 0)
            timeout = tcp_cfg.get("timeout", 5)
            raw = await TcpHealthChecker.check(host, port, timeout)
            ok = raw.get("healthy", False)
            results.append(
                CheckResult(
                    plugin=self.name,
                    module="Infrastructure",
                    check_name=f"tcp_{svc.name}",
                    status="pass" if ok else "fail",
                    severity=Severity.INFO if ok else Severity.HIGH,
                    summary=f"TCP {host}:{port}: {'OK' if ok else 'FAILED'}",
                    details=raw,
                    needs_healing=not ok,
                    heal_hint=f"restart:{svc.container}" if not ok else None,
                )
            )

        return results

    async def _check_disk(self) -> list[CheckResult]:
        raw = await self._disk_checker.check()
        needs = raw.get("needs_healing", False)
        severity_str = raw.get("severity", "ok")
        sev = Severity.CRITICAL if severity_str == "critical" else Severity.WARNING if severity_str == "warning" else Severity.INFO
        return [
            CheckResult(
                plugin=self.name,
                module="Infrastructure",
                check_name="disk_usage",
                status="fail" if needs else "pass",
                severity=sev,
                summary=f"Disk usage: {raw.get('usage_pct', '?')}% ({severity_str})",
                details=raw,
                needs_healing=needs,
                heal_hint="disk_cleanup" if needs else None,
            )
        ]

    async def _check_memory(self) -> list[CheckResult]:
        raw_list = await self._memory_checker.check(self._services)
        results: list[CheckResult] = []
        for item in raw_list:
            container = item.get("container", "unknown")
            mem_pct = item.get("mem_pct", 0.0)
            needs = item.get("needs_healing", False)
            results.append(
                CheckResult(
                    plugin=self.name,
                    module="Infrastructure",
                    check_name=f"memory_{container}",
                    status="fail" if needs else "pass",
                    severity=Severity.WARNING if needs else Severity.INFO,
                    summary=f"{container} memory: {mem_pct}%",
                    details=item,
                    needs_healing=needs,
                    heal_hint=f"restart:{container}" if needs else None,
                )
            )
        return results

    async def _check_network(self) -> list[CheckResult]:
        raw = await self._network_checker.check()
        needs = raw.get("needs_healing", False)
        stale = raw.get("stale_bridges", [])
        return [
            CheckResult(
                plugin=self.name,
                module="Infrastructure",
                check_name="network_health",
                status="fail" if needs else "pass",
                severity=Severity.CRITICAL if needs else Severity.INFO,
                summary=f"Network: {'stale bridges detected' if stale else 'OK'}",
                details=raw,
                needs_healing=needs,
                heal_hint="network_heal" if needs else None,
            )
        ]

    async def _check_celery(self) -> list[CheckResult]:
        raw_list = await self._celery_checker.check()
        results: list[CheckResult] = []
        for item in raw_list:
            check_name = item.get("check", "celery_unknown")
            container = item.get("container", "")
            needs = item.get("needs_healing", False)
            results.append(
                CheckResult(
                    plugin=self.name,
                    module="Infrastructure",
                    check_name=f"celery_{check_name}",
                    status="fail" if needs else "pass",
                    severity=Severity.WARNING if needs else Severity.INFO,
                    summary=f"Celery {check_name}: {'needs attention' if needs else 'OK'}",
                    details=item,
                    needs_healing=needs,
                    heal_hint=f"restart:{container}" if needs and container else None,
                )
            )
        return results

    async def _check_vps_load(self) -> list[CheckResult]:
        raw_list = await self._vps_checker.check()
        results: list[CheckResult] = []
        for item in raw_list:
            load_type = item.get("type", "vps_metric")
            needs = item.get("needs_healing", False)
            results.append(
                CheckResult(
                    plugin=self.name,
                    module="Infrastructure",
                    check_name=f"vps_{load_type}",
                    status="fail" if needs else "pass",
                    severity=Severity.WARNING if needs else Severity.INFO,
                    summary=f"VPS {load_type}: {'overloaded' if needs else 'OK'}",
                    details=item,
                    needs_healing=needs,
                    heal_hint=None,
                )
            )
        return results

    async def _check_ssl(self) -> list[CheckResult]:
        raw_list = await self._ssl_checker.check()
        results: list[CheckResult] = []
        for item in raw_list:
            domain = item.get("domain", "unknown")
            days_left = item.get("days_left", 999)
            needs = item.get("needs_healing", False)
            results.append(
                CheckResult(
                    plugin=self.name,
                    module="Infrastructure",
                    check_name=f"ssl_{domain}",
                    status="fail" if needs else "pass",
                    severity=Severity.CRITICAL if needs else Severity.INFO,
                    summary=f"SSL {domain}: {days_left} days remaining",
                    details=item,
                    needs_healing=needs,
                    heal_hint=f"ssl_renew:{domain}" if needs else None,
                )
            )
        return results

    async def _check_config_drift(self) -> list[CheckResult]:
        raw = await self._config_drift_checker.check()
        count = raw.get("count", 0)
        needs = count > 0
        return [
            CheckResult(
                plugin=self.name,
                module="Infrastructure",
                check_name="config_drift",
                status="fail" if needs else "pass",
                severity=Severity.WARNING if needs else Severity.INFO,
                summary=f"Config drift: {count} item(s) drifted" if needs else "Config drift: none",
                details=raw,
                needs_healing=needs,
                heal_hint=None,
            )
        ]

    # ------------------------------------------------------------------
    # OOM + restart-rate probes (added 2026-04-11)
    # ------------------------------------------------------------------
    #
    # Why these exist:
    #   On 2026-04-10/11 celery-heavy was in an OOM crash-loop
    #   (RestartCount 0 → 34 in 15h) and Guardian noticed nothing, because:
    #     1. docker inspect reports OOMKilled=false when init: true / tini
    #        catches the child SIGKILL and exits 0 on its behalf.
    #     2. Guardian had no probe that looked at `docker events` for OOM
    #        signals, and no probe that sampled RestartCount over time.
    #   These two checks close the gap. They are cheap (one subprocess and
    #   one docker-API call per patrol) and state is held in memory.

    async def _check_oom_events(self) -> list[CheckResult]:
        """Detect containers that have been OOM-killed by the kernel cgroup.

        Uses `docker events --filter event=oom` to gather historical OOM
        events since the last poll. We record timestamps per container in a
        sliding window and alert when a container has been killed
        `_oom_alert_threshold` times within `_oom_window_minutes`.
        """
        now = datetime.now(timezone.utc)
        # First call: look back over the full window so we don't miss fresh OOMs.
        since = self._last_oom_poll or (now - timedelta(minutes=self._oom_window_minutes))

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "events",
                "--since", since.strftime("%Y-%m-%dT%H:%M:%S"),
                "--until", now.strftime("%Y-%m-%dT%H:%M:%S"),
                "--filter", "event=oom",
                "--format", "{{.Time}}|{{.Actor.Attributes.name}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        except (asyncio.TimeoutError, FileNotFoundError, OSError) as exc:
            return [CheckResult(
                plugin=self.name,
                module="Infrastructure",
                check_name="oom_events",
                status="fail",
                severity=Severity.WARNING,
                summary=f"OOM probe error: {str(exc)[:100]}",
                needs_healing=False,
            )]

        self._last_oom_poll = now

        # Parse "<unix-ts>|<container_name>" lines
        for line in stdout.decode(errors="replace").strip().splitlines():
            if "|" not in line:
                continue
            ts_str, _, name = line.partition("|")
            try:
                ts = datetime.fromtimestamp(int(ts_str), tz=timezone.utc)
            except ValueError:
                continue
            if not name:
                continue
            self._oom_events.setdefault(name, []).append(ts)

        # Prune outside the sliding window
        cutoff = now - timedelta(minutes=self._oom_window_minutes)
        results: list[CheckResult] = []
        for name, events in list(self._oom_events.items()):
            fresh = [t for t in events if t >= cutoff]
            if fresh:
                self._oom_events[name] = fresh
            else:
                del self._oom_events[name]
                continue
            if len(fresh) >= self._oom_alert_threshold:
                results.append(CheckResult(
                    plugin=self.name,
                    module="Infrastructure",
                    check_name=f"oom_{name}",
                    status="fail",
                    severity=Severity.CRITICAL,
                    summary=(
                        f"{name} OOM-killed {len(fresh)}x in the last "
                        f"{self._oom_window_minutes} min — likely memory leak "
                        f"or cgroup limit too low. Restart won't fix it."
                    ),
                    details={
                        "events": [t.isoformat() for t in fresh],
                        "window_minutes": self._oom_window_minutes,
                    },
                    # Deliberately not healable: a restart would just OOM again.
                    needs_healing=False,
                    heal_hint=None,
                ))

        if not results:
            results.append(CheckResult(
                plugin=self.name,
                module="Infrastructure",
                check_name="oom_events",
                status="pass",
                severity=Severity.INFO,
                summary="No container OOM-kills in the last "
                        f"{self._oom_window_minutes} min",
            ))
        return results

    async def _check_restart_rate(self) -> list[CheckResult]:
        """Detect containers that are restarting abnormally fast.

        Samples every sowknow4-* container's RestartCount via the Docker
        Engine API, stores the sample in a per-container sliding window, and
        alerts when the count has grown by `_restart_alert_threshold` or more
        within `_restart_window_minutes`.

        This is the catch-all net — crash-loop, OOM, healthcheck flap,
        segfault, whatever the cause, a container restarting 3+ times in
        10 min is abnormal and the user wants to know.
        """
        now = datetime.now(timezone.utc)
        results: list[CheckResult] = []

        try:
            transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
            async with httpx.AsyncClient(
                transport=transport, base_url="http://docker", timeout=5
            ) as client:
                resp = await client.get("/containers/json?all=true")
                containers = resp.json()
                for c in containers:
                    names = c.get("Names", [])
                    name = names[0].lstrip("/") if names else ""
                    # Scope to sowknow4-* only — Guardian should not babysit
                    # other projects sharing this host (ghostshell, etc.)
                    if not name.startswith("sowknow4-"):
                        continue

                    insp = await client.get(f"/containers/{c['Id']}/json")
                    restart_count = insp.json().get("RestartCount", 0)

                    history = self._restart_history.setdefault(name, [])
                    history.append((now, restart_count))
                    # Prune older than window
                    cutoff = now - timedelta(minutes=self._restart_window_minutes)
                    history[:] = [(t, rc) for (t, rc) in history if t >= cutoff]

                    if len(history) < 2:
                        continue

                    oldest_rc = history[0][1]
                    delta = restart_count - oldest_rc
                    if delta >= self._restart_alert_threshold:
                        results.append(CheckResult(
                            plugin=self.name,
                            module="Infrastructure",
                            check_name=f"restart_rate_{name}",
                            status="fail",
                            severity=Severity.CRITICAL,
                            summary=(
                                f"{name} restarted {delta}x in the last "
                                f"{self._restart_window_minutes} min "
                                f"(RestartCount {oldest_rc} → {restart_count}). "
                                f"Check `docker logs {name}` and dmesg for OOM."
                            ),
                            details={
                                "delta": delta,
                                "window_minutes": self._restart_window_minutes,
                                "current_restart_count": restart_count,
                            },
                            # Deliberately not healable: auto-restart during a
                            # crash-loop just accelerates the loop.
                            needs_healing=False,
                            heal_hint=None,
                        ))
        except Exception as exc:
            return [CheckResult(
                plugin=self.name,
                module="Infrastructure",
                check_name="restart_rate",
                status="fail",
                severity=Severity.WARNING,
                summary=f"Restart-rate probe error: {str(exc)[:100]}",
                needs_healing=False,
            )]

        if not results:
            results.append(CheckResult(
                plugin=self.name,
                module="Infrastructure",
                check_name="restart_rate",
                status="pass",
                severity=Severity.INFO,
                summary=f"No crash-looping containers "
                        f"(window: {self._restart_window_minutes} min, "
                        f"threshold: {self._restart_alert_threshold})",
            ))
        return results

    # ------------------------------------------------------------------
    # heal()
    # ------------------------------------------------------------------

    async def heal(self, result: CheckResult) -> HealResult | None:
        hint = result.heal_hint
        if not hint:
            return None

        # restart:<container_name>
        if hint.startswith("restart:"):
            container_name = hint[len("restart:"):]
            raw = await self._container_healer.heal(container_name)
            return HealResult(
                plugin=self.name,
                target=container_name,
                action="container_restart",
                success=raw.get("healed", False),
                details=raw.get("action", raw.get("error", "")),
            )

        # disk_cleanup
        if hint == "disk_cleanup":
            raw = await self._disk_healer.heal()
            return HealResult(
                plugin=self.name,
                target="disk",
                action="disk_cleanup",
                success=raw.get("healed", False),
                details=", ".join(raw.get("actions", [])) or raw.get("error", ""),
            )

        # network_heal
        if hint == "network_heal":
            raw = await self._network_healer.heal()
            return HealResult(
                plugin=self.name,
                target="network",
                action="network_heal",
                success=raw.get("healed", False),
                details=", ".join(raw.get("actions", [])) or raw.get("error", ""),
            )

        # ssl_renew:<domain>
        if hint.startswith("ssl_renew:"):
            domain = hint[len("ssl_renew:"):]
            raw = await self._ssl_healer.heal(domain)
            return HealResult(
                plugin=self.name,
                target=domain,
                action="ssl_renew",
                success=raw.get("healed", False),
                details=raw.get("action", raw.get("error", "")),
            )

        # Unknown hint — no-op
        return None
