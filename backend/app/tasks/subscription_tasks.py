"""Subscription payment reminder tasks — sent via email at 08:00 UTC daily."""
import logging
import os
import smtplib
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from app.models.user import User

logger = logging.getLogger(__name__)

REPORT_RECIPIENT = os.getenv("HEALTH_REPORT_EMAIL", "smamadouster@gmail.com")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("GMAIL_SMTP_USER", "")
SMTP_PASSWORD = os.getenv("GMAIL_SMTP_PASSWORD", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID")


def _telegram_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID)


def _send_telegram(message: str) -> bool:
    if not _telegram_configured():
        return False
    try:
        import httpx
    except ImportError:
        logger.warning("Telegram reminder skipped — httpx not installed")
        return False

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_ADMIN_CHAT_ID,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
            )
            if response.status_code == 200:
                logger.info("Telegram reminder sent")
                return True
            else:
                logger.warning("Telegram API error %s: %s", response.status_code, response.text[:200])
                return False
    except Exception as exc:
        logger.warning("Telegram reminder failed: %s", exc)
        return False


def _smtp_configured() -> bool:
    return bool(SMTP_USER and SMTP_PASSWORD)


def _send_email(to: str, subject: str, html_body: str, text_body: str) -> bool:
    if not _smtp_configured():
        logger.warning("Subscription reminder not sent — GMAIL_SMTP_USER or GMAIL_SMTP_PASSWORD not set")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [to], msg.as_string())
        logger.info("Subscription reminder sent to %s", to)
        return True
    except Exception as e:
        logger.error("Failed to send subscription reminder: %s", e)
        return False


def _next_due_date(last_payment: date, billing_cycle: BillingCycle) -> date:
    """Calculate the next payment due date based on last payment and billing cycle."""
    if billing_cycle == BillingCycle.MONTHLY:
        # Add one month, handling end-of-month
        year = last_payment.year
        month = last_payment.month + 1
        if month > 12:
            month = 1
            year += 1
        day = min(last_payment.day, monthrange(year, month)[1])
        return date(year, month, day)
    else:
        # Yearly
        return date(last_payment.year + 1, last_payment.month, last_payment.day)


def _upcoming_due_date(last_payment: date, billing_cycle: BillingCycle, today: date) -> date:
    """Find the upcoming due date (the first due date >= today)."""
    due = _next_due_date(last_payment, billing_cycle)
    # If due date has passed, keep advancing until we find one in the future
    while due < today:
        if billing_cycle == BillingCycle.MONTHLY:
            year = due.year
            month = due.month + 1
            if month > 12:
                month = 1
                year += 1
            day = min(last_payment.day, monthrange(year, month)[1])
            due = date(year, month, day)
        else:
            due = date(due.year + 1, due.month, due.day)
    return due


@celery_app.task(name="app.tasks.subscription_tasks.send_payment_reminders")
def send_payment_reminders() -> dict:
    """Send payment reminder emails for subscriptions due in 2 days."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        today = datetime.now(UTC).date()

        result = db.execute(select(Subscription))
        subs = result.scalars().all()

        reminders_sent = 0
        reminders_failed = 0
        skipped = 0

        for sub in subs:
            if sub.status != SubscriptionStatus.ACTIVE:
                skipped += 1
                continue

            upcoming_due = _upcoming_due_date(sub.last_payment, sub.billing_cycle, today)
            days_until_due = (upcoming_due - today).days

            # Only remind when exactly 2 days away
            if days_until_due != 2:
                skipped += 1
                continue

            # Avoid duplicate reminders for the same due date
            if sub.reminder_sent_for_date == upcoming_due:
                skipped += 1
                continue

            # Resolve recipient
            user_result = db.execute(select(User).where(User.id == sub.user_id))
            user = user_result.scalar_one_or_none()
            recipient = user.email if user else REPORT_RECIPIENT

            # Build email
            subject = "Payment Reminder"
            cycle_label = "month" if sub.billing_cycle == BillingCycle.MONTHLY else "year"
            text_body = (
                f"Hi,\n\n"
                f"This is a friendly reminder that your subscription payment is due in 2 days.\n\n"
                f"Subscription: {sub.name}\n"
                f"Amount: {sub.price}\n"
                f"Billing: {cycle_label}ly\n"
                f"Due date: {upcoming_due.isoformat()}\n\n"
                f"Thanks,\nSOWKNOW"
            )
            html_body = f"""
            <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
              <h2 style="color:#1f2937">Payment Reminder</h2>
              <p>Hi,</p>
              <p>This is a friendly reminder that your subscription payment is due in <strong>2 days</strong>.</p>
              <table style="border-collapse:collapse;width:100%;margin-top:16px">
                <tr style="background:#f3f4f6"><td style="padding:8px;font-weight:bold">Subscription</td><td style="padding:8px">{sub.name}</td></tr>
                <tr><td style="padding:8px;font-weight:bold">Amount</td><td style="padding:8px">{sub.price}</td></tr>
                <tr style="background:#f9fafb"><td style="padding:8px;font-weight:bold">Billing</td><td style="padding:8px">{cycle_label}ly</td></tr>
                <tr><td style="padding:8px;font-weight:bold">Due date</td><td style="padding:8px">{upcoming_due.isoformat()}</td></tr>
              </table>
              <p style="margin-top:24px;color:#6b7280;font-size:12px">
                This reminder was sent automatically by SOWKNOW.
              </p>
            </body></html>
            """

            email_ok = _send_email(recipient, subject, html_body, text_body)
            telegram_msg = (
                f"⏰ *Payment Reminder*\n\n"
                f"*Subscription:* {sub.name}\n"
                f"*Amount:* {sub.price}\n"
                f"*Billing:* {cycle_label}ly\n"
                f"*Due in 2 days:* {upcoming_due.isoformat()}"
            )
            telegram_ok = _send_telegram(telegram_msg)

            if email_ok or telegram_ok:
                sub.reminder_sent_for_date = upcoming_due
                db.commit()
                reminders_sent += 1
            else:
                reminders_failed += 1

        return {
            "sent": reminders_sent,
            "failed": reminders_failed,
            "skipped": skipped,
            "date": today.isoformat(),
        }
    except Exception as e:
        logger.exception("Subscription reminder task failed")
        return {"sent": 0, "failed": 0, "skipped": 0, "error": str(e)}
    finally:
        db.close()
