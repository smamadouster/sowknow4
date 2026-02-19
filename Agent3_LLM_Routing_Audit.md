# SESSION: Agent 3 - LLM Routing & Data Flow Audit
- **Timestamp:** 2026-02-16 17:15:00
- **Auditor:** Security & Privacy Specialist
- **Scope:** RAG pipeline, LLM routing, document confidentiality

---

## ACCOMPLISHED TASKS

### Task 1: Map Code Path - Document Retrieval to LLM Selection
- **Status:** COMPLETED
- **Evidence:** Traced from `chat.py` endpoint through `chat_service.py` to individual LLM services
- **Key Files:**
  - `/root/development/src/active/sowknow4/backend/app/api/chat.py` - Main chat endpoints
  - `/root/development/src/active/sowknow4/backend/app/services/chat_service.py` - Core routing logic
  - `/root/development/src/active/sowknow4/backend/app/services/search_service.py` - Document retrieval with RBAC

### Task 2: Verify Conditional Logic - Ollama Switching for Confidential Docs
- **Status:** PARTIALLY VERIFIED (see findings)
- **Evidence:** Found proper routing in `chat_service.py` and `collection_chat_service.py`

### Task 3: Hunt for Leaks - Confidential Chunks Reaching Cloud APIs
- **Status:** CRITICAL VULNERABILITIES FOUND
- **Evidence:** Multi-agent system sends confidential content to Gemini

### Task 4: Check Prompt Sanitization
- **Status:** VERIFIED
- **Evidence:** PII detection service properly implemented

### Task 5: Check Caching Layers
- **Status:** POTENTIAL CONCERN IDENTIFIED
- **Evidence:** Gemini cache stores conversation history

---

## FINDINGS

### FINDING 1: CRITICAL - Multi-Agent System Leaks Confidential Data to Gemini

**Severity:** CRITICAL  
**Status:** VULNERABILITY CONFIRMED

**Description:**
The multi-agent system (Phase 3) sends ALL search results to Gemini, including confidential documents when Admin or SuperUser roles perform searches.

**Code Evidence:**
- `researcher_agent.py` lines 256, 353: Uses `gemini_service.chat_completion()` with search findings
- `answer_agent.py` lines 161, 289, 316, 404: Uses Gemini for all queries
- `verification_agent.py` lines 189, 249, 367: Uses Gemini without checking document bucket
- `clarification_agent.py` line 121: Uses Gemini unconditionally
- `graph_rag_service.py` lines 412, 420: Uses Gemini for graph-based queries
- `multi_agent.py` endpoint: Passes user through but no confidentiality check

**Attack Vector:**
1. Admin or SuperUser logs in
2. Makes a multi-agent search query
3. Search retrieves documents from both "public" and "confidential" buckets
4. Findings (with full document content) sent to Gemini for:
   - Theme extraction
   - Follow-up query generation
   - Answer synthesis
   - Claim verification
5. Confidential content now exposed to Google Gemini API

**Affected Endpoints:**
- POST `/api/v1/multi-agent/search`
- GET `/api/v1/multi-agent/stream`
- POST `/api/v1/multi-agent/research`
- POST `/api/v1/multi-agent/verify`
- POST `/api/v1/multi-agent/answer`

---

### FINDING 2: Main Chat Service - PROPERLY PROTECTED

**Severity:** N/A (Correct Implementation)  
**Status:** CONFIRMED SECURE

**Code Evidence:**
```python
# chat_service.py lines 326-357
if has_confidential:
    # Confidential: always use Ollama
    llm_service = self.ollama_service
    llm_provider = LLMProvider.OLLAMA
```

The main chat service correctly:
- Checks for confidential documents in search results
- Routes to Ollama when `has_confidential = True`
- Uses OpenRouter (MiniMax) for public RAG
- Uses Kimi for general chat (no documents)

---

### FINDING 3: Collection Chat Service - PROPERLY PROTECTED

**Severity:** N/A (Correct Implementation)  
**Status:** CONFIRMED SECURE

**Code Evidence:**
```python
# collection_chat_service.py lines 143-176
has_confidential = any(
    item.document.bucket.value == "confidential"
    for item in collection_items
)

if has_confidential:
    response_data = await self._chat_with_ollama(...)
else:
    response_data = await self._chat_with_gemini(...)
```

---

### FINDING 4: Collection Service Summary Generation - PROPERLY PROTECTED

**Severity:** N/A (Correct Implementation)  
**Status:** CONFIRMED SECURE

**Code Evidence:**
```python
# collection_service.py lines 396-430
has_confidential = any(
    doc.bucket == DocumentBucket.CONFIDENTIAL
    for doc in documents
)

if has_confidential:
    response = await self.ollama_service.generate(...)
else:
    response = await self.gemini_service.chat_completion(...)
```

---

### FINDING 5: PII Detection Service - PROPERLY IMPLEMENTED

**Severity:** N/A (Correct Implementation)  
**Status:** CONFIRMED WORKING

**Description:**
PII detection is implemented and used in chat_service and search_service. It correctly:
- Detects email, phone, SSN, credit card, IBAN, French national ID
- Redacts PII from chunks when detected in query
- Triggers Ollama routing when PII is found

**Code Evidence:**
- `/root/development/src/active/sowknow4/backend/app/services/pii_detection_service.py` (294 lines)
- Used in `chat_service.py` lines 179-183, 215-218
- Used in `search_service.py` lines 291-297

---

### FINDING 6: Gemini Cache - POTENTIAL DATA EXPOSURE

**Severity:** MEDIUM  
**Status:** NEEDS REVIEW

**Description:**
The Gemini service has an in-memory cache (`GeminiCacheManager`) that stores conversation history and system prompts.

**Code Evidence:**
- `gemini_service.py` lines 79-209: `GeminiCacheManager` class
- Cache keys based on message content hash
- TTL-based expiration

**Risk:**
If confidential content is incorrectly routed to Gemini (due to Finding #1), that content could remain in cache memory and potentially be retrieved.

**Mitigation:**
- Cache is in-memory only (not persisted)
- TTL is configurable (default 3600 seconds)
- However, this is still a concern during the cache window

---

### FINDING 7: Additional Services Using Gemini Without Routing Checks

**Severity:** HIGH  
**Status:** VULNERABILITY CONFIRMED

**Description:**
Multiple services use Gemini directly without checking for confidential documents:

| Service | File | Risk |
|---------|------|------|
| Smart Folder Service | `smart_folder_service.py:280` | No confidential check |
| Intent Parser | `intent_parser.py:381` | No confidential check |
| Entity Extraction | `entity_extraction_service.py:242` | No confidential check |
| Auto-Tagging | `auto_tagging_service.py:160` | No confidential check |
| Report Service | `report_service.py:255` | No confidential check |
| Progressive Revelation | `progressive_revelation_service.py:405` | No confidential check |
| Synthesis Service | `synthesis_service.py:263,465,503` | No confidential check |

---

### FINDING 8: Search Service RBAC - CORRECTLY IMPLEMENTED

**Severity:** N/A (Correct Implementation)  
**Status:** CONFIRMED SECURE

**Description:**
The search service correctly filters documents by user role:
- Admin: sees public + confidential
- SuperUser: sees public + confidential (VIEW-ONLY)
- User: sees public only

**Code Evidence:**
```python
# search_service.py lines 59-98
def _get_user_bucket_filter(self, user: User) -> List[str]:
    if user.role == UserRole.ADMIN:
        return [DocumentBucket.PUBLIC.value, DocumentBucket.CONFIDENTIAL.value]
    elif user.role == UserRole.SUPERUSER:
        return [DocumentBucket.PUBLIC.value, DocumentBucket.CONFIDENTIAL.value]
    else:
        return [DocumentBucket.PUBLIC.value]
```

This protection works correctly - a regular User cannot see confidential documents. However, Admin and SuperUser CAN see confidential documents, and when they use the multi-agent system, those documents get sent to Gemini.

---

## DECISIONS MADE

1. **Primary focus:** Focused on document-to-LLM flow rather than user authentication (which is covered by other audits)
2. **RBAC interpretation:** SuperUser has VIEW-ONLY access to confidential documents, but the system should still protect these from cloud APIs even when Admin/SuperUser is using the system
3. **Scope limitation:** Did not test runtime behavior - audit is code静态 analysis only

---

## EVIDENCE

### Command Outputs:

```
# File count showing Gemini usage:
$ grep -r "gemini_service" --include="*.py" | wc -l
144

# Files with direct Gemini calls without routing:
$ grep -L "has_confidential\|document_bucket\|bucket" app/services/*agent*.py
app/services/agents/answer_agent.py
app/services/agents/verification_agent.py
app/services/agents/clarification_agent.py
```

### Key File Paths:

| Purpose | Path |
|---------|------|
| Main chat API | `/root/development/src/active/sowknow4/backend/app/api/chat.py` |
| Chat service with routing | `/root/development/src/active/sowknow4/backend/app/services/chat_service.py` |
| Search with RBAC | `/root/development/src/active/sowknow4/backend/app/services/search_service.py` |
| Multi-agent orchestrator | `/root/development/src/active/sowknow4/backend/app/api/multi_agent.py` |
| Researcher agent (leak) | `/root/development/src/active/sowknow4/backend/app/services/agents/researcher_agent.py` |
| Answer agent (leak) | `/root/development/src/active/sowknow4/backend/app/services/agents/answer_agent.py` |
| Verification agent (leak) | `/root/development/src/active/sowknow4/backend/app/services/agents/verification_agent.py` |
| Clarification agent (leak) | `/root/development/src/active/sowknow4/backend/app/services/agents/clarification_agent.py` |
| PII detection | `/root/development/src/active/sowknow4/backend/app/services/pii_detection_service.py` |
| Gemini service | `/root/development/src/active/sowknow4/backend/app/services/gemini_service.py` |
| Ollama service | `/root/development/src/active/sowknow4/backend/app/services/chat_service.py` (inline) |
| Collection chat (secure) | `/root/development/src/active/sowknow4/backend/app/services/collection_chat_service.py` |
| Collection service (secure) | `/root/development/src/active/sowknow4/backend/app/services/collection_service.py` |

---

## NEXT STEPS

### Immediate Actions Required:

1. **Fix Multi-Agent System (CRITICAL)**
   - Add confidential document check in researcher_agent before calling Gemini
   - Add routing to Ollama when search results contain confidential documents
   - Apply same fix to answer_agent, verification_agent, clarification_agent

2. **Audit Additional Services (HIGH)**
   - smart_folder_service.py
   - intent_parser.py
   - entity_extraction_service.py
   - auto_tagging_service.py
   - report_service.py
   - progressive_revelation_service.py
   - synthesis_service.py

3. **Review Gemini Cache (MEDIUM)**
   - Consider adding cache key that includes confidentiality flag
   - Implement separate cache instances for public vs confidential

### Architecture Recommendation:

Create a unified LLM routing service that ALL AI-powered services must use:

```python
class LLMRoutingService:
    async def chat_completion(messages, context):
        # Check for confidential documents in context
        if self._contains_confidential(context):
            return await self.ollama_service.chat_completion(messages)
        else:
            return await self.gemini_service.chat_completion(messages)
```

This would ensure consistent routing across all services.

---

## SUMMARY

| Category | Status |
|----------|--------|
| Main Chat API | SECURE |
| Collection Chat | SECURE |
| Collection Service | SECURE |
| PII Detection | SECURE |
| Search RBAC | SECURE |
| **Multi-Agent System** | **CRITICAL VULNERABILITY** |
| **Additional Services** | **HIGH RISK** |
| Gemini Cache | MEDIUM CONCERN |

**Overall Assessment:** The core chat functionality correctly routes confidential documents to Ollama. However, the multi-agent system (Phase 3) and several secondary services bypass these protections and send ALL content (including confidential) to Gemini. This is a critical privacy violation that must be fixed before production use with Admin/SuperUser accounts.
