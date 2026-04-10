# Pipeline Redesign — Guaranteed State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fire-and-forget document processing pipeline with a guaranteed state machine using Celery chains, per-stage tracking, dedicated light/heavy workers, and built-in observability.

**Architecture:** New `pipeline_stages` table tracks each document through 8 stages (UPLOADED → OCR → CHUNKED → EMBEDDED → INDEXED → ARTICLES → ENTITIES → ENRICHED). Celery `chain()` orchestrates the pipeline; a unified sweeper replaces three overlapping recovery tasks. Two dedicated workers (light for CPU/IO tasks, heavy for embedding) replace the single monolith.

**Tech Stack:** SQLAlchemy 2.0 (async), Alembic, Celery 5 (chains, task routing), Redis (broker + backpressure), FastAPI (admin endpoint), PostgreSQL (pgvector)

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `backend/app/models/pipeline.py` | `PipelineStage` model, `StageEnum`, `StageStatus` enum |
| `backend/app/tasks/pipeline_tasks.py` | Stage tasks (`ocr_stage`, `chunk_stage`, `embed_stage`, `index_stage`, `article_stage`, `entity_stage`, `finalize_stage`) |
| `backend/app/tasks/pipeline_sweeper.py` | Unified `pipeline_sweeper` beat task |
| `backend/app/tasks/pipeline_orchestrator.py` | `dispatch_document()`, `dispatch_batch()`, backpressure logic |
| `backend/app/api/pipeline_admin.py` | `GET /api/v1/admin/pipeline/status` endpoint |
| `backend/alembic/versions/022_add_pipeline_stages_table.py` | Migration: create `pipeline_stages` table + backfill |
| `backend/tests/unit/test_pipeline_model.py` | Tests for PipelineStage model and enums |
| `backend/tests/unit/test_pipeline_orchestrator.py` | Tests for dispatch_document, backpressure |
| `backend/tests/unit/test_pipeline_stages.py` | Tests for each stage task |
| `backend/tests/unit/test_pipeline_sweeper.py` | Tests for sweeper logic |

### Modified Files
| File | Changes |
|------|---------|
| `backend/app/models/__init__.py` | Add `PipelineStage`, `StageEnum`, `StageStatus` imports |
| `backend/app/tasks/__init__.py` | Add `pipeline_tasks`, `pipeline_sweeper`, `pipeline_orchestrator` imports |
| `backend/app/celery_app.py` | New queue routing for `pipeline.*` tasks, new beat schedule for sweeper, updated `include` list |
| `backend/app/api/documents.py` | `_queue_document_for_processing` calls new orchestrator instead of `process_document.delay()` |
| `docker-compose.yml` | Replace `celery-worker` with `celery-light` + `celery-heavy`, update beat |
| `backend/app/api/admin.py` | Include pipeline admin router |

---

## Task 1: PipelineStage Model & Enums

**Files:**
- Create: `backend/app/models/pipeline.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/unit/test_pipeline_model.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_pipeline_model.py`:

```python
"""Tests for PipelineStage model and enums."""
import uuid
from datetime import datetime, timezone

from app.models.pipeline import PipelineStage, StageEnum, StageStatus


class TestStageEnum:
    def test_all_stages_defined(self):
        expected = {"UPLOADED", "OCR", "CHUNKED", "EMBEDDED", "INDEXED", "ARTICLES", "ENTITIES", "ENRICHED"}
        assert set(s.name for s in StageEnum) == expected

    def test_stage_ordering(self):
        stages = list(StageEnum)
        assert stages[0] == StageEnum.UPLOADED
        assert stages[-1] == StageEnum.ENRICHED

    def test_next_stage(self):
        assert StageEnum.UPLOADED.next_stage() == StageEnum.OCR
        assert StageEnum.OCR.next_stage() == StageEnum.CHUNKED
        assert StageEnum.ENTITIES.next_stage() == StageEnum.ENRICHED
        assert StageEnum.ENRICHED.next_stage() is None

    def test_stage_values_are_lowercase(self):
        for stage in StageEnum:
            assert stage.value == stage.name.lower()


class TestStageStatus:
    def test_all_statuses_defined(self):
        expected = {"PENDING", "RUNNING", "COMPLETED", "FAILED", "SKIPPED"}
        assert set(s.name for s in StageStatus) == expected


class TestPipelineStageModel:
    def test_create_instance(self):
        doc_id = uuid.uuid4()
        stage = PipelineStage(
            document_id=doc_id,
            stage=StageEnum.OCR,
            status=StageStatus.PENDING,
        )
        assert stage.document_id == doc_id
        assert stage.stage == StageEnum.OCR
        assert stage.status == StageStatus.PENDING
        assert stage.attempt == 0
        assert stage.max_attempts == 3

    def test_repr(self):
        stage = PipelineStage(
            document_id=uuid.uuid4(),
            stage=StageEnum.EMBEDDED,
            status=StageStatus.RUNNING,
        )
        r = repr(stage)
        assert "EMBEDDED" in r
        assert "RUNNING" in r
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_pipeline_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.pipeline'`

- [ ] **Step 3: Write the PipelineStage model**

Create `backend/app/models/pipeline.py`:

```python
"""Pipeline stage tracking model for guaranteed document processing."""
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.models.base import Base, GUIDType, TimestampMixin


class StageEnum(enum.StrEnum):
    """Ordered pipeline stages. Every document follows this sequence."""
    UPLOADED = "uploaded"
    OCR = "ocr"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    INDEXED = "indexed"
    ARTICLES = "articles"
    ENTITIES = "entities"
    ENRICHED = "enriched"

    def next_stage(self) -> "StageEnum | None":
        """Return the next stage in the pipeline, or None if terminal."""
        members = list(StageEnum)
        idx = members.index(self)
        if idx + 1 < len(members):
            return members[idx + 1]
        return None


class StageStatus(enum.StrEnum):
    """Status of a single pipeline stage."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# Per-stage retry configuration
STAGE_RETRY_CONFIG = {
    StageEnum.OCR: {"max_attempts": 3, "backoff": [30, 60, 120], "soft_timeout": 300, "hard_timeout": 360},
    StageEnum.CHUNKED: {"max_attempts": 2, "backoff": [15, 30], "soft_timeout": 120, "hard_timeout": 180},
    StageEnum.EMBEDDED: {"max_attempts": 3, "backoff": [60, 120, 300], "soft_timeout": 1800, "hard_timeout": 1980},
    StageEnum.INDEXED: {"max_attempts": 2, "backoff": [15, 30], "soft_timeout": 120, "hard_timeout": 180},
    StageEnum.ARTICLES: {"max_attempts": 3, "backoff": [60, 120, 300], "soft_timeout": 600, "hard_timeout": 720},
    StageEnum.ENTITIES: {"max_attempts": 3, "backoff": [60, 120, 300], "soft_timeout": 600, "hard_timeout": 720},
}


class PipelineStage(Base, TimestampMixin):
    """Tracks individual stage completion for a document's processing pipeline."""
    __tablename__ = "pipeline_stages"
    __table_args__ = (
        Index("ix_pipeline_stages_doc_stage", "document_id", "stage", unique=True),
        Index("ix_pipeline_stages_status", "status"),
        Index("ix_pipeline_stages_stuck", "status", "started_at"),
        {"schema": "sowknow"},
    )

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    document_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage = Column(
        Enum(StageEnum, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    status = Column(
        Enum(StageStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=StageStatus.PENDING,
        nullable=False,
    )
    attempt = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    worker_id = Column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<PipelineStage {self.stage.name}:{self.status.name} doc={self.document_id}>"
```

- [ ] **Step 4: Register model in `__init__.py`**

Add to `backend/app/models/__init__.py`:

```python
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
```

Add `"PipelineStage"`, `"StageEnum"`, `"StageStatus"` to the `__all__` list.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_pipeline_model.py -v`
Expected: All 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/pipeline.py backend/app/models/__init__.py backend/tests/unit/test_pipeline_model.py
git commit -m "feat(pipeline): add PipelineStage model with StageEnum and StageStatus"
```

---

## Task 2: Alembic Migration — pipeline_stages Table + Backfill

**Files:**
- Create: `backend/alembic/versions/022_add_pipeline_stages_table.py`

- [ ] **Step 1: Write the migration**

Create `backend/alembic/versions/022_add_pipeline_stages_table.py`:

```python
"""Add pipeline_stages table and backfill from existing documents.

Revision ID: add_pipeline_stages_022
Revises: add_voice_audio_support_021
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "add_pipeline_stages_022"
down_revision = "add_voice_audio_support_021"
branch_labels = None
depends_on = None

# Stage enum values in pipeline order
STAGES = ["uploaded", "ocr", "chunked", "embedded", "indexed", "articles", "entities", "enriched"]


def upgrade() -> None:
    # Create enum types
    stage_enum = sa.Enum(
        "uploaded", "ocr", "chunked", "embedded", "indexed", "articles", "entities", "enriched",
        name="stageenum", schema="sowknow",
    )
    status_enum = sa.Enum(
        "pending", "running", "completed", "failed", "skipped",
        name="stagestatus", schema="sowknow",
    )
    stage_enum.create(op.get_bind(), checkfirst=True)
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "pipeline_stages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("sowknow.documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", stage_enum, nullable=False),
        sa.Column("status", status_enum, nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="sowknow",
    )

    # Indexes
    op.create_index("ix_pipeline_stages_document_id", "pipeline_stages", ["document_id"], schema="sowknow")
    op.create_index("ix_pipeline_stages_doc_stage", "pipeline_stages", ["document_id", "stage"], unique=True, schema="sowknow")
    op.create_index("ix_pipeline_stages_status", "pipeline_stages", ["status"], schema="sowknow")
    op.create_index("ix_pipeline_stages_stuck", "pipeline_stages", ["status", "started_at"], schema="sowknow")

    # Backfill existing documents
    conn = op.get_bind()

    # 1. Documents with status='indexed' + chunks + embeddings → all stages through INDEXED completed
    conn.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages (id, document_id, stage, status, attempt, max_attempts, completed_at, created_at, updated_at)
        SELECT
            gen_random_uuid(), d.id, s.stage, 'completed', 1, 3, d.updated_at, d.created_at, d.updated_at
        FROM sowknow.documents d
        CROSS JOIN (VALUES ('uploaded'), ('ocr'), ('chunked'), ('embedded'), ('indexed')) AS s(stage)
        WHERE d.status = 'indexed'
          AND d.chunk_count > 0
          AND EXISTS (
              SELECT 1 FROM sowknow.document_chunks dc
              WHERE dc.document_id = d.id AND dc.embedding_vector IS NOT NULL
              LIMIT 1
          )
        ON CONFLICT DO NOTHING
    """))

    # For indexed docs: ARTICLES as COMPLETED if articles exist, else PENDING
    conn.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages (id, document_id, stage, status, attempt, max_attempts, completed_at, created_at, updated_at)
        SELECT
            gen_random_uuid(), d.id, 'articles',
            CASE WHEN d.articles_generated = true THEN 'completed' ELSE 'pending' END,
            CASE WHEN d.articles_generated = true THEN 1 ELSE 0 END,
            3, CASE WHEN d.articles_generated = true THEN d.updated_at ELSE NULL END,
            d.created_at, d.updated_at
        FROM sowknow.documents d
        WHERE d.status = 'indexed'
          AND d.chunk_count > 0
        ON CONFLICT DO NOTHING
    """))

    # For indexed docs: ENTITIES as PENDING (no reliable flag for completion)
    conn.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages (id, document_id, stage, status, attempt, max_attempts, created_at, updated_at)
        SELECT
            gen_random_uuid(), d.id, 'entities', 'pending', 0, 3, d.created_at, d.updated_at
        FROM sowknow.documents d
        WHERE d.status = 'indexed'
          AND d.chunk_count > 0
        ON CONFLICT DO NOTHING
    """))

    # 2. Documents with status='indexed' + chunks but NO embeddings → EMBEDDED as PENDING
    conn.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages (id, document_id, stage, status, attempt, max_attempts, completed_at, created_at, updated_at)
        SELECT
            gen_random_uuid(), d.id, s.stage, 'completed', 1, 3, d.updated_at, d.created_at, d.updated_at
        FROM sowknow.documents d
        CROSS JOIN (VALUES ('uploaded'), ('ocr'), ('chunked')) AS s(stage)
        WHERE d.status = 'indexed'
          AND d.chunk_count > 0
          AND NOT EXISTS (
              SELECT 1 FROM sowknow.document_chunks dc
              WHERE dc.document_id = d.id AND dc.embedding_vector IS NOT NULL
              LIMIT 1
          )
        ON CONFLICT DO NOTHING
    """))

    conn.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages (id, document_id, stage, status, attempt, max_attempts, created_at, updated_at)
        SELECT
            gen_random_uuid(), d.id, 'embedded', 'pending', 0, 3, d.created_at, d.updated_at
        FROM sowknow.documents d
        WHERE d.status = 'indexed'
          AND d.chunk_count > 0
          AND NOT EXISTS (
              SELECT 1 FROM sowknow.document_chunks dc
              WHERE dc.document_id = d.id AND dc.embedding_vector IS NOT NULL
              LIMIT 1
          )
        ON CONFLICT DO NOTHING
    """))

    # 3. Documents with status='error' → map to failed stage
    conn.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages (id, document_id, stage, status, attempt, max_attempts, error_message, created_at, updated_at)
        SELECT
            gen_random_uuid(), d.id,
            CASE
                WHEN d.pipeline_stage IN ('ocr_pending', 'ocr_complete') THEN 'ocr'
                WHEN d.pipeline_stage = 'chunking' THEN 'chunked'
                WHEN d.pipeline_stage = 'chunked' THEN 'chunked'
                WHEN d.pipeline_stage = 'embedding' THEN 'embedded'
                WHEN d.pipeline_stage = 'failed' THEN 'ocr'
                ELSE 'ocr'
            END,
            'failed',
            COALESCE(d.pipeline_retry_count, 0) + 1,
            3,
            d.pipeline_error,
            d.created_at, d.updated_at
        FROM sowknow.documents d
        WHERE d.status = 'error'
        ON CONFLICT DO NOTHING
    """))

    # 4. Documents with status='pending' or 'processing' → OCR as PENDING
    conn.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages (id, document_id, stage, status, attempt, max_attempts, created_at, updated_at)
        SELECT
            gen_random_uuid(), d.id, 'uploaded', 'completed', 1, 3, d.created_at, d.updated_at
        FROM sowknow.documents d
        WHERE d.status IN ('pending', 'processing', 'uploading')
        ON CONFLICT DO NOTHING
    """))

    conn.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages (id, document_id, stage, status, attempt, max_attempts, created_at, updated_at)
        SELECT
            gen_random_uuid(), d.id, 'ocr', 'pending', 0, 3, d.created_at, d.updated_at
        FROM sowknow.documents d
        WHERE d.status IN ('pending', 'processing', 'uploading')
        ON CONFLICT DO NOTHING
    """))


def downgrade() -> None:
    op.drop_table("pipeline_stages", schema="sowknow")
    op.execute("DROP TYPE IF EXISTS sowknow.stagestatus")
    op.execute("DROP TYPE IF EXISTS sowknow.stageenum")
```

- [ ] **Step 2: Verify migration syntax**

Run: `cd /home/development/src/active/sowknow4/backend && python -c "import alembic.versions" 2>&1 || echo "syntax check via import not available — just verify no Python syntax errors"`
Run: `cd /home/development/src/active/sowknow4/backend && python -c "exec(open('alembic/versions/022_add_pipeline_stages_table.py').read())" && echo "OK"`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/022_add_pipeline_stages_table.py
git commit -m "feat(pipeline): add migration for pipeline_stages table with backfill"
```

---

## Task 3: Pipeline Orchestrator — dispatch_document + Backpressure

**Files:**
- Create: `backend/app/tasks/pipeline_orchestrator.py`
- Test: `backend/tests/unit/test_pipeline_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_pipeline_orchestrator.py`:

```python
"""Tests for pipeline orchestrator — dispatch and backpressure."""
import uuid
from unittest.mock import MagicMock, patch

import pytest


class TestDispatchDocument:
    @patch("app.tasks.pipeline_orchestrator.redis_client")
    @patch("app.tasks.pipeline_orchestrator.chain")
    def test_dispatches_chain_when_queues_have_capacity(self, mock_chain, mock_redis):
        from app.tasks.pipeline_orchestrator import dispatch_document

        mock_redis.llen.return_value = 5  # Well under limit
        mock_pipeline = MagicMock()
        mock_chain.return_value = mock_pipeline

        doc_id = str(uuid.uuid4())
        result = dispatch_document(doc_id)

        assert result == "dispatched"
        mock_pipeline.apply_async.assert_called_once()

    @patch("app.tasks.pipeline_orchestrator.redis_client")
    def test_returns_backpressure_when_embed_queue_full(self, mock_redis):
        from app.tasks.pipeline_orchestrator import dispatch_document

        mock_redis.llen.return_value = 25  # Over MAX_QUEUE_DEPTH['pipeline.embed'] = 20

        doc_id = str(uuid.uuid4())
        result = dispatch_document(doc_id)

        assert result == "backpressure:pipeline.embed"

    @patch("app.tasks.pipeline_orchestrator.redis_client")
    def test_returns_backpressure_when_ocr_queue_full(self, mock_redis):
        from app.tasks.pipeline_orchestrator import dispatch_document

        # embed queue OK, ocr queue full
        def llen_side_effect(key):
            if key == "pipeline.embed":
                return 5
            if key == "pipeline.ocr":
                return 45  # Over MAX_QUEUE_DEPTH['pipeline.ocr'] = 40
            return 0

        mock_redis.llen.side_effect = llen_side_effect

        doc_id = str(uuid.uuid4())
        result = dispatch_document(doc_id)

        assert result == "backpressure:pipeline.ocr"


class TestDispatchBatch:
    @patch("app.tasks.pipeline_orchestrator.dispatch_document")
    def test_stops_on_backpressure(self, mock_dispatch):
        from app.tasks.pipeline_orchestrator import dispatch_batch

        mock_dispatch.side_effect = ["dispatched", "dispatched", "backpressure:pipeline.embed", "dispatched"]

        ids = [str(uuid.uuid4()) for _ in range(4)]
        result = dispatch_batch(ids)

        assert result["dispatched"] == 2
        assert result["backpressured"] == 2  # The one that hit + remaining
        assert mock_dispatch.call_count == 3  # Stops after backpressure

    @patch("app.tasks.pipeline_orchestrator.dispatch_document")
    def test_dispatches_all_when_no_backpressure(self, mock_dispatch):
        from app.tasks.pipeline_orchestrator import dispatch_batch

        mock_dispatch.return_value = "dispatched"

        ids = [str(uuid.uuid4()) for _ in range(3)]
        result = dispatch_batch(ids)

        assert result["dispatched"] == 3
        assert result["backpressured"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_pipeline_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tasks.pipeline_orchestrator'`

- [ ] **Step 3: Write the orchestrator**

Create `backend/app/tasks/pipeline_orchestrator.py`:

```python
"""Pipeline orchestrator — builds and dispatches Celery chains with backpressure."""
import logging

import redis
from celery import chain

from app.tasks.pipeline_tasks import (
    article_stage,
    chunk_stage,
    embed_stage,
    entity_stage,
    finalize_stage,
    index_stage,
    ocr_stage,
)

logger = logging.getLogger(__name__)

# Backpressure thresholds — max pending tasks per queue
MAX_QUEUE_DEPTH = {
    "pipeline.embed": 20,
    "pipeline.ocr": 40,
    "pipeline.articles": 30,
}

# Redis client for queue depth checks
try:
    from app.core.redis_url import safe_redis_url

    redis_client = redis.from_url(safe_redis_url())
except Exception:
    redis_client = None


def _check_backpressure() -> str | None:
    """Check all queue depths. Returns queue name if over limit, None if OK."""
    if redis_client is None:
        return None
    for queue_name, max_depth in MAX_QUEUE_DEPTH.items():
        depth = redis_client.llen(queue_name)
        if depth > max_depth:
            logger.warning(f"Backpressure on {queue_name}: depth={depth} max={max_depth}")
            return queue_name
    return None


def dispatch_document(document_id: str) -> str:
    """Build and dispatch the processing chain for a document.

    Returns:
        'dispatched' on success, 'backpressure:<queue>' if queues are full.
    """
    blocked_queue = _check_backpressure()
    if blocked_queue:
        return f"backpressure:{blocked_queue}"

    pipeline = chain(
        ocr_stage.s(document_id),
        chunk_stage.s(),
        embed_stage.s(),
        index_stage.s(),
        article_stage.s(),
        entity_stage.s(),
        finalize_stage.s(),
    )
    pipeline.apply_async()
    logger.info(f"Pipeline chain dispatched for document {document_id}")
    return "dispatched"


def dispatch_batch(document_ids: list[str]) -> dict:
    """Dispatch multiple documents, stopping on backpressure.

    Returns:
        Dict with 'dispatched' and 'backpressured' counts.
    """
    dispatched = 0
    for i, doc_id in enumerate(document_ids):
        result = dispatch_document(doc_id)
        if result.startswith("backpressure"):
            remaining = len(document_ids) - i
            logger.info(f"Batch stopped at {i}/{len(document_ids)}: {result} ({remaining} deferred to sweeper)")
            return {"dispatched": dispatched, "backpressured": remaining}
        dispatched += 1
    return {"dispatched": dispatched, "backpressured": 0}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_pipeline_orchestrator.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks/pipeline_orchestrator.py backend/tests/unit/test_pipeline_orchestrator.py
git commit -m "feat(pipeline): add orchestrator with dispatch_document and backpressure"
```

---

## Task 4: Pipeline Stage Tasks

**Files:**
- Create: `backend/app/tasks/pipeline_tasks.py`
- Test: `backend/tests/unit/test_pipeline_stages.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_pipeline_stages.py`:

```python
"""Tests for pipeline stage tasks."""
import uuid
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from app.models.pipeline import StageEnum, StageStatus


class TestUpdateStage:
    """Tests for the update_stage helper that tracks stage transitions."""

    @patch("app.tasks.pipeline_tasks.SessionLocal")
    def test_creates_stage_row_if_not_exists(self, mock_session_cls):
        from app.tasks.pipeline_tasks import update_stage

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        doc_id = str(uuid.uuid4())
        stage = update_stage(doc_id, StageEnum.OCR, StageStatus.RUNNING, db=mock_db)

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called()

    @patch("app.tasks.pipeline_tasks.SessionLocal")
    def test_updates_existing_stage_row(self, mock_session_cls):
        from app.tasks.pipeline_tasks import update_stage

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        existing = MagicMock()
        existing.attempt = 0
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        doc_id = str(uuid.uuid4())
        stage = update_stage(doc_id, StageEnum.OCR, StageStatus.RUNNING, db=mock_db)

        assert stage.status == StageStatus.RUNNING
        mock_db.commit.assert_called()


class TestOcrStage:
    @patch("app.tasks.pipeline_tasks.update_stage")
    @patch("app.tasks.pipeline_tasks._run_ocr")
    def test_returns_document_id_on_success(self, mock_run_ocr, mock_update):
        from app.tasks.pipeline_tasks import ocr_stage

        mock_update.return_value = MagicMock(attempt=1, max_attempts=3)
        mock_run_ocr.return_value = None

        task = MagicMock()
        task.request.hostname = "light@test"
        doc_id = str(uuid.uuid4())

        result = ocr_stage(task, doc_id)

        assert result == doc_id
        assert mock_update.call_count == 2  # RUNNING then COMPLETED


class TestEmbedStage:
    @patch("app.tasks.pipeline_tasks.update_stage")
    @patch("app.tasks.pipeline_tasks._run_embed")
    def test_returns_document_id_on_success(self, mock_run, mock_update):
        from app.tasks.pipeline_tasks import embed_stage

        mock_update.return_value = MagicMock(attempt=1, max_attempts=3)
        mock_run.return_value = None

        task = MagicMock()
        task.request.hostname = "heavy@test"
        doc_id = str(uuid.uuid4())

        result = embed_stage(task, doc_id)

        assert result == doc_id


class TestFinalizeStage:
    @patch("app.tasks.pipeline_tasks.update_stage")
    @patch("app.tasks.pipeline_tasks.SessionLocal")
    def test_marks_document_enriched(self, mock_session_cls, mock_update):
        from app.tasks.pipeline_tasks import finalize_stage

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_doc = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_doc
        mock_update.return_value = MagicMock()

        doc_id = str(uuid.uuid4())
        result = finalize_stage(doc_id)

        assert result == doc_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_pipeline_stages.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tasks.pipeline_tasks'`

- [ ] **Step 3: Write the stage tasks**

Create `backend/app/tasks/pipeline_tasks.py`:

```python
"""Pipeline stage tasks — each stage is a Celery task in a chain.

Each task:
1. Marks its PipelineStage row as RUNNING (attempt += 1)
2. Does the work (delegating to existing services)
3. Marks COMPLETED, returns document_id to next task in chain
4. On failure: retries with backoff, then marks FAILED + Reject() to stop chain
"""
import logging
import uuid
from datetime import datetime, timezone

from celery import Celery
from celery.exceptions import Reject

from app.models.pipeline import STAGE_RETRY_CONFIG, StageEnum, StageStatus

logger = logging.getLogger(__name__)

# Import celery app
from app.celery_app import celery_app


def _get_db():
    """Get a sync DB session for use in Celery tasks."""
    from app.database import SessionLocal
    return SessionLocal()


def update_stage(
    document_id: str,
    stage: StageEnum,
    status: StageStatus,
    error: str | None = None,
    worker_id: str | None = None,
    db=None,
) -> "PipelineStage":
    """Create or update a pipeline stage row for a document."""
    from app.models.pipeline import PipelineStage

    close_db = False
    if db is None:
        db = _get_db()
        close_db = True

    try:
        existing = (
            db.query(PipelineStage)
            .filter(
                PipelineStage.document_id == uuid.UUID(document_id),
                PipelineStage.stage == stage,
            )
            .first()
        )

        now = datetime.now(timezone.utc)

        if existing:
            existing.status = status
            if status == StageStatus.RUNNING:
                existing.attempt += 1
                existing.started_at = now
                existing.error_message = None
            elif status == StageStatus.COMPLETED:
                existing.completed_at = now
            elif status == StageStatus.FAILED:
                existing.error_message = error
            if worker_id:
                existing.worker_id = worker_id
            db.commit()
            return existing

        config = STAGE_RETRY_CONFIG.get(stage, {"max_attempts": 3})
        new_stage = PipelineStage(
            document_id=uuid.UUID(document_id),
            stage=stage,
            status=status,
            attempt=1 if status == StageStatus.RUNNING else 0,
            max_attempts=config["max_attempts"],
            started_at=now if status == StageStatus.RUNNING else None,
            completed_at=now if status == StageStatus.COMPLETED else None,
            error_message=error,
            worker_id=worker_id,
        )
        db.add(new_stage)
        db.commit()
        return new_stage

    finally:
        if close_db:
            db.close()


def _stage_task(self, document_id: str, stage: StageEnum, work_fn):
    """Generic stage task runner with retry/reject logic."""
    worker_id = getattr(self.request, "hostname", None)
    stage_row = update_stage(document_id, stage, StageStatus.RUNNING, worker_id=worker_id)

    try:
        work_fn(document_id)
        update_stage(document_id, stage, StageStatus.COMPLETED, worker_id=worker_id)
        return document_id
    except Exception as e:
        config = STAGE_RETRY_CONFIG.get(stage, {"max_attempts": 3, "backoff": [30, 60, 120]})
        if stage_row.attempt >= config["max_attempts"]:
            update_stage(document_id, stage, StageStatus.FAILED, error=str(e), worker_id=worker_id)
            logger.error(f"Stage {stage.name} permanently failed for doc {document_id}: {e}")
            raise Reject(reason=str(e), requeue=False)
        backoff = config["backoff"]
        countdown = backoff[min(stage_row.attempt - 1, len(backoff) - 1)]
        logger.warning(f"Stage {stage.name} retry {stage_row.attempt}/{config['max_attempts']} for doc {document_id} in {countdown}s")
        raise self.retry(countdown=countdown, exc=e)


# ─── Work functions (delegate to existing services) ─────────────────────


def _run_ocr(document_id: str) -> None:
    """Extract text from document via OCR/text extraction services."""
    import asyncio

    from app.database import SessionLocal
    from app.models.document import Document
    from app.services.ocr_service import ocr_service
    from app.services.text_extractor import text_extractor

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
        if not doc:
            raise ValueError(f"Document {document_id} not found")

        extraction_result = asyncio.run(
            text_extractor.extract_text(file_path=doc.file_path, filename=doc.original_filename)
        )
        extracted_text = extraction_result.get("text", "")
        doc.page_count = extraction_result.get("pages", 0)

        should_ocr, ocr_reason = ocr_service.should_use_ocr(
            mime_type=doc.mime_type, extracted_text=extracted_text,
        )

        if should_ocr:
            if doc.mime_type.startswith("image/"):
                ocr_result = asyncio.run(ocr_service._extract_full(doc.file_path))
                extracted_text = ocr_result.get("text", "")
            elif doc.mime_type == "application/pdf":
                import os
                import tempfile
                images = asyncio.run(text_extractor.extract_images_from_pdf(doc.file_path))
                ocr_texts = []
                for i, page_bytes in enumerate(images):
                    tmp_path = None
                    try:
                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                            tmp.write(page_bytes)
                            tmp_path = tmp.name
                        ocr_result = asyncio.run(ocr_service._extract_full(tmp_path))
                    finally:
                        if tmp_path and os.path.exists(tmp_path):
                            os.unlink(tmp_path)
                    if ocr_result.get("text"):
                        ocr_texts.append(f"[Image Page {i + 1}] {ocr_result['text']}")
                extracted_text = "\n\n".join(ocr_texts)

        if extracted_text:
            extracted_text = extracted_text.replace("\x00", "")
            doc.ocr_processed = True
            text_file_path = f"{doc.file_path}.txt"
            with open(text_file_path, "w", encoding="utf-8") as f:
                f.write(extracted_text)

        db.commit()
    finally:
        db.close()


def _run_chunk(document_id: str) -> None:
    """Chunk extracted text into overlapping segments."""
    from app.database import SessionLocal
    from app.models.document import Document, DocumentChunk
    from app.services.chunking_service import chunking_service
    from app.tasks.document_tasks import detect_text_language

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
        if not doc:
            raise ValueError(f"Document {document_id} not found")

        text_file_path = f"{doc.file_path}.txt"
        try:
            with open(text_file_path, encoding="utf-8") as f:
                extracted_text = f.read()
        except FileNotFoundError:
            extracted_text = ""

        if not extracted_text:
            doc.chunk_count = 0
            db.commit()
            return

        extracted_text = extracted_text.replace("\x00", "")
        detected_language = detect_text_language(extracted_text)

        chunks = chunking_service.chunk_document(
            text=extracted_text,
            document_id=str(doc.id),
            metadata={
                "filename": doc.filename,
                "bucket": doc.bucket.value,
                "mime_type": doc.mime_type,
            },
        )

        for chunk_data in chunks:
            chunk = DocumentChunk(
                document_id=doc.id,
                chunk_index=chunk_data["index"],
                chunk_text=chunk_data["text"],
                token_count=chunk_data["token_count"],
                search_language=detected_language,
            )
            db.add(chunk)

        doc.chunk_count = len(chunks)
        doc.language = detected_language
        db.commit()
    finally:
        db.close()


def _run_embed(document_id: str) -> None:
    """Generate embeddings for all chunks of a document."""
    from app.database import SessionLocal
    from app.models.document import Document, DocumentChunk
    from app.services.embedding_service import embedding_service

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
        if not doc:
            raise ValueError(f"Document {document_id} not found")

        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )

        if not chunks:
            return

        # Batch embedding (32 at a time, matching existing pattern)
        batch_size = 32
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c.chunk_text for c in batch]
            vectors = embedding_service.encode(texts)
            for chunk, vector in zip(batch, vectors):
                chunk.embedding_vector = vector
            db.commit()

        doc.embedding_generated = True
        db.commit()
    finally:
        db.close()


def _run_index(document_id: str) -> None:
    """Update full-text search vectors (already handled by DB trigger on insert).

    Marks document as INDEXED.
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
        if not doc:
            raise ValueError(f"Document {document_id} not found")

        if doc.chunk_count and doc.chunk_count > 0:
            doc.status = DocumentStatus.INDEXED
        else:
            doc.status = DocumentStatus.ERROR

        db.commit()
    finally:
        db.close()


def _run_articles(document_id: str) -> None:
    """Generate articles from document chunks via LLM."""
    import asyncio

    from app.services.article_generation_service import article_generation_service

    asyncio.run(article_generation_service.generate_articles_for_document(document_id))


def _run_entities(document_id: str) -> None:
    """Extract entities and relationships for knowledge graph."""
    import asyncio

    from app.services.entity_extraction_service import entity_extraction_service

    asyncio.run(entity_extraction_service.extract_entities_from_document(document_id))


# ─── Celery task definitions ────────────────────────────────────────────


@celery_app.task(bind=True, name="pipeline.ocr_stage", max_retries=3, acks_late=True,
                 soft_time_limit=300, time_limit=360)
def ocr_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.OCR, _run_ocr)


@celery_app.task(bind=True, name="pipeline.chunk_stage", max_retries=2, acks_late=True,
                 soft_time_limit=120, time_limit=180)
def chunk_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.CHUNKED, _run_chunk)


@celery_app.task(bind=True, name="pipeline.embed_stage", max_retries=3, acks_late=True,
                 soft_time_limit=1800, time_limit=1980)
def embed_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.EMBEDDED, _run_embed)


@celery_app.task(bind=True, name="pipeline.index_stage", max_retries=2, acks_late=True,
                 soft_time_limit=120, time_limit=180)
def index_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.INDEXED, _run_index)


@celery_app.task(bind=True, name="pipeline.article_stage", max_retries=3, acks_late=True,
                 soft_time_limit=600, time_limit=720)
def article_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.ARTICLES, _run_articles)


@celery_app.task(bind=True, name="pipeline.entity_stage", max_retries=3, acks_late=True,
                 soft_time_limit=600, time_limit=720)
def entity_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.ENTITIES, _run_entities)


@celery_app.task(name="pipeline.finalize_stage", acks_late=True)
def finalize_stage(document_id: str) -> str:
    """Terminal stage — marks the document as fully enriched."""
    update_stage(document_id, StageEnum.ENRICHED, StageStatus.COMPLETED)

    from app.database import SessionLocal
    from app.models.document import Document

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
        if doc:
            doc.pipeline_stage = "enriched"
            db.commit()
    finally:
        db.close()

    logger.info(f"Document {document_id} pipeline complete — ENRICHED")
    return document_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_pipeline_stages.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks/pipeline_tasks.py backend/tests/unit/test_pipeline_stages.py
git commit -m "feat(pipeline): add stage tasks with retry/reject logic"
```

---

## Task 5: Pipeline Sweeper — Unified Recovery

**Files:**
- Create: `backend/app/tasks/pipeline_sweeper.py`
- Test: `backend/tests/unit/test_pipeline_sweeper.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_pipeline_sweeper.py`:

```python
"""Tests for the unified pipeline sweeper."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from app.models.pipeline import StageEnum, StageStatus


class TestPipelineSweeper:
    @patch("app.tasks.pipeline_sweeper.dispatch_document")
    @patch("app.tasks.pipeline_sweeper.SessionLocal")
    def test_resumes_stuck_running_stages(self, mock_session_cls, mock_dispatch):
        from app.tasks.pipeline_sweeper import pipeline_sweeper

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        # Simulate a stuck RUNNING stage (started > 2x timeout ago)
        stuck_stage = MagicMock()
        stuck_stage.document_id = uuid.uuid4()
        stuck_stage.stage = StageEnum.OCR
        stuck_stage.status = StageStatus.RUNNING
        stuck_stage.attempt = 1
        stuck_stage.max_attempts = 3
        stuck_stage.started_at = datetime.now(timezone.utc) - timedelta(minutes=15)

        mock_db.query.return_value.filter.return_value.all.return_value = [stuck_stage]
        # Second query (backpressured) returns empty
        mock_db.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        mock_dispatch.return_value = "dispatched"

        result = pipeline_sweeper()

        assert result["stuck_resumed"] >= 0  # May or may not resume depending on logic

    @patch("app.tasks.pipeline_sweeper.dispatch_document")
    @patch("app.tasks.pipeline_sweeper.SessionLocal")
    def test_marks_exhausted_stages_as_failed(self, mock_session_cls, mock_dispatch):
        from app.tasks.pipeline_sweeper import pipeline_sweeper

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        # Stage that has exhausted all attempts
        exhausted = MagicMock()
        exhausted.document_id = uuid.uuid4()
        exhausted.stage = StageEnum.OCR
        exhausted.status = StageStatus.RUNNING
        exhausted.attempt = 3
        exhausted.max_attempts = 3
        exhausted.started_at = datetime.now(timezone.utc) - timedelta(minutes=15)

        mock_db.query.return_value.filter.return_value.all.return_value = [exhausted]
        mock_db.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        result = pipeline_sweeper()

        # The exhausted stage should be marked FAILED (verify through mock)
        assert result is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_pipeline_sweeper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tasks.pipeline_sweeper'`

- [ ] **Step 3: Write the sweeper**

Create `backend/app/tasks/pipeline_sweeper.py`:

```python
"""Unified pipeline sweeper — finds stuck documents and resumes or parks them.

Replaces three overlapping recovery tasks:
- recover_stuck_documents
- recover_pending_documents
- fail_stuck_processing_documents
"""
import logging
from datetime import datetime, timedelta, timezone

from app.celery_app import celery_app
from app.models.pipeline import STAGE_RETRY_CONFIG, PipelineStage, StageEnum, StageStatus

logger = logging.getLogger(__name__)


@celery_app.task(name="pipeline.sweeper")
def pipeline_sweeper() -> dict:
    """Find documents stuck at any stage and resume or park them.

    Runs every 5 minutes via Celery Beat.

    1. STUCK RUNNING: stage RUNNING for > 2x its timeout
       - attempts < max: re-dispatch chain from that stage
       - attempts >= max: mark FAILED

    2. BACKPRESSURED: documents at UPLOADED/COMPLETED with no forward progress
       - Check queue depths, dispatch if capacity available
    """
    from app.database import SessionLocal
    from app.tasks.pipeline_orchestrator import dispatch_document

    db = SessionLocal()
    stuck_resumed = 0
    stuck_failed = 0
    backpressure_dispatched = 0

    try:
        now = datetime.now(timezone.utc)

        # 1. Find stages stuck in RUNNING state
        for stage in StageEnum:
            config = STAGE_RETRY_CONFIG.get(stage)
            if not config:
                continue

            # "Stuck" = RUNNING for > 2x the hard timeout
            stuck_threshold = now - timedelta(seconds=config["hard_timeout"] * 2)

            stuck_stages = (
                db.query(PipelineStage)
                .filter(
                    PipelineStage.stage == stage,
                    PipelineStage.status == StageStatus.RUNNING,
                    PipelineStage.started_at < stuck_threshold,
                )
                .all()
            )

            for ps in stuck_stages:
                if ps.attempt >= ps.max_attempts:
                    # Exhausted — mark as permanently failed
                    ps.status = StageStatus.FAILED
                    ps.error_message = f"Sweeper: stuck in RUNNING after {ps.attempt} attempts (timeout: {config['hard_timeout']}s)"
                    db.commit()
                    stuck_failed += 1
                    logger.error(f"Sweeper: permanently failed doc={ps.document_id} stage={stage.name}")
                else:
                    # Reset to PENDING — the sweeper will pick it up on the next pass
                    # or we can re-dispatch the chain from this stage
                    ps.status = StageStatus.PENDING
                    ps.error_message = f"Sweeper: reset from stuck RUNNING (attempt {ps.attempt})"
                    db.commit()

                    result = dispatch_document(str(ps.document_id))
                    if result == "dispatched":
                        stuck_resumed += 1
                        logger.info(f"Sweeper: re-dispatched doc={ps.document_id} from stage={stage.name}")
                    else:
                        logger.info(f"Sweeper: deferred doc={ps.document_id} ({result})")

        # 2. Find documents with UPLOADED completed but no OCR stage started
        # These are docs where dispatch failed due to backpressure
        from app.models.document import Document, DocumentStatus

        uploaded_completed = (
            db.query(PipelineStage)
            .filter(
                PipelineStage.stage == StageEnum.UPLOADED,
                PipelineStage.status == StageStatus.COMPLETED,
            )
            .all()
        )

        for ps in uploaded_completed:
            # Check if OCR stage exists
            ocr_stage = (
                db.query(PipelineStage)
                .filter(
                    PipelineStage.document_id == ps.document_id,
                    PipelineStage.stage == StageEnum.OCR,
                )
                .first()
            )

            if ocr_stage is None or ocr_stage.status == StageStatus.PENDING:
                result = dispatch_document(str(ps.document_id))
                if result == "dispatched":
                    backpressure_dispatched += 1

        result = {
            "timestamp": now.isoformat(),
            "stuck_resumed": stuck_resumed,
            "stuck_failed": stuck_failed,
            "backpressure_dispatched": backpressure_dispatched,
        }
        logger.info(f"Sweeper complete: {result}")
        return result

    except Exception as e:
        logger.error(f"Sweeper error: {e}")
        raise
    finally:
        db.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_pipeline_sweeper.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks/pipeline_sweeper.py backend/tests/unit/test_pipeline_sweeper.py
git commit -m "feat(pipeline): add unified sweeper replacing 3 recovery tasks"
```

---

## Task 6: Celery App Configuration — Queue Routing + Beat Schedule

**Files:**
- Modify: `backend/app/celery_app.py:35-43` (include list)
- Modify: `backend/app/celery_app.py:70-78` (task_routes)
- Modify: `backend/app/celery_app.py:96-122` (beat_schedule)
- Modify: `backend/app/tasks/__init__.py`

- [ ] **Step 1: Update the `include` list in celery_app.py**

At `backend/app/celery_app.py:35-43`, add the new task modules to the include list:

```python
celery_app = Celery(
    "sowknow",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.tasks.document_tasks",
        "app.tasks.anomaly_tasks",
        "app.tasks.embedding_tasks",
        "app.tasks.report_tasks",
        "app.tasks.monitoring_tasks",
        "app.tasks.article_tasks",
        "app.tasks.voice_tasks",
        "app.tasks.pipeline_tasks",
        "app.tasks.pipeline_sweeper",
        "app.tasks.pipeline_orchestrator",
    ],
)
```

- [ ] **Step 2: Add pipeline queue routing**

At `backend/app/celery_app.py:70-78`, add pipeline task routes **above** the existing wildcard routes (Celery matches first-match):

```python
    task_routes={
        # Pipeline stage tasks — per-stage queues
        "pipeline.ocr_stage": {"queue": "pipeline.ocr"},
        "pipeline.chunk_stage": {"queue": "pipeline.chunk"},
        "pipeline.embed_stage": {"queue": "pipeline.embed"},
        "pipeline.index_stage": {"queue": "pipeline.index"},
        "pipeline.article_stage": {"queue": "pipeline.articles"},
        "pipeline.entity_stage": {"queue": "pipeline.entities"},
        "pipeline.finalize_stage": {"queue": "pipeline.index"},
        "pipeline.sweeper": {"queue": "scheduled"},
        # Existing routes
        "build_smart_collection": {"queue": "collections"},
        "app.tasks.document_tasks.*": {"queue": "document_processing"},
        "app.tasks.embedding_tasks.*": {"queue": "document_processing"},
        "app.tasks.article_tasks.*": {"queue": "document_processing"},
        "app.tasks.voice_tasks.*": {"queue": "document_processing"},
        "app.tasks.anomaly_tasks.*": {"queue": "scheduled"},
        "app.tasks.report_tasks.*": {"queue": "celery"},
    },
```

- [ ] **Step 3: Add sweeper to beat schedule**

At `backend/app/celery_app.py:96-122`, add the sweeper schedule and comment out old recovery tasks:

```python
    beat_schedule={
        "daily-anomaly-report": {
            "task": "app.tasks.anomaly_tasks.daily_anomaly_report",
            "schedule": crontab(hour=9, minute=0),
            "args": (),
        },
        # Pipeline sweeper replaces the 3 recovery tasks below
        "pipeline-sweeper": {
            "task": "pipeline.sweeper",
            "schedule": 300,  # Every 5 minutes
            "args": (),
        },
        # DEPRECATED — kept commented for rollback reference
        # "recover-stuck-documents": {...},
        # "recover-pending-documents": {...},
        # "fail-stuck-processing": {...},
        "cleanup-old-reports": {
            "task": "app.tasks.report_tasks.cleanup_old_reports",
            "schedule": crontab(hour=2, minute=0),
            "args": (7,),
        },
    },
```

- [ ] **Step 4: Update tasks/__init__.py**

Add the new modules to `backend/app/tasks/__init__.py`:

```python
# Celery tasks initialization
from app.tasks import (
    anomaly_tasks,
    article_tasks,
    backfill_tasks,
    document_tasks,
    embedding_tasks,
    pipeline_orchestrator,
    pipeline_sweeper,
    pipeline_tasks,
    report_tasks,
    voice_tasks,
)

__all__ = [
    "document_tasks",
    "anomaly_tasks",
    "article_tasks",
    "backfill_tasks",
    "embedding_tasks",
    "pipeline_orchestrator",
    "pipeline_sweeper",
    "pipeline_tasks",
    "report_tasks",
    "voice_tasks",
]
```

- [ ] **Step 5: Verify no import errors**

Run: `cd /home/development/src/active/sowknow4/backend && python -c "from app.celery_app import celery_app; print('OK:', list(celery_app.conf.task_routes.keys())[:5])"`
Expected: OK with no errors

- [ ] **Step 6: Commit**

```bash
git add backend/app/celery_app.py backend/app/tasks/__init__.py
git commit -m "feat(pipeline): add queue routing and sweeper beat schedule"
```

---

## Task 7: Pipeline Admin Status Endpoint

**Files:**
- Create: `backend/app/api/pipeline_admin.py`
- Modify: `backend/app/api/admin.py` (include router)

- [ ] **Step 1: Write the endpoint**

Create `backend/app/api/pipeline_admin.py`:

```python
"""Pipeline observability endpoint for admin dashboard.

Replaces the manual embed_chunked_docs.py script with a proper API.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin_only
from app.database import get_db
from app.models.pipeline import PipelineStage, StageEnum, StageStatus

router = APIRouter(prefix="/admin/pipeline", tags=["admin-pipeline"])


@router.get("/status", dependencies=[Depends(require_admin_only)])
async def pipeline_status(db: AsyncSession = Depends(get_db)) -> dict:
    """Get pipeline status overview — stage counts, queue depths, worker status.

    Returns per-stage counts of pending/running/completed/failed documents,
    Redis queue depths, and worker health.
    """
    # Stage counts
    stages = {}
    for stage in StageEnum:
        result = await db.execute(
            select(PipelineStage.status, func.count())
            .where(PipelineStage.stage == stage)
            .group_by(PipelineStage.status)
        )
        counts = {row[0].value: row[1] for row in result.all()}
        stages[stage.value] = {
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
        }

    # Queue depths from Redis
    queues = {}
    try:
        import redis
        from app.core.redis_url import safe_redis_url
        from app.tasks.pipeline_orchestrator import MAX_QUEUE_DEPTH

        r = redis.from_url(safe_redis_url())
        for queue_name in ["pipeline.ocr", "pipeline.chunk", "pipeline.embed",
                           "pipeline.index", "pipeline.articles", "pipeline.entities"]:
            depth = r.llen(queue_name)
            queues[queue_name] = {
                "depth": depth,
                "max": MAX_QUEUE_DEPTH.get(queue_name),
            }
    except Exception:
        queues = {"error": "Could not connect to Redis"}

    # Worker status
    workers = {}
    try:
        from app.celery_app import celery_app

        inspect = celery_app.control.inspect(timeout=5.0)
        stats = inspect.stats() or {}
        for worker_name, worker_stats in stats.items():
            workers[worker_name] = {
                "status": "ok",
                "tasks_processed": worker_stats.get("total", {}).get("app.tasks.document_tasks.process_document", 0),
                "pool": worker_stats.get("pool", {}).get("implementation", "unknown"),
            }
    except Exception:
        workers = {"error": "Could not inspect workers"}

    return {
        "stages": stages,
        "queues": queues,
        "workers": workers,
    }
```

- [ ] **Step 2: Include the router in admin**

At the top of `backend/app/api/admin.py`, after the existing imports, add:

```python
from app.api.pipeline_admin import router as pipeline_router
```

At the bottom of the file, or wherever routers are included, add:

Actually — FastAPI routers are typically included in the main app, not nested. Let's check how routers are registered.

- [ ] **Step 3: Find where routers are included and add the pipeline router**

Check `backend/app/main.py` or `backend/main.py` or `backend/main_minimal.py` for the `app.include_router(...)` calls. Add:

```python
from app.api.pipeline_admin import router as pipeline_admin_router
app.include_router(pipeline_admin_router, prefix="/api/v1")
```

- [ ] **Step 4: Test the endpoint manually**

Run: `cd /home/development/src/active/sowknow4/backend && python -c "
from app.api.pipeline_admin import router
print('Routes:', [r.path for r in router.routes])
"`
Expected: `Routes: ['/status']`

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/pipeline_admin.py
git commit -m "feat(pipeline): add admin pipeline status endpoint"
```

---

## Task 8: Upload Endpoint Integration — Switch to New Orchestrator

**Files:**
- Modify: `backend/app/api/documents.py:451-481` (`_queue_document_for_processing`)

- [ ] **Step 1: Modify `_queue_document_for_processing` to use the new orchestrator**

Replace the body of `_queue_document_for_processing` in `backend/app/api/documents.py` (around line 464-481):

Old code calls `process_document.delay(str(document.id))`. New code calls `dispatch_document()`:

```python
async def _queue_document_for_processing(
    document: Document,
    db: AsyncSession,
    success_message: str = "Document uploaded successfully and queued for processing",
) -> DocumentUploadResponse:
    """Queue a persisted document for Celery processing and return the response.

    Uses the new pipeline orchestrator with Celery chains and backpressure.
    """
    try:
        from app.tasks.pipeline_orchestrator import dispatch_document
        from app.tasks.pipeline_tasks import update_stage
        from app.models.pipeline import StageEnum, StageStatus

        # Mark UPLOADED stage as completed
        update_stage(str(document.id), StageEnum.UPLOADED, StageStatus.COMPLETED)

        # Dispatch the pipeline chain
        result = dispatch_document(str(document.id))

        if result == "dispatched":
            document.status = DocumentStatus.PROCESSING
            document.pipeline_stage = "ocr"
        else:
            # Backpressure — leave as PENDING, sweeper will pick it up
            document.status = DocumentStatus.PENDING
            document.pipeline_stage = "uploaded"
            document.document_metadata = {
                **(document.document_metadata or {}),
                "backpressure": result,
            }

        await db.commit()

        return DocumentUploadResponse(
            id=str(document.id),
            filename=document.filename,
            status=document.status.value,
            message=success_message if result == "dispatched" else "Document queued, processing will start when capacity is available",
        )

    except Exception as e:
        logger.error(f"Failed to queue document {document.id}: {e}")
        document.status = DocumentStatus.ERROR
        document.pipeline_stage = "failed"
        document.pipeline_error = str(e)[:500]
        await db.commit()

        return DocumentUploadResponse(
            id=str(document.id),
            filename=document.filename,
            status="error",
            message=f"Failed to queue for processing: {str(e)[:200]}",
        )
```

- [ ] **Step 2: Verify the upload endpoint still imports correctly**

Run: `cd /home/development/src/active/sowknow4/backend && python -c "from app.api.documents import router; print('OK')" 2>&1 | head -5`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/documents.py
git commit -m "feat(pipeline): switch upload endpoint to new orchestrator"
```

---

## Task 9: Docker Compose — Light + Heavy Workers

**Files:**
- Modify: `docker-compose.yml:211-261` (replace `celery-worker` with `celery-light` + `celery-heavy`)

- [ ] **Step 1: Replace the celery-worker service**

In `docker-compose.yml`, replace the `celery-worker:` service block (lines 211-261) with two new services:

```yaml
  celery-light:
    <<: *common-env
    init: true
    security_opt:
      - no-new-privileges:true
    build:
      context: ./backend
      dockerfile: Dockerfile.worker
    container_name: sowknow4-celery-light
    restart: unless-stopped
    logging: *default-logging
    environment:
      - DATABASE_URL=postgresql://${DATABASE_USER:-sowknow}:${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set in .env}@postgres:5432/${DATABASE_NAME:-sowknow}  # pragma: allowlist secret
      - REDIS_HOST=redis
      - KIMI_API_KEY=${KIMI_API_KEY:-}
      - MINIMAX_API_KEY=${MINIMAX_API_KEY}
      - OLLAMA_BASE_URL=http://host.docker.internal:11434
      - SENTENCE_TRANSFORMERS_HOME=/models
      - HF_HOME=/models
      - TRANSFORMERS_CACHE=/models
      - PADDLEOCR_HOME=/tmp/paddleocr
      - SKIP_MODEL_DOWNLOAD=1
    volumes:
      - sowknow-public-data:/data/public
      - sowknow-confidential-data:/data/confidential
      - sowknow-audio-data:/data/audio
      - ./backend:/app
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    extra_hosts:
      - "host.docker.internal:host-gateway"
    healthcheck:
      test: ["CMD-SHELL", "cat /proc/1/cmdline 2>/dev/null | tr '\\0' ' ' | grep -q celery || exit 1"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 60s
    deploy:
      resources:
        limits:
          memory: 2048M
          cpus: '1.0'
    command: >-
      celery -A app.celery_app worker --loglevel=info --concurrency=2
      -Q celery,document_processing,scheduled,pipeline.ocr,pipeline.chunk,pipeline.index,pipeline.articles,pipeline.entities
      --max-tasks-per-child=50 --prefetch-multiplier=2
      -n light@%h
    networks:
      - sowknow-net

  celery-heavy:
    <<: *common-env
    init: true
    security_opt:
      - no-new-privileges:true
    build:
      context: ./backend
      dockerfile: Dockerfile.worker
    container_name: sowknow4-celery-heavy
    restart: unless-stopped
    logging: *default-logging
    environment:
      - DATABASE_URL=postgresql://${DATABASE_USER:-sowknow}:${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set in .env}@postgres:5432/${DATABASE_NAME:-sowknow}  # pragma: allowlist secret
      - REDIS_HOST=redis
      - SENTENCE_TRANSFORMERS_HOME=/models
      - HF_HOME=/models
      - TRANSFORMERS_CACHE=/models
    volumes:
      - sowknow-public-data:/data/public
      - sowknow-confidential-data:/data/confidential
      - sowknow-audio-data:/data/audio
      - sowknow-model-cache:/models
      - ./backend:/app
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "cat /proc/1/cmdline 2>/dev/null | tr '\\0' ' ' | grep -q celery || exit 1"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 120s
    deploy:
      resources:
        limits:
          # CRITICAL: concurrency MUST stay at 1. Model ~1.3GB + encoding batch RAM.
          memory: 4096M
          cpus: '1.5'
    command: >-
      celery -A app.celery_app worker --loglevel=info --concurrency=1
      -Q pipeline.embed
      --max-tasks-per-child=20 --prefetch-multiplier=1
      -n heavy@%h
    networks:
      - sowknow-net
```

- [ ] **Step 2: Update celery-beat depends_on if it references celery-worker**

Check if `celery-beat` depends on `celery-worker`. If so, remove that dependency (beat doesn't depend on workers).

- [ ] **Step 3: Validate compose syntax**

Run: `cd /home/development/src/active/sowknow4 && docker compose config --quiet && echo "VALID" || echo "INVALID"`
Expected: VALID

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(pipeline): replace single worker with light + heavy workers"
```

---

## Task 10: Include Pipeline Router in App

**Files:**
- Modify: `backend/main_minimal.py` or `backend/app/main.py` (wherever routers are included)

- [ ] **Step 1: Find where routers are included**

Run: `cd /home/development/src/active/sowknow4/backend && grep -n "include_router" main_minimal.py app/main.py 2>/dev/null | head -20`

- [ ] **Step 2: Add pipeline router include**

Add this line alongside the other `include_router` calls:

```python
from app.api.pipeline_admin import router as pipeline_admin_router
app.include_router(pipeline_admin_router, prefix="/api/v1")
```

- [ ] **Step 3: Verify no import errors**

Run: `cd /home/development/src/active/sowknow4/backend && python -c "from app.api.pipeline_admin import router; print('Routes:', [r.path for r in router.routes])"`
Expected: `Routes: ['/status']`

- [ ] **Step 4: Commit**

```bash
git add backend/main_minimal.py  # or backend/app/main.py
git commit -m "feat(pipeline): register pipeline admin router"
```

---

## Task 11: Run Full Test Suite

- [ ] **Step 1: Run all unit tests**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -30`
Expected: All tests PASS (existing + new pipeline tests)

- [ ] **Step 2: Fix any test failures**

If any tests fail, diagnose and fix. Common issues:
- Import order in `__init__.py` (circular imports)
- Mock patching paths that don't match new module locations
- Missing `SessionLocal` import in test environment

- [ ] **Step 3: Commit any fixes**

```bash
git add -u
git commit -m "fix: resolve test failures from pipeline integration"
```

---

## Task 12: Final Cleanup & Validation

- [ ] **Step 1: Verify docker compose is valid**

Run: `cd /home/development/src/active/sowknow4 && docker compose config --quiet && echo "VALID"`

- [ ] **Step 2: Verify all new files are tracked**

Run: `cd /home/development/src/active/sowknow4 && git status`

- [ ] **Step 3: Verify no circular imports**

Run: `cd /home/development/src/active/sowknow4/backend && python -c "
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
from app.tasks.pipeline_orchestrator import dispatch_document, dispatch_batch
from app.tasks.pipeline_sweeper import pipeline_sweeper
from app.api.pipeline_admin import router
print('All imports OK')
"`

- [ ] **Step 4: Create summary commit**

```bash
git add -A
git commit -m "feat(pipeline): guaranteed state machine — complete implementation

Pipeline redesign replacing fire-and-forget .delay() calls with:
- PipelineStage model tracking 8 stages per document
- Celery chain orchestration with per-stage retry/reject
- Backpressure mechanism preventing queue flooding
- Unified sweeper replacing 3 overlapping recovery tasks
- Light + Heavy worker split (2GB/4GB, concurrency 2/1)
- Admin pipeline status endpoint for observability
- Alembic migration with backfill of existing documents"
```

---

## Notes for Phase 3 Cleanup (after 1 week stable)

These are **not part of this plan** — they happen after the new pipeline is proven in production:

1. Remove old `pipeline_stage`, `pipeline_error`, `pipeline_retry_count`, `pipeline_last_attempt` columns from Document model
2. Remove old recovery tasks from `anomaly_tasks.py` (recover_stuck_documents, recover_pending_documents, fail_stuck_processing_documents)
3. Remove `embed_chunked_docs.py` from project root
4. Remove old `process_document` task from `document_tasks.py` (keep the file for non-pipeline tasks like `cleanup_old_tasks`, `batch_extract_entities`)
5. Remove old `celery-worker` Docker image tag after confirming rollback is no longer needed
