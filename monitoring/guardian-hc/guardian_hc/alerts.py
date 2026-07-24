import os
import re
import json
import time
import asyncio
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx
import structlog

logger = structlog.get_logger()


def _resolve_env(value: str) -> str:
    """Resolve ${VAR} patterns in config values to environment variables."""
    if not isinstance(value, str):
        return value
    return re.sub(r'\$\{(\w+)\}', lambda m: os.getenv(m.group(1), m.group(0)), value)


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
            self.telegram_token = _resolve_env(str(tg.get("token", "")))
        self.telegram_chat_id = _resolve_env(str(tg.get("chat_id", "")))

        self.slack_url = config.get("slack", {}).get("webhook_url", os.getenv("SLACK_WEBHOOK_URL", ""))

        # Email (Gmail SMTP)
        em = config.get("email", {})
        self.smtp_host = _resolve_env(em.get("smtp_host", "smtp.gmail.com"))
        self.smtp_port = int(_resolve_env(em.get("smtp_port", "587")))
        self.smtp_user = _resolve_env(em.get("smtp_user", ""))
        self.smtp_password = _resolve_env(em.get("smtp_password", ""))
        self.email_from = _resolve_env(em.get("from", self.smtp_user))
        self.email_to = _resolve_env(em.get("to", ""))

        # Alert flood control: identical alerts are sent at most once per
        # throttle window; repeats are counted and summarized on the next send.
        self.throttle_minutes = int(config.get("throttle_minutes", 30))
        self._throttle_state_file = (
            os.getenv("GUARDIAN_STATE_DIR", "/tmp") + "/guardian-alert-throttle.json"
        )
        self._throttle: dict[str, dict] = self._load_throttle_state()

    # ------------------------------------------------------------------
    # Throttle (flood control)
    # ------------------------------------------------------------------

    def _load_throttle_state(self) -> dict:
        try:
            with open(self._throttle_state_file) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_throttle_state(self) -> None:
        try:
            tmp = self._throttle_state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._throttle, f)
            os.replace(tmp, self._throttle_state_file)
        except Exception as e:
            logger.warning("alert.throttle.save_failed", error=str(e)[:100])

    @staticmethod
    def _throttle_key(message: str) -> str:
        """Coarse fingerprint: digits stripped so '3 stuck' and '5 stuck'
        variants of the same alert share one throttle bucket."""
        normalized = re.sub(r"\d+", "N", message[:200])
        return hashlib.sha1(normalized.encode()).hexdigest()

    def _throttle_check(self, message: str) -> str | None:
        """Return a suffix to append when sending, or None to suppress.

        First send in a window: allowed (with a "×N suppressed" note if the
        previous window had repeats). Repeats inside the window: counted
        and suppressed.
        """
        if self.throttle_minutes <= 0:
            return ""
        key = self._throttle_key(message)
        now = time.time()
        entry = self._throttle.get(key)
        window = self.throttle_minutes * 60
        if entry and now - entry["ts"] < window:
            entry["count"] += 1
            self._save_throttle_state()
            logger.info(
                "alert.throttled", key=key[:8], count=entry["count"],
                window_min=self.throttle_minutes,
            )
            return None
        suppressed = entry["count"] if entry else 0
        self._throttle[key] = {"ts": now, "count": 0}
        # Bound state size (drop entries older than 7 days)
        if len(self._throttle) > 500:
            cutoff = now - 7 * 86400
            self._throttle = {k: v for k, v in self._throttle.items() if v["ts"] > cutoff}
        self._save_throttle_state()
        if suppressed:
            return (
                f"\n\n_(this alert repeated {suppressed}× in the last "
                f"{self.throttle_minutes}min — repeats are throttled)_"
            )
        return ""

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_user and self.smtp_password and self.email_to)

    async def send(self, message: str):
        suffix = self._throttle_check(message)
        if suffix is None:
            return  # throttled repeat — counted, not sent
        message = message + suffix
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

    async def send_email_only(self, message: str):
        """Send alert via email only (used when Telegram is down)."""
        suffix = self._throttle_check(message)
        if suffix is None:
            return  # throttled repeat
        message = message + suffix
        await self.send_email(
            subject="Guardian HC Alert (Telegram DOWN)",
            html_body=f"<p>{message}</p>",
            plain_body=message,
        )

    async def test_telegram(self) -> bool:
        """Verify Telegram alerting is functional. Returns True if working."""
        if not (self.telegram_token and self.telegram_chat_id):
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{self.telegram_token}/getMe")
                return resp.status_code == 200 and resp.json().get("ok", False)
        except Exception:
            return False

    async def test_email(self) -> bool:
        """Verify SMTP credentials are valid. Returns True if login succeeds."""
        if not self.email_configured:
            return False

        def _test():
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
            return True

        try:
            return await asyncio.to_thread(_test)
        except Exception:
            return False
