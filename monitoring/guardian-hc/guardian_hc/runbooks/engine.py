"""
Guardian HC — Runbook Engine

Runbooks are YAML files that define step-by-step diagnostic and repair procedures
for specific incident types. Each runbook maps to a check_name (or service) and
provides ordered steps with success/failure branching.

When Guardian encounters a failing check that has a runbook, it runs the runbook
instead of falling back to a generic container restart. This enables:

  - Root-cause diagnosis before any destructive action
  - Ordered escalation (diagnose → targeted fix → restart → rebuild → alert human)
  - Probe error detection (don't restart a healthy container because a probe is broken)
  - Suppression-aware restarts (all container restarts go through RestartTracker)

Step actions:
  exec               — run a command inside a container via docker exec
  restart_container  — restart a container (gated through RestartTracker)
  http_check         — GET an HTTP URL and check the status code
  alert              — send a Telegram/email alert
  wait               — sleep N seconds (for post-restart stabilisation)
  log                — emit a structured log line (terminal no-op step)

YAML format:

  name: celery_completion
  description: "..."
  triggers:
    - check_name: celery_completion   # matches CheckResult.check_name
  steps:
    - id: my_step
      name: "Human-readable label"
      action: exec
      container: sowknow4-backend
      command: "python3 -c 'print(ok)'"
      expect_in_stdout: "ok"          # optional — checked after returncode
      expect_returncode: 0            # default 0
      timeout: 30                     # seconds, default 45
      wait_after: 10                  # seconds to sleep after (restart only)
      on_success: next_step_id        # "next" = advance in list order
      on_failure: other_step_id
      terminal: false                 # true = stop execution here
"""
from __future__ import annotations

import asyncio
import subprocess
import structlog
import yaml
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from guardian_hc.core import GuardianHC

logger = structlog.get_logger()


@dataclass
class StepResult:
    step_id: str
    action: str
    success: bool
    output: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RunbookResult:
    runbook_name: str
    check_name: str
    outcome: str          # "resolved" | "escalated" | "probe_error" | "suppressed" | "incomplete"
    steps_executed: list[StepResult] = field(default_factory=list)
    duration_s: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_log_dict(self) -> dict:
        return {
            "runbook": self.runbook_name,
            "check": self.check_name,
            "outcome": self.outcome,
            "steps": len(self.steps_executed),
            "duration_s": round(self.duration_s, 1),
        }


class RunbookEngine:
    """Load YAML runbooks and execute them against live infrastructure."""

    def __init__(self, runbooks_dir: str, guardian: "GuardianHC") -> None:
        self._guardian = guardian
        self._runbooks: dict[str, dict] = {}
        self._load(runbooks_dir)

    def _load(self, runbooks_dir: str) -> None:
        p = Path(runbooks_dir)
        if not p.exists():
            logger.warning("runbooks.dir_not_found", path=runbooks_dir)
            return
        count = 0
        for path in sorted(p.glob("*.yml")):
            try:
                with open(path) as f:
                    rb = yaml.safe_load(f)
                name = rb.get("name", path.stem)
                self._runbooks[name] = rb
                count += 1
            except Exception as e:
                logger.error("runbooks.load_failed", path=str(path), error=str(e)[:200])
        logger.info("runbooks.loaded", count=count, dir=runbooks_dir)

    @property
    def loaded(self) -> list[str]:
        return list(self._runbooks.keys())

    def find(self, check_name: str, service: str = "") -> dict | None:
        """Return the runbook for a check_name, or None if none defined."""
        # Direct name match
        if check_name in self._runbooks:
            return self._runbooks[check_name]
        # Trigger-based match
        for rb in self._runbooks.values():
            for trigger in rb.get("triggers", []):
                if trigger.get("check_name") == check_name:
                    return rb
                if service and trigger.get("service") == service:
                    return rb
        return None

    async def execute(
        self,
        runbook: dict,
        check_name: str,
        context: dict | None = None,
    ) -> RunbookResult:
        """Execute a runbook and return the result."""
        ctx = context or {}
        # Inject Redis auth string for use in exec commands
        rp = getattr(self._guardian, "_v2_config", None)
        if rp:
            redis_pw = rp.celery.get("redis_password", "") if hasattr(rp, "celery") else ""
        else:
            redis_pw = self._guardian.config.celery.get("redis_password", "")
        if redis_pw:
            ctx.setdefault("redis_auth", f"--no-auth-warning -a {redis_pw}")
        else:
            ctx.setdefault("redis_auth", "")

        start = datetime.now(timezone.utc)
        result = RunbookResult(runbook_name=runbook.get("name", "?"), check_name=check_name)

        steps_list: list[dict] = runbook.get("steps", [])
        steps_by_id: dict[str, dict] = {s["id"]: s for s in steps_list}
        step_ids: list[str] = [s["id"] for s in steps_list]

        current_id: str | None = step_ids[0] if step_ids else None

        while current_id:
            step = steps_by_id.get(current_id)
            if step is None:
                logger.warning("runbooks.unknown_step", step_id=current_id, runbook=runbook["name"])
                break

            logger.info("runbook.step", runbook=runbook["name"], step=current_id, action=step.get("action"))
            step_result = await self._execute_step(step, ctx)
            result.steps_executed.append(step_result)

            if step.get("terminal", False):
                result.outcome = step["id"]
                break

            # Resolve next step
            next_raw = step.get("on_success") if step_result.success else step.get("on_failure")
            if next_raw == "next":
                idx = step_ids.index(current_id)
                current_id = step_ids[idx + 1] if idx + 1 < len(step_ids) else None
            else:
                current_id = next_raw

        if not result.outcome:
            result.outcome = "incomplete"

        result.duration_s = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info("runbook.complete", **result.to_log_dict())
        return result

    # ------------------------------------------------------------------
    # Step executors
    # ------------------------------------------------------------------

    async def _execute_step(self, step: dict, ctx: dict) -> StepResult:
        action = step.get("action", "")
        dispatch = {
            "exec": self._exec,
            "restart_container": self._restart_container,
            "http_check": self._http_check,
            "alert": self._alert,
            "wait": self._wait,
            "log": self._log_step,
            "resolved": self._log_step,
            "escalated": self._log_step,
        }
        fn = dispatch.get(action)
        if fn is None:
            return StepResult(step_id=step["id"], action=action, success=False,
                              output=f"unknown action: {action!r}")
        try:
            return await fn(step, ctx)
        except Exception as exc:
            logger.error("runbook.step_exception", step=step["id"], error=str(exc)[:200])
            return StepResult(step_id=step["id"], action=action, success=False, output=str(exc)[:300])

    async def _exec(self, step: dict, ctx: dict) -> StepResult:
        container = step.get("container", "")
        cmd_str = step.get("command", "")
        # Substitute context placeholders: {redis_auth}, {check_name}, etc.
        for k, v in ctx.items():
            cmd_str = cmd_str.replace(f"{{{k}}}", str(v))

        cmd = ["docker", "exec", container, "sh", "-c", cmd_str]
        timeout = int(step.get("timeout", 45))
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return StepResult(step_id=step["id"], action="exec", success=False,
                              output=f"timed out after {timeout}s")

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        expected_rc = int(step.get("expect_returncode", 0))
        success = proc.returncode == expected_rc

        expected_str = step.get("expect_in_stdout")
        if success and expected_str:
            success = expected_str in stdout

        reject_str = step.get("reject_in_stdout")
        if success and reject_str and reject_str in stdout:
            success = False

        reject_stderr = step.get("reject_in_stderr")
        if success and reject_stderr and reject_stderr in stderr:
            success = False

        output = f"rc={proc.returncode}"
        if stdout:
            output += f" stdout={stdout[:300]}"
        if stderr:
            output += f" stderr={stderr[:300]}"

        return StepResult(step_id=step["id"], action="exec", success=success, output=output)

    async def _restart_container(self, step: dict, ctx: dict) -> StepResult:
        container = step.get("container", "")
        guardian = self._guardian
        tracker = guardian._get_tracker(container)
        can, msg = tracker.can_restart()
        if not can:
            logger.warning("runbook.restart_suppressed", container=container, reason=msg[:200])
            return StepResult(step_id=step["id"], action="restart_container", success=False,
                              output=f"suppressed: {msg[:300]}")

        from guardian_hc.healers.container_healer import ContainerHealer
        healer = ContainerHealer()
        out = await healer.heal(container)
        success = out.get("healed", False)
        tracker.record_attempt(success)
        guardian._save_tracker_state()

        wait_after = int(step.get("wait_after", 15))
        if success and wait_after:
            await asyncio.sleep(wait_after)

        return StepResult(step_id=step["id"], action="restart_container", success=success,
                          output=str(out)[:300])

    async def _http_check(self, step: dict, ctx: dict) -> StepResult:
        import httpx
        url = step.get("url", "")
        for k, v in ctx.items():
            url = url.replace(f"{{{k}}}", str(v))
        expect_status = int(step.get("expect_status", 200))
        timeout = int(step.get("timeout", 10))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
            success = resp.status_code == expect_status
            return StepResult(step_id=step["id"], action="http_check", success=success,
                              output=f"HTTP {resp.status_code}")
        except Exception as exc:
            return StepResult(step_id=step["id"], action="http_check", success=False,
                              output=str(exc)[:200])

    async def _alert(self, step: dict, ctx: dict) -> StepResult:
        message = step.get("message", "")
        for k, v in ctx.items():
            message = message.replace(f"{{{k}}}", str(v))
        try:
            await self._guardian.alert_manager.send(message)
            return StepResult(step_id=step["id"], action="alert", success=True)
        except Exception as exc:
            return StepResult(step_id=step["id"], action="alert", success=False, output=str(exc)[:200])

    async def _wait(self, step: dict, ctx: dict) -> StepResult:
        secs = int(step.get("seconds", 5))
        await asyncio.sleep(secs)
        return StepResult(step_id=step["id"], action="wait", success=True, output=f"slept {secs}s")

    async def _log_step(self, step: dict, ctx: dict) -> StepResult:
        message = step.get("message", step["id"])
        logger.info("runbook.terminal_step", step=step["id"], message=message)
        return StepResult(step_id=step["id"], action=step.get("action", "log"), success=True,
                          output=message)
