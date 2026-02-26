"""
Shared slowapi Limiter instance (T04).
Import this in both main.py and router files.
"""
import os
from slowapi import Limiter
from slowapi.util import get_remote_address

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

limiter = Limiter(key_func=get_remote_address, storage_uri=REDIS_URL)
