"""
Shared constants for SOWKNOW backend.

Cookie names, token types, and other values that must be consistent
across auth.py, deps.py, and middleware layers.
"""

# Cookie names — single source of truth
COOKIE_ACCESS_TOKEN_NAME = "access_token"
COOKIE_REFRESH_TOKEN_NAME = "refresh_token"
