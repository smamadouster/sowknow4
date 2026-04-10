# Pipeline Redesign — Guaranteed State Machine

**Date:** 2026-04-06
**Status:** Draft
**Goal:** Replace the fire-and-forget document processing pipeline with a guaranteed state machine that never silently drops stages, splits work across dedicated workers, and provides built-in observability.

## Problem Statement

The current pipeline dispatches stages (embedding, articles, entities) as independent `.delay()` calls that can fail silently. When they do, documents are marked INDEXED but have no embeddings or articles — permanently degraded with no automatic recovery. This design caused 2,980 documents to stall without embeddings over a 2-day period.

Additional issues:
- Single worker (concurrency=1) bottleneck forced by 1.3GB embedding model
- Three overlapping recovery tasks with duplicated logic (one had a NameError bug)
- Recovery throttled to 10 docs/run = 50 hours to clear a 3,000-doc backlog
- No pipeline observability without running a manual script (`embed_chunked_docs.py`)
- Articles and entity extraction are afterthoughts, not guaranteed stages

## Design

### 1. Pipeline Stages

Every document follows a linear, guaranteed pipeline. No stage is skipped. No transition happens without proof the previous stage succeeded.

```
UPLOADED → OCR → CHUNKED → EMBEDDED → INDEXED → ARTICLES → ENTITIES → ENRICHED
                                                                          ↓
                                                                    ERROR (any stage)
```

| Stage | What Happens | Output | Worker |
|-------|-------------|--------|--------|
| `UPLOADED` | File validated, deduped, stored | File on disk | API (sync) |
| `OCR` | Text extraction (PaddleOCR/Tesseract) | `.txt` sidecar | Light |
| `CHUNKED` | Split into 512-token chunks | `DocumentChunk` rows | Light |
| `EMBEDDED` | Generate vectors for all chunks | `embedding_vector` filled | Heavy |
| `INDEXED` | Full-text search vectors updated | `search_vector` filled | Light |
| `ARTICLES` | LLM article generation from chunks | `Article` rows | Light |
| `ENTITIES` | Entity extraction for knowledge graph | Entity/relationship rows | Light |
| `ENRICHED` | Terminal success — fully processed | — | — |

### 2. Stage Tracking Table

New `pipeline_stages` table replaces scattered metadata fields:

```python
class PipelineStage(Base):
    __tablename__ = "pipeline_stages"

    id: UUID               # PK
    document_id: UUID      # FK → documents
    stage: StageEnum       # UPLOADED, OCR, CHUNKED, EMBEDDED, INDEXED, ARTICLES, ENTITIES, ENRICHED
    status: StageStatus    # PENDING, RUNNING, COMPLETED, FAILED, SKIPPED
    attempt: int           # current attempt number (starts at 0)
    max_attempts: int      # default 3, per-stage override
    started_at: datetime
    completed_at: datetime
    error_message: text    # full error, not truncated to 500 chars
    worker_id: str         # which worker processed this
    created_at: datetime
```

A document's "current stage" is always the earliest stage that is NOT `COMPLETED` or `SKIPPED`. No ambiguity.

**When `SKIPPED` applies:**
- Audio files with pre-existing transcripts: OCR stage is `SKIPPED` (text already provided)
- Journal entries with inline text: OCR stage is `SKIPPED`
- Documents with 0 chunks (e.g., empty files): EMBEDDED, INDEXED, ARTICLES, ENTITIES stages are `SKIPPED`, document goes straight to `ENRICHED`

### 3. Celery Chain Orchestration

When a document enters the pipeline, the orchestrator builds a Celery `chain()`:

```python
from celery import chain

def dispatch_document(document_id: str) -> str:
    """Build and dispatch the processing chain for a document."""
    # Check backpressure before dispatching
    embed_depth = redis.llen('pipeline.embed')
    if embed_depth > MAX_QUEUE_DEPTH['pipeline.embed']:
        return 'backpressure:embed'

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
    return 'dispatched'
```

Each stage task:
1. Creates/updates its `PipelineStage` row → `status=RUNNING`, `attempt+=1`
2. Does its work
3. Marks `status=COMPLETED`, returns `document_id` to next task in chain
4. On exception: retries up to `max_attempts` with exponential backoff, then marks `FAILED` and raises `Reject()` to stop the chain

No silent failures possible — the chain is atomic.

### 4. Worker Architecture

Two dedicated workers replace the single monolith:

| Worker | Container | Concurrency | Memory | Queues |
|--------|-----------|-------------|--------|--------|
| **Light** | `sowknow4-celery-light` | 2 | 2GB | `pipeline.ocr`, `pipeline.chunk`, `pipeline.index`, `pipeline.articles`, `pipeline.entities`, `scheduled` |
| **Heavy** | `sowknow4-celery-heavy` | 1 | 4GB | `pipeline.embed` |

**Why this split:**
- The 1.3GB embedding model forces concurrency=1 on the heavy worker (fork duplication would OOM)
- Light worker handles CPU-bound tasks (OCR, chunking) and I/O-bound tasks (LLM calls for articles/entities) — these don't need the model, so concurrency=2 is safe
- Total memory: 6GB (same as current 5.5GB + headroom)

**Worker lifecycle:**
- Heavy: `worker_max_tasks_per_child=20`, `prefetch=1`
- Light: `worker_max_tasks_per_child=50`, `prefetch=2`
- Celery Beat runs on light worker

**Queue-per-stage routing:**

```python
task_routes = {
    'pipeline.ocr_stage':      {'queue': 'pipeline.ocr'},
    'pipeline.chunk_stage':    {'queue': 'pipeline.chunk'},
    'pipeline.embed_stage':    {'queue': 'pipeline.embed'},
    'pipeline.index_stage':    {'queue': 'pipeline.index'},
    'pipeline.article_stage':  {'queue': 'pipeline.articles'},
    'pipeline.entity_stage':   {'queue': 'pipeline.entities'},
    'pipeline.finalize_stage': {'queue': 'pipeline.index'},
}
```

Per-stage queues enable instant observability: `redis-cli LLEN pipeline.embed` tells you exactly where the bottleneck is.

**Unchanged:** `sowknow4-celery-collections` (512MB, concurrency=2) stays as-is.

### 5. Per-Stage Retry Policy

| Stage | Max Attempts | Backoff | Timeout (soft/hard) | Typical Failure |
|-------|-------------|---------|---------------------|-----------------|
| `OCR` | 3 | 30s → 60s → 120s | 5min / 6min | Corrupted file, PaddleOCR crash |
| `CHUNKED` | 2 | 15s → 30s | 2min / 3min | Rarely fails |
| `EMBEDDED` | 3 | 60s → 120s → 300s | 30min / 33min | OOM, model load failure |
| `INDEXED` | 2 | 15s → 30s | 2min / 3min | DB connection issue |
| `ARTICLES` | 3 | 60s → 120s → 300s | 10min / 12min | OpenRouter down, rate limited |
| `ENTITIES` | 3 | 60s → 120s → 300s | 10min / 12min | LLM timeout |

Each stage task follows this pattern:

```python
@celery_app.task(bind=True, name='pipeline.ocr_stage',
                 max_retries=3, acks_late=True)
def ocr_stage(self, document_id):
    stage = update_stage(document_id, 'OCR', status='RUNNING')
    try:
        extract_text(document_id)
        update_stage(document_id, 'OCR', status='COMPLETED')
        return document_id
    except Exception as e:
        if stage.attempt >= stage.max_attempts:
            update_stage(document_id, 'OCR', status='FAILED', error=str(e))
            raise Reject()  # chain stops
        raise self.retry(countdown=BACKOFF[stage.attempt])
```

### 6. Recovery — The Sweeper

One unified task replaces three overlapping recovery tasks:

```python
@celery_beat(every=5, unit='minutes')
def pipeline_sweeper():
    """Find documents stuck at any stage and resume or park them."""

    # 1. STUCK RUNNING: stage RUNNING for > 2x its timeout
    #    → attempts < max: re-dispatch chain from that stage
    #    → attempts >= max: mark FAILED

    # 2. BACKPRESSURED: documents at UPLOADED with no chain dispatched
    #    → Check queue depths, dispatch if capacity available

    # 3. No throttle — processes ALL stuck docs each run
```

**Why one sweeper:**
- Current system has 3 recovery tasks with overlapping logic and a NameError bug caused by code duplication
- One task, one place to maintain

### 7. Backpressure

Prevents queueing more work than workers can handle:

```python
MAX_QUEUE_DEPTH = {
    'pipeline.embed': 20,
    'pipeline.ocr': 40,
    'pipeline.articles': 30,
}
```

The orchestrator checks queue depth before dispatching. If over limit, the document stays at `UPLOADED` — the sweeper picks it up when queues drain.

**Batch orchestrator** for bulk imports:

```python
def dispatch_batch(document_ids: list[str]):
    for doc_id in document_ids:
        result = dispatch_document(doc_id)
        if result.startswith('backpressure'):
            break  # sweeper resumes later
```

### 8. Observability

Pipeline status becomes a first-class admin endpoint (replaces `embed_chunked_docs.py`):

```
GET /api/v1/admin/pipeline/status

{
  "stages": {
    "OCR":      {"pending": 3, "running": 2, "completed": 2950, "failed": 1},
    "EMBEDDED": {"pending": 45, "running": 1, "completed": 2900, "failed": 5},
    "ARTICLES": {"pending": 100, "running": 2, "completed": 2800, "failed": 12}
  },
  "queues": {
    "pipeline.embed": {"depth": 18, "max": 20},
    "pipeline.ocr": {"depth": 5, "max": 40}
  },
  "workers": {
    "light": {"status": "ok", "tasks_processed": 1520},
    "heavy": {"status": "ok", "tasks_processed": 890}
  }
}
```

## Migration Plan

### Phase 1: Database Migration (no downtime)

- Add `pipeline_stages` table via Alembic
- Keep old `pipeline_stage`, `pipeline_error`, `pipeline_retry_count` fields on Document
- Backfill `pipeline_stages` rows for all existing documents:
  - `status=INDEXED` + chunks + embeddings → all stages COMPLETED through INDEXED; ARTICLES/ENTITIES as PENDING
  - `status=INDEXED` + chunks + no embeddings → COMPLETED through CHUNKED; EMBEDDED as PENDING
  - `status=ERROR` → map to failed stage based on `pipeline_stage` field
  - `status=PENDING/PROCESSING` → OCR as PENDING

### Phase 2: Deploy New Workers (~2 min downtime)

- Stop old `sowknow4-celery-worker`
- Start `sowknow4-celery-light` + `sowknow4-celery-heavy`
- Deploy new pipeline task code
- Start Celery Beat with sweeper
- Old queues drained during transition

### Phase 3: Cleanup (after 1 week stable)

- Remove old `pipeline_stage`, `pipeline_error`, `pipeline_retry_count` from Document model
- Remove old task files and recovery functions
- Remove `embed_chunked_docs.py`

### Backlog Strategy

**Immediate (before redesign):** Restart current worker, run existing backfill to unblock 2,980 docs.

**After deploy:** Migration backfill creates `pipeline_stages` rows. Sweeper picks up any remaining `EMBEDDED:PENDING` docs and queues them through the new chain.

### Rollback Plan

- Stop light + heavy workers, restart old `sowknow4-celery-worker` (keep old image tagged 1 week)
- Old `pipeline_stage` fields still exist during Phase 2
- Phase 3 cleanup intentionally delayed 1 week for this reason

## What Gets Deleted

| Old Component | Replaced By |
|---------------|-------------|
| `document_tasks.py` → `process_document()` | Pipeline chain |
| `anomaly_tasks.py` → 3 recovery tasks | `pipeline_sweeper()` |
| `embedding_tasks.py` → `recompute_embeddings_for_document()` | `embed_stage()` |
| `backfill_tasks.py` | Migration backfill + sweeper |
| `embed_chunked_docs.py` | `/api/v1/admin/pipeline/status` |
| `document.pipeline_stage` field | `pipeline_stages` table |
| `sowknow4-celery-worker` container | `sowknow4-celery-light` + `sowknow4-celery-heavy` |

## What Stays Unchanged

- Upload API endpoints — same interface, calls new orchestrator
- `sowknow4-celery-collections` worker
- Document / DocumentChunk models (except removing old pipeline fields in Phase 3)
- Embedding service, OCR service, chunking service, article generation service, entity extraction service — same logic, wrapped in stage tasks
- Deduplication, storage, encryption — untouched
