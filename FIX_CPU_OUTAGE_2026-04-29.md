# SOWKNOW4 CPU Outage Fix — 2026-04-29

## Alarm Summary

| Container | CPU | Status |
|-----------|-----|--------|
| `sowknow4-backend` | **100.36%** | CRITICAL |
| `sowknow4-embed-server` | **100.82%** | CRITICAL |
| `sowknow4-embed-server-2` | **54.53%** | WARNING |

- Automated rollback of `sowknow4-backend` failed.
- 44 pending OS package updates on `vps1`.

---

## Root Cause

### 1. Unbounded `pipeline_sweeper` queries (`backend/app/tasks/pipeline_sweeper.py`)

The Celery Beat scheduler runs `pipeline.sweeper` **every 5 minutes**. Two of its queries had **no `LIMIT` clause**, causing them to fetch and iterate over an unbounded number of rows when a backlog exists:

- **`stuck_stages`** (line 58): fetches ALL documents stuck in `RUNNING` for each stage type.
- **`uploaded_done`** (line 256): fetches ALL documents with `UPLOADED=COMPLETED` to check if OCR is missing.

With a large document backlog, the backend CPU saturates looping over thousands of rows every 5 minutes, and each dispatch floods the embed queues, which in turn saturates the embed servers.

### 2. Excessive `gc.collect()` in embed server (`backend/app/services/embedding_service.py`)

A recent sync changed `gc.collect()` to run **after every single encode**, even for tiny batches of 1–5 texts. On a busy embed server this adds unnecessary CPU overhead.

---

## Fixes Applied

### Code Fix 1: Cap sweeper queries at 500 rows
**File:** `backend/app/tasks/pipeline_sweeper.py`

Added `.limit(500)` to both unbounded queries so the sweeper can never scan more than 500 rows per pass.

### Code Fix 2: Reduce GC pressure in embed server
**File:** `backend/app/services/embedding_service.py`

Restored conditional `gc.collect()` to run only for batches larger than 50 texts (previous behaviour).

### Code Fix 3: Database indexes for sweeper queries
**Files:**
- `backend/app/models/pipeline.py` — model updated
- `backend/alembic/versions/028_add_pipeline_sweeper_indexes.py` — migration created

Added composite indexes:
- `ix_pipeline_stages_stage_status_started` on `(stage, status, started_at)`
- `ix_pipeline_stages_stage_status` on `(stage, status)`

These prevent table scans when the sweeper filters by `stage` + `status`.

---

## Deployment Steps (run on vps1)

### 1. Pull the fixed code
```bash
cd /var/docker/sowknow4
git pull origin main
```

### 2. Run the emergency restart script
```bash
cd /var/docker/sowknow4
chmod +x scripts/emergency-restart.sh
./scripts/emergency-restart.sh
```

This script will:
1. Stop `celery-beat` first (pauses the sweeper).
2. Stop the three high-CPU containers gracefully.
3. Rebuild & restart them.
4. Run health checks.
5. Restart `celery-beat`.

### 3. Apply the DB migration (after services are healthy)
```bash
cd /var/docker/sowknow4/backend
docker compose exec backend alembic upgrade head
```

### 4. Verify the fix
Wait 5–10 minutes, then check:
```bash
# Container CPU
docker stats --no-stream sowknow4-backend sowknow4-embed-server sowknow4-embed-server-2

# Pipeline backlog (should show reasonable counts)
docker exec sowknow4-postgres psql -U sowknow -c \
  "SELECT stage, status, COUNT(*) FROM sowknow.pipeline_stages GROUP BY stage, status;"

# Recent sweeper metrics
docker logs --since 10m sowknow4-celery-beat 2>&1 | grep -i sweeper
```

### 5. Address pending package updates (maintenance window)
```bash
sudo apt update
sudo apt upgrade -y
# Reboot if kernel was updated
sudo reboot
```

---

## Why the Automated Rollback Failed

The rollback script attempted to restart `sowknow4-backend` while the sweeper was actively dispatching documents. Because the backend container was the source of the load (not just a victim), a simple `docker compose restart backend` did not stop the underlying cause. The sweeper tasks were still queued in Redis and resumed immediately after restart, pushing CPU back to 100%.

The correct fix is to **stop `celery-beat` first** (stops new sweeper runs), then restart the backend and embed servers together.

---

## Preventive Measures Already in Place

- Guardian HC `resource_hogs` runbook detects CPU >200% for >1h and can kill stray processes.
- Pipeline orchestrator has `MAX_QUEUE_DEPTH` backpressure to prevent queue overflow.
- Embed servers use `--limit-max-requests 10000` to recycle workers and release memory.

## Additional Recommendations

1. **Monitor `pipeline_stages` backlog** — set a Guardian alert if `PENDING` rows exceed 1,000.
2. **Add a rate-limit on the sweeper** — consider running it every 10 minutes instead of 5 if the system is under load.
3. **Review `cpuset` pinning** — `cpuset: "6,7"` and `cpuset: "4,5"` isolate embed servers to specific cores. On a shared VPS this is fine if those vCPUs exist, but if the host is oversubscribed it can cause steal-time spikes.
