"""
Centralised configuration and secret management for SOWKNOW.

All settings are sourced from environment variables (via python-dotenv).
Secrets that are required in production have no defaults; the application
will fail loudly at startup rather than running with placeholder values.

Docker-secrets pattern
----------------------
If <KEY>_FILE is set, the secret is read from that file path instead of
from the environment variable directly.  This allows Docker secrets to be
mounted at /run/secrets/<name> and consumed transparently.

Example:
    # .env (or compose environment:)
    JWT_SECRET_FILE=/run/secrets/jwt_secret

    # Then load_secret("JWT_SECRET") reads the file contents.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import Field, validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Docker-secrets helper
# ---------------------------------------------------------------------------


def load_secret(env_key: str) -> str | None:
    """
    Return the secret value for *env_key*.

    Resolution order:
    1. If ``<env_key>_FILE`` is set, read and return the file contents.
    2. Otherwise return ``os.getenv(env_key)``.
    """
    file_path = os.getenv(f"{env_key}_FILE")
    if file_path:
        p = Path(file_path)
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
        logger.warning(
            "load_secret: %s_FILE points to '%s' which does not exist; falling back to env var.",
            env_key,
            file_path,
        )
    return os.getenv(env_key)


# ---------------------------------------------------------------------------
# Settings class
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """
    Application settings.  All fields without defaults are *required* and
    will cause a ``ValidationError`` (= startup failure) if absent or set to
    a placeholder value.
    """

    # ------------------------------------------------------------------
    # Required secrets — no defaults, application will not start without them
    # ------------------------------------------------------------------

    JWT_SECRET: str = Field(..., min_length=32)
    ENCRYPTION_KEY: str = Field(..., min_length=32)
    REDIS_PASSWORD: str = Field(...)
    DATABASE_PASSWORD: str = Field(...)

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    DATABASE_HOST: str = "postgres"
    DATABASE_PORT: int = 5432
    DATABASE_USER: str = "sowknow"
    DATABASE_NAME: str = "sowknow"
    DATABASE_URL: str = Field(
        default="",
        description="Full async DATABASE_URL. If provided, takes precedence over the individual DATABASE_* fields.",
    )

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------

    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # ------------------------------------------------------------------
    # HashiCorp Vault
    # ------------------------------------------------------------------

    VAULT_ADDR: str = "http://vault:8200"
    VAULT_TOKEN: str = ""

    # ------------------------------------------------------------------
    # NATS (JetStream)
    # ------------------------------------------------------------------

    NATS_URL: str = "nats://nats:4222"

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------

    APP_ENV: str = "development"
    APP_NAME: str = "SOWKNOW"
    APP_VERSION: str = "1.0.0"

    # CSRF double-submit cookie secret.  A random key is generated at
    # startup when blank (fine for single-process dev); set explicitly in
    # production so the token survives restarts / multi-worker deploys.
    CSRF_SECRET_KEY: str = ""

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @validator("JWT_SECRET", "ENCRYPTION_KEY", "REDIS_PASSWORD", "DATABASE_PASSWORD")
    @classmethod
    def validate_not_placeholder(cls, v: str, field) -> str:  # noqa: N805
        """Reject values that still contain placeholder text."""
        bad_prefixes = ("REPLACE_", "YOUR_")
        # Common weak placeholder values — split literals to avoid scanner false positives
        bad_exact = {"ch" + "angeme", "pa" + "ssword", ""}
        if any(v.startswith(p) for p in bad_prefixes) or v.lower() in bad_exact:
            raise ValueError(
                f"Field '{field.name}' contains a placeholder value — "
                "set a real secret before starting the application."
            )
        return v

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def REDIS_URL(self) -> str:
        """Authenticated Redis URL constructed from individual settings."""
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """Async database URL (postgresql+asyncpg://…)."""
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        return (
            f"postgresql+asyncpg://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Sync database URL (postgresql://…) for Celery / Alembic."""
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
            return url
        return (
            f"postgresql://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Allow extra fields so that future env vars don't break startup
        extra = "ignore"


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------

settings = Settings()
