# Guardian HC Overhaul — Design Spec

**Date:** 2026-04-08
**Status:** Approved
**Goal:** Fix stale Guardian config, restore telegram-bot monitoring, remove journalctl dependency, add daily email report at 6 AM UTC

---

## Problem Statement

Guardian HC has been running with 3 persistent issues:
1. Config references `sowknow4-celery-worker` (dead) and `sowknow4-telegram-bot` (not started) — causes permanent `failed=2 healed=1` every 2 minutes + Telegram alert spam
2. Disk healer calls `journalctl` which doesn't exist in the slim container image
3. No email delivery — daily report is Telegram-only; user needs a rich HTML dashboard emailed at 6 AM UTC

## Scope

### In Scope
- Update `guardian-hc.sowknow4.yml` with correct celery worker names
- Remove `journal_vacuum` from config and disk healer
- Start `sowknow4-telegram-bot` container
- Add SMTP email channel to AlertManager
- Rewrite daily report to produce rich HTML dashboard
- Change daily report schedule from 7 AM to 6 AM UTC
- Add SMTP env vars to docker-compose guardian-hc service

### Out of Scope
- Guardian architecture changes (patrol system, check/heal pattern)
- New checks or healers beyond the disk healer fix
- Slack integration improvements
- Dashboard UI changes

---

## Section A — Config Fix (`guardian-hc.sowknow4.yml`)

### Replace celery-worker with actual workers

Remove:
```yaml
- name: "celery-worker"
  container: "sowknow4-celery-worker"
```

Add:
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
```

### Remove journal_vacuum

```yaml
disk:
  auto_clean:
    # journal_vacuum: removed — not available in slim container
    docker_prune: true
    log_max_size: "50M"
```

### Add email alerts config

```yaml
alerts:
  telegram:
    token: "${TELEGRAM_BOT_TOKEN}"
    chat_id: "${TELEGRAM_CHAT_ID}"
  email:
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    smtp_user: "${GMAIL_SMTP_USER}"
    smtp_password: "${GMAIL_SMTP_PASSWORD}"  # pragma: allowlist secret
    from: "${GMAIL_SMTP_USER}"
    to: "smamadouster@gmail.com"
```

---

## Section B — Disk Healer Fix

**File:** `monitoring/guardian-hc/guardian_hc/healers/disk_healer.py`

Remove the `journalctl --vacuum-size` subprocess call entirely. The Guardian container is `python:3.12-slim` — no systemd, no journalctl. Keep:
- Docker prune via Docker API
- Log file cleanup via `find /var/log`

---

## Section C — Telegram Bot Startup

- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in `.env`
- Run `docker compose up -d telegram-bot` to start the container
- Verify Guardian detects it as healthy after startup

---

## Section D — Email Alert Channel

**File:** `monitoring/guardian-hc/guardian_hc/alerts.py`

Add `send_email(subject, html_body)` method to `AlertManager`:

```python
async def send_email(self, subject: str, html_body: str):
    """Send HTML email via Gmail SMTP with STARTTLS."""
```

Implementation:
- `smtplib.SMTP` with STARTTLS on port 587
- Gmail App Password auth (env: `GMAIL_SMTP_USER`, `GMAIL_SMTP_PASSWORD`)
- `email.mime.multipart.MIMEMultipart("alternative")` with HTML part
- Run in executor (`asyncio.to_thread`) to avoid blocking the event loop
- Log success/failure via structlog, never crash on send failure

Config parsed from `alerts.email` block in YAML.

---

## Section E — Rich Daily Report

**File:** `monitoring/guardian-hc/guardian_hc/daily_report.py`

### Schedule
- **6:00 AM UTC** (changed from 7 AM)

### Delivery
- HTML email to `smamadouster@gmail.com`
- Condensed text summary to Telegram

### Report Template (HTML email)

```
# SOWKNOW4 Daily Health Dashboard
Date: YYYY-MM-DD
Time: HH:MM:SS UTC
Server: hostname (IP)
Platform: SOWKNOW4 Legacy Knowledge Vault

## System Health Overview
| Metric       | Value              | Status    |
|--------------|--------------------|-----------|
| Disk Usage   | XX% (XXG used)     | G/Y/R     |
| Memory Usage | X.XGi/XXGi (XX%)  | G/Y/R     |
| Load Average | X.XX, X.XX, X.XX  | G/Y/R     |

## SOWKNOW4 Services
| Service            | Port | Status | Details            |
|--------------------|------|--------|--------------------|
| Backend API        | 8001 | UP/DOWN| FastAPI             |
| Frontend           | 3000 | UP/DOWN| Next.js PWA         |
| PostgreSQL         | 5432 | UP/DOWN| pgvector            |
| Redis              | 6379 | UP/DOWN| Cache/Queue         |
| Vault              | 8200 | UP/DOWN| Secrets             |
| NATS               | 4222 | UP/DOWN| Messaging           |
| Celery Light       | —    | UP/DOWN| Light tasks         |
| Celery Heavy       | —    | UP/DOWN| OCR/Embeddings      |
| Celery Collections | —    | UP/DOWN| Smart Collections   |
| Celery Beat        | —    | UP/DOWN| Scheduler           |
| Telegram Bot       | —    | UP/DOWN| Chat interface      |
| Guardian HC        | —    | UP/DOWN| Self-healing monitor|
| Prometheus         | 9090 | UP/DOWN| Metrics             |

## Container Summary
X/Y online | Z errored | Total RAM: XXXMB

## Incidents (24h)
- Total: X | Auto-healed: X | Pending: X
- [List of notable incidents]
```

### Data Sources

| Data | Source | Method |
|------|--------|--------|
| Hostname, IP | `socket.gethostname()`, Docker host info | Python stdlib |
| Disk usage | `shutil.disk_usage("/")` via host mount or Docker API `/system/df` | Python stdlib |
| Memory | `/proc/meminfo` (mounted read-only) or Docker API `/info` | File read |
| Load average | `os.getloadavg()` or `/proc/loadavg` | Python stdlib |
| Container status | Docker API `/containers/json?all=true` | httpx UDS |
| Container memory | Docker API `/containers/{id}/stats?stream=false` | httpx UDS |
| Service health | Existing check results from last patrol cycle | In-memory history |
| Incidents | `core._history` list (last 500 actions) | In-memory |

### Status Indicators
- Green: metric within normal range
- Yellow: warning threshold crossed
- Red: critical threshold crossed or service down

Thresholds follow existing config (disk: 70/85/90%, load: 6.0, steal: 20%).

---

## Section F — Docker Compose Updates

**File:** `docker-compose.yml`

Add to guardian-hc service environment:
```yaml
- GMAIL_SMTP_USER=${GMAIL_SMTP_USER}
- GMAIL_SMTP_PASSWORD=${GMAIL_SMTP_PASSWORD}  # pragma: allowlist secret
```

Add `/proc:/host/proc:ro` volume mount for host system metrics (memory, load).

---

## File Change Summary

| File | Change |
|------|--------|
| `monitoring/guardian-hc/guardian-hc.sowknow4.yml` | Replace celery-worker, remove journal_vacuum, add email config |
| `monitoring/guardian-hc/guardian_hc/healers/disk_healer.py` | Remove journalctl call |
| `monitoring/guardian-hc/guardian_hc/alerts.py` | Add `send_email()` method, parse email config |
| `monitoring/guardian-hc/guardian_hc/daily_report.py` | Full rewrite — rich HTML dashboard, email delivery, 6 AM UTC |
| `monitoring/guardian-hc/guardian_hc/core.py` | Update daily report schedule to 6 AM, pass email config |
| `docker-compose.yml` | Add SMTP env vars + /proc mount to guardian-hc service |
| `.env` | Add GMAIL_SMTP_USER, GMAIL_SMTP_PASSWORD (user action) |

---

## Deployment Steps

1. Update all files
2. User sets `GMAIL_SMTP_USER` and `GMAIL_SMTP_PASSWORD` (App Password) in `.env`
3. Verify `TELEGRAM_CHAT_ID` is set in `.env`
4. `docker compose up -d telegram-bot` — start the bot
5. `docker compose --profile monitoring up -d --build guardian-hc` — rebuild Guardian
6. Verify all containers healthy within 5 minutes
7. Check Guardian logs — `failed=0` on critical patrol
8. Test email: trigger a manual daily report or wait until 6 AM UTC
