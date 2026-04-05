# Pipeline Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the document processing pipeline that has a 100% failure rate for April 2-4 uploads, backfill missing embeddings/articles, and harden recovery tasks.

**Architecture:** Two parallel tracks -- Track A is a hotfix to the `already_queued` NameError in `anomaly_tasks.py` plus a batch reprocess of 2,238 failed documents. Track B fixes error capture, consolidates duplicate recovery logic, and creates a `backfill_tasks.py` module for embedding/article backfills.

**Tech Stack:** Python, Celery, SQLAlchemy, PostgreSQL, pytest (SQLite unit tests with mock patching)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `backend/app/tasks/anomaly_tasks.py` | **Modify** -- Fix NameError (line 680), improve error capture in all 3 recovery functions, standardize metadata keys |
| `backend/app/tasks/document_tasks.py` | **Modify** -- Remove duplicate `recover_stuck_documents` function (lines 585-669) |
| `backend/app/tasks/backfill_tasks.py` | **Create** -- All backfill/reprocess tasks: embeddings, articles, article embeddings, failed doc reprocess |
| `backend/tests/unit/test_anomaly_tasks.py` | **Create** -- Unit tests for recovery task fixes |
| `backend/tests/unit/test_backfill_tasks.py` | **Create** -- Unit tests for backfill tasks |

---

## Task 1: Fix `already_queued` NameError (HOTFIX)

**Files:**
- Modify: `backend/app/tasks/anomaly_tasks.py:680`
- Test: `backend/tests/unit/test_anomaly_tasks.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_anomaly_tasks.py`:

```python
"""
Unit tests for anomaly recovery tasks.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentBucket, DocumentStatus
from app.tasks.anomaly_tasks import recover_pending_documents


def _make_pending_doc(db: Session, created_minutes_ago: int = 10) -> Document:
    """Create a PENDING document older than the recovery threshold."""
    doc = Document(
        id=uuid.uuid4(),
        filename="test_pending.pdf",
        original_filename="test_pending.pdf",
        file_path="/data/public/test_pending.pdf",
        mime_type="application/pdf",
        bucket=DocumentBucket.PUBLIC,
        status=DocumentStatus.PENDING,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=created_minutes_ago),
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=created_minutes_ago),
        document_metadata={},
    )
    db.add(doc)
    db.commit()
    return doc


def _run_pending_recovery(db: Session, threshold: int = 5) -> dict:
    """Run recover_pending_documents with the test db session."""
    mock_pd = Mock()
    mock_task = Mock()
    mock_task.id = "fake-celery-task-id"
    mock_pd.delay = Mock(return_value=mock_task)

    with patch("app.database.SessionLocal", return_value=db), \
         patch("app.tasks.document_tasks.process_document", mock_pd):
        original_close = db.close
        db.close = Mock()
        try:
            result = recover_pending_documents(pending_threshold_minutes=threshold)
        finally:
            db.close = original_close

    return result


class TestRecoverPendingDocuments:
    def test_does_not_crash_with_name_error(self, db: Session):
        """The critical bug: already_queued was undefined, causing NameError."""
        doc = _make_pending_doc(db, created_minutes_ago=10)
        # This must not raise NameError
        result = _run_pending_recovery(db)
        assert "recovered" in result
        assert "already_queued" in result
        assert "failed" in result

    def test_recovers_old_pending_document(self, db: Session):
        """A PENDING document older than threshold should be re-queued."""
        doc = _make_pending_doc(db, created_minutes_ago=10)
        result = _run_pending_recovery(db, threshold=5)
        assert len(result["recovered"]) == 1
        assert result["recovered"][0]["document_id"] == str(doc.id)

    def test_ignores_recent_pending_document(self, db: Session):
        """A PENDING document within threshold should NOT be re-queued."""
        doc = _make_pending_doc(db, created_minutes_ago=2)
        result = _run_pending_recovery(db, threshold=5)
        assert len(result["recovered"]) == 0
```

- [ ] **Step 2: Run the test to confirm it fails with NameError**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_anomaly_tasks.py -v -x 2>&1 | head -40`

Expected: FAIL with `NameError: name 'already_queued' is not defined`

- [ ] **Step 3: Fix the bug -- initialize `already_queued`**

In `backend/app/tasks/anomaly_tasks.py`, line 680, replace:

```python
    checked = []
```

with:

```python
    already_queued = []
```

- [ ] **Step 4: Run tests to verify the fix**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_anomaly_tasks.py -v`

Expected: All 3 tests PASS

- [ ] **Step 5: Commit the hotfix**

```bash
git add backend/app/tasks/anomaly_tasks.py backend/tests/unit/test_anomaly_tasks.py
git commit -m "fix: resolve NameError in recover_pending_documents (already_queued undefined)

The variable 'already_queued' was used at lines 754 and 807 but never
initialized (line 680 had 'checked' instead). This caused a silent
NameError every 5 minutes, preventing all document recovery since April 1.
Root cause of 2,831 ERROR documents (31.2% of all uploads)."
```

---

## Task 2: Improve error capture in recovery tasks

**Files:**
- Modify: `backend/app/tasks/anomaly_tasks.py:565-596` (recover_stuck_documents)
- Modify: `backend/app/tasks/anomaly_tasks.py:700-720` (recover_pending_documents)
- Modify: `backend/app/tasks/anomaly_tasks.py:895-916` (fail_stuck_processing_documents)
- Test: `backend/tests/unit/test_anomaly_tasks.py`

- [ ] **Step 1: Write failing test for error capture**

Append to `backend/tests/unit/test_anomaly_tasks.py`:

```python
from app.tasks.anomaly_tasks import recover_stuck_documents


def _make_processing_doc(db: Session, updated_minutes_ago: int = 30, recovery_count: int = 4) -> Document:
    """Create a PROCESSING document that has exceeded max recovery attempts."""
    doc = Document(
        id=uuid.uuid4(),
        filename="stuck_doc.pdf",
        original_filename="stuck_doc.pdf",
        file_path="/data/public/stuck_doc.pdf",
        mime_type="application/pdf",
        bucket=DocumentBucket.PUBLIC,
        status=DocumentStatus.PROCESSING,
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=updated_minutes_ago),
        document_metadata={"recovery_count": recovery_count, "celery_task_id": "old-task-id"},
    )
    db.add(doc)
    db.commit()
    return doc


def _run_stuck_recovery(db: Session, max_minutes: int = 5) -> dict:
    """Run recover_stuck_documents with the test db session."""
    mock_pd = Mock()
    mock_pd.delay = Mock(return_value=None)

    with patch("app.database.SessionLocal", return_value=db), \
         patch("app.tasks.document_tasks.process_document", mock_pd):
        original_close = db.close
        db.close = Mock()
        try:
            result = recover_stuck_documents(max_processing_minutes=max_minutes)
        finally:
            db.close = original_close

    return result


class TestRecoverStuckDocumentsErrorCapture:
    def test_permanently_failed_doc_captures_celery_traceback(self, db: Session):
        """When marking a doc as permanently failed, attempt to capture Celery task traceback."""
        doc = _make_processing_doc(db, updated_minutes_ago=30, recovery_count=4)

        mock_async_result = Mock()
        mock_async_result.traceback = "Traceback: OOM killed during OCR"

        with patch("celery.result.AsyncResult", return_value=mock_async_result):
            result = _run_stuck_recovery(db, max_minutes=5)

        db.refresh(doc)
        assert doc.status == DocumentStatus.ERROR
        meta = doc.document_metadata
        assert "actual_error" in meta
        assert "OOM killed" in meta["actual_error"]
```

- [ ] **Step 2: Run to confirm it fails**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_anomaly_tasks.py::TestRecoverStuckDocumentsErrorCapture -v -x`

Expected: FAIL -- `actual_error` not in metadata

- [ ] **Step 3: Add error capture to `recover_stuck_documents`**

In `backend/app/tasks/anomaly_tasks.py`, inside the `if recovery_count > MAX_RECOVERY_ATTEMPTS:` block (around line 571), add Celery traceback retrieval before setting the document status:

```python
                if recovery_count > MAX_RECOVERY_ATTEMPTS:
                    # Attempt to retrieve the actual Celery task error
                    actual_error = None
                    celery_task_id = existing_meta.get("celery_task_id")
                    if celery_task_id:
                        try:
                            from celery.result import AsyncResult
                            task_result = AsyncResult(celery_task_id)
                            if task_result.traceback:
                                actual_error = str(task_result.traceback)[:1000]
                        except Exception:
                            pass

                    doc.status = DocumentStatus.ERROR
                    doc.document_metadata = {
                        **existing_meta,
                        "recovery_count": recovery_count,
                        "recovered_from_stuck": True,
                        "stuck_duration_minutes": stuck_duration,
                        "recovered_at": datetime.now(timezone.utc).isoformat(),
                        "processing_error": (
                            f"Permanently failed: stuck in processing after {recovery_count} recovery attempts"
                        ),
                        "actual_error": actual_error or "No traceback available (task result expired or not found)",
                    }
```

- [ ] **Step 4: Apply same pattern to `recover_pending_documents`**

In `backend/app/tasks/anomaly_tasks.py`, inside the `if recovery_count > MAX_RECOVERY_ATTEMPTS:` block in `recover_pending_documents` (around line 703), add:

```python
                if recovery_count > MAX_RECOVERY_ATTEMPTS:
                    # Attempt to retrieve the actual Celery task error
                    actual_error = None
                    celery_task_id = existing_meta.get("celery_task_id")
                    if celery_task_id:
                        try:
                            from celery.result import AsyncResult
                            task_result = AsyncResult(celery_task_id)
                            if task_result.traceback:
                                actual_error = str(task_result.traceback)[:1000]
                        except Exception:
                            pass

                    doc.status = DocumentStatus.ERROR
                    doc.document_metadata = {
                        **existing_meta,
                        "pending_recovery_count": recovery_count,
                        "recovery_error": f"Failed to queue after {MAX_RECOVERY_ATTEMPTS} attempts",
                        "actual_error": actual_error or "No traceback available",
                    }
```

- [ ] **Step 5: Apply same pattern to `fail_stuck_processing_documents`**

In `backend/app/tasks/anomaly_tasks.py`, in the `fail_stuck_processing_documents` function (around line 902), add traceback retrieval before setting ERROR:

```python
            # Try to capture actual Celery error
            actual_error = None
            if celery_task_id:
                try:
                    from celery.result import AsyncResult
                    task_result = AsyncResult(celery_task_id)
                    if task_result.traceback:
                        actual_error = str(task_result.traceback)[:1000]
                except Exception:
                    pass

            existing_meta = doc.document_metadata or {}
            doc.status = DocumentStatus.ERROR
            doc.document_metadata = {
                **existing_meta,
                "failure_reason": f"Processing stuck > {max_processing_minutes} minutes, task {'not found in broker' if celery_task_id else 'never queued'}",
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "actual_error": actual_error or "No traceback available",
            }
```

- [ ] **Step 6: Run all anomaly tests**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_anomaly_tasks.py -v`

Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/tasks/anomaly_tasks.py backend/tests/unit/test_anomaly_tasks.py
git commit -m "fix: capture actual Celery traceback when marking documents as permanently failed

All three recovery tasks (recover_stuck_documents, recover_pending_documents,
fail_stuck_processing_documents) now attempt to retrieve the Celery task
traceback via AsyncResult before setting the generic error message."
```

---

## Task 3: Remove duplicate `recover_stuck_documents` from `document_tasks.py`

**Files:**
- Modify: `backend/app/tasks/document_tasks.py:585-669` -- remove function
- Test: `backend/tests/unit/test_document_tasks.py`

- [ ] **Step 1: Verify existing tests reference anomaly_tasks version**

Read `backend/tests/unit/test_document_tasks.py` line 14: it imports `from app.tasks.anomaly_tasks import recover_stuck_documents`. This confirms tests already use the correct version.

- [ ] **Step 2: Check celery_app.py beat schedule references**

The beat schedule at `backend/app/celery_app.py:101` references `"app.tasks.anomaly_tasks.recover_stuck_documents"` -- correct. The `document_tasks.py` version uses `name="app.tasks.document_tasks.recover_stuck_documents"` which is NOT in the beat schedule, so it's dead code.

- [ ] **Step 3: Delete the duplicate function**

Remove lines 585-669 from `backend/app/tasks/document_tasks.py` -- the entire `recover_stuck_documents` function and its `@shared_task` decorator. This includes:
- The `@shared_task` decorator (line 585)
- The function definition and body (lines 586-669)

- [ ] **Step 4: Run existing document_tasks tests**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_document_tasks.py -v`

Expected: All existing tests still PASS (they import from `anomaly_tasks`, not `document_tasks`)

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks/document_tasks.py
git commit -m "refactor: remove duplicate recover_stuck_documents from document_tasks.py

The canonical version lives in anomaly_tasks.py and is referenced by the
Celery Beat schedule. The document_tasks.py copy was dead code with
conflicting metadata keys and no retry limits."
```

---

## Task 4: Create backfill tasks module

**Files:**
- Create: `backend/app/tasks/backfill_tasks.py`
- Test: `backend/tests/unit/test_backfill_tasks.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_backfill_tasks.py`:

```python
"""
Unit tests for backfill tasks.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, call

import pytest
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentBucket, DocumentStatus


def _make_indexed_doc(db: Session, embedding_generated: bool = False, articles_generated: bool = False, chunk_count: int = 10) -> Document:
    doc = Document(
        id=uuid.uuid4(),
        filename="backfill_test.pdf",
        original_filename="backfill_test.pdf",
        file_path="/data/public/backfill_test.pdf",
        mime_type="application/pdf",
        bucket=DocumentBucket.PUBLIC,
        status=DocumentStatus.INDEXED,
        created_at=datetime.now(timezone.utc) - timedelta(days=3),
        updated_at=datetime.now(timezone.utc) - timedelta(days=3),
        ocr_processed=True,
        embedding_generated=embedding_generated,
        articles_generated=articles_generated,
        chunk_count=chunk_count,
        document_metadata={},
    )
    db.add(doc)
    db.commit()
    return doc


def _make_error_doc(db: Session, created_at: datetime = None) -> Document:
    doc = Document(
        id=uuid.uuid4(),
        filename="failed_doc.pdf",
        original_filename="failed_doc.pdf",
        file_path="/data/public/failed_doc.pdf",
        mime_type="application/pdf",
        bucket=DocumentBucket.PUBLIC,
        status=DocumentStatus.ERROR,
        created_at=created_at or datetime(2026, 4, 3, tzinfo=timezone.utc),
        updated_at=datetime.now(timezone.utc),
        document_metadata={
            "processing_error": "Permanently failed: stuck in processing after 4 recovery attempts",
            "recovery_count": 5,
        },
    )
    db.add(doc)
    db.commit()
    return doc


class TestReprocessFailedDocuments:
    def test_resets_error_docs_to_pending(self, db: Session):
        from app.tasks.backfill_tasks import reprocess_failed_documents

        doc = _make_error_doc(db, created_at=datetime(2026, 4, 3, tzinfo=timezone.utc))

        mock_pd = Mock()
        mock_task = Mock()
        mock_task.id = "new-task-id"
        mock_pd.apply_async = Mock(return_value=mock_task)

        with patch("app.database.SessionLocal", return_value=db), \
             patch("app.tasks.document_tasks.process_document", mock_pd):
            original_close = db.close
            db.close = Mock()
            try:
                result = reprocess_failed_documents("2026-04-02", "2026-04-05", batch_size=100, delay_seconds=0)
            finally:
                db.close = original_close

        assert result["total_reset"] == 1
        db.refresh(doc)
        assert doc.status == DocumentStatus.PENDING
        assert doc.document_metadata.get("recovery_count") == 0


class TestBackfillMissingEmbeddings:
    def test_queues_embedding_tasks_for_indexed_docs(self, db: Session):
        from app.tasks.backfill_tasks import backfill_missing_embeddings

        doc = _make_indexed_doc(db, embedding_generated=False, articles_generated=True)

        mock_embed = Mock()
        mock_embed.apply_async = Mock(return_value=Mock(id="embed-task-id"))

        with patch("app.database.SessionLocal", return_value=db), \
             patch("app.tasks.embedding_tasks.recompute_embeddings_for_document", mock_embed):
            original_close = db.close
            db.close = Mock()
            try:
                result = backfill_missing_embeddings(batch_size=100, delay_seconds=0)
            finally:
                db.close = original_close

        assert result["total_queued"] == 1
        mock_embed.apply_async.assert_called_once()


class TestBackfillMissingArticles:
    def test_queues_article_tasks_for_indexed_docs(self, db: Session):
        from app.tasks.backfill_tasks import backfill_missing_articles

        doc = _make_indexed_doc(db, embedding_generated=True, articles_generated=False, chunk_count=5)

        mock_gen = Mock()
        mock_gen.apply_async = Mock(return_value=Mock(id="article-task-id"))

        with patch("app.database.SessionLocal", return_value=db), \
             patch("app.tasks.article_tasks.generate_articles_for_document", mock_gen):
            original_close = db.close
            db.close = Mock()
            try:
                result = backfill_missing_articles(batch_size=100, delay_seconds=0)
            finally:
                db.close = original_close

        assert result["total_queued"] == 1
        mock_gen.apply_async.assert_called_once()
```

- [ ] **Step 2: Run tests to confirm they fail (module not found)**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_backfill_tasks.py -v -x 2>&1 | head -20`

Expected: `ModuleNotFoundError: No module named 'app.tasks.backfill_tasks'`

- [ ] **Step 3: Create `backfill_tasks.py`**

Create `backend/app/tasks/backfill_tasks.py`:

```python
"""
Backfill tasks for recovering from pipeline failures.

These tasks are designed to be run manually (via celery call or admin API)
to fix batches of documents that missed processing stages.
"""

import logging
from datetime import datetime, timezone

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="app.tasks.backfill_tasks.reprocess_failed_documents")
def reprocess_failed_documents(
    date_from: str,
    date_to: str,
    batch_size: int = 200,
    delay_seconds: int = 5,
) -> dict:
    """
    Reset ERROR documents back to PENDING for reprocessing.

    Targets documents that failed due to pipeline bugs (stuck processing,
    recovery task crashes), NOT genuine processing failures.

    Args:
        date_from: ISO date string (inclusive), e.g. "2026-04-02"
        date_to: ISO date string (exclusive), e.g. "2026-04-05"
        batch_size: Max documents to reset per invocation
        delay_seconds: Stagger delay between queued tasks
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.tasks.document_tasks import process_document

    db = SessionLocal()
    try:
        from_dt = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        to_dt = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)

        docs = (
            db.query(Document)
            .filter(
                Document.status == DocumentStatus.ERROR,
                Document.created_at >= from_dt,
                Document.created_at < to_dt,
            )
            .limit(batch_size)
            .all()
        )

        logger.info(f"Reprocess backfill: found {len(docs)} ERROR documents in [{date_from}, {date_to})")

        reset_count = 0
        for i, doc in enumerate(docs):
            meta = doc.document_metadata or {}
            doc.status = DocumentStatus.PENDING
            doc.document_metadata = {
                **meta,
                "recovery_count": 0,
                "pending_recovery_count": 0,
                "backfill_reset_at": datetime.now(timezone.utc).isoformat(),
                "original_error": meta.get("processing_error", "unknown"),
            }
            db.commit()

            process_document.apply_async(
                args=(str(doc.id),),
                countdown=i * delay_seconds,
            )
            reset_count += 1

        logger.info(f"Reprocess backfill: reset {reset_count} documents, stagger={delay_seconds}s")

        return {
            "status": "success",
            "date_from": date_from,
            "date_to": date_to,
            "total_reset": reset_count,
            "batch_size": batch_size,
        }

    except Exception as e:
        logger.error(f"Error in reprocess_failed_documents: {e}")
        db.rollback()
        raise

    finally:
        db.close()


@shared_task(name="app.tasks.backfill_tasks.backfill_missing_embeddings")
def backfill_missing_embeddings(
    batch_size: int = 10,
    delay_seconds: int = 30,
) -> dict:
    """
    Queue embedding generation for indexed documents that are missing embeddings.

    Args:
        batch_size: Max documents to process per invocation
        delay_seconds: Stagger delay between queued tasks (embeddings are CPU-heavy)
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.tasks.embedding_tasks import recompute_embeddings_for_document

    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(
                Document.status == DocumentStatus.INDEXED,
                Document.embedding_generated == False,  # noqa: E712
            )
            .limit(batch_size)
            .all()
        )

        logger.info(f"Embedding backfill: found {len(docs)} indexed documents without embeddings")

        queued = 0
        for i, doc in enumerate(docs):
            recompute_embeddings_for_document.apply_async(
                args=(str(doc.id),),
                countdown=i * delay_seconds,
            )
            queued += 1

        return {
            "status": "success",
            "total_queued": queued,
            "batch_size": batch_size,
            "delay_seconds": delay_seconds,
        }

    finally:
        db.close()


@shared_task(name="app.tasks.backfill_tasks.backfill_missing_articles")
def backfill_missing_articles(
    batch_size: int = 20,
    delay_seconds: int = 60,
) -> dict:
    """
    Queue article generation for indexed documents that are missing articles.

    Args:
        batch_size: Max documents to process per invocation
        delay_seconds: Stagger delay (article gen calls external LLM APIs)
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.tasks.article_tasks import generate_articles_for_document

    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(
                Document.status == DocumentStatus.INDEXED,
                Document.articles_generated == False,  # noqa: E712
                Document.chunk_count > 0,
            )
            .limit(batch_size)
            .all()
        )

        logger.info(f"Article backfill: found {len(docs)} indexed documents without articles")

        queued = 0
        for i, doc in enumerate(docs):
            generate_articles_for_document.apply_async(
                args=(str(doc.id),),
                countdown=i * delay_seconds,
            )
            queued += 1

        return {
            "status": "success",
            "total_queued": queued,
            "batch_size": batch_size,
            "delay_seconds": delay_seconds,
        }

    finally:
        db.close()


@shared_task(name="app.tasks.backfill_tasks.backfill_article_embeddings")
def backfill_article_embeddings(
    batch_size: int = 50,
    delay_seconds: int = 10,
) -> dict:
    """
    Queue embedding generation for articles stuck in PENDING status.

    Args:
        batch_size: Max articles to process per invocation
        delay_seconds: Stagger delay between batches
    """
    from app.database import SessionLocal
    from app.models.article import Article, ArticleStatus
    from app.tasks.article_tasks import generate_article_embeddings

    db = SessionLocal()
    try:
        articles = (
            db.query(Article)
            .filter(
                Article.status == ArticleStatus.PENDING,
                Article.embedding_vector == None,  # noqa: E711
            )
            .limit(batch_size)
            .all()
        )

        logger.info(f"Article embedding backfill: found {len(articles)} pending articles")

        if not articles:
            return {"status": "success", "total_queued": 0}

        article_ids = [str(a.id) for a in articles]
        generate_article_embeddings.apply_async(
            args=(article_ids,),
            countdown=delay_seconds,
        )

        return {
            "status": "success",
            "total_queued": len(article_ids),
            "batch_size": batch_size,
        }

    finally:
        db.close()
```

- [ ] **Step 4: Run all backfill tests**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_backfill_tasks.py -v`

Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks/backfill_tasks.py backend/tests/unit/test_backfill_tasks.py
git commit -m "feat: add backfill tasks for reprocessing failed docs and missing embeddings/articles

New module with 4 Celery tasks:
- reprocess_failed_documents: reset ERROR docs to PENDING in date range
- backfill_missing_embeddings: queue embedding gen for indexed docs
- backfill_missing_articles: queue article gen for indexed docs
- backfill_article_embeddings: queue embeddings for pending articles

All use staggered countdown delays to avoid overwhelming the worker."
```

---

## Task 5: Deploy hotfix and run reprocessing

**Files:** None (operational steps)

- [ ] **Step 1: Deploy the code changes to production**

```bash
cd /var/docker/sowknow4
git pull
docker compose up -d --build sowknow4-backend sowknow4-celery-worker sowknow4-celery-beat
```

Wait for all containers to show `(healthy)`:

```bash
docker ps --filter "name=sowknow4" --format "table {{.Names}}\t{{.Status}}"
```

- [ ] **Step 2: Verify the hotfix -- check Celery logs for recover_pending_documents**

```bash
docker logs sowknow4-celery-worker --tail 100 2>&1 | grep -E "recover_pending|already_queued|NameError"
```

Expected: `recover_pending_documents` succeeds without NameError. Should see "succeeded" messages.

- [ ] **Step 3: Verify the 198 stuck docs start processing**

Wait 10 minutes for recovery tasks to cycle, then check:

```bash
docker exec sowknow4-postgres psql -U sowknow -c "
SELECT status, COUNT(*) FROM documents
WHERE created_at >= '2026-04-04' AND status IN ('pending', 'processing')
GROUP BY status;"
```

Expected: Counts decreasing as docs process.

- [ ] **Step 4: Run the reprocess backfill for April 2-4 error docs**

```bash
docker exec sowknow4-celery-worker celery -A app.celery_app call \
  app.tasks.backfill_tasks.reprocess_failed_documents \
  --args='["2026-04-02", "2026-04-04", 200, 5]'
```

Repeat with different date ranges to cover all batches:

```bash
docker exec sowknow4-celery-worker celery -A app.celery_app call \
  app.tasks.backfill_tasks.reprocess_failed_documents \
  --args='["2026-04-04", "2026-04-06", 200, 5]'
```

Monitor progress:

```bash
docker exec sowknow4-postgres psql -U sowknow -c "
SELECT status, COUNT(*) FROM documents
WHERE created_at >= '2026-04-02'
GROUP BY status ORDER BY count DESC;"
```

- [ ] **Step 5: Run article generation backfill**

```bash
docker exec sowknow4-celery-worker celery -A app.celery_app call \
  app.tasks.backfill_tasks.backfill_missing_articles \
  --args='[20, 60]'
```

- [ ] **Step 6: Run article embedding backfill**

```bash
docker exec sowknow4-celery-worker celery -A app.celery_app call \
  app.tasks.backfill_tasks.backfill_article_embeddings \
  --args='[50, 10]'
```

- [ ] **Step 7: Start embedding backfill (long-running)**

```bash
docker exec sowknow4-celery-worker celery -A app.celery_app call \
  app.tasks.backfill_tasks.backfill_missing_embeddings \
  --args='[10, 30]'
```

Note: This processes 10 docs at a time with 30s stagger. For 4,084 docs, you'll need to call this multiple times or increase batch_size. Monitor:

```bash
docker exec sowknow4-postgres psql -U sowknow -c "
SELECT embedding_generated, COUNT(*) FROM documents
WHERE status = 'indexed'
GROUP BY embedding_generated;"
```

---

## Task 6: Final verification audit

**Files:** None (verification queries)

- [ ] **Step 1: Run full pipeline audit**

```bash
docker exec sowknow4-postgres psql -U sowknow -c "
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN status='indexed' THEN 1 ELSE 0 END) as indexed,
  SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors,
  SUM(CASE WHEN status IN ('pending','processing') THEN 1 ELSE 0 END) as in_progress,
  ROUND(100.0 * SUM(CASE WHEN embedding_generated THEN 1 ELSE 0 END) / COUNT(*), 1) as embed_pct,
  ROUND(100.0 * SUM(CASE WHEN articles_generated THEN 1 ELSE 0 END) / COUNT(*), 1) as article_pct
FROM documents;"
```

Expected targets:
- indexed > 95%
- errors < 5%
- embed_pct > 95% (may take hours for full backfill)
- article_pct > 95%

- [ ] **Step 2: Check articles status**

```bash
docker exec sowknow4-postgres psql -U sowknow -c "
SELECT status, COUNT(*) FROM articles GROUP BY status;"
```

Expected: pending < 100 (down from 1,167)

- [ ] **Step 3: Verify no new stuck documents**

```bash
docker exec sowknow4-postgres psql -U sowknow -c "
SELECT COUNT(*) FROM documents
WHERE status IN ('pending', 'processing')
AND updated_at < NOW() - INTERVAL '30 minutes';"
```

Expected: 0

- [ ] **Step 4: Check Celery worker health**

```bash
docker logs sowknow4-celery-worker --tail 20 2>&1 | grep -E "ERROR|NameError|traceback"
```

Expected: No NameError, no unhandled exceptions in recovery tasks
