"""
Unit tests for AlertService, TelegramNotifier, and EmailNotifier.

All external calls (HTTP, SMTP) are mocked so no network access is required.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_BACKEND = str(Path(__file__).parent.parent.parent.parent / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("APP_ENV", "test")


# ---------------------------------------------------------------------------
# TelegramNotifier
# ---------------------------------------------------------------------------


def test_telegram_notifier_is_configured_false_without_token():
    """TelegramNotifier.is_configured returns False when env vars are absent."""
    with (
        patch.dict(os.environ, {}, clear=False),
    ):
        # Temporarily remove Telegram env vars if present
        env_backup = {
            k: os.environ.pop(k)
            for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_CHAT_ID")
            if k in os.environ
        }
        try:
            # Re-import to pick up env changes
            import importlib
            import app.services.telegram_notifier as mod
            importlib.reload(mod)
            notifier = mod.TelegramNotifier()
            assert not notifier.is_configured
        finally:
            os.environ.update(env_backup)


def test_telegram_notifier_is_configured_true_with_token():
    """TelegramNotifier.is_configured returns True when both env vars are present."""
    with patch.dict(
        os.environ,
        {"TELEGRAM_BOT_TOKEN": "test-bot-token", "TELEGRAM_ADMIN_CHAT_ID": "12345"},
    ):
        import importlib
        import app.services.telegram_notifier as mod
        importlib.reload(mod)
        notifier = mod.TelegramNotifier()
        assert notifier.is_configured


# ---------------------------------------------------------------------------
# EmailNotifier
# ---------------------------------------------------------------------------


def test_email_notifier_is_configured_false_without_api_key():
    """EmailNotifier.is_configured returns False when SENDGRID_API_KEY is absent."""
    env_backup = {k: os.environ.pop(k) for k in ("SENDGRID_API_KEY",) if k in os.environ}
    try:
        import importlib
        import app.services.email_notifier as mod
        importlib.reload(mod)
        notifier = mod.EmailNotifier()
        assert not notifier.is_configured
    finally:
        os.environ.update(env_backup)


def test_email_notifier_is_configured_true_with_api_key():
    """EmailNotifier.is_configured returns True when SENDGRID_API_KEY is set."""
    with patch.dict(
        os.environ,
        {
            "SENDGRID_API_KEY": "SG.test-key",
            "ALERT_FROM_EMAIL": "test@example.com",
            "ADMIN_EMAILS": "admin@example.com",
        },
    ):
        import importlib
        import app.services.email_notifier as mod
        importlib.reload(mod)
        notifier = mod.EmailNotifier()
        assert notifier.is_configured


# ---------------------------------------------------------------------------
# AlertService
# ---------------------------------------------------------------------------


def test_alert_service_telegram_configured_property():
    """AlertService.telegram_configured mirrors TelegramNotifier.is_configured."""
    from app.services.alert_service import AlertService

    service = AlertService.__new__(AlertService)
    mock_telegram = MagicMock()
    mock_telegram.is_configured = True
    mock_email = MagicMock()
    mock_email.is_configured = False
    service._telegram = mock_telegram
    service._email = mock_email

    assert service.telegram_configured is True
    assert service.email_configured is False


def test_alert_service_email_configured_property():
    """AlertService.email_configured mirrors EmailNotifier.is_configured."""
    from app.services.alert_service import AlertService

    service = AlertService.__new__(AlertService)
    mock_telegram = MagicMock()
    mock_telegram.is_configured = False
    mock_email = MagicMock()
    mock_email.is_configured = True
    service._telegram = mock_telegram
    service._email = mock_email

    assert service.email_configured is True
    assert service.telegram_configured is False


@pytest.mark.asyncio
async def test_alert_service_send_task_failure_alert():
    """AlertService.send_task_failure_alert should fire without raising."""
    from app.services.alert_service import AlertService

    service = AlertService.__new__(AlertService)
    mock_telegram = AsyncMock()
    mock_telegram.is_configured = False
    mock_telegram.send_alert = AsyncMock(return_value=True)
    mock_email = AsyncMock()
    mock_email.is_configured = False
    mock_email.send_alert = AsyncMock(return_value=True)
    service._telegram = mock_telegram
    service._email = mock_email

    # Should not raise even when notifiers are unconfigured
    try:
        await service.send_task_failure_alert(
            task_name="app.tasks.document_tasks.process_document",
            task_id="test-task-id",
            exception=RuntimeError("disk full"),
            retry_count=3,
        )
    except Exception as exc:
        pytest.fail(f"send_task_failure_alert raised unexpectedly: {exc}")
