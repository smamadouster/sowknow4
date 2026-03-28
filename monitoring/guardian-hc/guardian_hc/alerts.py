import os
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
