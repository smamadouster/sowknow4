"""ProbesPlugin — deep application probes for Guardian (Watcher role).

Runs targeted probes against live services: JWT auth, Redis, Postgres,
Celery, pipeline stages, Nginx, and full auth-flow login.
"""
from __future__ import annotations

import subprocess
from typing import Any

import httpx
import structlog

from guardian_hc.healers.container_healer import ContainerHealer
from guardian_hc.plugin import (
    CheckContext,
    CheckResult,
    GuardianPlugin,
    HealResult,
    Severity,
)

logger = structlog.get_logger()


class ProbesPlugin(GuardianPlugin):
    """Deep application probe plugin."""

    name = "probes"
    enabled = True

    PROBE_LEVELS: dict[str, list[str]] = {
        "critical": ["jwt", "redis_deep", "celery_completion"],
        "standard": [
            "jwt", "redis_deep", "celery_completion",
            "postgres_deep", "deep_health", "pipeline", "nginx",
        ],
        "deep": [
            "jwt", "redis_deep", "celery_completion",
            "postgres_deep", "deep_health", "pipeline", "nginx", "auth_flow",
        ],
    }

    def __init__(self, config: dict) -> None:
        self._backend_url: str = config.get("backend_url", "http://localhost:8000")
        self._redis_host: str = config.get("redis_host", "localhost")
        self._redis_port: int = int(config.get("redis_port", 6379))
        self._redis_password: str = config.get("redis_password", "")
        self._nginx_url: str = config.get("nginx_url", "http://localhost:80")
        # service_account may be a dict {username, password} or a bare string
        # (name only, no credentials). Normalise to dict to keep usage consistent.
        sa = config.get("service_account", {})
        self._service_account: dict = sa if isinstance(sa, dict) else {}

    # ------------------------------------------------------------------
    # Public plugin interface
    # ------------------------------------------------------------------

    async def check(self, context: CheckContext) -> list[CheckResult]:
        level = context.patrol_level
        probes = self.PROBE_LEVELS.get(level, self.PROBE_LEVELS["standard"])

        _dispatch: dict[str, Any] = {
            "jwt": self._check_jwt,
            "redis_deep": self._check_redis_deep,
            "celery_completion": self._check_celery_completion,
            "postgres_deep": self._check_postgres_deep,
            "deep_health": self._check_deep_health,
            "pipeline": self._check_pipeline,
            "nginx": self._check_nginx,
            "auth_flow": self._check_auth_flow,
        }

        results: list[CheckResult] = []
        for probe in probes:
            fn = _dispatch.get(probe)
            if fn is None:
                continue
            try:
                result = await fn(context)
                results.append(result)
            except Exception as exc:
                logger.error("probe.exception", probe=probe, error=str(exc)[:200])
                results.append(CheckResult(
                    plugin=self.name,
                    module="Infrastructure",
                    check_name=probe,
                    status="fail",
                    severity=Severity.CRITICAL,
                    summary=f"Probe '{probe}' raised unexpected exception: {exc!s:.200}",
                    needs_healing=False,
                ))
        return results

    async def heal(self, result: CheckResult) -> HealResult | None:
        hint = result.heal_hint
        if not hint:
            return None

        if hint == "restart_backend":
            healer = ContainerHealer()
            out = await healer.heal("sowknow4-backend")
            return HealResult(
                plugin=self.name,
                target="sowknow4-backend",
                action="restart_backend",
                success=out.get("healed", False),
                details=str(out),
            )

        if hint == "redis_memory_purge":
            return await self._heal_redis_memory_purge()

        if hint and hint.startswith("restart:"):
            container = hint.split(":", 1)[1]
            healer = ContainerHealer()
            out = await healer.heal(container)
            return HealResult(
                plugin=self.name,
                target=container,
                action="restart_container",
                success=out.get("healed", False),
                details=str(out),
            )

        if hint == "kill_pg_idle":
            return await self._heal_kill_pg_idle()

        if hint == "requeue_stuck_docs":
            return await self._heal_requeue_stuck_docs()

        return None

    # ------------------------------------------------------------------
    # Individual probes
    # ------------------------------------------------------------------

    async def _check_jwt(self, ctx: CheckContext) -> CheckResult:
        """Verify JWT authentication service responds correctly."""
        url = f"{self._backend_url}/api/v1/health/auth-check"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
            if resp.status_code == 200:
                return CheckResult(
                    plugin=self.name,
                    module="Authentication Service",
                    check_name="jwt",
                    status="pass",
                    severity=Severity.INFO,
                    summary="JWT auth endpoint healthy",
                    details={"status_code": resp.status_code},
                )
            return CheckResult(
                plugin=self.name,
                module="Authentication Service",
                check_name="jwt",
                status="fail",
                severity=Severity.CRITICAL,
                summary=f"JWT auth endpoint returned HTTP {resp.status_code}",
                details={"status_code": resp.status_code},
                needs_healing=True,
                heal_hint="restart_backend",
            )
        except Exception as exc:
            return CheckResult(
                plugin=self.name,
                module="Authentication Service",
                check_name="jwt",
                status="fail",
                severity=Severity.CRITICAL,
                summary=f"JWT auth endpoint unreachable: {exc!s:.200}",
                needs_healing=True,
                heal_hint="restart_backend",
            )

    def _redis_cli_cmd(self, *args: str) -> list[str]:
        """Build a redis-cli docker exec command, injecting auth if configured."""
        cmd = ["docker", "exec", "sowknow4-redis", "redis-cli"]
        if self._redis_password:
            cmd += ["--no-auth-warning", "-a", self._redis_password]
        cmd += list(args)
        return cmd

    async def _check_redis_deep(self, ctx: CheckContext) -> CheckResult:
        """Deep Redis health: PING, memory usage, DBSIZE."""
        try:
            ping_proc = subprocess.run(
                self._redis_cli_cmd("PING"),
                capture_output=True, text=True, timeout=10,
            )
            if "PONG" not in ping_proc.stdout:
                # NOAUTH means Redis is up but the probe isn't sending credentials.
                # Restarting Redis won't fix this — it's a probe config error.
                if "NOAUTH" in ping_proc.stdout or "NOAUTH" in ping_proc.stderr:
                    return CheckResult(
                        plugin=self.name,
                        module="Storage Layer",
                        check_name="redis_deep",
                        status="fail",
                        severity=Severity.CRITICAL,
                        summary="redis_deep probe config error: Redis requires auth but probe has no password",
                        details={"stdout": ping_proc.stdout[:200],
                                 "hint": "Set redis_password in guardian-hc.yml plugins.probes config"},
                        needs_healing=False,
                    )
                return CheckResult(
                    plugin=self.name,
                    module="Storage Layer",
                    check_name="redis_deep",
                    status="fail",
                    severity=Severity.CRITICAL,
                    summary="Redis PING failed",
                    needs_healing=True,
                    heal_hint="restart:sowknow4-redis",
                )

            info_proc = subprocess.run(
                self._redis_cli_cmd("INFO", "memory"),
                capture_output=True, text=True, timeout=10,
            )
            dbsize_proc = subprocess.run(
                self._redis_cli_cmd("DBSIZE"),
                capture_output=True, text=True, timeout=10,
            )

            mem_info = _parse_redis_info(info_proc.stdout)
            used_rss = int(mem_info.get("used_memory_rss", 0))
            maxmemory = int(mem_info.get("maxmemory", 0))
            dbsize = dbsize_proc.stdout.strip()

            details: dict = {"used_memory_rss": used_rss, "maxmemory": maxmemory, "dbsize": dbsize}

            if maxmemory > 0 and used_rss / maxmemory > 0.85:
                return CheckResult(
                    plugin=self.name,
                    module="Storage Layer",
                    check_name="redis_deep",
                    status="warning",
                    severity=Severity.WARNING,
                    summary=f"Redis memory usage >85% ({used_rss}/{maxmemory})",
                    details=details,
                    needs_healing=True,
                    heal_hint="redis_memory_purge",
                )

            return CheckResult(
                plugin=self.name,
                module="Storage Layer",
                check_name="redis_deep",
                status="pass",
                severity=Severity.INFO,
                summary="Redis healthy",
                details=details,
            )
        except Exception as exc:
            return CheckResult(
                plugin=self.name,
                module="Storage Layer",
                check_name="redis_deep",
                status="fail",
                severity=Severity.CRITICAL,
                summary=f"Redis deep check failed: {exc!s:.200}",
                needs_healing=True,
                heal_hint="restart:sowknow4-redis",
            )

    async def _check_postgres_deep(self, ctx: CheckContext) -> CheckResult:
        """Deep Postgres health: connections, idle-in-transaction, deadlocks."""
        try:
            conn_result = subprocess.run(
                [
                    "docker", "exec", "sowknow4-postgres",
                    "psql", "-U", "postgres", "-t", "-c",
                    "SELECT count(*) FROM pg_stat_activity WHERE state IS NOT NULL;",
                ],
                capture_output=True, text=True, timeout=15,
            )
            max_result = subprocess.run(
                [
                    "docker", "exec", "sowknow4-postgres",
                    "psql", "-U", "postgres", "-t", "-c",
                    "SHOW max_connections;",
                ],
                capture_output=True, text=True, timeout=15,
            )
            idle_result = subprocess.run(
                [
                    "docker", "exec", "sowknow4-postgres",
                    "psql", "-U", "postgres", "-t", "-c",
                    "SELECT count(*) FROM pg_stat_activity WHERE state='idle in transaction'"
                    " AND now()-state_change > interval '5 minutes';",
                ],
                capture_output=True, text=True, timeout=15,
            )
            deadlock_result = subprocess.run(
                [
                    "docker", "exec", "sowknow4-postgres",
                    "psql", "-U", "postgres", "-t", "-c",
                    "SELECT sum(deadlocks) FROM pg_stat_database;",
                ],
                capture_output=True, text=True, timeout=15,
            )

            active = int(conn_result.stdout.strip() or 0)
            max_conn = int(max_result.stdout.strip() or 100)
            idle_txn = int(idle_result.stdout.strip() or 0)
            deadlocks = int(deadlock_result.stdout.strip() or 0)

            details = {
                "active_connections": active,
                "max_connections": max_conn,
                "idle_in_transaction": idle_txn,
                "deadlocks": deadlocks,
            }

            if idle_txn > 0:
                return CheckResult(
                    plugin=self.name,
                    module="Storage Layer",
                    check_name="postgres_deep",
                    status="warning",
                    severity=Severity.WARNING,
                    summary=f"Postgres has {idle_txn} idle-in-transaction connections >5min",
                    details=details,
                    needs_healing=True,
                    heal_hint="kill_pg_idle",
                )

            if max_conn > 0 and active / max_conn > 0.80:
                return CheckResult(
                    plugin=self.name,
                    module="Storage Layer",
                    check_name="postgres_deep",
                    status="warning",
                    severity=Severity.WARNING,
                    summary=f"Postgres connection capacity >80% ({active}/{max_conn})",
                    details=details,
                )

            return CheckResult(
                plugin=self.name,
                module="Storage Layer",
                check_name="postgres_deep",
                status="pass",
                severity=Severity.INFO,
                summary=f"Postgres healthy ({active}/{max_conn} connections)",
                details=details,
            )

        except Exception as exc:
            return CheckResult(
                plugin=self.name,
                module="Storage Layer",
                check_name="postgres_deep",
                status="fail",
                severity=Severity.CRITICAL,
                summary=f"Postgres deep check failed: {exc!s:.200}",
            )

    async def _check_deep_health(self, ctx: CheckContext) -> CheckResult:
        """GET /api/v1/health/deep and validate db_connected + celery_ping."""
        url = f"{self._backend_url}/api/v1/health/deep"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)

            if resp.status_code != 200:
                return CheckResult(
                    plugin=self.name,
                    module="Infrastructure",
                    check_name="deep_health",
                    status="fail",
                    severity=Severity.HIGH,
                    summary=f"Deep health returned HTTP {resp.status_code}",
                )

            data = resp.json()
            db_ok = data.get("db_connected", False)
            celery_ok = data.get("celery_ping", False)
            issues = []
            if not db_ok:
                issues.append("db_connected=False")
            if not celery_ok:
                issues.append("celery_ping=False")

            if issues:
                return CheckResult(
                    plugin=self.name,
                    module="Infrastructure",
                    check_name="deep_health",
                    status="fail",
                    severity=Severity.HIGH,
                    summary=f"Deep health issues: {', '.join(issues)}",
                    details=data,
                )

            return CheckResult(
                plugin=self.name,
                module="Infrastructure",
                check_name="deep_health",
                status="pass",
                severity=Severity.INFO,
                summary="Deep health OK (db + celery connected)",
                details=data,
            )
        except Exception as exc:
            return CheckResult(
                plugin=self.name,
                module="Infrastructure",
                check_name="deep_health",
                status="fail",
                severity=Severity.HIGH,
                summary=f"Deep health check failed: {exc!s:.200}",
            )

    async def _check_celery_completion(self, ctx: CheckContext) -> CheckResult:
        """Submit guardian_ping task and verify completion within 30s."""
        try:
            submit = subprocess.run(
                [
                    "docker", "exec", "sowknow4-backend",
                    "python3", "-c",
                    (
                        "from app.tasks.guardian_tasks import guardian_ping;"
                        "r = guardian_ping.apply_async();"
                        "res = r.get(timeout=30);"
                        "print('ok' if res else 'fail')"
                    ),
                ],
                capture_output=True, text=True, timeout=40,
            )
            success = submit.returncode == 0 and "ok" in submit.stdout
            if success:
                return CheckResult(
                    plugin=self.name,
                    module="Document Pipeline",
                    check_name="celery_completion",
                    status="pass",
                    severity=Severity.INFO,
                    summary="Celery task completed successfully",
                )

            # Classify failure: probe config error vs actual Celery failure.
            # Import/syntax errors mean the probe itself is broken — restarting
            # Celery won't help and would just cause unnecessary churn.
            stderr = submit.stderr or ""
            stdout = submit.stdout or ""
            _PROBE_ERROR_KEYWORDS = (
                "modulenotfounderror", "importerror", "syntaxerror",
                "nameerror", "attributeerror", "no module named",
            )
            is_probe_error = any(kw in stderr.lower() or kw in stdout.lower()
                                 for kw in _PROBE_ERROR_KEYWORDS)
            if is_probe_error:
                return CheckResult(
                    plugin=self.name,
                    module="Document Pipeline",
                    check_name="celery_completion",
                    status="fail",
                    severity=Severity.CRITICAL,
                    summary="celery_completion probe config error — Celery is likely fine",
                    details={"stderr": stderr[:500], "hint": "Check probe import path or task registration"},
                    needs_healing=False,  # Don't restart Celery — the probe is broken
                )

            return CheckResult(
                plugin=self.name,
                module="Document Pipeline",
                check_name="celery_completion",
                status="fail",
                severity=Severity.CRITICAL,
                summary="Celery task did not complete within 30s",
                details={"stderr": stderr[:500]},
                needs_healing=True,
                heal_hint="restart:sowknow4-celery-light",
            )
        except Exception as exc:
            return CheckResult(
                plugin=self.name,
                module="Document Pipeline",
                check_name="celery_completion",
                status="fail",
                severity=Severity.CRITICAL,
                summary=f"Celery completion check failed: {exc!s:.200}",
                needs_healing=True,
                heal_hint="restart:sowknow4-celery-light",
            )

    async def _check_pipeline(self, ctx: CheckContext) -> CheckResult:
        """Detect pipeline stages stuck in RUNNING >10 minutes."""
        try:
            result = subprocess.run(
                [
                    "docker", "exec", "sowknow4-postgres",
                    "psql", "-U", "postgres", "-t", "-c",
                    "SELECT count(*) FROM pipeline_stages"
                    " WHERE status='RUNNING'"
                    " AND updated_at < now() - interval '10 minutes';",
                ],
                capture_output=True, text=True, timeout=15,
            )
            stuck = int(result.stdout.strip() or 0)
            if stuck > 0:
                return CheckResult(
                    plugin=self.name,
                    module="Document Pipeline",
                    check_name="pipeline",
                    status="warning",
                    severity=Severity.WARNING,
                    summary=f"{stuck} pipeline stage(s) stuck in RUNNING >10min",
                    details={"stuck_count": stuck},
                    needs_healing=True,
                    heal_hint="requeue_stuck_docs",
                )
            return CheckResult(
                plugin=self.name,
                module="Document Pipeline",
                check_name="pipeline",
                status="pass",
                severity=Severity.INFO,
                summary="No stuck pipeline stages",
            )
        except Exception as exc:
            return CheckResult(
                plugin=self.name,
                module="Document Pipeline",
                check_name="pipeline",
                status="fail",
                severity=Severity.WARNING,
                summary=f"Pipeline check failed: {exc!s:.200}",
            )

    async def _check_nginx(self, ctx: CheckContext) -> CheckResult:
        """Verify Nginx proxy health endpoint responds."""
        url = f"{self._nginx_url}/api/v1/health"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
            if resp.status_code == 200:
                return CheckResult(
                    plugin=self.name,
                    module="Infrastructure",
                    check_name="nginx",
                    status="pass",
                    severity=Severity.INFO,
                    summary="Nginx proxy healthy",
                    details={"status_code": resp.status_code},
                )
            return CheckResult(
                plugin=self.name,
                module="Infrastructure",
                check_name="nginx",
                status="fail",
                severity=Severity.HIGH,
                summary=f"Nginx returned HTTP {resp.status_code}",
                details={"status_code": resp.status_code},
                needs_healing=True,
                heal_hint="restart:sowknow4-nginx",
            )
        except Exception as exc:
            return CheckResult(
                plugin=self.name,
                module="Infrastructure",
                check_name="nginx",
                status="fail",
                severity=Severity.HIGH,
                summary=f"Nginx unreachable: {exc!s:.200}",
                needs_healing=True,
                heal_hint="restart:sowknow4-nginx",
            )

    async def _check_auth_flow(self, ctx: CheckContext) -> CheckResult:
        """Full auth-flow probe: POST /api/v1/auth/login with service account."""
        url = f"{self._backend_url}/api/v1/auth/login"
        username = self._service_account.get("username", "")
        password = self._service_account.get("password", "")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json={"username": username, "password": password})
            if resp.status_code == 200:
                return CheckResult(
                    plugin=self.name,
                    module="Authentication Service",
                    check_name="auth_flow",
                    status="pass",
                    severity=Severity.INFO,
                    summary="Auth login flow succeeded",
                )
            return CheckResult(
                plugin=self.name,
                module="Authentication Service",
                check_name="auth_flow",
                status="fail",
                severity=Severity.CRITICAL,
                summary=f"Auth login flow returned HTTP {resp.status_code}",
                details={"status_code": resp.status_code},
                needs_healing=True,
                heal_hint="restart_backend",
            )
        except Exception as exc:
            return CheckResult(
                plugin=self.name,
                module="Authentication Service",
                check_name="auth_flow",
                status="fail",
                severity=Severity.CRITICAL,
                summary=f"Auth flow unreachable: {exc!s:.200}",
                needs_healing=True,
                heal_hint="restart_backend",
            )

    # ------------------------------------------------------------------
    # Heal helpers
    # ------------------------------------------------------------------

    async def _heal_redis_memory_purge(self) -> HealResult:
        try:
            proc = subprocess.run(
                ["docker", "exec", "sowknow4-redis", "redis-cli", "MEMORY", "PURGE"],
                capture_output=True, text=True, timeout=15,
            )
            success = proc.returncode == 0
            return HealResult(
                plugin=self.name,
                target="sowknow4-redis",
                action="redis_memory_purge",
                success=success,
                details=proc.stdout.strip() or proc.stderr.strip(),
            )
        except Exception as exc:
            return HealResult(
                plugin=self.name,
                target="sowknow4-redis",
                action="redis_memory_purge",
                success=False,
                details=str(exc)[:200],
            )

    async def _heal_kill_pg_idle(self) -> HealResult:
        try:
            proc = subprocess.run(
                [
                    "docker", "exec", "sowknow4-postgres",
                    "psql", "-U", "postgres", "-c",
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                    " WHERE state='idle in transaction'"
                    " AND now()-state_change > interval '5 minutes';",
                ],
                capture_output=True, text=True, timeout=15,
            )
            success = proc.returncode == 0
            return HealResult(
                plugin=self.name,
                target="sowknow4-postgres",
                action="kill_pg_idle",
                success=success,
                details=proc.stdout.strip()[:500],
            )
        except Exception as exc:
            return HealResult(
                plugin=self.name,
                target="sowknow4-postgres",
                action="kill_pg_idle",
                success=False,
                details=str(exc)[:200],
            )

    async def _heal_requeue_stuck_docs(self) -> HealResult:
        try:
            proc = subprocess.run(
                [
                    "docker", "exec", "sowknow4-postgres",
                    "psql", "-U", "postgres", "-c",
                    "UPDATE pipeline_stages SET status='PENDING', updated_at=now()"
                    " WHERE status='RUNNING'"
                    " AND updated_at < now() - interval '10 minutes';",
                ],
                capture_output=True, text=True, timeout=15,
            )
            success = proc.returncode == 0
            return HealResult(
                plugin=self.name,
                target="sowknow4-postgres",
                action="requeue_stuck_docs",
                success=success,
                details=proc.stdout.strip()[:500],
            )
        except Exception as exc:
            return HealResult(
                plugin=self.name,
                target="sowknow4-postgres",
                action="requeue_stuck_docs",
                success=False,
                details=str(exc)[:200],
            )


# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------

def _parse_redis_info(info_text: str) -> dict[str, str]:
    """Parse redis-cli INFO output into a flat dict."""
    result: dict[str, str] = {}
    for line in info_text.splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()
    return result
