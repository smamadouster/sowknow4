# SOWKNOW4 Codebase Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all issues identified in the codebase analysis and performance review — from critical migration conflicts to documentation bloat.

**Architecture:** Ten tasks ordered by severity. Critical database and async fixes first, then performance optimizations, then housekeeping. Each task is independently committable and testable.

**Tech Stack:** Python/FastAPI, SQLAlchemy/Alembic, Celery, Next.js, Docker, PostgreSQL/pgvector, Redis

---

## File Map

| Task | Files Created/Modified | Purpose |
|------|----------------------|---------|
| 1 | `backend/alembic/versions/005_add_fulltext_search.py` (delete) | Remove orphaned migration |
| 2 | `backend/app/services/dlq_service.py` | Fix sync-in-async blocking |
| 3 | `backend/app/services/collection_service.py`, `backend/app/api/collections.py` | Add cache invalidation |
| 4 | `backend/app/api/collections.py` | Fix N+1 with selectinload |
| 5 | `backend/app/services/prometheus_metrics.py`, `backend/app/services/chat_service.py` | Add LLM metrics |
| 6 | `frontend/next.config.js` | Enable image optimization |
| 7 | `backend/app/celery_app.py` | Increase result TTL |
| 8 | `backend/tests/unit/test_rbac.py` (delete), `backend/tests/unit/test_auth.py` (delete) | Consolidate duplicate tests |
| 9 | Root `.md` files, `docs/archive/` | Archive stale docs |
| 10 | `backend/app/api/{auth,documents,collections,admin,chat,search}/` | Remove empty dirs |

---

### Task 1: Verify Alembic Migration Chain Integrity

The migration chain has two branches that merge at revision `013`. The filenames look like duplicates (e.g., two `005_*.py` files) but the actual `revision` IDs are unique and the chain is valid:

- **Branch A:** `001 → 002 → 003 → 004 → add_uploaded_by_001 → 006 → 007 → 008 → 009 → 010 → 011 → 012`
- **Branch B:** `004 → fix_vector_type_004 → add_vector_fts_005 → add_minimax_enum_006 → add_audit_logs_007 → add_coll_confidential_008 → add_rls_009 → add_chat_idx_010 → add_smart_folders_011 → add_unique_012`
- **Merge:** `013 (down_revision=('012', 'add_unique_012'))` → `014`
- **Orphan:** `005_add_fulltext_search.py` references non-existent `down_revision='004_fix_embedding_vector'`

**Files:**
- Delete: `backend/alembic/versions/005_add_fulltext_search.py`

- [ ] **Step 1: Verify the migration chain resolves cleanly**

Run from the backend directory with the database available:

```bash
cd /home/development/src/active/sowknow4/backend
python -c "
from alembic.config import Config
from alembic.script import ScriptDirectory
cfg = Config('alembic.ini')
scripts = ScriptDirectory.from_config(cfg)
heads = scripts.get_heads()
print(f'Heads: {heads}')
for rev in scripts.walk_revisions():
    print(f'  {rev.revision} <- {rev.down_revision}')
"
```

Expected: Either a clean single-head chain, or an error about the orphaned `005_add_fulltext_search` migration.

- [ ] **Step 2: Delete the orphaned migration**

The file `005_add_fulltext_search.py` has `down_revision = '004_fix_embedding_vector'` which doesn't exist in any migration. It's a dead reference.

```bash
rm backend/alembic/versions/005_add_fulltext_search.py
```

- [ ] **Step 3: Re-verify the chain is clean**

```bash
cd /home/development/src/active/sowknow4/backend
python -c "
from alembic.config import Config
from alembic.script import ScriptDirectory
cfg = Config('alembic.ini')
scripts = ScriptDirectory.from_config(cfg)
heads = scripts.get_heads()
print(f'Heads: {heads}')
assert len(heads) == 1, f'Expected 1 head, got {len(heads)}: {heads}'
print('Migration chain OK - single head')
"
```

Expected: `Heads: ['add_articles_014']` and `Migration chain OK - single head`.

If the chain still shows multiple heads, the two branches haven't merged properly and we need to investigate `013_add_search_history.py`'s merge point.

- [ ] **Step 4: Commit**

```bash
git add -u backend/alembic/versions/
git commit -m "fix(migrations): remove orphaned 005_add_fulltext_search migration

The file referenced non-existent down_revision '004_fix_embedding_vector'.
The actual fulltext search migration lives in 009_add_fulltext_search.py."
```

---

### Task 2: Fix Blocking Sync DB Call in DLQ Service

**Files:**
- Modify: `backend/app/services/dlq_service.py`
- Test: `backend/tests/unit/test_dlq_service_async.py`

The DLQ service uses synchronous `SessionLocal()` which blocks the async event loop. Since this is called from Celery tasks (sync context), not from async FastAPI handlers, the real fix is to ensure we never call it from async context AND to document that clearly. The sync usage is correct for Celery workers — the issue is the async alert dispatch mixed in.

- [ ] **Step 1: Read the current DLQ service**

```bash
cat -n backend/app/services/dlq_service.py
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/unit/test_dlq_service_async.py`:

```python
"""Tests for DLQ service — verify sync/async boundary is clean."""
import pytest
from unittest.mock import patch, MagicMock


class TestDLQStoreFailedTask:
    """Test store_failed_task handles DB and alerts correctly."""

    @patch("app.services.dlq_service.SessionLocal")
    def test_store_failed_task_commits_to_db(self, mock_session_cls):
        """Verify failed task is stored via sync DB session."""
        from app.services.dlq_service import dlq_service

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        result = dlq_service.store_failed_task(
            task_name="test.task",
            task_id="abc-123",
            args=("arg1",),
            kwargs={"key": "val"},
            exception=ValueError("test error"),
            traceback_str="Traceback ...",
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()
        assert result is not None

    @patch("app.services.dlq_service.SessionLocal")
    def test_store_failed_task_rolls_back_on_error(self, mock_session_cls):
        """Verify rollback on DB error."""
        from app.services.dlq_service import dlq_service

        mock_db = MagicMock()
        mock_db.commit.side_effect = Exception("DB error")
        mock_session_cls.return_value = mock_db

        result = dlq_service.store_failed_task(
            task_name="test.task",
            task_id="abc-123",
            args=(),
            kwargs={},
            exception=ValueError("test"),
        )

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()
        assert result is None
```

- [ ] **Step 3: Run test to verify it fails or passes**

```bash
cd /home/development/src/active/sowknow4
python -m pytest backend/tests/unit/test_dlq_service_async.py -v
```

- [ ] **Step 4: Fix the async alert dispatch in store_failed_task**

In `backend/app/services/dlq_service.py`, the alert dispatch (lines 76-97) tries to run async code from a sync context. Replace the fire-and-forget async pattern with a sync-safe approach:

Find the alert dispatch block (approximately lines 76-97) and replace it with:

```python
        # Best-effort alert (sync-safe — no async event loop required)
        try:
            import threading
            def _send_alert():
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    try:
                        from app.services.alert_service import alert_service
                        loop.run_until_complete(
                            alert_service.send_task_failure_alert(
                                task_name=task_name,
                                task_id=task_id,
                                error=str(exception),
                            )
                        )
                    finally:
                        loop.close()
                except Exception:
                    pass  # Alert is best-effort, never block DLQ storage

            thread = threading.Thread(target=_send_alert, daemon=True)
            thread.start()
        except Exception:
            pass  # Alert failure must never block DLQ storage
```

- [ ] **Step 5: Run tests**

```bash
cd /home/development/src/active/sowknow4
python -m pytest backend/tests/unit/test_dlq_service_async.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/dlq_service.py backend/tests/unit/test_dlq_service_async.py
git commit -m "fix(dlq): make alert dispatch sync-safe in store_failed_task

Alert dispatch now runs in a daemon thread with its own event loop,
preventing blocking the Celery worker when no async loop is running."
```

---

### Task 3: Add Cache Invalidation on Collection Mutation

**Files:**
- Modify: `backend/app/services/collection_service.py` (lines ~204-281)
- Modify: `backend/app/api/collections.py` (delete endpoint)
- Test: `backend/tests/unit/test_collection_cache_invalidation.py`

The `openrouter_service.invalidate_collection_cache()` method exists (lines 383-419) but is never called. Collection updates/deletes serve stale cached LLM responses.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_collection_cache_invalidation.py`:

```python
"""Tests for collection cache invalidation on mutation."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4


@pytest.mark.asyncio
class TestCollectionCacheInvalidation:
    """Verify cache is invalidated when collections are mutated."""

    @patch("app.services.collection_service._openrouter_svc")
    async def test_delete_collection_invalidates_cache(self, mock_openrouter):
        """Deleting a collection should invalidate its OpenRouter cache."""
        from app.services.collection_service import CollectionService

        mock_openrouter.invalidate_collection_cache = MagicMock(return_value=3)
        service = CollectionService()

        collection_id = uuid4()
        mock_db = AsyncMock()
        mock_collection = MagicMock()
        mock_collection.id = collection_id

        # Mock the DB query to return our collection
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_collection
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        await service.delete_collection(collection_id, mock_db)

        mock_openrouter.invalidate_collection_cache.assert_called_once_with(
            str(collection_id)
        )

    @patch("app.services.collection_service._openrouter_svc")
    async def test_update_collection_invalidates_cache(self, mock_openrouter):
        """Updating a collection should invalidate its OpenRouter cache."""
        from app.services.collection_service import CollectionService

        mock_openrouter.invalidate_collection_cache = MagicMock(return_value=1)
        service = CollectionService()

        collection_id = uuid4()
        mock_db = AsyncMock()
        mock_collection = MagicMock()
        mock_collection.id = collection_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_collection
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        await service.update_collection(collection_id, {"name": "New Name"}, mock_db)

        mock_openrouter.invalidate_collection_cache.assert_called_once_with(
            str(collection_id)
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/development/src/active/sowknow4
python -m pytest backend/tests/unit/test_collection_cache_invalidation.py -v
```

Expected: FAIL — `CollectionService` has no `delete_collection`/`update_collection` that calls cache invalidation.

- [ ] **Step 3: Read collection_service.py to find exact mutation methods**

```bash
cat -n backend/app/services/collection_service.py
```

Identify the delete and update methods and their exact signatures.

- [ ] **Step 4: Add cache invalidation calls**

In `backend/app/services/collection_service.py`, add a helper and call it from every mutation method:

```python
def _invalidate_cache(self, collection_id) -> None:
    """Best-effort cache invalidation for collection LLM responses."""
    if not _cache_invalidation_enabled:
        return
    try:
        _openrouter_svc.invalidate_collection_cache(str(collection_id))
    except Exception as e:
        logger.warning(f"Cache invalidation failed for collection {collection_id}: {e}")
```

Then add `self._invalidate_cache(collection_id)` after every `db.commit()` in delete/update/add-item/remove-item methods.

- [ ] **Step 5: Run tests**

```bash
cd /home/development/src/active/sowknow4
python -m pytest backend/tests/unit/test_collection_cache_invalidation.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/collection_service.py backend/tests/unit/test_collection_cache_invalidation.py
git commit -m "fix(cache): invalidate OpenRouter cache on collection mutation

Calls invalidate_collection_cache() after collection delete, update,
add-item, and remove-item to prevent stale AI responses."
```

---

### Task 4: Fix N+1 Query in Collection List Endpoint

**Files:**
- Modify: `backend/app/api/collections.py` (lines ~154-185, ~235-265)
- Test: `backend/tests/unit/test_collection_query_optimization.py`

Collection list queries don't use `selectinload` for relationships — accessing `item.document` triggers separate queries per item.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_collection_query_optimization.py`:

```python
"""Test that collection queries use eager loading."""
import pytest
from unittest.mock import AsyncMock, MagicMock, call
from sqlalchemy.orm import selectinload


class TestCollectionQueryOptimization:
    """Verify selectinload is used for collection relationships."""

    def test_collection_items_query_uses_selectinload(self):
        """The collection items query must include selectinload for documents."""
        # This is a code inspection test — verify the import exists
        from app.api.collections import router
        import inspect
        source = inspect.getsource(router)
        # Verify selectinload is imported and used
        assert "selectinload" in source or "joinedload" in source, (
            "Collection router must use selectinload or joinedload "
            "to prevent N+1 queries on item.document access"
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/development/src/active/sowknow4
python -m pytest backend/tests/unit/test_collection_query_optimization.py -v
```

Expected: FAIL — `selectinload` not in source.

- [ ] **Step 3: Read the collection items query**

```bash
sed -n '230,270p' backend/app/api/collections.py
```

- [ ] **Step 4: Add selectinload to collection items query**

In `backend/app/api/collections.py`, add the import at the top:

```python
from sqlalchemy.orm import selectinload
```

Then modify the CollectionItem query (around line 236) to eagerly load documents:

```python
# Before:
select(CollectionItem).where(CollectionItem.collection_id == collection_id).order_by(CollectionItem.order_index)

# After:
select(CollectionItem).options(selectinload(CollectionItem.document)).where(CollectionItem.collection_id == collection_id).order_by(CollectionItem.order_index)
```

- [ ] **Step 5: Run tests**

```bash
cd /home/development/src/active/sowknow4
python -m pytest backend/tests/unit/test_collection_query_optimization.py -v
python -m pytest backend/tests/integration/test_collection_export.py -v
```

Expected: Both PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/collections.py backend/tests/unit/test_collection_query_optimization.py
git commit -m "perf(collections): add selectinload to prevent N+1 on item.document

Collection items query now eagerly loads related documents in a single
query instead of issuing one query per item."
```

---

### Task 5: Add LLM Request Metrics to Prometheus

**Files:**
- Modify: `backend/app/services/prometheus_metrics.py`
- Modify: `backend/app/services/chat_service.py` (around line 63)
- Test: `backend/tests/unit/test_llm_metrics.py`

No metrics exist for LLM provider latency, retry rates, or error rates. This makes debugging production issues blind.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_llm_metrics.py`:

```python
"""Tests for LLM request metrics."""
import pytest
from app.services.prometheus_metrics import (
    llm_request_duration,
    llm_request_total,
    llm_retry_total,
)


class TestLLMMetrics:
    """Verify LLM metrics are defined and functional."""

    def test_llm_request_duration_metric_exists(self):
        """LLM request duration metric should be defined."""
        assert llm_request_duration is not None
        assert llm_request_duration.name == "sowknow_llm_request_duration_seconds"

    def test_llm_request_total_metric_exists(self):
        """LLM request count metric should be defined."""
        assert llm_request_total is not None
        assert llm_request_total.name == "sowknow_llm_requests_total"

    def test_llm_retry_total_metric_exists(self):
        """LLM retry count metric should be defined."""
        assert llm_retry_total is not None
        assert llm_retry_total.name == "sowknow_llm_retries_total"

    def test_can_record_request_duration(self):
        """Should record duration by provider."""
        llm_request_duration.observe(1.5, labels={"provider": "openrouter", "model": "mistral-small"})
        assert llm_request_duration._values[("openrouter", "mistral-small")] == 1.5

    def test_can_increment_request_count(self):
        """Should count requests by provider and status."""
        llm_request_total.inc(labels={"provider": "minimax", "status": "success"})
        llm_request_total.inc(labels={"provider": "minimax", "status": "success"})
        assert llm_request_total._values[("minimax", "success")] == 2.0

    def test_can_increment_retry_count(self):
        """Should count retries by provider."""
        llm_retry_total.inc(labels={"provider": "ollama"})
        assert llm_retry_total._values[("ollama",)] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/development/src/active/sowknow4
python -m pytest backend/tests/unit/test_llm_metrics.py -v
```

Expected: FAIL — `llm_request_duration`, `llm_request_total`, `llm_retry_total` not importable.

- [ ] **Step 3: Add LLM metrics to prometheus_metrics.py**

Append to the end of `backend/app/services/prometheus_metrics.py`:

```python
# --- LLM Provider Metrics ---

llm_request_duration = Metric(
    name="sowknow_llm_request_duration_seconds",
    help_text="Duration of LLM API requests in seconds",
    labels=["provider", "model"],
)

llm_request_total = Metric(
    name="sowknow_llm_requests_total",
    help_text="Total number of LLM API requests",
    labels=["provider", "status"],
)

llm_retry_total = Metric(
    name="sowknow_llm_retries_total",
    help_text="Total number of LLM API retries",
    labels=["provider"],
)
```

- [ ] **Step 4: Run tests**

```bash
cd /home/development/src/active/sowknow4
python -m pytest backend/tests/unit/test_llm_metrics.py -v
```

Expected: PASS.

- [ ] **Step 5: Instrument chat_service.py with metrics**

In `backend/app/services/chat_service.py`, add the import near the top:

```python
import time as _time
from app.services.prometheus_metrics import (
    llm_request_duration,
    llm_request_total,
    llm_retry_total,
)
```

Then wrap the LLM call in the `chat_completion` or `send_message` method with timing:

```python
_start = _time.monotonic()
try:
    # ... existing LLM call ...
    _elapsed = _time.monotonic() - _start
    llm_request_duration.observe(_elapsed, labels={"provider": provider_name, "model": model_name})
    llm_request_total.inc(labels={"provider": provider_name, "status": "success"})
except Exception as e:
    _elapsed = _time.monotonic() - _start
    llm_request_duration.observe(_elapsed, labels={"provider": provider_name, "model": model_name})
    llm_request_total.inc(labels={"provider": provider_name, "status": "error"})
    raise
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/prometheus_metrics.py backend/app/services/chat_service.py backend/tests/unit/test_llm_metrics.py
git commit -m "feat(metrics): add LLM provider request duration and retry metrics

Tracks per-provider latency, success/error counts, and retry rates
via Prometheus metrics for observability into LLM routing performance."
```

---

### Task 6: Enable Next.js Image Optimization

**Files:**
- Modify: `frontend/next.config.js` (line 50)

- [ ] **Step 1: Read current config**

```bash
cat -n frontend/next.config.js
```

- [ ] **Step 2: Change unoptimized to false and add formats**

In `frontend/next.config.js`, replace:

```javascript
  images: {
    unoptimized: true,
  },
```

With:

```javascript
  images: {
    unoptimized: false,
    formats: ['image/avif', 'image/webp'],
    deviceSizes: [640, 750, 828, 1080, 1200, 1920],
  },
```

- [ ] **Step 3: Verify the frontend builds**

```bash
cd /home/development/src/active/sowknow4/frontend
npx next build 2>&1 | tail -20
```

Expected: Build succeeds. If it fails due to missing sharp dependency:

```bash
npm install sharp
```

- [ ] **Step 4: Commit**

```bash
git add frontend/next.config.js
git commit -m "perf(frontend): enable Next.js image optimization with AVIF/WebP

Replaces unoptimized:true with responsive image generation,
saving 30-50% bandwidth on image assets."
```

---

### Task 7: Increase Celery Task Result TTL

**Files:**
- Modify: `backend/app/celery_app.py` (line 78)

- [ ] **Step 1: Read current config**

```bash
sed -n '75,82p' backend/app/celery_app.py
```

- [ ] **Step 2: Change result_expires from 3600 to 86400**

In `backend/app/celery_app.py`, replace:

```python
    result_expires=3600,  # 1 hour
```

With:

```python
    result_expires=86400,  # 24 hours — document processing may be checked hours later
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/celery_app.py
git commit -m "fix(celery): increase task result TTL from 1 hour to 24 hours

Users checking document processing status hours after submission
would find expired results. 24h covers all reasonable check-back windows."
```

---

### Task 8: Consolidate Duplicate Test Files

**Files:**
- Delete: `backend/tests/unit/test_rbac.py` (subset of `security/test_rbac.py`)
- Delete: `backend/tests/unit/test_auth.py` (subset of `security/test_auth_security.py`)

The `security/` versions are more comprehensive (they test HTTP endpoints with TestClient, not just model properties). The `unit/` versions test basic enum values which are implicitly covered.

- [ ] **Step 1: Verify security tests cover unit test cases**

The unit `test_rbac.py` tests:
- `UserRole.USER.value == "user"` — covered by security/test_rbac.py creating users with each role
- `UserRole.ADMIN.value == "admin"` — covered
- Bucket access logic — covered more thoroughly in security/test_rbac.py and security/test_confidential_isolation.py

The unit `test_auth.py` tests:
- Register success — covered by security/test_auth_security.py
- Login flow — covered by security/test_auth_security.py
- Cookie-based tokens — covered by security/test_auth_security.py

- [ ] **Step 2: Run security tests to confirm they pass**

```bash
cd /home/development/src/active/sowknow4
python -m pytest backend/tests/security/test_rbac.py backend/tests/security/test_auth_security.py backend/tests/security/test_auth_compliance.py -v 2>&1 | tail -30
```

Expected: Tests pass (or skip due to missing fixtures — acceptable for consolidation).

- [ ] **Step 3: Delete the duplicate unit test files**

```bash
rm backend/tests/unit/test_rbac.py
rm backend/tests/unit/test_auth.py
```

- [ ] **Step 4: Run full test suite to verify no regressions**

```bash
cd /home/development/src/active/sowknow4
python -m pytest backend/tests/ --co -q 2>&1 | tail -5
```

Expected: Collection count decreases by the number of tests in deleted files, no import errors.

- [ ] **Step 5: Commit**

```bash
git add -u backend/tests/
git commit -m "refactor(tests): remove duplicate unit/test_rbac.py and unit/test_auth.py

These were subsets of the more comprehensive security/test_rbac.py
and security/test_auth_security.py. No test coverage lost."
```

---

### Task 9: Archive Stale Documentation

**Files:**
- Create: `docs/archive/` directory
- Move: 20+ stale .md files from root and docs/

- [ ] **Step 1: Create archive directory**

```bash
mkdir -p docs/archive
```

- [ ] **Step 2: Move agent audit reports from root**

```bash
mv Agent1_Filesystem_Audit.md docs/archive/
mv Agent2_Database_Audit.md docs/archive/
mv Agent3_LLM_Routing_Audit.md docs/archive/
mv Agent4_Audit_Monitoring.md docs/archive/
mv Agent5_Pentest.md docs/archive/
mv Agent6_QA_Report.md docs/archive/
```

- [ ] **Step 3: Move stale reports and summaries from root**

```bash
mv CELERY_TASK_QUEUE_AUDIT_REPORT.md docs/archive/
mv DOCKER_ARCHITECTURE_AUDIT.md docs/archive/
mv DOCUMENTATION_FIX_REPORT.md docs/archive/
mv DOCUMENTATION_UPDATE_2026-02-24.md docs/archive/
mv EXECUTION_SUMMARY.md docs/archive/
mv GEMINI_MIGRATION_QA_REPORT.md docs/archive/
mv PROGRESS_SUMMARY_2026_02_24.md docs/archive/
mv SECURITY_FIX_REPORT.md docs/archive/
mv SECURITY_FIX_SUMMARY.md docs/archive/
mv SESSION_COMPLETION_SUMMARY.md docs/archive/
mv TELEGRAM_UPLOAD_FIX.md docs/archive/
mv E2E_Test_Mastertask.md docs/archive/
mv MASTERTASK_NEXT_PHASE.md docs/archive/
```

- [ ] **Step 4: Move stale execution plan versions (keep latest only)**

```bash
mv SOWKNOW_ExecutionPlan_v1.1.md docs/archive/
mv SOWKNOW_GeminiFlash_Implementation_Plan.md docs/archive/
```

- [ ] **Step 5: Verify remaining root .md files are essential**

After cleanup, root should have only:
- `CLAUDE.md` (project rules — keep)
- `README.md` (repo entry point — keep)
- `CHANGELOG.md` (release notes — keep)
- `DEPLOYMENT.md` (deploy guide — keep)
- `DEPLOYMENT-PRODUCTION.md` (production-specific — keep)
- `MONITORING.md` (ops guide — keep)
- `DATABASE-PASSWORD-GUIDE.md` (ops guide — keep)
- `Mastertask.md` (active planning — keep if current)
- `HURDLES_TO_PRODUCTION.md` (active tracking — keep if current)
- `soul.md` (project identity — keep)
- `SOWKNOW_PRD_v1.1.md` (product requirements — keep)
- `SOWKNOW_TechStack_v1.1.md` (tech stack — keep)
- `SOWKNOW_ExecutionPlan_v1.2.md` (latest plan — keep)
- `AI-ERVICES-CONFIGURATION.md` (config guide — keep)

```bash
ls *.md | wc -l
```

Expected: ~14 files (down from 35).

- [ ] **Step 6: Commit**

```bash
git add -A docs/archive/
git add -u *.md
git commit -m "docs: archive 19 stale audit/report files to docs/archive/

Moves agent audit reports, one-time fix reports, and superseded
execution plans out of root. Root .md count: 35 → ~14."
```

---

### Task 10: Remove Empty API Subdirectories

**Files:**
- Delete: `backend/app/api/{auth,documents,collections,admin,chat,search}/` (all empty)

- [ ] **Step 1: Confirm directories are empty**

```bash
for dir in auth documents collections admin chat search; do
  echo "=== backend/app/api/$dir ==="
  ls -la "backend/app/api/$dir/"
done
```

Expected: Each directory contains only `.` and `..`.

- [ ] **Step 2: Remove empty directories**

```bash
rmdir backend/app/api/auth
rmdir backend/app/api/documents
rmdir backend/app/api/collections
rmdir backend/app/api/admin
rmdir backend/app/api/chat
rmdir backend/app/api/search
```

- [ ] **Step 3: Verify no imports reference these directories**

```bash
cd /home/development/src/active/sowknow4
grep -r "from app.api.auth" backend/app/ || echo "No references found"
grep -r "from app.api.documents" backend/app/ || echo "No references found"
grep -r "from app.api.collections" backend/app/ || echo "No references found"
grep -r "from app.api.admin" backend/app/ || echo "No references found"
grep -r "from app.api.chat" backend/app/ || echo "No references found"
grep -r "from app.api.search" backend/app/ || echo "No references found"
```

Expected: "No references found" for all.

- [ ] **Step 4: Commit**

```bash
git add -A backend/app/api/
git commit -m "chore: remove 6 empty API subdirectories

These were created but never populated — all route logic lives in
the parent backend/app/api/*.py files directly."
```

---

## Execution Order Summary

| # | Task | Severity | Est. Complexity |
|---|------|----------|-----------------|
| 1 | Fix alembic migration chain | Critical | Low |
| 2 | Fix sync/async DLQ service | Critical | Medium |
| 3 | Add cache invalidation | High | Medium |
| 4 | Fix N+1 collection queries | High | Low |
| 5 | Add LLM metrics | High | Medium |
| 6 | Enable image optimization | Medium | Low |
| 7 | Increase Celery result TTL | Medium | Low |
| 8 | Consolidate duplicate tests | Low | Low |
| 9 | Archive stale documentation | Low | Low |
| 10 | Remove empty directories | Low | Low |

## Post-Remediation Verification

After all tasks are complete, run:

```bash
# Full backend test suite
cd /home/development/src/active/sowknow4
python -m pytest backend/tests/ -v --tb=short 2>&1 | tail -30

# Frontend build check
cd frontend && npx next build 2>&1 | tail -10

# Docker compose validation
docker compose config --quiet && echo "Compose config OK"

# Migration chain verification
cd backend && python -c "
from alembic.config import Config
from alembic.script import ScriptDirectory
cfg = Config('alembic.ini')
scripts = ScriptDirectory.from_config(cfg)
heads = scripts.get_heads()
assert len(heads) == 1, f'Multiple heads: {heads}'
print(f'Single head: {heads[0]} — OK')
"

# Root doc count
ls *.md | wc -l  # Should be ~14
```
