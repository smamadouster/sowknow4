# Smart Collections v2 — 3-Stage Pipeline with Articles-First Search

## Summary

Redesign the Smart Collections build pipeline with 3 changes:
1. **MiniMax 2.7 for all LLM calls** — remove Ollama from collections entirely (only filenames/titles sent, no PII risk)
2. **Dedicated Celery queue + lightweight worker** — collections never compete with OCR/embedding tasks
3. **Articles-first hybrid search with quality gates** — search articles first, fall back to chunks, retry on poor results

## Architecture: 3-Stage Pipeline

```
Stage 1: UNDERSTAND
  → MiniMax parses intent (keywords, entities, dates, doc types)
  → Pick search strategy based on intent
  → Quality gate: confidence < 0.5 → retry with simpler prompt → fallback to rule-based

Stage 2: GATHER + VERIFY
  → Run article_semantic + article_keyword + chunk_semantic + chunk_keyword + tag concurrently
  → Merge with RRF (articles 1.2x, tags 1.5x)
  → Group by document_id, prefer article as display item
  → Quality gate: results < 3 → broaden search (drop date filters, expand keywords)
  → Max 2 retries, then proceed with best results

Stage 3: SYNTHESIZE + DELIVER
  → Build rich context from article titles + summaries (not just filenames)
  → MiniMax generates collection summary
  → Create CollectionItems with article_id when available, document_id always
  → Set status = READY
```

## Change 1: MiniMax for Everything

**What changes:**
- `_generate_collection_summary()` — remove the `has_confidential` branch and Ollama call. Always use MiniMax directly (not OpenRouter).
- `build_collection_pipeline()` — remove `use_ollama` flag. Always pass `use_ollama=False` to intent parser.
- Remove `self.ollama_service` from CollectionService `__init__`.

**Why this is safe:** The collection summary prompt sends article titles, summaries, and filenames — never document content. No PII leaves the system.

**Why MiniMax direct instead of OpenRouter:** One fewer network hop. MiniMax M2.7 has 128K context, 120s timeout. Saves ~$0.002/call vs OpenRouter routing fee.

## Change 2: Dedicated Collections Queue

**Celery config (`celery_app.py`):**
```python
task_routes = {
    ...existing routes...
    "build_smart_collection": {"queue": "collections"},
}
```

**New container in `docker-compose.yml`:**
```yaml
celery-collections:
    build:
      context: ./backend
      dockerfile: Dockerfile.worker
    container_name: sowknow4-celery-collections
    command: celery -A app.celery_app worker --loglevel=info --concurrency=2 -Q collections
    environment:
      - SKIP_MODEL_DOWNLOAD=1  # No embedding model needed
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.5'
```

**Key:** `SKIP_MODEL_DOWNLOAD=1` + `--concurrency=2` because collection tasks are just HTTP calls to MiniMax, no heavy model loading.

## Change 3: Articles-First Hybrid Search

**New method: `_gather_and_verify()`** replaces `_gather_documents_for_intent()`

Search runs 5 concurrent tasks (same as hybrid_search but with explicit article priority):
1. `article_semantic_search(query, limit=50)` 
2. `article_keyword_search(query, limit=50)`
3. `semantic_search(query, limit=50)` — chunk-level, catches what articles miss
4. `keyword_search(query, limit=50)` — chunk-level fallback
5. `tag_search(query, limit=50)`

Results merged with RRF. Grouped by `document_id`. For each document, if an article exists, use it as the display item. If not, use the chunk.

**Quality gate:** If fewer than 3 results after merge:
- Attempt 2: Drop date range filter, search again
- Attempt 3: Use only keywords (no entity/type filters)
- After 3 attempts: proceed with whatever we have

**CollectionItem model change:**
- Add `article_id` column (UUID FK → articles, nullable)
- Keep `document_id` as required (traceability)
- When article exists: both `article_id` and `document_id` are set
- When no article: only `document_id` is set

**Summary generation context upgrade:**
Instead of filenames only, build context from articles:
```
- "Tax Declaration 2023" (Summary: Annual income tax filing for the Mboup household...)
- "Property Deed Ndakhte" (Summary: Transfer of property at Rue de la Paix to Ndakhte Mboup...)
```

This gives MiniMax much richer material for the collection summary.

## Migration

- Add `article_id` column to `collection_items` table (nullable FK)
- No data migration needed — existing items keep `document_id` only

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/collection_service.py` | Rewrite `build_collection_pipeline` as 3 stages, new `_gather_and_verify`, MiniMax-only summary |
| `backend/app/models/collection.py` | Add `article_id` to CollectionItem |
| `backend/app/celery_app.py` | Add `collections` queue route |
| `backend/app/tasks/document_tasks.py` | Update task routing for `build_smart_collection` |
| `docker-compose.yml` | Add `celery-collections` service |
| `backend/alembic/versions/016_*.py` | Migration for `article_id` column |
| `backend/app/schemas/collection.py` | Add `article_id`, `article_title`, `article_summary` to response |
| `backend/app/api/collections.py` | Update detail endpoint to include article info |
| `frontend/app/[locale]/collections/[id]/page.tsx` | Show article titles/summaries instead of just filenames |
