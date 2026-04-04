# SOWKNOW — Deep-Tier Agentic Stack Audit Report v2.0

> **Generated:** 2026-03-30 08:19:32
> **Codebase:** `/home/development/src/active/sowknow4`
> **Source files:** 295
> **Test files:** 86 *(excluded from agent/tool counts)*
> **Lines scanned:** 101,085
> **Self-excluded:** 4 audit script files

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Phase 1: Agent Census & Identity Audit](#2-phase-1-agent-census--identity-audit)
3. [Phase 2: 4-Stage Persistent Memory Audit](#3-phase-2-4-stage-persistent-memory-audit)
4. [Phase 3: Tooling & Programmatic Use Audit](#4-phase-3-tooling--programmatic-use-audit)
5. [Phase 4: Orchestration & Communication Audit](#5-phase-4-orchestration--communication-audit)
6. [Deliverable 2: Memory Gap Report](#6-deliverable-2-memory-gap-report)
7. [Deliverable 3: Optimization Roadmap](#7-deliverable-3-optimization-roadmap)
8. [Security Quick-Check](#8-security-quick-check)

---

## 1. Project Overview

### Directory Structure

```
.claude/    .github/    backend/    data/       docker/
docs/       frontend/   logs/       monitoring/ nginx/
scripts/    sync-agent/ tests/
```

### LLM Provider Usage (source files only)

| Provider | Refs | Files | Top Files |
|----------|------|-------|-----------|
| **ollama** | 325 | 45 | `backend/app/api/admin.py`, `backend/app/api/chat.py`, `backend/app/api/health.py`, `backend/app/main_minimal.py` +40 more |
| **openrouter** | 158 | 24 | `backend/app/api/chat.py`, `backend/app/api/collections.py`, `backend/app/api/status.py`, `backend/app/main.py` +19 more |
| **minimax** | 139 | 31 | `backend/app/api/chat.py`, `backend/app/api/status.py`, `backend/app/main_minimal.py` +26 more |
| **moonshot_kimi** | 74 | 17 | `backend/app/api/admin.py`, `backend/app/api/chat.py`, `backend/app/models/chat.py` +12 more |
| **paddleocr** | 21 | 4 | `backend/app/api/status.py`, `backend/app/main_minimal.py`, `backend/app/services/monitoring.py`, `backend/app/services/ocr_service.py` |
| **tesseract_ocr** | 18 | 2 | `backend/app/services/monitoring.py`, `backend/app/services/ocr_service.py` |
| **anthropic** | 4 | 3 | `backend/alembic/versions/006_add_minimax_enum.py`, `backend/app/api/deps.py`, `backend/app/services/monitoring.py` |

---

## 2. Phase 1: Agent Census & Identity Audit

**Total detected:** 59 real + 1 test (excluded)
- Agent classes: **6**
- Standalone prompts: **53**

### Deliverable 1: Agent Status Table

#### Agent Classes

| Name | Grade | WHY | WHO | HOW | Vault | LLM |
|------|-------|-----|-----|-----|-------|-----|
| AgentOrchestrator | F | :x: | :x: | :x: | :x: | ollama |
| AnswerAgent | F | :x: | :x: | :x: | :x: | ollama |
| ClarificationAgent | F | :x: | :x: | :x: | :x: | unknown |
| ResearcherAgent | F | :x: | :x: | :x: | :x: | ollama |
| VerificationAgent | F | :x: | :x: | :x: | :x: | ollama |
| SyncAgent | F | :x: | :x: | :x: | :x: | unknown |

#### Service-Level System Prompts

| File | Line | Grade | WHY | WHO | HOW | Vault | Prompt Snippet |
|------|------|-------|-----|-----|-----|-------|----------------|
| `backend/app/models/deferred_query.py` | L44 | F | :x: | :x: | :x: | :x: | — |
| `backend/app/services/agents/answer_agent.py` | L254 | C | :x: | :white_check_mark: | :x: | :x: | *"You are the Answer Agent for SOWKNOW. Generate clear, accurate answers..."* |
| `backend/app/services/agents/answer_agent.py` | L318 | F | :x: | :x: | :x: | :x: | *"Extract 3-5 key points from the answer..."* |
| `backend/app/services/agents/answer_agent.py` | L392 | D | :x: | :x: | :x: | :x: | *"Based on the original question and answer, suggest 3-5 relevant follow-up..."* |
| `backend/app/services/agents/answer_agent.py` | L171 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/agents/answer_agent.py` | L298 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/agents/answer_agent.py` | L402 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/agents/clarification_agent.py` | L133 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/agents/researcher_agent.py` | L226 | F | :x: | :x: | :x: | :x: | *"Analyze the search results and extract 3-5 key themes..."* |
| `backend/app/services/agents/researcher_agent.py` | L311 | D | :x: | :x: | :x: | :x: | *"Based on the original query and research findings, suggest 3-5 follow-up..."* |
| `backend/app/services/agents/researcher_agent.py` | L242 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/agents/researcher_agent.py` | L327 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/agents/verification_agent.py` | L175 | D | :x: | :x: | :x: | :x: | *"Analyze the claim and identify its type and key components..."* |
| `backend/app/services/agents/verification_agent.py` | L216 | D | :x: | :x: | :x: | :x: | *"Analyze whether the source text supports, contradicts, or is neutral..."* |
| `backend/app/services/agents/verification_agent.py` | L331 | D | :x: | :x: | :x: | :x: | *"Identify any factual conflicts between the two source texts..."* |
| `backend/app/services/agents/verification_agent.py` | L187 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/agents/verification_agent.py` | L241 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/agents/verification_agent.py` | L350 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/article_generation_service.py` | L101 | F | :x: | :x: | :x: | :x: | *"Parse LLM JSON response into article dicts..."* |
| `backend/app/services/auto_tagging_service.py` | L146 | C | :x: | :white_check_mark: | :x: | :x: | *"You are an intelligent document tagger for SOWKNOW..."* |
| `backend/app/services/auto_tagging_service.py` | L214 | C | :x: | :white_check_mark: | :x: | :x: | *"You are an intelligent document tagger for SOWKNOW..."* |
| `backend/app/services/auto_tagging_service.py` | L175 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/auto_tagging_service.py` | L243 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/chat_service.py` | L254 | C | :white_check_mark: | :x: | :x: | :white_check_mark: | *"You are SOWKNOW, a helpful AI assistant for a multi-generational legacy..."* |
| `backend/app/services/chat_service.py` | L272 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/collection_chat_service.py` | L303 | D | :x: | :x: | :x: | :x: | *"You are SOWKNOW, a helpful assistant for a document collection..."* |
| `backend/app/services/collection_chat_service.py` | L338 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/collection_service.py` | L464 | D | :x: | :white_check_mark: | :x: | :x: | *"You are a helpful assistant that summarizes document collections..."* |
| `backend/app/services/deferred_query_service.py` | L199 | F | :x: | :x: | :x: | :x: | *record...* |
| `backend/app/services/entity_extraction_service.py` | L185 | C | :x: | :white_check_mark: | :x: | :x: | *"You are an expert entity extractor for SOWKNOW..."* |
| `backend/app/services/entity_extraction_service.py` | L249 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/graph_rag_service.py` | L388 | D | :x: | :x: | :x: | :x: | *"You are SOWKNOW, an AI assistant for a knowledge management system..."* |
| `backend/app/services/graph_rag_service.py` | L441 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/intent_parser.py` | L405 | C | :x: | :white_check_mark: | :x: | :x: | *"You are a precise JSON-only intent parser..."* |
| `backend/app/services/progressive_revelation_service.py` | L450 | D | :x: | :x: | :x: | :x: | *"You are SOWKNOW's family historian..."* |
| `backend/app/services/progressive_revelation_service.py` | L490 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/report_service.py` | L236 | D | :x: | :x: | :x: | :x: | *"You are SOWKNOW, a professional report generator..."* |
| `backend/app/services/report_service.py` | L263 | F | :x: | :x: | :x: | :x: | *"You are SOWKNOW, a professional report generator that creates..."* |
| `backend/app/services/search_agent.py` | L222 | C | :x: | :white_check_mark: | :x: | :x: | *"Tu es un agent d'analyse de requetes pour SOWKNOW..."* |
| `backend/app/services/search_agent.py` | L256 | C | :x: | :white_check_mark: | :x: | :x: | *"Tu es un assistant de recherche pour SOWKNOW..."* |
| `backend/app/services/search_agent.py` | L284 | F | :x: | :x: | :x: | :x: | *system...* |
| `backend/app/services/smart_folder_service.py` | L242 | D | :x: | :x: | :x: | :x: | *"You are SOWKNOW, an AI content generator..."* |
| `backend/app/services/smart_folder_service.py` | L260 | D | :x: | :x: | :x: | :x: | *"You are SOWKNOW, an AI content generator that creates..."* |
| `backend/app/services/synthesis_service.py` | L244 | C | :x: | :white_check_mark: | :x: | :x: | *"You are an expert information extractor for SOWKNOW..."* |
| `backend/app/services/synthesis_service.py` | L441 | D | :x: | :x: | :x: | :x: | *"You are SOWKNOW's synthesis engine..."* |
| `backend/app/services/synthesis_service.py` | L488 | D | :x: | :x: | :x: | :x: | *"Extract the 3-7 most important key points..."* |
| `backend/app/services/synthesis_service.py` | L268 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/synthesis_service.py` | L462 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `backend/app/services/synthesis_service.py` | L499 | F | :x: | :x: | :x: | :x: | *system_prompt...* |
| `docs/search_agent.py` | L62 | C | :x: | :white_check_mark: | :x: | :x: | *"Tu es un agent d'analyse de requetes pour SOWKNOW..."* |
| `docs/search_agent.py` | L114 | C | :x: | :white_check_mark: | :x: | :x: | *"Tu es un assistant de recherche pour SOWKNOW..."* |
| `docs/search_agent.py` | L173 | F | :x: | :x: | :x: | :x: | *system...* |
| `docs/search_agent.py` | L194 | F | :x: | :x: | :x: | :x: | *system...* |

### Profile Grade Distribution

| Grade | Count | Bar |
|-------|-------|-----|
| **A** | 0 | |
| **B** | 0 | |
| **C** | 11 | ███████████ |
| **D** | 14 | ██████████████ |
| **F** | 34 | ██████████████████████████████████ |

> **CRITICAL:** 34/59 agents have grade F (no meaningful prompt identity). Every agent needs WHY (mission), WHO (persona), HOW (constraints).

---

## 3. Phase 2: 4-Stage Persistent Memory Audit

### Memory Tier Status Matrix

| Tier | Real | Partial | Status |
|------|------|---------|--------|
| Stage 1: SENSORY / BUFFER | 34 | 165 | :green_circle: IMPLEMENTED |
| Stage 2: WORKING MEMORY | 0 | 1 | :red_circle: **MISSING** |
| Stage 3: EPISODIC MEMORY | 259 | 169 | :green_circle: IMPLEMENTED |
| Stage 4: SEMANTIC MEMORY | 134 | 125 | :green_circle: IMPLEMENTED |

---

### Stage 1: SENSORY / BUFFER

**Purpose:** Input filtering, dedup, PII sanitization before LLM

**Real implementation signals (34):**

| Signal | Location |
|--------|----------|
| PII detection/redaction | `backend/app/services/chat_service.py:25` |
| PII detection/redaction | `backend/app/services/llm_router.py:5` |
| PII detection/redaction | `backend/app/services/pii_detection_service.py:15` |
| PII detection/redaction | `backend/app/services/search_service.py:16` |
| PII detection/redaction | `backend/app/services/agents/agent_orchestrator.py:31` |
| Intent classification | `docs/search_router.py:205` |

<details>
<summary><b>Supporting signals (165)</b> - click to expand</summary>

| Signal | Location |
|--------|----------|
| Token counting | `backend/alembic/versions/001_initial_schema.py:94` |
| Rate limiting | `backend/app/celery_app.py:81` |
| Rate limiting | `backend/app/main.py:14` |
| Token limit config | `backend/app/services/article_generation_service.py:120` |
| Token limit config | `backend/app/services/auto_tagging_service.py:191` |
| Input truncation | `backend/app/services/auto_tagging_service.py:57` |
| Token limit config | `backend/app/services/base_llm_service.py:22` |
| Token counting | `backend/app/services/chunking_service.py:23` |
| Token limit config | `backend/app/services/collection_chat_service.py:358` |
| Token limit config | `backend/app/services/collection_service.py:475` |
| Token counting | `backend/app/services/embedding_service.py:255` |
| Token limit config | `backend/app/services/entity_extraction_service.py:274` |
| Token limit config | `backend/app/services/graph_rag_service.py:449` |
| Token limit config | `backend/app/services/intent_parser.py:429` |
| Rate limiting | `backend/app/services/kimi_service.py:213` |
| Token limit config | `backend/app/services/kimi_service.py:70` |
| Input truncation | `backend/app/services/kimi_service.py:67` |
| Token limit config | `backend/app/services/llm_router.py:111` |
| Token limit config | `backend/app/services/minimax_service.py:46` |
| Input truncation | `backend/app/services/minimax_service.py:45` |
| Token limit config | `backend/app/services/ollama_service.py:52` |
| Rate limiting | `backend/app/services/openrouter_service.py:371` |
| Token limit config | `backend/app/services/openrouter_service.py:153` |
| Token counting | `backend/app/services/openrouter_service.py:147` |
| Input truncation | `backend/app/services/openrouter_service.py:152` |
| Token limit config | `backend/app/services/progressive_revelation_service.py:500` |
| Token limit config | `backend/app/services/report_service.py:272` |
| Token limit config | `backend/app/services/search_agent.py:273` |
| Input truncation | `backend/app/services/similarity_service.py:273` |
| Token limit config | `backend/app/services/smart_folder_service.py:269` |
| Token limit config | `backend/app/services/synthesis_service.py:279` |
| Input truncation | `backend/app/services/telegram_notifier.py:55` |
| Input truncation | `backend/app/services/agents/agent_orchestrator.py:392` |
| Token limit config | `backend/app/services/agents/answer_agent.py:178` |
| Token limit config | `backend/app/services/agents/clarification_agent.py:140` |
| Token limit config | `backend/app/services/agents/researcher_agent.py:250` |
| Token limit config | `backend/app/services/agents/verification_agent.py:194` |
| Rate limiting | `backend/app/api/auth.py:10` |
| Token counting | `backend/app/tasks/document_tasks.py:271` |
| Token counting | `backend/app/models/document.py:198` |
| Token counting | `backend/app/schemas/document.py:109` |
| Input truncation | `frontend/components/BatchUploader.tsx:156` |
| Input truncation | `frontend/components/knowledge-graph/EntityList.tsx:127` |
| Input truncation | `frontend/app/[locale]/documents/page.tsx:640` |
| Input truncation | `frontend/app/[locale]/documents/[id]/page.tsx:526` |
| Input truncation | `frontend/app/[locale]/chat/page.tsx:292` |
| Input truncation | `frontend/app/[locale]/collections/page.tsx:219` |
| Input truncation | `frontend/app/[locale]/monitoring/page.tsx:248` |
| Input truncation | `frontend/app/[locale]/smart-folders/page.tsx:379` |
| Input truncation | `frontend/app/[locale]/dashboard/page.tsx:398` |
| Rate limiting | `frontend/app/[locale]/verify-email/[token]/page.tsx:79` |
| Input truncation | `frontend/app/[locale]/search/page.tsx:281` |
| Rate limiting | `frontend/app/[locale]/forgot-password/page.tsx:19` |
| Token limit config | `docs/search_agent.py:164` |

</details>

---

### Stage 2: WORKING MEMORY

**Purpose:** Prompt caching for static context (vault, values, summaries)

**Supporting signals (1):**
- Chat history storage -> `backend/alembic/versions/010_add_chat_session_index.py:7`

> **GAP:** No prompt-level caching for the SOWKNOW knowledge base.
>
> **NOTE:** Redis response caching (detected elsewhere) caches LLM *outputs*. Working Memory caches the *system context* at the LLM provider level so that the family vault, core values, and document summaries don't consume fresh tokens on every single API call.
>
> **IMPACT:** ~4,000-8,000 redundant tokens/query for resending static context.
>
> **FIX:** If OpenRouter supports it, use their context caching headers. Otherwise, maintain a compressed context summary with a TTL.

---

### Stage 3: EPISODIC MEMORY

**Purpose:** Vector-indexed document retrieval (pgvector + RAG)

<details>
<summary><b>Real implementation signals (259)</b> - click to expand</summary>

| Signal | Location |
|--------|----------|
| pgvector database | `docker-compose.dev.yml:3` |
| pgvector database | `docker-compose.prebuilt.yml:2` |
| pgvector database | `docker-compose.production.yml:15` |
| pgvector database | `docker-compose.simple.yml:5` |
| pgvector database | `docker-compose.yml:11` |
| Embedding model | `docker-compose.yml:226` |
| pgvector database | `backend/alembic/versions/001_initial_schema.py:20` |
| Document chunking | `backend/alembic/versions/001_initial_schema.py:92` |
| pgvector database | `backend/alembic/versions/004_add_pgvector_column.py:1` |
| Similarity search | `backend/alembic/versions/004_add_pgvector_column.py:13` |
| Vector store operations | `backend/alembic/versions/005_add_vector_fts_indexes.py:1` |
| Hybrid search | `backend/alembic/versions/005_add_vector_fts_indexes.py:2` |
| Document chunking | `backend/alembic/versions/005_add_vector_fts_indexes.py:35` |
| Document chunking | `backend/alembic/versions/009_add_fulltext_search.py:6` |
| Vector store operations | `backend/alembic/versions/010_upgrade_to_hnsw.py:1` |
| pgvector database | `backend/alembic/versions/014_add_articles.py:43` |
| Similarity search | `backend/alembic/versions/014_add_articles.py:60` |
| pgvector database | `backend/scripts/backfill_embeddings.py:2` |
| Document chunking | `backend/scripts/reprocess_all.py:44` |
| pgvector database | `backend/app/database.py:26` |
| pgvector database | `backend/app/main.py:34` |
| pgvector database | `backend/app/main_minimal.py:473` |
| Vector store operations | `backend/app/main_minimal.py:488` |
| Embedding model | `backend/app/main_minimal.py:261` |
| pgvector database | `backend/app/performance.py:110` |
| Vector store operations | `backend/app/performance.py:109` |
| Document chunking | `backend/app/services/article_generation_service.py:57` |
| Hybrid search | `backend/app/services/chat_service.py:199` |
| Document chunking | `backend/app/services/chat_service.py:213` |
| Chunk retrieval | `backend/app/services/chat_service.py:180` |
| Document chunking | `backend/app/services/chunking_service.py:2` |
| Embedding model | `backend/app/services/chunking_service.py:5` |
| Document chunking | `backend/app/services/collection_chat_service.py:286` |
| Hybrid search | `backend/app/services/collection_service.py:354` |
| Similarity search | `backend/app/services/embedding_service.py:196` |
| Document chunking | `backend/app/services/embedding_service.py:246` |
| Embedding model | `backend/app/services/embedding_service.py:2` |
| Document chunking | `backend/app/services/entity_extraction_service.py:172` |
| Embedding model | `backend/app/services/performance_service.py:133` |
| Document chunking | `backend/app/services/report_service.py:175` |
| Hybrid search | `backend/app/services/search_agent.py:20` |
| Document chunking | `backend/app/services/search_agent.py:465` |
| Chunk retrieval | `backend/app/services/search_agent.py:480` |
| Chunk retrieval | `backend/app/services/search_models.py:127` |
| pgvector database | `backend/app/services/search_service.py:120` |
| Similarity search | `backend/app/services/search_service.py:120` |
| Hybrid search | `backend/app/services/search_service.py:2` |
| Document chunking | `backend/app/services/search_service.py:30` |
| Embedding model | `backend/app/services/search_service.py:123` |
| Similarity search | `backend/app/services/similarity_service.py:147` |
| Hybrid search | `backend/app/services/smart_folder_service.py:162` |
| Document chunking | `backend/app/services/smart_folder_service.py:203` |
| Document chunking | `backend/app/services/synthesis_service.py:218` |
| Embedding generation | `backend/app/api/documents.py:1008` |
| Similarity search | `backend/app/api/documents.py:966` |
| Hybrid search | `backend/app/api/search_agent_router.py:33` |
| Document chunking | `backend/app/api/search_agent_router.py:65` |
| pgvector database | `backend/app/api/status.py:33` |
| Document chunking | `backend/app/tasks/article_tasks.py:165` |
| Embedding generation | `backend/app/tasks/document_tasks.py:425` |
| Document chunking | `backend/app/tasks/document_tasks.py:80` |
| Embedding generation | `backend/app/tasks/embedding_tasks.py:5` |
| Document chunking | `backend/app/tasks/embedding_tasks.py:77` |
| Embedding model | `backend/app/tasks/embedding_tasks.py:45` |
| pgvector database | `backend/app/models/article.py:9` |
| Chunk retrieval | `backend/app/models/deferred_query.py:43` |
| pgvector database | `backend/app/models/document.py:16` |
| Document chunking | `backend/app/models/document.py:187` |
| Document chunking | `backend/app/models/processing.py:15` |
| Document chunking | `backend/app/schemas/chat.py:51` |
| Embedding generation | `backend/app/schemas/document.py:154` |
| Document chunking | `backend/app/schemas/document.py:108` |
| Hybrid search | `backend/app/schemas/search.py:11` |
| Document chunking | `backend/app/schemas/search.py:19` |
| pgvector database | `scripts/backfill_embeddings_to_vector.py:3` |
| pgvector database | `docker/archived-compose/docker-compose.prebuilt.yml:2` |
| pgvector database | `docker/archived-compose/docker-compose.production.yml:15` |
| pgvector database | `docker/archived-compose/docker-compose.simple.yml:5` |
| Document chunking | `frontend/app/[locale]/search/page.tsx:40` |
| pgvector database | `docs/0003_agentic_search.py:13` |
| Hybrid search | `docs/0003_agentic_search.py:7` |
| pgvector database | `docs/search_agent.py:12` |
| Hybrid search | `docs/search_agent.py:316` |
| Embedding model | `docs/search_agent.py:30` |
| Chunk retrieval | `docs/search_agent.py:622` |
| Hybrid search | `docs/search_models.py:53` |
| Chunk retrieval | `docs/search_models.py:155` |
| Chunk retrieval | `docs/search_router.py:134` |
| pgvector database | `.github/workflows/performance-benchmarks.yml:19` |

</details>

<details>
<summary><b>Supporting signals (169)</b> - click to expand</summary>

Embedding env vars and config across `backend/alembic/`, `backend/app/`, `backend/scripts/`, `scripts/`, `frontend/`, `docs/` — 35 unique locations.

</details>

---

### Stage 4: SEMANTIC MEMORY

**Purpose:** Structured relationships, entity graph, core values

<details>
<summary><b>Real implementation signals (134)</b> - click to expand</summary>

| Signal | Location |
|--------|----------|
| Knowledge/entity graph | `backend/alembic/versions/003_add_knowledge_graph.py:1` |
| Knowledge/entity graph | `backend/app/main.py:28` |
| Graph-RAG | `backend/app/main.py:27` |
| Knowledge/entity graph | `backend/app/main_minimal.py:156` |
| Graph-RAG | `backend/app/main_minimal.py:155` |
| Knowledge/entity graph | `backend/app/performance.py:31` |
| Knowledge/entity graph | `backend/app/services/entity_extraction_service.py:2` |
| Entity extraction | `backend/app/services/entity_extraction_service.py:2` |
| Knowledge/entity graph | `backend/app/services/graph_rag_service.py:2` |
| Graph-RAG | `backend/app/services/graph_rag_service.py:27` |
| Knowledge/entity graph | `backend/app/services/progressive_revelation_service.py:2` |
| Family/curator context | `backend/app/services/progressive_revelation_service.py:5` |
| Knowledge/entity graph | `backend/app/services/relationship_service.py:2` |
| Entity extraction | `backend/app/services/relationship_service.py:21` |
| Relationship mapping | `backend/app/services/relationship_service.py:2` |
| Knowledge/entity graph | `backend/app/services/synthesis_service.py:2` |
| Knowledge/entity graph | `backend/app/services/temporal_reasoning_service.py:2` |
| Knowledge/entity graph | `backend/app/services/timeline_service.py:2` |
| Knowledge/entity graph | `backend/app/services/agents/researcher_agent.py:4` |
| Graph-RAG | `backend/app/services/agents/researcher_agent.py:13` |
| Knowledge/entity graph | `backend/app/api/graph_rag.py:68` |
| Graph-RAG | `backend/app/api/graph_rag.py:22` |
| Family/curator context | `backend/app/api/graph_rag.py:309` |
| Knowledge/entity graph | `backend/app/api/knowledge_graph.py:2` |
| Entity extraction | `backend/app/api/knowledge_graph.py:4` |
| Relationship mapping | `backend/app/api/knowledge_graph.py:4` |
| Knowledge/entity graph | `backend/app/api/status.py:25` |
| Entity extraction | `backend/app/api/status.py:47` |
| Relationship mapping | `backend/app/api/status.py:49` |
| Family/curator context | `backend/app/api/status.py:56` |
| Knowledge/entity graph | `backend/app/models/__init__.py:15` |
| Knowledge/entity graph | `backend/app/models/knowledge_graph.py:2` |
| Knowledge/entity graph | `frontend/components/Navigation.tsx:12` |
| Knowledge/entity graph | `frontend/components/knowledge-graph/GraphVisualization.tsx:2` |
| Knowledge/entity graph | `frontend/lib/api.ts:416` |
| Knowledge/entity graph | `frontend/app/[locale]/page.tsx:19` |
| Entity extraction | `frontend/app/[locale]/page.tsx:104` |
| Knowledge/entity graph | `frontend/app/[locale]/knowledge-graph/page.tsx:2` |

</details>

<details>
<summary><b>Supporting signals (125)</b> - click to expand</summary>

Entity type definitions and progressive revelation across `backend/alembic/`, `backend/app/services/`, `backend/app/api/`, `backend/app/models/`, `frontend/components/`, `frontend/lib/`, `frontend/app/` — 22 unique locations.

</details>

---

## 4. Phase 3: Tooling & Programmatic Use Audit

**Formal tool schemas detected:** 0 (source) + 0 (tests)

> **NO FORMAL TOOL SCHEMAS IN SOURCE CODE**
>
> The multi-agent system (AgentOrchestrator -> Clarification/Researcher/Verification/Answer) calls services directly via Python methods rather than through structured tool schemas.

**Risks:**
- Agents can't self-discover available tools
- No schema validation prevents hallucinated parameters
- Tool outputs aren't validated before agent consumption
- Adding new tools requires code changes in the orchestrator

**Recommended tool schemas for SOWKNOW:**

| Tool | Description |
|------|-------------|
| `document_search` | Hybrid semantic + keyword vault search |
| `document_upload` | Ingest file into processing pipeline |
| `ocr_process` | Trigger OCR via configured engine |
| `vault_classify` | Classify document as Public/Confidential |
| `generate_report` | Create collection report (Short/Standard/Full) |
| `entity_extract` | Extract people, orgs, concepts from document |
| `llm_route` | Select LLM provider based on vault context |

---

## 5. Phase 4: Orchestration & Communication Audit

### Orchestration Patterns

| Pattern | Status | Signals | Key Locations |
|---------|--------|---------|---------------|
| **Orchestrator** | :green_circle: | 1 | `backend/app/services/agents/agent_orchestrator.py` |
| **LLM Routing** | :green_circle: | 10 | `llm_router.py` (class + provider selection + confidential routing), `auto_tagging_service.py`, `chat_service.py`, `entity_extraction_service.py`, `intent_parser.py`, `openrouter_service.py` |
| **State Management** | :green_circle: | 2 | `backend/telegram_bot/bot.py` (StateManager class + session management) |
| **Workflow** | :green_circle: | 25 | Celery tasks across `celery_app.py`, `dlq_service.py`, `document_tasks.py`, `embedding_tasks.py`, `article_tasks.py` +17 more |

### Docker Infrastructure Health

| Check | Status |
|-------|--------|
| Persistent volumes | :green_circle: |
| Health checks | :green_circle: |
| Restart policies | :green_circle: |
| Resource limits | :green_circle: |
| Network isolation | :green_circle: |

### Container Services Detected

| Service | Status |
|---------|--------|
| PostgreSQL / pgvector | :green_circle: |
| Redis | :green_circle: |
| Ollama | :green_circle: |
| Celery workers | :green_circle: |
| Reverse proxy (Nginx/Caddy) | :green_circle: |
| NATS messaging | :green_circle: |

### Environment Configuration (values REDACTED)

**220 env keys detected:** 60 sensitive, 160 non-sensitive

| File | Total Keys | Sensitive |
|------|-----------|-----------|
| `.env` | 47 | 12 (DATABASE_PASSWORD, POSTGRES_PASSWORD, REDIS_PASSWORD, JWT_SECRET, MINIMAX_API_KEY, MOONSHOT_API_KEY, OPENROUTER_API_KEY...) |
| `.env.example` | 44 | 16 (DATABASE_PASSWORD, JWT_SECRET, ENCRYPTION_KEY, REDIS_PASSWORD, MINIMAX_API_KEY...) |
| `.env.save` | 42 | 10 (DATABASE_PASSWORD, REDIS_PASSWORD, JWT_SECRET, MINIMAX_API_KEY, MOONSHOT_API_KEY, OPENROUTER_API_KEY, TELEGRAM_BOT_TOKEN...) |
| `.secrets` | 7 | 5 (POSTGRES_PASSWORD, SECRET_KEY, JWT_SECRET_KEY, BOT_API_KEY, TELEGRAM_BOT_TOKEN) |
| `backend/.env.example` | 38 | 9 (JWT_SECRET, ENCRYPTION_KEY, MOONSHOT_API_KEY...) |
| `backend/.env.production` | 30 | 8 |
| `frontend/.env.production` | 12 | 0 |

---

## 6. Deliverable 2: Memory Gap Report

*Identifies where "forgetting" or "redundant token spending" occurs.*

### Tier Status Summary

| Status | Tiers |
|--------|-------|
| :red_circle: **GAPS** (1 tier missing) | Working Memory (prompt caching) |
| :green_circle: **IMPLEMENTED** (3 tiers) | Sensory/Buffer (34 signals), Episodic Memory (259 signals), Semantic Memory (134 signals) |

### Token Waste Estimate (per query)

| Issue | Cost | Cause |
|-------|------|-------|
| No prompt caching | **~4,000-8,000 tokens/query** | Resending static SOWKNOW context every call |

### Cross-Agent State Preservation

:green_circle: 24 state management signals detected.
- State manager class -> `backend/telegram_bot/bot.py`
- Session management -> `backend/telegram_bot/bot.py`

---

## 7. Deliverable 3: Optimization Roadmap

*High-impact changes to make SOWKNOW "Legacy-Ready"*

### OPT-1: Upgrade Agent Profiles with Mission / Persona / Constraints

| | |
|---|---|
| **Priority** | :red_circle: CRITICAL |
| **Effort** | 1 week |
| **Trigger** | 34/59 agents scored grade F |

Every system prompt must clearly define three pillars:

**WHY (Mission):**
> *"You are the Vault Router. Your mission is to ensure zero exposure of confidential documents to cloud APIs."*

**WHO (Persona):**
> *"You are a meticulous, security-conscious classifier that treats every ambiguous document as potentially confidential."*

**HOW (Constraints):**
> *"You MUST classify before routing. You MUST NOT pass any document to OpenRouter/MiniMax that hasn't been vault-checked. You MUST log every routing decision for audit."*

**Apply to:** `chat_service`, `search_agent`, `collection_service`, `report_service`, `smart_folder_service`, `synthesis_service`, `auto_tagging_service`, `entity_extraction_service`, `intent_parser`, `article_generation_service`

---

### OPT-2: Implement Working Memory (prompt-level context caching)

| | |
|---|---|
| **Priority** | :red_circle: CRITICAL |
| **Effort** | 1-2 weeks |
| **Trigger** | Only 0 real working memory signals found |

Redis response caching (which exists) is **NOT** working memory. Working memory caches the **STATIC SYSTEM CONTEXT** at the LLM level:

1. **Build a compressed "SOWKNOW Context Block" (~2000 tokens):**
   - System identity and persona
   - Vault rules and routing constraints
   - Document corpus summary (top entities, date ranges, topics)
   - Family context and core values (curator-defined)

2. **Cache this block across sessions:**
   - If OpenRouter supports context caching headers: use them
   - If not: store the block in Redis with a TTL, prepend to every call
   - Invalidate only when the document corpus changes significantly

3. **Estimated savings:** ~4,000-8,000 tokens per query. At current usage, this could reduce LLM costs by **30-50%**

---

### OPT-5: Formalize Tool Schemas for Agent Interoperability

| | |
|---|---|
| **Priority** | :green_circle: MEDIUM |
| **Effort** | 3-5 days |
| **Trigger** | Only 0 formal tool schemas found |

Current agents call services via direct Python methods. For future extensibility and LLM-native tool use:

1. Define JSON schemas for core operations: `document_search`, `vault_classify`, `entity_extract`, `generate_report`
2. Add a `ToolRegistry` that agents can introspect at runtime
3. Wrap each tool with input validation (Pydantic models)
4. Add output validation before passing results back to the agent

> This is MEDIUM priority because the current direct-call approach works. Schemas become critical if you add new agents or expose tool use via API.

---

## 8. Security Quick-Check

- **60 sensitive env keys** detected (values NEVER shown in this report)

| File | Sensitive Keys |
|------|---------------|
| `.env` | 12 |
| `.env.example` | 16 |
| `.env.save` | 10 |
| `.secrets` | 5 |
| `backend/.env.example` | 9 |
| `backend/.env.production` | 8 |

> Ensure `.env` files are in `.gitignore` and not committed to VCS.
> Rotate any credentials that were exposed in audit v1 report output.

**Vault-aware agents:** 1/59

> Most agent prompts don't mention confidentiality constraints. Consider adding vault awareness to all agents that touch documents.

---

*END OF AUDIT REPORT v2.0*
