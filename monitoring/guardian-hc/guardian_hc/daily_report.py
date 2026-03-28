"""
Guardian HC -- Daily Intelligence Report.
Generates and sends a daily health summary at 7 AM.
"""

import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()


def generate_report(guardian) -> tuple[str, str, dict]:
    """Generate plain text + HTML report from Guardian state."""
    history = guardian.get_history(50)
    healed = [h for h in history if h.get("healed")]
    failed = [h for h in history if not h.get("healed") and h.get("action")]

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%A, %B %d, %Y")
    total = len(history)
    healed_count = len(healed)
    pending = len(failed)
    is_clean = total == 0 and pending == 0

    data = {"total": total, "healed": healed_count, "pending": pending,
            "healed_items": healed[-10:], "pending_items": failed[-10:]}

    if is_clean:
        plain = f"Guardian HC Report | SOWKNOW4 -- {date_str}\n\nNOTHING TO REPORT\nAll systems healthy.\n\n-- Guardian HC"
    else:
        lines = [f"Guardian HC Report | SOWKNOW4 -- {date_str}", "",
                 f"INCIDENTS: {total}  |  AUTO-HEALED: {healed_count}  |  PENDING: {pending}", ""]
        if healed:
            lines.append("-- AUTO-HEALED --")
            for h in healed[-5:]:
                lines.append(f"  {h.get('target', '?')}: {h.get('action', '')}")
        if failed:
            lines.append("-- NEEDS ATTENTION --")
            for f in failed[-5:]:
                lines.append(f"  {f.get('target', '?')}: {f.get('error', f.get('action', ''))}")
        lines.extend(["", "-- Guardian HC"])
        plain = "\n".join(lines)

    status_color = "#27AE60" if is_clean else "#C0392B" if pending > 0 else "#E67E22"
    status_text = "ALL CLEAR" if is_clean else f"{pending} NEED ATTENTION" if pending > 0 else f"{total} RESOLVED"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{font-family:Arial,sans-serif;background:#f5f6fa;margin:0;padding:20px}}
.c{{max-width:600px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)}}
.h{{background:#1B2A4A;color:#fff;padding:24px}}.h h1{{margin:0;font-size:20px}}.h .d{{color:#9CA3AF;font-size:13px;margin-top:4px}}
.s{{background:{status_color};color:#fff;padding:12px 24px;font-weight:700;font-size:14px}}
.b{{padding:24px}}.m{{display:flex;gap:12px;margin-bottom:16px}}
.m>div{{flex:1;background:#f8f9fa;border-radius:8px;padding:12px;text-align:center}}
.m .n{{font-size:28px;font-weight:700;color:#1B2A4A}}.m .l{{font-size:11px;color:#7F8C8D;text-transform:uppercase}}
.i{{padding:8px 0;border-bottom:1px solid #f0f0f0;font-size:13px}}.i .t{{font-weight:600}}
.f{{background:#f8f9fa;padding:16px 24px;text-align:center;font-size:11px;color:#9CA3AF}}
</style></head><body><div class="c">
<div class="h"><h1>Guardian HC | SOWKNOW4</h1><div class="d">{date_str}</div></div>
<div class="s">{status_text}</div>
<div class="b"><div class="m">
<div><div class="n">{total}</div><div class="l">Incidents</div></div>
<div><div class="n" style="color:#27AE60">{healed_count}</div><div class="l">Healed</div></div>
<div><div class="n" style="color:{'#C0392B' if pending else '#27AE60'}">{pending}</div><div class="l">Pending</div></div>
</div>"""

    if is_clean:
        html += '<p style="text-align:center;color:#27AE60;padding:20px">All systems healthy</p>'
    else:
        for h in healed[-5:]:
            html += f'<div class="i"><div class="t" style="color:#27AE60">{h.get("target", "")}</div><div>{h.get("action", "")}</div></div>'
        for f in failed[-5:]:
            html += f'<div class="i"><div class="t" style="color:#C0392B">{f.get("target", "")}</div><div>{f.get("error", f.get("action", ""))}</div></div>'

    html += '</div><div class="f">Guardian HC -- SOWKNOW4 | GollamTech</div></div></body></html>'

    return plain, html, data


async def send_report(guardian, smtp_config: dict = None, alert_manager=None) -> dict:
    """Send the daily report via Telegram ONLY when there are unresolved issues."""
    plain, html, data = generate_report(guardian)
    result = {"incidents": data["total"], "healed": data["healed"], "pending": data["pending"]}

    # Only send Telegram when there are PENDING (unresolved) issues.
    # If everything was auto-healed or clean, stay silent.
    if data["pending"] > 0 and alert_manager:
        try:
            await alert_manager.send(plain)
            result["alert_sent"] = True
        except Exception:
            result["alert_sent"] = False
    else:
        result["alert_sent"] = False
        if data["pending"] == 0:
            result["alert_skipped"] = "No unresolved issues -- report not sent"

    return result
