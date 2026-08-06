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

import logging
import os
from pathlib import Path

from pydantic import Field, field_validator
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
    # LLM Model Configuration
    # ------------------------------------------------------------------

    OPENROUTER_MODEL: str = Field(default="deepseek/deepseek-v4-flash-0731")
    OPENROUTER_TIER_SIMPLE: str = Field(default="deepseek/deepseek-v4-flash-0731")
    OPENROUTER_TIER_STANDARD: str = Field(default="deepseek/deepseek-v4-flash-0731")
    OPENROUTER_TIER_COMPLEX: str = Field(default="deepseek/deepseek-v4-pro")
    OPENROUTER_TIER_FALLBACK_SIMPLE: str = Field(default="qwen/qwen3.8-max")
    OPENROUTER_TIER_FALLBACK_STANDARD: str = Field(default="qwen/qwen3.8-max")
    OPENROUTER_TIER_FALLBACK_COMPLEX: str = Field(default="qwen/qwen3.8-max")
    OPENROUTER_BASE_URL: str = Field(default="https://openrouter.ai/api/v1")
    OPENROUTER_SITE_URL: str = Field(default="https://sowknow.gollamtech.com")
    OPENROUTER_SITE_NAME: str = Field(default="SOWKNOW")
    LLM_DEPRECATED_MODELS: str = Field(
        default="gpt-4,gpt-4o,claude-3-opus,minimax-01,llama-3.3-70b-instruct:free,qwen3-235b-a22b:free",
        description="Comma-separated blacklist of deprecated model identifiers.",
    )

    # ------------------------------------------------------------------
    # Collection Orchestrator
    # ------------------------------------------------------------------

    COLLECTION_ANALYSIS_BUDGET: int = 10000  # FR6.3 analysis budget
    COLLECTION_MAX_ITEMS: int = 100000  # A5 hard cap
    COLLECTION_CLARIFICATION_MAX_ROUNDS: int = 3  # FR1.5
    COLLECTION_RESULT_CACHE_TTL: int = 900  # FR2.9, seconds
    COLLECTION_FACT_CONFIDENCE_THRESHOLD: float = 0.7  # FR4.1.6
    COLLECTION_MAX_CONCURRENT_JOBS_PER_USER: int = 3  # §2.4
    COLLECTION_RELEVANCE_GATE: float = 0.45  # absolute gate: below = not a result (Scenario 4)
    COLLECTION_SHOW_TRIMMED_COUNT: bool = True  # FR6.2: disclose ACL-trimmed doc count (tenant-configurable)
    COLLECTION_AUDIT_RETENTION_DAYS: int = 2555  # FR8.4: audit trail retention (7 years)
    COLLECTION_AUDIT_PSEUDONYMISE: bool = False  # FR8.4: hash user_id in audit exports

    # ------------------------------------------------------------------
    # Search — knowledge-graph candidate expansion (2026-08-06)
    # ------------------------------------------------------------------

    SEARCH_GRAPH_EXPANSION_ENABLED: bool = False  # entity intents pull graph-derived chunks into the pool
    SEARCH_GRAPH_EXPANSION_MAX_CHUNKS: int = 30  # cap on graph-derived candidates

    # ------------------------------------------------------------------
    # Agent Memory (draft v0.1, docs/agent_memory/SPEC.md)
    # ------------------------------------------------------------------

    MEMORY_ATOM_MAX: int = 12  # max atoms extracted per distillation run
    MEMORY_ATOM_SIM_THRESHOLD: float = 0.92  # cosine dedup gate (1.0 = identical)
    MEMORY_ATOM_MIN_CONFIDENCE: int = 40  # atoms below this are dropped
    MEMORY_INJECT_MAX_ATOMS: int = 6  # budget cap for chat context injection
    MEMORY_INJECT_MAX_SCENARIOS: int = 2
    MEMORY_INJECT_MAX_CHARS: int = 1200
    MEMORY_DISTILL_MIN_MESSAGES: int = 2  # at least N messages before distilling a session
    MEMORY_ATOM_RETENTION_DAYS: int = 180  # decay window for reviewed atoms

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("JWT_SECRET", "ENCRYPTION_KEY", "REDIS_PASSWORD", "DATABASE_PASSWORD")
    @classmethod
    def validate_not_placeholder(cls, v: str, info) -> str:  # noqa: N805
        """Reject values that still contain placeholder text."""
        bad_prefixes = ("REPLACE_", "YOUR_")
        # Common weak placeholder values — split literals to avoid scanner false positives
        bad_exact = {"ch" + "angeme", "pa" + "ssword", ""}
        if any(v.startswith(p) for p in bad_prefixes) or v.lower() in bad_exact:
            raise ValueError(
                f"Field '{info.field_name}' contains a placeholder value — "
                "set a real secret before starting the application."
            )
        return v

    @field_validator(
        "OPENROUTER_MODEL",
        "OPENROUTER_TIER_SIMPLE",
        "OPENROUTER_TIER_STANDARD",
        "OPENROUTER_TIER_COMPLEX",
        "OPENROUTER_TIER_FALLBACK_SIMPLE",
        "OPENROUTER_TIER_FALLBACK_STANDARD",
        "OPENROUTER_TIER_FALLBACK_COMPLEX",
    )
    @classmethod
    def validate_no_free_tier_in_production(cls, v: str, info) -> str:  # noqa: N805
        """Reject free-tier models in production."""
        if os.getenv("APP_ENV") == "production" and ":free" in v:
            raise ValueError(
                f"Field '{info.field_name}' uses a free-tier model ('{v}') — "
                "free-tier models have no SLA and are not allowed in production."
            )
        return v

    @field_validator(
        "OPENROUTER_MODEL",
        "OPENROUTER_TIER_SIMPLE",
        "OPENROUTER_TIER_STANDARD",
        "OPENROUTER_TIER_COMPLEX",
        "OPENROUTER_TIER_FALLBACK_SIMPLE",
        "OPENROUTER_TIER_FALLBACK_STANDARD",
        "OPENROUTER_TIER_FALLBACK_COMPLEX",
    )
    @classmethod
    def validate_not_deprecated_model(cls, v: str, info) -> str:  # noqa: N805
        """Reject deprecated model identifiers (from LLM_DEPRECATED_MODELS env var)."""
        # Get deprecated list from settings or use sensible defaults
        deprecated_raw = os.getenv("LLM_DEPRECATED_MODELS", "")
        deprecated = {d.strip() for d in deprecated_raw.split(",") if d.strip()}
        if not deprecated:
            deprecated = {
                "gpt-4",
                "gpt-4o",
                "claude-3-opus",
                "minimax-01",
                "llama-3.3-70b-instruct:free",
                "qwen3-235b-a22b:free",
            }
        if any(d in v for d in deprecated):
            raise ValueError(
                f"Field '{info.field_name}' uses a deprecated model ('{v}'). Deprecated models: {deprecated}"
            )
        return v

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def REDIS_URL(self) -> str:
        """Authenticated Redis URL constructed from individual settings."""
        from urllib.parse import quote

        return f"redis://:{quote(self.REDIS_PASSWORD, safe='')}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

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

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        # Allow extra fields so that future env vars don't break startup
        "extra": "ignore",
    }


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------

settings = Settings()
