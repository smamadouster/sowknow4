"""
Shared slowapi Limiter instance (T04).
Import this in both main.py and router files.
"""
import os
from urllib.parse import quote
from slowapi import Limiter
from slowapi.util import get_remote_address


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


REDIS_URL = _limiter_redis_url()

limiter = Limiter(key_func=get_remote_address, storage_uri=REDIS_URL)
