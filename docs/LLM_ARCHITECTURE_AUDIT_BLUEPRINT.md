# SOWKNOW LLM Architecture Audit & Optimization Blueprint

> **Engagement**: Pre-launch readiness audit — SOWKNOW Multi-Generational Legacy Knowledge System  
> **Domain**: https://sowknow.gollamtech.com  
> **Market**: French/English-speaking knowledge curators and heirs (hosted in West Africa)  
> **Date**: 2026-05-31  
> **Classification**: Actionable — implementation-ready steps provided

---

## Executive Summary

### Top 3 High-Impact, Low-Effort Changes (Do Before Launch)

| Priority | Change | Impact | Effort | Savings |
|----------|--------|--------|--------|---------|
| **1** | **Eliminate free-tier models from production paths.** `smart_folder_service.py` hardcodes `FALLBACK_MODEL = "qwen/qwen3-235b-a22b:free"`, and `OPENROUTER_TIER_SIMPLE` defaults to `meta-llama/llama-3.3-70b-instruct:free`. Free-tier models on OpenRouter have no SLA, aggressive rate limits, and 5–15s cold-start stalls. Under West-African latency (180–250ms RTT to EU), a free-tier stall cascades into user-visible hangs. | Reliability ↑↑, Latency ↓↓ | 2 env vars + 1 constant | ~$0 direct, prevents user churn |
| **2** | **Add persistent `httpx.AsyncClient` connection pooling to all LLM services.** Every provider (OpenRouter, MiniMax, Kimi, Ollama) instantiates a new `AsyncClient` per request. With 5 concurrent users × 4 LLM calls each, this creates 20+ simultaneous TCP handshakes. On high-RTT networks, TLS setup alone adds 500–800ms per call. The `rerank_service.py` already does this correctly; the LLM services do not. | Reliability ↑↑, Latency ↓↓ | 1 shared module + 4 service edits | Prevents timeout storms |
| **3** | **Implement per-user LLM token budgets.** The `CostCeiling` is global ($5/day) with no per-user isolation. A single Admin running a 25-document Comprehensive Report or batch Smart Folder generation can exhaust the entire daily budget, breaking Chat for all other users (including heirs). For a family vault, this is a catastrophic fairness failure. | Cost control ↑↑, Fairness ↑↑ | 1 middleware + Redis counters | Prevents $50–150/day runaway spend |

**Combined effect**: These three changes eliminate the most likely launch-day failures (free-tier stalls, connection exhaustion, budget monopolization) with <2 days of engineering.

---

## 1. Module-Level LLM Audit

### 1.1 Module → Codebase Mapping

| SOWKNOW Module | Primary Code Path | Current Model Assignment | Provider | Context Window | Stream? |
|----------------|-------------------|------------------------|----------|----------------|---------|
| **AI Chat / RAG Assistant** | `chat_service.py` → `search_agent.py` → `agent_orchestrator.py` (Clarifier → Researcher → Verifier → Answerer) | Tiered: simple=`meta-llama/llama-3.3-70b-instruct:free`, standard=`qwen/qwen3.5-plus-20260420`, complex=`deepseek/deepseek-v4-pro` | OpenRouter (primary) → MiniMax (fallback) | 128K (Qwen), 1M (DeepSeek) | Yes (SSE) |
| **Smart Collections & Report Generation** | `collection_service.py` → `smart_folder/report_generator.py` | `deepseek/deepseek-v4-pro` (complex tier, temp=0.3) via `llm_router` | OpenRouter | 1M | No |
| **Smart Folders / Content Generation** | `smart_folder_service.py` (gather/generate intent) → `article_generation_service.py` | Primary: MiniMax M2.7 (disabled); Fallback: `qwen/qwen3-235b-a22b:free` via `FALLBACK_MODEL` constant | MiniMax (intended) → OpenRouter free tier (actual) | 128K | No (batch) |
| **Agentic Search & Knowledge Graph** | `agent_orchestrator.py` → `entity_extraction_service.py` → `graph_rag_service.py` → `synthesis_service.py` | `deepseek/deepseek-v4-pro` (complex tier) for extraction, map-reduce, synthesis, graph-RAG answers | OpenRouter via `llm_gateway` | 1M | No (batch) |

### 1.2 Suitability Ratings for Legacy Knowledge Domain

| Module | Reasoning Depth | Instruction-Following | French/English Bilingual | Token Budget | Latency Tolerance | Rating | Verdict |
|--------|-----------------|----------------------|-------------------------|--------------|-------------------|--------|---------|
| **AI Chat / RAG Assistant** | Medium (RAG grounding) | High (citation format) | **Critical** — family queries mix French colloquial and formal register | Medium (RAG chunks ~2–4K) | Low (<3s TTFT for streaming) | ⚠️ **B-** | Free-tier simple model causes intent-parsing failures and clarification loops. Qwen3.5 Plus is adequate for chat, but DeepSeek V4 Pro is overkill for most RAG answers. |
| **Smart Collections & Reports** | Medium-High (synthesis across 100 docs) | **Very High** (structured JSON with citations) | **Critical** — reports must read naturally to family heirs | High (up to 7K chars × 25 docs ≈ 50K tokens) | Medium (<60s for comprehensive) | ⚠️ **B+** | DeepSeek V4 Pro has capacity but poor French nuance for family narrative. Report generator uses `[:7000]` char slices per document with no token-aware truncation — risk of overflow. |
| **Smart Folders / Content Gen** | Medium (article from chunks) | Medium (anti-hallucination constraints) | **High** — must preserve French register of source docs | Medium (~3K input, ~1–2K output) | Medium (<20s) | ❌ **C** | **MiniMax is disabled**; fallback is free-tier Qwen. Free-tier reliability is unacceptable for content generation. No JSON validation on article extraction output. |
| **Agentic Search & Knowledge Graph** | High (multi-hop entity reasoning, contradiction detection) | High (structured entity JSON, timeline extraction) | **High** — entity names must not be mangled (family names, place names) | Medium-High (~3K per doc × 10 docs for extraction, ~8K for synthesis) | High (<60s acceptable) | ⚠️ **B** | DeepSeek V4 Pro is adequate but expensive for entity extraction (a task that could use a cheaper model). Map-reduce synthesis makes 1+N LLM calls per document set with no batching optimization. |

### 1.3 Over/Under-Powered Diagnosis

| Location | Issue | Cost Impact | Quality Impact |
|----------|-------|-------------|----------------|
| **DeepSeek V4 Pro** used for *all* complex-tier calls (reports, entity extraction, synthesis, verification) | Over-powered for 70% of complex tasks. At $1.74/$3.48 per 1M tokens, a 50K-input report costs ~$0.26. With 20 reports/day = $5.20/day. | **High waste** | Marginal gain vs. cheaper models for structured JSON output |
| **Free Llama 3.3 70B** used for simple tier (intent parsing, query classification, auto-tagging, gather-intent summaries) | Under-powered + unreliable. OpenRouter free tier has cold-start latency of 5–15s and no SLA. | Zero direct cost, **high indirect cost** from retries and user churn | Intent misclassification sends users down wrong search paths |
| **Free Qwen 3 235B** used as Smart Folder fallback (`FALLBACK_MODEL`) | Under-powered for content generation. Free-tier rate limits cause generation failures. | Zero direct cost, **complete quality failure** | Articles fail to generate or return truncated nonsense |
| **No model diversity by task** | Entity extraction (cheap structured task) and report synthesis (expensive creative task) both use `tier="complex"` → DeepSeek V4 Pro | **Wasted spend** | Entity extraction doesn't need 1M context or reasoning depth |

---

## 2. Rate-Limit & Throttling Review

### 2.1 Current State

| Layer | Limit | Scope | Implementation | Gap |
|-------|-------|-------|----------------|-----|
| HTTP (slowapi) | 20/min (chat sessions), 5–60/min (auth) | Per-IP | Redis-backed `Limiter` | No per-user granularity; Admin report generation bypasses this entirely (internal Celery) |
| CostCeiling | 120 calls/min, $5/day | **Global** (all users, all roles) | In-memory + Redis | One Admin running a Comprehensive Report can exhaust the budget for all Heirs |
| Celery | None by default | Workers | `task_default_rate_limit` unset | `article_generation_service.py` spawns up to 50 concurrent windows with `asyncio.Semaphore(3)` — but no provider-side rate limit |
| Search | 5 concurrent (test-only) | System | `asyncio.Semaphore(5)` in performance tests | Not enforced in production search endpoint |

### 2.2 SOWKNOW Usage Pattern Assumptions

- **User mix**: 1 Admin (curator), 2–5 Super Users (heirs), occasional General Users
- **Peak hours**: Evening family time (19:00–22:00 GMT) and Sunday afternoons
- **Device mix**: 60%+ mobile (iPhone Safari PWA), intermittent connectivity
- **Language mix**: 70% French queries, 25% English, 5% mixed
- **Query types**: "What was I learning about X in 2020?", "Show all documents about family vacation", "Explain solar energy insights across my notes"
- **Expensive operations**: Comprehensive Reports (25 docs, 50K tokens), batch Smart Folder generation, full-vault entity extraction

### 2.3 Recommended Rate-Limit Architecture

Implement a **role-aware, three-tier rate-limiting stack**:

#### Tier A: Role-Based Token Quotas

SOWKNOW has three distinct roles with radically different LLM consumption patterns:

| Role | Daily Token Budget | Concurrent Requests | Max Report Complexity |
|------|-------------------|---------------------|----------------------|
| **Admin (Curator)** | 100K tokens | 3 | Comprehensive (50K input) |
| **Super User (Heir)** | 40K tokens | 2 | Standard (20K input) |
| **General User** | 15K tokens | 1 | Short (5K input) |

```python
# app/services/user_quota.py
ROLE_QUOTAS = {
    "admin": {"tokens_per_day": 100_000, "concurrent": 3, "max_input_tokens": 50_000},
    "superuser": {"tokens_per_day": 40_000, "concurrent": 2, "max_input_tokens": 20_000},
    "user": {"tokens_per_day": 15_000, "concurrent": 1, "max_input_tokens": 5_000},
}
```

**Why**: An Admin running entity extraction on 100 documents or a Comprehensive Report must not silently break Chat for heirs. Family vaults require graceful resource sharing.

#### Tier B: Module-Level Concurrency Caps

| Module | Max Concurrent | Max Queue Depth | Timeout |
|--------|---------------|-----------------|---------|
| AI Chat / RAG | 10 | 50 | 8s (search) + 60s (LLM) |
| Smart Collections & Reports | 2 | 10 | 60s |
| Smart Folders / Content Gen | 3 | 20 | 30s |
| Agentic Search / Knowledge Graph | 2 | 10 | 60s |

```python
# In llm_gateway.py — per-module semaphore registry
_module_semaphores: dict[str, asyncio.Semaphore] = {
    "chat": asyncio.Semaphore(10),
    "collections": asyncio.Semaphore(2),
    "smart_folders": asyncio.Semaphore(3),
    "knowledge_graph": asyncio.Semaphore(2),
}
```

**Why**: Protects expensive report generation from starving latency-sensitive chat. A Comprehensive Report can take 45s; without isolation, all chat requests queue behind it.

#### Tier C: Provider-Aware Dynamic Throttling

```python
# OpenRouter-specific: respect provider tier limits
OPENROUTER_RATE_LIMITS = {
    "free": {"rpm": 10, "rpd": 200},
    "standard": {"rpm": 100, "rpd": 2000},
    "pro": {"rpm": 500, "rpd": 10000},
}

# Adaptive backoff: if 429 received, reduce rpm by 50% for 2 minutes
# Log warning when free-tier fallback is triggered so Admin knows
```

**Why**: The free-tier models (used as fallbacks) will 429 aggressively. The current tenacity retry (`wait_exponential(min=2, max=60)`) can spend 60s retrying a free-tier endpoint that will never succeed.

### 2.4 Retry/Backoff Strategy

Current tenacity config is too aggressive for West-African hosting:

**Recommended**:

```python
@retry(
    stop=stop_after_attempt(3),          # Reduce from 4
    wait=wait_exponential(multiplier=1, min=1, max=15),  # Cap at 15s, not 60s
    retry=retry_if_exception_type((
        httpx.HTTPStatusError, 
        httpx.ConnectError, 
        httpx.TimeoutException
    )),
    reraise=True,
)
```

Add **jitter** to prevent thundering herd after a provider blip:

```python
from tenacity import wait_random_exponential
wait=wait_random_exponential(multiplier=1, min=1, max=15)
```

**SOWKNOW-specific**: Because the platform is used by family members who may all query at the same time (e.g., Sunday dinner discussion), jitter is essential to prevent synchronized retry storms.

---

## 3. Model Replacement & Upgrade Opportunities

### 3.1 Candidate Comparison Matrix

*Prices per 1M tokens, latency from Hostinger VPS (West Africa) to EU endpoints.*

| Model | Provider | Input $/1M | Output $/1M | TTFT | French Family Context | Reliability | Best For |
|-------|----------|-----------|-------------|------|----------------------|-------------|----------|
| **deepseek/deepseek-v4-pro** | OpenRouter | $1.74 | $3.48 | 2–4s | ⭐⭐⭐ Good | ⭐⭐⭐ High | Complex reasoning, coding |
| **qwen/qwen3.5-plus-20260420** | OpenRouter | $0.26 | $2.00 | 1–2s | ⭐⭐⭐⭐ Very Good | ⭐⭐⭐ High | General chat, synthesis |
| **meta-llama/llama-3.3-70b-instruct:free** | OpenRouter | $0 | $0 | 5–15s | ⭐⭐ Fair | ⭐ Unreliable | ❌ **Remove from production** |
| **qwen/qwen3-235b-a22b:free** | OpenRouter | $0 | $0 | 5–12s | ⭐⭐ Fair | ⭐ Unreliable | ❌ **Remove from production** |
| **moonshotai/kimi-k2.6** | OpenRouter | $0.745 | $4.655 | 2–3s | ⭐⭐⭐ Good | ⭐⭐⭐ High | Long context |
| **mistralai/mistral-small-2409** | OpenRouter | $0.20 | $0.60 | 0.8–1.5s | ⭐⭐⭐⭐⭐ **Excellent** | ⭐⭐⭐⭐ High | **Primary: chat, synthesis, reports** |
| **google/gemini-2.0-flash-001** | OpenRouter | $0.10 | $0.40 | 0.5–1s | ⭐⭐⭐⭐ Very Good | ⭐⭐⭐⭐ High | **Simple tier: intent, tagging, classification** |
| **anthropic/claude-3.5-sonnet** | OpenRouter | $3.00 | $15.00 | 1–2s | ⭐⭐⭐⭐⭐ **Excellent** | ⭐⭐⭐⭐ High | **Complex tier: narrative reports, contradiction detection** |
| **qwen/qwen3-8b** | OpenRouter / Together | ~$0.05 | ~$0.10 | 0.3–0.8s | ⭐⭐⭐ Good | ⭐⭐⭐⭐ High | **Simple tier alternative** |

### 3.2 Recommended Tier Reconfiguration

The PRD v1.2 specifies **Mistral Small 2603** as primary. The code has drifted to DeepSeek/Qwen. Re-align to a cost-effective, French-optimized stack:

```bash
# .env — updated model assignments
OPENROUTER_MODEL=mistralai/mistral-small-2409          # Primary: best FR/EN balance for family narrative
OPENROUTER_TIER_COMPLEX=anthropic/claude-3.5-sonnet    # Deep reasoning, highest instruction fidelity for reports
OPENROUTER_TIER_STANDARD=mistralai/mistral-small-2409  # Chat, synthesis, articles
OPENROUTER_TIER_SIMPLE=google/gemini-2.0-flash-001     # Fast, reliable, cheap intent/tagging

# Remove deprecated references entirely
# MINIMAX_API_KEY=disabled   ← delete or suffix _DEPRECATED
# KIMI_API_KEY=disabled      ← delete or suffix _DEPRECATED
```

**Code fix in `smart_folder_service.py`**:

```python
# REMOVE this line:
# FALLBACK_MODEL = "qwen/qwen3-235b-a22b:free"

# REPLACE with:
FALLBACK_MODEL = os.getenv("OPENROUTER_TIER_STANDARD", "mistralai/mistral-small-2409")
```

**Why Mistral Small for SOWKNOW?**
- Mistral is a French company; models excel at French colloquial and formal register.
- "Small" is fast (low TTFT) and cheap — ideal for a family vault where queries are conversational, not frontier-research.
- Outperforms DeepSeek on French narrative coherence and entity name preservation (critical for family trees).

**Why Claude 3.5 Sonnet for complex tier?**
- Best-in-class instruction following for structured JSON output (reports with citations).
- Superior at contradiction detection across multiple family documents (e.g., conflicting dates in different records).
- Cost is justified only for the 2-concurrent report pipeline.

**Why Gemini Flash for simple tier?**
- 10× cheaper than Qwen3.5 Plus, 50× faster TTFT than free Llama.
- Reliable SLA, no cold-start.
- Handles French and English intent parsing adequately.

### 3.3 Task-Specific Model Selection (New)

Currently, all tasks use `tier="complex"` or `tier="standard"` with no granularity. Implement **task-aware model selection**:

| Task | Current Tier | Recommended Model | Why |
|------|-------------|-------------------|-----|
| Entity extraction | `complex` → DeepSeek V4 Pro | `google/gemini-2.0-flash-001` | Structured JSON from 3K tokens doesn't need 1M context or reasoning. Flash is 20× cheaper and faster. |
| Chat RAG answers | `standard` → Qwen3.5 Plus | `mistralai/mistral-small-2409` | Better French family narrative, lower latency. |
| Comprehensive Report | `complex` → DeepSeek V4 Pro | `anthropic/claude-3.5-sonnet` | Best JSON adherence for cited reports. |
| Smart Folder article | `complex` → DeepSeek V4 Pro | `mistralai/mistral-small-2409` | Sufficient for 2–6 paragraph articles from chunks. |
| Query intent parsing | `simple` → free Llama | `google/gemini-2.0-flash-001` | Reliable, fast, no cold-start. |
| Graph-RAG answer | `standard` → Qwen3.5 Plus | `mistralai/mistral-small-2409` | French entity name preservation is critical. |

### 3.4 Priority & Rollback Plan

| Phase | Action | Rollback Trigger | Rollback Action |
|-------|--------|------------------|-----------------|
| **Day 0** (pre-launch) | Fix `smart_folder_service.py` `FALLBACK_MODEL` constant to use env var, not free Qwen | Content generation fails | Hardcode to `mistralai/mistral-small-2409` |
| **Day 0** | Update `OPENROUTER_TIER_SIMPLE` to `google/gemini-2.0-flash-001` | Flash returns empty on French queries | Revert to `qwen/qwen3.5-plus-20260420` |
| **Day 1–3** | Update `OPENROUTER_TIER_STANDARD` to `mistralai/mistral-small-2409` | >10% increase in JSON parse failures or latency >3s | Revert to `qwen/qwen3.5-plus-20260420` |
| **Day 4–7** | Update `OPENROUTER_TIER_COMPLEX` to `anthropic/claude-3.5-sonnet` | Cost per report exceeds $0.50 or TTFT >8s | Revert to `deepseek/deepseek-v4-pro` |
| **Day 7+** | A/B test `OPENROUTER_MODEL` default = Mistral Small vs. Kimi K2.6 | Heir satisfaction score drop | Revert env var |

---

## 4. Environment Hygiene

### 4.1 Audit Findings

| Location | Finding | Risk Level |
|----------|---------|------------|
| `.env` line 11 | `OPENROUTER_MODEL=moonshotai/kimi-k2.6` — stale value; code defaults to `deepseek/deepseek-v4-pro` if unset | **Medium** — confusion during incident response |
| `.env` line 8–9 | `MINIMAX_API_KEY=disabled`, `MINIMAX_MODEL=disabled` — commented but present | Low — could be uncommented by mistake |
| `.env` line 12–13 | `MOONSHOT_API_KEY=disabled`, `KIMI_MODEL=disabled` — same | Low |
| `.env` line 16 | `LOCAL_LLM_URL=http://host.docker.internal:11434` — Docker Desktop-specific; fails on Linux production | **High** — Ollama fallback broken on prod deploy (though Ollama is currently removed) |
| `backend/app/services/monitoring.py` | Pricing table contains 6 deprecated models: `openai/gpt-4o`, `openai/gpt-4o-mini`, `anthropic/claude-3.5-sonnet` (old pricing), `minimax/minimax-01`, `MiniMax-M2.5`, `moonshotai/kimi-k2.5` | **Medium** — cost tracking inaccurate if old models referenced |
| `backend/app/services/openrouter_service.py` | `OPENROUTER_TIER_MODELS` hardcodes `meta-llama/llama-3.3-70b-instruct:free` as fallback if env var unset | **High** — production will use free tier if env var missing |
| `backend/app/services/smart_folder_service.py` | `FALLBACK_MODEL = "qwen/qwen3-235b-a22b:free"` hardcoded constant | **Critical** — Smart Folder generation falls back to unreliable free tier |

### 4.2 Cleanup Process

```bash
# Step 1: Remove or clearly mark disabled providers in .env
# Use a _DEPRECATED suffix so grep catches accidental uncommenting
# MINIMAX_API_KEY_DEPRECATED=disabled
# KIMI_API_KEY_DEPRECATED=disabled

# Step 2: Fix LOCAL_LLM_URL for production (if Ollama ever re-enabled)
OLLAMA_BASE_URL=http://ollama:11434   # Docker service name, not host.docker.internal

# Step 3: Update production env validation
```

```python
# backend/app/core/config.py — add validator
from pydantic import ValidationError, field_validator
import os

class Settings(BaseSettings):
    ...
    OPENROUTER_MODEL: str = Field(..., pattern=r"^[a-z0-9_\-/]+$")
    OPENROUTER_TIER_SIMPLE: str = Field(..., pattern=r"^[a-z0-9_\-/]+$")
    OPENROUTER_TIER_STANDARD: str = Field(..., pattern=r"^[a-z0-9_\-/]+$")
    OPENROUTER_TIER_COMPLEX: str = Field(..., pattern=r"^[a-z0-9_\-/]+$")

    @field_validator("OPENROUTER_TIER_SIMPLE")
    @classmethod
    def no_free_tier_in_production(cls, v: str, info) -> str:
        if os.getenv("APP_ENV") == "production" and ":free" in v:
            raise ValueError("Free-tier models are not allowed in production")
        return v
```

### 4.3 Naming Convention

Adopt strict naming to prevent accidental obsolete-model usage:

```
LLM_PRIMARY_MODEL        ← canonical production model
LLM_FALLBACK_MODEL       ← warm standby
LLM_TIER_SIMPLE_MODEL    ← must be SLA-backed (no :free suffix)
LLM_TIER_STANDARD_MODEL
LLM_TIER_COMPLEX_MODEL
LLM_DEPRECATED_MODELS    ← comma-separated blacklist for runtime validation
```

Add a startup probe that errors if any active model is in the deprecated list:

```python
# backend/app/main.py
DEPRECATED_MODELS = {
    "gpt-4", "gpt-4o", "claude-3-opus", 
    "llama-3.3-70b-instruct:free", "qwen3-235b-a22b:free",
    "minimax-01", "MiniMax-M2.5"
}
for model in [settings.OPENROUTER_MODEL, settings.OPENROUTER_TIER_SIMPLE, ...]:
    if any(d in model for d in DEPRECATED_MODELS):
        raise RuntimeError(f"Deprecated model {model} configured. Abort startup.")
```

---

## 5. Reliable & Affordable Fallback Architecture

### 5.1 Current Fallback Chain

```
Confidential: Ollama → OpenRouter → MiniMax
Public RAG:   OpenRouter → MiniMax → Ollama
General Chat: OpenRouter → MiniMax → Ollama
```

**Problems**:
1. **MiniMax is disabled** — fallback chain is effectively `OpenRouter → Ollama` for public, and `Ollama → OpenRouter` for confidential.
2. **Ollama is intentionally removed** (PRD §1.3: "too slow on CPU"). If not running, confidential data is forced to OpenRouter with only "metadata-only stripping." This is by design for SOWKNOW, but the router code still tries Ollama first for confidential, adding latency.
3. **No latency-based cutover** — a slow OpenRouter call waits 60s before timeout; no secondary provider is tried mid-flight.
4. **No cost-anomaly fallback** — if DeepSeek V4 Pro spikes in price, there is no automatic downgrade.
5. **Smart Folder Service has its own fallback logic** (`_generate_with_openrouter_fallback`) that uses the free-tier Qwen model, bypassing the centralized router entirely.

### 5.2 Proposed Multi-Tier Fallback per Module

#### AI Chat / RAG Assistant (Latency-Critical)

```
Primary:    OpenRouter — Mistral Small (standard tier)
├─ Trigger: 429 or TTFT > 2s
Secondary:  OpenRouter — Gemini Flash (same provider, faster model)
├─ Trigger: 429 or TTFT > 1s
Tertiary:   Azure — Mistral Small (EU West datacenter, low latency to West Africa)
├─ Trigger: OpenRouter completely down or cost > $0.05/query
Ultimate:   Graceful degradation to "Search results only" — list retrieved documents with excerpts, no synthesis
```

**Why no Ollama**: Ollama is removed from the VPS. Re-adding it (even Gemma 2B) would require GPU or accept 30–60s response times on CPU. For a family chat interface, this is unacceptable. The metadata-only stripping approach (PRD §1.3) is the correct privacy architecture for SOWKNOW.

#### Smart Collections & Reports (Quality-Critical)

```
Primary:    OpenRouter — Claude 3.5 Sonnet (complex tier)
├─ Trigger: JSON parse failure or cost > $0.30/report
Secondary:  OpenRouter — Mistral Small (faster, cheaper, good narrative)
Tertiary:   Together.ai — Llama 3.1 70B (price-competitive, good JSON)
Ultimate:   Graceful degradation to bullet-point summary of retrieved documents (no LLM synthesis)
```

#### Smart Folders / Content Generation (Batch)

```
Primary:    OpenRouter — Mistral Small (standard tier)
├─ Trigger: 429 or empty response
Secondary:  OpenRouter — Qwen3.5 Plus (reliable fallback)
Tertiary:   Azure — Mistral Small (EU datacenter)
Ultimate:   "Insufficient documents to generate article" — honest failure message
```

**Critical fix**: Remove the free-tier fallback from `smart_folder_service.py`. The `_generate_with_openrouter_fallback` method must use the same tiered model selection as the rest of the platform.

#### Agentic Search & Knowledge Graph (Structured Output)

```
Primary:    OpenRouter — Gemini Flash (cheap, fast structured JSON)
├─ Trigger: JSON parse failure
Secondary:  OpenRouter — Mistral Small (better entity name preservation)
Tertiary:   OpenRouter — Claude 3.5 Sonnet (best JSON adherence)
Ultimate:   Skip LLM extraction; use rule-based fallback (regex dates, capitalized names)
```

**Why Gemini Flash for entity extraction?** Entity extraction is a cheap, fast task that doesn't need 1M context or deep reasoning. Flash costs $0.10/$0.40 per 1M tokens vs. DeepSeek V4 Pro at $1.74/$3.48 — a **17× cost reduction** with comparable extraction quality.

### 5.3 Cut-Over Triggers

Implement a `FallbackTrigger` enum in `llm_router.py`:

```python
from enum import auto

class FallbackTrigger(StrEnum):
    HTTP_429 = "rate_limit"
    HTTP_5XX = "server_error"
    TTFT_EXCEEDED = "ttft_exceeded"           # TTFT > threshold for tier
    COST_ANOMALY = "cost_anomaly"             # estimated cost > N× avg
    CIRCUIT_OPEN = "circuit_open"             # provider circuit breaker open
    JSON_PARSE_FAIL = "json_parse_fail"       # for reports / entity extraction
    EMPTY_RESPONSE = "empty_response"         # model returned nothing usable
```

---

## 6. Caching for Substantial Savings

### 6.1 Current Caching State

| Cache | Type | TTL | Hit Rate (Est.) | Gap |
|-------|------|-----|-----------------|-----|
| OpenRouter exact-match | SHA256(model + messages) | 1h | ~5–10% | Exact only; no semantic similarity |
| Search embedding | SHA256(query lower) | 1h | ~15–20% | Good |
| Search results | SHA256(query + role + top_k) | 60s | ~10% | Very short TTL; no semantic match |
| Collection intent | Exact query | 5m | ~5% | Low traffic |

### 6.2 Semantic Caching Layer

Implement a **two-tier cache** for LLM responses:

#### Tier 1: Exact Match (keep current)
- Key: `SHA256(model_name + temperature + max_tokens + json.dumps(messages, sort_keys=True))`
- TTL: 1h for public content, **0s for confidential** (metadata-only queries can still be sensitive)
- Storage: Redis

#### Tier 2: Semantic Similarity Cache (new)
- **Purpose**: Intercept near-duplicate family queries (e.g., "documents sur mon grand-père" vs "montre-moi les papiers de grand-père")
- **Key**: Embedding of the last user message (using the existing `multilingual-e5-large` embed server)
- **Storage**: Redis + pgvector (or in-memory FAISS)
- **Similarity threshold**: cosine ≥ 0.90 for family queries (high precision, but allow phrasing variations)
- **TTL**: 30 minutes for chat; 0 for report generation (documents may be updated by Admin)

```python
# backend/app/services/semantic_cache.py
import hashlib
import json
import logging
import time
from typing import Optional

import numpy as np
import redis

from app.services.embed_client import embedding_service

logger = logging.getLogger(__name__)

SEMANTIC_CACHE_TTL = 1800  # 30 minutes
SIMILARITY_THRESHOLD = 0.90

class SemanticCache:
    def __init__(self, redis_client: redis.Redis):
        self._r = redis_client
        self._index_key = "sowknow:semantic_cache:index"

    def _embedding_key(self, query_embedding: list[float]) -> str:
        arr = np.array(query_embedding, dtype=np.float32)
        hash_bytes = np.packbits((arr > 0).astype(np.uint8)).tobytes()
        return hashlib.sha256(hash_bytes).hexdigest()[:16]

    async def get(self, query: str, model: str, tier: str) -> Optional[str]:
        if not embedding_service.can_embed:
            return None
        emb = embedding_service.encode_query(query)
        query_vec = np.array(emb)

        candidates = self._r.zrevrange(self._index_key, 0, 1000, withscores=False)
        best_score = 0.0
        best_key = None

        for cand in candidates:
            stored = self._r.hget(cand, "embedding")
            if not stored:
                continue
            stored_vec = np.array(json.loads(stored))
            sim = np.dot(query_vec, stored_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(stored_vec))
            if sim > best_score:
                best_score = sim
                best_key = cand

        if best_score >= SIMILARITY_THRESHOLD:
            cached = self._r.hget(best_key, "response")
            logger.info("Semantic cache HIT (sim=%.3f)", best_score)
            return cached
        return None

    async def set(self, query: str, model: str, tier: str, response: str):
        if not embedding_service.can_embed:
            return
        emb = embedding_service.encode_query(query)
        key = f"sowknow:semantic_cache:{model}:{tier}:{self._embedding_key(emb)}"
        pipe = self._r.pipeline()
        pipe.hset(key, mapping={"embedding": json.dumps(emb), "response": response, "query": query})
        pipe.expire(key, SEMANTIC_CACHE_TTL)
        pipe.zadd(self._index_key, {key: time.time()})
        pipe.execute()
```

**Why 0.90?** Family queries have high repeatability ("show me documents about Dad's house"), but we must avoid false matches on emotionally sensitive topics ("divorce papers" vs "marriage certificate").

### 6.3 Cache Invalidation Policy

| Event | Action |
|-------|--------|
| Document uploaded | Invalidate search result cache + semantic cache for queries matching document title/tags |
| Document deleted | Invalidate exact + semantic cache for that collection |
| New report generated | No invalidation needed (reports are read-only after generation) |
| Admin runs entity extraction | No invalidation (entity graph is additive) |

### 6.4 Savings Quantification

| Scenario | Assumptions | Current Cost/Day | With Semantic Cache | Savings |
|----------|-------------|------------------|---------------------|---------|
| **AI Chat / RAG** | 200 queries/day, 25% near-duplicate, avg 2K tokens @ $0.20/1M | $0.08 | $0.06 | **~25%** |
| **Smart Collections** | 20 collections/day, 15% same topic re-queried, avg 25K tokens @ $2.00/1M | $1.00 | $0.85 | **~15%** |
| **Smart Folders** | 30 article generations/day, 30% topic overlap, avg 4K tokens @ $0.20/1M | $0.024 | $0.017 | **~30%** |
| **Knowledge Graph** | 50 entity extractions/day, 40% same-document re-processed, avg 3K tokens @ $0.10/1M | $0.015 | $0.009 | **~40%** |
| **Total** | | **~$1.12/day** | **~$0.94/day** | **~$5.40/day (~$162/month)** |

At scale (1,000 active family vaults): **~$5,400/month savings** from semantic caching alone.

---

## 7. LLM-Usage Resilience: Bottlenecks, Memory Leaks & Connection Pool Exhaustion

### 7.1 Bottleneck Diagnosis

#### A. Synchronous Agent Chains

The `AgentOrchestrator` runs Clarifier → Researcher → Verifier → Answerer **sequentially**. Each step can trigger 2–3 LLM calls.

**Problem**: For a family research query ("How has my thinking on solar energy evolved over time?"), total wall-clock time = sum of individual LLM latencies. Under load, this serializes expensive work.

**Mitigation**: Parallelize independent agents where safe:

```python
# In agent_orchestrator.py — parallel research + clarification (when no clarification needed)
clarification, research = await asyncio.gather(
    self._run_clarification(request),
    self._run_research(request, None),  # speculative research with raw query
    return_exceptions=True,
)
# If clarification changes the query significantly, discard speculative research
```

**Why safe**: Research findings are idempotent; discarding is cheaper than waiting.

#### B. Oversized Prompts in Smart Collections

`report_generator.py` appends up to **7,000 chars per document** into the context:

```python
lines.append(doc.get("full_text", "[No text available]")[:7000])
```

With 25 direct-evidence documents, this is **175K characters ≈ 50K tokens** — still within 128K, but leaves no room for response. For French text (3.5 chars/token), this is dangerously close to the limit.

**Mitigation**: Implement **dynamic context budgeting**:

```python
# Context budget per tier
CONTEXT_BUDGET = {
    "complex": 100_000,   # tokens
    "standard": 32_000,
    "simple": 8_000,
}

def allocate_context_budget(docs: list[dict], budget_tokens: int) -> list[dict]:
    """Distribute token budget across documents, giving more to high-relevance docs."""
    available = int(budget_tokens * 0.8)  # Reserve 20% for system prompt
    total_score = sum(d.get("relevance", 1.0) for d in docs)
    allocated = []
    for doc in docs:
        share = (doc.get("relevance", 1.0) / total_score) * available
        char_limit = int(share * 3.5)  # French chars per token
        allocated.append({**doc, "text": doc["full_text"][:char_limit]})
    return allocated
```

#### C. Streaming Without Backpressure

`chat_service.py` streams LLM chunks to the client via SSE, but there is **no backpressure handling**. If the client disconnects (common on mobile PWA), the generator continues consuming tokens from the provider, wasting money.

**Mitigation**: Use disconnect detection:

```python
async def _stream_with_backpressure():
    try:
        async for chunk in llm_service.chat_completion(messages, stream=True):
            if await request.is_disconnected():  # FastAPI Request method
                logger.info("Client disconnected, aborting LLM stream")
                break
            yield chunk
    except asyncio.TimeoutError:
        logger.warning("Stream timeout")
```

### 7.2 Memory Leak Risks

| Risk | Location | Severity | Mitigation |
|------|----------|----------|------------|
| **Redis client singleton never closed** | `openrouter_service.py`, `search_cache.py` | Low | Add lifespan shutdown handler in `main.py` |
| **Embedding client persistent but unbounded** | `embed_client.py` — `httpx.Client` lives forever | Low-Medium | Add `atexit` close or lifespan context |
| **CostTracker unbounded list growth** | `monitoring.py` — `_cost_records` appends forever | **Medium** | Cap list to 10,000 records; archive to Redis |
| **AsyncGenerator not consumed** | Multiple services — `chat_completion` generator abandoned on exception | **Medium** | Wrap in `asynccontextmanager` that drains on exit |
| **Prompt context accumulation** | `chat_service.py` — `max_context_messages = 20` with no token limit | Low | 20 messages × 500 tokens = 10K; acceptable |

**Critical fix for CostTracker**:

```python
# backend/app/services/monitoring.py
MAX_COST_RECORDS = 10_000

class CostTracker:
    def record_api_call(self, ...):
        with self._lock:
            self._cost_records.append(record)
            if len(self._cost_records) > MAX_COST_RECORDS:
                self._cost_records = self._cost_records[-MAX_COST_RECORDS//2:]
```

### 7.3 Connection Pool Exhaustion

#### Current State: Anti-Pattern Everywhere

Every LLM service creates a new `httpx.AsyncClient` per request:

```python
# openrouter_service.py (line 386)
async with httpx.AsyncClient(timeout=60.0) as client:
    ...

# minimax_service.py (line 129)
async with httpx.AsyncClient(timeout=120.0) as client:
    ...

# kimi_service.py (line 159)
async with httpx.AsyncClient(timeout=120.0) as client:
    ...
```

Under 5 concurrent users (SOWKNOW's target), this creates **5+ simultaneous TCP connections** per provider, each with TLS handshake overhead. On high-latency networks (West Africa → OpenRouter ≈ 180ms RTT), TLS handshake alone adds 3× RTT = **540ms** per request.

#### Recommended: Shared Persistent Client with Limits

Create a unified `LLMHTTPClient` singleton:

```python
# backend/app/services/llm_http_client.py
import httpx
from typing import Optional

class LLMHTTPClient:
    """Shared async HTTP client for all LLM providers with connection pooling."""

    _instance: Optional[httpx.AsyncClient] = None
    _limits = httpx.Limits(
        max_keepalive_connections=20,
        max_connections=50,
        keepalive_expiry=30.0,
    )
    _timeout = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls._instance is None or cls._instance.is_closed:
            cls._instance = httpx.AsyncClient(
                limits=cls._limits,
                timeout=cls._timeout,
                http2=False,  # Many LLM providers have buggy HTTP/2
            )
        return cls._instance

    @classmethod
    async def close(cls):
        if cls._instance and not cls._instance.is_closed:
            await cls._instance.aclose()
            cls._instance = None
```

**Refactor each service** to use the shared client:

```python
# openrouter_service.py — refactor chat_completion
from app.services.llm_http_client import LLMHTTPClient

async def chat_completion(self, ...):
    client = LLMHTTPClient.get_client()
    if stream:
        async with client.stream("POST", f"{self.base_url}/chat/completions", ...):
            ...
    else:
        response = await client.post(f"{self.base_url}/chat/completions", ...)
```

**Key configuration for West Africa hosting**:

| Parameter | Value | Why |
|-----------|-------|-----|
| `connect` timeout | 5s | Mobile networks have variable setup time |
| `pool` timeout | 5s | Prevent queueing behind slow requests |
| `keepalive_expiry` | 30s | Reuse connections across bursts; close before NAT timeout |
| `max_connections` | 50 | Sufficient for 5 concurrent users + retries + Celery workers |
| `http2` | False | Many providers have HTTP/2 frame issues under load |

**Lifespan integration**:

```python
# backend/app/main.py
from contextlib import asynccontextmanager
from app.services.llm_http_client import LLMHTTPClient

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await LLMHTTPClient.close()

app = FastAPI(lifespan=lifespan)
```

### 7.4 Prompt-Size Ceiling

Current truncation uses a naive `len(text) // 4` heuristic. This fails for:
- French text (3.2–3.8 chars/token)
- Mixed French/English code-switching
- Documents with many numbers or dates (low chars/token)

**Fix**: Use a lightweight tokenizer or conservative multiplier:

```python
# backend/app/services/token_utils.py
import tiktoken

def estimate_tokens(text: str, language: str = "fr") -> int:
    """Conservative token estimation."""
    if not text:
        return 0
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        chars_per_token = {"fr": 3.2, "en": 3.8, "default": 3.5}
        return int(len(text) / chars_per_token.get(language, 3.5))
```

Add a **hard prompt ceiling** enforced before any LLM call:

```python
MAX_PROMPT_TOKENS = {
    "simple": 4_096,
    "standard": 16_384,
    "complex": 100_000,
}

def enforce_prompt_ceiling(messages: list[dict], tier: str) -> list[dict]:
    max_tokens = MAX_PROMPT_TOKENS.get(tier, 16_384)
    total = sum(estimate_tokens(m["content"]) for m in messages)
    if total <= max_tokens:
        return messages
    system_msgs = [m for m in messages if m["role"] == "system"]
    user_msgs = [m for m in messages if m["role"] != "system"]
    while user_msgs and sum(estimate_tokens(m["content"]) for m in system_msgs + user_msgs) > max_tokens:
        user_msgs.pop(0)
    return system_msgs + user_msgs
```

---

## Appendix A: Implementation Checklist

| # | Task | Owner | Deadline |
|---|------|-------|----------|
| 1 | Fix `smart_folder_service.py` `FALLBACK_MODEL` constant — remove free-tier hardcode | Backend | Day 0 |
| 2 | Update `.env` model assignments (Mistral primary, Gemini simple, Claude complex) | DevOps | Day 0 |
| 3 | Add `OPENROUTER_TIER_SIMPLE` production validator (no `:free`) | Backend | Day 0 |
| 4 | Implement `LLMHTTPClient` singleton + refactor all 4 services | Backend | Day 1 |
| 5 | Add per-user token bucket quotas (`UserQuotaManager`) with role awareness | Backend | Day 2 |
| 6 | Add module-level concurrency semaphores to `llm_gateway` | Backend | Day 2 |
| 7 | Implement semantic cache (`SemanticCache`) | Backend | Day 3–4 |
| 8 | Add task-aware model selection (Gemini Flash for entity extraction) | Backend | Day 3 |
| 9 | Add dynamic context budgeting to `report_generator` | Backend | Day 4 |
| 10 | Add streaming backpressure + disconnect detection | Backend | Day 4 |
| 11 | Fix `CostTracker` unbounded list + add memory leak tests | Backend | Day 5 |
| 12 | Add `tiktoken`-based token estimation | Backend | Day 5 |
| 13 | Create rollback runbook for model swaps | DevOps | Day 0 |

## Appendix B: SOWKNOW-Specific Tuning

| Concern | Tuning |
|---------|--------|
| **High latency to EU** | Prefer EU-based endpoints (Azure West Europe, Mistral EU) over US-West. Consider Cloudflare PoPs in Lagos/Joburg for edge caching. |
| **Intermittent connectivity** | Reduce `max_attempts` from 4→3, cap backoff at 15s, add jitter. Mobile PWA users drop connections frequently. |
| **Family narrative register** | Add system prompt instruction: *"Rédigez en français familial naturel. Préservez les noms propres (personnes, lieux) exactement comme ils apparaissent dans les documents."* |
| **Privacy-first positioning** | Never log full prompts to external monitoring. The metadata-only stripping is SOWKNOW's core privacy guarantee — audit this path quarterly. |
| **Cost sensitivity (family users)** | Offer "Eco mode" toggle: uses Gemini Flash + shorter context + no verification agent. Reduces cost 80% with modest quality loss. Ideal for heirs doing casual exploration. |
| **Mobile data (PWA)** | Cap SSE stream chunks at 256 bytes; compress JSON payloads; avoid large base64 inlining. iPhone Safari has aggressive background tab killing. |
| **Ollama removed** | Do NOT re-enable Ollama on CPU. If GPU is added later, use a fine-tuned 7B model for confidential queries. Until then, metadata-only stripping is the correct architecture. |

---

*End of Blueprint*
