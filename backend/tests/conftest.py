"""
Test configuration and fixtures for pytest
"""
import pytest
import os
from typing import Generator, Dict
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models.base import Base
from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.utils.security import create_access_token, get_password_hash


# Test database URL
TEST_DATABASE_URL = "sqlite:///./test.db"

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


@pytest.fixture(scope="function")
def client(db: Session) -> Generator[TestClient, None, None]:
    """Create a test client with database override"""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db: Session) -> User:
    """Create a test user"""
    user = User(
        email="test@example.com",
        hashed_password="hashed_password",
        full_name="Test User",
        role=UserRole.USER,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_user(db: Session) -> User:
    """Create an admin user"""
    user = User(
        email="admin@example.com",
        hashed_password="hashed_password",
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
def test_document(db: Session) -> Document:
    """Create a test document"""
    document = Document(
        filename="test_document.pdf",
        original_filename="test_document.pdf",
        file_path="/data/public/test_document.pdf",
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
def auth_headers(client: TestClient, test_user: User) -> dict:
    """Get authentication headers for test user"""
    # Login and get token
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": test_user.email,
            "password": "test_password"
        }
    )

    if response.status_code == 200:
        data = response.json()
        token = data.get("access_token")
        if token:
            return {"Authorization": f"Bearer {token}"}

    return {}


@pytest.fixture
def superuser(db: Session) -> User:
    """Create a superuser for testing"""
    user = User(
        email="superuser@example.com",
        hashed_password=get_password_hash("super_password"),
        full_name="Super User",
        role=UserRole.SUPERUSER,
        is_active=True,
        is_superuser=True,
        can_access_confidential=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def regular_user(db: Session) -> User:
    """Create a regular user for testing"""
    user = User(
        email="user@example.com",
        hashed_password=get_password_hash("user_password"),
        full_name="Regular User",
        role=UserRole.USER,
        is_active=True
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
def user_headers(regular_user: User) -> dict:
    """Get authentication headers for regular user"""
    return get_auth_headers_for_user(regular_user)


@pytest.fixture
def superuser_headers(superuser: User) -> dict:
    """Get authentication headers for superuser"""
    return get_auth_headers_for_user(superuser)


@pytest.fixture
def admin_headers(admin_user: User) -> dict:
    """Get authentication headers for admin user"""
    return get_auth_headers_for_user(admin_user)
