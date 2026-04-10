# Guardian HC Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Guardian HC stale config, restore telegram-bot monitoring, remove journalctl dependency, and add rich daily email report at 6 AM UTC.

**Architecture:** Patch-in-place approach — update YAML config for correct container names, remove broken journalctl calls from disk healer, add SMTP email channel to AlertManager, rewrite daily_report.py to generate a rich HTML VPS dashboard, and update docker-compose with SMTP env vars + /proc mount.

**Tech Stack:** Python 3.12, httpx, smtplib, structlog, Docker API via unix socket, Gmail SMTP with App Password

**Spec:** `docs/superpowers/specs/2026-04-08-guardian-hc-overhaul-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `monitoring/guardian-hc/guardian-hc.sowknow4.yml` | Modify | Replace celery-worker, remove journal_vacuum, add email config |
| `monitoring/guardian-hc/guardian_hc/healers/disk_healer.py` | Modify | Remove journalctl subprocess call |
| `monitoring/guardian-hc/guardian_hc/alerts.py` | Modify | Add `send_email()` method with Gmail SMTP |
| `monitoring/guardian-hc/guardian_hc/daily_report.py` | Rewrite | Rich HTML dashboard report + email delivery |
| `monitoring/guardian-hc/guardian_hc/core.py` | Modify | Change daily report schedule 7AM -> 6AM, pass email config |
| `docker-compose.yml` | Modify | Add SMTP env vars + /proc mount to guardian-hc |

---

### Task 1: Update Guardian Config (YAML)

**Files:**
- Modify: `monitoring/guardian-hc/guardian-hc.sowknow4.yml:62-93`

- [ ] **Step 1: Replace celery-worker with actual workers and remove journal_vacuum**

Replace the entire `celery-worker` and `telegram-bot` service block (lines 62-93) with the correct 3 celery workers. Remove `journal_vacuum` from disk config. Add email alerts config.

In `monitoring/guardian-hc/guardian-hc.sowknow4.yml`, replace:

```yaml
  - name: "celery-worker"
    container: "sowknow4-celery-worker"
    health_check:
      type: container
    auto_heal:
      restart: true
      rebuild_on_failure: true

  - name: "celery-beat"
    container: "sowknow4-celery-beat"
    health_check:
      type: container
    auto_heal:
      restart: true
```

With:

```yaml
  - name: "celery-light"
    container: "sowknow4-celery-light"
    health_check:
      type: container
    auto_heal:
      restart: true

  - name: "celery-heavy"
    container: "sowknow4-celery-heavy"
    health_check:
      type: container
    auto_heal:
      restart: true
      rebuild_on_failure: true

  - name: "celery-collections"
    container: "sowknow4-celery-collections"
    health_check:
      type: container
    auto_heal:
      restart: true

  - name: "celery-beat"
    container: "sowknow4-celery-beat"
    health_check:
      type: container
    auto_heal:
      restart: true
```

Then in the `disk:` section, replace:

```yaml
disk:
  warning_threshold: 70
  critical_threshold: 85
  emergency_threshold: 90
  auto_clean:
    journal_vacuum: "100M"
    docker_prune: true
    log_max_size: "50M"
```

With:

```yaml
disk:
  warning_threshold: 70
  critical_threshold: 85
  emergency_threshold: 90
  auto_clean:
    docker_prune: true
    log_max_size: "50M"
```

Then in the `alerts:` section, replace:

```yaml
alerts:
  telegram:
    token: "${TELEGRAM_BOT_TOKEN}"
    chat_id: "${TELEGRAM_CHAT_ID}"
```

With:

```yaml
alerts:
  telegram:
    token: "${TELEGRAM_BOT_TOKEN}"
    chat_id: "${TELEGRAM_CHAT_ID}"
  email:
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    smtp_user: "${GMAIL_SMTP_USER}"
    smtp_password: "${GMAIL_SMTP_PASSWORD}"
    from: "${GMAIL_SMTP_USER}"
    to: "smamadouster@gmail.com"
```

- [ ] **Step 2: Verify YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('monitoring/guardian-hc/guardian-hc.sowknow4.yml'))"`
Expected: No error, clean exit.

- [ ] **Step 3: Commit**

```bash
git add monitoring/guardian-hc/guardian-hc.sowknow4.yml
git commit -m "fix(guardian): update config — correct celery workers, remove journal_vacuum, add email"
```

---

### Task 2: Fix Disk Healer — Remove journalctl

**Files:**
- Modify: `monitoring/guardian-hc/guardian_hc/healers/disk_healer.py`

- [ ] **Step 1: Remove journalctl call from disk healer**

Replace the entire content of `monitoring/guardian-hc/guardian_hc/healers/disk_healer.py` with:

```python
import asyncio
import json
import httpx


class DiskHealer:
    def __init__(self, config=None):
        self.config = config or {}

    async def heal(self) -> dict:
        cleaned = []
        try:
            if self.config.get("auto_clean", {}).get("docker_prune", True):
                transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
                async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=30) as client:
                    await client.post("/containers/prune")
                    await client.post("/images/prune", params={"filters": json.dumps({"dangling": ["true"]})})
                cleaned.append("Docker pruned")

            max_size = self.config.get("auto_clean", {}).get("log_max_size", "50M")
            await (await asyncio.create_subprocess_shell(
                f"find /var/log -name '*.log' -size +{max_size} -delete", stdout=asyncio.subprocess.PIPE
            )).communicate()
            cleaned.append("Large logs removed")

            return {"healed": True, "actions": cleaned}
        except Exception as e:
            return {"healed": False, "error": str(e)[:200], "partial": cleaned}
```

- [ ] **Step 2: Commit**

```bash
git add monitoring/guardian-hc/guardian_hc/healers/disk_healer.py
git commit -m "fix(guardian): remove journalctl call from disk healer — not available in slim image"
```

---

### Task 3: Add Email Channel to AlertManager

**Files:**
- Modify: `monitoring/guardian-hc/guardian_hc/alerts.py`

- [ ] **Step 1: Add send_email method**

Replace the entire content of `monitoring/guardian-hc/guardian_hc/alerts.py` with:

```python
import os
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx
import structlog

logger = structlog.get_logger()


class AlertManager:
    def __init__(self, config: dict = None):
        config = config or {}
        self.telegram_token = ""
        self.telegram_chat_id = ""
        self.slack_url = ""

        tg = config.get("telegram", {})
        tf = tg.get("token_file", "")
        if tf and os.path.exists(tf):
            self.telegram_token = open(tf).read().strip()
        if not self.telegram_token:
            self.telegram_token = str(tg.get("token", os.getenv("TELEGRAM_BOT_TOKEN", "")))
        self.telegram_chat_id = str(tg.get("chat_id", os.getenv("TELEGRAM_CHAT_ID", "")))

        self.slack_url = config.get("slack", {}).get("webhook_url", os.getenv("SLACK_WEBHOOK_URL", ""))

        # Email (Gmail SMTP)
        em = config.get("email", {})
        self.smtp_host = em.get("smtp_host", os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com"))
        self.smtp_port = int(em.get("smtp_port", os.getenv("GMAIL_SMTP_PORT", "587")))
        self.smtp_user = str(em.get("smtp_user", os.getenv("GMAIL_SMTP_USER", "")))
        self.smtp_password = str(em.get("smtp_password", os.getenv("GMAIL_SMTP_PASSWORD", "")))
        self.email_from = str(em.get("from", self.smtp_user))
        self.email_to = str(em.get("to", ""))

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_user and self.smtp_password and self.email_to)

    async def send(self, message: str):
        if self.telegram_token and self.telegram_chat_id:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        f"https://api.telegram.org/bot{self.telegram_token}/sendMessage",
                        json={
                            "chat_id": self.telegram_chat_id,
                            "text": f"Guardian HC | SOWKNOW4\n\n{message}",
                            "parse_mode": "Markdown",
                        },
                    )
                    logger.info("alert.telegram.sent")
            except Exception as e:
                logger.warning("alert.telegram.failed", error=str(e)[:100])

        if self.slack_url:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(self.slack_url, json={"text": f"Guardian HC | SOWKNOW4: {message}"})
            except Exception:
                pass

    async def send_email(self, subject: str, html_body: str, plain_body: str = ""):
        """Send HTML email via Gmail SMTP with STARTTLS. Runs in executor to avoid blocking."""
        if not self.email_configured:
            logger.warning("alert.email.not_configured")
            return

        def _send():
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.email_from
            msg["To"] = self.email_to

            if plain_body:
                msg.attach(MIMEText(plain_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.email_from, [self.email_to], msg.as_string())

        try:
            await asyncio.to_thread(_send)
            logger.info("alert.email.sent", to=self.email_to)
        except Exception as e:
            logger.warning("alert.email.failed", error=str(e)[:200])
```

- [ ] **Step 2: Commit**

```bash
git add monitoring/guardian-hc/guardian_hc/alerts.py
git commit -m "feat(guardian): add Gmail SMTP email channel to AlertManager"
```

---

### Task 4: Rewrite Daily Report — Rich HTML Dashboard

**Files:**
- Rewrite: `monitoring/guardian-hc/guardian_hc/daily_report.py`

- [ ] **Step 1: Replace daily_report.py with rich dashboard generator**

Replace the entire content of `monitoring/guardian-hc/guardian_hc/daily_report.py` with:

```python
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
<div style="background:#f9fafb;padding:16px 32px;text-align:center;font-size:11px;color:#9CA3AF;border-top:1px solid #eee">Guardian HC v1.2.0 &mdash; SOWKNOW4 Legacy Knowledge Vault &mdash; GollamTech</div>

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
    """Legacy wrapper — returns (plain, html, data). Not used by new flow."""
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
```

- [ ] **Step 2: Commit**

```bash
git add monitoring/guardian-hc/guardian_hc/daily_report.py
git commit -m "feat(guardian): rich HTML daily dashboard report with email + Telegram delivery"
```

---

### Task 5: Update Core — 6 AM Schedule

**Files:**
- Modify: `monitoring/guardian-hc/guardian_hc/core.py:256-271`

- [ ] **Step 1: Change daily report schedule from 7 AM to 6 AM UTC**

In `monitoring/guardian-hc/guardian_hc/core.py`, in the `_daily_report_loop` method, replace:

```python
    async def _daily_report_loop(self):
        """Send daily report at 7:00 AM UTC."""
        from guardian_hc.daily_report import send_report
        while True:
            now = datetime.now(timezone.utc)
            target = now.replace(hour=7, minute=0, second=0, microsecond=0)
            if now >= target:
                target = target.replace(day=target.day + 1)
            wait = (target - now).total_seconds()
            logger.info("daily_report.scheduled", next_run=target.isoformat(), wait_hours=round(wait / 3600, 1))
            await asyncio.sleep(wait)
            try:
                result = await send_report(self, alert_manager=self.alert_manager)
                logger.info("daily_report.sent", result=result)
            except Exception as e:
                logger.error("daily_report.failed", error=str(e)[:200])
```

With:

```python
    async def _daily_report_loop(self):
        """Send daily report at 6:00 AM UTC."""
        from guardian_hc.daily_report import send_report
        while True:
            now = datetime.now(timezone.utc)
            target = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if now >= target:
                target = target.replace(day=target.day + 1)
            wait = (target - now).total_seconds()
            logger.info("daily_report.scheduled", next_run=target.isoformat(), wait_hours=round(wait / 3600, 1))
            await asyncio.sleep(wait)
            try:
                result = await send_report(self, alert_manager=self.alert_manager)
                logger.info("daily_report.sent", result=result)
            except Exception as e:
                logger.error("daily_report.failed", error=str(e)[:200])
```

- [ ] **Step 2: Commit**

```bash
git add monitoring/guardian-hc/guardian_hc/core.py
git commit -m "fix(guardian): change daily report schedule from 7 AM to 6 AM UTC"
```

---

### Task 6: Update Docker Compose — SMTP Env + /proc Mount

**Files:**
- Modify: `docker-compose.yml:520-549`

- [ ] **Step 1: Add SMTP env vars and /proc mount to guardian-hc service**

In `docker-compose.yml`, in the `guardian-hc` service, replace the environment block:

```yaml
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - REDIS_PASSWORD=${REDIS_PASSWORD}  # pragma: allowlist secret
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./monitoring/guardian-hc/guardian-hc.sowknow4.yml:/config/guardian-hc.yml:ro
```

With:

```yaml
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - REDIS_PASSWORD=${REDIS_PASSWORD}  # pragma: allowlist secret
      - GMAIL_SMTP_USER=${GMAIL_SMTP_USER}
      - GMAIL_SMTP_PASSWORD=${GMAIL_SMTP_PASSWORD}  # pragma: allowlist secret
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./monitoring/guardian-hc/guardian-hc.sowknow4.yml:/config/guardian-hc.yml:ro
      - /proc:/host/proc:ro
```

- [ ] **Step 2: Verify compose syntax**

Run: `docker compose config --quiet`
Expected: No error output.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(guardian): add SMTP env vars and /proc mount for daily report"
```

---

### Task 7: Update Version + Deps

**Files:**
- Modify: `monitoring/guardian-hc/setup.py`

- [ ] **Step 1: Bump version to 1.2.0**

In `monitoring/guardian-hc/setup.py`, replace:

```python
    version="1.1.0",
```

With:

```python
    version="1.2.0",
```

- [ ] **Step 2: Commit**

```bash
git add monitoring/guardian-hc/setup.py
git commit -m "chore(guardian): bump version to 1.2.0"
```

---

### Task 8: Deploy + Verify

- [ ] **Step 1: User sets environment variables**

The user must add to `.env`:
```
GMAIL_SMTP_USER=smamadouster@gmail.com
GMAIL_SMTP_PASSWORD=<gmail-app-password>  # pragma: allowlist secret
TELEGRAM_CHAT_ID=<their-chat-id>
```

Gmail App Password: Google Account > Security > 2FA > App passwords > generate one for "Mail".

- [ ] **Step 2: Start telegram-bot**

```bash
docker compose up -d telegram-bot
```

Expected: `sowknow4-telegram-bot` starts and shows `(healthy)` within 60s.

Verify: `docker ps --filter name=sowknow4-telegram-bot --format "{{.Names}} {{.Status}}"`

- [ ] **Step 3: Rebuild and restart Guardian HC**

```bash
docker compose --profile monitoring up -d --build guardian-hc
```

Expected: `sowknow4-guardian-hc` rebuilds and shows `(healthy)` within 60s.

- [ ] **Step 4: Verify Guardian logs show no persistent failures**

```bash
docker logs sowknow4-guardian-hc --tail 20
```

Expected:
- `patrol.critical.complete failed=0 healed=0` (all green)
- No `journalctl: not found` errors
- `daily_report.scheduled next_run=2026-04-09T06:00:00` (next 6 AM UTC)

- [ ] **Step 5: Verify all containers healthy**

```bash
docker compose --profile monitoring ps
```

Expected: All containers show `(healthy)`. No `failed=2` spam in Guardian logs.

- [ ] **Step 6: Test email delivery (optional manual trigger)**

```bash
docker exec sowknow4-guardian-hc python -c "
import asyncio
from guardian_hc.core import GuardianHC
g = GuardianHC.from_config('/config/guardian-hc.yml')
from guardian_hc.daily_report import send_report
print(asyncio.run(send_report(g, alert_manager=g.alert_manager)))
"
```

Expected: Email arrives at smamadouster@gmail.com with the rich HTML dashboard. Telegram gets condensed summary.
