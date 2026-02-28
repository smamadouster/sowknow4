"""
Safe Redis URL builder.

REDIS_URL is composed by docker-compose string interpolation:
  redis://:${REDIS_PASSWORD}@redis:6379/0

When REDIS_PASSWORD contains special characters (@ / *), the resulting
URL is not a valid RFC-3986 URI.  urllib.parse.urlparse — used internally
by redis-py, slowapi/limits, and Celery — mis-parses the netloc portion
and silently falls back to localhost:6379, causing ConnectionRefused.

This module rebuilds the URL from REDIS_PASSWORD with proper
percent-encoding so every client gets a parseable URI.
"""

import os
from urllib.parse import quote


def safe_redis_url(default_host: str = "redis") -> str:
    """Return a properly percent-encoded Redis URL."""
    password = os.getenv("REDIS_PASSWORD", "")
    host = os.getenv("REDIS_HOST", default_host)
    port = os.getenv("REDIS_PORT", "6379")
    db = os.getenv("REDIS_DB", "0")
    if password:
        return f"redis://:{quote(password, safe='')}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"
