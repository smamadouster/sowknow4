"""Daily pipeline health report — sent via email at 07:30 UTC."""
import logging
import os
import smtplib
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

REPORT_RECIPIENT = os.getenv("HEALTH_REPORT_EMAIL", "smamadouster@gmail.com")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("GMAIL_SMTP_USER", "")
SMTP_PASSWORD = os.getenv("GMAIL_SMTP_PASSWORD", "")


def _smtp_configured() -> bool:
    return bool(SMTP_USER and SMTP_PASSWORD)


def _send_email(subject: str, html_body: str, text_body: str) -> bool:
    if not _smtp_configured():
        logger.warning("Health report not sent — GMAIL_SMTP_USER or GMAIL_SMTP_PASSWORD not set")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = REPORT_RECIPIENT
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [REPORT_RECIPIENT], msg.as_string())
        logger.info("Health report sent to %s", REPORT_RECIPIENT)
        return True
    except Exception as e:
        logger.error("Failed to send health report: %s", e)
        return False


@celery_app.task(name="pipeline.daily_health_report")
def daily_health_report() -> dict:
    """Gather pipeline metrics and email a daily health report."""
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.models.pipeline import PipelineStage, StageStatus, StageEnum
    from sqlalchemy import func, select
    from app.core.redis_url import safe_redis_url
    import redis

    db = SessionLocal()
    try:
        now = datetime.now(UTC)
        day_ago = now - timedelta(hours=24)

        # ── Document counts ──
        doc_counts = {}
        for status in DocumentStatus:
            cnt = db.query(func.count(Document.id)).filter(Document.status == status).scalar()
            doc_counts[status.value] = cnt or 0

        total_docs = sum(doc_counts.values())

        # ── Stage breakdown (exclude ERROR docs from funnel) ──
        stage_rows = db.execute(
            select(PipelineStage.stage, PipelineStage.status, func.count().label("cnt"))
            .join(Document, Document.id == PipelineStage.document_id)
            .where(Document.status != DocumentStatus.ERROR)
            .group_by(PipelineStage.stage, PipelineStage.status)
        ).all()

        stage_counts: dict[str, dict[str, int]] = {
            s.value: {"pending": 0, "running": 0, "failed": 0, "completed": 0}
            for s in StageEnum
        }
        for row in stage_rows:
            key = row.stage if isinstance(row.stage, str) else row.stage.value
            status = row.status if isinstance(row.status, str) else row.status.value
            if key in stage_counts and status in stage_counts[key]:
                stage_counts[key][status] = row.cnt

        # ── Last 24h completions ──
        recent_completions = db.execute(
            select(PipelineStage.stage, func.count().label("cnt"))
            .where(
                PipelineStage.status == StageStatus.COMPLETED,
                PipelineStage.completed_at >= day_ago,
            )
            .group_by(PipelineStage.stage)
        ).all()
        recent_by_stage = {
            (r.stage if isinstance(r.stage, str) else r.stage.value): r.cnt
            for r in recent_completions
        }

        # ── Oldest pending document ──
        oldest_pending = (
            db.query(Document)
            .filter(Document.status == DocumentStatus.PENDING)
            .order_by(Document.created_at.asc())
            .first()
        )

        # ── Queue depths via Redis ──
        queue_depths = {}
        try:
            r = redis.from_url(safe_redis_url())
            for q in [
                "pipeline.ocr", "pipeline.chunk", "pipeline.embed",
                "pipeline.index", "pipeline.articles", "pipeline.entities",
                "celery", "scheduled",
            ]:
                queue_depths[q] = r.llen(q)
        except Exception:
            queue_depths = {q: "N/A" for q in [
                "pipeline.ocr", "pipeline.chunk", "pipeline.embed",
                "pipeline.index", "pipeline.articles", "pipeline.entities",
                "celery", "scheduled",
            ]}

        # ── Failed doc count (permanent) ──
        permanent_failed = (
            db.query(func.count(Document.id))
            .filter(Document.status == DocumentStatus.ERROR)
            .scalar()
        )

        # ── Build text report ──
        text_lines = [
            f"SOWKNOW Pipeline Health Report — {now.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "DOCUMENTS",
            f"  Total:     {total_docs}",
            f"  Indexed:   {doc_counts.get('indexed', 0)}",
            f"  Pending:   {doc_counts.get('pending', 0)}",
            f"  Processing:{doc_counts.get('processing', 0)}",
            f"  Error:     {doc_counts.get('error', 0)} (permanent failures)",
            "",
            "PIPELINE FUNNEL (last 24h completions)",
        ]
        for stage in StageEnum:
            s = stage.value
            c = stage_counts.get(s, {})
            completed_24h = recent_by_stage.get(s, 0)
            text_lines.append(
                f"  {s:12s}  pending={c.get('pending', 0):4d}  running={c.get('running', 0):4d}  "
                f"failed={c.get('failed', 0):4d}  completed_24h={completed_24h:4d}"
            )

        text_lines.extend([
            "",
            "QUEUE DEPTHS",
        ])
        for q, d in queue_depths.items():
            text_lines.append(f"  {q:30s} {d}")

        text_lines.extend([
            "",
            "OLDEST PENDING",
        ])
        if oldest_pending:
            age_hours = (now - oldest_pending.created_at).total_seconds() / 3600
            text_lines.append(
                f"  {oldest_pending.filename} ({age_hours:.1f}h old)"
            )
        else:
            text_lines.append("  None")

        text_body = "\n".join(text_lines)

        # ── Build HTML report ──
        stage_rows_html = ""
        for stage in StageEnum:
            s = stage.value
            c = stage_counts.get(s, {})
            completed_24h = recent_by_stage.get(s, 0)
            stage_rows_html += (
                f"<tr><td>{s}</td><td>{c.get('pending', 0)}</td>"
                f"<td>{c.get('running', 0)}</td><td>{c.get('failed', 0)}</td>"
                f"<td>{completed_24h}</td></tr>"
            )

        queue_rows_html = ""
        for q, d in queue_depths.items():
            queue_rows_html += f"<tr><td>{q}</td><td>{d}</td></tr>"

        oldest_html = (
            f"<p>{oldest_pending.filename} ({age_hours:.1f}h old)</p>"
            if oldest_pending
            else "<p>None</p>"
        )

        html_body = f"""
        <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;padding:20px">
          <h2 style="color:#1f2937">🩺 SOWKNOW Pipeline Health Report</h2>
          <p style="color:#6b7280">{now.strftime('%Y-%m-%d %H:%M UTC')}</p>

          <h3 style="margin-top:24px">Documents</h3>
          <table style="border-collapse:collapse;width:100%">
            <tr style="background:#f3f4f6">
              <th style="text-align:left;padding:8px">Status</th>
              <th style="text-align:right;padding:8px">Count</th>
            </tr>
            <tr><td style="padding:8px">Total</td><td style="text-align:right;padding:8px">{total_docs}</td></tr>
            <tr style="background:#f9fafb"><td style="padding:8px">Indexed</td><td style="text-align:right;padding:8px">{doc_counts.get('indexed', 0)}</td></tr>
            <tr><td style="padding:8px">Pending</td><td style="text-align:right;padding:8px">{doc_counts.get('pending', 0)}</td></tr>
            <tr style="background:#f9fafb"><td style="padding:8px">Processing</td><td style="text-align:right;padding:8px">{doc_counts.get('processing', 0)}</td></tr>
            <tr><td style="padding:8px">Error (permanent)</td><td style="text-align:right;padding:8px">{permanent_failed}</td></tr>
          </table>

          <h3 style="margin-top:24px">Pipeline Funnel</h3>
          <table style="border-collapse:collapse;width:100%;font-size:14px">
            <tr style="background:#f3f4f6">
              <th style="text-align:left;padding:8px">Stage</th>
              <th style="text-align:right;padding:8px">Pending</th>
              <th style="text-align:right;padding:8px">Running</th>
              <th style="text-align:right;padding:8px">Failed</th>
              <th style="text-align:right;padding:8px">Completed (24h)</th>
            </tr>
            {stage_rows_html}
          </table>

          <h3 style="margin-top:24px">Queue Depths</h3>
          <table style="border-collapse:collapse;width:100%;font-size:14px">
            <tr style="background:#f3f4f6">
              <th style="text-align:left;padding:8px">Queue</th>
              <th style="text-align:right;padding:8px">Depth</th>
            </tr>
            {queue_rows_html}
          </table>

          <h3 style="margin-top:24px">Oldest Pending Document</h3>
          {oldest_html}

          <p style="color:#9ca3af;font-size:12px;margin-top:32px">
            This report is sent daily at 07:30 UTC.<br>
            To change recipient, set HEALTH_REPORT_EMAIL in your environment.
          </p>
        </body></html>
        """

        subject = f"SOWKNOW Pipeline Health — {now.strftime('%Y-%m-%d')}"
        sent = _send_email(subject, html_body, text_body)

        return {
            "sent": sent,
            "recipient": REPORT_RECIPIENT,
            "timestamp": now.isoformat(),
            "total_docs": total_docs,
            "permanent_failed": permanent_failed,
        }

    except Exception as e:
        logger.exception("Health report generation failed")
        return {"sent": False, "error": str(e)}
    finally:
        db.close()
