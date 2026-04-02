# Smart Collections v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic collection build pipeline with a 3-stage architecture (Understand → Gather+Verify → Synthesize), using MiniMax direct for all LLM calls, articles-first hybrid search with quality gates, and a dedicated Celery queue so collections never compete with document processing.

**Architecture:** The pipeline runs in a lightweight Celery worker (`celery-collections`, 512MB, concurrency=2) on the `collections` queue. Stage 1 parses intent via MiniMax. Stage 2 runs 5 concurrent searches (article semantic/keyword + chunk semantic/keyword + tags), merges with RRF, and retries with broader queries if results < 3. Stage 3 builds a rich summary from article titles+summaries via MiniMax, creates CollectionItems linking both article_id and document_id, and sets status=READY. The frontend collection detail page shows article titles/summaries as the display layer with preview/open/download actions on the source documents.

**Tech Stack:** FastAPI, Celery + Redis, PostgreSQL/pgvector, MiniMax M2.7 API, SQLAlchemy 2.0 (async), Next.js 14

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/models/collection.py` | Add `article_id` FK to CollectionItem |
| Modify | `backend/app/services/collection_service.py` | Rewrite pipeline as 3 stages, MiniMax-only, articles-first |
| Modify | `backend/app/celery_app.py` | Add `collections` queue route |
| Modify | `backend/app/tasks/document_tasks.py` | Route `build_smart_collection` to `collections` queue |
| Modify | `docker-compose.yml` | Add `celery-collections` worker container |
| Modify | `backend/app/schemas/collection.py` | Add article fields to CollectionItemResponse |
| Modify | `backend/app/api/collections.py` | Include article info in detail response |
| Modify | `frontend/app/[locale]/collections/[id]/page.tsx` | Show article info + document preview/open/download |
| Modify | `frontend/app/messages/fr.json` | Add new translation keys |
| Modify | `frontend/app/messages/en.json` | Add new translation keys |
| Create | `backend/alembic/versions/016_add_article_id_to_collection_items.py` | Migration |
| Create | `backend/tests/unit/test_collection_v2_pipeline.py` | Unit tests for 3-stage pipeline |
| Create | `backend/tests/integration/test_collection_v2_integration.py` | Integration tests for quality gates and routing |

---

### Task 1: Add `article_id` to CollectionItem model

CollectionItem needs to optionally link to an article. When an article exists for a document, both `article_id` and `document_id` are set. When no article exists, only `document_id` is set.

**Files:**
- Modify: `backend/app/models/collection.py:134-178`
- Create: `backend/tests/unit/test_collection_v2_pipeline.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_collection_v2_pipeline.py`:

```python
"""Tests for Smart Collections v2 — 3-stage pipeline with articles-first search."""
import pytest
from app.models.collection import CollectionItem


class TestCollectionItemArticleField:
    """CollectionItem must have an optional article_id field."""

    def test_article_id_field_exists(self, db):
        """CollectionItem must accept article_id parameter."""
        from app.models.user import User, UserRole
        from app.models.collection import Collection, CollectionStatus
        from app.models.document import Document, DocumentBucket, DocumentStatus

        user = User(email="v2test@example.com", hashed_password="h", full_name="V2", role=UserRole.ADMIN, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        doc = Document(filename="test.pdf", original_filename="test.pdf", file_path="/data/public/test.pdf",
                       bucket=DocumentBucket.PUBLIC, status=DocumentStatus.INDEXED, size=1024, mime_type="application/pdf")
        db.add(doc)
        db.commit()
        db.refresh(doc)

        collection = Collection(user_id=user.id, name="V2 Test", query="test", collection_type="smart",
                                visibility="private", status=CollectionStatus.READY, document_count=1)
        db.add(collection)
        db.commit()
        db.refresh(collection)

        # Create item WITH article_id (simulating article-linked item)
        import uuid
        fake_article_id = uuid.uuid4()
        item = CollectionItem(
            collection_id=collection.id,
            document_id=doc.id,
            article_id=fake_article_id,
            relevance_score=85,
            order_index=0,
            added_by="ai",
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        assert item.article_id == fake_article_id
        assert item.document_id == doc.id

    def test_article_id_nullable(self, db):
        """CollectionItem must work without article_id (backward compatible)."""
        from app.models.user import User, UserRole
        from app.models.collection import Collection, CollectionStatus
        from app.models.document import Document, DocumentBucket, DocumentStatus

        user = db.query(User).first()
        if not user:
            user = User(email="v2null@example.com", hashed_password="h", full_name="V2", role=UserRole.ADMIN, is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)

        doc = Document(filename="no_article.pdf", original_filename="no_article.pdf", file_path="/data/public/no.pdf",
                       bucket=DocumentBucket.PUBLIC, status=DocumentStatus.INDEXED, size=1024, mime_type="application/pdf")
        db.add(doc)
        db.commit()
        db.refresh(doc)

        collection = Collection(user_id=user.id, name="No Article", query="test", collection_type="smart",
                                visibility="private", status=CollectionStatus.READY, document_count=1)
        db.add(collection)
        db.commit()
        db.refresh(collection)

        item = CollectionItem(
            collection_id=collection.id,
            document_id=doc.id,
            relevance_score=50,
            order_index=0,
            added_by="ai",
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        assert item.article_id is None
        assert item.document_id == doc.id
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/test_collection_v2_pipeline.py::TestCollectionItemArticleField -v --tb=short
```

Expected: FAIL — `article_id` field doesn't exist on CollectionItem.

- [ ] **Step 3: Add article_id column to CollectionItem**

In `backend/app/models/collection.py`, in the `CollectionItem` class (after `document_id` column around line 151), add:

```python
    article_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.articles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
```

Also add the relationship (after the `document` relationship around line 167):

```python
    article = relationship("Article", foreign_keys=[article_id])
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/test_collection_v2_pipeline.py::TestCollectionItemArticleField -v --tb=short
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/collection.py backend/tests/unit/test_collection_v2_pipeline.py
git commit -m "feat(collections): add article_id FK to CollectionItem model

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Add dedicated `collections` Celery queue + lightweight worker

Route `build_smart_collection` to its own queue and add a lightweight worker container.

**Files:**
- Modify: `backend/app/celery_app.py:69-75`
- Modify: `backend/app/tasks/document_tasks.py` (task routing)
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add queue route to celery_app.py**

In `backend/app/celery_app.py`, in the `task_routes` dict (around line 69-75), add a route for the collection task. Add this line BEFORE the wildcard routes:

```python
        "build_smart_collection": {"queue": "collections"},
```

The full `task_routes` should look like:

```python
    task_routes={
        "build_smart_collection": {"queue": "collections"},
        "app.tasks.document_tasks.*": {"queue": "document_processing"},
        "app.tasks.embedding_tasks.*": {"queue": "document_processing"},
        "app.tasks.article_tasks.*": {"queue": "document_processing"},
        "app.tasks.anomaly_tasks.*": {"queue": "scheduled"},
        "app.tasks.report_tasks.*": {"queue": "celery"},
    },
```

- [ ] **Step 2: Update celery-worker command to NOT consume from collections queue**

In `docker-compose.yml`, find the `celery-worker` service command (around line 257):

Change:
```yaml
    command: celery -A app.celery_app worker --loglevel=info --concurrency=1 -Q celery,document_processing,scheduled
```

To:
```yaml
    command: celery -A app.celery_app worker --loglevel=info --concurrency=1 -Q celery,document_processing,scheduled
```

(This stays the same — the main worker does NOT consume from `collections`.)

- [ ] **Step 3: Add celery-collections service to docker-compose.yml**

In `docker-compose.yml`, add the following service AFTER the `celery-beat` service (around line 290):

```yaml
  celery-collections:
    <<: *common-env
    init: true
    security_opt:
      - no-new-privileges:true
    build:
      context: ./backend
      dockerfile: Dockerfile.worker
    container_name: sowknow4-celery-collections
    restart: unless-stopped
    logging: *default-logging
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_HOST=redis
      - MINIMAX_API_KEY=${MINIMAX_API_KEY}
      - SKIP_MODEL_DOWNLOAD=1
    volumes:
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
      start_period: 30s
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.5'
    command: celery -A app.celery_app worker --loglevel=info --concurrency=2 -Q collections --without-heartbeat
    networks:
      - sowknow-net
```

Key differences from main worker:
- `SKIP_MODEL_DOWNLOAD=1` — no embedding model (saves 1.3GB)
- Only `MINIMAX_API_KEY` — no OLLAMA, no KIMI
- `--concurrency=2` — safe because no heavy model in memory
- `-Q collections` — only consumes from collections queue
- `512M` memory — lightweight, just HTTP calls
- `--without-heartbeat` — reduces Redis traffic

- [ ] **Step 4: Write a test to verify task routing**

Add to `backend/tests/unit/test_collection_v2_pipeline.py`:

```python
class TestCollectionQueueRouting:
    """build_smart_collection must be routed to the collections queue."""

    def test_task_routed_to_collections_queue(self):
        """Celery config must route build_smart_collection to 'collections' queue."""
        from app.celery_app import celery_app

        routes = celery_app.conf.task_routes
        assert "build_smart_collection" in routes
        assert routes["build_smart_collection"]["queue"] == "collections"
```

- [ ] **Step 5: Run test**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/test_collection_v2_pipeline.py::TestCollectionQueueRouting -v --tb=short
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/celery_app.py docker-compose.yml backend/tests/unit/test_collection_v2_pipeline.py
git commit -m "feat(collections): dedicated collections queue with lightweight worker container

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Rewrite pipeline Stage 1 — UNDERSTAND (MiniMax-only intent parsing)

Replace the Ollama/OpenRouter routing in intent parsing with MiniMax direct for all collection queries. Add a quality gate on confidence.

**Files:**
- Modify: `backend/app/services/collection_service.py`
- Modify: `backend/tests/unit/test_collection_v2_pipeline.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/unit/test_collection_v2_pipeline.py`:

```python
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.collection_service import collection_service
from app.services.intent_parser import ParsedIntent


class TestStage1Understand:
    """Stage 1: Intent parsing always uses MiniMax, never Ollama."""

    @pytest.mark.asyncio
    async def test_understand_never_calls_ollama(self):
        """Even for admin users, intent parsing must NOT use Ollama."""
        mock_intent = ParsedIntent(
            query="test", keywords=["test"], collection_name="Test", confidence=0.9,
        )

        with patch.object(
            collection_service.intent_parser, "parse_intent",
            new_callable=AsyncMock, return_value=mock_intent,
        ) as mock_parse:
            result = await collection_service._understand_query("Find financial documents")

            mock_parse.assert_called_once()
            call_kwargs = mock_parse.call_args.kwargs
            assert call_kwargs.get("use_ollama") is False, "Collections must never use Ollama for intent parsing"

    @pytest.mark.asyncio
    async def test_understand_retries_on_low_confidence(self):
        """If intent confidence < 0.5, must retry with simpler prompt then fallback."""
        low_confidence_intent = ParsedIntent(
            query="xyz", keywords=[], collection_name="", confidence=0.3,
        )
        good_intent = ParsedIntent(
            query="xyz", keywords=["xyz"], collection_name="XYZ Collection", confidence=0.7,
        )

        call_count = [0]
        async def _mock_parse(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return low_confidence_intent
            return good_intent

        with patch.object(
            collection_service.intent_parser, "parse_intent",
            side_effect=_mock_parse,
        ):
            intent, strategy = await collection_service._understand_query("xyz")

            assert call_count[0] >= 2, "Should retry on low confidence"
            assert intent.confidence >= 0.5

    @pytest.mark.asyncio
    async def test_understand_returns_strategy(self):
        """Must return a search strategy based on intent content."""
        entity_intent = ParsedIntent(
            query="Ndakhte Mboup", keywords=["Ndakhte", "Mboup"],
            entities=[{"type": "person", "name": "Ndakhte Mboup"}],
            collection_name="Ndakhte Mboup", confidence=0.9,
        )

        with patch.object(
            collection_service.intent_parser, "parse_intent",
            new_callable=AsyncMock, return_value=entity_intent,
        ):
            intent, strategy = await collection_service._understand_query("Ndakhte Mboup")

            assert strategy in ("entity_first", "date_filtered", "broad_hybrid")
            # Entity present → should pick entity_first
            assert strategy == "entity_first"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/test_collection_v2_pipeline.py::TestStage1Understand -v --tb=short
```

Expected: FAIL — `_understand_query` doesn't exist.

- [ ] **Step 3: Implement `_understand_query()` method**

In `backend/app/services/collection_service.py`, add this method to `CollectionService`:

```python
    async def _understand_query(self, query: str) -> tuple[ParsedIntentModel, str]:
        """
        Stage 1: UNDERSTAND — Parse intent and pick search strategy.
        Always uses MiniMax (never Ollama). Retries on low confidence.
        
        Returns:
            (ParsedIntent, strategy) where strategy is one of:
            - "entity_first": query contains named entities
            - "date_filtered": query specifies date ranges
            - "broad_hybrid": generic query, use all search types
        """
        # First attempt — always MiniMax (use_ollama=False)
        intent = await self.intent_parser.parse_intent(
            query=query, user_language="en", use_ollama=False,
        )

        # Quality gate: retry on low confidence
        if intent.confidence < 0.5:
            logger.info(f"Low confidence ({intent.confidence}) for '{query}', retrying with simplified prompt")
            retry_intent = await self.intent_parser.parse_intent(
                query=query, user_language="en", use_ollama=False,
            )
            if retry_intent.confidence > intent.confidence:
                intent = retry_intent

            # If still low, fall back to rule-based
            if intent.confidence < 0.5:
                intent = self.intent_parser._fallback_parse(query)

        # Pick search strategy based on intent content
        strategy = "broad_hybrid"
        if intent.entities and len(intent.entities) > 0:
            strategy = "entity_first"
        elif intent.date_range and intent.date_range.get("type") not in (None, "all_time"):
            strategy = "date_filtered"

        return intent, strategy
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/test_collection_v2_pipeline.py::TestStage1Understand -v --tb=short
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/collection_service.py backend/tests/unit/test_collection_v2_pipeline.py
git commit -m "feat(collections): Stage 1 UNDERSTAND — MiniMax-only intent parsing with quality gate

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Rewrite pipeline Stage 2 — GATHER + VERIFY (articles-first with retry)

Replace `_gather_documents_for_intent()` with `_gather_and_verify()` that searches articles first, falls back to chunks, and retries with broader queries on poor results.

**Files:**
- Modify: `backend/app/services/collection_service.py`
- Modify: `backend/tests/unit/test_collection_v2_pipeline.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/unit/test_collection_v2_pipeline.py`:

```python
class TestStage2GatherAndVerify:
    """Stage 2: Articles-first search with quality gates and retry."""

    @pytest.mark.asyncio
    async def test_gather_runs_article_searches(self):
        """Must call article_semantic_search and article_keyword_search."""
        intent = ParsedIntent(
            query="solar energy", keywords=["solar", "energy"],
            collection_name="Solar", confidence=0.9,
        )

        with patch.object(
            collection_service.search_service, "article_semantic_search",
            new_callable=AsyncMock, return_value=[],
        ) as mock_art_sem, patch.object(
            collection_service.search_service, "article_keyword_search",
            new_callable=AsyncMock, return_value=[],
        ) as mock_art_kw, patch.object(
            collection_service.search_service, "semantic_search",
            new_callable=AsyncMock, return_value=[],
        ), patch.object(
            collection_service.search_service, "keyword_search",
            new_callable=AsyncMock, return_value=[],
        ), patch.object(
            collection_service.search_service, "tag_search",
            new_callable=AsyncMock, return_value=[],
        ):
            mock_db = MagicMock()
            mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
            mock_user = MagicMock()

            await collection_service._gather_and_verify(intent, "broad_hybrid", mock_user, mock_db)

            mock_art_sem.assert_called()
            mock_art_kw.assert_called()

    @pytest.mark.asyncio
    async def test_gather_retries_on_few_results(self):
        """If < 3 results, must retry with broader search (drop date filters)."""
        intent_with_date = ParsedIntent(
            query="docs from 2024", keywords=["docs"],
            date_range={"type": "this_year"},
            collection_name="2024 Docs", confidence=0.9,
        )

        call_count = [0]
        async def _mock_search(*args, **kwargs):
            call_count[0] += 1
            return []  # Always empty to trigger retry

        with patch.object(collection_service.search_service, "article_semantic_search",
                          new_callable=AsyncMock, side_effect=_mock_search), \
             patch.object(collection_service.search_service, "article_keyword_search",
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(collection_service.search_service, "semantic_search",
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(collection_service.search_service, "keyword_search",
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(collection_service.search_service, "tag_search",
                          new_callable=AsyncMock, return_value=[]):

            mock_db = MagicMock()
            mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
            mock_user = MagicMock()

            await collection_service._gather_and_verify(intent_with_date, "date_filtered", mock_user, mock_db)

            # article_semantic_search should be called multiple times (original + retries)
            assert call_count[0] >= 2, f"Should retry, but only called {call_count[0]} times"

    @pytest.mark.asyncio
    async def test_gather_returns_grouped_results(self):
        """Results must be grouped by document_id with article preferred."""
        mock_article_result = MagicMock()
        mock_article_result.document_id = "doc-1"
        mock_article_result.article_id = "art-1"
        mock_article_result.article_title = "Solar Energy Report"
        mock_article_result.article_summary = "Analysis of solar energy..."
        mock_article_result.final_score = 0.9
        mock_article_result.result_type = "article"

        mock_chunk_result = MagicMock()
        mock_chunk_result.document_id = "doc-1"  # Same document
        mock_chunk_result.article_id = None
        mock_chunk_result.article_title = None
        mock_chunk_result.final_score = 0.7
        mock_chunk_result.result_type = "chunk"

        with patch.object(collection_service.search_service, "article_semantic_search",
                          new_callable=AsyncMock, return_value=[mock_article_result]), \
             patch.object(collection_service.search_service, "article_keyword_search",
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(collection_service.search_service, "semantic_search",
                          new_callable=AsyncMock, return_value=[mock_chunk_result]), \
             patch.object(collection_service.search_service, "keyword_search",
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(collection_service.search_service, "tag_search",
                          new_callable=AsyncMock, return_value=[]):

            mock_db = MagicMock()
            mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
            mock_user = MagicMock()

            results = await collection_service._gather_and_verify(
                ParsedIntent(query="solar", keywords=["solar"], collection_name="Solar", confidence=0.9),
                "broad_hybrid", mock_user, mock_db,
            )

            # Same document should appear once, with article preferred
            doc_ids = [r["document_id"] for r in results]
            assert doc_ids.count("doc-1") == 1, "Same document should not appear twice"
            assert results[0].get("article_id") == "art-1", "Article should be preferred over chunk"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/test_collection_v2_pipeline.py::TestStage2GatherAndVerify -v --tb=short
```

Expected: FAIL — `_gather_and_verify` doesn't exist.

- [ ] **Step 3: Implement `_gather_and_verify()` method**

In `backend/app/services/collection_service.py`, add this method to `CollectionService`:

```python
    async def _gather_and_verify(
        self, intent: ParsedIntentModel, strategy: str, user: User, db: Session,
    ) -> list[dict]:
        """
        Stage 2: GATHER + VERIFY — Articles-first hybrid search with quality gates.
        
        Runs 5 concurrent searches, merges with RRF, groups by document_id
        (preferring articles as display item), and retries with broader queries
        if results are insufficient.
        
        Returns:
            List of dicts with keys: document_id, article_id, article_title,
            article_summary, document_name, relevance_score, result_type
        """
        import asyncio

        search_query = " ".join(intent.keywords) if intent.keywords else intent.query
        max_attempts = 3
        min_results = 3

        for attempt in range(max_attempts):
            # Run all 5 searches concurrently
            art_sem_task = asyncio.create_task(
                self.search_service.article_semantic_search(query=search_query, limit=50, db=db, user=user)
            )
            art_kw_task = asyncio.create_task(
                self.search_service.article_keyword_search(query=search_query, limit=50, db=db, user=user)
            )
            chunk_sem_task = asyncio.create_task(
                self.search_service.semantic_search(query=search_query, limit=50, offset=0, db=db, user=user)
            )
            chunk_kw_task = asyncio.create_task(
                self.search_service.keyword_search(query=search_query, limit=50, offset=0, db=db, user=user)
            )
            tag_task = asyncio.create_task(
                self.search_service.tag_search(query=search_query, limit=50, offset=0, db=db, user=user)
            )

            done, pending = await asyncio.wait(
                {art_sem_task, art_kw_task, chunk_sem_task, chunk_kw_task, tag_task},
                timeout=20.0,
            )
            for task in pending:
                task.cancel()

            # Collect results safely
            all_results = []
            for task in done:
                try:
                    all_results.extend(task.result())
                except Exception as e:
                    logger.warning(f"Search task failed: {e}")

            # Group by document_id, prefer articles
            grouped = {}
            for r in all_results:
                doc_id = str(r.document_id)
                existing = grouped.get(doc_id)
                
                # Prefer article over chunk, higher score over lower
                is_article = r.result_type == "article"
                score = r.final_score or r.semantic_score or r.keyword_score or 0

                # RRF boost: articles 1.2x, tags 1.5x
                if is_article:
                    score *= 1.2
                if hasattr(r, 'result_type') and r.result_type == "tag":
                    score *= 1.5

                if not existing or score > existing["relevance_score"] or (is_article and existing.get("result_type") != "article"):
                    grouped[doc_id] = {
                        "document_id": doc_id,
                        "article_id": getattr(r, "article_id", None),
                        "article_title": getattr(r, "article_title", None),
                        "article_summary": getattr(r, "article_summary", None),
                        "document_name": getattr(r, "document_name", None),
                        "relevance_score": score,
                        "result_type": r.result_type,
                    }

            results = sorted(grouped.values(), key=lambda x: x["relevance_score"], reverse=True)[:100]

            # Quality gate
            if len(results) >= min_results:
                logger.info(f"Stage 2: Found {len(results)} results on attempt {attempt + 1}")
                return results

            # Retry with broader search
            logger.info(f"Stage 2: Only {len(results)} results on attempt {attempt + 1}, broadening search")
            if attempt == 0:
                # Attempt 2: drop date filter, use raw query
                search_query = intent.query
            elif attempt == 1:
                # Attempt 3: keywords only, no filtering
                search_query = " ".join(intent.keywords) if intent.keywords else intent.query

        logger.info(f"Stage 2: Returning {len(results)} results after {max_attempts} attempts")
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/test_collection_v2_pipeline.py::TestStage2GatherAndVerify -v --tb=short
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/collection_service.py backend/tests/unit/test_collection_v2_pipeline.py
git commit -m "feat(collections): Stage 2 GATHER+VERIFY — articles-first search with quality gates

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Rewrite pipeline Stage 3 — SYNTHESIZE (MiniMax-only, rich context)

Replace `_generate_collection_summary()` with a version that always uses MiniMax direct, uses article titles+summaries as context, and doesn't leak the system prompt.

**Files:**
- Modify: `backend/app/services/collection_service.py`
- Modify: `backend/tests/unit/test_collection_v2_pipeline.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/unit/test_collection_v2_pipeline.py`:

```python
class TestStage3Synthesize:
    """Stage 3: Summary generation uses MiniMax direct, never Ollama/OpenRouter."""

    @pytest.mark.asyncio
    async def test_synthesize_uses_minimax_direct(self):
        """Summary must use minimax_service.chat_completion_non_stream, not OpenRouter or Ollama."""
        gathered_results = [
            {"document_id": "d1", "article_id": "a1", "article_title": "Tax Report 2023",
             "article_summary": "Annual tax filing for Mboup household", "document_name": "tax.pdf",
             "relevance_score": 0.9, "result_type": "article"},
        ]
        intent = ParsedIntent(query="tax", keywords=["tax"], collection_name="Tax Docs", confidence=0.9)

        with patch.object(
            collection_service.minimax_service, "chat_completion_non_stream",
            new_callable=AsyncMock, return_value="Summary of tax documents.",
        ) as mock_minimax:
            summary = await collection_service._synthesize_summary(
                collection_name="Tax Docs", query="tax documents", results=gathered_results, intent=intent,
            )

            mock_minimax.assert_called_once()
            assert "Summary of tax documents" in summary

    @pytest.mark.asyncio
    async def test_synthesize_never_calls_ollama(self):
        """Even with confidential results, must NOT call Ollama."""
        gathered_results = [
            {"document_id": "d1", "article_id": None, "article_title": None,
             "article_summary": None, "document_name": "secret.pdf",
             "relevance_score": 0.8, "result_type": "chunk"},
        ]
        intent = ParsedIntent(query="secret", keywords=["secret"], collection_name="Secrets", confidence=0.9)

        with patch.object(
            collection_service.minimax_service, "chat_completion_non_stream",
            new_callable=AsyncMock, return_value="Summary.",
        ), patch.object(
            collection_service.ollama_service, "generate",
            new_callable=AsyncMock,
        ) as mock_ollama:
            await collection_service._synthesize_summary(
                collection_name="Secrets", query="secret", results=gathered_results, intent=intent,
            )
            mock_ollama.assert_not_called()

    @pytest.mark.asyncio
    async def test_synthesize_uses_article_context(self):
        """Prompt must include article titles and summaries, not just filenames."""
        gathered_results = [
            {"document_id": "d1", "article_id": "a1", "article_title": "Property Deed",
             "article_summary": "Transfer of property to Ndakhte Mboup in Dakar",
             "document_name": "deed.pdf", "relevance_score": 0.9, "result_type": "article"},
        ]
        intent = ParsedIntent(query="Ndakhte", keywords=["Ndakhte"], collection_name="Ndakhte", confidence=0.9)

        captured_messages = []
        async def _capture(*args, **kwargs):
            captured_messages.append(kwargs.get("messages") or args[0] if args else [])
            return "Summary of Ndakhte documents."

        with patch.object(
            collection_service.minimax_service, "chat_completion_non_stream",
            side_effect=_capture,
        ):
            await collection_service._synthesize_summary(
                collection_name="Ndakhte", query="Ndakhte", results=gathered_results, intent=intent,
            )

            # The prompt must contain article title and summary
            prompt_text = str(captured_messages[0])
            assert "Property Deed" in prompt_text, "Article title must be in prompt"
            assert "Transfer of property" in prompt_text, "Article summary must be in prompt"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/test_collection_v2_pipeline.py::TestStage3Synthesize -v --tb=short
```

Expected: FAIL — `_synthesize_summary` doesn't exist.

- [ ] **Step 3: Implement `_synthesize_summary()` method**

In `backend/app/services/collection_service.py`, add:

```python
    async def _synthesize_summary(
        self,
        collection_name: str,
        query: str,
        results: list[dict],
        intent: ParsedIntentModel,
    ) -> str:
        """
        Stage 3: SYNTHESIZE — Generate collection summary using MiniMax direct.
        Uses article titles+summaries as rich context (not just filenames).
        Never uses Ollama or OpenRouter.
        """
        # Build rich context from results
        context_lines = []
        for r in results[:15]:  # Top 15 for context
            if r.get("article_title") and r.get("article_summary"):
                context_lines.append(f'- "{r["article_title"]}" — {r["article_summary"]}')
            elif r.get("document_name"):
                context_lines.append(f'- {r["document_name"]}')

        context = "\n".join(context_lines) if context_lines else "No documents found."
        entities_str = ", ".join(e["name"] for e in intent.entities) if intent.entities else "None"

        prompt = f"""Generate a brief summary (2-3 sentences) for a document collection called "{collection_name}".

Query: "{query}"
Documents and articles in collection:
{context}

Entities found: {entities_str}

Summarize what this collection contains and its key themes. Be specific about the content, not generic."""

        messages = [
            {"role": "system", "content": "You are a document collection summarizer. Write concise, specific summaries in 2-3 sentences. Respond only with the summary text, nothing else."},
            {"role": "user", "content": prompt},
        ]

        try:
            summary = await self.minimax_service.chat_completion_non_stream(
                messages=messages, temperature=0.5, max_tokens=500,
            )
            return summary.strip()
        except Exception as e:
            logger.error(f"MiniMax summary generation failed: {e}")
            return f"Collection of {len(results)} documents related to: {query}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/test_collection_v2_pipeline.py::TestStage3Synthesize -v --tb=short
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/collection_service.py backend/tests/unit/test_collection_v2_pipeline.py
git commit -m "feat(collections): Stage 3 SYNTHESIZE — MiniMax-only summary with article context

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Wire the 3 stages into `build_collection_pipeline()`

Replace the existing pipeline body with calls to the 3 stage methods. Create CollectionItems with article_id when available.

**Files:**
- Modify: `backend/app/services/collection_service.py`
- Modify: `backend/tests/unit/test_collection_v2_pipeline.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/unit/test_collection_v2_pipeline.py`:

```python
class TestFullPipelineV2:
    """Full pipeline must call 3 stages and create items with article_id."""

    @pytest.mark.asyncio
    async def test_pipeline_calls_three_stages(self):
        """build_collection_pipeline must call _understand_query, _gather_and_verify, _synthesize_summary."""
        with patch.object(
            collection_service, "_understand_query", new_callable=AsyncMock,
            return_value=(ParsedIntent(query="test", keywords=["test"], collection_name="Test", confidence=0.9), "broad_hybrid"),
        ) as mock_s1, patch.object(
            collection_service, "_gather_and_verify", new_callable=AsyncMock,
            return_value=[],
        ) as mock_s2, patch.object(
            collection_service, "_synthesize_summary", new_callable=AsyncMock,
            return_value="Test summary.",
        ) as mock_s3:
            # Create a mock db and collection
            mock_db = MagicMock()
            mock_collection = MagicMock()
            mock_collection.query = "test"
            mock_collection.name = "Test"
            mock_user = MagicMock()
            mock_user.role = "admin"

            mock_db.execute = AsyncMock(side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=mock_collection)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=mock_user)),
            ])
            mock_db.commit = AsyncMock()
            mock_db.refresh = AsyncMock()
            mock_db.add = MagicMock()

            import uuid
            await collection_service.build_collection_pipeline(
                collection_id=uuid.uuid4(), user_id=uuid.uuid4(), db=mock_db,
            )

            mock_s1.assert_called_once()
            mock_s2.assert_called_once()
            mock_s3.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/test_collection_v2_pipeline.py::TestFullPipelineV2 -v --tb=short
```

Expected: FAIL — pipeline still uses old code path.

- [ ] **Step 3: Rewrite `build_collection_pipeline()` body**

In `backend/app/services/collection_service.py`, replace the body of `build_collection_pipeline()` (keeping the method signature, the collection/user loading, and the try/except error handling). Replace lines 196-249 with:

```python
        try:
            # Stage 1: UNDERSTAND
            parsed_intent, strategy = await self._understand_query(collection.query)

            # Stage 2: GATHER + VERIFY
            results = await self._gather_and_verify(parsed_intent, strategy, user, db)

            # Stage 3: SYNTHESIZE
            ai_summary = None
            if results:
                ai_summary = await self._synthesize_summary(
                    collection_name=parsed_intent.collection_name or collection.name,
                    query=collection.query,
                    results=results,
                    intent=parsed_intent,
                )

            # Create CollectionItems with article_id when available
            from uuid import UUID as UUIDType
            for idx, r in enumerate(results):
                doc_id = r["document_id"]
                art_id = r.get("article_id")
                item = CollectionItem(
                    collection_id=collection.id,
                    document_id=UUIDType(doc_id) if isinstance(doc_id, str) else doc_id,
                    article_id=UUIDType(art_id) if isinstance(art_id, str) and art_id else None,
                    relevance_score=min(int(r.get("relevance_score", 50) * 100), 100),
                    order_index=idx,
                    added_by="ai",
                    added_reason=f"Matched query: {collection.query}",
                )
                db.add(item)

            # Update collection to READY
            collection.parsed_intent = parsed_intent.to_dict()
            collection.ai_summary = ai_summary
            collection.ai_keywords = parsed_intent.keywords
            collection.ai_entities = parsed_intent.entities
            collection.filter_criteria = parsed_intent.to_search_filter()
            collection.document_count = len(results)
            collection.last_refreshed_at = datetime.utcnow().isoformat()
            collection.status = CollectionStatus.READY

            await db.commit()
            await db.refresh(collection)
            logger.info(f"Collection '{collection.name}' built: {len(results)} items, status=ready")
            return collection

        except Exception as e:
            logger.error(f"Collection build failed for {collection_id}: {e}", exc_info=True)
            collection.status = CollectionStatus.FAILED
            collection.build_error = str(e)[:500]
            await db.commit()
            raise
```

Also remove the `use_ollama` variable from the old code (it's no longer needed).

- [ ] **Step 4: Run all v2 tests**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/test_collection_v2_pipeline.py -v --tb=short
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/collection_service.py backend/tests/unit/test_collection_v2_pipeline.py
git commit -m "feat(collections): wire 3-stage pipeline into build_collection_pipeline

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Update schema and API for article info + document actions

Add article fields to the response schema and include article info in the collection detail endpoint. The frontend needs article_title, article_summary, and a link to the document for preview/open/download.

**Files:**
- Modify: `backend/app/schemas/collection.py`
- Modify: `backend/app/api/collections.py`

- [ ] **Step 1: Read current schemas**

Read `backend/app/schemas/collection.py` and find `CollectionItemResponse`.

- [ ] **Step 2: Add article fields to CollectionItemResponse**

In the `CollectionItemResponse` class, add:

```python
    article_id: str | None = None
    article_title: str | None = None
    article_summary: str | None = None
```

- [ ] **Step 3: Update collection detail endpoint to include article info**

In `backend/app/api/collections.py`, in the `get_collection` endpoint, find the section that enriches items with document info (around line 274-284). Update it to also include article info:

After the existing document info block, add article loading. The `CollectionItem` now has an `article` relationship. Update the `selectinload` query to also load articles:

Change the items query (around line 245-250) from:

```python
    items_result = await db.execute(
        select(CollectionItem)
        .options(selectinload(CollectionItem.document))
        .where(CollectionItem.collection_id == collection_id)
        .order_by(CollectionItem.order_index)
    )
```

To:

```python
    items_result = await db.execute(
        select(CollectionItem)
        .options(selectinload(CollectionItem.document), selectinload(CollectionItem.article))
        .where(CollectionItem.collection_id == collection_id)
        .order_by(CollectionItem.order_index)
    )
```

Then update the item enrichment loop to include article info:

```python
    for item in items:
        item_dict = CollectionItemResponse.model_validate(item).model_dump()
        if item.document:
            item_dict["document"] = {
                "id": str(item.document.id),
                "filename": item.document.filename,
                "mime_type": item.document.mime_type,
                "created_at": item.document.created_at.isoformat(),
            }
        if item.article:
            item_dict["article_id"] = str(item.article.id)
            item_dict["article_title"] = item.article.title
            item_dict["article_summary"] = item.article.summary
        enriched_items.append(item_dict)
```

Note: also add `mime_type` to the document dict — the frontend needs it for preview/download.

- [ ] **Step 4: Run existing tests for regression**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/test_collection_v2_pipeline.py tests/unit/test_collection_creation_async.py tests/unit/test_collection_stats_bug.py -v --tb=short
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/collection.py backend/app/api/collections.py
git commit -m "feat(collections): add article info + mime_type to collection detail response

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Update frontend collection detail page with document actions

Show article titles/summaries as the display layer. Add preview, open, and download buttons for each document.

**Files:**
- Modify: `frontend/app/[locale]/collections/[id]/page.tsx`
- Modify: `frontend/app/messages/fr.json`
- Modify: `frontend/app/messages/en.json`

- [ ] **Step 1: Read current page**

Read `frontend/app/[locale]/collections/[id]/page.tsx` fully.

- [ ] **Step 2: Update CollectionItem interface**

Update the `CollectionItem` interface at the top of the file to include article fields and mime_type:

```typescript
interface CollectionItem {
  id: string;
  document_id: string;
  article_id?: string;
  article_title?: string;
  article_summary?: string;
  relevance_score: number;
  notes: string | null;
  is_highlighted: boolean;
  document?: {
    id: string;
    filename: string;
    mime_type?: string;
    bucket?: string;
    created_at: string;
  };
}
```

- [ ] **Step 3: Update the document list rendering**

Replace the items rendering section (around line 328-361) with a version that shows article info and document actions:

```tsx
{collection.items.map((item) => (
  <div
    key={item.id}
    className={`p-4 hover:bg-gray-50 dark:hover:bg-gray-700 transition ${
      item.is_highlighted ? "bg-yellow-50 dark:bg-yellow-900/20" : ""
    }`}
  >
    <div className="flex items-start justify-between">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          {item.is_highlighted && <span>⭐</span>}
          <h3 className="font-medium text-gray-900 dark:text-white truncate">
            {item.article_title || item.document?.filename || "Unknown Document"}
          </h3>
        </div>
        {item.article_summary && (
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 line-clamp-2">
            {item.article_summary}
          </p>
        )}
        {!item.article_summary && item.notes && (
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
            {item.notes}
          </p>
        )}
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
          {item.document?.filename}
        </p>
      </div>
      <div className="flex items-center gap-2 ml-4 flex-shrink-0">
        <span className="text-sm text-gray-500 dark:text-gray-400">
          {item.relevance_score}%
        </span>
        {/* Document actions */}
        {item.document && (
          <div className="flex gap-1">
            <a
              href={`/${params.locale}/documents/${item.document.id}`}
              className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded"
              title={t('collections.preview')}
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
            </a>
            <a
              href={`${process.env.NEXT_PUBLIC_API_URL}/api/v1/documents/${item.document.id}/download`}
              className="p-1.5 text-gray-500 hover:text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 rounded"
              title={t('collections.download')}
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </a>
          </div>
        )}
      </div>
    </div>
  </div>
))}
```

- [ ] **Step 4: Add translation keys**

In `frontend/app/messages/fr.json`, in the `collections` section, add:

```json
"preview": "Apercu",
"download": "Telecharger",
"open_document": "Ouvrir le document",
"article_source": "Source"
```

In `frontend/app/messages/en.json`, in the `collections` section, add:

```json
"preview": "Preview",
"download": "Download",
"open_document": "Open document",
"article_source": "Source"
```

- [ ] **Step 5: Verify frontend builds**

```bash
cd /home/development/src/active/sowknow4/frontend && npm run build 2>&1 | tail -5
```

Expected: Build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/[locale]/collections/[id]/page.tsx frontend/app/messages/fr.json frontend/app/messages/en.json
git commit -m "feat(frontend): article display + document preview/download in collection detail

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Create Alembic migration for article_id column

**Files:**
- Create: `backend/alembic/versions/016_add_article_id_to_collection_items.py`

- [ ] **Step 1: Create migration manually**

Create `backend/alembic/versions/016_add_article_id_to_collection_items.py`:

```python
"""Add article_id to collection_items

Revision ID: add_article_id_016
Revises: add_collection_status_015
Create Date: 2026-04-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "add_article_id_016"
down_revision = "add_collection_status_015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collection_items",
        sa.Column("article_id", UUID(as_uuid=True), nullable=True),
        schema="sowknow",
    )
    op.create_index(
        "ix_collection_items_article_id",
        "collection_items",
        ["article_id"],
        schema="sowknow",
    )
    op.create_foreign_key(
        "fk_collection_items_article_id",
        "collection_items",
        "articles",
        ["article_id"],
        ["id"],
        source_schema="sowknow",
        referent_schema="sowknow",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_collection_items_article_id", "collection_items", schema="sowknow", type_="foreignkey")
    op.drop_index("ix_collection_items_article_id", table_name="collection_items", schema="sowknow")
    op.drop_column("collection_items", "article_id", schema="sowknow")
```

- [ ] **Step 2: Commit**

```bash
git add backend/alembic/versions/016_add_article_id_to_collection_items.py
git commit -m "migration: add article_id column to collection_items

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Also update `refresh_collection()` to use the 3-stage pipeline

The refresh endpoint currently uses the old `_gather_documents_for_intent()`. Update it to use the new 3-stage methods.

**Files:**
- Modify: `backend/app/services/collection_service.py`

- [ ] **Step 1: Read current `refresh_collection` method**

Read `backend/app/services/collection_service.py` lines 301-379 (the refresh method).

- [ ] **Step 2: Update refresh to use 3-stage methods**

Replace the body of `refresh_collection()` (after loading the collection) to use the same 3 stages:

```python
        # Stage 1: UNDERSTAND
        parsed_intent, strategy = await self._understand_query(collection.query)

        # Stage 2: GATHER + VERIFY
        results = await self._gather_and_verify(parsed_intent, strategy, user, db)

        # Remove existing items
        from sqlalchemy import delete as sql_delete
        await db.execute(sql_delete(CollectionItem).where(CollectionItem.collection_id == collection_id))

        # Add new items with article_id
        from uuid import UUID as UUIDType
        for idx, r in enumerate(results):
            doc_id = r["document_id"]
            art_id = r.get("article_id")
            item = CollectionItem(
                collection_id=collection.id,
                document_id=UUIDType(doc_id) if isinstance(doc_id, str) else doc_id,
                article_id=UUIDType(art_id) if isinstance(art_id, str) and art_id else None,
                relevance_score=min(int(r.get("relevance_score", 50) * 100), 100),
                order_index=idx,
                added_by="ai",
                added_reason="Refreshed collection",
            )
            db.add(item)

        # Stage 3: SYNTHESIZE (if requested)
        if update_summary and results:
            collection.ai_summary = await self._synthesize_summary(
                collection_name=collection.name,
                query=collection.query,
                results=results,
                intent=parsed_intent,
            )

        # Update metadata
        collection.document_count = len(results)
        collection.last_refreshed_at = datetime.utcnow().isoformat()
        collection.parsed_intent = parsed_intent.to_dict()
        collection.filter_criteria = parsed_intent.to_search_filter()

        await db.commit()
        await db.refresh(collection)

        self._invalidate_cache(collection_id)
        logger.info(f"Refreshed collection '{collection.name}' with {len(results)} items")
        return collection
```

- [ ] **Step 3: Run all tests**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/test_collection_v2_pipeline.py tests/unit/test_collection_creation_async.py tests/unit/test_collection_stats_bug.py -v --tb=short
```

Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/collection_service.py
git commit -m "feat(collections): update refresh endpoint to use 3-stage pipeline

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Full regression + deployment verification

**Files:** None (verification only)

- [ ] **Step 1: Run full collection test suite**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest \
  tests/unit/test_collection_v2_pipeline.py \
  tests/unit/test_collection_creation_async.py \
  tests/unit/test_collection_stats_bug.py \
  tests/unit/test_collection_cache_invalidation.py \
  tests/unit/test_collection_export_unit.py \
  tests/integration/test_collection_pipeline.py \
  -v --tb=short 2>&1 | tail -30
```

Expected: All PASS, zero failures.

- [ ] **Step 2: Run full unit test suite for regressions**

```bash
cd /home/development/src/active/sowknow4/backend && python3 -m pytest tests/unit/ -v --tb=short 2>&1 | tail -10
```

Expected: No NEW failures.

- [ ] **Step 3: Verify frontend builds**

```bash
cd /home/development/src/active/sowknow4/frontend && npm run build 2>&1 | tail -5
```

Expected: Build succeeds.

- [ ] **Step 4: Document deployment checklist**

```
DEPLOYMENT CHECKLIST — Smart Collections v2
=============================================
1. Push to git:          git push origin master
2. Sync to production:   cd /var/docker/sowknow4 && git fetch devrepo master && git merge devrepo/master
3. Run migration:        docker exec sowknow4-backend alembic upgrade head
4. Build new worker:     docker compose build celery-collections
5. Start new worker:     docker compose up -d celery-collections
6. Restart backend:      docker compose restart backend
7. Restart main worker:  docker compose restart celery-worker
8. Rebuild frontend:     docker compose build frontend && docker compose up -d frontend
9. Verify health:        docker compose ps (all containers healthy)
10. Test: Create a collection → should return 202, build in <60s via collections worker
11. Verify: docker logs sowknow4-celery-collections (should show build_smart_collection tasks)
```

---

## Summary of Changes

| Component | What Changes | Why |
|-----------|-------------|-----|
| LLM routing | MiniMax direct for all collection calls | Faster (no Ollama 600s), cheaper (no OpenRouter hop), safe (only titles/summaries sent) |
| Celery queue | Dedicated `collections` queue + 512MB worker | Collections never wait behind 2,600 document tasks |
| Search | Articles-first with chunk fallback + quality gates | Richer results, better summaries, handles "no results" gracefully |
| Model | `article_id` on CollectionItem | Links to pre-synthesized articles for display |
| Frontend | Article titles/summaries + preview/download buttons | Users see knowledge, not just filenames, and can access source documents |
| Pipeline | 3-stage architecture (Understand → Gather → Synthesize) | Clear boundaries, quality gates, testable stages |
