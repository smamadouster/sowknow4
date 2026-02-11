"""
Security test configuration with minimal dependencies.

This conftest provides fixtures for security testing without requiring
the full application to load.
"""
import pytest
import os
import uuid
from typing import Generator, Dict
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from unittest.mock import Mock, MagicMock

# Set test environment variables before importing anything
os.environ["JWT_SECRET"] = "test-secret-key-for-security-testing-only"
os.environ["DATABASE_URL"] = "sqlite:///./test_security.db"
os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"

from app.models.base import Base
from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.utils.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    decode_token
)

# Test database URL
TEST_DATABASE_URL = "sqlite:///./test_security.db"

# Create test engine
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False}
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db() -> Generator[Session, None, None]:
    """Create a fresh database for each test"""
    # Create tables
    Base.metadata.create_all(bind=test_engine)

    # Create session
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        # Drop tables after test
        Base.metadata.drop_all(bind=test_engine)

        # Delete test database file
        try:
            if os.path.exists(TEST_DATABASE_URL.replace("sqlite:///", "")):
                os.remove(TEST_DATABASE_URL.replace("sqlite:///", ""))
        except:
            pass


@pytest.fixture(scope="function")
def test_password() -> str:
    """Test password for users"""
    return "TestPassword123!"


@pytest.fixture
def admin_user(db: Session, test_password: str) -> User:
    """Create an admin user"""
    user = User(
        email="admin@test.com",
        hashed_password=get_password_hash(test_password),
        full_name="Admin User",
        role=UserRole.ADMIN,
        is_superuser=True,
        can_access_confidential=True,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def superuser(db: Session, test_password: str) -> User:
    """Create a superuser"""
    user = User(
        email="super@test.com",
        hashed_password=get_password_hash(test_password),
        full_name="Super User",
        role=UserRole.SUPERUSER,
        is_superuser=True,
        can_access_confidential=True,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def regular_user(db: Session, test_password: str) -> User:
    """Create a regular user"""
    user = User(
        email="user@test.com",
        hashed_password=get_password_hash(test_password),
        full_name="Regular User",
        role=UserRole.USER,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def inactive_user(db: Session, test_password: str) -> User:
    """Create an inactive user"""
    user = User(
        email="inactive@test.com",
        hashed_password=get_password_hash(test_password),
        full_name="Inactive User",
        role=UserRole.USER,
        is_active=False
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def public_document(db: Session) -> Document:
    """Create a public test document"""
    document = Document(
        filename="public_document.pdf",
        original_filename="public_document.pdf",
        file_path="/data/public/public_document.pdf",
        bucket=DocumentBucket.PUBLIC,
        status=DocumentStatus.INDEXED,
        size=1024,
        mime_type="application/pdf"
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


@pytest.fixture
def confidential_document(db: Session) -> Document:
    """Create a confidential test document"""
    document = Document(
        filename="confidential_document.pdf",
        original_filename="confidential_document.pdf",
        file_path="/data/confidential/confidential_document.pdf",
        bucket=DocumentBucket.CONFIDENTIAL,
        status=DocumentStatus.INDEXED,
        size=1024,
        mime_type="application/pdf"
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def get_auth_headers_for_user(user: User) -> Dict[str, str]:
    """Helper to create auth headers for a user"""
    token = create_access_token(data={
        "sub": user.email,
        "role": user.role.value,
        "user_id": str(user.id)
    })
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(admin_user: User) -> dict:
    """Get authentication headers for admin user"""
    return get_auth_headers_for_user(admin_user)


@pytest.fixture
def superuser_headers(superuser: User) -> dict:
    """Get authentication headers for superuser"""
    return get_auth_headers_for_user(superuser)


@pytest.fixture
def user_headers(regular_user: User) -> dict:
    """Get authentication headers for regular user"""
    return get_auth_headers_for_user(regular_user)


@pytest.fixture
def expired_token(regular_user: User) -> str:
    """Create an expired token for testing"""
    from datetime import datetime, timedelta

    expire = datetime.utcnow() - timedelta(minutes=15)
    from jose import jwt
    from app.utils.security import SECRET_KEY, ALGORITHM

    payload = {
        "sub": regular_user.email,
        "role": regular_user.role.value,
        "user_id": str(regular_user.id),
        "exp": expire
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


@pytest.fixture
def tampered_token(regular_user: User) -> str:
    """Create a tampered token for testing"""
    valid_token = create_access_token(data={
        "sub": regular_user.email,
        "role": regular_user.role.value,
        "user_id": str(regular_user.id)
    })

    # Tamper with the token (change a character)
    return valid_token[:-5] + "ABCDE"
