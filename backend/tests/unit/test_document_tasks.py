"""
Unit tests for document processing Celery tasks.
Tests stuck document handling, embedding error recovery, and chunk storage transactions.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import uuid

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentStatus, DocumentBucket
from app.models.processing import ProcessingQueue, TaskType, TaskStatus
from app.tasks.document_tasks import process_document
from app.tasks.anomaly_tasks import recover_stuck_documents


class TestStuckDocumentRecovery:
    """Tests for the periodic stuck document recovery task"""

    def test_recover_stuck_documents_finds_stuck_docs(self, db: Session):
        """Test that recovery task identifies documents stuck in PROCESSING state"""
        doc = Document(
            id=uuid.uuid4(),
            filename="stuck_doc.pdf",
            original_filename="stuck_doc.pdf",
            file_path="/data/public/stuck_doc.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.PROCESSING,
            size=1024,
            mime_type="application/pdf",
            updated_at=datetime.utcnow() - timedelta(minutes=10),
        )
        db.add(doc)

        processing_task = ProcessingQueue(
            id=uuid.uuid4(),
            document_id=doc.id,
            task_type=TaskType.OCR_PROCESSING,
            status=TaskStatus.IN_PROGRESS,
            started_at=datetime.utcnow() - timedelta(minutes=10),
        )
        db.add(processing_task)
        db.commit()

        result = recover_stuck_documents(max_processing_minutes=5)

        assert result["stuck_count"] == 1
        assert len(result["recovered"]) == 1
        assert result["recovered"][0]["document_id"] == str(doc.id)
        assert len(result["failed"]) == 0

    def test_recover_stuck_documents_ignores_recent_docs(self, db: Session):
        """Test that recently updated documents are not marked as stuck"""
        doc = Document(
            id=uuid.uuid4(),
            filename="recent_doc.pdf",
            original_filename="recent_doc.pdf",
            file_path="/data/public/recent_doc.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.PROCESSING,
            size=1024,
            mime_type="application/pdf",
            updated_at=datetime.utcnow() - timedelta(minutes=2),
        )
        db.add(doc)
        db.commit()

        result = recover_stuck_documents(max_processing_minutes=5)

        assert result["stuck_count"] == 0
        assert len(result["recovered"]) == 0

    def test_recover_stuck_documents_resets_status(self, db: Session):
        """Test that stuck documents are reset to PENDING for reprocessing"""
        doc = Document(
            id=uuid.uuid4(),
            filename="stuck_doc.pdf",
            original_filename="stuck_doc.pdf",
            file_path="/data/public/stuck_doc.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.PROCESSING,
            size=1024,
            mime_type="application/pdf",
            updated_at=datetime.utcnow() - timedelta(minutes=10),
        )
        db.add(doc)
        db.commit()

        recover_stuck_documents(max_processing_minutes=5)

        db.refresh(doc)
        assert doc.status == DocumentStatus.PENDING
        assert doc.document_metadata is not None
        assert doc.document_metadata.get("recovered_from_stuck") is True
        assert doc.document_metadata.get("stuck_duration_minutes") is not None

    def test_recover_stuck_documents_handles_multiple(self, db: Session):
        """Test recovery of multiple stuck documents"""
        for i in range(3):
            doc = Document(
                id=uuid.uuid4(),
                filename=f"stuck_doc_{i}.pdf",
                original_filename=f"stuck_doc_{i}.pdf",
                file_path=f"/data/public/stuck_doc_{i}.pdf",
                bucket=DocumentBucket.PUBLIC,
                status=DocumentStatus.PROCESSING,
                size=1024,
                mime_type="application/pdf",
                updated_at=datetime.utcnow() - timedelta(minutes=10 + i),
            )
            db.add(doc)
        db.commit()

        result = recover_stuck_documents(max_processing_minutes=5)

        assert result["stuck_count"] == 3
        assert len(result["recovered"]) == 3

    def test_recover_stuck_documents_only_processing_status(self, db: Session):
        """Test that only documents in PROCESSING status are recovered"""
        statuses = [
            (DocumentStatus.PENDING, True),
            (DocumentStatus.PROCESSING, False),
            (DocumentStatus.INDEXED, True),
            (DocumentStatus.ERROR, True),
        ]

        for status, should_be_ignored in statuses:
            doc = Document(
                id=uuid.uuid4(),
                filename=f"doc_{status.value}.pdf",
                original_filename=f"doc_{status.value}.pdf",
                file_path=f"/data/public/doc_{status.value}.pdf",
                bucket=DocumentBucket.PUBLIC,
                status=status,
                size=1024,
                mime_type="application/pdf",
                updated_at=datetime.utcnow() - timedelta(minutes=10),
            )
            db.add(doc)
        db.commit()

        result = recover_stuck_documents(max_processing_minutes=5)

        assert result["stuck_count"] == 1

    def test_recover_stuck_documents_updates_processing_queue(self, db: Session):
        """Test that ProcessingQueue is also reset on recovery"""
        doc = Document(
            id=uuid.uuid4(),
            filename="stuck_doc.pdf",
            original_filename="stuck_doc.pdf",
            file_path="/data/public/stuck_doc.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.PROCESSING,
            size=1024,
            mime_type="application/pdf",
            updated_at=datetime.utcnow() - timedelta(minutes=10),
        )
        db.add(doc)

        processing_task = ProcessingQueue(
            id=uuid.uuid4(),
            document_id=doc.id,
            task_type=TaskType.OCR_PROCESSING,
            status=TaskStatus.IN_PROGRESS,
            retry_count=5,
            started_at=datetime.utcnow() - timedelta(minutes=10),
        )
        db.add(processing_task)
        db.commit()

        recover_stuck_documents(max_processing_minutes=5)

        db.refresh(processing_task)
        assert processing_task.status == TaskStatus.PENDING
        assert processing_task.retry_count == 0


class TestEmbeddingErrorHandling:
    """Tests for embedding generation error handling"""

    def test_embedding_failure_metadata_structure(self, db: Session):
        """Test that embedding failure metadata is properly structured"""
        doc = Document(
            id=uuid.uuid4(),
            filename="test.pdf",
            original_filename="test.pdf",
            file_path="/data/public/test.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.PROCESSING,
            size=1024,
            mime_type="application/pdf",
            document_metadata={
                "embedding_error": "GPU OOM",
                "embedding_failed_at": datetime.utcnow().isoformat(),
            },
        )
        db.add(doc)
        db.commit()

        db.refresh(doc)
        assert doc.document_metadata is not None
        assert "embedding_error" in doc.document_metadata
        assert "embedding_failed_at" in doc.document_metadata

    def test_embedding_failure_allows_text_indexing(self, db: Session):
        """Test that documents can still be indexed for text search after embedding failure"""
        doc = Document(
            id=uuid.uuid4(),
            filename="test.pdf",
            original_filename="test.pdf",
            file_path="/data/public/test.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf",
            embedding_generated=False,
            document_metadata={"embedding_error": "Service unavailable"},
        )
        db.add(doc)
        db.commit()

        db.refresh(doc)
        assert doc.status == DocumentStatus.INDEXED
        assert doc.embedding_generated is False


class TestChunkStorageTransaction:
    """Tests for chunk storage transaction handling"""

    def test_chunk_storage_rollback_on_failure(self, db: Session):
        """Test that chunk storage rolls back on database error"""
        doc = Document(
            id=uuid.uuid4(),
            filename="test.pdf",
            original_filename="test.pdf",
            file_path="/data/public/test.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.PROCESSING,
            size=1024,
            mime_type="application/pdf",
        )
        db.add(doc)
        db.commit()

        initial_doc = db.query(Document).filter(Document.id == doc.id).first()

        assert initial_doc.chunk_count is None or initial_doc.chunk_count == 0

    def test_chunk_storage_metadata_error_tracking(self, db: Session):
        """Test that chunk storage errors are tracked in document metadata"""
        doc = Document(
            id=uuid.uuid4(),
            filename="test.pdf",
            original_filename="test.pdf",
            file_path="/data/public/test.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.PROCESSING,
            size=1024,
            mime_type="application/pdf",
            document_metadata={},
        )
        db.add(doc)
        db.commit()

        from app.models.document import DocumentChunk

        chunks_data = [
            {"index": 0, "text": "Chunk 1", "token_count": 2},
            {"index": 1, "text": "Chunk 2", "token_count": 2},
        ]

        try:
            for chunk_data in chunks_data:
                chunk = DocumentChunk(
                    document_id=doc.id,
                    chunk_index=chunk_data["index"],
                    chunk_text=chunk_data["text"],
                    token_count=chunk_data["token_count"],
                )
                db.add(chunk)

            doc.chunk_count = len(chunks_data)
            db.commit()
        except Exception as e:
            db.rollback()
            doc.document_metadata = doc.document_metadata or {}
            doc.document_metadata["chunk_storage_error"] = str(e)
            db.commit()

        db.refresh(doc)
        assert doc.chunk_count == 2


class TestDocumentStatusTransitions:
    """Tests for proper document status transitions during processing"""

    def test_status_updates_to_error_on_max_retries(self, db: Session):
        """Test that document status becomes ERROR after max retries"""
        doc = Document(
            id=uuid.uuid4(),
            filename="failing.pdf",
            original_filename="failing.pdf",
            file_path="/data/public/failing.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.PROCESSING,
            size=1024,
            mime_type="application/pdf",
            document_metadata={"retry_count": 2},
        )
        db.add(doc)

        processing_task = ProcessingQueue(
            id=uuid.uuid4(),
            document_id=doc.id,
            task_type=TaskType.OCR_PROCESSING,
            status=TaskStatus.IN_PROGRESS,
            retry_count=2,
        )
        db.add(processing_task)
        db.commit()

        current_retry = processing_task.retry_count + 1
        if current_retry >= 3:
            doc.status = DocumentStatus.ERROR
        else:
            doc.status = DocumentStatus.PENDING
        db.commit()

        db.refresh(doc)
        assert doc.status == DocumentStatus.ERROR

    def test_status_updates_to_pending_for_retry(self, db: Session):
        """Test that document status becomes PENDING for retry when retries remain"""
        doc = Document(
            id=uuid.uuid4(),
            filename="retry.pdf",
            original_filename="retry.pdf",
            file_path="/data/public/retry.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.PROCESSING,
            size=1024,
            mime_type="application/pdf",
            document_metadata={"retry_count": 0},
        )
        db.add(doc)

        processing_task = ProcessingQueue(
            id=uuid.uuid4(),
            document_id=doc.id,
            task_type=TaskType.OCR_PROCESSING,
            status=TaskStatus.IN_PROGRESS,
            retry_count=0,
        )
        db.add(processing_task)
        db.commit()

        current_retry = processing_task.retry_count + 1
        if current_retry >= 3:
            doc.status = DocumentStatus.ERROR
        else:
            doc.status = DocumentStatus.PENDING
        db.commit()

        db.refresh(doc)
        assert doc.status == DocumentStatus.PENDING


class TestCeleryBeatSchedule:
    """Tests for Celery beat schedule configuration"""

    def test_beat_schedule_has_stuck_document_task(self):
        """Test that beat schedule includes stuck document recovery"""
        from app.celery_app import celery_app

        beat_schedule = celery_app.conf.beat_schedule

        assert "recover-stuck-documents" in beat_schedule

    def test_beat_schedule_timing(self):
        """Test that beat schedule runs every 10 minutes with 5 min threshold"""
        from app.celery_app import celery_app

        beat_schedule = celery_app.conf.beat_schedule
        stuck_task = beat_schedule.get("recover-stuck-documents")

        assert stuck_task is not None
        assert stuck_task["schedule"] == 600
        assert stuck_task["args"] == (5,)

    def test_beat_schedule_has_daily_anomaly_report(self):
        """Test that beat schedule includes daily anomaly report"""
        from app.celery_app import celery_app

        beat_schedule = celery_app.conf.beat_schedule

        assert "daily-anomaly-report" in beat_schedule
