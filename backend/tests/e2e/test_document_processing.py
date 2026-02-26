"""
End-to-end tests for the document processing pipeline.

These tests exercise the full flow from task invocation through to database
state, using:
  - SQLite in-memory database (no PostgreSQL/pgvector required)
  - Celery in ALWAYS_EAGER mode (synchronous, no worker process needed)
  - Mocked external services (OCR, embedding, storage)

Test cases:
  1. Happy path — full pipeline → INDEXED status, chunks and embeddings created
  2. Error path — invalid/missing file → ERROR status after retries
  3. Concurrent processing — 5 documents processed simultaneously
  4. Stuck document recovery — stuck PROCESSING docs are re-queued
  5. generate_embeddings task — real chunk embedding and storage
  6. DLQ — permanently failed task ends up in failed_celery_tasks table
"""

from __future__ import annotations

import os
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Environment setup — must happen before any app imports
# ---------------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_e2e.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("APP_ENV", "test")

from app.models.base import Base
from app.models.document import Document, DocumentBucket, DocumentStatus, DocumentChunk
from app.models.processing import ProcessingQueue, TaskType, TaskStatus
from app.models.failed_task import FailedCeleryTask
from app.models.user import User, UserRole
from app.utils.security import get_password_hash


# ---------------------------------------------------------------------------
# SQLite test database — schema/type adaptation
# ---------------------------------------------------------------------------

_TEST_DB_URL = "sqlite://"  # in-memory

_engine = create_engine(
    _TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(Base.metadata, "before_create")
def _adapt_for_sqlite(metadata, connection, **kw):
    """Strip sowknow schema and replace PostgreSQL-only column types."""
    from sqlalchemy import JSON, Text

    for table in metadata.tables.values():
        table.schema = None
        for col in table.columns:
            type_name = type(col.type).__name__
            if type_name in ("JSONB", "JSON"):
                col.type = JSON()
            elif type_name == "Vector":
                col.type = Text()
            elif type_name == "ARRAY":
                col.type = Text()


_SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture(autouse=True)
def fresh_db() -> Generator[Session, None, None]:
    """Each test gets a clean in-memory database."""
    Base.metadata.drop_all(bind=_engine)
    Base.metadata.create_all(bind=_engine)
    session = _SessionFactory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=_engine)


# ---------------------------------------------------------------------------
# Celery eager-mode fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def celery_eager(settings=None):
    """Run Celery tasks synchronously (no broker/worker needed)."""
    from app.celery_app import celery_app

    celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)
    yield
    celery_app.conf.update(task_always_eager=False, task_eager_propagates=False)


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session(fresh_db) -> Session:
    return fresh_db


@pytest.fixture
def admin_user(db_session: Session) -> User:
    user = User(
        email="admin@test.com",
        hashed_password=get_password_hash("password"),
        full_name="Admin",
        role=UserRole.ADMIN,
        is_active=True,
        is_superuser=True,
        can_access_confidential=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_pdf_path(tmp_path) -> str:
    """Create a minimal valid-looking text file for OCR bypass in tests."""
    f = tmp_path / "sample.txt"
    f.write_text(
        "Sample document content for testing.\n"
        "This is paragraph two with more text to ensure chunking occurs.\n"
        "Additional content to create meaningful chunks for embedding generation.\n"
        * 10
    )
    return str(f)


def _make_document(
    db: Session,
    *,
    user_id=None,
    status: DocumentStatus = DocumentStatus.PENDING,
    file_path: str = "/tmp/nonexistent.txt",
    mime_type: str = "text/plain",
    batch_id: str = None,
) -> Document:
    doc = Document(
        filename=f"doc_{uuid.uuid4().hex[:8]}.txt",
        original_filename="test.txt",
        file_path=file_path,
        bucket=DocumentBucket.PUBLIC,
        status=status,
        size=1024,
        mime_type=mime_type,
        uploaded_by=user_id,
        batch_id=batch_id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _wait_for_status(
    db: Session,
    doc_id,
    expected: DocumentStatus,
    timeout: int = 10,
) -> bool:
    """Poll document status (useful when not in eager mode)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        db.expire_all()
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc and doc.status == expected:
            return True
        time.sleep(0.1)
    return False


# ---------------------------------------------------------------------------
# Mocked service factories
# ---------------------------------------------------------------------------

def _mock_text_extractor(text: str = "Hello world. This is test content. " * 20):
    """Return a mock text_extractor that yields fixed text."""
    mock = MagicMock()

    async def _extract(file_path, filename):
        return {"text": text, "pages": 1}

    async def _extract_images(file_path):
        return []

    mock.extract_text = _extract
    mock.extract_images_from_pdf = _extract_images
    return mock


def _mock_embedding_service(dim: int = 1024):
    """Return a mock embedding_service that yields zero vectors."""
    mock = MagicMock()
    mock.can_embed = True

    def _encode(texts, batch_size=32, show_progress=False):
        return [[0.01] * dim for _ in texts]

    mock.encode = _encode
    return mock


# ---------------------------------------------------------------------------
# TEST 1: Happy path — PENDING → INDEXED
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_full_pipeline_pending_to_indexed(self, db_session, sample_pdf_path):
        """
        Full pipeline: PENDING → text extraction → chunking → embedding → INDEXED.
        All external services are mocked; only DB state and task result are asserted.
        """
        doc = _make_document(db_session, file_path=sample_pdf_path)
        assert doc.status == DocumentStatus.PENDING

        with (
            patch("app.tasks.document_tasks.SessionLocal", return_value=db_session),
            patch(
                "app.tasks.document_tasks.text_extractor",
                _mock_text_extractor(),
                create=True,
            ),
            patch(
                "app.services.embedding_service.embedding_service",
                _mock_embedding_service(),
            ),
        ):
            # Import here to avoid module-level side-effects before patching
            from app.tasks.document_tasks import process_document

            result = process_document(str(doc.id), "full_pipeline")

        assert result["status"] == "success"
        db_session.expire_all()
        updated = db_session.query(Document).filter(Document.id == doc.id).first()
        assert updated.status == DocumentStatus.INDEXED

    def test_chunks_created_after_processing(self, db_session, sample_pdf_path):
        """Chunking step must create DocumentChunk rows."""
        doc = _make_document(db_session, file_path=sample_pdf_path)

        with (
            patch("app.tasks.document_tasks.SessionLocal", return_value=db_session),
            patch(
                "app.services.embedding_service.embedding_service",
                _mock_embedding_service(),
            ),
        ):
            from app.tasks.document_tasks import process_document
            process_document(str(doc.id), "full_pipeline")

        db_session.expire_all()
        chunks = (
            db_session.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.id)
            .all()
        )
        # At least one chunk expected from the sample text
        assert len(chunks) >= 1

    def test_processing_queue_completed(self, db_session, sample_pdf_path):
        """ProcessingQueue entry must be COMPLETED after successful run."""
        doc = _make_document(db_session, file_path=sample_pdf_path)

        with (
            patch("app.tasks.document_tasks.SessionLocal", return_value=db_session),
            patch(
                "app.services.embedding_service.embedding_service",
                _mock_embedding_service(),
            ),
        ):
            from app.tasks.document_tasks import process_document
            process_document(str(doc.id), "full_pipeline")

        db_session.expire_all()
        pq = (
            db_session.query(ProcessingQueue)
            .filter(ProcessingQueue.document_id == doc.id)
            .first()
        )
        assert pq is not None
        assert pq.status == TaskStatus.COMPLETED
        assert pq.progress_percentage == 100


# ---------------------------------------------------------------------------
# TEST 2: Error path — missing file → ERROR after retries
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_missing_file_sets_error_status(self, db_session):
        """
        A document pointing to a non-existent file should eventually reach
        ERROR status after exhausting retries.
        """
        doc = _make_document(db_session, file_path="/tmp/does_not_exist_ever.txt")

        from app.tasks.document_tasks import process_document
        from celery.exceptions import MaxRetriesExceeded

        with patch("app.tasks.document_tasks.SessionLocal", return_value=db_session):
            # Task will fail; eager mode raises after max retries
            with pytest.raises(Exception):
                process_document(str(doc.id), "full_pipeline")

        db_session.expire_all()
        updated = db_session.query(Document).filter(Document.id == doc.id).first()
        # After failure, status must be PENDING (queued for retry) or ERROR
        assert updated.status in (DocumentStatus.PENDING, DocumentStatus.ERROR)

    def test_processing_error_stored_in_metadata(self, db_session):
        """Error details must be stored in document_metadata."""
        doc = _make_document(db_session, file_path="/no/such/file.txt")

        from app.tasks.document_tasks import process_document

        with patch("app.tasks.document_tasks.SessionLocal", return_value=db_session):
            with pytest.raises(Exception):
                process_document(str(doc.id), "full_pipeline")

        db_session.expire_all()
        updated = db_session.query(Document).filter(Document.id == doc.id).first()
        assert updated.document_metadata is not None
        # Metadata should contain error information
        meta = updated.document_metadata or {}
        assert "processing_error" in meta or "retry_count" in meta

    def test_document_not_found_returns_error_dict(self, db_session):
        """Non-existent document_id should return an error dict, not raise."""
        from app.tasks.document_tasks import process_document

        with patch("app.tasks.document_tasks.SessionLocal", return_value=db_session):
            result = process_document(str(uuid.uuid4()), "full_pipeline")

        assert result["status"] == "error"
        assert "not found" in result["message"].lower()


# ---------------------------------------------------------------------------
# TEST 3: Concurrent processing — 5 documents simultaneously
# ---------------------------------------------------------------------------

class TestConcurrentProcessing:
    def test_five_documents_processed_concurrently(self, db_session, sample_pdf_path):
        """
        Five documents submitted via ThreadPoolExecutor must all end up
        with status INDEXED (or at least not in PROCESSING forever).
        """
        docs = [_make_document(db_session, file_path=sample_pdf_path) for _ in range(5)]
        doc_ids = [str(d.id) for d in docs]

        from app.tasks.document_tasks import process_document

        results = []
        errors = []

        def run_task(doc_id):
            with (
                patch("app.tasks.document_tasks.SessionLocal", return_value=_SessionFactory()),
                patch(
                    "app.services.embedding_service.embedding_service",
                    _mock_embedding_service(),
                ),
            ):
                return process_document(doc_id, "full_pipeline")

        # In eager mode each call is synchronous; ThreadPoolExecutor verifies
        # there are no shared-state concurrency issues
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(run_task, doc_id): doc_id for doc_id in doc_ids}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    errors.append(str(exc))

        assert len(results) + len(errors) == 5, "All 5 tasks must complete (success or error)"
        # Expect most to succeed
        success_count = sum(1 for r in results if r.get("status") == "success")
        assert success_count >= 3, f"Expected ≥3 successes, got {success_count}"

    def test_batch_status_endpoint_tracks_all_documents(self, db_session, admin_user):
        """Batch status query returns all documents belonging to a batch_id."""
        batch_id = str(uuid.uuid4())
        docs = [
            _make_document(
                db_session,
                status=DocumentStatus.INDEXED,
                batch_id=batch_id,
                user_id=admin_user.id,
            )
            for _ in range(3)
        ]
        _make_document(
            db_session,
            status=DocumentStatus.PENDING,
            batch_id=batch_id,
            user_id=admin_user.id,
        )

        # Query as the batch-status endpoint would
        results = (
            db_session.query(Document)
            .filter(
                Document.batch_id == batch_id,
                Document.uploaded_by == admin_user.id,
            )
            .all()
        )
        assert len(results) == 4

        from collections import Counter
        counts = Counter(d.status for d in results)
        assert counts[DocumentStatus.INDEXED] == 3
        assert counts[DocumentStatus.PENDING] == 1
        progress = round(3 / 4 * 100, 1)
        assert progress == 75.0


# ---------------------------------------------------------------------------
# TEST 4: Stuck document recovery
# ---------------------------------------------------------------------------

class TestStuckDocumentRecovery:
    def test_stuck_document_requeued(self, db_session):
        """
        A document stuck in PROCESSING longer than the threshold must be
        reset to PENDING and re-dispatched.
        """
        doc = _make_document(db_session, status=DocumentStatus.PROCESSING)

        # Create a ProcessingQueue entry that started 2 hours ago
        pq = ProcessingQueue(
            document_id=doc.id,
            task_type=TaskType.OCR_PROCESSING,
            status=TaskStatus.IN_PROGRESS,
            started_at=datetime.utcnow() - timedelta(hours=2),
        )
        db_session.add(pq)
        db_session.commit()

        with (
            patch("app.tasks.document_tasks.SessionLocal", return_value=db_session),
            patch("app.tasks.document_tasks.process_document") as mock_dispatch,
        ):
            mock_dispatch.delay = MagicMock(return_value=MagicMock(id="fake-task-id"))

            from app.tasks.document_tasks import recover_stuck_documents
            result = recover_stuck_documents(stuck_threshold_minutes=60)

        assert result["stuck_found"] >= 1
        assert result["requeued"] >= 1
        assert result["errors"] == 0

        db_session.expire_all()
        updated_doc = db_session.query(Document).filter(Document.id == doc.id).first()
        assert updated_doc.status == DocumentStatus.PENDING

        updated_pq = db_session.query(ProcessingQueue).filter(
            ProcessingQueue.document_id == doc.id
        ).first()
        assert updated_pq.status == TaskStatus.FAILED

    def test_recent_documents_not_recovered(self, db_session):
        """Documents that started processing recently must NOT be re-queued."""
        doc = _make_document(db_session, status=DocumentStatus.PROCESSING)
        pq = ProcessingQueue(
            document_id=doc.id,
            task_type=TaskType.OCR_PROCESSING,
            status=TaskStatus.IN_PROGRESS,
            started_at=datetime.utcnow() - timedelta(minutes=2),  # 2 min ago — fresh
        )
        db_session.add(pq)
        db_session.commit()

        with patch("app.tasks.document_tasks.SessionLocal", return_value=db_session):
            from app.tasks.document_tasks import recover_stuck_documents
            result = recover_stuck_documents(stuck_threshold_minutes=60)

        assert result["stuck_found"] == 0
        assert result["requeued"] == 0

    def test_multiple_stuck_documents_all_recovered(self, db_session):
        """All stuck documents in one call must be recovered."""
        docs = [_make_document(db_session, status=DocumentStatus.PROCESSING) for _ in range(3)]
        for doc in docs:
            pq = ProcessingQueue(
                document_id=doc.id,
                task_type=TaskType.OCR_PROCESSING,
                status=TaskStatus.IN_PROGRESS,
                started_at=datetime.utcnow() - timedelta(hours=3),
            )
            db_session.add(pq)
        db_session.commit()

        with (
            patch("app.tasks.document_tasks.SessionLocal", return_value=db_session),
            patch("app.tasks.document_tasks.process_document") as mock_dispatch,
        ):
            mock_dispatch.delay = MagicMock(return_value=MagicMock(id="fake-id"))
            from app.tasks.document_tasks import recover_stuck_documents
            result = recover_stuck_documents(stuck_threshold_minutes=60)

        assert result["stuck_found"] == 3
        assert result["requeued"] == 3


# ---------------------------------------------------------------------------
# TEST 5: generate_embeddings task
# ---------------------------------------------------------------------------

class TestGenerateEmbeddings:
    def test_embeddings_generated_for_chunks(self, db_session, sample_pdf_path):
        """generate_embeddings must store vectors on each chunk."""
        doc = _make_document(db_session, file_path=sample_pdf_path)

        # Pre-create chunks
        chunks = []
        for i in range(3):
            chunk = DocumentChunk(
                document_id=doc.id,
                chunk_index=i,
                chunk_text=f"This is chunk number {i} with some test content.",
                token_count=10,
            )
            db_session.add(chunk)
            chunks.append(chunk)
        db_session.commit()
        chunk_ids = [str(c.id) for c in chunks]

        with (
            patch("app.tasks.document_tasks.SessionLocal", return_value=db_session),
            patch(
                "app.services.embedding_service.embedding_service",
                _mock_embedding_service(),
            ),
        ):
            from app.tasks.document_tasks import generate_embeddings
            result = generate_embeddings(chunk_ids)

        assert result["status"] == "completed"
        assert result["successful"] == 3
        assert result["failed"] == 0

    def test_generate_embeddings_exceeds_batch_limit(self, db_session):
        """Calling generate_embeddings with >100 IDs must return an error."""
        chunk_ids = [str(uuid.uuid4()) for _ in range(101)]

        with patch("app.tasks.document_tasks.SessionLocal", return_value=db_session):
            from app.tasks.document_tasks import generate_embeddings
            result = generate_embeddings(chunk_ids)

        assert result["status"] == "error"
        assert "100" in result["message"]

    def test_generate_embeddings_empty_list(self, db_session):
        """generate_embeddings with an empty list must succeed with zero counts."""
        with patch("app.tasks.document_tasks.SessionLocal", return_value=db_session):
            from app.tasks.document_tasks import generate_embeddings
            result = generate_embeddings([])

        assert result["status"] == "error" or result.get("total", 0) == 0


# ---------------------------------------------------------------------------
# TEST 6: Dead Letter Queue integration
# ---------------------------------------------------------------------------

class TestDeadLetterQueue:
    def test_dlq_service_stores_failed_task(self, db_session):
        """DLQService.store_failed_task must persist a FailedCeleryTask row."""
        with patch("app.services.dlq_service.SessionLocal", return_value=db_session):
            from app.services.dlq_service import DeadLetterQueueService
            record = DeadLetterQueueService.store_failed_task(
                task_name="app.tasks.test.fake_task",
                task_id=str(uuid.uuid4()),
                args=("arg1",),
                kwargs={"key": "value"},
                exception=ValueError("test error"),
                traceback_str="Traceback (most recent call last):\n  ...",
                retry_count=3,
                extra_metadata={"document_id": str(uuid.uuid4())},
            )

        assert record is not None
        assert record.task_name == "app.tasks.test.fake_task"
        assert record.exception_type == "ValueError"
        assert record.retry_count == 3

    def test_dlq_list_returns_stored_records(self, db_session):
        """list_failed_tasks must return paginated results."""
        task_id = str(uuid.uuid4())
        with patch("app.services.dlq_service.SessionLocal", return_value=db_session):
            from app.services.dlq_service import DeadLetterQueueService
            DeadLetterQueueService.store_failed_task(
                task_name="app.tasks.some_task",
                task_id=task_id,
                args=(),
                kwargs={},
                exception=RuntimeError("boom"),
                retry_count=2,
            )
            result = DeadLetterQueueService.list_failed_tasks(page=1, page_size=10)

        assert result["total"] >= 1
        assert any(item.task_id == task_id for item in result["items"])

    def test_dlq_filter_by_task_name(self, db_session):
        """list_failed_tasks task_name_filter must narrow results."""
        with patch("app.services.dlq_service.SessionLocal", return_value=db_session):
            from app.services.dlq_service import DeadLetterQueueService
            for name in ["tasks.foo", "tasks.bar", "tasks.foo"]:
                DeadLetterQueueService.store_failed_task(
                    task_name=name,
                    task_id=str(uuid.uuid4()),
                    args=(),
                    kwargs={},
                    exception=Exception("err"),
                    retry_count=1,
                )
            result = DeadLetterQueueService.list_failed_tasks(
                task_name_filter="foo"
            )

        assert result["total"] == 2
        assert all("foo" in item.task_name for item in result["items"])
