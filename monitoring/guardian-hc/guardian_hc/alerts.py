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
