# SOWKNOW Testing Guide

**Version**: 3.0.0 (Phase 3)
**Last Updated**: February 24, 2026
**Status**: Production Ready

---

## Table of Contents

1. [Testing Strategy](#testing-strategy)
2. [Test Environment Setup](#test-environment-setup)
3. [Running Tests](#running-tests)
4. [Test Structure](#test-structure)
5. [Writing Tests](#writing-tests)
6. [Test Coverage](#test-coverage)
7. [CI/CD Integration](#cicd-integration)
8. [Troubleshooting](#troubleshooting)

---

## Testing Strategy

SOWKNOW uses a comprehensive testing approach covering unit, integration, E2E, performance, and security tests.

### Test Pyramid

```
       ╔═══════════════════╗
       ║  E2E Tests        ║  (20%)
       ║  - Full workflows ║
       ║  - User scenarios ║
       ╠═══════════════════╣
       ║ Integration Tests ║  (30%)
       ║ - API endpoints   ║
       ║ - Database ops    ║
       ║ - Service chains  ║
       ╠═══════════════════╣
       ║  Unit Tests       ║  (50%)
       ║  - Functions      ║
       ║  - Services       ║
       ║  - Utilities      ║
       ╚═══════════════════╝
```

### Test Types & Coverage

| Test Type | Purpose | Tools | Frequency |
|-----------|---------|-------|-----------|
| Unit | Function/service logic | pytest, unittest.mock | Per commit |
| Integration | API + database flow | pytest-asyncio | Per commit |
| E2E | Full user workflows | pytest, curl | Before release |
| Performance | Latency/throughput | pytest-benchmark | Weekly |
| Security | Auth, SQL injection, XSS | pytest, bandit | Before release |
| Load | Concurrent users | locust, Apache JMeter | Monthly |

---

## Test Environment Setup

### 1. Prerequisites

```bash
# Install test dependencies
cd /root/development/src/active/sowknow4
pip install -r backend/requirements-test.txt

# Required packages:
# - pytest>=7.0
# - pytest-asyncio>=0.21
# - pytest-cov>=4.0
# - pytest-xdist>=3.0 (parallel execution)
# - pytest-timeout>=2.1
# - pytest-benchmark>=4.0
# - faker>=18.0 (test data generation)
# - responses>=0.22 (mock HTTP requests)
# - sqlalchemy[asyncio]>=2.0
```

### 2. Test Database Setup

Create separate test database:

```bash
# Create test database
docker-compose exec postgres createdb -U sowknow sowknow_test

# Initialize schema (run migrations)
export TEST_DATABASE_URL="postgresql://sowknow:${DATABASE_PASSWORD}@localhost:5432/sowknow_test"
docker-compose exec backend alembic upgrade head -x sqlalchemy.url=$TEST_DATABASE_URL

# Verify tables
docker-compose exec postgres psql -U sowknow sowknow_test -c "\dt"
```

### 3. Environment Configuration

Create `backend/tests/.env.test`:

```bash
# Database
TEST_DATABASE_URL=postgresql://sowknow:sowknow_test@postgres:5432/sowknow_test
DATABASE_URL=postgresql://sowknow:sowknow_test@postgres:5432/sowknow_test

# Redis
REDIS_URL=redis://redis:6379/1  # Use DB 1 for tests
REDIS_PASSWORD=sowknow_test

# JWT
JWT_SECRET=test_jwt_secret_64_characters_minimum_length

# LLM
KIMI_API_KEY=test_key
MINIMAX_API_KEY=test_key
LOCAL_LLM_URL=http://host.docker.internal:11434

# App
APP_ENV=test
DEBUG=True

# Disable external calls
SKIP_EXTERNAL_API_TESTS=True
```

### 4. Conftest Setup

The `conftest.py` file provides shared fixtures:

```python
# backend/tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base, SessionLocal
from app.models.user import User
from app.services.auth_service import AuthService

@pytest.fixture(scope="session")
def test_db():
    """Create test database and tables."""
    engine = create_engine(os.getenv("TEST_DATABASE_URL"))
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)

@pytest.fixture
def db():
    """Database session for each test."""
    engine = create_engine(os.getenv("TEST_DATABASE_URL"))
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture
def test_user(db):
    """Create test user."""
    user = User(
        email="test@example.com",
        hashed_password=AuthService.hash_password("password123"),
        role="user"
    )
    db.add(user)
    db.commit()
    yield user

@pytest.fixture
def test_admin(db):
    """Create test admin user."""
    user = User(
        email="admin@example.com",
        hashed_password=AuthService.hash_password("password123"),
        role="admin"
    )
    db.add(user)
    db.commit()
    yield user
```

---

## Running Tests

### Basic Test Execution

```bash
# All tests
pytest backend/tests -v

# Specific test file
pytest backend/tests/unit/test_auth.py -v

# Specific test function
pytest backend/tests/unit/test_auth.py::test_login_success -v

# Tests matching pattern
pytest -k "search" -v

# Stop on first failure
pytest -x

# Show print statements
pytest -s

# Run with specific markers
pytest -m "not slow" -v
```

### Running Test Categories

```bash
# Unit tests only
pytest backend/tests/unit -v

# Integration tests
pytest backend/tests/integration -v

# E2E tests
pytest backend/tests/e2e -v

# Performance tests
pytest backend/tests/performance -v --benchmark-only

# Security tests
pytest backend/tests/security -v

# Exclude slow tests
pytest -m "not slow" -v
```

### Parallel Execution

```bash
# Run with 4 workers
pytest -n 4

# Auto-detect CPU count
pytest -n auto

# With coverage
pytest -n 4 --cov=app --cov-report=html
```

### Coverage Reports

```bash
# Generate coverage
pytest --cov=app --cov-report=html --cov-report=term-missing

# View HTML report
open htmlcov/index.html

# Show coverage by file
pytest --cov=app --cov-report=term-missing:skip-covered
```

### Test Run Script

Use provided script for full test suite:

```bash
# Run all tests with coverage
./scripts/run-tests.sh

# Run specific test type
./scripts/run-tests.sh unit
./scripts/run-tests.sh integration
./scripts/run-tests.sh e2e

# Run with detailed output
./scripts/run-tests.sh -v

# Run and generate reports
./scripts/run-tests.sh --report
```

---

## Test Structure

### Directory Organization

```
backend/tests/
├── conftest.py                    # Shared fixtures
├── test_e2e.py                    # Legacy E2E tests (being migrated)
├── fixtures/                      # Test data
│   ├── documents.json
│   ├── users.json
│   └── collections.json
├── unit/                          # Unit tests
│   ├── test_auth.py              # Authentication tests
│   ├── test_search.py            # Search logic tests
│   ├── test_embedding.py         # Embedding service tests
│   ├── test_ocr.py               # OCR tests
│   └── test_models.py            # Database model tests
├── integration/                   # Integration tests
│   ├── test_auth_api.py          # Auth endpoint tests
│   ├── test_documents_api.py     # Document endpoints
│   ├── test_search_api.py        # Search endpoints
│   ├── test_knowledge_graph_api.py
│   └── test_collections_api.py
├── e2e/                          # End-to-end tests
│   ├── test_upload_search_flow.py
│   ├── test_smart_collections.py
│   ├── test_knowledge_graph_flow.py
│   └── test_multi_agent_search.py
├── performance/                  # Performance tests
│   ├── test_search_latency.py
│   ├── test_document_processing.py
│   └── benchmark_report.json
├── security/                     # Security tests
│   ├── test_auth_security.py
│   ├── test_sql_injection.py
│   ├── test_access_control.py
│   └── test_audit_logging.py
└── README.md                     # Test documentation
```

### Test Naming Conventions

```python
# Unit test file
# backend/tests/unit/test_auth.py

class TestAuthService:
    """Tests for AuthService class."""

    def test_hash_password_creates_valid_hash(self):
        """Test that hash_password creates a bcrypt hash."""
        pass

    def test_verify_password_succeeds_with_valid_password(self):
        """Test that verify_password returns True for correct password."""
        pass

    def test_verify_password_fails_with_invalid_password(self):
        """Test that verify_password returns False for incorrect password."""
        pass

# Integration test file
# backend/tests/integration/test_auth_api.py

class TestAuthAPI:
    """Tests for authentication endpoints."""

    async def test_login_returns_token_for_valid_credentials(self, client, test_user):
        """Test POST /auth/login returns JWT for valid credentials."""
        pass

    async def test_login_returns_401_for_invalid_email(self, client):
        """Test POST /auth/login returns 401 for non-existent user."""
        pass
```

---

## Writing Tests

### Unit Test Example

```python
# backend/tests/unit/test_embedding.py

import pytest
from app.services.embedding_service import EmbeddingService
from unittest.mock import patch, MagicMock

class TestEmbeddingService:
    """Unit tests for EmbeddingService."""

    @pytest.fixture
    def service(self):
        """Create EmbeddingService instance."""
        return EmbeddingService()

    def test_embed_text_returns_vector(self, service):
        """Test that embed_text returns a valid embedding vector."""
        text = "This is a test document about family history."
        vector = service.embed(text)

        assert vector is not None
        assert isinstance(vector, list)
        assert len(vector) == 768  # multilingual-e5-large dimension
        assert all(isinstance(x, float) for x in vector)

    def test_embed_empty_text_returns_zero_vector(self, service):
        """Test that embedding empty text returns zero vector."""
        vector = service.embed("")

        assert vector is not None
        assert all(x == 0.0 for x in vector)

    @patch('app.services.embedding_service.SentenceTransformer')
    def test_embed_handles_model_load_failure(self, mock_model, service):
        """Test that embed gracefully handles model loading failure."""
        mock_model.side_effect = RuntimeError("CUDA out of memory")

        with pytest.raises(RuntimeError):
            service.embed("test")

    def test_similarity_score_between_identical_texts(self, service):
        """Test that identical texts have similarity score of 1.0."""
        text = "John Smith is the CEO of Smith Corporation."
        vec1 = service.embed(text)
        vec2 = service.embed(text)

        similarity = service.cosine_similarity(vec1, vec2)

        assert similarity == pytest.approx(1.0, abs=0.001)

    def test_similarity_score_between_unrelated_texts(self, service):
        """Test that unrelated texts have low similarity."""
        vec1 = service.embed("The weather is sunny today.")
        vec2 = service.embed("Quantum physics describes subatomic particles.")

        similarity = service.cosine_similarity(vec1, vec2)

        assert similarity < 0.5
```

### Integration Test Example

```python
# backend/tests/integration/test_documents_api.py

import pytest
from fastapi.testclient import TestClient
from app.main import app
from sqlalchemy.orm import Session

@pytest.fixture
def client():
    """Create test client for FastAPI app."""
    return TestClient(app)

@pytest.mark.asyncio
class TestDocumentsAPI:
    """Integration tests for document endpoints."""

    async def test_upload_document_creates_record(
        self, client, test_user, db
    ):
        """Test POST /documents/upload creates a document record."""
        headers = {"Authorization": f"Bearer {test_user.token}"}

        response = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": ("test.pdf", b"PDF content")}
        )

        assert response.status_code == 202
        assert "task_id" in response.json()

    async def test_list_documents_returns_user_documents(
        self, client, test_user, db
    ):
        """Test GET /documents returns user's documents."""
        # Create test document
        doc = create_test_document(test_user)
        db.add(doc)
        db.commit()

        headers = {"Authorization": f"Bearer {test_user.token}"}

        response = client.get("/api/v1/documents", headers=headers)

        assert response.status_code == 200
        assert len(response.json()["items"]) >= 1
        assert response.json()["items"][0]["id"] == doc.id

    async def test_delete_document_removes_record(
        self, client, test_user, db
    ):
        """Test DELETE /documents/{id} removes document."""
        doc = create_test_document(test_user)
        db.add(doc)
        db.commit()

        headers = {"Authorization": f"Bearer {test_user.token}"}

        response = client.delete(
            f"/api/v1/documents/{doc.id}",
            headers=headers
        )

        assert response.status_code == 204

        # Verify document deleted
        deleted = db.query(Document).filter_by(id=doc.id).first()
        assert deleted is None

    async def test_unauthorized_user_cannot_access_document(
        self, client, test_user
    ):
        """Test that unauthorized user cannot access others' documents."""
        other_user = create_test_user(email="other@example.com")
        doc = create_test_document(other_user)

        headers = {"Authorization": f"Bearer {test_user.token}"}

        response = client.get(
            f"/api/v1/documents/{doc.id}",
            headers=headers
        )

        assert response.status_code == 403
```

### E2E Test Example

```python
# backend/tests/e2e/test_upload_search_flow.py

import pytest
from fastapi.testclient import TestClient
import time

@pytest.mark.e2e
class TestUploadSearchFlow:
    """End-to-end test for document upload and search."""

    @pytest.mark.slow
    def test_upload_document_and_search(self, client, test_user, db):
        """Test complete flow: upload -> OCR -> embedding -> search."""
        headers = {"Authorization": f"Bearer {test_user.token}"}

        # 1. Upload document
        with open("tests/fixtures/sample.pdf", "rb") as f:
            response = client.post(
                "/api/v1/documents/upload",
                headers=headers,
                files={"file": f}
            )

        assert response.status_code == 202
        task_id = response.json()["task_id"]

        # 2. Wait for processing
        for _ in range(60):  # 60 second timeout
            task_response = client.get(
                f"/api/v1/tasks/{task_id}",
                headers=headers
            )
            if task_response.json()["status"] == "completed":
                break
            time.sleep(1)
        else:
            pytest.fail("Document processing timed out")

        # 3. Search for content
        search_response = client.post(
            "/api/v1/search",
            headers=headers,
            json={"query": "family history"}
        )

        assert search_response.status_code == 200
        results = search_response.json()["results"]
        assert len(results) > 0
        assert results[0]["document_id"] is not None
```

### Performance Test Example

```python
# backend/tests/performance/test_search_latency.py

import pytest

@pytest.mark.performance
class TestSearchLatency:
    """Performance tests for search latency."""

    def test_search_latency_under_3_seconds(
        self, client, test_user, benchmark
    ):
        """Test that search response time is under 3 seconds."""
        headers = {"Authorization": f"Bearer {test_user.token}"}

        def search():
            response = client.post(
                "/api/v1/search",
                headers=headers,
                json={"query": "family", "limit": 10}
            )
            assert response.status_code == 200

        # Run with pytest-benchmark
        result = benchmark(search)

        # Assert performance target
        assert result.stats.mean < 3.0  # 3 seconds

    def test_bulk_search_throughput(self, client, test_user):
        """Test search throughput with multiple queries."""
        headers = {"Authorization": f"Bearer {test_user.token}"}
        queries = ["family", "history", "finance", "business", "events"]

        start_time = time.time()

        for query in queries * 10:  # 50 total queries
            response = client.post(
                "/api/v1/search",
                headers=headers,
                json={"query": query}
            )
            assert response.status_code == 200

        elapsed = time.time() - start_time
        throughput = 50 / elapsed

        assert throughput > 10  # 10 queries per second
```

### Security Test Example

```python
# backend/tests/security/test_access_control.py

import pytest

@pytest.mark.security
class TestAccessControl:
    """Security tests for role-based access control."""

    def test_regular_user_cannot_access_confidential(
        self, client, test_user
    ):
        """Test that regular users cannot access confidential documents."""
        headers = {"Authorization": f"Bearer {test_user.token}"}

        # Create confidential document as admin
        admin_user = create_test_admin()
        doc = create_test_document(
            admin_user,
            is_confidential=True,
            title="Medical Records"
        )

        response = client.get(
            f"/api/v1/documents/{doc.id}",
            headers=headers
        )

        assert response.status_code == 403
        assert "permission" in response.json()["error"]["message"].lower()

    def test_super_user_cannot_modify_confidential(
        self, client, test_super_user
    ):
        """Test that super users cannot modify confidential documents."""
        headers = {"Authorization": f"Bearer {test_super_user.token}"}

        doc = create_test_document(
            test_super_user,
            is_confidential=True
        )

        response = client.put(
            f"/api/v1/documents/{doc.id}",
            headers=headers,
            json={"title": "Updated Title"}
        )

        assert response.status_code == 403
        assert "read-only" in response.json()["error"]["message"].lower()

    def test_sql_injection_attempt_fails(self, client, test_user):
        """Test that SQL injection attempts are blocked."""
        headers = {"Authorization": f"Bearer {test_user.token}"}

        response = client.get(
            "/api/v1/documents?id=1; DROP TABLE documents;--",
            headers=headers
        )

        assert response.status_code in [400, 422]

        # Verify table still exists
        response = client.get("/api/v1/documents", headers=headers)
        assert response.status_code == 200
```

---

## Test Coverage

### Coverage Goals

```
Target Coverage: 80%+
├─ Critical paths: 95%+ (auth, document processing, search)
├─ API endpoints: 90%+
├─ Services: 85%+
├─ Models: 80%+
└─ Utils: 70%+
```

### Generate Coverage Report

```bash
# Generate coverage with HTML report
pytest --cov=app \
       --cov-report=html \
       --cov-report=term-missing \
       --cov-report=lcov

# View results
open htmlcov/index.html

# Upload to code coverage service (optional)
pip install codecov
codecov --token=$CODECOV_TOKEN
```

### Coverage by Module

```
app/
├── api/
│   ├── auth.py                     95% (23/24 lines)
│   ├── search.py                   88% (42/48 lines)
│   ├── documents.py                85% (51/60 lines)
│   ├── knowledge_graph.py           82% (41/50 lines)
│   └── collections.py              80% (32/40 lines)
├── services/
│   ├── auth_service.py             96% (24/25 lines)
│   ├── search_service.py           87% (52/60 lines)
│   ├── embedding_service.py         91% (46/50 lines)
│   ├── ocr_service.py              84% (42/50 lines)
│   └── knowledge_graph_service.py  80% (48/60 lines)
├── models/
│   ├── user.py                     88% (35/40 lines)
│   ├── document.py                 85% (51/60 lines)
│   └── collection.py               82% (33/40 lines)
└── tasks/
    ├── document_processing.py      81% (41/51 lines)
    └── embeddings.py               83% (50/60 lines)

Total: 85% (612/720 lines)
```

---

## CI/CD Integration

### GitHub Actions Workflow

```yaml
# .github/workflows/tests.yml

name: Tests

on:
  push:
    branches: [master, develop]
  pull_request:
    branches: [master, develop]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: sowknow
          POSTGRES_PASSWORD: test
          POSTGRES_DB: sowknow_test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 6379:6379

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r backend/requirements-test.txt

      - name: Run tests
        run: |
          pytest backend/tests \
            --cov=app \
            --cov-report=xml \
            --cov-report=html \
            -v

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml

      - name: Generate test report
        if: always()
        run: |
          pytest backend/tests \
            --html=report.html \
            --self-contained-html

      - name: Upload test report
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: test-report
          path: report.html
```

### Pre-commit Hooks

```bash
# .git/hooks/pre-commit

#!/bin/bash
set -e

echo "Running tests before commit..."

# Run unit tests
pytest backend/tests/unit -q

# Check coverage
pytest backend/tests \
  --cov=app \
  --cov-fail-under=80 \
  --cov-report=term-missing:skip-covered -q

echo "✓ All tests passed"
```

---

## Troubleshooting

### Test Database Connection Issues

```bash
# Verify PostgreSQL is running
docker-compose ps postgres

# Check database exists
docker-compose exec postgres psql -U sowknow sowknow_test -c "\dt"

# Reset test database
docker-compose exec postgres dropdb -U sowknow sowknow_test
docker-compose exec postgres createdb -U sowknow sowknow_test

# Re-run migrations
TEST_DATABASE_URL=postgresql://sowknow:sowknow@postgres:5432/sowknow_test \
  alembic upgrade head
```

### Async Test Issues

```python
# Use pytest-asyncio for async tests
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result is not None

# If tests hang, check for:
# 1. Missing await on coroutines
# 2. Database session not closed
# 3. Redis connection not released
```

### Memory Issues

```bash
# Tests running out of memory?
# Run with reduced workers
pytest -n 1  # Single worker

# Or run in memory-constrained environment
pytest --memray backend/tests

# Check for memory leaks
pytest --memray-bin-path=memray backend/tests/test_memory_intensive.py
```

### Fixture Scope Issues

```python
# Make sure fixtures have correct scope:

@pytest.fixture(scope="function")  # Default - new instance per test
def test_instance():
    return TestClass()

@pytest.fixture(scope="class")     # Shared within test class
def shared_resource():
    return create_expensive_resource()

@pytest.fixture(scope="session")   # Shared across all tests
def db():
    return create_test_database()
```

### Flaky Tests

If tests are occasionally failing:

```bash
# Run specific test multiple times
pytest --count=10 backend/tests/test_flaky.py

# Run with increased timeout
pytest --timeout=30 backend/tests/test_slow.py

# Run with verbose output to debug
pytest -vv -s backend/tests/test_flaky.py
```

---

## Best Practices

### Test Organization

```python
# Good: Organized by feature
class TestSearchAPI:
    """All search-related tests grouped together."""

    async def test_basic_search(self):
        pass

    async def test_advanced_search(self):
        pass

    async def test_search_with_filters(self):
        pass

# Avoid: Unrelated tests mixed together
def test_login():
    pass

def test_search():
    pass

def test_logout():
    pass
```

### Meaningful Assertions

```python
# Good: Clear assertion with context
assert response.status_code == 200, \
    f"Expected 200, got {response.status_code}: {response.text}"

# Avoid: Unclear assertions
assert response
assert "ok" in str(response)
```

### Test Isolation

```python
# Good: Each test creates its own data
def test_document_creation(db):
    doc = create_test_document()
    db.add(doc)
    db.commit()
    # Test operates on isolated data

# Avoid: Tests sharing data or depending on order
@pytest.mark.order(1)
def test_create_document():
    global doc
    doc = create_test_document()

@pytest.mark.order(2)
def test_search_uses_doc_from_test_1():
    search(doc)  # Depends on previous test
```

### Performance Testing

```python
# Good: Explicit performance targets
def test_search_performance(benchmark):
    result = benchmark(client.post, "/api/v1/search", json={"query": "test"})
    assert result.stats.mean < 3.0  # 3 second target

# Avoid: Vague performance tests
def test_search_is_fast():
    start = time.time()
    search()
    elapsed = time.time() - start
    assert elapsed < 100  # Too lenient
```

---

## Support

For testing questions:
- Review `conftest.py` for available fixtures
- Check `/backend/tests/` for examples
- See pytest documentation: https://docs.pytest.org
- Review coverage reports in `htmlcov/index.html`

---

**SOWKNOW Testing Guide v3.0.0**
*Last Updated: February 24, 2026*
