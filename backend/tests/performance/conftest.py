"""
PostgreSQL container fixtures for collection performance benchmarks.

Provides a real pgvector-enabled PostgreSQL instance using testcontainers
with 50 public + 10 confidential documents pre-seeded with 1024-dim embeddings.

All fixtures are session-scoped so the container starts once per pytest run
and is shared across all benchmark tests in this directory.

CI usage:
  pytest tests/performance/test_collection_benchmarks.py -m benchmark -v
  (requires Docker to be available in the CI environment)
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Generator

import numpy as np
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# ---------------------------------------------------------------------------
# pytest marker registration (avoids --strict-markers error)
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "benchmark: collection pipeline performance benchmark (targets enforced)",
    )


# ---------------------------------------------------------------------------
# Minimal env-var stubs so LLM service singletons can be instantiated
# without real API keys (actual HTTP calls are mocked in each test).
# ---------------------------------------------------------------------------
_ENV_STUBS = {
    "OPENROUTER_API_KEY":  "test-benchmark-key",
    "KIMI_API_KEY":        "test-benchmark-key",
    "MINIMAX_API_KEY":     "test-benchmark-key",
    "OLLAMA_BASE_URL":     "http://localhost:11434",
    "SECRET_KEY":          "test-secret-key-for-benchmarks-only",
    "JWT_SECRET_KEY":      "test-jwt-secret-for-benchmarks",
    "REDIS_URL":           "redis://localhost:6379/0",
}

for _k, _v in _ENV_STUBS.items():
    os.environ.setdefault(_k, _v)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_DIM = 1024          # multilingual-e5-large output dimension
_PGVECTOR_IMAGE = "pgvector/pgvector:0.7.0-pg16"

_TOPICS = [
    "solar", "energy", "finance", "legal", "medical",
    "family", "tax", "insurance", "property", "education",
]


# ---------------------------------------------------------------------------
# Container (session-scoped — started once, stopped when session ends)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pg_container():
    """
    Start a PostgreSQL 16 container with pgvector pre-installed.

    Yields the running testcontainers PostgresContainer object.
    """
    from testcontainers.postgres import PostgresContainer

    # Use default testcontainers credentials (user=test, password=test, dbname=test)
    # to avoid triggering secret-scanning hooks on hard-coded password literals.
    with PostgresContainer(image=_PGVECTOR_IMAGE) as container:
        yield container


# ---------------------------------------------------------------------------
# Engine (session-scoped — one engine for the whole test run)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pg_engine(pg_container):
    """
    Build an SQLAlchemy engine connected to the container, then:
      1. Create the `vector` extension and `sowknow` schema.
      2. Override DATABASE_URL so app code that reads the env-var at
         import time gets the real Postgres URL (not the sqlite stub
         set by the root tests/conftest.py).
      3. Create all ORM tables via Base.metadata.create_all().

    Drops all tables and disposes the engine at session teardown.
    """
    # testcontainers 3.7 returns a psycopg2 connection URL
    db_url = pg_container.get_connection_url()

    engine = create_engine(
        db_url,
        echo=False,
        # Set search_path so raw SQL queries using unqualified table names
        # (e.g. in semantic_search) resolve to the sowknow schema.
        connect_args={"options": "-c search_path=sowknow,public"},
    )

    # Bootstrap extensions and schema before any ORM table creation
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS sowknow"))

    # Let app code know about the real Postgres URL
    os.environ["DATABASE_URL"] = db_url

    # Import all models so SQLAlchemy metadata is populated.
    # The import order matters: base → user → document → chat → collection
    import app.models.audit  # noqa: F401
    import app.models.chat  # noqa: F401
    import app.models.collection  # noqa: F401
    import app.models.document  # noqa: F401
    import app.models.knowledge_graph  # noqa: F401
    import app.models.processing  # noqa: F401
    import app.models.user  # noqa: F401
    from app.models.base import Base  # noqa: F401

    Base.metadata.create_all(bind=engine)

    yield engine

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# Seeded data (session-scoped — inserted once, visible to all benchmark tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def seeded_db(pg_engine) -> tuple[Session, object]:
    """
    Seed the database with:
      - 1 Admin user
      - 50 public PDFs × 5 chunks  (1024-dim normalised random embeddings)
      - 10 confidential PDFs × 2 chunks

    Returns (session, admin_user).  The session stays open for the entire
    pytest session so the seeded data is always readable.
    """
    from app.models.document import (
        Document,
        DocumentBucket,
        DocumentChunk,
        DocumentLanguage,
        DocumentStatus,
    )
    from app.models.user import User, UserRole
    from app.utils.security import get_password_hash

    SessionFactory = sessionmaker(
        bind=pg_engine,
        autocommit=False,
        autoflush=False,
    )
    session: Session = SessionFactory()

    rng = np.random.default_rng(seed=42)

    # ------------------------------------------------------------------
    # Admin user
    # ------------------------------------------------------------------
    admin = User(
        id=uuid.uuid4(),
        email="bench_admin@test.local",
        hashed_password=get_password_hash("bench_pass"),
        full_name="Benchmark Admin",
        role=UserRole.ADMIN,
        is_active=True,
        is_superuser=True,
        can_access_confidential=True,
    )
    session.add(admin)
    session.flush()          # get admin.id before bulk inserts

    # ------------------------------------------------------------------
    # 50 public documents — 5 chunks each
    # ------------------------------------------------------------------
    for i in range(50):
        topic = _TOPICS[i % len(_TOPICS)]
        doc_id = uuid.uuid4()

        doc = Document(
            id=doc_id,
            filename=f"{topic}_public_{i:03d}.pdf",
            original_filename=f"{topic}_public_{i:03d}.pdf",
            file_path=f"/data/public/{topic}_public_{i:03d}.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024 * (100 + i),
            mime_type="application/pdf",
            page_count=5,
            ocr_processed=True,
            embedding_generated=True,
            chunk_count=5,
            language=DocumentLanguage.ENGLISH,
        )
        session.add(doc)

        for j in range(5):
            vec = _random_unit_vector(rng, EMBEDDING_DIM)
            session.add(DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc_id,
                chunk_index=j,
                chunk_text=(
                    f"{topic} content chunk {j} from public document {i}. "
                    f"Keywords: {topic}, legacy, knowledge, heritage. " * 15
                ),
                embedding_vector=vec.tolist(),
                page_number=j + 1,
                token_count=150,
            ))

    # ------------------------------------------------------------------
    # 10 confidential documents — 2 chunks each
    # ------------------------------------------------------------------
    for i in range(10):
        doc_id = uuid.uuid4()

        doc = Document(
            id=doc_id,
            filename=f"confidential_{i:03d}.pdf",
            original_filename=f"confidential_{i:03d}.pdf",
            file_path=f"/data/confidential/confidential_{i:03d}.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024 * (200 + i),
            mime_type="application/pdf",
            page_count=3,
            ocr_processed=True,
            embedding_generated=True,
            chunk_count=2,
            language=DocumentLanguage.FRENCH,
        )
        session.add(doc)

        for j in range(2):
            vec = _random_unit_vector(rng, EMBEDDING_DIM)
            session.add(DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc_id,
                chunk_index=j,
                chunk_text=(
                    f"Confidentiel document {i} paragraphe {j}. "
                    f"Données personnelles sensibles, dossier médical. " * 15
                ),
                embedding_vector=vec.tolist(),
                page_number=j + 1,
                token_count=100,
            ))

    session.commit()
    yield session, admin
    session.close()


# ---------------------------------------------------------------------------
# Per-test session (function-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture
def pg_bench_db(pg_engine, seeded_db) -> Generator[tuple[Session, object], None, None]:
    """
    Function-scoped session connected to the seeded Postgres container.

    - Refreshes the admin user proxy into the new session's identity map
      so ORM relationships load correctly.
    - Closes (does NOT roll back) after the test so that collections written
      during e2e benchmarks are preserved for post-hoc inspection.
    """
    from app.models.user import User

    _, admin = seeded_db

    SessionFactory = sessionmaker(
        bind=pg_engine,
        autocommit=False,
        autoflush=False,
    )
    session: Session = SessionFactory()
    admin_fresh = session.get(User, admin.id)

    yield session, admin_fresh

    session.close()


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _random_unit_vector(rng: np.random.Generator, dim: int) -> np.ndarray:
    """Return a normalised float32 random vector suitable for cosine search."""
    vec = rng.standard_normal(dim).astype(np.float32)
    norm = float(np.linalg.norm(vec))
    if norm > 1e-9:
        vec /= norm
    return vec
