import os
from collections.abc import AsyncGenerator
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://sowknow:sowknow@localhost:5432/sowknow")

# Rewrite URL to use asyncpg driver
if DATABASE_URL.startswith("sqlite"):
    # SQLite: use aiosqlite for async (test environment only)
    _async_db_url = DATABASE_URL.replace("sqlite://", "sqlite+aiosqlite://", 1)
    _is_sqlite = True
else:
    _async_db_url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://").replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    _is_sqlite = False

# Async engine with pgvector support and connection pooling
# SQLite (test) does not support pool_size/max_overflow
engine = create_async_engine(
    _async_db_url,
    pool_pre_ping=not _is_sqlite,
    **({} if _is_sqlite else {"pool_recycle": 300, "pool_size": 10, "max_overflow": 20}),
)

# Async session factory — expire_on_commit=False avoids lazy-load errors
# after commit in async contexts
AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

# Synchronous engine + session for Celery workers (no async event loop available).
_sync_db_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace(
    "postgresql+psycopg2://", "postgresql://"
)
# SQLite does not support pool_size / max_overflow — use minimal kwargs for test environments
_sync_engine_kwargs: dict = {"pool_pre_ping": True}
if not _sync_db_url.startswith("sqlite"):
    _sync_engine_kwargs.update({"pool_recycle": 300, "pool_size": 5, "max_overflow": 10})
sync_engine = create_engine(_sync_db_url, **_sync_engine_kwargs)
SessionLocal = sessionmaker(sync_engine, expire_on_commit=False)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async dependency to get database session."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_pgvector() -> None:
    """Initialize pgvector extension if not exists (PostgreSQL only)."""
    if "sqlite" in _async_db_url:
        return
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


async def create_all_tables() -> None:
    """Create all tables defined in SQLAlchemy metadata."""
    from app.models.base import Base as ModelBase  # noqa: F401 — triggers model imports

    async with engine.begin() as conn:
        await conn.run_sync(ModelBase.metadata.create_all)


def get_vector_type() -> Any:
    """Get the vector type from pgvector."""
    from pgvector.sqlalchemy import Vector

    return Vector
