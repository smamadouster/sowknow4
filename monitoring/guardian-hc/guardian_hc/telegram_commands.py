"""Telegram command interface for Guardian v2."""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger()


class TelegramCommandHandler:
    """Handles /guardian commands via Telegram Bot API polling."""

    def __init__(self, guardian, token: str, chat_id: str):
        self._guardian = guardian
        self._token = token
        self._chat_id = chat_id
        self._last_update_id = 0
        self._silenced_until = None
        self._commands = {
            "/guardian": self._cmd_status,
            "/gstatus": self._cmd_status,
            "/gtrends": self._cmd_trends,
            "/gprobes": self._cmd_probes,
            "/gpatterns": self._cmd_patterns,
            "/gincidents": self._cmd_incidents,
            "/glearn": self._cmd_learn,
            "/gheal": self._cmd_heal,
            "/gsilence": self._cmd_silence,
        }

    async def poll_once(self):
        """Check for new commands and respond."""
        try:
            url = f"https://api.telegram.org/bot{self._token}/getUpdates"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params={
                    "offset": self._last_update_id + 1,
                    "timeout": 5,
                    "allowed_updates": ["message"],
                })
                data = resp.json()
                for update in data.get("result", []):
                    self._last_update_id = update["update_id"]
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    chat_id = str(msg.get("chat", {}).get("id", ""))

                    if chat_id != self._chat_id:
                        continue

                    parts = text.strip().split()
                    cmd = parts[0].lower() if parts else ""
                    args = parts[1:] if len(parts) > 1 else []

                    handler = self._commands.get(cmd)
                    if handler:
                        response = await handler(args)
                        await self._send(response)
        except Exception as e:
            logger.debug("telegram.poll.error", error=str(e)[:200])

    async def _send(self, text: str):
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={
                "chat_id": self._chat_id,
                "text": text[:4096],
                "parse_mode": "HTML",
            })

    async def _cmd_status(self, args: list) -> str:
        lines = ["<b>Guardian SOWKNOW Status</b>", ""]
        reg = getattr(self._guardian, '_agent_registry', None)
        if reg:
            for a in reg.agents:
                emoji = "✅" if a.status.value == "healthy" else "⚠️"
                lines.append(f"{emoji} {a.name}: {a.status.value}")

        if hasattr(self._guardian, 'correlator'):
            active = getattr(self._guardian.correlator, 'active_incidents', {})
            if active:
                lines.append(f"\n⚡ Active incidents: {len(active)}")
                for inc_id, inc in list(active.items())[:5]:
                    lines.append(f"  {inc_id}: {inc.root_cause.summary[:60]}")
            else:
                lines.append("\n✅ No active incidents")
        return "\n".join(lines)

    async def _cmd_trends(self, args: list) -> str:
        lines = ["📈 <b>Trending Metrics</b>", ""]
        db = getattr(self._guardian, '_metrics_db', None)
        if not db:
            return "Metrics DB not connected"

        metrics = ["disk.usage_pct", "redis.memory_rss", "pg.active_connections",
                   "celery.total_queue_depth", "backend.response_ms"]
        for metric in metrics:
            try:
                current = await db.get_latest(metric)
                if current is None:
                    continue
                slope = await db.get_slope(metric, hours=6)
                if slope is None:
                    arrow = "→"
                elif slope > 5:
                    arrow = "↑↑"
                elif slope > 1:
                    arrow = "↗"
                elif slope < -5:
                    arrow = "↓↓"
                elif slope < -1:
                    arrow = "↘"
                else:
                    arrow = "→"
                lines.append(f"  {arrow} {metric}: {current:.1f}")
            except Exception:
                pass
        return "\n".join(lines) if len(lines) > 2 else "No trend data yet"

    async def _cmd_probes(self, args: list) -> str:
        lines = ["🔍 <b>Probe Results</b>", ""]
        history = self._guardian.get_history(limit=50)
        probe_results = [h for h in history if h.get("plugin") == "probes"]
        if not probe_results:
            return "No recent probe results"
        for r in probe_results[-10:]:
            emoji = "✅" if r.get("success", True) else "❌"
            lines.append(f"{emoji} {r.get('target', '?')}: {r.get('action', '?')[:60]}")
        return "\n".join(lines)

    async def _cmd_patterns(self, args: list) -> str:
        db = getattr(self._guardian, '_metrics_db', None)
        if not db:
            return "Patterns DB not connected"
        patterns = await db.get_active_patterns()
        if not patterns:
            return "🧠 No learned patterns yet"
        lines = ["🧠 <b>Learned Patterns</b>", ""]
        for p in patterns:
            conf_bar = "█" * int(p["confidence"] * 10) + "░" * (10 - int(p["confidence"] * 10))
            lines.append(f"  {p['pattern_name']}")
            lines.append(f"    [{conf_bar}] {p['confidence']:.0%} | matched {p['times_matched']}x")
        return "\n".join(lines)

    async def _cmd_incidents(self, args: list) -> str:
        hours = int(args[0]) if args else 6
        lines = [f"⚡ <b>Incidents (last {hours}h)</b>", ""]
        history = self._guardian.get_history(limit=200)
        heals = [h for h in history if h.get("type") == "heal"]
        if not heals:
            return f"No incidents in the last {hours}h"
        for h in heals[-10:]:
            emoji = "✅" if h.get("success") else "❌"
            lines.append(f"{emoji} {h.get('target', '?')}: {h.get('action', '?')}")
        return "\n".join(lines)

    async def _cmd_learn(self, args: list) -> str:
        db = getattr(self._guardian, '_metrics_db', None)
        if not db:
            return "Learning DB not connected"
        patterns = await db.get_active_patterns()
        lines = ["🎓 <b>Learning Report</b>", ""]
        for p in patterns:
            if p["times_matched"] > 0:
                accuracy = p["times_correct"] / p["times_matched"] * 100
                lines.append(f"  {p['pattern_name']}: {accuracy:.0f}% accurate ({p['times_matched']} matches)")
        if len(lines) <= 2:
            lines.append("  No patterns have been tested yet")
        return "\n".join(lines)

    async def _cmd_heal(self, args: list) -> str:
        if not args:
            return "Usage: /gheal <service-name>"
        service = args[0]
        # Find container for service
        for svc in getattr(self._guardian, 'config', None).services or []:
            if svc.name == service:
                from guardian_hc.healers.container_healer import ContainerHealer
                healer = ContainerHealer()
                result = await healer.heal(svc.container)
                return f"🔧 Force heal {service}: {'success' if result.get('healed') else 'failed'}"
        return f"Unknown service: {service}"

    async def _cmd_silence(self, args: list) -> str:
        from datetime import datetime, timezone, timedelta
        minutes = int(args[0]) if args else 30
        self._silenced_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        return f"🔇 Alerts silenced for {minutes} minutes (until {self._silenced_until.strftime('%H:%M UTC')})"
