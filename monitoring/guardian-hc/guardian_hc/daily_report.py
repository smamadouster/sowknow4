"""
Guardian HC -- Daily Health Dashboard Report.
Generates and sends a rich HTML dashboard at 6 AM UTC via email + Telegram summary.
"""

import os
import socket
import shutil
import structlog
import httpx
from datetime import datetime, timezone

logger = structlog.get_logger()

# Service display metadata: (name, port_label, description)
SERVICE_META = {
    "backend": ("Backend API", "8001", "FastAPI"),
    "frontend": ("Frontend", "3000", "Next.js PWA"),
    "postgres": ("PostgreSQL", "5432", "pgvector"),
    "redis": ("Redis", "6379", "Cache/Queue"),
    "vault": ("Vault", "8200", "Secrets"),
    "nats": ("NATS", "4222", "Messaging"),
    "celery-light": ("Celery Light", "\u2014", "Light tasks"),
    "celery-heavy": ("Celery Heavy", "\u2014", "OCR/Embeddings"),
    "celery-collections": ("Celery Collections", "\u2014", "Smart Collections"),
    "celery-beat": ("Celery Beat", "\u2014", "Scheduler"),
    "telegram-bot": ("Telegram Bot", "\u2014", "Chat interface"),
}


async def _get_host_metrics() -> dict:
    """Gather system metrics from /host/proc (mounted read-only) or fallback."""
    metrics = {"hostname": socket.gethostname(), "ip": "unknown"}

    # Disk
    try:
        usage = shutil.disk_usage("/")
        pct = round(usage.used / usage.total * 100)
        used_gb = round(usage.used / (1024**3))
        total_gb = round(usage.total / (1024**3))
        metrics["disk"] = {"pct": pct, "used": f"{used_gb}G", "total": f"{total_gb}G"}
    except Exception:
        metrics["disk"] = {"pct": 0, "used": "?", "total": "?"}

    # Memory from /host/proc/meminfo or /proc/meminfo
    meminfo_path = "/host/proc/meminfo" if os.path.exists("/host/proc/meminfo") else "/proc/meminfo"
    try:
        mem = {}
        with open(meminfo_path) as f:
            for line in f:
                parts = line.split()
                if parts[0] in ("MemTotal:", "MemAvailable:"):
                    mem[parts[0].rstrip(":")] = int(parts[1])  # kB
        total_gi = round(mem.get("MemTotal", 0) / (1024 * 1024), 1)
        avail_gi = round(mem.get("MemAvailable", 0) / (1024 * 1024), 1)
        used_gi = round(total_gi - avail_gi, 1)
        pct = round(used_gi / total_gi * 100) if total_gi else 0
        metrics["memory"] = {"pct": pct, "used": f"{used_gi}Gi", "total": f"{total_gi}Gi"}
    except Exception:
        metrics["memory"] = {"pct": 0, "used": "?", "total": "?"}

    # Load average from /host/proc/loadavg or os.getloadavg()
    try:
        loadavg_path = "/host/proc/loadavg" if os.path.exists("/host/proc/loadavg") else "/proc/loadavg"
        with open(loadavg_path) as f:
            parts = f.read().split()
        metrics["load"] = [float(parts[0]), float(parts[1]), float(parts[2])]
    except Exception:
        try:
            metrics["load"] = list(os.getloadavg())
        except Exception:
            metrics["load"] = [0, 0, 0]

    return metrics


async def _get_container_stats() -> list[dict]:
    """Get all sowknow4 containers with status and memory via Docker API."""
    try:
        transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
        async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=10) as client:
            resp = await client.get("/containers/json?all=true")
            containers = []
            for c in resp.json():
                name = c.get("Names", ["/unknown"])[0].lstrip("/")
                if not name.startswith("sowknow4-"):
                    continue
                svc_name = name.replace("sowknow4-", "")
                state = c.get("State", "unknown")
                health = ""
                if c.get("Status"):
                    health = c["Status"]
                containers.append({
                    "name": name,
                    "service": svc_name,
                    "state": state,
                    "health": health,
                })
            return containers
    except Exception as e:
        logger.warning("daily_report.docker_api_failed", error=str(e)[:100])
        return []


def _status_icon(state: str, health: str) -> tuple[str, str]:
    """Return (emoji, status_text) for a container state."""
    if state != "running":
        return "\U0001f534", "DOWN"
    if "(healthy)" in health:
        return "\U0001f7e2", "UP"
    if "(unhealthy)" in health:
        return "\U0001f534", "RED"
    return "\U0001f7e1", "UP"


def _metric_status(value: float, warn: float, crit: float) -> str:
    if value >= crit:
        return "\U0001f534 Critical"
    if value >= warn:
        return "\U0001f7e1 Warning"
    return "\U0001f7e2 Good"


def _generate_html(metrics: dict, containers: list[dict], history: list[dict], now: datetime) -> str:
    """Generate the rich HTML dashboard email."""
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S UTC")

    disk = metrics["disk"]
    mem = metrics["memory"]
    load = metrics["load"]

    disk_status = _metric_status(disk["pct"], 70, 85)
    mem_status = _metric_status(mem["pct"], 70, 85)
    load_status = _metric_status(load[0], 4.0, 6.0)

    # Build service rows
    svc_rows = ""
    running_count = 0
    errored_count = 0
    total_containers = 0
    for c in containers:
        svc = c["service"]
        total_containers += 1
        icon, status_text = _status_icon(c["state"], c["health"])
        if c["state"] == "running":
            running_count += 1
        else:
            errored_count += 1
        meta = SERVICE_META.get(svc, (svc.replace("-", " ").title(), "\u2014", ""))
        display_name, port, details = meta
        svc_rows += f"""<tr>
<td style="padding:8px 12px;border-bottom:1px solid #eee;font-weight:600">{display_name}</td>
<td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center;font-family:monospace">{port}</td>
<td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center">{icon} {status_text}</td>
<td style="padding:8px 12px;border-bottom:1px solid #eee;color:#6B7280">{details}</td>
</tr>"""

    # Incidents
    healed = [h for h in history if h.get("healed")]
    failed = [h for h in history if not h.get("healed") and h.get("action")]
    healed_count = len(healed)
    pending_count = len(failed)
    total_incidents = len(history)

    incident_rows = ""
    for h in (healed[-5:] + failed[-5:]):
        color = "#10B981" if h.get("healed") else "#EF4444"
        status = "Healed" if h.get("healed") else "Pending"
        target = h.get("target", "?")
        action = h.get("action", h.get("error", ""))
        incident_rows += f"""<tr>
<td style="padding:6px 12px;border-bottom:1px solid #f3f4f6;color:{color};font-weight:600">{status}</td>
<td style="padding:6px 12px;border-bottom:1px solid #f3f4f6">{target}</td>
<td style="padding:6px 12px;border-bottom:1px solid #f3f4f6;color:#6B7280">{action}</td>
</tr>"""

    overall_color = "#10B981" if pending_count == 0 else "#EF4444"
    overall_text = "All Systems Operational" if pending_count == 0 else f"{pending_count} Issue{'s' if pending_count != 1 else ''} Need Attention"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f3f4f6;margin:0;padding:20px">
<div style="max-width:680px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,.08)">

<!-- Header -->
<div style="background:#111827;color:#fff;padding:28px 32px">
<h1 style="margin:0;font-size:22px">\U0001f5a5 SOWKNOW4 Daily Health Dashboard</h1>
<div style="color:#9CA3AF;font-size:13px;margin-top:6px"><strong>Date:</strong> {date_str} &nbsp;|&nbsp; <strong>Time:</strong> {time_str}</div>
<div style="color:#9CA3AF;font-size:13px"><strong>Server:</strong> {metrics['hostname']} &nbsp;|&nbsp; <strong>Platform:</strong> SOWKNOW4 Legacy Knowledge Vault</div>
</div>

<!-- Overall Status -->
<div style="background:{overall_color};color:#fff;padding:14px 32px;font-weight:700;font-size:15px">{overall_text}</div>

<!-- System Health -->
<div style="padding:24px 32px">
<h2 style="margin:0 0 16px;font-size:16px;color:#374151">\U0001f4ca System Health Overview</h2>
<table style="width:100%;border-collapse:collapse;font-size:14px">
<tr style="background:#f9fafb"><th style="padding:10px 12px;text-align:left;color:#6B7280;font-size:12px;text-transform:uppercase">Metric</th><th style="padding:10px 12px;text-align:left;color:#6B7280;font-size:12px;text-transform:uppercase">Value</th><th style="padding:10px 12px;text-align:left;color:#6B7280;font-size:12px;text-transform:uppercase">Status</th></tr>
<tr><td style="padding:10px 12px;border-bottom:1px solid #eee;font-weight:600">Disk Usage</td><td style="padding:10px 12px;border-bottom:1px solid #eee">{disk['pct']}% ({disk['used']} / {disk['total']})</td><td style="padding:10px 12px;border-bottom:1px solid #eee">{disk_status}</td></tr>
<tr><td style="padding:10px 12px;border-bottom:1px solid #eee;font-weight:600">Memory Usage</td><td style="padding:10px 12px;border-bottom:1px solid #eee">{mem['used']}/{mem['total']} ({mem['pct']}%)</td><td style="padding:10px 12px;border-bottom:1px solid #eee">{mem_status}</td></tr>
<tr><td style="padding:10px 12px;border-bottom:1px solid #eee;font-weight:600">Load Average</td><td style="padding:10px 12px;border-bottom:1px solid #eee">{load[0]:.2f}, {load[1]:.2f}, {load[2]:.2f}</td><td style="padding:10px 12px;border-bottom:1px solid #eee">{load_status}</td></tr>
</table>
</div>

<!-- Services -->
<div style="padding:0 32px 24px">
<h2 style="margin:0 0 16px;font-size:16px;color:#374151">\U0001f3e5 SOWKNOW4 Services</h2>
<table style="width:100%;border-collapse:collapse;font-size:14px">
<tr style="background:#f9fafb"><th style="padding:10px 12px;text-align:left;color:#6B7280;font-size:12px;text-transform:uppercase">Service</th><th style="padding:10px 12px;text-align:center;color:#6B7280;font-size:12px;text-transform:uppercase">Port</th><th style="padding:10px 12px;text-align:center;color:#6B7280;font-size:12px;text-transform:uppercase">Status</th><th style="padding:10px 12px;text-align:left;color:#6B7280;font-size:12px;text-transform:uppercase">Details</th></tr>
{svc_rows}
</table>
<div style="margin-top:12px;font-size:13px;color:#6B7280"><strong>{running_count}/{total_containers}</strong> online &nbsp;|&nbsp; <strong>{errored_count}</strong> errored</div>
</div>

<!-- Incidents -->
<div style="padding:0 32px 24px">
<h2 style="margin:0 0 16px;font-size:16px;color:#374151">\U0001f4cb Incidents (24h)</h2>
<div style="display:flex;gap:16px;margin-bottom:16px">
<div style="flex:1;background:#f9fafb;border-radius:8px;padding:12px;text-align:center"><div style="font-size:28px;font-weight:700;color:#111827">{total_incidents}</div><div style="font-size:11px;color:#6B7280;text-transform:uppercase">Total</div></div>
<div style="flex:1;background:#f0fdf4;border-radius:8px;padding:12px;text-align:center"><div style="font-size:28px;font-weight:700;color:#10B981">{healed_count}</div><div style="font-size:11px;color:#6B7280;text-transform:uppercase">Auto-Healed</div></div>
<div style="flex:1;background:{'#fef2f2' if pending_count else '#f9fafb'};border-radius:8px;padding:12px;text-align:center"><div style="font-size:28px;font-weight:700;color:{'#EF4444' if pending_count else '#10B981'}">{pending_count}</div><div style="font-size:11px;color:#6B7280;text-transform:uppercase">Pending</div></div>
</div>
{f'<table style="width:100%;border-collapse:collapse;font-size:13px">{incident_rows}</table>' if incident_rows else '<p style="text-align:center;color:#10B981;padding:8px">No incidents in the last 24 hours</p>'}
</div>

<!-- Footer -->
<div style="background:#f9fafb;padding:16px 32px;text-align:center;font-size:11px;color:#9CA3AF;border-top:1px solid #eee">Guardian HC v1.3.0 &mdash; SOWKNOW4 Legacy Knowledge Vault &mdash; GollamTech</div>

</div></body></html>"""


def _generate_telegram_summary(metrics: dict, containers: list[dict], history: list[dict], now: datetime) -> str:
    """Generate a condensed plain text summary for Telegram."""
    date_str = now.strftime("%Y-%m-%d %H:%M UTC")
    disk = metrics["disk"]
    mem = metrics["memory"]
    load = metrics["load"]

    running = sum(1 for c in containers if c["state"] == "running")
    total = len(containers)
    down = [c["service"] for c in containers if c["state"] != "running"]

    healed = sum(1 for h in history if h.get("healed"))
    failed = sum(1 for h in history if not h.get("healed") and h.get("action"))

    lines = [
        f"\U0001f4ca *SOWKNOW4 Daily Report* -- {date_str}",
        "",
        f"\U0001f5a5 Disk: {disk['pct']}% | Mem: {mem['used']}/{mem['total']} | Load: {load[0]:.1f}",
        f"\U0001f4e6 Containers: {running}/{total} online",
    ]
    if down:
        lines.append(f"\U0001f534 Down: {', '.join(down)}")
    lines.append(f"\U0001f527 Incidents: {len(history)} total | {healed} healed | {failed} pending")

    if failed > 0:
        lines.append("\n\u26a0\ufe0f Manual attention needed!")
    else:
        lines.append("\n\u2705 All systems operational")

    return "\n".join(lines)


def generate_report(guardian) -> tuple[str, str, dict]:
    """Legacy wrapper -- returns (plain, html, data). Not used by new flow."""
    history = guardian.get_history(50)
    healed = [h for h in history if h.get("healed")]
    failed = [h for h in history if not h.get("healed") and h.get("action")]
    data = {"total": len(history), "healed": len(healed), "pending": len(failed)}
    return "", "", data


async def send_report(guardian, alert_manager=None) -> dict:
    """Send the daily dashboard report via email (HTML) and Telegram (summary)."""
    now = datetime.now(timezone.utc)
    history = guardian.get_history(100)
    healed_list = [h for h in history if h.get("healed")]
    failed_list = [h for h in history if not h.get("healed") and h.get("action")]

    result = {
        "incidents": len(history),
        "healed": len(healed_list),
        "pending": len(failed_list),
    }

    metrics = await _get_host_metrics()
    containers = await _get_container_stats()

    # Email: always send the full HTML dashboard
    if alert_manager and alert_manager.email_configured:
        try:
            subject = f"SOWKNOW4 Health Dashboard \u2014 {now.strftime('%Y-%m-%d')}"
            html = _generate_html(metrics, containers, history, now)
            plain = _generate_telegram_summary(metrics, containers, history, now)
            await alert_manager.send_email(subject, html, plain)
            result["email_sent"] = True
        except Exception as e:
            logger.error("daily_report.email_failed", error=str(e)[:200])
            result["email_sent"] = False
    else:
        result["email_sent"] = False
        result["email_skipped"] = "Email not configured"

    # Telegram: always send condensed summary
    if alert_manager:
        try:
            summary = _generate_telegram_summary(metrics, containers, history, now)
            await alert_manager.send(summary)
            result["telegram_sent"] = True
        except Exception as e:
            logger.error("daily_report.telegram_failed", error=str(e)[:200])
            result["telegram_sent"] = False

    return result
