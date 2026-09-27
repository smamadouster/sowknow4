"""Redis pub/sub progress events for Smart Folder generation.

The Celery worker publishes real pipeline progress to a per-stream channel;
the FastAPI SSE endpoint subscribes to that channel and forwards events to
the browser.

Redis pub/sub is fire-and-forget: a subscriber only receives messages
published *after* it subscribes.  The SSE endpoint therefore mints the
stream key up front, subscribes, and only then dispatches the Celery task.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "smart_folder:progress"


def channel_for(stream_key: str) -> str:
    """Return the pub/sub channel name for a given stream key."""
    return f"{CHANNEL_PREFIX}:{stream_key}"


async def publish_event(channel: str, event: str, **payload: Any) -> None:
    """Publish a single event to a Redis pub/sub channel.

    Best-effort only: a Redis hiccup must never fail an in-flight Smart
    Folder generation, so all errors are swallowed (logged at debug).
    """
    try:
        import redis.asyncio as redis

        from app.core.redis_url import safe_redis_url

        client = redis.from_url(
            safe_redis_url(),
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
        )
        message = json.dumps({"event": event, **payload}, default=str)
        await client.publish(channel, message)
        await client.close()
    except Exception as exc:  # noqa: BLE001 - best effort only
        logger.debug("Smart Folder progress publish skipped (%s): %s", channel, exc)


async def publish_step(channel: str, step: str, message: str, progress_percent: int) -> None:
    """Publish a pipeline step event."""
    await publish_event(
        channel,
        "step",
        step=step,
        message=message,
        progress_percent=progress_percent,
    )
