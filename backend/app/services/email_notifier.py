"""
Email alert notifier via SendGrid.

Sends HTML email alerts to configured admin addresses.
Requires SENDGRID_API_KEY, ALERT_FROM_EMAIL, and ADMIN_EMAILS environment variables.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Send HTML alert emails to admins via SendGrid."""

    def __init__(self):
        self.api_key: Optional[str] = os.getenv("SENDGRID_API_KEY")
        self.from_email: str = os.getenv("ALERT_FROM_EMAIL", "alerts@sowknow.local")
        admin_emails_raw = os.getenv("ADMIN_EMAILS", "")
        self.admin_emails = [
            e.strip() for e in admin_emails_raw.split(",") if e.strip()
        ]
        self._enabled = bool(self.api_key and self.admin_emails)

        if not self._enabled:
            logger.debug(
                "EmailNotifier: SENDGRID_API_KEY or ADMIN_EMAILS not set — disabled."
            )

    @property
    def is_configured(self) -> bool:
        """True when SendGrid API key is set and email notifications are enabled."""
        return self._enabled

    async def send_alert(
        self,
        subject: str,
        message: str,
        severity: str = "INFO",
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        Send an HTML alert email to all configured admin addresses.

        Args:
            subject:  Email subject line (will be prefixed with [SOWKNOW Alert]).
            message:  Plain-text message body.
            severity: One of CRITICAL / HIGH / MEDIUM / LOW / INFO.
            metadata: Optional key-value context rendered in a table.

        Returns:
            True if all sends succeeded, False if any failed.
        """
        if not self._enabled:
            logger.debug(f"EmailNotifier disabled — would have sent: {subject}")
            return False

        try:
            from sendgrid import SendGridAPIClient  # type: ignore
            from sendgrid.helpers.mail import Mail  # type: ignore
        except ImportError:
            logger.warning("EmailNotifier: sendgrid package not installed")
            return False

        html = _build_html(subject, message, severity, metadata)
        full_subject = f"[SOWKNOW Alert] [{severity.upper()}] {subject}"

        success = True
        try:
            sg = SendGridAPIClient(self.api_key)
            mail = Mail(
                from_email=self.from_email,
                to_emails=self.admin_emails,
                subject=full_subject,
                html_content=html,
            )
            response = sg.send(mail)
            if response.status_code not in (200, 202):
                logger.warning(
                    f"SendGrid returned {response.status_code} for alert: {subject}"
                )
                success = False
            else:
                logger.debug(f"Email alert sent ({severity}): {subject}")
        except Exception as exc:
            logger.warning(f"EmailNotifier: failed to send '{subject}': {exc}")
            success = False

        return success


def _build_html(
    subject: str,
    message: str,
    severity: str,
    metadata: Optional[dict],
) -> str:
    """Build a simple HTML email body."""
    severity_colors = {
        "CRITICAL": "#dc2626",
        "HIGH": "#ea580c",
        "MEDIUM": "#ca8a04",
        "LOW": "#16a34a",
        "INFO": "#2563eb",
    }
    color = severity_colors.get(severity.upper(), "#2563eb")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    meta_rows = ""
    if metadata:
        for k, v in metadata.items():
            meta_rows += f"<tr><td style='padding:4px 8px;font-weight:bold'>{k}</td><td style='padding:4px 8px'>{v}</td></tr>"
        meta_section = f"""
        <h3 style="margin-top:20px">Context</h3>
        <table style="border-collapse:collapse;width:100%">{meta_rows}</table>
        """
    else:
        meta_section = ""

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <div style="background:{color};color:white;padding:12px 20px;border-radius:6px 6px 0 0">
        <strong>[{severity.upper()}] SOWKNOW Alert</strong>
      </div>
      <div style="border:1px solid #e5e7eb;border-top:none;padding:20px;border-radius:0 0 6px 6px">
        <h2 style="margin-top:0">{subject}</h2>
        <p style="white-space:pre-wrap">{message}</p>
        {meta_section}
        <p style="color:#6b7280;font-size:12px;margin-top:24px">{timestamp}</p>
      </div>
    </body></html>
    """
