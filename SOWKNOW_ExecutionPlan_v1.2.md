# SOWKNOW Multi-Generational Legacy Knowledge System
## Execution Plan v1.2

**Date:** February 2026
**Classification:** CONFIDENTIAL
**Timeline:** 20 Weeks (3 Phases) | LLM: Gemini Flash + Shared Ollama
**Last Amendment:** February 10, 2026

---

## Amendment Record

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| v1.0 | Feb 1, 2026 | Initial execution plan | System |
| v1.1 | Feb 5, 2026 | Tech stack refinements | System |
| v1.2 | Feb 10, 2026 | **STRATEGIC LLM PIVOT: Kimi 2.5 → Gemini Flash** | Infrastructure Adviser |

### Critical Amendments (Feb 10, 2026)

**STRATEGIC ADVISORY NOTE:** This version incorporates a significant architectural shift from Kimi 2.5 to **Gemini Flash** as the primary cloud LLM. This decision is based on:

1. **Massive Context Window:** 1M+ tokens vs Kimi 2.5's 128k (8x improvement)
2. **Context Caching:** Up to 80% cost reduction for recurring vault queries
3. **Superior Multilingual Performance:** Native FR/EN support aligns with SOWKNOW localization
4. **Native Multimodality:** Future potential to replace Hunyuan-OCR for document understanding

**INFRASTRUCTURE IMPACT:**
- Celery worker memory pressure relieved (cloud-first synthesis)
- Cost monitoring now includes Gemini cache hit-rate metrics
- API client migrated from httpx → google-generativeai SDK

---

## 1. Executive Summary

The SOWKNOW execution plan spans 20 weeks across 3 phases. Phase 1 (8 weeks) delivers the Core MVP: document upload, OCR processing via Hunyuan API, RAG-powered search using multilingual-e5-large embeddings, conversational AI chat via **Gemini Flash** (with context caching), confidential document routing via shared Ollama, and Telegram bot integration. Phase 2 (6 weeks) adds Smart Collections, Smart Folders, report generation, and auto-tagging. Phase 3 (6 weeks) implements Knowledge Graph, Graph-RAG, synthesis engine, and agentic search.

Each sprint is 2 weeks. Every sprint ends with a deployable increment. SOWKNOW uses the shared Ollama instance already running on the VPS, and **Gemini Flash via Google AI API** for all cloud AI features.

### 1.1 Timeline Overview

| Phase | Duration | Sprints | Key Deliverable |
|-------|----------|---------|-----------------|
| Phase 1: Core MVP | Weeks 1-8 | Sprint 1-4 | Full document pipeline + Gemini Flash chat + Telegram |
| Phase 2: Intelligence | Weeks 9-14 | Sprint 5-7 | Smart Collections + Smart Folders + reports |
| Phase 3: Advanced | Weeks 15-20 | Sprint 8-10 | Knowledge Graph + Graph-RAG + agentic search |

### 1.2 Resource Constraints

| Resource | Specification | Impact |
|----------|---------------|--------|
| VPS | Hostinger 16GB RAM, 200GB Disk (shared) | ~6.4GB for SOWKNOW containers; rest for Ollama + OS + other projects |
| GPU | None | OCR via Hunyuan API; Ollama CPU inference (shared) |
| Ollama | Shared instance, already running | No container management; connect via LOCAL_LLM_URL |
| Cloud LLM | **Gemini Flash** via Google Generative AI API | **Context caching enabled**; daily cost + cache hit-rate monitoring required |
| Users at Launch | 5 | Low concurrency; simplified auth sufficient |
| Document Ingestion | Incremental | No big-bang migration; pipeline ramps up gradually |

### 1.3 Strategic Infrastructure Advice (Feb 2026)

| Area | Advisory | Action Required |
|------|----------|-----------------|
| **Embedding Model** | multilingual-e5-large (1.3GB) leaves only 200MB in Celery worker | Monitor closely; drop to base version (900MB) if OOM during heavy indexing |
| **Ollama Latency** | CPU-only inference → 2-5s first token latency expected | Add "Local LLM is thinking..." UI indicator |
| **OCR Costs** | Hunyuan-OCR: $0.001–$0.003/page can accumulate | Tesseract fallback as safety valve for bulk uploads |
| **Security** | httpOnly cookies + localhost Ollama = excellent | Continue strict practices; all confidential access logged |

---

## 2. Revised AI/ML Pipeline

### 2.1 Updated LLM Strategy

The system now utilizes a "**Cloud-First, Local-Secure**" routing strategy, prioritizing **Gemini Flash** for its high-throughput and long-context capabilities.

| Aspect | Gemini Flash (Public Docs) | Ollama (Confidential Docs) |
|--------|----------------------------|----------------------------|
| **Provider** | Google AI (Gemini API) | Shared VPS instance (localhost:11434) |
| **Model** | Gemini 1.5/2.0/3.0 Flash | mistral:7b-instruct (shared) |
| **Context Window** | 1 Million+ tokens | Depends on loaded model |
| **Key Use Cases** | Massive RAG synthesis, Smart Folders, multi-doc reports, Telegram chat | Confidential doc Q&A, Admin vault queries |
| **Primary Advantage** | Context Caching (Reduces cost/latency for recurring vault queries) | Full privacy, everything local |
| **Cost** | Per-token (highly optimized via caching) | Free (shared local compute) |
| **RAM Impact** | None (Cloud API) | None (SOWKNOW budget externalized) |

### 2.2 RAG Routing & Logic Amendments

The LLM Router logic in the backend must be updated to handle the massive context window of Gemini:

| Feature | Implementation |
|---------|---------------|
| **Large-Scale Retrieval** | For queries involving dozens of public documents, router bypasses individual chunking and feeds full document text (up to 1M tokens) directly into Gemini Flash |
| **Context Caching** | System automatically caches embeddings of "pinned" or frequently accessed collections in Gemini API to decrease response time and cost |
| **Privacy Override** | If any document in a "Smart Folder" generation is marked Confidential, router redirects entire task to local Ollama instance |
| **Cache Monitoring** | Track `usage_metadata.cached_content_token_count` per-call; alert if hit-rate < 50% for high-volume collections |

### 2.3 Infrastructure Adjustments

| Component | Change |
|-----------|--------|
| **API Framework** | httpx client augmented with `google-generativeai` Python library for native streaming and caching support |
| **Embedding Consistency** | Continue using multilingual-e5-large locally for indexing to maintain vector-search independence |
| **Worker Limits** | With Gemini Flash handling heavier synthesis tasks, maintain 1536MB RAM limit for Celery worker |
| **Fallback Strategy** | Retain Ollama as local, zero-PII fallback for truly confidential admin docs |

---

## 3. Infrastructure & DevOps (Revised)

### 3.1 Health Checks & Monitoring

Added specific probes for Gemini API and context caching performance:

| Service | Health Check | Interval | Alert Condition |
|---------|--------------|----------|-----------------|
| **Gemini API** | `client.models.get_model()` | 300s | 3 consecutive timeouts |
| **Context Cache** | Inspect `usage_metadata.cached_content_token_count` | Per-call | Alert if hit-rate < 50% for high-volume collections |
| **Ollama (Local)** | `GET http://localhost:11434/api/tags` | 60s | Connection refused (Warn, fallback to Cloud) |
| **Worker RAM** | `docker stats --format "{{.MemUsage}}"` | 30s | Usage > 1.4GB (Risk of OOM for e5-large model) |

**Key Monitoring Metrics:**

| Metric | Target | Purpose |
|--------|--------|---------|
| **Latency** | 50th/95th/99th percentile for Gemini Flash | Track response time distribution |
| **Token Efficiency** | Cache hit tokens vs total tokens | Validate RAG pipeline cost efficiency |
| **Error Rate** | 4xx/5xx errors < 5% over 5 minutes | Alert on authentication/quota/Google issues |

### 3.2 Backup & Secrets Strategy (Zero-Touch)

**Automated Key Rotation:**
- **Frequency:** Rotate GEMINI_API_KEY every 90 days
- **Procedure:** Generate new key in Google Cloud Console → Update VPS environment → Restart services → Revoke old key

**Secret Storage:**
- **Prohibited:** No API keys or secrets in Git or Dockerfiles
- **Standard:** External .env file or dedicated secrets manager (HashiCorp Vault / Google Secret Manager)

**Document Backups:**
| Type | Frequency | Method |
|------|-----------|--------|
| **Local** | Daily | Compressed pg_dump of metadata and vectors |
| **Offsite** | Weekly | Encrypted sync of /data/public and /data/confidential volumes |
| **Validation** | Monthly | Automated "Restore Test" to verify pgvector re-indexing |

---

## 4. Phase 1: Core MVP (Weeks 1-8)

**Goal:** Deliver a working end-to-end pipeline from document upload to conversational AI answers via **Gemini Flash** with source citations, plus Telegram bot integration.

### Sprint 1: Foundation (Weeks 1-2)
**Theme:** Infrastructure + Auth + Data Models

| Task | Description | Deliverable |
|------|-------------|-------------|
| Docker Compose | All SOWKNOW services (8 containers), resource limits, health checks, sowknow-net network | Working dev environment |
| PostgreSQL + pgvector | Schema, Alembic migrations, pgvector extension, full-text search indexes, GIN indexes | All tables created |
| FastAPI Scaffold | Project structure, middleware, error handling, /health, structured JSON logging | API at :8000 |
| Auth System | JWT login/register, bcrypt hashing, role middleware (Admin/SuperUser/User), httpOnly cookies | POST /api/auth/* working |
| User Management | Admin seeding, CRUD for users, role assignment, can_access_confidential flag | Admin can manage users |
| Next.js Scaffold | TypeScript, Tailwind, layout, auth pages, PWA manifest, next-intl (FR/EN) | Frontend at :3000 |
| Nginx Config | Reverse proxy, TLS (Let's Encrypt), rate limiting, static file serving | HTTPS working |
| Ollama Connection | Verify shared Ollama reachable from Docker (extra_hosts config), health check endpoint | Ollama ping working |
| **Gemini API Setup** | **Google Generative AI SDK integration, API key configuration, context caching enablement** | **Gemini Flash responding** |

**Exit Criteria:** Admin logs in, sees empty dashboard, all 8 containers healthy, HTTPS working, Ollama reachable, **Gemini API connected**.

### Sprint 2: Document Pipeline (Weeks 3-4)
**Theme:** Upload + OCR + Text Extraction + Storage

| Task | Description | Deliverable |
|------|-------------|-------------|
| Upload API | Multipart upload, file validation, Public/Confidential bucket routing | POST /api/upload working |
| Upload UI | Drag-and-drop (react-dropzone), file type validation, progress bar, batch support | Upload page functional |
| Celery + Redis | Task queue, worker config, beat scheduler, retry policies, dead letter queue | Async tasks running |
| Hunyuan-OCR | API client for Base/Large modes, image preprocessing, text extraction, error handling | OCR processing images |
| Text Extraction | PyPDF2 for PDFs, python-docx for DOCX, plain text for TXT/MD/JSON | All formats extracted |
| Document List UI | Table: filename, size, type, date, status (Indexed/Processing/Error), pagination | /documents page |
| Processing Queue | Status tracking (queued/processing/indexed/error), progress indicators in dashboard | Queue visible |
| File Storage | Docker volumes (sowknow-public, sowknow-confidential), file serving API | Docs stored and retrievable |

**Exit Criteria:** Admin uploads files via web, sees them processed (OCR for images, text extraction for PDFs), views document list with status.

### Sprint 3: Search + RAG + Chat (Weeks 5-6)
**Theme:** Embedding Pipeline + Hybrid Search + Gemini Flash Chat + Ollama Routing

| Task | Description | Deliverable |
|------|-------------|-------------|
| Text Chunking | Recursive character splitter (512 tokens, 50 overlap), metadata preservation | Chunks generated on upload |
| Embedding | multilingual-e5-large in Celery worker, batch processing, pgvector storage | Vectors for all chunks |
| Hybrid Search | pgvector cosine similarity + full-text search, role-based filtering, relevance scoring | POST /api/search working |
| Search UI | Search bar, result cards with snippets, relevance scores, source links, FR/EN | /search page functional |
| **Gemini Integration** | **Gemini Flash API client (google-generativeai), streaming SSE, context packing with caching (up to 1M tokens)** | **Gemini Flash responding with cache** |
| Chat API | Session management, message history, source citations, llm_used tracking | POST /api/chat/* working |
| Chat UI | ChatGPT-like interface, streaming responses, citations, session list, model indicator | /chat page functional |
| Confidential Routing | Auto-detect confidential docs in retrieved chunks, switch to Ollama, log decisions | LLM routing working |
| **UI Indicators** | **"Local LLM is thinking..." for Ollama; cache hit/miss display for Gemini** | **Clear model status display** |

**Exit Criteria:** Users search by natural language, get relevant results. Multi-turn chat works via **Gemini Flash with context caching**. Confidential queries auto-route to Ollama. Model indicator shows active LLM + cache status.

### Sprint 4: Telegram + Dashboard + QA (Weeks 7-8)
**Theme:** Telegram Bot + Admin Dashboard + Anomalies + Production Deploy

| Task | Description | Deliverable |
|------|-------------|-------------|
| Telegram Bot | python-telegram-bot: file upload, search queries, chat (Gemini Flash), multi-turn sessions | Bot responding |
| Telegram Auth | User ID to SOWKNOW account mapping, role-based access | Auth working |
| Caption Tags | Parse 'public'/'confidential' + comments/tags from file captions | Visibility control working |
| Dashboard | Total docs, uploads today, pages indexed, **Gemini cache hit-rate**, system health cards | Dashboard with live stats |
| Anomaly Report | 09:00 AM daily via Celery Beat: docs in 'processing' >24h, **cache miss alerts** | Anomalies in dashboard |
| Role-Based UI | Hide Upload/Settings/KG for non-admin, hide Confidential for User role | UI respects all roles |
| Error Handling | Graceful degradation for all API failures, Ollama unavailable fallback messaging | UI never crashes |
| Language Toggle | French (default) / English selector, persistent preference | Bilingual UI working |
| E2E Testing | Critical paths: upload > process > search > chat > Telegram > confidential routing | All paths validated |
| VPS Deploy | Production deploy to Hostinger, SSL, DNS, monitoring, backup automation | System live |

**Phase 1 Exit Criteria:** Complete MVP live on production. Upload via web + Telegram. Search + chat via **Gemini Flash with context caching**. Confidential docs route to shared Ollama. Dashboard with stats, **cache metrics**, and anomalies. All 5 users onboarded.

---

## 5. Phase 2: Intelligence Layer (Weeks 9-14)

**Goal:** Add **Gemini Flash-powered** Smart Collections, Smart Folders, automated reports, and intelligent categorization.

### Sprint 5: Smart Collections (Weeks 9-10)
**Theme:** Natural Language Collections + Intent Parsing via Gemini Flash

| Task | Description | Deliverable |
|------|-------------|-------------|
| Intent Parser | **Gemini Flash extracts: keywords, date ranges, entities, document types from natural language** | Structured intent extraction |
| Collection API | Create collection from NL query, gather docs, persist with metadata and AI summary | POST /api/collections |
| Collection UI | Input field, document grid, **Gemini summary display**, save/name collection | /collections page |
| Follow-up Q&A | Multi-turn conversation scoped to gathered documents only (**with context caching**) | Context-scoped chat |
| Temporal Filtering | Date range extraction, scoped search within time periods | "Docs from 2020" works |
| Collection Save | Persist: name, query, document IDs, AI summary, creation date | Saved collections browsable |

### Sprint 6: Smart Folders + Reports (Weeks 11-12)
**Theme:** AI Content Generation + PDF Reports + Auto-Tagging

| Task | Description | Deliverable |
|------|-------------|-------------|
| Smart Folders API | User inputs topic, **Gemini Flash searches related docs and generates article/content** | POST /api/smart-folders/generate |
| Smart Folders UI | Topic input, document preview, generated content display, save as new document | /smart-folders page |
| Admin Confidential | Admin Smart Folder requests include Confidential docs (routed via Ollama) | Vault analysis working |
| Report Generation | **Gemini Flash creates Short/Standard/Comprehensive reports from collections** | 3 report templates |
| PDF Export | Professional PDF: cover, summary, document list, analysis, citations | Downloadable PDF reports |
| AI Auto-Tagging | On ingestion: **Gemini Flash extracts topic, entities, importance, language** | Auto-tags on uploads |
| Similarity Grouping | Cluster similar documents by embedding similarity (all IDs, all balance sheets) | Similar docs suggested |

### Sprint 7: Mac Agent + Polish (Weeks 13-14)
**Theme:** Source Sync + Phase 2 QA

| Task | Description | Deliverable |
|------|-------------|-------------|
| Mac Sync Agent | Lightweight Python agent for manual file sync from iCloud/Dropbox/local folders | Agent installable |
| Selective Sync | User chooses folders, agent scans and uploads new/modified files via API | Folder selection working |
| Deduplication | Hash-based duplicate detection, skip already-uploaded files | No duplicate uploads |
| Performance Tuning | Embedding batch optimization, **Gemini context cache optimization**, memory profiling | Measurable improvements |
| Phase 2 E2E Testing | Full test: collections, smart folders, reports, auto-tagging, Mac agent | All Phase 2 validated |
| Documentation | API docs update, user guide for Smart Collections and Smart Folders | Docs updated |

**Phase 2 Exit Criteria:** Smart Collections via NL (**Gemini Flash**). Smart Folders generate articles from docs. PDF reports in 3 formats. Auto-tags on upload. Mac agent syncs files. **Context cache hit-rate > 50% for frequent collections.**

---

## 6. Phase 3: Advanced Reasoning (Weeks 15-20)

**Goal:** Build the knowledge graph, implement graph-augmented retrieval, synthesis engine, and multi-agent search architecture.

### Sprint 8: Knowledge Graph (Weeks 15-16)

| Task | Description | Deliverable |
|------|-------------|-------------|
| Entity Extraction | **Gemini Flash extracts people, organizations, concepts, locations from all docs** | Entities stored |
| Relationship Mapping | Connect entities across documents (person-works-at-company, concept-related) | Relationships created |
| Timeline Construction | Chronological ordering, detect evolution patterns | Timeline data model |
| Graph Storage | PostgreSQL tables for entities + relationships (no separate graph DB) | Graph queryable via SQL |
| Graph Visualization | Interactive knowledge graph explorer in admin dashboard | Visual graph working |

### Sprint 9: Graph-RAG + Synthesis (Weeks 17-18)

| Task | Description | Deliverable |
|------|-------------|-------------|
| Graph-RAG | Query knowledge graph for related concepts, expand retrieval beyond keywords | Graph-augmented search |
| Synthesis Pipeline | Map-Reduce via **Gemini Flash**: retrieve 20-50 chunks, summarize, synthesize patterns | Broad questions answered |
| Temporal Reasoning | Arrange chunks by date, describe thought evolution over time | Evolution queries work |
| Progressive Revelation | Time-based access controls for heirs on confidential content | Scheduled content reveal |
| Family Context | **Gemini Flash generates explanations of document significance and curator perspective** | Context notes on docs |

### Sprint 10: Agentic Search + Final QA (Weeks 19-20)

| Task | Description | Deliverable |
|------|-------------|-------------|
| Clarification Agent | **Gemini Flash analyzes query, decides if clarification needed, asks follow-ups** | Smart query refinement |
| Researcher Agent | Executes search using hybrid + graph + temporal methods | Comprehensive retrieval |
| Verification Agent | **Gemini Flash scores answer quality, triggers re-search if insufficient** | Quality gate working |
| Answer Agent | Formats response with citations, highlights, confidence indicators | Polished answers |
| Agent Orchestration | Coordinate flow, fallback to simple RAG if agents fail | Full pipeline working |
| Full System QA | E2E testing all features, load testing with 5 concurrent users | Production-ready |
| Documentation | Complete API docs, user guide (FR/EN), admin manual, deployment runbook | Full docs delivered |
| Monitoring | Advanced metrics: query latency, **Gemini costs + cache efficiency**, Ollama usage, storage | Ops dashboard live |

**Phase 3 Exit Criteria:** Knowledge Graph operational. Graph-RAG improves search. Synthesis answers broad questions. Agentic search pipeline functional. Full documentation complete.

---

## 7. Risk Matrix

| Risk | Phase | Impact | Prob. | Mitigation |
|------|-------|--------|-------|------------|
| Shared Ollama overloaded by other projects | 1 | Medium | Medium | Request queuing, timeout handling, graceful fallback messaging to user |
| **Gemini API downtime or latency** | 1 | High | Low | **Retry with exponential backoff, cache responses, queue pending requests** |
| **Gemini API cost overrun** | 1-2 | Medium | Medium | **Daily cost monitoring + cache hit-rate tracking, budget caps ($50/day alert)** |
| VPS memory contention (shared) | 1 | High | Medium | Strict Docker limits (6.4GB total), stagger heavy jobs, monitor VPS-wide |
| OCR accuracy below 97% | 1 | Medium | Low | Hunyuan-OCR primary, **Tesseract fallback for bulk uploads** |
| **Embedding model RAM pressure** | 1 | Medium | Medium | **multilingual-e5-base fallback (900MB vs 1.3GB) if OOM detected** |
| **Cache hit-rate below target** | 1-2 | Medium | Medium | **Optimize pinned collections, alert if < 50%, review query patterns** |
| Search quality insufficient | 1-2 | High | Medium | Hybrid search tuning, relevance feedback, weight adjustment |
| Scope creep in Phase 2-3 | 2-3 | High | High | Strict sprint scope, defer nice-to-haves, weekly review |
| Knowledge Graph complexity | 3 | Medium | High | PostgreSQL-only graph, simple entity model, iterate on quality |

---

## 8. External Dependencies

| Dependency | Type | Risk | Fallback |
|------------|------|------|----------|
| Hostinger VPS | Infrastructure | Low | Migrate to Hetzner/OVH |
| **Google Gemini API** | **Cloud LLM** | **Medium** | **OpenRouter (Claude Haiku / GPT-4o-mini) as backup** |
| Shared Ollama | Local LLM | Medium | Queue requests, degrade gracefully if busy |
| Hunyuan-OCR API | OCR Service | Medium | Tesseract OCR (local, lower quality) |
| Telegram Bot API | Communication | Low | Very stable; no fallback needed |
| sentence-transformers | Embedding | Low | Pin version for stability |

---

## 9. Production Deployment Checklist

### 9.1 Pre-Launch (Sprint 4)

- All 8 SOWKNOW containers start cleanly with resource limits (<6.4GB total)
- Health checks passing for all services
- **Gemini API health check passing with valid API key**
- Shared Ollama reachable from SOWKNOW containers via localhost:11434
- HTTPS working with valid SSL certificate
- Admin account created with strong password
- **GEMINI_API_KEY in .env (not in version control)**, rotated every 90 days
- Backup automation configured and tested
- Rate limiting active at Nginx level
- Monitoring alerts for memory, disk, **Gemini costs, cache efficiency** configured
- Telegram bot responding to messages
- French and English UI both functional
- Confidential routing verified: **Gemini Flash for public, Ollama for confidential**
- **Context caching enabled for pinned collections**
- **Cache hit-rate baseline established (>30% target)**

### 9.2 Post-Launch Monitoring (First 2 Weeks)

- Daily: SOWKNOW container memory vs. 6.4GB budget
- Daily: VPS total memory usage (including Ollama and other projects)
- **Daily: Gemini API cost tracking + cache hit-rate analysis**
- Daily: Processing anomalies report (09:00 AM)
- **Daily: Alert if cache hit-rate < 50% for high-volume collections**
- Weekly: Search quality spot-check (10 sample queries FR + EN)
- Weekly: Backup restoration test
- Weekly: Disk usage trending
- **Weekly: Review context cache performance and optimize pinned collections**

---

## 10. Success Criteria by Phase

| Phase | Criteria | Measurement |
|-------|----------|-------------|
| Phase 1 (Wk 8) | 5 users upload, search, and chat successfully | Manual testing by all 5 users |
| Phase 1 (Wk 8) | OCR accuracy >97% on 50-doc sample batch | Automated accuracy check |
| Phase 1 (Wk 8) | **Gemini Flash search in <3s with cache, Ollama in <8s** | Latency monitoring |
| Phase 1 (Wk 8) | Confidential routing 100% accurate (no PII to cloud) | Audit log review |
| **Phase 1 (Wk 8)** | **Context cache hit-rate > 30% for frequent queries** | **Cache analytics** |
| Phase 2 (Wk 14) | Smart Collections + Smart Folders adopted by >3/5 users | Usage analytics |
| Phase 2 (Wk 14) | PDF reports generated >90% success rate | Error tracking |
| **Phase 2 (Wk 14)** | **Cache hit-rate > 50% for Smart Folders/Collections** | **Performance optimization** |
| Phase 3 (Wk 20) | Graph-RAG improves relevance >15% vs Phase 1 | A/B comparison |
| Phase 3 (Wk 20) | Agentic search handles >80% queries without fallback | Agent success rate |

---

## 11. Next Phase Plan (Post-Amendment)

### 11.1 Immediate Actions (Week 1)

| Priority | Task | Owner | Due |
|----------|------|-------|-----|
| **P0** | Acquire GEMINI_API_KEY from Google Cloud Console | Dev | Day 1 |
| **P0** | Install `google-generativeai` package in backend | Dev | Day 1 |
| **P0** | Update .env template with GEMINI_API_KEY placeholder | Dev | Day 1 |
| **P0** | Implement Gemini health check endpoint | Dev | Day 2 |
| **P1** | Create context caching service wrapper | Dev | Day 3 |
| **P1** | Update LLM router logic for Gemini routing | Dev | Day 4 |
| **P1** | Add "Local LLM is thinking..." UI indicator | Frontend | Day 5 |
| **P2** | Document Gemini API cost monitoring strategy | DevOps | Week 1 |

### 11.2 Sprint 1 Modified Tasks

| Original Task | Modification |
|---------------|--------------|
| Moonshot Integration | **REPLACED:** Gemini Flash Integration with google-generativeai SDK |
| Kimi 2.5 API client | **REPLACED:** Gemini Flash API client with streaming and context caching |
| Context packing (10 msgs) | **ENHANCED:** Up to 1M token context with automatic caching for recurring queries |
| Cost monitoring | **ENHANCED:** Track both token costs AND cache hit-rate efficiency |

### 11.3 Technical Debt Tracking

| Item | Introduced By | Impact | Planned Resolution |
|------|---------------|--------|-------------------|
| Kimi 2.5 legacy code | v1.0 → v1.2 migration | Medium | Remove all Moonshot API references by Sprint 2 |
| Cache hit-rate alerting | New requirement | Low | Implement by Sprint 3 |
| Celery memory optimization | New advisory | Medium | Monitor and potentially reduce to 1GB if stable |

---

## Appendix A: Gemini Flash Integration Guide

### A.1 Environment Variables

```bash
# .env file (NEVER commit to Git)
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.0-flash-exp  # or gemini-1.5-flash
GEMINI_MAX_TOKENS=1000000
GEMINI_CACHE_TTL=3600  # 1 hour
GEMINI_DAILY_BUDGET_CAP=50.00  # USD
```

### A.2 Python SDK Setup

```python
# backend/app/llm/gemini_client.py
import google.generativeai as genai
from google.generativeai.caching import CachedContent

genai.configure(api_key=settings.GEMINI_API_KEY)

class GeminiClient:
    def __init__(self):
        self.model = genai.GenerativeModel(settings.GEMINI_MODEL)
        self.cache = {}

    async def generate_with_cache(self, prompt: str, cache_key: str = None):
        if cache_key and cache_key in self.cache:
            cached = self.cache[cache_key]
            # Use cached content for cost savings
            return cached.generate_content(prompt)

        response = await self.model.generate_content_async(prompt)
        return response
```

### A.3 Context Caching Strategy

| Scenario | Caching Strategy | Expected Savings |
|----------|------------------|------------------|
| Pinned Collections | Cache full collection text | 60-80% on recurring queries |
| Smart Folders | Cache generated article | 80% on re-reads |
| Follow-up Q&A | Cache conversation context | 50-70% on multi-turn chats |
| Daily Reports | Cache report template | 40-60% on similar reports |

---

**End of Document v1.2**
