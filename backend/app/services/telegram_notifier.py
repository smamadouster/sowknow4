"""
Telegram alert notifier.

Sends formatted alert messages to a configured admin chat via the Telegram Bot API.
Requires TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID environment variables.
"""

import json
import logging
import os
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

_SEVERITY_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH": "🟠",
    "MEDIUM": "🟡",
    "LOW": "🟢",
    "INFO": "ℹ️",
}


class TelegramNotifier:
    """Send alert messages to a Telegram chat via the Bot API."""

    def __init__(self):
        self.bot_token: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id: str | None = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
        self._enabled = bool(self.bot_token and self.chat_id)

        if not self._enabled:
            logger.debug(
                "TelegramNotifier: TELEGRAM_BOT_TOKEN or TELEGRAM_ADMIN_CHAT_ID not set — notifications disabled."
            )

    @property
    def is_configured(self) -> bool:
        """True when Telegram bot token and chat ID are set."""
        return self._enabled

    async def send_alert(
        self,
        message: str,
        severity: str = "INFO",
        metadata: dict | None = None,
        title: str | None = None,
    ) -> bool:
        """
        Send an alert message to the configured Telegram chat.

        Args:
            message:  Main message body.
            severity: One of CRITICAL / HIGH / MEDIUM / LOW / INFO.
            metadata: Optional key-value context (truncated to stay within limits).
            title:    Optional bolded title line.

        Returns:
            True if the message was delivered, False otherwise.
        """
        if not self._enabled:
            logger.debug(f"TelegramNotifier disabled — would have sent: {message[:80]}")
            return False

        try:
            import httpx
        except ImportError:
            logger.warning("TelegramNotifier: httpx not installed, cannot send alert")
            return False

        emoji = _SEVERITY_EMOJI.get(severity.upper(), "ℹ️")
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

        parts = [f"{emoji} *{severity.upper()} Alert*"]
        if title:
            parts.append(f"*{_escape_md(title)}*")
        parts.append(_escape_md(message))

        if metadata:
            try:
                meta_str = json.dumps(metadata, indent=2, default=str)
                # Telegram message limit ~4096 chars; keep metadata short
                if len(meta_str) > 800:
                    meta_str = meta_str[:800] + "\n…(truncated)"
                parts.append(f"```\n{meta_str}\n```")
            except Exception:
                pass

        parts.append(f"_{timestamp}_")
        text = "\n\n".join(parts)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "MarkdownV2",
                        "disable_web_page_preview": True,
                    },
                )
                if response.status_code == 200:
                    logger.debug(f"Telegram alert sent ({severity}): {message[:60]}")
                    return True
                else:
                    logger.warning(f"Telegram API error {response.status_code}: {response.text[:200]}")
                    return False
        except Exception as exc:
            logger.warning(f"TelegramNotifier: failed to send message: {exc}")
            return False


def _escape_md(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))
