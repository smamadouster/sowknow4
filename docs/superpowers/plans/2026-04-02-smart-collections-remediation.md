# Smart Collections Remediation — Complete Pipeline Fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the Smart Collections feature that has been broken for months with persistent 504 Gateway Timeout errors, by converting the synchronous LLM pipeline to an async Celery task, fixing bugs, raising timeout limits, and adding real tests that validate correctness and timing.

**Architecture:** The current `POST /api/v1/collections` runs 3 sequential LLM calls (intent parsing + hybrid search + summary generation = 50-200s) inside a single HTTP request. Nginx kills at 120s → 504. The fix converts collection creation to a 2-phase flow: the endpoint returns `202 Accepted` immediately with the collection in `"building"` status, while a Celery task runs the LLM pipeline in the background. A new `/status` endpoint lets the frontend poll until completion. All existing endpoints (list, get, update, delete, chat, export) remain synchronous since they don't involve LLM calls.

**Tech Stack:** FastAPI, Celery + Redis, PostgreSQL/pgvector, SQLAlchemy 2.0 (async), httpx, Next.js 14, pytest + pytest-asyncio

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/models/collection.py` | Add `"building"` and `"failed"` to collection status |
| Modify | `backend/app/services/collection_service.py` | Extract LLM pipeline into `build_collection_pipeline()`, callable from Celery |
| Modify | `backend/app/api/collections.py` | Return 202 + poll, fix missing `await`, add `/status` endpoint |
| Modify | `backend/app/tasks/document_tasks.py` | Add `build_smart_collection` Celery task |
| Modify | `nginx/nginx.conf` | Add dedicated `/api/v1/collections` location with 300s timeout |
| Modify | `nginx/nginx-http-only.conf` | Same nginx timeout fix for HTTP-only config |
| Modify | `frontend/app/[locale]/collections/page.tsx` | Poll for collection readiness after creation |
| Modify | `frontend/lib/api.ts` | Add `getCollectionStatus()` method |
| Modify | `frontend/app/messages/fr.json` | Add `building`/`failed` status translations |
| Modify | `frontend/app/messages/en.json` | Add `building`/`failed` status translations |
| Create | `backend/tests/unit/test_collection_creation_async.py` | Unit tests for async pipeline logic |
| Create | `backend/tests/integration/test_collection_pipeline.py` | Integration tests for full pipeline correctness |
| Create | `backend/tests/unit/test_collection_stats_bug.py` | Regression test for missing `await` bug |

---

## Task 1: Fix the missing `await` bug on `get_collection_stats`

This is a real bug that crashes the `/stats` endpoint. Fix it first — it's 1 line and gives us confidence the test infra works.

**Files:**
- Create: `backend/tests/unit/test_collection_stats_bug.py`
- Modify: `backend/app/api/collections.py:208`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_collection_stats_bug.py`:

```python
"""
Regression test for missing await on get_collection_stats.

The endpoint at collections.py:208 was calling an async method without await,
returning a coroutine object instead of the stats dict.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


class TestCollectionStatsEndpoint:
    """Verify GET /api/v1/collections/stats returns valid JSON, not a coroutine."""

    def test_stats_endpoint_returns_json(self, client: TestClient, admin_headers: dict):
        """
        The stats endpoint must return a 200 with a JSON body containing
        total_collections key. Before the fix, it returned 500 because
        collection_service.get_collection_stats() was called without await.
        """
        with patch(
            "app.api.collections.collection_service.get_collection_stats",
            new_callable=AsyncMock,
            return_value={
                "total_collections": 0,
                "pinned_collections": 0,
                "favorite_collections": 0,
                "total_documents_in_collections": 0,
                "average_documents_per_collection": 0.0,
                "collections_by_type": {},
                "recent_activity": [],
            },
        ):
            response = client.get("/api/v1/collections/stats", headers=admin_headers)

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "total_collections" in data
        assert isinstance(data["total_collections"], int)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_collection_stats_bug.py -v --tb=short
```

Expected: FAIL — the endpoint returns 500 because the coroutine object is not awaited.

- [ ] **Step 3: Fix the missing await**

In `backend/app/api/collections.py`, line 208, change:

```python
        stats = collection_service.get_collection_stats(user=current_user, db=db)
```

to:

```python
        stats = await collection_service.get_collection_stats(user=current_user, db=db)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_collection_stats_bug.py -v --tb=short
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/development/src/active/sowknow4 && git add backend/tests/unit/test_collection_stats_bug.py backend/app/api/collections.py && git commit -m "fix(collections): add missing await on get_collection_stats endpoint"
```

---

## Task 2: Add `"building"` and `"failed"` status to Collection model

The collection needs a status field so the frontend knows when it's ready. Currently there's no status column — the collection is created fully formed or not at all. We add a status enum with: `ready`, `building`, `failed`.

**Files:**
- Modify: `backend/app/models/collection.py`
- Create: `backend/tests/unit/test_collection_creation_async.py` (first test only)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_collection_creation_async.py`:

```python
"""
Tests for async collection creation pipeline.
Covers: status transitions, Celery task dispatch, error handling.
"""
import pytest
from app.models.collection import Collection, CollectionStatus


class TestCollectionStatusEnum:
    """CollectionStatus enum must exist with building/ready/failed values."""

    def test_status_enum_has_building(self):
        assert CollectionStatus.BUILDING.value == "building"

    def test_status_enum_has_ready(self):
        assert CollectionStatus.READY.value == "ready"

    def test_status_enum_has_failed(self):
        assert CollectionStatus.FAILED.value == "failed"

    def test_collection_model_has_status_field(self, db):
        """Collection model must have a status column."""
        from app.models.user import User, UserRole

        user = db.query(User).first()
        if not user:
            user = User(
                email="status_test@example.com",
                hashed_password="hashed",  # pragma: allowlist secret
                full_name="Status Test",
                role=UserRole.USER,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        collection = Collection(
            user_id=user.id,
            name="Status Test",
            query="test",
            collection_type="smart",
            visibility="private",
            status=CollectionStatus.BUILDING,
            document_count=0,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        assert collection.status == CollectionStatus.BUILDING

    def test_collection_status_default_is_ready(self, db):
        """Existing collections without explicit status should default to ready."""
        from app.models.user import User, UserRole

        user = db.query(User).first()
        if not user:
            user = User(
                email="default_status@example.com",
                hashed_password="hashed",  # pragma: allowlist secret
                full_name="Default Status",
                role=UserRole.USER,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        collection = Collection(
            user_id=user.id,
            name="Default Status Test",
            query="test",
            collection_type="smart",
            visibility="private",
            document_count=0,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        assert collection.status == CollectionStatus.READY
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_collection_creation_async.py::TestCollectionStatusEnum -v --tb=short
```

Expected: FAIL — `CollectionStatus` does not exist yet.

- [ ] **Step 3: Add CollectionStatus enum and status column to Collection model**

In `backend/app/models/collection.py`, add the enum and column. Find the existing enum definitions (near `CollectionType`, `CollectionVisibility`) and add:

```python
class CollectionStatus(str, Enum):
    """Status of collection build pipeline"""
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"
```

Then in the `Collection` class, add the column after the existing fields (near `document_count`):

```python
    status = Column(SqlEnum(CollectionStatus), default=CollectionStatus.READY, nullable=False, server_default="ready")
    build_error = Column(String, nullable=True)  # Error message if status == FAILED
```

Also add the import for `SqlEnum` if not present:

```python
from sqlalchemy import Enum as SqlEnum
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_collection_creation_async.py::TestCollectionStatusEnum -v --tb=short
```

Expected: PASS — all 4 tests green.

- [ ] **Step 5: Commit**

```bash
cd /home/development/src/active/sowknow4 && git add backend/app/models/collection.py backend/tests/unit/test_collection_creation_async.py && git commit -m "feat(collections): add CollectionStatus enum with building/ready/failed states"
```

---

## Task 3: Refactor collection_service to separate shell creation from LLM pipeline

Currently `create_collection()` does everything in one call. Split it into:
1. `create_collection_shell()` — creates the DB row with `status=BUILDING`, returns immediately
2. `build_collection_pipeline()` — runs intent parsing + search + summary, updates the row to `READY`

This separation is the core architectural fix. The shell creator runs in the HTTP request; the pipeline runs in Celery.

**Files:**
- Modify: `backend/app/services/collection_service.py`
- Modify: `backend/tests/unit/test_collection_creation_async.py` (add tests)

- [ ] **Step 1: Write the failing test for create_collection_shell**

Add to `backend/tests/unit/test_collection_creation_async.py`:

```python
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from app.models.collection import Collection, CollectionStatus
from app.models.user import User, UserRole
from app.schemas.collection import CollectionCreate
from app.services.collection_service import collection_service


class TestCreateCollectionShell:
    """create_collection_shell must create a DB row with status=BUILDING and no LLM calls."""

    @pytest.mark.asyncio
    async def test_shell_creates_building_status(self, db):
        """Shell creation sets status to BUILDING."""
        user = db.query(User).first()
        if not user:
            user = User(
                email="shell_test@example.com",
                hashed_password="hashed",  # pragma: allowlist secret
                full_name="Shell Test",
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        data = CollectionCreate(
            name="Shell Test Collection",
            query="Find all financial documents",
            collection_type="smart",
            visibility="private",
        )

        collection = await collection_service.create_collection_shell(
            collection_data=data, user=user, db=db
        )

        assert collection.id is not None
        assert collection.status == CollectionStatus.BUILDING
        assert collection.name == "Shell Test Collection"
        assert collection.query == "Find all financial documents"
        assert collection.document_count == 0
        assert collection.ai_summary is None

    @pytest.mark.asyncio
    async def test_shell_does_not_call_llm(self, db):
        """Shell creation must NOT call any LLM service."""
        user = db.query(User).first()
        if not user:
            user = User(
                email="no_llm@example.com",
                hashed_password="hashed",  # pragma: allowlist secret
                full_name="No LLM",
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        data = CollectionCreate(
            name="No LLM Test",
            query="Find contracts",
            collection_type="smart",
            visibility="private",
        )

        with patch.object(
            collection_service.intent_parser, "parse_intent", new_callable=AsyncMock
        ) as mock_intent, patch.object(
            collection_service.search_service, "hybrid_search", new_callable=AsyncMock
        ) as mock_search:
            await collection_service.create_collection_shell(
                collection_data=data, user=user, db=db
            )
            mock_intent.assert_not_called()
            mock_search.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_collection_creation_async.py::TestCreateCollectionShell -v --tb=short
```

Expected: FAIL — `create_collection_shell` does not exist.

- [ ] **Step 3: Implement create_collection_shell and build_collection_pipeline**

In `backend/app/services/collection_service.py`, add two new methods to `CollectionService`. Keep the existing `create_collection()` method intact (it still works for tests/internal use). Add these methods:

```python
    async def create_collection_shell(
        self, collection_data: CollectionCreate, user: User, db: Session
    ) -> Collection:
        """
        Create a collection record with status=BUILDING.
        No LLM calls — returns instantly for the HTTP response.
        """
        collection = Collection(
            user_id=user.id,
            name=collection_data.name,
            description=collection_data.description,
            collection_type=collection_data.collection_type,
            visibility=collection_data.visibility,
            query=collection_data.query,
            status=CollectionStatus.BUILDING,
            document_count=0,
            is_pinned=False,
            is_favorite=False,
        )
        db.add(collection)
        await db.commit()
        await db.refresh(collection)
        logger.info(f"Created collection shell '{collection.name}' (status=building) for user {user.email}")
        return collection

    async def build_collection_pipeline(
        self, collection_id: uuid.UUID, user_id: uuid.UUID, db: Session
    ) -> Collection:
        """
        Run the full LLM pipeline for a collection: intent parsing, document
        gathering, and AI summary generation. Updates collection to READY on
        success or FAILED on error.

        This method is designed to be called from a Celery task.
        """
        from app.models.user import User as UserModel

        result = await db.execute(select(Collection).where(Collection.id == collection_id))
        collection = result.scalar_one_or_none()
        if not collection:
            raise ValueError(f"Collection {collection_id} not found")

        user_result = await db.execute(select(UserModel).where(UserModel.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise ValueError(f"User {user_id} not found")

        try:
            use_ollama = hasattr(user, "role") and user.role in [
                UserRole.ADMIN, UserRole.SUPERUSER,
            ]

            # Step 1: Parse intent
            parsed_intent = await self.intent_parser.parse_intent(
                query=collection.query,
                user_language="en",
                use_ollama=use_ollama,
            )

            # Step 2: Gather documents
            documents = await self._gather_documents_for_intent(
                intent=parsed_intent, user=user, db=db
            )

            # Step 3: Generate summary
            ai_summary = None
            if documents:
                ai_summary = await self._generate_collection_summary(
                    collection_name=parsed_intent.collection_name or collection.name,
                    query=collection.query,
                    documents=documents[:10],
                    parsed_intent=parsed_intent,
                )

            # Step 4: Add collection items
            for idx, doc in enumerate(documents):
                relevance = self._calculate_relevance(doc, parsed_intent)
                item = CollectionItem(
                    collection_id=collection.id,
                    document_id=doc.id,
                    relevance_score=relevance,
                    order_index=idx,
                    added_by="ai",
                    added_reason=f"Matched query: {collection.query}",
                )
                db.add(item)

            # Step 5: Update collection to READY
            collection.parsed_intent = parsed_intent.to_dict()
            collection.ai_summary = ai_summary
            collection.ai_keywords = parsed_intent.keywords
            collection.ai_entities = parsed_intent.entities
            collection.filter_criteria = parsed_intent.to_search_filter()
            collection.document_count = len(documents)
            collection.last_refreshed_at = datetime.utcnow().isoformat()
            collection.status = CollectionStatus.READY

            await db.commit()
            await db.refresh(collection)
            logger.info(
                f"Collection '{collection.name}' built: {len(documents)} docs, status=ready"
            )
            return collection

        except Exception as e:
            logger.error(f"Collection build failed for {collection_id}: {e}", exc_info=True)
            collection.status = CollectionStatus.FAILED
            collection.build_error = str(e)[:500]
            await db.commit()
            raise
```

Also add the import at the top of the file:

```python
from app.models.collection import CollectionStatus
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_collection_creation_async.py -v --tb=short
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/development/src/active/sowknow4 && git add backend/app/services/collection_service.py backend/tests/unit/test_collection_creation_async.py && git commit -m "feat(collections): split creation into shell + async pipeline"
```

---

## Task 4: Add build_smart_collection Celery task

The Celery task wraps `build_collection_pipeline()` with a sync-to-async bridge. It catches all errors and sets the collection to FAILED status.

**Files:**
- Modify: `backend/app/tasks/document_tasks.py`
- Modify: `backend/tests/unit/test_collection_creation_async.py` (add Celery task tests)

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_collection_creation_async.py`:

```python
from unittest.mock import patch, MagicMock, AsyncMock


class TestBuildSmartCollectionTask:
    """Celery task must call build_collection_pipeline and handle errors."""

    def test_task_is_registered(self):
        """The build_smart_collection task must be importable."""
        from app.tasks.document_tasks import build_smart_collection
        assert callable(build_smart_collection)

    def test_task_calls_pipeline(self, db):
        """Task must invoke build_collection_pipeline with correct args."""
        from app.tasks.document_tasks import build_smart_collection

        fake_collection_id = str(uuid4())
        fake_user_id = str(uuid4())

        with patch("app.tasks.document_tasks._run_build_pipeline") as mock_run:
            mock_run.return_value = None
            build_smart_collection(fake_collection_id, fake_user_id)
            mock_run.assert_called_once_with(fake_collection_id, fake_user_id)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_collection_creation_async.py::TestBuildSmartCollectionTask -v --tb=short
```

Expected: FAIL — `build_smart_collection` does not exist.

- [ ] **Step 3: Add the Celery task to document_tasks.py**

In `backend/app/tasks/document_tasks.py`, add at the bottom (before any `if __name__` block):

```python
# ---------------------------------------------------------------------------
# Smart Collection async build task
# ---------------------------------------------------------------------------

def _run_build_pipeline(collection_id: str, user_id: str) -> None:
    """
    Sync wrapper that runs the async collection build pipeline.
    Called by the Celery task. Uses a fresh async DB session.
    """
    import asyncio
    from uuid import UUID
    from app.services.collection_service import collection_service
    from app.database import async_session_factory

    async def _inner():
        async with async_session_factory() as session:
            await collection_service.build_collection_pipeline(
                collection_id=UUID(collection_id),
                user_id=UUID(user_id),
                db=session,
            )

    # Celery workers don't have a running event loop
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_inner())
    finally:
        loop.close()


@celery_app.task(
    name="build_smart_collection",
    bind=True,
    max_retries=1,
    soft_time_limit=240,
    time_limit=300,
)
def build_smart_collection(self, collection_id: str, user_id: str) -> dict:
    """
    Celery task: build a Smart Collection asynchronously.

    Runs intent parsing → hybrid search → AI summary → DB update.
    On failure, the collection is set to FAILED status by the pipeline itself.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Starting build_smart_collection for collection={collection_id}")

    try:
        _run_build_pipeline(collection_id, user_id)
        return {"status": "ready", "collection_id": collection_id}
    except Exception as exc:
        logger.error(f"build_smart_collection failed: {exc}", exc_info=True)
        return {"status": "failed", "collection_id": collection_id, "error": str(exc)[:500]}
```

Also ensure `celery_app` is imported at the top of the file (it likely already is).

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_collection_creation_async.py::TestBuildSmartCollectionTask -v --tb=short
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/development/src/active/sowknow4 && git add backend/app/tasks/document_tasks.py backend/tests/unit/test_collection_creation_async.py && git commit -m "feat(collections): add build_smart_collection Celery task"
```

---

## Task 5: Update API endpoint to return 202 + add status polling endpoint

The `POST /api/v1/collections` endpoint now creates a shell and dispatches the Celery task, returning `202 Accepted`. A new `GET /api/v1/collections/{id}/status` endpoint returns the build status.

**Files:**
- Modify: `backend/app/api/collections.py`
- Create: `backend/tests/integration/test_collection_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_collection_pipeline.py`:

```python
"""
Integration tests for the async collection creation pipeline.
Tests: 202 response, status polling, error propagation, list filtering.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.collection import Collection, CollectionStatus
from app.models.user import User, UserRole


class TestCreateCollectionReturns202:
    """POST /api/v1/collections must return 202 with collection in building status."""

    def test_create_returns_202_with_building_status(
        self, client: TestClient, db: Session, admin_headers: dict
    ):
        """Endpoint returns 202 Accepted with status=building, no 504."""
        with patch(
            "app.api.collections.build_smart_collection"
        ) as mock_task:
            mock_task.delay = MagicMock()

            response = client.post(
                "/api/v1/collections",
                headers=admin_headers,
                json={
                    "name": "Test Async Collection",
                    "query": "Find all financial documents from 2024",
                    "collection_type": "smart",
                    "visibility": "private",
                },
            )

        assert response.status_code == 202, f"Expected 202, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "building"
        assert data["name"] == "Test Async Collection"
        assert data["document_count"] == 0

    def test_create_dispatches_celery_task(
        self, client: TestClient, db: Session, admin_headers: dict
    ):
        """Endpoint must dispatch build_smart_collection Celery task."""
        with patch(
            "app.api.collections.build_smart_collection"
        ) as mock_task:
            mock_task.delay = MagicMock()

            client.post(
                "/api/v1/collections",
                headers=admin_headers,
                json={
                    "name": "Celery Dispatch Test",
                    "query": "Find contracts",
                    "collection_type": "smart",
                    "visibility": "private",
                },
            )

            mock_task.delay.assert_called_once()
            args = mock_task.delay.call_args[0]
            assert len(args) == 2  # collection_id, user_id
            assert isinstance(args[0], str)  # collection_id as string
            assert isinstance(args[1], str)  # user_id as string


class TestCollectionStatusEndpoint:
    """GET /api/v1/collections/{id}/status returns build status."""

    def test_status_returns_building(
        self, client: TestClient, db: Session, admin_headers: dict, admin_user: User
    ):
        """Status endpoint returns building when collection is being built."""
        collection = Collection(
            user_id=admin_user.id,
            name="Building Collection",
            query="test",
            collection_type="smart",
            visibility="private",
            status=CollectionStatus.BUILDING,
            document_count=0,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        response = client.get(
            f"/api/v1/collections/{collection.id}/status",
            headers=admin_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "building"
        assert data["document_count"] == 0

    def test_status_returns_ready_with_count(
        self, client: TestClient, db: Session, admin_headers: dict, admin_user: User
    ):
        """Status endpoint returns ready with document count when done."""
        collection = Collection(
            user_id=admin_user.id,
            name="Ready Collection",
            query="test",
            collection_type="smart",
            visibility="private",
            status=CollectionStatus.READY,
            document_count=15,
            ai_summary="A summary of the collection.",
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        response = client.get(
            f"/api/v1/collections/{collection.id}/status",
            headers=admin_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["document_count"] == 15

    def test_status_returns_failed_with_error(
        self, client: TestClient, db: Session, admin_headers: dict, admin_user: User
    ):
        """Status endpoint returns failed with error message."""
        collection = Collection(
            user_id=admin_user.id,
            name="Failed Collection",
            query="test",
            collection_type="smart",
            visibility="private",
            status=CollectionStatus.FAILED,
            build_error="OpenRouter API timeout after 120s",
            document_count=0,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        response = client.get(
            f"/api/v1/collections/{collection.id}/status",
            headers=admin_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert "error" in data
        assert "timeout" in data["error"].lower()


class TestCollectionListFiltering:
    """GET /api/v1/collections must include building/failed collections."""

    def test_list_includes_building_collections(
        self, client: TestClient, db: Session, admin_headers: dict, admin_user: User
    ):
        """Building collections appear in the list so users see them."""
        collection = Collection(
            user_id=admin_user.id,
            name="Building In List",
            query="test",
            collection_type="smart",
            visibility="private",
            status=CollectionStatus.BUILDING,
            document_count=0,
        )
        db.add(collection)
        db.commit()

        response = client.get("/api/v1/collections", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        names = [c["name"] for c in data["collections"]]
        assert "Building In List" in names
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/integration/test_collection_pipeline.py -v --tb=short
```

Expected: FAIL — endpoint still returns 201, no `/status` endpoint exists.

- [ ] **Step 3: Update the collections API**

In `backend/app/api/collections.py`, make these changes:

**3a.** Add import at the top of the file:

```python
from app.tasks.document_tasks import build_smart_collection
from app.models.collection import CollectionStatus
```

**3b.** Replace the `create_collection` endpoint (lines 90-111) with:

```python
@router.post("", response_model=CollectionResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_collection(
    collection_data: CollectionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """
    Create a new Smart Collection from natural language query.

    Returns 202 Accepted immediately. The AI pipeline (intent parsing,
    document gathering, summary generation) runs asynchronously via Celery.
    Poll GET /api/v1/collections/{id}/status to check progress.
    """
    try:
        collection = await collection_service.create_collection_shell(
            collection_data=collection_data, user=current_user, db=db
        )

        # Dispatch async build task
        build_smart_collection.delay(str(collection.id), str(current_user.id))

        return collection
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create collection: {str(e)}",
        )
```

**3c.** Add the status endpoint. Place it BEFORE the `/{collection_id}` GET route to avoid path conflicts:

```python
@router.get("/{collection_id}/status")
async def get_collection_status(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Get collection build status.

    Returns status (building/ready/failed), document_count, and error message if failed.
    Used by frontend to poll for completion after async creation.
    """
    visibility_filter = collection_service._get_user_visibility_filter(current_user)

    coll_result = await db.execute(
        select(Collection).where(
            and_(
                Collection.id == collection_id,
                or_(
                    Collection.user_id == current_user.id,
                    Collection.visibility.in_(visibility_filter),
                ),
            )
        )
    )
    collection = coll_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    result = {
        "id": str(collection.id),
        "status": collection.status.value if hasattr(collection.status, 'value') else collection.status,
        "name": collection.name,
        "document_count": collection.document_count,
        "ai_summary": collection.ai_summary,
    }

    if collection.status == CollectionStatus.FAILED:
        result["error"] = collection.build_error or "Unknown error"

    return result
```

**IMPORTANT:** The `/status` route must be defined BEFORE the `/{collection_id}` route in the file. Place it after the `/stats` endpoint and before the `/{collection_id}` GET endpoint. Otherwise FastAPI will try to match "status" as a UUID.

Actually — looking again, the `/status` path is `/{collection_id}/status` which won't conflict since `collection_id` is a UUID type. Place it right after the `/{collection_id}` GET endpoint, before `/{collection_id}` PATCH.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/integration/test_collection_pipeline.py -v --tb=short
```

Expected: All tests PASS.

- [ ] **Step 5: Also run existing collection tests to check for regressions**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/e2e/test_smart_collection_creation.py tests/unit/test_collection_stats_bug.py tests/unit/test_collection_creation_async.py -v --tb=short
```

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/development/src/active/sowknow4 && git add backend/app/api/collections.py backend/tests/integration/test_collection_pipeline.py && git commit -m "feat(collections): async creation with 202 response + status polling endpoint"
```

---

## Task 6: Increase hybrid search timeout for collection gathering

The hybrid search has an 8-second timeout that is too aggressive for collection gathering (which requests up to 100 results). The collection service should pass a larger timeout.

**Files:**
- Modify: `backend/app/services/collection_service.py:358`
- Modify: `backend/tests/unit/test_collection_creation_async.py` (add test)

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_collection_creation_async.py`:

```python
class TestHybridSearchTimeout:
    """Collection gathering must pass a longer timeout to hybrid_search."""

    @pytest.mark.asyncio
    async def test_gather_passes_20s_timeout(self, db):
        """_gather_documents_for_intent must call hybrid_search with timeout >= 20."""
        from app.services.intent_parser import ParsedIntent

        user = db.query(User).first()
        if not user:
            user = User(
                email="timeout_test@example.com",
                hashed_password="hashed",  # pragma: allowlist secret
                full_name="Timeout Test",
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        intent = ParsedIntent(
            query="solar energy",
            keywords=["solar", "energy"],
            date_range={"type": "all_time"},
            entities=[],
            document_types=["all"],
            collection_name="Test",
            confidence=0.9,
        )

        with patch.object(
            collection_service.search_service,
            "hybrid_search",
            new_callable=AsyncMock,
            return_value={"results": [], "total": 0, "query": "solar energy"},
        ) as mock_search:
            await collection_service._gather_documents_for_intent(
                intent=intent, user=user, db=db
            )

            mock_search.assert_called_once()
            call_kwargs = mock_search.call_args
            # Check the timeout keyword argument
            if call_kwargs.kwargs.get("timeout"):
                assert call_kwargs.kwargs["timeout"] >= 20
            else:
                # If timeout is positional, check all args
                pytest.fail("hybrid_search must be called with timeout=20 keyword argument")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_collection_creation_async.py::TestHybridSearchTimeout -v --tb=short
```

Expected: FAIL — currently no `timeout` kwarg is passed.

- [ ] **Step 3: Add timeout parameter to the hybrid_search call**

In `backend/app/services/collection_service.py`, in `_gather_documents_for_intent()`, find line 358:

```python
            search_result = await self.search_service.hybrid_search(
                query=search_query, limit=100, offset=0, db=db, user=user
            )
```

Change to:

```python
            search_result = await self.search_service.hybrid_search(
                query=search_query, limit=100, offset=0, db=db, user=user, timeout=20.0
            )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_collection_creation_async.py::TestHybridSearchTimeout -v --tb=short
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/development/src/active/sowknow4 && git add backend/app/services/collection_service.py backend/tests/unit/test_collection_creation_async.py && git commit -m "fix(collections): increase hybrid search timeout from 8s to 20s for collection gathering"
```

---

## Task 7: Add dedicated nginx location for collections with 300s timeout

Even though the main pipeline is now async, the refresh and chat endpoints still make LLM calls. Give the collections path a generous timeout.

**Files:**
- Modify: `nginx/nginx.conf`
- Modify: `nginx/nginx-http-only.conf`

- [ ] **Step 1: Add collections location block to nginx.conf**

In `nginx/nginx.conf`, add a new location block AFTER the `/api/v1/documents/upload` block (after line 112) and BEFORE the general `/api/` block:

```nginx
        # Collections endpoints — longer timeout for LLM-powered operations
        location /api/v1/collections {
            limit_req zone=api_limit burst=20 nodelay;

            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Collections involve LLM calls (refresh, chat) — need generous timeout
            proxy_read_timeout 300s;
            proxy_connect_timeout 10s;
            proxy_send_timeout 120s;
        }
```

- [ ] **Step 2: Apply the same change to nginx-http-only.conf**

In `nginx/nginx-http-only.conf`, add the same location block AFTER the `/api/v1/documents/upload` block and BEFORE the general `/api/` block:

```nginx
        # Collections endpoints — longer timeout for LLM-powered operations
        location /api/v1/collections {
            limit_req zone=api_limit burst=20 nodelay;

            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Collections involve LLM calls (refresh, chat) — need generous timeout
            proxy_read_timeout 300s;
            proxy_connect_timeout 10s;
            proxy_send_timeout 120s;
        }
```

- [ ] **Step 3: Validate nginx config syntax**

```bash
cd /home/development/src/active/sowknow4 && docker run --rm -v $(pwd)/nginx/nginx.conf:/etc/nginx/nginx.conf:ro nginx:alpine nginx -t 2>&1 || echo "If docker not available, check syntax manually"
```

Expected: `nginx: the configuration file /etc/nginx/nginx.conf syntax is ok`

- [ ] **Step 4: Commit**

```bash
cd /home/development/src/active/sowknow4 && git add nginx/nginx.conf nginx/nginx-http-only.conf && git commit -m "fix(nginx): add dedicated /api/v1/collections location with 300s proxy timeout"
```

---

## Task 8: Update frontend to handle async collection creation with polling

The frontend needs to:
1. Handle the 202 response from collection creation
2. Show a "building" indicator on the collections list
3. Poll the `/status` endpoint until the collection is ready

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/app/[locale]/collections/page.tsx`
- Modify: `frontend/app/messages/fr.json`
- Modify: `frontend/app/messages/en.json`

- [ ] **Step 1: Add getCollectionStatus to api.ts**

Find the `getCollections` method in `frontend/lib/api.ts` and add after it:

```typescript
  async getCollectionStatus(collectionId: string): Promise<ApiResponse<{
    id: string;
    status: string;
    name: string;
    document_count: number;
    ai_summary: string | null;
    error?: string;
  }>> {
    return this.request(`/v1/collections/${collectionId}/status`);
  }
```

- [ ] **Step 2: Update the collections page to handle 202 and poll**

Replace the `handleCreateCollection` function in `frontend/app/[locale]/collections/page.tsx` (lines 67-92):

```typescript
  const [buildingCollections, setBuildingCollections] = useState<Set<string>>(new Set());

  const handleCreateCollection = async () => {
    if (!newQuery.trim()) return;
    setCreateError(null);

    try {
      const { api } = await import("@/lib/api");
      const response = await api.createCollection(
        newQuery.slice(0, 500),
        newQuery
      );

      if (response.error) {
        setCreateError(response.error);
        return;
      }

      if (response.data) {
        const newCollection = response.data as Collection & { status?: string };
        setShowCreateModal(false);
        setNewQuery("");

        // Add to building set and start polling
        if (newCollection.id && newCollection.status === "building") {
          setBuildingCollections((prev) => new Set(prev).add(newCollection.id));
          pollCollectionStatus(newCollection.id);
        }

        fetchCollections();
      }
    } catch (error) {
      console.error("Error creating collection:", error);
      setCreateError(error instanceof Error ? error.message : "Failed to create collection");
    }
  };

  const pollCollectionStatus = async (collectionId: string) => {
    const { api } = await import("@/lib/api");
    const maxAttempts = 60; // 5 minutes at 5s intervals
    let attempts = 0;

    const poll = async () => {
      attempts++;
      try {
        const response = await api.getCollectionStatus(collectionId);
        if (response.data) {
          const status = response.data.status;
          if (status === "ready" || status === "failed") {
            setBuildingCollections((prev) => {
              const next = new Set(prev);
              next.delete(collectionId);
              return next;
            });
            fetchCollections();
            return;
          }
        }
      } catch (error) {
        console.error("Error polling collection status:", error);
      }

      if (attempts < maxAttempts) {
        setTimeout(poll, 5000);
      } else {
        setBuildingCollections((prev) => {
          const next = new Set(prev);
          next.delete(collectionId);
          return next;
        });
      }
    };

    setTimeout(poll, 3000); // First poll after 3s
  };
```

- [ ] **Step 3: Update the collection card to show building status**

In the same file, update the collection card rendering (inside the `.map()`) to show building state. Find the `<div className="bg-white dark:bg-gray-800 rounded-lg shadow` section and add a status indicator after the document count:

Replace the document count span (around line 240-242):

```typescript
                      <span className="text-sm text-gray-500 dark:text-gray-400">
                        {buildingCollections.has(collection.id) || collection.document_count === 0 ? (
                          <span className="flex items-center gap-1">
                            <span className="inline-block w-3 h-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></span>
                            {t('building')}
                          </span>
                        ) : (
                          `${collection.document_count} ${t('documents')}`
                        )}
                      </span>
```

- [ ] **Step 4: Add translation keys**

In `frontend/app/messages/fr.json`, inside the `"collections"` section, add:

```json
    "building": "Construction en cours...",
    "build_failed": "La construction a echoue"
```

In `frontend/app/messages/en.json`, inside the `"collections"` section, add:

```json
    "building": "Building...",
    "build_failed": "Build failed"
```

- [ ] **Step 5: Commit**

```bash
cd /home/development/src/active/sowknow4 && git add frontend/lib/api.ts frontend/app/[locale]/collections/page.tsx frontend/app/messages/fr.json frontend/app/messages/en.json && git commit -m "feat(frontend): async collection creation with polling and building indicator"
```

---

## Task 9: Create Alembic migration for the new status column

The production database needs a migration to add the `status` and `build_error` columns.

**Files:**
- Create: `backend/alembic/versions/XXX_add_collection_status.py` (auto-generated)

- [ ] **Step 1: Generate the migration**

```bash
cd /home/development/src/active/sowknow4/backend && python -m alembic revision --autogenerate -m "add collection status and build_error columns"
```

- [ ] **Step 2: Review the generated migration**

Open the generated file and verify it contains:
- `op.add_column('collections', sa.Column('status', ...))` with `server_default='ready'`
- `op.add_column('collections', sa.Column('build_error', sa.String(), nullable=True))`
- Downgrade that drops both columns

If the autogenerate missed anything, manually add:

```python
def upgrade() -> None:
    op.add_column('collections', sa.Column(
        'status',
        sa.Enum('building', 'ready', 'failed', name='collectionstatus'),
        nullable=False,
        server_default='ready',
    ))
    op.add_column('collections', sa.Column('build_error', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('collections', 'build_error')
    op.drop_column('collections', 'status')
    op.execute("DROP TYPE IF EXISTS collectionstatus")
```

- [ ] **Step 3: Test migration against dev database**

```bash
cd /home/development/src/active/sowknow4/backend && python -m alembic upgrade head
```

Expected: Migration applies cleanly.

- [ ] **Step 4: Commit**

```bash
cd /home/development/src/active/sowknow4 && git add backend/alembic/versions/ && git commit -m "migration: add collection status and build_error columns"
```

---

## Task 10: Add the CollectionResponse schema update for status field

The Pydantic response schema needs to include the new `status` and `build_error` fields.

**Files:**
- Modify: `backend/app/schemas/collection.py`

- [ ] **Step 1: Read the current schema**

Read `backend/app/schemas/collection.py` and find the `CollectionResponse` class.

- [ ] **Step 2: Add status fields to CollectionResponse**

In the `CollectionResponse` class, add:

```python
    status: str = "ready"
    build_error: str | None = None
```

- [ ] **Step 3: Run all collection tests to verify no regressions**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_collection_creation_async.py tests/unit/test_collection_stats_bug.py tests/integration/test_collection_pipeline.py tests/e2e/test_smart_collection_creation.py -v --tb=short
```

Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/development/src/active/sowknow4 && git add backend/app/schemas/collection.py && git commit -m "feat(schema): add status and build_error to CollectionResponse"
```

---

## Task 11: Add pipeline accuracy and correctness integration tests

These tests validate that the full pipeline produces correct results — not just that it runs. They test: LLM routing logic, document matching accuracy, error recovery, and status transitions.

**Files:**
- Modify: `backend/tests/integration/test_collection_pipeline.py`

- [ ] **Step 1: Add pipeline correctness tests**

Append to `backend/tests/integration/test_collection_pipeline.py`:

```python
from datetime import datetime
from uuid import uuid4
from unittest.mock import AsyncMock, patch, MagicMock

from app.models.collection import Collection, CollectionItem, CollectionStatus
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.models.user import User, UserRole
from app.services.collection_service import collection_service
from app.services.intent_parser import ParsedIntent


class TestPipelineCorrectness:
    """Verify the build pipeline produces correct, complete collections."""

    @pytest.mark.asyncio
    async def test_pipeline_sets_ready_on_success(self, db, admin_user):
        """Pipeline must transition collection from BUILDING → READY."""
        from app.schemas.collection import CollectionCreate

        # Create shell
        data = CollectionCreate(
            name="Correctness Test",
            query="Find solar energy documents",
            collection_type="smart",
            visibility="private",
        )
        collection = await collection_service.create_collection_shell(
            collection_data=data, user=admin_user, db=db
        )
        assert collection.status == CollectionStatus.BUILDING

        # Mock LLM calls and run pipeline
        mock_intent = ParsedIntent(
            query="Find solar energy documents",
            keywords=["solar", "energy"],
            date_range={"type": "all_time"},
            entities=[],
            document_types=["all"],
            collection_name="Solar Energy Docs",
            confidence=0.9,
        )

        async def _instant_llm(*args, **kwargs):
            yield "Summary of solar energy documents."

        with patch.object(
            collection_service.intent_parser, "parse_intent",
            new_callable=AsyncMock, return_value=mock_intent,
        ), patch(
            "app.services.openrouter_service.openrouter_service.chat_completion",
            side_effect=_instant_llm,
        ):
            result = await collection_service.build_collection_pipeline(
                collection_id=collection.id,
                user_id=admin_user.id,
                db=db,
            )

        assert result.status == CollectionStatus.READY
        assert result.ai_summary is not None
        assert result.parsed_intent is not None
        assert result.ai_keywords == ["solar", "energy"]

    @pytest.mark.asyncio
    async def test_pipeline_sets_failed_on_error(self, db, admin_user):
        """Pipeline must transition collection to FAILED on LLM error."""
        from app.schemas.collection import CollectionCreate

        data = CollectionCreate(
            name="Failure Test",
            query="This will fail",
            collection_type="smart",
            visibility="private",
        )
        collection = await collection_service.create_collection_shell(
            collection_data=data, user=admin_user, db=db
        )

        with patch.object(
            collection_service.intent_parser, "parse_intent",
            new_callable=AsyncMock,
            side_effect=Exception("LLM connection refused"),
        ):
            with pytest.raises(Exception, match="LLM connection refused"):
                await collection_service.build_collection_pipeline(
                    collection_id=collection.id,
                    user_id=admin_user.id,
                    db=db,
                )

        # Refresh from DB
        db.refresh(collection)
        assert collection.status == CollectionStatus.FAILED
        assert "LLM connection refused" in collection.build_error

    @pytest.mark.asyncio
    async def test_pipeline_gathers_matching_documents(self, db, admin_user):
        """Pipeline must populate collection items from search results."""
        from app.schemas.collection import CollectionCreate

        # Seed documents
        docs = []
        for i in range(5):
            doc = Document(
                filename=f"solar_report_{i}.pdf",
                original_filename=f"solar_report_{i}.pdf",
                file_path=f"/data/public/solar_report_{i}.pdf",
                bucket=DocumentBucket.PUBLIC,
                status=DocumentStatus.INDEXED,
                size=1024,
                mime_type="application/pdf",
            )
            db.add(doc)
            docs.append(doc)
        db.commit()
        for doc in docs:
            db.refresh(doc)

        data = CollectionCreate(
            name="Gathering Test",
            query="solar reports",
            collection_type="smart",
            visibility="private",
        )
        collection = await collection_service.create_collection_shell(
            collection_data=data, user=admin_user, db=db
        )

        mock_intent = ParsedIntent(
            query="solar reports",
            keywords=["solar", "reports"],
            date_range={"type": "all_time"},
            entities=[],
            document_types=["all"],
            collection_name="Solar Reports",
            confidence=0.9,
        )

        # Mock search to return our seeded docs
        mock_search_results = [
            MagicMock(document_id=doc.id) for doc in docs
        ]

        async def _instant_llm(*args, **kwargs):
            yield "Summary of solar reports collection."

        with patch.object(
            collection_service.intent_parser, "parse_intent",
            new_callable=AsyncMock, return_value=mock_intent,
        ), patch.object(
            collection_service.search_service, "hybrid_search",
            new_callable=AsyncMock,
            return_value={"results": mock_search_results, "total": 5, "query": "solar reports"},
        ), patch(
            "app.services.openrouter_service.openrouter_service.chat_completion",
            side_effect=_instant_llm,
        ):
            result = await collection_service.build_collection_pipeline(
                collection_id=collection.id,
                user_id=admin_user.id,
                db=db,
            )

        assert result.document_count == 5
        assert result.status == CollectionStatus.READY

        # Verify collection items were created
        items = db.query(CollectionItem).filter(
            CollectionItem.collection_id == collection.id
        ).all()
        assert len(items) == 5
        item_doc_ids = {item.document_id for item in items}
        expected_doc_ids = {doc.id for doc in docs}
        assert item_doc_ids == expected_doc_ids


class TestLLMRoutingAccuracy:
    """Verify confidential documents route to Ollama, public to OpenRouter."""

    @pytest.mark.asyncio
    async def test_confidential_docs_use_ollama_for_summary(self):
        """When documents include confidential, summary must use Ollama."""
        mock_docs = [
            MagicMock(
                filename="public.pdf",
                bucket=DocumentBucket.PUBLIC,
                created_at=datetime.now(),
            ),
            MagicMock(
                filename="secret.pdf",
                bucket=DocumentBucket.CONFIDENTIAL,
                created_at=datetime.now(),
            ),
        ]
        mock_intent = MagicMock()
        mock_intent.keywords = ["test"]
        mock_intent.entities = []

        with patch.object(
            collection_service.ollama_service, "generate",
            new_callable=AsyncMock,
            return_value="Confidential summary via Ollama",
        ) as mock_ollama:
            summary = await collection_service._generate_collection_summary(
                collection_name="Mixed",
                query="test",
                documents=mock_docs,
                parsed_intent=mock_intent,
            )

            mock_ollama.assert_called_once()
            assert summary == "Confidential summary via Ollama"

    @pytest.mark.asyncio
    async def test_public_docs_use_openrouter_for_summary(self):
        """When all documents are public, summary must use OpenRouter."""
        mock_docs = [
            MagicMock(
                filename="public1.pdf",
                bucket=DocumentBucket.PUBLIC,
                created_at=datetime.now(),
            ),
            MagicMock(
                filename="public2.pdf",
                bucket=DocumentBucket.PUBLIC,
                created_at=datetime.now(),
            ),
        ]
        mock_intent = MagicMock()
        mock_intent.keywords = ["test"]
        mock_intent.entities = []

        async def _openrouter_response(*args, **kwargs):
            yield "Public summary via OpenRouter"

        with patch(
            "app.services.openrouter_service.openrouter_service.chat_completion",
            side_effect=_openrouter_response,
        ) as mock_or:
            summary = await collection_service._generate_collection_summary(
                collection_name="Public Only",
                query="test",
                documents=mock_docs,
                parsed_intent=mock_intent,
            )

            assert "Public summary via OpenRouter" in summary

    @pytest.mark.asyncio
    async def test_admin_intent_parsing_uses_ollama(self):
        """Admin/superuser intent parsing should use Ollama path."""
        mock_intent = ParsedIntent(
            query="test", keywords=["test"], collection_name="Test",
            confidence=0.9,
        )

        async def _ollama_response(*args, **kwargs):
            yield '{"keywords": ["test"], "date_range": {"type": "all_time"}, "entities": [], "document_types": ["all"], "collection_name": "Test"}'

        with patch(
            "app.services.ollama_service.ollama_service.chat_completion",
            side_effect=_ollama_response,
        ) as mock_ollama:
            result = await collection_service.intent_parser.parse_intent(
                query="test", user_language="en", use_ollama=True,
            )
            mock_ollama.assert_called_once()


class TestRefreshEndpointStillWorks:
    """Refresh uses the old synchronous path — make sure it still works."""

    def test_refresh_returns_200(
        self, client: TestClient, db: Session, admin_headers: dict, admin_user: User
    ):
        """POST /collections/{id}/refresh must still return 200."""
        collection = Collection(
            user_id=admin_user.id,
            name="Refresh Test",
            query="test",
            collection_type="smart",
            visibility="private",
            status=CollectionStatus.READY,
            document_count=5,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        mock_intent = MagicMock()
        mock_intent.keywords = ["test"]
        mock_intent.entities = []
        mock_intent.document_types = ["all"]
        mock_intent.date_range = {"type": "all_time"}
        mock_intent.collection_name = "Refresh Test"
        mock_intent.confidence = 0.9
        mock_intent.to_dict.return_value = {"keywords": ["test"]}
        mock_intent.to_search_filter.return_value = {}

        async def _instant(*a, **k):
            yield "Refreshed summary"

        with patch.object(
            collection_service.intent_parser, "parse_intent",
            new_callable=AsyncMock, return_value=mock_intent,
        ), patch.object(
            collection_service.search_service, "hybrid_search",
            new_callable=AsyncMock,
            return_value={"results": [], "total": 0, "query": "test"},
        ), patch(
            "app.services.openrouter_service.openrouter_service.chat_completion",
            side_effect=_instant,
        ):
            response = client.post(
                f"/api/v1/collections/{collection.id}/refresh",
                headers=admin_headers,
            )

        assert response.status_code == 200
```

- [ ] **Step 2: Run all integration tests**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/integration/test_collection_pipeline.py -v --tb=short
```

Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
cd /home/development/src/active/sowknow4 && git add backend/tests/integration/test_collection_pipeline.py && git commit -m "test(collections): add pipeline correctness, LLM routing, and error recovery tests"
```

---

## Task 12: Full regression run and deployment verification

Run ALL collection tests together, then document the deployment steps.

**Files:** None (verification only)

- [ ] **Step 1: Run full collection test suite**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest \
  tests/unit/test_collection_stats_bug.py \
  tests/unit/test_collection_creation_async.py \
  tests/unit/test_collection_cache_invalidation.py \
  tests/unit/test_collection_export_unit.py \
  tests/integration/test_collection_pipeline.py \
  tests/e2e/test_smart_collection_creation.py \
  tests/e2e/test_smart_collections_spec.py \
  -v --tb=short 2>&1 | tail -30
```

Expected: All PASS, zero failures.

- [ ] **Step 2: Run existing unit test suite for regressions**

```bash
cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```

Expected: No new failures.

- [ ] **Step 3: Verify nginx config in both files**

```bash
grep -A5 "location /api/v1/collections" /home/development/src/active/sowknow4/nginx/nginx.conf
grep -A5 "location /api/v1/collections" /home/development/src/active/sowknow4/nginx/nginx-http-only.conf
```

Expected: Both show `proxy_read_timeout 300s;`

- [ ] **Step 4: Verify frontend builds**

```bash
cd /home/development/src/active/sowknow4/frontend && npm run build 2>&1 | tail -10
```

Expected: Build succeeds with no errors.

- [ ] **Step 5: Document deployment checklist**

Print to console (not a file) for the operator:

```
DEPLOYMENT CHECKLIST — Smart Collections Remediation
=====================================================
1. Run Alembic migration: docker exec sowknow4-backend alembic upgrade head
2. Rebuild backend: docker compose build backend
3. Rebuild celery-worker: docker compose build celery-worker
4. Rebuild frontend: docker compose build frontend
5. Copy nginx configs to production: scp nginx/*.conf production:/var/docker/sowknow4/nginx/
6. Reload nginx: docker exec sowknow4-nginx nginx -s reload
7. Restart services: docker compose up -d backend celery-worker frontend
8. Verify health: docker compose ps (all containers healthy)
9. Test: Create a collection from the UI — should get instant 202, then poll to ready
10. Monitor: docker logs sowknow4-celery-worker -f (watch for build_smart_collection tasks)
```

---

## Summary of Changes

| Root Cause | Fix | Verified By |
|-----------|-----|-------------|
| #1 Synchronous LLM pipeline (504s) | Async Celery task + 202 response | `test_create_returns_202_with_building_status`, `test_create_dispatches_celery_task` |
| #2 Hybrid search 8s timeout | Increased to 20s | `test_gather_passes_20s_timeout` |
| #3 Missing `await` on stats | Added `await` | `test_stats_endpoint_returns_json` |
| #4 No async offloading | Celery `build_smart_collection` task | `test_task_is_registered`, `test_task_calls_pipeline` |
| #5 Nginx timeout too low | Dedicated 300s collections location | Manual nginx config check |
| #6 Frontend no feedback | Polling + building indicator | Frontend build verification |
| #7 DB pool exhaustion | Resolved by moving LLM pipeline off HTTP thread | Implicit — no long-running HTTP connections |

| Correctness Test | What It Proves |
|-----------------|---------------|
| `test_pipeline_sets_ready_on_success` | BUILDING → READY transition works end-to-end |
| `test_pipeline_sets_failed_on_error` | BUILDING → FAILED transition captures error message |
| `test_pipeline_gathers_matching_documents` | Collection items match search results exactly |
| `test_confidential_docs_use_ollama` | Privacy routing is correct — no PII to cloud |
| `test_public_docs_use_openrouter` | Cost-optimized path works for public docs |
| `test_admin_intent_parsing_uses_ollama` | Admin queries route through Ollama |
| `test_refresh_returns_200` | Existing refresh endpoint not broken |
| `test_list_includes_building_collections` | Users see their in-progress collections |
| `test_status_returns_building/ready/failed` | Polling endpoint works for all states |
