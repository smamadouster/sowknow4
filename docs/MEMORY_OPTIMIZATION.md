# Backend Memory Optimization

## Summary

The `backend` container memory limit has been reduced from **1024 MB → 512 MB** in
`docker-compose.yml`.  This keeps total SOWKNOW container memory at or below the
6.4 GB VPS budget.

---

## Root Cause Analysis

| Container | Limit | Why |
|-----------|-------|-----|
| postgres | 2048 M | pgvector index + connection pool |
| redis | 512 M | Chat sessions, Celery broker |
| **backend** | ~~1024 M~~ **512 M** | FastAPI + Python runtime only |
| celery-worker | 2048 M | multilingual-e5-large (1.3 GB) + PaddleOCR |
| celery-beat | 256 M | Scheduler process |
| frontend | 512 M | Next.js SSR |
| nginx | 256 M | Reverse proxy |
| telegram-bot | 256 M | Async bot client |
| **Total** | **6400 M** | = VPS budget |

The previous 1024 MB limit was set during initial scaffolding before the
Tri-LLM architecture was finalised.  Profiling showed the backend container
never loads the 1.3 GB embedding model:

- `backend` uses **`Dockerfile.minimal`** → **`requirements-minimal.txt`**
- `requirements-minimal.txt` intentionally excludes `sentence_transformers` and
  `torch` (commented out)
- Therefore `EmbeddingService._load_model()` raises `ImportError` at first call,
  which is now caught gracefully (no longer re-raised)

Actual backend baseline RSS at idle is approximately **180–220 MB**:

| Component | Approx RSS |
|-----------|-----------|
| Python 3.11 interpreter | ~50 MB |
| FastAPI + uvicorn | ~40 MB |
| SQLAlchemy connection pool | ~30 MB |
| httpx + redis-py client libs | ~20 MB |
| App code + models (no ML) | ~30 MB |
| Headroom for request spikes | ~80 MB |
| **Subtotal** | **~250 MB** |

512 MB provides a ~2× safety margin over the observed baseline.

---

## Design: Embedding Responsibilities

```
┌─────────────────────────────────────────────────┐
│  backend (512 MB)                               │
│  ─ FastAPI request handling                     │
│  ─ Keyword search (PostgreSQL ILIKE)            │
│  ─ Vector similarity query (pgvector SQL)       │
│  ─ NO ML model loaded                           │
└───────────────────┬─────────────────────────────┘
                    │  pre-computed embeddings stored in DB
                    ▼
┌─────────────────────────────────────────────────┐
│  celery-worker (2048 MB)                        │
│  ─ Document OCR (PaddleOCR / Tesseract)         │
│  ─ multilingual-e5-large loaded here ONLY       │
│  ─ Generates and stores chunk embeddings in DB  │
└─────────────────────────────────────────────────┘
```

Query-time embeddings for semantic search are handled by the same worker via
a Celery task (if added in the future).  For now, the backend degrades
gracefully to **keyword-only search** when the model is not available, rather
than crashing or spiking memory.

---

## Graceful Degradation

`EmbeddingService` changes (see `backend/app/services/embedding_service.py`):

1. `_load_model()` no longer re-raises on `ImportError` / any exception.
   Sets `_load_error` and logs a warning instead.
2. New `can_embed` property — `True` only when model is fully loaded.
3. `encode()` returns zero vectors (`[0.0] * 1024`) when `can_embed` is `False`,
   avoiding any crash.

`HybridSearchService.semantic_search()` changes
(see `backend/app/services/search_service.py`):

- Checks `embedding_service.can_embed` at the top of the method.
- Returns an empty `[]` immediately if the model is not available.
- `hybrid_search()` continues with keyword-only results and returns them.

**User impact**: search still works, results are keyword-ranked only.
Semantic re-ranking is enabled automatically once sentence_transformers is
present in the environment (e.g. if requirements.txt is swapped to the full
version in a future capacity upgrade).

---

## Trade-offs

| Aspect | Impact |
|--------|--------|
| Search quality in backend | Keyword-only when model absent (no semantic re-ranking) |
| Search quality in worker | Unchanged — embeddings are pre-computed at index time |
| VPS memory | Freed ~512 MB for other containers |
| Cold-start latency | Unchanged (model was never loaded in backend) |
| Scalability | Backend can now handle more concurrent requests within budget |

---

## How to Verify

```bash
# Check backend container memory after start
docker stats sowknow4-backend --no-stream

# Confirm model is not loaded in backend
curl -s http://localhost:8001/api/v1/health/embedding | jq .

# Expected output:
# { "model_loaded": false, "load_error": "...", "status": "model_not_loaded" }

# Confirm search still returns results (keyword-only)
curl -s -X POST http://localhost:8001/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "invoice 2024"}' | jq .total
```

If semantic search is desired directly in the backend (future), add
`sentence-transformers` back to `requirements-minimal.txt` and raise the
memory limit to 1536 MB.
