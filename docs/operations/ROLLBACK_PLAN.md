# §3.4 Priority & Rollback Plan

Phased rollout of the §3.2/§3.3 tier reconfiguration with automated monitoring and documented rollback procedures.

## Model Stack (current)

| Tier | Model | Purpose |
|------|-------|---------|
| Primary (`OPENROUTER_MODEL`) | `mistralai/mistral-small-2409` | Default chat, synthesis |
| Simple (`OPENROUTER_TIER_SIMPLE`) | `google/gemini-2.0-flash-001` | Intent parsing, tagging, extraction |
| Standard (`OPENROUTER_TIER_STANDARD`) | `mistralai/mistral-small-2409` | Chat RAG, articles, Graph-RAG |
| Complex (`OPENROUTER_TIER_COMPLEX`) | `anthropic/claude-3.5-sonnet` | Reports, reasoning, verification |

## Rollback Monitor

The `RollbackMonitor` service (`app/services/rollback_monitor.py`) tracks the metrics that trigger rollbacks. It persists data in Redis with 24-hour rolling windows.

### Tracked Metrics

| Metric | Redis Key Pattern | Threshold |
|--------|-------------------|-----------|
| Latency (P95) | `rollback:latency:{tier}` | >3,000 ms (standard/simple) |
| TTFT (P95) | `rollback:ttft:{tier}` | >8,000 ms (complex) |
| JSON parse failure rate | `rollback:json_fail:{tier}` / `rollback:json_ok:{tier}` | >10% |
| Report cost | `rollback:report_cost` | >$0.50 |
| Satisfaction score | `rollback:satisfaction:{role}` | <4.0/5 |

### API Endpoint

```
GET /api/v1/status/rollback
```

Returns current metrics, active triggers, and recommended rollback actions.

## Phased Rollout

### Day 0 — Pre-launch

**Action:** Fix `smart_folder_service.py` to use env-var driven model selection (no hardcoded free-tier fallbacks).

**Status:** ✅ Completed in commit `d85f8d4`.

**Rollback trigger:** Content generation fails.
**Rollback action:** Hardcode `OPENROUTER_MODEL=mistralai/mistral-small-2409`.

---

### Day 0 — Simple Tier

**Action:** `OPENROUTER_TIER_SIMPLE=google/gemini-2.0-flash-001`

**Status:** ✅ Active (config + env defaults updated).

**Rollback trigger:** Flash returns empty on French queries.
**Rollback action:** Revert to `OPENROUTER_TIER_SIMPLE=qwen/qwen3.5-plus-20260420`.

---

### Day 1–3 — Standard Tier

**Action:** `OPENROUTER_TIER_STANDARD=mistralai/mistral-small-2409`

**Status:** ✅ Active.

**Rollback trigger:**
- JSON parse failure rate >10% **or**
- P95 latency >3,000 ms

**Rollback action:** Revert to `OPENROUTER_TIER_STANDARD=qwen/qwen3.5-plus-20260420`.

**Monitoring:** Check `/api/v1/status/rollback` daily. Watch `rollback:latency:standard` and `rollback:json_fail:standard`.

---

### Day 4–7 — Complex Tier

**Action:** `OPENROUTER_TIER_COMPLEX=anthropic/claude-3.5-sonnet`

**Status:** ✅ Active.

**Rollback trigger:**
- Cost per comprehensive report >$0.50 **or**
- TTFT >8,000 ms

**Rollback action:** Revert to `OPENROUTER_TIER_COMPLEX=deepseek/deepseek-v4-pro`.

**Monitoring:** Check `/api/v1/status/rollback` daily. Watch `rollback:report_cost` and `rollback:ttft:complex`.

---

### Day 7+ — Primary Model A/B Test

**Action:** A/B test `OPENROUTER_MODEL` default (Mistral Small vs. Kimi K2.6).

**Rollback trigger:** Heir satisfaction score drops below 4.0/5.

**Rollback action:** Revert `OPENROUTER_MODEL` env var to previous value.

**Monitoring:** Collect satisfaction scores via feedback UI. Check `/api/v1/status/rollback` for `rollback:satisfaction:superuser` and `rollback:satisfaction:user`.

## How to Execute a Rollback

All tier models are env-var driven. No code changes are required for rollback.

1. Edit `.env` (or deployment secrets):
   ```bash
   OPENROUTER_TIER_STANDARD=qwen/qwen3.5-plus-20260420
   ```

2. Restart the backend:
   ```bash
   docker compose restart backend
   ```

3. Verify in logs:
   ```
   INFO: OPENROUTER_TIER_STANDARD=qwen/qwen3.5-plus-20260420
   ```

4. Monitor the `/api/v1/status/rollback` endpoint for 30 minutes to confirm metrics normalize.

## Emergency Contacts

- **Deployment:** `scripts/deploy-production.sh`
- **Health checks:** `/api/v1/health`, `/api/v1/status/rollback`
- **Logs:** `logs/app/`, `logs/celery/`
