# Pipeline Remediation: Document Processing Audit & Fix

**Date**: 2026-04-05
**Status**: Approved
**Scope**: Fix document processing pipeline failures, backfill missing embeddings/articles

---

## Problem Statement

An audit of 9,060 uploaded documents revealed catastrophic pipeline failures:

- **2,831 documents (31.2%) in ERROR** -- mostly from April 2-4 (2,238 docs, 100% failure rate)
- **198 documents stuck** in pending/processing from April 4
- **4,084 indexed documents missing embeddings** (415,283 chunks with no vectors)
- **501 indexed documents missing articles**
- **1,167 articles stuck in PENDING** without embeddings
- **Only 1,933 documents (21.3%) fully completed** the entire pipeline

### Root Cause

Commit `4cfead6` (April 1, 2026) introduced `recover_pending_documents()` in `backend/app/tasks/anomaly_tasks.py` with an **undefined variable `already_queued`** at line 754. The variable is referenced at lines 754 and 807 but never initialized (line 680 initializes `checked = []` which is never used).

This causes a `NameError` every 5 minutes when Celery Beat triggers the task, creating a cascade:
1. Recovery task crashes silently
2. Documents stuck in PROCESSING are never properly recovered
3. After 4 failed recovery attempts, marked ERROR with generic message
4. No actual error captured -- the real error (NameError) is in the recovery task, not the document

---

## Architecture

Two parallel tracks executed concurrently.

### Track A: Hotfix (immediate)

**A1. Fix `already_queued` NameError**
- File: `backend/app/tasks/anomaly_tasks.py`
- Line 680: Replace `checked = []` with `already_queued = []`
- This single fix unblocks the entire recovery pipeline

**A2. Reset April 2-4 error documents**
- Target: Documents where `created_at >= '2026-04-02'` AND `status = 'error'` AND metadata contains "permanently failed" or "pending_recovery_count"
- Reset `status` to `PENDING`
- Clear `recovery_count` and `pending_recovery_count` from metadata
- Execute via backfill task in controlled batches (200 docs per batch, 5s stagger)
- NOT raw SQL -- use Celery task to properly queue `process_document.delay()`

**A3. Stuck documents (198)**
- 169 pending + 29 processing docs from April 4
- Auto-recover once A1 hotfix deploys -- the fixed recovery task handles them naturally

### Track B: Deep Fixes (parallel)

**B1. Improve error capture in recovery tasks**
- File: `backend/app/tasks/anomaly_tasks.py`
- In `recover_stuck_documents()` (line 571+): Before marking ERROR, retrieve Celery task result/traceback via `AsyncResult(celery_task_id).traceback` and store in `metadata.actual_error`
- In `recover_pending_documents()` (line 703+): Same pattern
- In `fail_stuck_processing_documents()` (line 844+): Same pattern
- Add try/except around AsyncResult retrieval (may be expired in Redis)

**B2. Embedding backfill (4,084 docs, 415K chunks)**
- New file: `backend/app/tasks/backfill_tasks.py`
- Task: `backfill_missing_embeddings(batch_size=10, delay_seconds=30)`
- Query: `status = 'indexed' AND embedding_generated = false`
- For each doc: call `recompute_embeddings_for_document.delay(doc_id)` with countdown stagger
- Long-running: expect several hours for 415K chunks at CPU speed (32 chunks/batch)

**B3. Article generation backfill (501 docs)**
- Task: `backfill_missing_articles(batch_size=20, delay_seconds=60)`
- Query: `status = 'indexed' AND articles_generated = false AND chunk_count > 0`
- For each doc: call `generate_articles_for_document.delay(doc_id)` with countdown stagger
- Rate limit: respect OpenRouter/MiniMax API limits

**B4. Article embedding backfill (1,167 articles)**
- Task: `backfill_article_embeddings(batch_size=50, delay_seconds=10)`
- Query: `status = 'pending' AND embedding_vector IS NULL`
- Batch article IDs, call `generate_article_embeddings.delay(batch_ids)`

**B5. Consolidate duplicate recovery logic**
- Remove duplicate recovery from `backend/app/tasks/document_tasks.py`
- Standardize on single metadata key `recovery_count` (not both `recovery_count` and `pending_recovery_count`)
- Set MAX_RECOVERY_ATTEMPTS = 3 consistently everywhere
- All recovery logic lives in `anomaly_tasks.py` only

**B6. Backfill management module**
- New file: `backend/app/tasks/backfill_tasks.py`
- Contains all backfill tasks from B2/B3/B4 plus:
  - `reprocess_failed_documents(date_from, date_to, batch_size=200, delay_seconds=5)`
- All tasks registered as Celery tasks, callable from admin API or `celery call`

---

## Files Modified

| File | Change |
|------|--------|
| `backend/app/tasks/anomaly_tasks.py` | A1: fix variable init; B1: improve error capture; B5: standardize recovery keys |
| `backend/app/tasks/backfill_tasks.py` | **NEW** -- B2/B3/B4/B6: all backfill tasks |
| `backend/app/tasks/document_tasks.py` | B5: remove duplicate recovery logic |
| `backend/app/celery_app.py` | Register backfill tasks (if not auto-discovered) |

---

## Execution Order

```
Hour 0:   A1 (hotfix already_queued) -> deploy -> verify recovery task works
          A3 (198 stuck docs auto-recover)
          
Hour 0+:  B1 (improve error capture) -- deploy alongside
          B5 (consolidate recovery logic) -- deploy alongside

Hour 1:   B6 (create backfill_tasks.py)

Hour 1+:  A2 (reset 2,238 April error docs via reprocess_failed_documents task)
          B3 (article generation for 501 docs)
          B4 (article embeddings for 1,167 articles)

Hour 2+:  B2 (embedding backfill for 415K chunks -- long-running)
```

---

## Verification Criteria

After remediation, re-run the audit queries:

1. **Documents ERROR < 5%** (down from 31.2%) -- remaining errors are genuine failures
2. **Documents INDEXED > 95%** (up from 66.6%)
3. **Embeddings generated > 95%** (up from 21.4%)
4. **Articles generated > 95%** (up from 61.0%)
5. **Articles INDEXED (searchable) > 99%** of total articles
6. **Zero documents stuck in pending/processing** for > 30 minutes
7. `recover_pending_documents` completes without errors in Celery logs
8. All backfill tasks report completion with success/failure counts

---

## Risk Mitigation

- **Worker overload**: All backfill tasks use countdown staggering (5-60s between batches) to prevent queue flooding
- **OOM risk**: Embedding backfill processes 10 docs at a time; the 1.3GB model stays loaded between batches
- **API cost**: Article generation staggered at 60s intervals; OpenRouter caching reduces cost
- **Data safety**: No documents are deleted -- only status transitions from ERROR -> PENDING
- **Rollback**: If reprocessing causes issues, the backfill task can be revoked via `celery control revoke`
