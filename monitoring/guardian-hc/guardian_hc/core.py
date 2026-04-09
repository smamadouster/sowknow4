"""
Guardian HC Core -- Configuration-driven health check and self-healing.
"""

import yaml
import asyncio
import structlog
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

from guardian_hc.checks.containers import ContainerChecker
from guardian_hc.checks.http_health import HttpHealthChecker
from guardian_hc.checks.tcp_health import TcpHealthChecker
from guardian_hc.checks.disk import DiskChecker
from guardian_hc.checks.memory import MemoryChecker
from guardian_hc.checks.ssl_check import SslChecker
from guardian_hc.checks.config_drift import ConfigDriftChecker
from guardian_hc.checks.ollama_health import OllamaChecker
from guardian_hc.checks.vps_load import VpsLoadChecker
from guardian_hc.checks.network_health import NetworkHealthChecker
from guardian_hc.healers.container_healer import ContainerHealer
from guardian_hc.healers.disk_healer import DiskHealer
from guardian_hc.healers.ssl_healer import SslHealer
from guardian_hc.healers.memory_healer import MemoryHealer
from guardian_hc.healers.network_healer import NetworkHealer
from guardian_hc.patrol.runner import PatrolRunner
from guardian_hc.alerts import AlertManager

logger = structlog.get_logger()

# Restart cooldown: max attempts before suppression, then exponential backoff
RESTART_MAX_ATTEMPTS = 5
RESTART_COOLDOWN_BASE = 300  # 5 minutes initial cooldown
RESTART_COOLDOWN_MAX = 3600  # 1 hour max cooldown


@dataclass
class RestartTracker:
    """Tracks restart attempts per container to prevent flapping."""
    attempts: int = 0
    last_attempt: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=timezone.utc))
    suppressed_until: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=timezone.utc))

    def can_restart(self) -> tuple[bool, str]:
        now = datetime.now(timezone.utc)
        if now < self.suppressed_until:
            remaining = int((self.suppressed_until - now).total_seconds())
            return False, (
                f"Restart suppressed: {self.attempts} attempts in "
                f"{int((now - self.last_attempt).total_seconds()) + remaining}s. "
                f"Next retry in {remaining}s. Container likely has a CODE BUG -- restarting won't fix it."
            )
        return True, ""

    def record_attempt(self, success: bool):
        now = datetime.now(timezone.utc)
        self.last_attempt = now
        if success:
            self.attempts = 0
            self.suppressed_until = datetime.min.replace(tzinfo=timezone.utc)
        else:
            self.attempts += 1
            if self.attempts >= RESTART_MAX_ATTEMPTS:
                cooldown = min(
                    RESTART_COOLDOWN_BASE * (2 ** (self.attempts - RESTART_MAX_ATTEMPTS)),
                    RESTART_COOLDOWN_MAX,
                )
                self.suppressed_until = now + timedelta(seconds=cooldown)


@dataclass
class ServiceConfig:
    name: str
    container: str
    health_check: dict = field(default_factory=dict)
    auto_heal: dict = field(default_factory=dict)


@dataclass
class GuardianConfig:
    app_name: str = "Application"
    compose_file: str = "./docker-compose.yml"
    services: list[ServiceConfig] = field(default_factory=list)
    alerts: dict = field(default_factory=dict)
    patrols: dict = field(default_factory=dict)
    disk: dict = field(default_factory=dict)
    ssl: dict = field(default_factory=dict)
    ollama: dict = field(default_factory=dict)
    vps_load: dict = field(default_factory=dict)
    network: dict = field(default_factory=dict)
    dashboard_port: int = 9090


class GuardianHC:
    """Main Guardian HC controller."""

    def __init__(self, config: GuardianConfig):
        self.config = config
        self.alert_manager = AlertManager(config.alerts)
        self.container_checker = ContainerChecker()
        self.container_healer = ContainerHealer()
        self.disk_checker = DiskChecker(config.disk)
        self.disk_healer = DiskHealer(config.disk)
        self.memory_checker = MemoryChecker()
        self.memory_healer = MemoryHealer()
        self.ssl_checker = SslChecker(config.ssl)
        self.ssl_healer = SslHealer(config.ssl)
        self.drift_checker = ConfigDriftChecker(config)
        self.ollama_checker = OllamaChecker(config.ollama)
        self.vps_load_checker = VpsLoadChecker(config.vps_load)
        self.network_checker = NetworkHealthChecker(config.network)
        self.network_healer = NetworkHealer({"compose_file": config.compose_file})
        self.patrol_runner = PatrolRunner(self)
        self._shutdown = False
        self._history: list[dict] = []
        self._restart_trackers: dict[str, RestartTracker] = {}

    @classmethod
    def from_config(cls, config_path: str) -> "GuardianHC":
        """Load from guardian-hc.yml config file."""
        with open(config_path) as f:
            raw = yaml.safe_load(f)

        services = []
        for svc in raw.get("services", []):
            services.append(ServiceConfig(
                name=svc.get("name", ""),
                container=svc.get("container", ""),
                health_check=svc.get("health_check", {}),
                auto_heal=svc.get("auto_heal", {}),
            ))

        config = GuardianConfig(
            app_name=raw.get("app", {}).get("name", "Application"),
            compose_file=raw.get("app", {}).get("compose_file", "./docker-compose.yml"),
            services=services,
            alerts=raw.get("alerts", {}),
            patrols=raw.get("patrols", {}),
            disk=raw.get("disk", {}),
            ssl=raw.get("ssl", {}),
            ollama=raw.get("ollama", {}),
            vps_load=raw.get("vps_load", {}),
            network=raw.get("network", {}),
            dashboard_port=raw.get("dashboard", {}).get("port", 9090),
        )
        return cls(config)

    def log_action(self, action: dict):
        action["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._history.append(action)
        if len(self._history) > 500:
            self._history.pop(0)

    def get_history(self, limit: int = 50) -> list[dict]:
        return self._history[-limit:]

    def _get_tracker(self, container: str) -> RestartTracker:
        if container not in self._restart_trackers:
            self._restart_trackers[container] = RestartTracker()
        return self._restart_trackers[container]

    async def _try_heal_container(self, svc: ServiceConfig, reason: str, results: dict) -> bool:
        """Attempt container restart with cooldown. Returns True if healed."""
        tracker = self._get_tracker(svc.container)
        can, msg = tracker.can_restart()
        if not can:
            results["failed"] += 1
            await self.alert_manager.send(
                f"*{svc.name}* is running but failing health checks | RESTART SUPPRESSED: {msg}")
            self.log_action({"target": svc.name, "action": "restart_suppressed", "reason": msg})
            return False

        heal = await self.container_healer.heal(
            svc.container,
            rebuild=svc.auto_heal.get("rebuild_on_failure", False),
            compose_file=self.config.compose_file,
        )
        tracker.record_attempt(heal.get("healed", False))
        self.log_action({"target": svc.name, "action": f"restart_{reason}", **heal})
        if heal.get("healed"):
            results["healed"] += 1
            return True
        else:
            results["failed"] += 1
            await self.alert_manager.send(
                f"Container *{svc.name}* failed {reason} and auto-restart failed.\n{heal.get('error', '')}")
            return False

    async def run_check_cycle(self, level: str = "standard") -> dict:
        """Run a complete check + heal cycle."""
        results = {"level": level, "timestamp": datetime.now(timezone.utc).isoformat(),
                   "checks": [], "healed": 0, "failed": 0}

        for svc in self.config.services:
            status = await self.container_checker.check(svc.container)
            results["checks"].append({"service": svc.name, "type": "container", **status})

            if status["status"] != "running" and svc.auto_heal.get("restart", False):
                await self._try_heal_container(svc, "container_down", results)

            hc = svc.health_check
            if hc.get("type") == "http" and status["status"] == "running":
                http_status = await HttpHealthChecker.check(hc.get("url", ""), timeout=hc.get("timeout", 10))
                results["checks"].append({"service": svc.name, "type": "http", **http_status})
                if not http_status.get("healthy") and svc.auto_heal.get("restart", False):
                    await self._try_heal_container(svc, "http_unhealthy", results)

            elif hc.get("type") == "tcp" and status["status"] == "running":
                tcp_status = await TcpHealthChecker.check(hc.get("host", "localhost"), hc.get("port", 0))
                results["checks"].append({"service": svc.name, "type": "tcp", **tcp_status})
                if not tcp_status.get("healthy") and svc.auto_heal.get("restart", False):
                    await self._try_heal_container(svc, "tcp_unhealthy", results)

        if level in ("standard", "deep"):
            disk_status = await self.disk_checker.check()
            results["checks"].append({"type": "disk", **disk_status})
            if disk_status.get("needs_healing"):
                heal = await self.disk_healer.heal()
                self.log_action({"target": "disk", **heal})
                if heal.get("healed"):
                    results["healed"] += 1

            mem_status = await self.memory_checker.check(self.config.services)
            for ms in mem_status:
                results["checks"].append({"type": "memory", **ms})
                if ms.get("needs_healing"):
                    heal = await self.memory_healer.heal(ms["container"])
                    self.log_action({"target": ms["container"], "action": "memory_restart", **heal})
                    if heal.get("healed"):
                        results["healed"] += 1

            # Network health -- CRITICAL: detect stale nftables + broken connectivity
            net_status = await self.network_checker.check()
            results["checks"].append({"type": "network_health", **net_status})
            if net_status.get("needs_healing"):
                stale = net_status.get("stale_bridges", [])
                probes_failed = [p for p in net_status.get("probe_results", []) if not p.get("ok")]
                stale_summary = ", ".join(s.get("bridge", "?") for s in stale) if stale else "none"
                probe_summary = ", ".join(p.get("to", "?") for p in probes_failed) if probes_failed else "none"

                await self.alert_manager.send(
                    f"CRITICAL: Docker network broken!\n"
                    f"Stale nftables bridges: {stale_summary}\n"
                    f"Failed probes: {probe_summary}\n"
                    f"Auto-healing: flushing nftables + restarting Docker...")

                heal = await self.network_healer.heal(stale_bridges=stale)
                self.log_action({"target": "network", "action": "nftables_flush", **heal})
                if heal.get("healed"):
                    results["healed"] += 1
                    await self.alert_manager.send(
                        f"Network healed: {', '.join(heal.get('actions', []))}")
                else:
                    results["failed"] += 1
                    await self.alert_manager.send(
                        f"Network healing FAILED: {heal.get('error', 'unknown')}\n"
                        f"Manual intervention required!")

            ollama_status = await self.ollama_checker.check()
            results["checks"].append({"type": "ollama_health", **ollama_status})
            if ollama_status.get("needs_healing"):
                await self.alert_manager.send(
                    f"Ollama is *unavailable* -- confidential doc routing may fail.\n"
                    f"{ollama_status.get('error', '')}")
                results["failed"] += 1

            vps_load_status = await self.vps_load_checker.check()
            for vls in vps_load_status:
                results["checks"].append({"type": "vps_load", **vls})
                if vls.get("needs_healing"):
                    detail = ""
                    if vls.get("type") == "load_average":
                        detail = f"Load5={vls.get('load5')}"
                    elif vls.get("type") == "steal_time":
                        detail = f"Steal={vls.get('steal_pct')}%"
                    await self.alert_manager.send(
                        f"VPS load critical: {detail} -- {vls['type']} threshold exceeded.")
                    results["failed"] += 1

        if level == "deep":
            ssl_status = await self.ssl_checker.check()
            for ss in ssl_status:
                results["checks"].append({"type": "ssl", **ss})
                if ss.get("needs_healing"):
                    heal = await self.ssl_healer.heal(ss["domain"])
                    self.log_action({"target": f"ssl:{ss['domain']}", **heal})
                    if heal.get("healed"):
                        results["healed"] += 1

            drift = await self.drift_checker.check()
            results["checks"].append({"type": "config_drift", **drift})

        return results

    async def run(self):
        """Main loop -- run patrols, dashboard, and daily report on schedule."""
        logger.info("guardian_hc.started", app=self.config.app_name)
        print(f"Guardian HC v{__import__('guardian_hc').__version__} -- Protecting: {self.config.app_name}")

        tasks = []
        tasks.append(asyncio.create_task(self.patrol_runner.run()))

        try:
            from guardian_hc.dashboard import DashboardServer
            dashboard = DashboardServer(self, port=self.config.dashboard_port)
            tasks.append(asyncio.create_task(dashboard.start()))
            print(f"Dashboard: http://localhost:{self.config.dashboard_port}")
        except ImportError:
            logger.info("dashboard.aiohttp_not_installed", note="pip install aiohttp for dashboard")

        tasks.append(asyncio.create_task(self._daily_report_loop()))
        await asyncio.gather(*tasks)

    async def _daily_report_loop(self):
        """Send daily report at 6:00 AM UTC."""
        from guardian_hc.daily_report import send_report
        while True:
            now = datetime.now(timezone.utc)
            target = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            wait = (target - now).total_seconds()
            logger.info("daily_report.scheduled", next_run=target.isoformat(), wait_hours=round(wait / 3600, 1))
            await asyncio.sleep(wait)
            try:
                result = await send_report(self, alert_manager=self.alert_manager)
                logger.info("daily_report.sent", result=result)
            except Exception as e:
                logger.error("daily_report.failed", error=str(e)[:200])
