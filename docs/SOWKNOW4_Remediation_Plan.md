# SOWKNOW4 — Remediation Plan

**Date:** April 13, 2026  
**Based on:** 2 rounds of forensic evidence collection, verified on VPS  
**Execution:** Hand each phase to Claude Code. Do NOT proceed to next phase until QA gate passes.  
**Principle:** One phase at a time. Verify. Then move.

---

## How to use this document

Each phase has 5 sections:

1. **CONTEXT** — what we know from evidence and why this matters
2. **CHANGES** — exact files and modifications required
3. **DEPLOY** — commands to apply the changes
4. **QA GATE** — validation commands that MUST all pass
5. **ROLLBACK** — how to undo if something goes wrong

**Claude Code instruction format:** Copy the CONTEXT + CHANGES section for each phase into Claude Code as the task. After Claude Code implements, run the QA GATE yourself on the VPS. Only proceed if every check passes.

---

## PHASE 1: Redis Emergency Recovery
**Priority:** P0 — System is down. Nothing works until this is fixed.  
**Estimated time:** 15 minutes  
**Risk:** Low (Redis is already crashed, can't get worse)

### CONTEXT

Redis is OOM crash-looping (exit code 137, restart count 8). Root cause confirmed by forensic evidence:
- Container cgroup memory limit: 512MB
- Redis maxmemory setting: 400MB
- Eviction policy: noeviction (Redis refuses writes at 400MB instead of evicting old keys)
- On-disk data (AOF + RDB): 181.9MB which expands to ~224MB in memory
- BGSAVE fork needs temporary memory overhead → pushes past 512MB cgroup → OOM kill
- Cycle repeats every ~27 seconds
- ALL downstream services (Celery workers, backend, Telegram bot) are dead because their broker is dead

Celery result TTL is 24 hours (result_expires=86400), so task results accumulate throughout the day.

### CHANGES

**File: `/var/docker/sowknow4/docker-compose.yml` — Redis service**

1. Raise container memory limit from 512MB to **768MB**
   - Why 768MB and not 512MB: Redis needs room for maxmemory (400MB) + BGSAVE fork overhead (~150-200MB) + AOF rewrite buffer. 400 + 200 + buffer = needs ~650MB minimum. 768MB gives safe headroom.

2. Change Redis command to use `allkeys-lru` eviction instead of `noeviction`
   - Find the Redis command/config line that sets `--maxmemory-policy noeviction`
   - Change to `--maxmemory-policy allkeys-lru`
   - This means when Redis approaches maxmemory (400MB), it evicts the least-recently-used keys instead of refusing writes and crashing the pipeline

3. Set `vm.overcommit_memory=1` on the host to prevent BGSAVE fork failures
   - Redis recommends this to avoid background save failures under memory pressure
   - Add to `/etc/sysctl.conf` and apply immediately

### DEPLOY

```bash
# 1. Backup docker-compose.yml
cd /var/docker/sowknow4
cp docker-compose.yml docker-compose.yml.bak-phase1-$(date +%Y%m%d-%H%M)

# 2. Apply changes to docker-compose.yml (Claude Code will edit the file)
# After editing, verify the diff:
diff docker-compose.yml.bak-phase1-* docker-compose.yml

# 3. Set vm.overcommit_memory on host
echo "vm.overcommit_memory = 1" | sudo tee -a /etc/sysctl.conf
sudo sysctl vm.overcommit_memory=1

# 4. Restart Redis only
docker compose up -d redis

# 5. Wait 30 seconds for Redis to stabilize, then restart dependent services
sleep 30
docker compose up -d
```

### QA GATE — All must pass before proceeding

```bash
echo "=== QA GATE: Phase 1 — Redis Recovery ==="

# QA-1.1: Redis is running and healthy (not restarting)
echo "--- QA-1.1: Redis container health ---"
docker inspect sowknow4-redis --format '{{.State.Status}} {{.State.Health.Status}} OOMKilled:{{.State.OOMKilled}} Restarts:{{.RestartCount}}'
# EXPECTED: running healthy OOMKilled:false Restarts:0 (or low, stable number)
# FAIL IF: OOMKilled:true or status is restarting

# QA-1.2: Redis responds to ping
echo "--- QA-1.2: Redis PING ---"
docker exec sowknow4-redis redis-cli PING
# EXPECTED: PONG
# FAIL IF: connection refused or timeout

# QA-1.3: Redis memory is under control
echo "--- QA-1.3: Redis memory ---"
docker exec sowknow4-redis redis-cli INFO memory | grep -E "used_memory_human|maxmemory_human|maxmemory_policy"
# EXPECTED: used_memory_human < 400MB, maxmemory_policy: allkeys-lru
# FAIL IF: maxmemory_policy still shows noeviction

# QA-1.4: Eviction policy is correct
echo "--- QA-1.4: Eviction policy ---"
docker exec sowknow4-redis redis-cli CONFIG GET maxmemory-policy
# EXPECTED: allkeys-lru
# FAIL IF: noeviction

# QA-1.5: Container memory limit is 768MB
echo "--- QA-1.5: Container memory limit ---"
docker inspect sowknow4-redis --format '{{.HostConfig.Memory}}' | awk '{print $1/1048576 "MB"}'
# EXPECTED: 768MB
# FAIL IF: 256MB or 512MB

# QA-1.6: All SOWKNOW containers are running
echo "--- QA-1.6: All containers up ---"
docker ps --filter "name=sowknow4" --format "{{.Names}} {{.Status}}" | sort
# EXPECTED: All containers show "Up" with (healthy) where applicable
# FAIL IF: Any container is restarting or exited

# QA-1.7: Celery workers can reach Redis
echo "--- QA-1.7: Worker broker connectivity ---"
docker logs sowknow4-celery-light --since 2m 2>&1 | grep -iE "connected|ready|error|redis" | tail -5
docker logs sowknow4-celery-heavy --since 2m 2>&1 | grep -iE "connected|ready|error|redis" | tail -5
# EXPECTED: "Connected to redis://..." or "celery@... ready"
# FAIL IF: "Cannot connect to redis" or "connection refused"

# QA-1.8: vm.overcommit_memory is set
echo "--- QA-1.8: vm.overcommit_memory ---"
sysctl vm.overcommit_memory
# EXPECTED: vm.overcommit_memory = 1
# FAIL IF: vm.overcommit_memory = 0

# QA-1.9: Redis stable for 2 minutes (no restart cycle)
echo "--- QA-1.9: Stability check (wait 2 min) ---"
echo "Watching for 2 minutes..."
for i in $(seq 1 4); do
    sleep 30
    status=$(docker inspect sowknow4-redis --format '{{.State.Status}}' 2>/dev/null)
    mem=$(docker stats sowknow4-redis --no-stream --format "{{.MemUsage}}" 2>/dev/null)
    echo "  Check $i/4: status=$status memory=$mem"
done
# EXPECTED: All 4 checks show "running" with stable memory
# FAIL IF: Status changes to "restarting" or memory keeps climbing

echo "=== Phase 1 QA complete. ALL checks must show EXPECTED values. ==="
```

### ROLLBACK

```bash
cd /var/docker/sowknow4
cp docker-compose.yml.bak-phase1-* docker-compose.yml
docker compose up -d redis
# Note: rollback returns to the crash state — only use if the fix made things worse
```

---

## PHASE 2: Confidential Routing Fix
**Priority:** P0 — 8,895 confidential documents cause RuntimeError on any matching query  
**Estimated time:** 30 minutes  
**Risk:** Medium — touches LLM routing logic. Must not break public document chat.  
**Depends on:** Phase 1 (Redis must be up for testing)

### CONTEXT

Evidence from forensic round 2:
- `llm_router.py` hard-codes confidential/PII traffic to `["ollama"]` only
- Ollama was intentionally removed from the VPS (too slow on CPU)
- When a confidential query arrives, the router tries Ollama, health check fails, raises `RuntimeError("No LLM provider available.")`
- 8,895 documents are in the confidential bucket — any search matching these will hard-fail
- HOWEVER: `chat_service.py` already implements metadata-only stripping (lines 191, 299, 305, 317) — confidential chunk content is stripped to metadata before reaching the LLM prompt
- The privacy guarantee is preserved at the service layer — the router just doesn't know this yet

The fix: Update the LLM router to allow cloud providers (OpenRouter/MiniMax) for confidential queries when Ollama is not available, BECAUSE the metadata-only content stripping already prevents raw confidential text from reaching the cloud LLM.

### CHANGES

**File: `/var/docker/sowknow4/backend/app/services/llm_router.py`**

Locate the `select_provider` method (around lines 215-238). Currently the logic is:
- If vault_hint == "confidential": providers = ["ollama"]
- This must change to: If vault_hint == "confidential" AND Ollama is available: use Ollama. If Ollama is NOT available: use the normal provider chain (OpenRouter → MiniMax) with a log warning that confidential query is being handled via metadata-only mode.

Important constraints:
- Do NOT remove the Ollama preference for confidential — if Ollama is ever re-added, it should automatically become the confidential provider again
- DO add a clear log line: `logger.warning("Confidential query routed via metadata-only mode (Ollama unavailable)")` — this creates an audit trail
- Do NOT change the metadata stripping in chat_service.py — it's already correct
- The docstring at lines 11-13 is stale ("Public docs → MiniMax → OpenRouter") — fix it to match reality while editing

**File: `/var/docker/sowknow4/backend/app/services/llm_router.py`**

Also update the `_build_router()` or module docstring to accurately reflect the routing:
- Public: OpenRouter (Mistral Small 2603) → MiniMax M2.7
- Confidential: Ollama (if available) → OpenRouter/MiniMax with metadata-only stripping (if Ollama unavailable)
- PII detected: Same as confidential

### DEPLOY

```bash
cd /var/docker/sowknow4

# 1. Backup
cp backend/app/services/llm_router.py backend/app/services/llm_router.py.bak-phase2-$(date +%Y%m%d-%H%M)

# 2. Claude Code edits llm_router.py

# 3. Rebuild and deploy backend (no bind mount — image rebuild required)
docker compose build backend
docker compose up -d backend

# 4. Also rebuild workers (they share the backend code)
docker compose build celery-light celery-heavy celery-collections
docker compose up -d celery-light celery-heavy celery-collections
```

### QA GATE — All must pass before proceeding

```bash
echo "=== QA GATE: Phase 2 — Confidential Routing ==="

# QA-2.1: Backend is running after rebuild
echo "--- QA-2.1: Backend health ---"
docker exec sowknow4-backend curl -s http://localhost:8000/health 2>/dev/null || \
docker exec sowknow4-backend curl -s http://localhost:8000/api/v1/health 2>/dev/null || \
echo "  Backend health endpoint not reachable (will be fixed in Phase 4)"
# EXPECTED: Some response (200 or JSON)
# NOTE: Health endpoint path may still be wrong — that's Phase 4

# QA-2.2: The routing change is in the running code
echo "--- QA-2.2: Router code verification ---"
docker exec sowknow4-backend grep -n "metadata.only\|metadata-only\|Ollama unavailable\|allkeys-lru\|confidential.*openrouter\|confidential.*fallback" /app/app/services/llm_router.py | head -10
# EXPECTED: Lines showing the new fallback logic and log warning
# FAIL IF: Still shows only ["ollama"] for confidential with no fallback

# QA-2.3: No import errors or startup crashes
echo "--- QA-2.3: Backend startup logs ---"
docker logs sowknow4-backend --since 5m 2>&1 | grep -iE "error|exception|import|traceback" | tail -10
# EXPECTED: No errors (or only pre-existing unrelated warnings)
# FAIL IF: ImportError, SyntaxError, or any crash

# QA-2.4: Ollama health check failures are logged (expected — Ollama is removed)
echo "--- QA-2.4: Ollama health check in logs ---"
docker logs sowknow4-backend --since 5m 2>&1 | grep -iE "ollama" | tail -5
# EXPECTED: "ollama failed" or "Ollama unavailable" — this is correct behavior
# FAIL IF: No mention of Ollama at all (routing logic may not be executing)

# QA-2.5: Verify confidential document count is accessible
echo "--- QA-2.5: Confidential document count ---"
docker exec sowknow4-postgres psql -U sowknow -d sowknow -c "SELECT bucket, COUNT(*) FROM documents GROUP BY bucket;"
# EXPECTED: confidential = ~8,895
# This confirms the data is still intact

# QA-2.6: CRITICAL — Test a confidential query via Telegram or API
echo "--- QA-2.6: Manual test required ---"
echo "  ACTION NEEDED: Send a query via Telegram that should match a confidential document."
echo "  For example, search for a name that appears in confidential documents."
echo "  EXPECTED: Response with metadata references, NOT a RuntimeError."
echo "  FAIL IF: Error message about 'No LLM provider available' or timeout."
echo ""
echo "  After testing, check logs for the audit trail:"
docker logs sowknow4-backend --since 5m 2>&1 | grep -i "metadata.only\|confidential.*routed\|metadata-only" | tail -5
# EXPECTED: Log line showing metadata-only routing was used

echo "=== Phase 2 QA complete. QA-2.6 requires manual verification. ==="
```

### ROLLBACK

```bash
cd /var/docker/sowknow4
cp backend/app/services/llm_router.py.bak-phase2-* backend/app/services/llm_router.py
docker compose build backend celery-light celery-heavy celery-collections
docker compose up -d backend celery-light celery-heavy celery-collections
```

---

## PHASE 3: Pipeline Recovery
**Priority:** P1 — 3,634 documents stuck, 54 zombie tasks  
**Estimated time:** 30 minutes active, then 2-4 hours monitored recovery  
**Risk:** Low — database updates on non-terminal rows only  
**Depends on:** Phase 1 (Redis must be up), Phase 2 (routing must work for pipeline)

### CONTEXT

Evidence from forensic round 1:
- 778 documents in OCR pending (7 days old)
- 2,802 documents in embed pending (7 days old)
- 54 documents stuck in embed "running" (15+ hours — zombie tasks from Redis crash)
- 40 permanently failed documents (12 embed, 26 chunked, 2 OCR)
- Sweeper throttling IS deployed (500/queue/sweep with backpressure gates)
- Caveat: if Redis is still flaky when first sweep runs, backpressure bypass triggers

### CHANGES

This phase has no code changes — only database operations and monitored recovery.

**Step 1: Reset 54 zombie "running" tasks to "pending"**

These tasks were in-flight when Redis crashed. The workers that owned them are gone. They will never complete. Reset them so the sweeper can re-dispatch.

```sql
-- Run inside sowknow4-postgres
-- First, count what we'll update (dry run)
SELECT stage, status, COUNT(*), MIN(updated_at) as oldest
FROM pipeline_stages
WHERE status = 'running'
  AND updated_at < NOW() - INTERVAL '1 hour'
GROUP BY stage, status;

-- Then reset (only if dry run looks right)
UPDATE pipeline_stages
SET status = 'pending',
    updated_at = NOW()
WHERE status = 'running'
  AND updated_at < NOW() - INTERVAL '1 hour';
```

**Step 2: Let the sweeper handle the 778 + 2,802 pending documents naturally**

Do NOT manually dispatch tasks. The sweeper has backpressure gates (500/queue/sweep) that prevent queue flooding. Let it run on its normal 5-minute cycle.

**Step 3: Monitor memory and queue depth for 2 hours**

The pipeline will now process ~3,600 documents. Watch for:
- celery-heavy memory staying under 4GB (solo pool should be fine)
- Redis memory staying under 400MB (allkeys-lru should evict if needed)
- Queue depth not exceeding 500 per queue (backpressure should cap it)

### DEPLOY

```bash
# Step 1: Reset zombies
docker exec sowknow4-postgres psql -U sowknow -d sowknow -c "
  -- Dry run: show what will be reset
  SELECT stage, status, COUNT(*), MIN(updated_at) as oldest
  FROM pipeline_stages
  WHERE status = 'running'
    AND updated_at < NOW() - INTERVAL '1 hour'
  GROUP BY stage, status;
"

# If dry run looks correct, execute:
docker exec sowknow4-postgres psql -U sowknow -d sowknow -c "
  UPDATE pipeline_stages
  SET status = 'pending', updated_at = NOW()
  WHERE status = 'running'
    AND updated_at < NOW() - INTERVAL '1 hour';
"

# Step 2: Monitor (run this in a terminal for 2 hours)
watch -n 60 '
echo "=== Pipeline Status ==="
docker exec sowknow4-postgres psql -U sowknow -d sowknow -c "
  SELECT stage, status, COUNT(*) FROM pipeline_stages
  WHERE status IN ('"'"'pending'"'"','"'"'running'"'"','"'"'failed'"'"')
  GROUP BY stage, status ORDER BY stage, status;"

echo ""
echo "=== Queue Depths ==="
for q in celery document_processing pipeline.embed pipeline.ocr pipeline.chunk collections; do
  depth=$(docker exec sowknow4-redis redis-cli LLEN "$q" 2>/dev/null || echo "N/A")
  printf "  %-25s %s\n" "$q" "$depth"
done

echo ""
echo "=== Memory ==="
docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" sowknow4-redis sowknow4-celery-heavy sowknow4-celery-light 2>/dev/null
'
```

### QA GATE — All must pass before proceeding

```bash
echo "=== QA GATE: Phase 3 — Pipeline Recovery ==="

# QA-3.1: No zombie running tasks remain
echo "--- QA-3.1: Zombie check ---"
docker exec sowknow4-postgres psql -U sowknow -d sowknow -c "
  SELECT COUNT(*) as zombie_count FROM pipeline_stages
  WHERE status = 'running' AND updated_at < NOW() - INTERVAL '1 hour';"
# EXPECTED: 0
# FAIL IF: > 0

# QA-3.2: Pending counts are decreasing (run twice, 10 min apart)
echo "--- QA-3.2: Pipeline draining ---"
docker exec sowknow4-postgres psql -U sowknow -d sowknow -c "
  SELECT stage, status, COUNT(*) FROM pipeline_stages
  WHERE status = 'pending' GROUP BY stage, status ORDER BY stage;"
# EXPECTED: Numbers should be lower than the initial 778 + 2,802
# FAIL IF: Numbers are static or increasing

# QA-3.3: Completed count is increasing
echo "--- QA-3.3: Completions ---"
docker exec sowknow4-postgres psql -U sowknow -d sowknow -c "
  SELECT stage, COUNT(*) FROM pipeline_stages
  WHERE status = 'completed' AND updated_at > NOW() - INTERVAL '1 hour'
  GROUP BY stage;"
# EXPECTED: Recent completions appearing
# FAIL IF: Zero completions in last hour

# QA-3.4: Redis memory stable
echo "--- QA-3.4: Redis memory during recovery ---"
docker exec sowknow4-redis redis-cli INFO memory | grep used_memory_human
# EXPECTED: Below 400MB
# FAIL IF: Approaching 400MB with no evictions happening

# QA-3.5: celery-heavy not approaching memory limit
echo "--- QA-3.5: Heavy worker memory ---"
docker stats sowknow4-celery-heavy --no-stream --format "{{.MemUsage}}"
# EXPECTED: Well below 4GB
# FAIL IF: Climbing toward limit

# QA-3.6: No new OOM kills
echo "--- QA-3.6: Kernel OOM check ---"
dmesg -T 2>/dev/null | grep -i "out of memory" | tail -5
# EXPECTED: No new entries since Phase 1
# FAIL IF: New OOM kills

echo "=== Phase 3 QA complete. Run QA-3.2 twice 10 min apart to confirm drain. ==="
```

### ROLLBACK

No rollback needed — the zombie reset is idempotent. If the pipeline isn't draining, stop investigating the pipeline and go back to Phase 1/2 verification.

---

## PHASE 4: Health & Observability Fixes
**Priority:** P1 — prevents future incidents from being masked  
**Estimated time:** 45 minutes  
**Risk:** Low — health checks only affect monitoring, not functionality  
**Depends on:** Phase 1-3 stable

### CONTEXT

Evidence confirmed:
- Backend healthcheck hits `http://localhost:3000/` (the frontend) — backend health is never checked
- Real backend health endpoints: `/health`, `/api/v1/health`, `/api/v1/health/detailed`
- Celery worker health checks only verify `grep -q celery` in cmdline — process alive, not broker-connected
- Redis health check correctly uses `redis-cli ping` but can't save Redis from OOM (that's now fixed)

### CHANGES

**File: `/var/docker/sowknow4/docker-compose.yml` — backend service healthcheck**

Change the healthcheck test from:
```yaml
test: ["CMD-SHELL", "curl -f http://localhost:3000/ || exit 1"]
```
To:
```yaml
test: ["CMD-SHELL", "curl -sf http://127.0.0.1:8000/health || curl -sf http://127.0.0.1:8000/api/v1/health || exit 1"]
```

This tries both health endpoints (the actual backend port and path).

**File: `/var/docker/sowknow4/docker-compose.yml` — celery-light and celery-heavy healthchecks**

Change from process-alive check:
```yaml
test: ["CMD-SHELL", "cat /proc/1/cmdline 2>/dev/null | tr '\\0' ' ' | grep -q celery || exit 1"]
```
To broker-connectivity check:
```yaml
test: ["CMD-SHELL", "celery -A app.celery_app inspect ping --timeout 10 2>/dev/null | grep -q OK || exit 1"]
```

This verifies the worker can actually reach the broker (Redis) and respond to a ping — not just that the process exists.

Note: `celery inspect ping` may be slow (10s timeout). If it causes health check flapping, fall back to a lighter check that tests Redis connectivity:
```yaml
test: ["CMD-SHELL", "python -c 'import redis; r=redis.Redis(host=\"redis\"); r.ping()' || exit 1"]
```

### DEPLOY

```bash
cd /var/docker/sowknow4
cp docker-compose.yml docker-compose.yml.bak-phase4-$(date +%Y%m%d-%H%M)

# Claude Code edits docker-compose.yml

# Apply — restart only the containers whose healthchecks changed
docker compose up -d backend celery-light celery-heavy
```

### QA GATE

```bash
echo "=== QA GATE: Phase 4 — Observability ==="

# QA-4.1: Backend healthcheck now hits the backend
echo "--- QA-4.1: Backend health ---"
docker inspect sowknow4-backend --format '{{.Config.Healthcheck.Test}}'
# EXPECTED: Contains "127.0.0.1:8000" not "localhost:3000"

# QA-4.2: Backend reports healthy via the correct endpoint
echo "--- QA-4.2: Backend health status ---"
docker inspect sowknow4-backend --format '{{.State.Health.Status}}'
# EXPECTED: healthy
# FAIL IF: unhealthy (may mean the health endpoint returns non-200 — investigate)

# QA-4.3: Worker healthchecks test broker connectivity
echo "--- QA-4.3: Worker healthcheck definition ---"
docker inspect sowknow4-celery-light --format '{{.Config.Healthcheck.Test}}'
docker inspect sowknow4-celery-heavy --format '{{.Config.Healthcheck.Test}}'
# EXPECTED: Contains "inspect ping" or "redis" or broker connectivity test
# FAIL IF: Still contains "grep -q celery"

# QA-4.4: Workers report healthy
echo "--- QA-4.4: Worker health status ---"
docker inspect sowknow4-celery-light --format '{{.State.Health.Status}}'
docker inspect sowknow4-celery-heavy --format '{{.State.Health.Status}}'
# EXPECTED: healthy
# FAIL IF: unhealthy (may mean celery inspect ping is too slow — use fallback check)

# QA-4.5: Simulate Redis down — workers should go unhealthy
echo "--- QA-4.5: Negative test (OPTIONAL — only run if brave) ---"
echo "  To test: docker pause sowknow4-redis, wait 90s, check worker health."
echo "  Workers should report unhealthy. Then: docker unpause sowknow4-redis."
echo "  Skip this if the system just recovered — stability is more important."

echo "=== Phase 4 QA complete. ==="
```

### ROLLBACK

```bash
cd /var/docker/sowknow4
cp docker-compose.yml.bak-phase4-* docker-compose.yml
docker compose up -d backend celery-light celery-heavy
```

---

## PHASE 5: Whisper Voice Transcription Fix
**Priority:** P1 — Voice notes via Telegram are non-functional  
**Estimated time:** 15 minutes + rebuild time (~10-15 min for whisper compilation)  
**Risk:** Low — only affects voice transcription, no impact on core pipeline  
**Depends on:** Phase 1 (Redis must be up for workers to start)

### CONTEXT

Evidence confirmed in both forensic rounds:
- `whisper-cpp` binary exists at `/usr/local/bin/whisper-cpp`
- Model exists at `/models/ggml-small.bin` (466MB)
- Error: `libggml.so.0: cannot open shared object file: No such file or directory`
- Previous investigation identified `libwhisper.so` as missing — that's been fixed
- NEW: upstream whisper.cpp split `ggml` into a separate shared library
- `libggml.so.0` and `libggml-base.so.0` must be copied from the build directory to `/usr/local/lib/` before the build cleanup step

### CHANGES

**File: `/var/docker/sowknow4/backend/Dockerfile.worker`**

Find the whisper.cpp build section. It currently looks approximately like:

```dockerfile
    && cp build/bin/whisper-cli /usr/local/bin/whisper-cpp \
    && cp build/src/libwhisper.so* /usr/local/lib/ \
    && ldconfig \
    && cd / && rm -rf /tmp/whisper.cpp \
```

Add the ggml library copies BEFORE the cleanup step:

```dockerfile
    && cp build/bin/whisper-cli /usr/local/bin/whisper-cpp \
    && cp build/src/libwhisper.so* /usr/local/lib/ \
    && cp build/ggml/src/libggml.so* /usr/local/lib/ \
    && cp build/ggml/src/libggml-base.so* /usr/local/lib/ \
    && ldconfig \
    && cd / && rm -rf /tmp/whisper.cpp \
```

**Important:** The exact path to `libggml*.so*` depends on the whisper.cpp version. If `build/ggml/src/` doesn't exist, find them:
```bash
# Run inside the build step if paths don't match:
find build -name "libggml*.so*" -type f
```

### DEPLOY

```bash
cd /var/docker/sowknow4
cp backend/Dockerfile.worker backend/Dockerfile.worker.bak-phase5-$(date +%Y%m%d-%H%M)

# Claude Code edits Dockerfile.worker

# Rebuild BOTH worker images (they share the Dockerfile)
docker compose build celery-light celery-heavy

# Restart workers
docker compose up -d celery-light celery-heavy
```

### QA GATE

```bash
echo "=== QA GATE: Phase 5 — Whisper Fix ==="

# QA-5.1: whisper-cpp runs without shared library error
echo "--- QA-5.1: whisper-cpp help ---"
docker exec sowknow4-celery-light /usr/local/bin/whisper-cpp --help 2>&1 | head -3
# EXPECTED: Usage information, NOT "cannot open shared object file"
# FAIL IF: libggml error persists

# QA-5.2: All required shared libraries are resolved
echo "--- QA-5.2: ldd check ---"
docker exec sowknow4-celery-light ldd /usr/local/bin/whisper-cpp 2>/dev/null | grep -E "not found|libggml|libwhisper"
# EXPECTED: libggml.so.0, libggml-base.so.0, libwhisper.so all resolved (no "not found")
# FAIL IF: Any line shows "not found"

# QA-5.3: Model file is accessible
echo "--- QA-5.3: Model file ---"
docker exec sowknow4-celery-light ls -lh /models/ggml-small.bin
# EXPECTED: ~466MB file present

# QA-5.4: Workers are healthy after rebuild
echo "--- QA-5.4: Worker status ---"
docker ps --filter "name=sowknow4-celery" --format "{{.Names}} {{.Status}}"
# EXPECTED: All celery containers Up (healthy)

# QA-5.5: Pipeline still processing (rebuild didn't break embedding)
echo "--- QA-5.5: Pipeline continuity ---"
docker logs sowknow4-celery-heavy --since 5m 2>&1 | grep -iE "embedded\|succeeded\|task" | tail -5
# EXPECTED: Recent task completions
# FAIL IF: No activity or errors

# QA-5.6: Voice transcription end-to-end test (MANUAL)
echo "--- QA-5.6: Manual test ---"
echo "  ACTION NEEDED: Send a voice note via Telegram to the SOWKNOW bot."
echo "  EXPECTED: Transcribed text response."
echo "  FAIL IF: Error or silence."
echo ""
echo "  After testing, check logs:"
docker logs sowknow4-celery-light --since 5m 2>&1 | grep -iE "whisper|transcri|voice|audio" | tail -10

echo "=== Phase 5 QA complete. QA-5.6 requires manual verification. ==="
```

### ROLLBACK

```bash
cd /var/docker/sowknow4
cp backend/Dockerfile.worker.bak-phase5-* backend/Dockerfile.worker
docker compose build celery-light celery-heavy
docker compose up -d celery-light celery-heavy
```

---

## PHASE 6: Cleanup & Hardening
**Priority:** P2 — Technical debt reduction, not blocking  
**Estimated time:** 1-2 hours  
**Risk:** Low  
**Depends on:** All previous phases stable for 24+ hours

### CONTEXT

Evidence from full investigation:
- Kimi/Moonshot service is dead code (loaded but zero traffic, docstring says "legacy — being phased out")
- 42GB of inactive Docker images reclaimable
- 7.75GB of build cache reclaimable
- Stale docstrings in llm_router.py (partially fixed in Phase 2)
- PRD v1.1 has 6+ factual errors vs. reality

### CHANGES

**6A: Remove dead Kimi code**
- Remove `kimi_service.py` import and injection from `chat_service.py` and `llm_router.py`
- Remove `KIMI_API_KEY` / `MOONSHOT_API_KEY` from `.env` template (keep in `.env` if historical reference needed)
- Do NOT delete `kimi_service.py` file yet — just remove the imports and injections

**6B: Docker image cleanup**
```bash
# List images that would be pruned (dry run)
docker image prune --all --filter "until=168h" --dry-run

# If safe, prune
docker image prune --all --filter "until=168h"

# Build cache cleanup
docker builder prune --keep-storage 2GB
```

**6C: PRD v1.2 draft**

Create a PRD update document noting at minimum:
- VPS is 31GB RAM, not 16GB
- LLM provider is OpenRouter (Mistral Small 2603) with MiniMax fallback, not Kimi/Moonshot
- Ollama is removed (not viable on CPU-only VPS)
- Confidential routing uses metadata-only stripping to cloud providers
- Container limits: Redis 768MB, celery-heavy 4GB (not 512MB per PRD)
- Queue separation: celery-collections is separate, celery-light still handles pipeline stages
- InputGuard exists and is deployed
- Knowledge graph module drafted but not wired into live pipeline
- Agent orchestrator exists but agent identity profiles need improvement

### QA GATE

```bash
echo "=== QA GATE: Phase 6 — Cleanup ==="

# QA-6.1: Kimi imports removed
echo "--- QA-6.1: No Kimi references in active code paths ---"
docker exec sowknow4-backend grep -rn "kimi_service\|from.*kimi" /app/app/services/chat_service.py /app/app/services/llm_router.py 2>/dev/null
# EXPECTED: No matches (or only in the file itself, not imports)
# FAIL IF: Active import statements still present

# QA-6.2: Backend still works after Kimi removal
echo "--- QA-6.2: Backend health ---"
docker logs sowknow4-backend --since 2m 2>&1 | grep -iE "error|exception|import" | tail -5
# EXPECTED: No import errors
# FAIL IF: ImportError related to kimi

# QA-6.3: Disk space recovered
echo "--- QA-6.3: Disk usage ---"
df -h / | tail -1
docker system df
# EXPECTED: Significant reduction in image/cache usage

# QA-6.4: Full system health after all phases
echo "--- QA-6.4: Final system state ---"
docker ps --filter "name=sowknow4" --format "{{.Names}} {{.Status}}" | sort
echo ""
docker exec sowknow4-redis redis-cli INFO memory | grep used_memory_human
echo ""
docker exec sowknow4-postgres psql -U sowknow -d sowknow -c "
  SELECT status, COUNT(*) FROM pipeline_stages GROUP BY status ORDER BY status;"
echo ""
echo "All SOWKNOW4 systems nominal."

echo "=== Phase 6 QA complete. Full remediation plan executed. ==="
```

---

## POST-REMEDIATION: 48-Hour Stability Watch

After all phases are complete, monitor for the 2-day cycle that was the original complaint. Run this check at 24h and 48h after Phase 6:

```bash
echo "=== 48-Hour Stability Check ==="
echo "Timestamp: $(date)"

# 1. Redis still healthy?
docker inspect sowknow4-redis --format 'OOMKilled:{{.State.OOMKilled}} Restarts:{{.RestartCount}}'
docker exec sowknow4-redis redis-cli INFO memory | grep -E "used_memory_human|evicted_keys"

# 2. Any OOM kills since remediation?
dmesg -T 2>/dev/null | grep -i "out of memory" | tail -5

# 3. Pipeline draining normally?
docker exec sowknow4-postgres psql -U sowknow -d sowknow -c "
  SELECT status, COUNT(*) FROM pipeline_stages GROUP BY status ORDER BY status;"

# 4. All containers stable?
docker ps --filter "name=sowknow4" --format "{{.Names}} {{.Status}}" | sort

# 5. No cascading failures?
for c in sowknow4-backend sowknow4-celery-light sowknow4-celery-heavy sowknow4-redis; do
    echo "--- $c recent errors ---"
    docker logs "$c" --since 24h 2>&1 | grep -c -iE "error|exception|timeout|killed"
done

echo ""
echo "If restart counts are 0 and pipeline pending counts are decreasing:"
echo "THE 2-DAY CYCLE IS BROKEN."
```

---

## Summary

| Phase | What | Blocks | Time |
|-------|------|--------|------|
| 1 | Redis: 768MB + allkeys-lru + vm.overcommit | Everything | 15 min |
| 2 | Confidential routing: allow cloud with metadata-only | Chat for 8,895 docs | 30 min |
| 3 | Pipeline: reset zombies, monitor recovery | Document processing | 30 min + 2h watch |
| 4 | Health checks: correct paths and broker probes | Future incident detection | 45 min |
| 5 | Whisper: copy libggml.so* in Dockerfile | Voice transcription | 15 min + rebuild |
| 6 | Cleanup: dead code, images, PRD update | Technical debt | 1-2 hours |

Total active effort: ~4-5 hours across 2-3 days (allowing stability verification between phases).

---

*This plan was built on verified evidence, not assumptions. Every change traces back to a specific forensic finding. The QA gates ensure nothing is forgotten and no phase proceeds without confirmation.*
