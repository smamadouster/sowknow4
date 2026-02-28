"""
Unified alert service with severity-based routing.

Severity → channels mapping:
  CRITICAL  →  Telegram + Email
  HIGH      →  Telegram
  MEDIUM    →  Telegram
  LOW       →  (logged only, no external notification)
  INFO      →  (logged only)

Usage:
    from app.services.alert_service import alert_service
    await alert_service.send_alert("Task failed", severity="HIGH", metadata={...})
"""

import logging

from app.services.email_notifier import EmailNotifier
from app.services.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)

# Severity → list of channels that should receive the alert
_CHANNEL_MAP: dict[str, list[str]] = {
    "CRITICAL": ["telegram", "email"],
    "HIGH": ["telegram"],
    "MEDIUM": ["telegram"],
    "LOW": [],
    "INFO": [],
}


class AlertService:
    """Route alerts to the appropriate notification channels based on severity."""

    def __init__(self):
        self._telegram = TelegramNotifier()
        self._email = EmailNotifier()

    async def send_alert(
        self,
        message: str,
        severity: str = "INFO",
        title: str | None = None,
        metadata: dict | None = None,
    ) -> dict[str, bool]:
        """
        Send an alert to all channels appropriate for the given severity.

        Args:
            message:  Human-readable description of the event.
            severity: CRITICAL / HIGH / MEDIUM / LOW / INFO.
            title:    Short summary used as email subject and Telegram title.
            metadata: Optional context dict (document_id, task_id, etc.)

        Returns:
            Dict of channel → success flag, e.g. {"telegram": True, "email": False}
        """
        severity = severity.upper()
        channels = _CHANNEL_MAP.get(severity, [])
        results: dict[str, bool] = {}

        subject = title or message[:80]

        for channel in channels:
            try:
                if channel == "telegram":
                    ok = await self._telegram.send_alert(
                        message=message,
                        severity=severity,
                        metadata=metadata,
                        title=title,
                    )
                    results["telegram"] = ok
                elif channel == "email":
                    ok = await self._email.send_alert(
                        subject=subject,
                        message=message,
                        severity=severity,
                        metadata=metadata,
                    )
                    results["email"] = ok
            except Exception as exc:
                logger.error(f"AlertService: channel '{channel}' raised: {exc}")
                results[channel] = False

        # Always log, regardless of external delivery
        log_fn = logger.critical if severity == "CRITICAL" else (logger.error if severity == "HIGH" else logger.warning)
        log_fn(f"[ALERT/{severity}] {subject} | channels={list(results.keys())} | results={results}")

        return results

    async def send_task_failure_alert(
        self,
        task_name: str,
        task_id: str,
        exception: str,
        retry_count: int = 0,
        extra_metadata: dict | None = None,
    ) -> dict[str, bool]:
        """Convenience method for task failure alerts (always HIGH severity)."""
        metadata = {
            "task_name": task_name,
            "task_id": task_id,
            "exception": exception[:300],
            "retry_count": retry_count,
            **(extra_metadata or {}),
        }
        return await self.send_alert(
            message=f"Task '{task_name}' failed permanently after {retry_count} retries.",
            severity="HIGH",
            title=f"Task Failure: {task_name}",
            metadata=metadata,
        )

    async def send_anomaly_alert(
        self,
        anomaly_type: str,
        details: str,
        severity: str = "MEDIUM",
        metadata: dict | None = None,
    ) -> dict[str, bool]:
        """Convenience method for anomaly detection alerts."""
        return await self.send_alert(
            message=details,
            severity=severity,
            title=f"Anomaly: {anomaly_type}",
            metadata=metadata,
        )

    @property
    def telegram_configured(self) -> bool:
        """True when Telegram notifier is enabled and configured."""
        return self._telegram.is_configured

    @property
    def email_configured(self) -> bool:
        """True when email notifier is enabled and configured."""
        return self._email.is_configured


# Module-level singleton
alert_service = AlertService()
