"""
Shared slowapi Limiter instance (T04).
Import this in both main.py and router files.
"""

import os
from urllib.parse import quote

from slowapi import Limiter
from starlette.requests import Request


def _limiter_redis_url() -> str:
    """Build Redis URL for slowapi with URL-encoded password.

    REDIS_URL is built by docker-compose via string interpolation and may
    contain unencoded special characters (@ / *) in the password, which
    break urllib.parse.urlparse — causing slowapi to silently fall back to
    localhost:6379.  Reconstruct from individual env vars instead.
    """
    password = os.getenv("REDIS_PASSWORD", "")
    host = os.getenv("REDIS_HOST", "redis")
    port = os.getenv("REDIS_PORT", "6379")
    db = os.getenv("REDIS_DB", "0")
    if password:
        return f"redis://:{quote(password, safe='')}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"


def _get_client_ip(request: Request) -> str:
    """
    Return the real client IP for rate-limiting purposes.

    When the app is behind nginx, ``request.client.host`` is the internal
    proxy IP, so all users share a single rate-limit bucket.  Nginx forwards
    the original client IP in ``X-Forwarded-For``; use that when present.

    SEC-05: Direct backend access should be blocked at the network level
    (no host port mapping).  With that in place, ``X-Forwarded-For`` can be
    trusted as coming from nginx.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # nginx appends $remote_addr to any existing chain; the first entry is
        # the original client.  Take the first non-empty entry.
        for part in forwarded_for.split(","):
            ip = part.strip()
            if ip:
                return ip
    if request.client:
        return request.client.host
    return "unknown"


REDIS_URL = _limiter_redis_url()

limiter = Limiter(key_func=_get_client_ip, storage_uri=REDIS_URL)
