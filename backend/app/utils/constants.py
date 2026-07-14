"""
Shared constants for SOWKNOW backend.

Cookie names, token types, and other values that must be consistent
across auth.py, deps.py, and middleware layers.
"""

import os

# Environment-based configuration (mirrors backend/app/api/auth.py)
_ENVIRONMENT = os.getenv("APP_ENV", "development").lower()
_SECURE_FLAG = _ENVIRONMENT == "production"


def _prefixed_cookie_name(base: str, host_prefix: bool = False) -> str:
    """
    Return the cookie name used at runtime.

    In production we apply browser security prefixes:
      - __Host- requires Secure, Path=/ and no Domain attribute.
      - __Secure- requires Secure but allows Path/Domain restrictions.

    Development runs over plain HTTP, so prefixed cookies would be rejected;
    we keep the legacy names there.
    """
    if not _SECURE_FLAG:
        return base
    if host_prefix:
        return f"__Host-{base}"
    return f"__Secure-{base}"


# Cookie names — single source of truth
COOKIE_ACCESS_TOKEN_NAME = _prefixed_cookie_name("access_token", host_prefix=True)
COOKIE_REFRESH_TOKEN_NAME = _prefixed_cookie_name("refresh_token", host_prefix=False)

# CSRF double-submit cookie is not an auth token, but uses the same host-prefix
# rules in production (Path=/, Secure, no Domain).
CSRF_COOKIE_NAME = _prefixed_cookie_name("csrf_token", host_prefix=True)
