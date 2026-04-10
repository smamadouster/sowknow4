"""
Guardian HC -- Embedded Dashboard Server.
Serves a real-time dashboard on port 9090 (configurable).
"""

import os
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()

DASHBOARD_HTML = os.path.join(os.path.dirname(__file__), "dashboard.html")


class DashboardServer:
    """Minimal HTTP server for the Guardian HC dashboard."""

    def __init__(self, guardian, port: int = 9090):
        self.guardian = guardian
        self.port = port

    def _get_metrics(self) -> dict:
        history = self.guardian.get_history(100)
        healed = [h for h in history if h.get("healed") or h.get("success") is True]
        failed = [h for h in history if not (h.get("healed") or h.get("success") is True) and h.get("action")]

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "incidents": {
                "total_24h": len(history),
                "auto_healed": len(healed),
                "pending": len(failed),
                "history": history[-20:],
            },
            "circuit_breakers": {"total": 0, "open": 0, "breakers": []},
            "patrols": {"total_24h": len(self.guardian._history), "history": []},
            "tasks": {"completed": 0, "failed": 0, "stuck": 0, "in_progress": 0},
            "disk": {"usage_pct": 0, "available": "?"},
            "memory_stats": {},
            "learnings": [],
            "improvements": [],
        }

    async def start(self):
        """Start the dashboard HTTP server."""
        from aiohttp import web

        async def handle_dashboard(request):
            if os.path.exists(DASHBOARD_HTML):
                return web.FileResponse(DASHBOARD_HTML)
            return web.Response(text="Dashboard HTML not found", status=404)

        async def handle_metrics(request):
            return web.json_response(self._get_metrics())

        async def handle_send_report(request):
            from guardian_hc.daily_report import send_report
            result = await send_report(self.guardian, alert_manager=self.guardian.alert_manager)
            return web.json_response(result)

        app = web.Application()
        app.router.add_get("/", handle_dashboard)
        app.router.add_get("/dashboard", handle_dashboard)
        app.router.add_get("/api/metrics", handle_metrics)
        app.router.add_post("/api/report/send", handle_send_report)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()
        logger.info("dashboard.started", port=self.port, url=f"http://localhost:{self.port}")
