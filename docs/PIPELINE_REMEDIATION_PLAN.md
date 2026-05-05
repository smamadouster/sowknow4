# Pipeline Remediation Plan

> Status: **IN PROGRESS** — Code fixes applied. Operational recovery required.
> Created: 2026-05-03

---

## 1. Situation Summary

| Stage | Pending | Running | Failed | Throughput | Health |
|-------|---------|---------|--------|------------|--------|
| Uploaded | 0 | 0 | 3 | 0/hr | 🔴 Needs Attention |
| OCR | 0 | 0 | 51 | 0/hr | 🔴 Needs Attention |
| Chunking | 0 | 0 | 136 | 0/hr | 🔴 Needs Attention |
| Embedding | 0 | 0 | 32 | 0/hr | 🔴 Needs Attention |
| Indexing | 8 | 0 | — | 0/hr | 🟢 OK (stalled) |
| Articles | 0 | 0 | 1 | 0/hr | 🔴 Needs Attention |
| Entities | 10 | 0 | 294 | 0/hr | 🔴 Needs Attention |
| Enriched | 6 | 0 | — | 0/hr | 🟢 OK (stalled) |

**Total failed:** 517 documents  
**Critical issue:** 0 throughput across **all** stages = Celery workers are likely down.

---

## 2. Root Cause Analysis

### 2.1 Primary — Pipeline is completely stalled
- **8 pending in Indexing, 10 in Entities, 6 in Enriched** with 0 running means Celery workers are not picking up tasks.
- Likely causes:
  - Celery service crashed or was not restarted after deploy
  - Worker OOM killed during entity extraction (spaCy model ~500MB/worker)
  - Redis unreachable (tasks cannot be dispatched or consumed)

### 2.2 Secondary — Excessive permanent failures (517 total)

| Stage | Failure Driver |
|-------|----------------|
| **Chunking (136)** | Documents with empty text, 0 chunks, or exceeding `CHUNK_COUNT_MAX` (5000). **Bug found:** oversized docs raised `RuntimeError` instead of `_PermanentPipelineError`, wasting 2 retries each before failing. |
| **Entities (294)** | Worker memory/time limits during spaCy NER + graph extraction. The stage internally swallows all exceptions (silent failure pattern), but Celery hard-kills (OOM/time-limit) leave the stage as FAILED. |
| **OCR (51)** | Unsupported formats, missing files, or OCR service downtime. |
| **Embedding (32)** | Embed server unreachable or unhealthy during batch encode. |
| **Articles (1)** | LLM transient failure. |

---

## 3. Remediation Phases

### Phase 1 — Stabilize (Immediate)
**Goal:** Restore worker connectivity and verify queue flow.

1. **Check Celery worker status**
   ```bash
   sudo systemctl status celery
   # OR Docker:
   docker ps | grep celery
   docker logs <celery_container> --tail 100
   ```

2. **Check Redis connectivity** (backend uses Redis for queues + sweeper lock)
   ```bash
   redis-cli ping
   redis-cli llen pipeline.embed
   redis-cli llen pipeline.entities
   ```

3. **Restart workers** if down or stuck
   ```bash
   sudo systemctl restart celery
   # Verify they come back:
   sudo systemctl status celery
   ```

4. **Verify queue consumption**
   - Watch the dashboard for `Running` counts to appear (> 0)
   - Or run: `redis-cli llen pipeline.embed` — should decrease over time

**Success criteria:** Throughput > 0/hr on at least one stage within 5 minutes of restart.

---

### Phase 2 — Apply Code Fixes (Already Applied)
**Goal:** Prevent new unnecessary failures and enable recovery.

| Fix | File | Description |
|-----|------|-------------|
| Chunk bugfix | `backend/app/tasks/pipeline_tasks.py` | Changed `RuntimeError` → `_PermanentPipelineError` when `len(chunks) > CHUNK_COUNT_MAX`. Eliminates wasteful retries for oversized documents. |
| Retry endpoint | `backend/app/api/pipeline_admin.py` | New `POST /api/v1/admin/pipeline/retry-failed?stage={stage}&limit={limit}`. Resets FAILED rows to PENDING and re-dispatches them. Skips docs in permanent ERROR state. |
| Dashboard UI | `frontend/app/[locale]/dashboard/page.tsx` | Added worker-status alert banner and per-stage **Retry** buttons. |
| API client | `frontend/lib/api.ts` | Added `getPipelineStatus()` and `retryFailedPipelineStages()` methods. |

**Deploy:** Restart the backend API and Celery workers after pulling these changes.

---

### Phase 3 — Recover Failed Backlog
**Goal:** Retry the 517 failed documents in the correct order.

**Important:** Retry upstream stages before downstream stages. If you retry Embedding before Chunking, the embed task will fail permanently because chunks are missing.

**Recommended order:**

1. **OCR first** (51 failed)
   - Dashboard → Pipeline Health → click **Retry 51** next to OCR
   - Or API: `POST /api/v1/admin/pipeline/retry-failed?stage=ocr&limit=100`

2. **Chunking second** (136 failed)
   - Click **Retry 136** next to Chunking
   - These will likely fail again for truly empty documents (expected). The bugfix ensures they fail fast now.

3. **Embedding third** (32 failed)
   - Click **Retry 32** next to Embedding
   - Ensure the embed server is healthy first:
     ```bash
     curl http://localhost:8001/health
     ```

4. **Entities fourth** (294 failed)
   - Click **Retry 294** next to Entities
   - **Caution:** This stage is memory-heavy. If workers have < 2GB RAM each, consider retrying in smaller batches (set `limit=50` via API) to avoid cascading OOMs.

5. **Articles last** (1 failed)
   - Click **Retry 1** next to Articles

**Monitoring during recovery:**
- Refresh dashboard every 30 seconds
- Watch `Failed` counts — they should decrease as `Running` appears
- If `Failed` stays flat, check Celery logs for repeated errors:
  ```bash
  sudo journalctl -u celery -f
  ```

---

### Phase 4 — Validate & Clear Stuck Items
**Goal:** Ensure all documents reach `ENRICHED` or are properly parked in `ERROR`.

1. **Run the pipeline sweeper manually** (if not running on beat schedule)
   ```bash
   cd backend && celery -A app.celery_app call pipeline.sweeper
   ```

2. **Verify sweeper metrics** in Celery logs:
   - `stuck_resumed` — tasks that were stuck and re-dispatched
   - `stuck_failed` — tasks that exhausted retries and were parked
   - `total_dispatched` — new tasks pushed to queues

3. **Check for documents stuck > 24h**
   - Dashboard → Anomalies section
   - If anomalies persist, inspect individual documents:
     ```sql
     SELECT id, filename, status, pipeline_error
     FROM sowknow.documents
     WHERE status = 'PROCESSING'
       AND updated_at < NOW() - INTERVAL '24 hours';
     ```

4. **Clean up permanent ERROR documents**
   - If a document truly cannot be processed (corrupt file, unsupported format), leave it in ERROR
   - For false positives (e.g., transient OCR API outage), use:
     ```bash
     curl -X POST "https://<host>/api/v1/admin/recover-failed-uploads?limit=200" \
       -H "Authorization: Bearer <token>"
     ```

---

### Phase 5 — Hardening & Prevention
**Goal:** Reduce future failure rates and improve observability.

#### 5.1 Memory management for entity stage
- **Problem:** spaCy `fr_core_news_lg` loads ~500MB per Celery worker process. 4–8 workers = 2–4GB RAM just for NLP.
- **Actions:**
  - Increase worker memory limits or reduce worker concurrency (`-c 2` instead of `-c 4`)
  - Consider using `fr_core_news_md` or `fr_core_news_sm` if precision trade-off is acceptable
  - Add `maxmemory-policy allkeys-lru` to Redis if queue backlog causes memory pressure

#### 5.2 Add timeouts to LLM calls in entity extraction
- **Problem:** `_extract_with_llm` calls OpenRouter with `httpx.AsyncClient(timeout=60.0)`, but the entity stage overall has no sub-operation timeout beyond the Celery task limit.
- **Action:** Add a per-document timeout wrapper so slow LLM calls fail fast rather than consuming the full 720s Celery hard limit.

#### 5.3 Alerting
- **Add alert** when `throughput_per_hour == 0` for > 15 minutes
- **Add alert** when `failed` count for any stage increases by > 10 in 1 hour
- **Add alert** when Celery worker count drops to 0

#### 5.4 Dashboard improvements (future)
- Show per-stage error breakdown (top 5 exception types from DLQ)
- Show queue depths from `/admin/pipeline/status` directly in the table
- Add "Retry All Failed" bulk action

---

## 4. Verification Checklist

- [ ] Celery workers show `status: ok` in `/api/v1/admin/pipeline/status`
- [ ] Throughput on dashboard shows > 0/hr within 5 minutes of restart
- [ ] `Failed` counts decrease after clicking Retry buttons
- [ ] No stage has > 50 pending with 0 running for > 30 minutes
- [ ] Anomalies section shows 0 stuck documents
- [ ] Redis queue depths (`pipeline.*`) decrease steadily

---

## 5. Rollback Plan

If retrying causes cascading failures (e.g., workers OOM-looping):

1. **Pause dispatch** by setting global backpressure artificially:
   ```bash
   redis-cli lpush pipeline.embed STOP  # fake queue depth bump
   ```
   (This triggers `MAX_TOTAL_QUEUE_DEPTH` backpressure)

2. **Purge queues** if needed:
   ```bash
   celery -A app.celery_app purge
   ```

3. **Reset failed stages manually** via SQL if the API is unavailable:
   ```sql
   UPDATE sowknow.pipeline_stages
   SET status = 'pending', attempt = 0, error_message = NULL
   WHERE status = 'failed' AND stage = 'entities';
   ```

---

## Appendix A — Quick API Commands

```bash
# Check pipeline status (queues + workers)
curl -s -H "Authorization: Bearer $TOKEN" \
  https://<host>/api/v1/admin/pipeline/status | jq

# Retry failed entities (batch of 100)
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  "https://<host>/api/v1/admin/pipeline/retry-failed?stage=entities&limit=100" | jq

# List DLQ (dead letter queue) failed tasks
curl -s -H "Authorization: Bearer $TOKEN" \
  https://<host>/api/v1/admin/failed-tasks | jq '.items[0:5]'

# Trigger sweeper manually
celery -A app.celery_app call pipeline.sweeper
```

## Appendix B — File Changes Summary

```
backend/app/tasks/pipeline_tasks.py   # RuntimeError → _PermanentPipelineError
backend/app/api/pipeline_admin.py     # + /retry-failed endpoint
frontend/lib/api.ts                   # + getPipelineStatus, retryFailedPipelineStages
frontend/app/[locale]/dashboard/page.tsx  # + worker alerts, retry buttons
```
