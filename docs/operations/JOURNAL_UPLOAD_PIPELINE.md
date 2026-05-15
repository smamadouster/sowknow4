# Journal of Upload Pipeline Failures

> **Purpose:** Daily operational journal to track upload pipeline health, correlate failures over time, and identify root causes.
> 
> **Rule:** Append a new section every day. Include the Morning Check snapshot even if everything is green — absence of data is also data.

---

## Template (copy for each new day)

```markdown
### YYYY-MM-DD — [Operator / System]

#### Morning Check Snapshot
```text
# Paste morning check output here
```

#### Pipeline State
| Stage | Pending | Running | Failed | Completed (24h) |
|-------|---------|---------|--------|-----------------|
| uploaded | 0 | 0 | 0 | 0 |
| ocr | 0 | 0 | 0 | 0 |
| chunked | 0 | 0 | 0 | 0 |
| embedded | 0 | 0 | 0 | 0 |
| indexed | 0 | 0 | 0 | 0 |

#### Issues Observed
- 

#### Root-Cause Hypotheses
- 

#### Actions Taken
- 

#### Follow-Up / Tomorrow
- 
```

---

## 2026-05-12 — Kimi Code CLI (initial audit)

### Morning Check Snapshot
```text
=== Morning Check ===
 docs_with_chunks
------------------
             6491

  stage   | status  | count
----------+---------+-------
 uploaded | pending |     2
 ocr      | pending |     1
 ocr      | failed  |     3
 chunked  | pending |     2
 chunked  | failed  |    25
 embedded | pending |     7
 embedded | running |    29

sowknow4-backend Up 23 hours (healthy)
sowknow4-celery-articles Up 23 hours (healthy)
sowknow4-celery-beat Up 23 hours (healthy)
sowknow4-celery-collections Up 23 hours (healthy)
sowknow4-celery-entities Up 23 hours (healthy)
sowknow4-celery-heavy Up 23 hours (healthy)
sowknow4-celery-light Up 23 hours (healthy)
sowknow4-embed-server Up 23 hours (healthy)
sowknow4-embed-server-2 Up 2 days (healthy)
sowknow4-frontend Up 23 hours (healthy)
sowknow4-nats Up 23 hours (healthy)
sowknow4-postgres Up 49 minutes (healthy)
sowknow4-redis Up 23 hours (healthy)
sowknow4-rerank-server Up 23 hours (healthy)
sowknow4-telegram-bot Up 23 hours (healthy)
```

### Pipeline State
| Stage | Pending | Running | Failed | Completed (1h) |
|-------|---------|---------|--------|----------------|
| uploaded | 2 | 0 | 0 | — |
| ocr | 1 | 0 | 3 | — |
| chunked | 2 | 0 | 25 | — |
| embedded | 7 | 29 | 0 | 34 |
| indexed | 0 | 0 | 0 | 34 |

### Infrastructure Events
- **Postgres restart at ~17:05 UTC** (container up only 49 min at check time).
  - Intentional shutdown (`terminating connection due to administrator command`).
  - Killed an in-flight `CREATE INDEX CONCURRENTLY` on `document_chunks.embedding_vector`.
  - Index **does exist** after restart (`ix_document_chunks_embedding_hnsw` confirmed), so no action needed.
- **No OOM kills** on host in recent history.

### Issues Observed

#### 1. 🔴 Embedding bottleneck — 29 zombie tasks
- **11 tasks** "running" for **>3 hours** (oldest: ~4.6 h).
- **11 tasks** "running" for **1–3 hours**.
- Only **7 tasks** actually touched in the last hour.
- **Embed servers saturated:**
  - `embed-server`:   88.9 % CPU, 7.29 GiB / 10 GiB RAM
  - `embed-server-2`: 98.2 % CPU, 4.26 GiB / 10 GiB RAM
- **Celery queues are empty** (`celery`, `celery:heavy`, `celery:light`, `celery:articles` all `LLEN = 0`).
- **Celery workers timing out:** `SoftTimeLimitExceeded` on embed requests.
- **Conclusion:** The 29 "running" tasks are **zombies** — Celery is not actually processing them, but they hold DB locks / slots and starve new work.

#### 2. 🟡 Chunked stage — 25 failed
| Error | Count | First seen | Notes |
|-------|-------|------------|-------|
| No text content extracted | 13 | 2026-05-10 | Document uploaded but completely empty / unparseable |
| Too many chunks (>5k / >10k) | 8 | 2026-05-10 | Hard limit `CHUNK_COUNT_MAX` rejecting large spreadsheets |
| Sweeper: stuck in RUNNING | 4 | 2026-05-10 | Sweeper already retried twice and gave up |

#### 3. 🟡 OCR stage — 3 failed
| Document | File | Size | Error | Root-cause hypothesis |
|----------|------|------|-------|----------------------|
| `bf040165-...` | `Balance 2012 excel.xls` | 18 KB | `'ElementTree' object has no attribute 'getiterator'` | **xlrd 1.2.0 xlsx parser broken on Python 3.11** (`getiterator` removed in Py 3.9). File may be HTML/XML disguised as `.xls`, causing xlrd to enter its XML path. |
| `1bb96982-...` | `Liasse Fiscale GUINEE 2012.xlsx` | 595 KB | `File is not a zip file` | Corrupt / misnamed file. Not a valid OOXML package. |
| `7eb595cc-...` | `CONVENTION POUR LA GESTION DE LA PAIE.doc` | **0 bytes** | `Could not extract text from DOC file. Ensure antiword is installed.` | **File is empty (0 B).** Error message is misleading — antiword *is* installed in all workers. |

#### 4. 🟡 Vault DNS failures
- Backend health check repeatedly failing: `Temporary failure in name resolution` for Vault.
- Non-blocking for pipeline but indicates infrastructure drift.

### Root-Cause Hypotheses
1. **Embed server concurrency mismatch:** Celery dispatches more embed tasks than the 2 embed servers can handle, causing cascading timeouts and zombie tasks.
2. **xlrd 1.2.0 + Python 3.11 incompatibility:** The recent `xlrd==1.2.0` pin works for legacy BIFF `.xls`, but its internal xlsx parser uses `ElementTree.getiterator()` which was removed in Python 3.9+. Any `.xls` file that triggers the XML path explodes.
3. **Missing guard for 0-byte files:** Empty files should be rejected at upload or OCR with a clear "empty file" error, not a misleading "antiword not installed" message.
4. **Postgres restart wiped in-flight tasks:** The 4 "Sweeper: stuck in RUNNING" failures from May 10 pre-date the restart, but the 7 pending embed tasks from early May 9–10 may be artifacts of earlier crashes.

### Actions Taken
- [x] **Reset 22 zombie embedded tasks** (running >1 h) to `PENDING` via `backend/scripts/_ops_reset_embed_zombies.py`.
  - Verified: 22 tasks reset, 7 genuinely active tasks left in `RUNNING`.
- [x] **Patched `_spreadsheet_extractor.py`** to catch `AttributeError` from `getiterator` and surface a clean error (`"xlrd parser incompatible with this file on Python 3.11+"`).
- [x] **Patched `text_extractor.py`**:
  - Added early `os.path.getsize() == 0` guard returning `"Empty file (0 bytes)"`.
  - Updated `_extract_from_xls` fallback logic: when xlrd fails with `getiterator`, return the openpyxl fallback error instead of the cryptic xlrd traceback.
- [x] **Created this journal file** at `docs/operations/JOURNAL_UPLOAD_PIPELINE.md`.

### Follow-Up / Tomorrow
- Monitor whether the 29 pending embed tasks are picked up as the 7 active tasks finish.
- If embed servers stay >90 % CPU after the backlog drains, consider adding `embed-server-3` or reducing Celery embed concurrency.
- Re-run Morning Check and append results below.

---

### 2026-05-12 Evening Update (post-intervention)

#### Pipeline State (after reset)
| Stage | Pending | Running | Failed | Notes |
|-------|---------|---------|--------|-------|
| uploaded | 2 | 0 | 0 | — |
| ocr | 1 | 0 | 3 | — |
| chunked | 2 | 0 | 25 | — |
| embedded | 29 | 7 | 0 | 22 reset zombies now PENDING; 7 active still RUNNING |
| indexed | 0 | 0 | 0 | 34 completed in last hour |

#### Observations
- The 7 remaining `RUNNING` embed tasks **are genuinely active** and making progress:
  - `bab2ee8c...` 128/7433 chunks
  - `8b70e63c...` 32/6078 chunks
  - `65b4c539...` 160/1179 chunks
  - `86f29b53...` 320/790 chunks
- Embed servers remain **highly loaded** (~90–98 % CPU), so the 29 pending tasks will not start until capacity frees up.
- No new zombie tasks created in the last 10 minutes.
- Code patches validated (imports OK inside backend container).

#### Post-Restart Embed Server State (~18:20 UTC)
Both embed servers restarted with the new dynamic-batcher code:
```json
{
  "status": "healthy",
  "queue_depth": 1,
  "rss_mb": 3640,
  "device": "cpu"
}
```
- `queue_depth` field confirms dynamic batcher is active.
- Batcher window = 10 ms, max batch size = 64.
- Logs show normal `POST /embed 200 OK` traffic resuming immediately.

### Architecture Changes Deployed (2026-05-12)

#### Dynamic Batching (embed_server/main.py v1.3.0)
- Replaced per-request `asyncio.Semaphore(1)` with a single `DynamicBatcher` coroutine.
- Coalesces concurrent `/embed` and `/embed-query` calls within a 10 ms window.
- Dispatches passages and queries separately (different prefixes).
- Returns `HTTP 503` when queue depth hits 512 (backpressure).
- Normalizes numpy arrays → Python lists before JSON serialization so both ST and ONNX backends work transparently.

#### ONNX/INT8 Rollout (pre-staged, not yet activated)
Files created:
- `backend/app/services/embedding_service_onnx.py` — drop-in ONNX Runtime backend
- `scripts/export_e5_to_onnx.py` — one-time model export (`optimum` + `avx512_vnni`)
- `scripts/validate_onnx_embeddings.py` — validates cosine similarity + top-k Jaccard against FP32 corpus
- `backend/embed_server/requirements.txt` — added `optimum[onnxruntime]==1.21.4` and `onnxruntime==1.18.1`

Activation: set `EMBED_BACKEND=onnx` env var on a replica and restart.

### Rollout Sequence (pending)
1. **Export model** (run once inside a container with the new deps):
   ```bash
   docker exec sowknow4-embed-server pip install "optimum[onnxruntime]==1.21.4" "onnxruntime==1.18.1"
   docker exec sowknow4-embed-server python /app/scripts/export_e5_to_onnx.py
   ```
2. **Validate** against production corpus:
   ```bash
   DATABASE_URL=postgresql://... python scripts/validate_onnx_embeddings.py --sample 500
   ```
3. **Canary** one replica with `EMBED_BACKEND=onnx`.
4. **Compare** throughput via batcher logs (`tput=...`) and `/health queue_depth`.
5. **Flip** second replica if metrics hold.
