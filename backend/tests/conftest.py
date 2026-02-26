"""
Test configuration and fixtures for pytest

Integration tests that require a real PostgreSQL instance with the pgvector
extension use testcontainers (see tests/performance/conftest.py).  Those
fixtures seed the database with 50 public documents and 10 confidential
documents using 1024-dim normalised random embeddings so that pgvector
similarity-search benchmarks run against realistic data volumes.

For unit tests this file provides SQLite-backed fixtures.
For performance benchmarks import from tests/performance/conftest.py which
spins up a DockerContainer (testcontainers.postgres.PostgresContainer) with
the pgvector/pgvector:pg16 image and enables the vector extension.
"""

import pytest
import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["APP_ENV"] = "development"

from typing import Generator, Dict
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker, Session

# ---------------------------------------------------------------------------
# Full-stack imports — only available when all Docker dependencies are
# installed (asyncpg, slowapi, etc.).  Unit tests still run without them.
# ---------------------------------------------------------------------------
try:
    from fastapi.testclient import TestClient
    from app.models.base import Base
    from app.models.user import User, UserRole
    from app.models.document import Document, DocumentBucket, DocumentStatus
    from app.utils.security import create_access_token, get_password_hash
    from app.main import app
    from app.database import get_db
    _FULL_STACK_AVAILABLE = True
except (ImportError, Exception):
    # Full-stack dependencies (slowapi, asyncpg, etc.) not installed.
    # Unit tests that don't require a database/application context still run.
    _FULL_STACK_AVAILABLE = False
    app = None
    get_db = None
    Base = None
    TestClient = None


# Test database URL
TEST_DATABASE_URL = "sqlite:///./test.db"

# Create test engine with proper UUID handling (only when full stack is available)
test_engine = (
    create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if _FULL_STACK_AVAILABLE
    else None
)


if _FULL_STACK_AVAILABLE:
    # Remove schema from all tables for SQLite compatibility
    # and replace PostgreSQL-specific types
    @event.listens_for(Base.metadata, "before_create")
    def remove_schema(metadata, connection, **kw):
        from sqlalchemy import JSON, Text

        for table in metadata.tables.values():
            table.schema = None
            for column in table.columns:
                col_type = type(column.type).__name__
                if col_type == "JSONB":
                    column.type = JSON()
                elif col_type == "Vector":
                    column.type = Text()
                elif col_type == "ARRAY":
                    column.type = Text()


TestingSessionLocal = (
    sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    if _FULL_STACK_AVAILABLE
    else None
)


@pytest.fixture(scope="function")
def db() -> Generator[Session, None, None]:
    """Create a fresh database for each test"""
    if not _FULL_STACK_AVAILABLE:
        pytest.skip("Full-stack dependencies not available (requires Docker environment)")
    # Drop any leftover tables from interrupted previous runs, then create fresh
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    # Create session
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        # Drop tables after test
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db: Session) -> Generator:
    """Create a test client with database override"""
    if not _FULL_STACK_AVAILABLE:
        pytest.skip("Full-stack dependencies not available (requires Docker environment)")

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db: Session) -> "User":
    """Create a test user"""
    user = User(
        email="test@example.com",
        hashed_password="hashed_password",
        full_name="Test User",
        role=UserRole.USER,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_user(db: Session) -> "User":
    """Create an admin user"""
    user = User(
        email="admin@example.com",
        hashed_password="hashed_password",
        full_name="Admin User",
        role=UserRole.ADMIN,
        is_superuser=True,
        can_access_confidential=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def test_document(db: Session) -> "Document":
    """Create a test document"""
    document = Document(
        filename="test_document.pdf",
        original_filename="test_document.pdf",
        file_path="/data/public/test_document.pdf",
        bucket=DocumentBucket.PUBLIC,
        status=DocumentStatus.INDEXED,
        size=1024,
        mime_type="application/pdf",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


@pytest.fixture
def auth_headers(client, test_user: "User") -> dict:
    """
    Get authentication headers for test user.

    Returns Bearer token headers for the test_user.
    Compatible with both cookie-based and header-based auth flows.
    """
    return get_auth_headers_for_user(test_user)


@pytest.fixture
def superuser(db: Session) -> "User":
    """Create a superuser for testing"""
    user = User(
        email="superuser@example.com",
        hashed_password=get_password_hash("super_password"),
        full_name="Super User",
        role=UserRole.SUPERUSER,
        is_active=True,
        is_superuser=True,
        can_access_confidential=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def regular_user(db: Session) -> "User":
    """Create a regular user for testing"""
    user = User(
        email="user@example.com",
        hashed_password=get_password_hash("user_password"),
        full_name="Regular User",
        role=UserRole.USER,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def public_document(db: Session) -> "Document":
    """Create a public test document"""
    document = Document(
        filename="public_document.pdf",
        original_filename="public_document.pdf",
        file_path="/data/public/public_document.pdf",
        bucket=DocumentBucket.PUBLIC,
        status=DocumentStatus.INDEXED,
        size=1024,
        mime_type="application/pdf",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


@pytest.fixture
def confidential_document(db: Session) -> "Document":
    """Create a confidential test document"""
    document = Document(
        filename="confidential_document.pdf",
        original_filename="confidential_document.pdf",
        file_path="/data/confidential/confidential_document.pdf",
        bucket=DocumentBucket.CONFIDENTIAL,
        status=DocumentStatus.INDEXED,
        size=1024,
        mime_type="application/pdf",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def get_auth_headers_for_user(user: "User") -> Dict[str, str]:
    """Helper to create auth headers for a user"""
    token = create_access_token(
        data={"sub": user.email, "role": user.role.value, "user_id": str(user.id)}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers(regular_user: "User") -> dict:
    """Get authentication headers for regular user"""
    return get_auth_headers_for_user(regular_user)


@pytest.fixture
def superuser_headers(superuser: "User") -> dict:
    """Get authentication headers for superuser"""
    return get_auth_headers_for_user(superuser)


@pytest.fixture
def admin_headers(admin_user: "User") -> dict:
    """Get authentication headers for admin user"""
    return get_auth_headers_for_user(admin_user)
