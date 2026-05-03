# SOWKNOW4 Stabilization Runbook — 2026-05-01

## Context

Daily production incidents have been traced to two recurring patterns:

1. **celery-light memory pressure (~95%)** — caused by 4 concurrent prefork workers
   running OCR, whisper-cpp (466 MB model), LLM article generation, and entity
   extraction inside a 3072 MB cgroup.
2. **embed-server CPU spikes (~101%)** — historically a *symptom* of upstream queue
   flooding by the pipeline sweeper, not a root cause in the embed server itself.

This runbook documents the systemic fixes applied to break the incident loop.

---

## Changes Applied

### 1. Infrastructure — docker-compose.yml

| Service | Change | Rationale |
|---------|--------|-----------|
| **celery-light** | Memory limit `3072M → 4096M` | Headroom for whisper model + OCR + 4 workers |
| **celery-light** | Added `--max-tasks-per-child=20` | Forces worker process recycle before memory fragmentation accumulates (PaddleOCR / whisper leak paths) |
| **celery-light** | Healthcheck: process-alive → broker-connectivity | `celery inspect ping` proves the worker can reach Redis; process-alive was hiding zombie workers |
| **celery-heavy** | Healthcheck: same broker-connectivity upgrade | Consistent observability across all Celery workers |
| **Memory comments** | Updated all stale allocation comments | `embed-server` was documented as 3072 MB but actually allocated 10240 MB; `backend` as 768 MB but actually 1536 MB |

**Deploy command:**
```bash
cd /var/docker/sowknow4
docker compose up -d --no-deps celery-light celery-heavy
```

---

### 2. Pipeline Sweeper — backend/app/tasks/pipeline_sweeper.py

| Change | Detail |
|--------|--------|
| **MAX_DISPATCHES_PER_RUN** | Hard cap of `1000` dispatches per 5-minute sweep. Prevents the sweeper from flooding queues when a large backlog exists (e.g., after an outage or batch upload). |
| **Embed backpressure** | Pre-dispatch check of `pipeline.embed` queue depth. If depth > `250`, the sweeper skips stalled/missing dispatches that would land on the embed queue. |
| **Metrics enrichment** | Sweeper log now includes `total_dispatched`, `embed_queue_depth`, `embed_backpressure`, and `max_dispatches_per_run` for faster RCA. |

**Environment overrides:**
```bash
SWEEPER_MAX_DISPATCH=500      # lower cap during sensitive windows
SWEEPER_EMBED_QUEUE_LIMIT=150 # more aggressive embed protection
```

---

### 3. Pipeline Orchestrator — backend/app/tasks/pipeline_orchestrator.py

| Change | Detail |
|--------|--------|
| **Global backpressure** | New `MAX_TOTAL_QUEUE_DEPTH = 800`. If the sum of all pipeline queues exceeds 800, **all** dispatching stops until the workers catch up. |
| **Total queue depth metric** | `_total_queue_depth()` helper sums every pipeline queue for the global check. |

This closes the gap where individual queue limits were respected but the *sum* of queues could still overwhelm the system.

---

### 4. Embed Client Circuit Breaker — backend/app/services/embed_client.py

| Change | Detail |
|--------|--------|
| **Circuit breaker** | After `5` consecutive failures, the client fast-fails all requests for `60` seconds instead of retrying and hammering an overloaded embed server. |
| **Success reset** | A single successful request resets the failure counter. |
| **Failure recording** | HTTP status errors and network errors both increment the counter. |

This prevents the "thundering herd" problem when an embed-server worker is mid-restart (`--limit-max-requests 10000`).

---

### 5. Celery Resilience — backend/app/celery_app.py

| Change | Detail |
|--------|--------|
| `task_reject_on_worker_lost=True` | If a worker is SIGKILL'd (OOM, Guardian HC restart), the task is re-queued instead of lost. Combined with `acks_late=True` this eliminates ghost tasks. |
| `worker_send_task_events=True` | Enables runtime task tracking for Flower / monitoring dashboards. |
| `task_send_sent_event=True` | Emits `task-sent` events for queue-depth correlation. |

---

### 6. Guardian HC Early Warning — monitoring/guardian-hc/checks/memory.py

| Change | Detail |
|--------|--------|
| **80% warning threshold** | Memory check now emits `severity: warning` at `>80%` and `severity: critical` at `>90%`. Operators get a 10-percentage-point buffer to act before auto-heal triggers a restart. |

---

## Operational Playbook

### Scenario A: celery-light memory > 90% (auto-heal restart)

1. Check if restart is looping:
   ```bash
   docker logs --since 30m sowknow4-celery-light | grep -c "Ready"
   ```
   If count > 3 in 30 min → memory leak, not transient load.

2. If looping, lower concurrency temporarily:
   ```bash
   # Edit docker-compose.yml: --concurrency=4 → --concurrency=2
   docker compose up -d --no-deps celery-light
   ```

3. If still looping after concurrency drop, check for stuck tasks:
   ```bash
   docker exec sowknow4-celery-light celery -A app.celery_app inspect active
   ```

### Scenario B: embed-server CPU sustained > 100% for >1 hour

1. **Do NOT restart embed-server first.** Check upstream cause:
   ```bash
   docker logs --since 60m sowknow4-backend | grep -i "sweeper completed"
   ```
   Look for `total_dispatched` near the 1000 cap or `embed_backpressure: true`.

2. Check queue depths:
   ```bash
   docker exec sowknow4-redis redis-cli -a $REDIS_PASSWORD llen pipeline.embed
   docker exec sowknow4-redis redis-cli -a $REDIS_PASSWORD llen pipeline.ocr
   ```

3. If queues are > 500 each, stop celery-beat to pause sweeper dispatch:
   ```bash
   docker compose stop sowknow4-celery-beat
   # Wait for workers to drain queues, then restart
   docker compose start sowknow4-celery-beat
   ```

4. Only restart embed-server if `/health` passes but `/embed` returns 500 or hangs
   (see `runbooks/embed_server_deep.yml`).

### Scenario C: Global queue depth > 800 (all dispatching stopped)

1. Identify which stage is bottlenecked:
   ```bash
   for q in pipeline.ocr pipeline.chunk pipeline.embed pipeline.index pipeline.articles pipeline.entities; do
     depth=$(docker exec sowknow4-redis redis-cli -a $REDIS_PASSWORD llen $q)
     echo "$q: $depth"
   done
   ```

2. Scale the bottleneck worker (if CPU/memory headroom exists):
   ```bash
   # Example: embed queue is backed up
   docker compose up -d --scale celery-heavy=2  # only if host has CPU free
   ```
   > Note: `celery-heavy` uses `--pool=threads`, so scaling is safe. Do NOT scale
   > `celery-entities` (prefork + 1.3 GB model = OOM).

3. If no headroom, pause new uploads until drain completes.

---

## Monitoring Checklist (verify after deploy)

- [ ] `docker inspect sowknow4-celery-light --format '{{.HostConfig.Memory}}'` → `4294967296` (4 GiB)
- [ ] `docker inspect sowknow4-celery-light --format '{{.Config.Healthcheck.Test}}'` → contains `inspect ping`
- [ ] `docker logs sowknow4-celery-light | grep "ready"` → worker starts without error
- [ ] `docker exec sowknow4-backend python -c "from app.services.embed_client import embedding_service; print(embedding_service._consecutive_failures)"` → `0`
- [ ] Guardian HC memory check shows `severity` field in `/tmp/guardian-memory.json` (or equivalent)
- [ ] Sweeper logs include `embed_queue_depth` and `total_dispatched` fields

---

## Future Hardening (backlog)

1. **Dedicated voice worker** — Move `app.tasks.voice_tasks.*` to a new `celery-voice`
   queue/worker so whisper-cpp's 466 MB model does not share memory with OCR/LLM tasks.
2. **Redis stream queue depth** — Replace `llen` checks with Redis Streams for exact
   consumer-group lag metrics.
3. **Embed-server auto-scaling** — Use Docker Compose `deploy.replicas` with a
   lightweight HAProxy sidecar instead of static round-robin in `embed_client.py`.
4. **SLO-based alerting** — Alert on p95 pipeline latency per stage, not just
   container resource metrics.

---

## References

- `FIX_CPU_OUTAGE_2026-04-29.md` — Root cause of the 101% CPU false-positive pattern
- `docs/SOWKNOW4_Remediation_Plan.md` — Original healthcheck improvement recommendations
- `docs/superpowers/specs/2026-04-09-alertiq-sowknow-design.md` — Entity queue explosion pattern
