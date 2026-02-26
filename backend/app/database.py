from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import AsyncAdaptedQueuePool
from typing import AsyncGenerator
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://sowknow:sowknow@localhost:5432/sowknow"
)

# Rewrite URL to use asyncpg driver
_async_db_url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://").replace(
    "postgresql+psycopg2://", "postgresql+asyncpg://"
)

# Async engine with pgvector support and connection pooling
engine = create_async_engine(
    _async_db_url,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=10,
    max_overflow=20,
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
sync_engine = create_engine(
    _sync_db_url,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=5,
    max_overflow=10,
)
SessionLocal = sessionmaker(sync_engine, expire_on_commit=False)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async dependency to get database session."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_pgvector():
    """Initialize pgvector extension if not exists (PostgreSQL only)."""
    if "sqlite" in _async_db_url:
        return
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


async def create_all_tables():
    """Create all tables defined in SQLAlchemy metadata."""
    from app.models.base import Base as ModelBase  # noqa: F401 — triggers model imports

    async with engine.begin() as conn:
        await conn.run_sync(ModelBase.metadata.create_all)


def get_vector_type():
    """Get the vector type from pgvector."""
    from pgvector.sqlalchemy import Vector

    return Vector
