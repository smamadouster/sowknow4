# LLM INTEGRATION LAYER - COMPREHENSIVE AUDIT REPORT

**Generated:** 2026-02-21  
**Scope:** LLM Router, Minimax/Moonshot, Ollama, Context Routing & Response Format  
**Status:** CRITICAL BLOCKERS IDENTIFIED

---

## EXECUTIVE SUMMARY

| Category | Status | Critical | High | Medium |
|----------|--------|----------|------|--------|
| LLM Router Structure | BLOCKED | 2 | 2 | 1 |
| Minimax/Moonshot | CRITICAL | 1 | 0 | 2 |
| Ollama Integration | WARNING | 1 | 1 | 0 |
| Context Routing | PASSING | 0 | 0 | 1 |

**VERDICT: NOT PRODUCTION READY** - Critical security and architectural issues must be resolved.

---

## AGENT 1: LLM ROUTER SERVICE STRUCTURE

### File Status
```
EXPECTED: backend/app/services/llm_router.py
ACTUAL: NOT FOUND
```

### CRITICAL FINDINGS

#### 1. Missing Dedicated Router File
**Severity:** CRITICAL  
**Impact:** LLM routing logic is scattered across multiple services

The expected centralized `llm_router.py` does not exist. Instead, routing logic is embedded inline in `chat_service.py`.

**Current Architecture:**
```
backend/app/services/
├── chat_service.py          [EMBEDDED ROUTING - Lines 327-376]
├── minimax_service.py       [Direct Minimax API]
├── openrouter_service.py    [OpenRouter Gateway]
├── ollama_service.py        [Local LLM]
├── kimi_service.py          [MISSING FILE - Referenced but not found]
└── pii_detection_service.py [PII Detection]
```

#### 2. Missing Required Methods

| Required Method | Status | Current Alternative |
|-----------------|--------|---------------------|
| `detect_context_sensitivity(chunks)` | NOT FOUND | `pii_detection_service.detect_pii()` (text-based) |
| `generate_completion(prompt, context_chunks, stream)` | NOT FOUND | `chat_service.generate_chat_response()` |
| `_generate_Minimax(prompt, chunks, stream)` | NOT FOUND | `minimax_service.chat_completion(messages, ...)` |
| `_generate_ollama(prompt, chunks, stream)` | NOT FOUND | `ollama_service.chat_completion(messages, ...)` |

**Signature Mismatch:**
```python
# REQUIRED:
generate_completion(prompt, context_chunks, stream)

# ACTUAL (minimax_service.py):
async def chat_completion(messages, stream, temperature, max_tokens, cache_key)
```

#### 3. Missing Kimi Service File
**Location:** `backend/app/services/kimi_service.py`  
**Status:** IMPORTED BUT FILE DOES NOT EXIST

```python
# chat_service.py:26-30
try:
    from app.services.kimi_service import kimi_service
except ImportError:
    kimi_service = None  # Always fails - file missing
```

**Impact:** Kimi LLM will never be available for general chat fallback.

#### 4. Enum Inconsistency
```python
# api/chat.py - LLMProvider enum:
class LLMProvider(str, enum.Enum):
    MINIMAX = "minimax"
    KIMI = "kimi"
    OLLAMA = "ollama"
    # OPENROUTER = MISSING

# chat_service.py:347 - Uses non-existent enum value:
llm_provider = LLMProvider.OPENROUTER  # AttributeError risk
```

---

## AGENT 2: MINIMAX/MOONSHOT INTEGRATION

### Implementation Status

| Component | Status | Details |
|-----------|--------|---------|
| Minimax API Client | IMPLEMENTED | Direct API via httpx.AsyncClient, 120s timeout |
| OpenRouter Gateway | IMPLEMENTED | Fallback API with minimax/minimax-01 model |
| Moonshot/Kimi API | BROKEN | Service file missing (kimi_service.py) |
| Environment Loading | IMPLEMENTED | os.getenv() pattern |
| Streaming (SSE) | IMPLEMENTED | `async for line in response.aiter_lines()` |
| Retry Logic | IMPLEMENTED | tenacity: 3 attempts, exponential backoff 2-10s |
| Circuit Breaker | IMPLEMENTED | network_utils.py: 5 failures / 60s recovery |
| Error Handling | IMPLEMENTED | HTTPStatusError, HTTPError catch + logging |

### CRITICAL SECURITY FINDING: EXPOSED API KEYS

**Severity:** CRITICAL  
**Location:** `.env` file (tracked in repository)

```
EXPOSED CREDENTIALS:
├── MINIMAX_API_KEY=sk-api-QF9ZIg-...   [LINE 11]
├── MOONSHOT_API_KEY=sk-kimi-NiqE...    [LINE 15]
├── OPENROUTER_API_KEY=sk-or-v1-1ba...  [LINE 19]
├── DATABASE_PASSWORD=your_secure_pass  [LINE 2]
├── JWT_SECRET=your-super-secret-key    [LINE 6]
└── TELEGRAM_BOT_TOKEN=...              [LINE 24]
```

**IMMEDIATE ACTIONS REQUIRED:**
1. **ROTATE ALL API KEYS** immediately
2. Remove `.env` from version control
3. Add `.env` to `.gitignore`
4. Use `.env.example` with placeholder values only

### Code Quality - Minimax Service

**Strengths:**
- Proper async implementation with httpx
- SSE streaming support
- Retry with exponential backoff
- Comprehensive error logging

**Streaming Implementation (minimax_service.py:102-120):**
```python
if stream:
    async with client.stream("POST", f"{self.base_url}/v1/text/chatcompletion_v2", ...) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.strip():
                data = json.loads(line)
                if "choices" in data and len(data["choices"]) > 0:
                    delta = data["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
```

---

## AGENT 3: OLLAMA INTEGRATION

### Configuration Status

| Setting | Expected | Actual | Status |
|---------|----------|--------|--------|
| URL Variable | LOCAL_LLM_URL | OLLAMA_BASE_URL + LOCAL_LLM_URL | INCONSISTENT |
| Default URL | localhost:11434 | ollama:11434 | DIFFERENT |
| Model | mistral:7b-instruct | mistral:7b-instruct | MATCH |
| Streaming | Required | Implemented | PASS |

### Environment Variable Inconsistency

```python
# ollama_service.py:18
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

# main_minimal.py:225
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434")
```

**Impact:** Docker networking vs localhost assumptions may cause connection failures.

### CRITICAL: NO FALLBACK FOR CONFIDENTIAL DOCUMENTS

**Severity:** CRITICAL  
**Location:** chat_service.py:334-338, collection_chat_service.py:210

```python
if has_confidential:
    # Confidential: always use Ollama
    llm_service = self.ollama_service
    llm_provider = LLMProvider.OLLAMA
    routing_reason = "confidential_docs"
    # NO ELSE/FALLBACK - If Ollama unavailable, error returned
```

**Impact:** 
- If Ollama service is down, confidential document queries receive only an error message
- No alternative processing path exists by design (privacy requirement)
- No queue/retry mechanism for temporarily unavailable scenarios

**Error Response When Unavailable:**
```python
return {
    "response": "I'm sorry, I couldn't process your question. The local LLM may be unavailable.",
    "sources": [],
    "llm_used": "ollama",
}
```

### Fallback Chain for Public Documents (Working)

```
Public Docs → MiniMax → OpenRouter → Ollama
General Chat → Kimi → MiniMax → OpenRouter → Ollama
```

---

## AGENT 4: CONTEXT ROUTING & RESPONSE FORMAT

### Routing Decision Tree - VERIFIED

```
┌─────────────────────────────────────────────────────────────┐
│                    ROUTING DECISION TREE                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  IF confidential bucket detected                            │
│     OR PII detected in query                                │
│     → Ollama (local)                                        │
│                                                             │
│  ELSE IF has public document sources                        │
│     → MiniMax (cloud direct)                                │
│     → OpenRouter (fallback)                                 │
│     → Ollama (final fallback)                               │
│                                                             │
│  ELSE (general chat, no sources)                            │
│     → Kimi (cloud) [BROKEN - file missing]                  │
│     → MiniMax (fallback)                                    │
│     → OpenRouter (fallback)                                 │
│     → Ollama (final fallback)                               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Response Format - VERIFIED

| Field | Required | Status | Structure |
|-------|----------|--------|-----------|
| content | string | PRESENT | Main response text |
| model_used / llm_used | string | PRESENT | Enum: "minimax", "kimi", "ollama" |
| sources | array | PRESENT | `{document_id, document_name, chunk_id, relevance_score}` |

### Privacy Protection - VERIFIED

**Status:** PASSING - No leaks detected

**Protection Mechanisms:**
1. Bucket-based routing (`document_bucket == "confidential"`)
2. PII detection override (PII in query → Ollama)
3. "Most restrictive" approach (any confidential → all to Ollama)
4. Audit logging for confidential access

**Code Verification (chat_service.py:214-217):**
```python
has_confidential = any(
    r.document_bucket == "confidential" for r in search_result["results"]
) or has_pii  # PII also triggers Ollama routing
```

### Edge Cases Identified

1. **Mixed Buckets:** Uses most restrictive - if ANY confidential, entire request → Ollama
2. **PII Override:** PII in query text triggers Ollama even for public documents
3. **Null Findings:** Answer agent returns False for empty findings (safe default)
4. **Audit Trail:** Confidential access logged at multiple points

---

## CONSOLIDATED FINDINGS

### CRITICAL BLOCKERS (Must Fix Before Production)

| ID | Issue | Location | Impact |
|----|-------|----------|--------|
| C1 | Exposed API keys in tracked `.env` | `.env` | Security breach |
| C2 | Missing `kimi_service.py` file | `backend/app/services/` | General chat broken |
| C3 | No fallback for confidential docs when Ollama down | `chat_service.py:334` | User experience |
| C4 | Missing centralized `llm_router.py` | `backend/app/services/` | Architecture |

### HIGH PRIORITY ISSUES

| ID | Issue | Location | Impact |
|----|-------|----------|--------|
| H1 | Missing `detect_context_sensitivity()` method | Services | API contract |
| H2 | Enum inconsistency - OPENROUTER not in LLMProvider | `api/chat.py` | Runtime error |
| H3 | Inconsistent env vars (OLLAMA_BASE_URL vs LOCAL_LLM_URL) | Multiple | Configuration |
| H4 | Method signature mismatch | All services | API contract |

### MEDIUM PRIORITY ISSUES

| ID | Issue | Location | Impact |
|----|-------|----------|--------|
| M1 | Distributed routing logic | `chat_service.py` | Maintainability |
| M2 | Real-looking keys in `.env.example` | `backend/.env.example` | Security confusion |

---

## RECOMMENDATIONS

### Immediate Actions (Day 1)

1. **Rotate all exposed API keys** - Document rotation in `docs/INFRASTRUCTURE_AUDIT_REPORT.md`
2. **Remove `.env` from git tracking:** `git rm --cached .env`
3. **Create missing `kimi_service.py`** or remove the import

### Short-term Actions (Week 1)

4. **Create centralized `llm_router.py`:**
   ```python
   class LLMRouter:
       def detect_context_sensitivity(chunks) -> bool
       async def generate_completion(prompt, context_chunks, stream)
       async def _generate_minimax(prompt, chunks, stream)
       async def _generate_ollama(prompt, chunks, stream)
   ```

5. **Fix enum inconsistency:** Add `OPENROUTER = "openrouter"` to LLMProvider

6. **Standardize environment variables:** Use single `OLLAMA_BASE_URL` everywhere

### Medium-term Actions (Week 2-4)

7. **Implement queue system for confidential queries** when Ollama temporarily unavailable
8. **Add health check** before routing to provide proactive status
9. **Create API contract tests** to verify response formats

---

## FILES REVIEWED

```
backend/app/services/
├── chat_service.py          [500 lines] - Main routing logic
├── minimax_service.py       [155 lines] - Minimax direct API
├── openrouter_service.py    [288 lines] - OpenRouter gateway
├── ollama_service.py        [186 lines] - Local LLM
├── pii_detection_service.py [~100 lines] - PII detection
├── collection_chat_service.py - Collection-specific routing
├── smart_folder_service.py  - Smart folder generation
├── report_service.py        - Report generation
└── agents/
    ├── researcher_agent.py  - Research agent routing
    ├── verification_agent.py - Verification agent
    └── answer_agent.py      - Answer agent routing

backend/app/api/
├── chat.py                  - LLMProvider enum
└── search.py                - Search routing logic

backend/app/models/
└── document.py              - DocumentBucket enum

backend/app/network_utils.py [278 lines] - Circuit breaker

.env                         - CRITICAL: Exposed credentials
```

---

## AUDIT TRAIL

| Agent | Task | Status | Timestamp |
|-------|------|--------|-----------|
| Agent 1 | LLM Router Structure | COMPLETE | 2026-02-21 |
| Agent 2 | Minimax/Moonshot Integration | COMPLETE | 2026-02-21 |
| Agent 3 | Ollama Integration | COMPLETE | 2026-02-21 |
| Agent 4 | Context Routing & Response | COMPLETE | 2026-02-21 |

---

**Report Generated By:** Orchestrator  
**Total Issues Found:** 10 (4 Critical, 4 High, 2 Medium)  
**Recommendation:** Address C1-C4 before any production deployment
