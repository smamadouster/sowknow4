# SOWKNOW Multi-Generational Legacy Knowledge System
## Execution Plan v1.1

**Date:** February 2026
**Classification:** CONFIDENTIAL
**Timeline:** 20 Weeks (3 Phases) | LLM: Kimi 2.5 + Shared Ollama

---

## 1. Executive Summary

The SOWKNOW execution plan spans 20 weeks across 3 phases. Phase 1 (8 weeks) delivers the Core MVP: document upload, OCR processing via Hunyuan API, RAG-powered search using multilingual-e5-large embeddings, conversational AI chat via Kimi 2.5, confidential document routing via shared Ollama, and Telegram bot integration. Phase 2 (6 weeks) adds Smart Collections, Smart Folders, report generation, and auto-tagging. Phase 3 (6 weeks) implements Knowledge Graph, Graph-RAG, synthesis engine, and agentic search.

Each sprint is 2 weeks. Every sprint ends with a deployable increment. SOWKNOW uses the shared Ollama instance already running on the VPS, and Kimi 2.5 via Moonshot API for all cloud AI features, consistent with the broader Aicha platform ecosystem.

### 1.1 Timeline Overview

| Phase | Duration | Sprints | Key Deliverable |
|-------|----------|---------|-----------------|
| Phase 1: Core MVP | Weeks 1-8 | Sprint 1-4 | Full document pipeline + Kimi 2.5 chat + Telegram |
| Phase 2: Intelligence | Weeks 9-14 | Sprint 5-7 | Smart Collections + Smart Folders + reports |
| Phase 3: Advanced | Weeks 15-20 | Sprint 8-10 | Knowledge Graph + Graph-RAG + agentic search |

### 1.2 Resource Constraints

| Resource | Specification | Impact |
|----------|---------------|--------|
| VPS | Hostinger 16GB RAM, 200GB Disk (shared) | ~6.4GB for SOWKNOW containers; rest for Ollama + OS + other projects |
| GPU | None | OCR via Hunyuan API; Ollama CPU inference (shared) |
| Ollama | Shared instance, already running | No container management; connect via LOCAL_LLM_URL |
| Cloud LLM | Kimi 2.5 via Moonshot API | Pay-per-token; daily cost monitoring required |
| Users at Launch | 5 | Low concurrency; simplified auth sufficient |
| Document Ingestion | Incremental | No big-bang migration; pipeline ramps up gradually |

---

## 2. Phase 1: Core MVP (Weeks 1-8)

**Goal:** Deliver a working end-to-end pipeline from document upload to conversational AI answers via Kimi 2.5 with source citations, plus Telegram bot integration.

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

**Exit Criteria:** Admin logs in, sees empty dashboard, all 8 containers healthy, HTTPS working, Ollama reachable.

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
**Theme:** Embedding Pipeline + Hybrid Search + Kimi 2.5 Chat + Ollama Routing

| Task | Description | Deliverable |
|------|-------------|-------------|
| Text Chunking | Recursive character splitter (512 tokens, 50 overlap), metadata preservation | Chunks generated on upload |
| Embedding | multilingual-e5-large in Celery worker, batch processing, pgvector storage | Vectors for all chunks |
| Hybrid Search | pgvector cosine similarity + full-text search, role-based filtering, relevance scoring | POST /api/search working |
| Search UI | Search bar, result cards with snippets, relevance scores, source links, FR/EN | /search page functional |
| Moonshot Integration | Kimi 2.5 API client (httpx async), streaming SSE, context packing (10 msgs + chunks) | Kimi 2.5 responding |
| Chat API | Session management, message history, source citations, llm_used tracking | POST /api/chat/* working |
| Chat UI | ChatGPT-like interface, streaming responses, citations, session list, model indicator | /chat page functional |
| Confidential Routing | Auto-detect confidential docs in retrieved chunks, switch to Ollama, log decisions | LLM routing working |

**Exit Criteria:** Users search by natural language, get relevant results. Multi-turn chat works via Kimi 2.5. Confidential queries auto-route to Ollama. Model indicator shows active LLM.

### Sprint 4: Telegram + Dashboard + QA (Weeks 7-8)
**Theme:** Telegram Bot + Admin Dashboard + Anomalies + Production Deploy

| Task | Description | Deliverable |
|------|-------------|-------------|
| Telegram Bot | python-telegram-bot: file upload, search queries, chat (Kimi 2.5), multi-turn sessions | Bot responding |
| Telegram Auth | User ID to SOWKNOW account mapping, role-based access | Auth working |
| Caption Tags | Parse 'public'/'confidential' + comments/tags from file captions | Visibility control working |
| Dashboard | Total docs, uploads today, pages indexed, system health cards (Legal-BERT style) | Dashboard with live stats |
| Anomaly Report | 09:00 AM daily via Celery Beat: docs in 'processing' >24h shown in Anomalies Bucket | Anomalies in dashboard |
| Role-Based UI | Hide Upload/Settings/KG for non-admin, hide Confidential for User role | UI respects all roles |
| Error Handling | Graceful degradation for all API failures, Ollama unavailable fallback messaging | UI never crashes |
| Language Toggle | French (default) / English selector, persistent preference | Bilingual UI working |
| E2E Testing | Critical paths: upload > process > search > chat > Telegram > confidential routing | All paths validated |
| VPS Deploy | Production deploy to Hostinger, SSL, DNS, monitoring, backup automation | System live |

**Phase 1 Exit Criteria:** Complete MVP live on production. Upload via web + Telegram. Search + chat via Kimi 2.5. Confidential docs route to shared Ollama. Dashboard with stats and anomalies. All 5 users onboarded.

---

## 3. Phase 2: Intelligence Layer (Weeks 9-14)

**Goal:** Add Kimi 2.5-powered Smart Collections, Smart Folders, automated reports, and intelligent categorization.

### Sprint 5: Smart Collections (Weeks 9-10)
**Theme:** Natural Language Collections + Intent Parsing via Kimi 2.5

| Task | Description | Deliverable |
|------|-------------|-------------|
| Intent Parser | Kimi 2.5 extracts: keywords, date ranges, entities, document types from natural language | Structured intent extraction |
| Collection API | Create collection from NL query, gather docs, persist with metadata and AI summary | POST /api/collections |
| Collection UI | Input field, document grid, Kimi 2.5 summary display, save/name collection | /collections page |
| Follow-up Q&A | Multi-turn conversation scoped to gathered documents only (Kimi 2.5) | Context-scoped chat |
| Temporal Filtering | Date range extraction, scoped search within time periods | "Docs from 2020" works |
| Collection Save | Persist: name, query, document IDs, AI summary, creation date | Saved collections browsable |

### Sprint 6: Smart Folders + Reports (Weeks 11-12)
**Theme:** AI Content Generation + PDF Reports + Auto-Tagging

| Task | Description | Deliverable |
|------|-------------|-------------|
| Smart Folders API | User inputs topic, Kimi 2.5 searches related docs and generates article/content | POST /api/smart-folders/generate |
| Smart Folders UI | Topic input, document preview, generated content display, save as new document | /smart-folders page |
| Admin Confidential | Admin Smart Folder requests include Confidential docs (routed via Ollama) | Vault analysis working |
| Report Generation | Kimi 2.5 creates Short/Standard/Comprehensive reports from collections | 3 report templates |
| PDF Export | Professional PDF: cover, summary, document list, analysis, citations | Downloadable PDF reports |
| AI Auto-Tagging | On ingestion: Kimi 2.5 extracts topic, entities, importance, language | Auto-tags on uploads |
| Similarity Grouping | Cluster similar documents by embedding similarity (all IDs, all balance sheets) | Similar docs suggested |

### Sprint 7: Mac Agent + Polish (Weeks 13-14)
**Theme:** Source Sync + Phase 2 QA

| Task | Description | Deliverable |
|------|-------------|-------------|
| Mac Sync Agent | Lightweight Python agent for manual file sync from iCloud/Dropbox/local folders | Agent installable |
| Selective Sync | User chooses folders, agent scans and uploads new/modified files via API | Folder selection working |
| Deduplication | Hash-based duplicate detection, skip already-uploaded files | No duplicate uploads |
| Performance Tuning | Embedding batch optimization, Kimi 2.5 prompt caching, memory profiling | Measurable improvements |
| Phase 2 E2E Testing | Full test: collections, smart folders, reports, auto-tagging, Mac agent | All Phase 2 validated |
| Documentation | API docs update, user guide for Smart Collections and Smart Folders | Docs updated |

**Phase 2 Exit Criteria:** Smart Collections via NL (Kimi 2.5). Smart Folders generate articles from docs. PDF reports in 3 formats. Auto-tags on upload. Mac agent syncs files.

---

## 4. Phase 3: Advanced Reasoning (Weeks 15-20)

**Goal:** Build the knowledge graph, implement graph-augmented retrieval, synthesis engine, and multi-agent search architecture.

### Sprint 8: Knowledge Graph (Weeks 15-16)

| Task | Description | Deliverable |
|------|-------------|-------------|
| Entity Extraction | Kimi 2.5 extracts people, organizations, concepts, locations from all docs | Entities stored |
| Relationship Mapping | Connect entities across documents (person-works-at-company, concept-related) | Relationships created |
| Timeline Construction | Chronological ordering, detect evolution patterns | Timeline data model |
| Graph Storage | PostgreSQL tables for entities + relationships (no separate graph DB) | Graph queryable via SQL |
| Graph Visualization | Interactive knowledge graph explorer in admin dashboard | Visual graph working |

### Sprint 9: Graph-RAG + Synthesis (Weeks 17-18)

| Task | Description | Deliverable |
|------|-------------|-------------|
| Graph-RAG | Query knowledge graph for related concepts, expand retrieval beyond keywords | Graph-augmented search |
| Synthesis Pipeline | Map-Reduce via Kimi 2.5: retrieve 20-50 chunks, summarize, synthesize patterns | Broad questions answered |
| Temporal Reasoning | Arrange chunks by date, describe thought evolution over time | Evolution queries work |
| Progressive Revelation | Time-based access controls for heirs on confidential content | Scheduled content reveal |
| Family Context | Kimi 2.5 generates explanations of document significance and curator perspective | Context notes on docs |

### Sprint 10: Agentic Search + Final QA (Weeks 19-20)

| Task | Description | Deliverable |
|------|-------------|-------------|
| Clarification Agent | Kimi 2.5 analyzes query, decides if clarification needed, asks follow-ups | Smart query refinement |
| Researcher Agent | Executes search using hybrid + graph + temporal methods | Comprehensive retrieval |
| Verification Agent | Kimi 2.5 scores answer quality, triggers re-search if insufficient | Quality gate working |
| Answer Agent | Formats response with citations, highlights, confidence indicators | Polished answers |
| Agent Orchestration | Coordinate flow, fallback to simple RAG if agents fail | Full pipeline working |
| Full System QA | E2E testing all features, load testing with 5 concurrent users | Production-ready |
| Documentation | Complete API docs, user guide (FR/EN), admin manual, deployment runbook | Full docs delivered |
| Monitoring | Advanced metrics: query latency, Kimi 2.5 costs, Ollama usage, storage | Ops dashboard live |

**Phase 3 Exit Criteria:** Knowledge Graph operational. Graph-RAG improves search. Synthesis answers broad questions. Agentic search pipeline functional. Full documentation complete.

---

## 5. Risk Matrix

| Risk | Phase | Impact | Prob. | Mitigation |
|------|-------|--------|-------|------------|
| Shared Ollama overloaded by other projects | 1 | Medium | Medium | Request queuing, timeout handling, graceful fallback messaging to user |
| Moonshot API downtime or latency | 1 | High | Low | Retry with exponential backoff, cache responses, queue pending requests |
| Kimi 2.5 cost overrun | 1-2 | Medium | Medium | Daily cost monitoring, batch processing, prompt optimization |
| VPS memory contention (shared) | 1 | High | Medium | Strict Docker limits (6.4GB total), stagger heavy jobs, monitor VPS-wide |
| OCR accuracy below 97% | 1 | Medium | Low | Multi-mode OCR, manual review queue for low-confidence extractions |
| Embedding model RAM pressure | 1 | Medium | Medium | multilingual-e5-base fallback (900MB vs 1.3GB), lazy loading |
| Search quality insufficient | 1-2 | High | Medium | Hybrid search tuning, relevance feedback, weight adjustment |
| Scope creep in Phase 2-3 | 2-3 | High | High | Strict sprint scope, defer nice-to-haves, weekly review |
| Knowledge Graph complexity | 3 | Medium | High | PostgreSQL-only graph, simple entity model, iterate on quality |

---

## 6. External Dependencies

| Dependency | Type | Risk | Fallback |
|------------|------|------|----------|
| Hostinger VPS | Infrastructure | Low | Migrate to Hetzner/OVH |
| Moonshot API (Kimi 2.5) | Cloud LLM | Medium | OpenRouter (Gemini Flash / Claude Haiku) |
| Shared Ollama | Local LLM | Medium | Queue requests, degrade gracefully if busy |
| Hunyuan-OCR API | OCR Service | Medium | Tesseract OCR (local, lower quality) |
| Telegram Bot API | Communication | Low | Very stable; no fallback needed |
| sentence-transformers | Embedding | Low | Pin version for stability |

---

## 7. Production Deployment Checklist

### 7.1 Pre-Launch (Sprint 4)

- All 8 SOWKNOW containers start cleanly with resource limits (<6.4GB total)
- Health checks passing for all services
- Shared Ollama reachable from SOWKNOW containers via localhost:11434
- Kimi 2.5 (Moonshot API) responding with valid API key
- HTTPS working with valid SSL certificate
- Admin account created with strong password
- Backup automation configured and tested
- Secrets in .env file, not in version control
- Rate limiting active at Nginx level
- Monitoring alerts for memory, disk, errors configured
- Telegram bot responding to messages
- French and English UI both functional
- Confidential routing verified: Kimi 2.5 for public, Ollama for confidential

### 7.2 Post-Launch Monitoring (First 2 Weeks)

- Daily: SOWKNOW container memory vs. 6.4GB budget
- Daily: VPS total memory usage (including Ollama and other projects)
- Daily: Moonshot API cost tracking
- Daily: Processing anomalies report (09:00 AM)
- Weekly: Search quality spot-check (10 sample queries FR + EN)
- Weekly: Backup restoration test
- Weekly: Disk usage trending

---

## 8. Success Criteria by Phase

| Phase | Criteria | Measurement |
|-------|----------|-------------|
| Phase 1 (Wk 8) | 5 users upload, search, and chat successfully | Manual testing by all 5 users |
| Phase 1 (Wk 8) | OCR accuracy >97% on 50-doc sample batch | Automated accuracy check |
| Phase 1 (Wk 8) | Kimi 2.5 search answers in <3s, Ollama in <8s | Latency monitoring |
| Phase 1 (Wk 8) | Confidential routing 100% accurate (no PII to cloud) | Audit log review |
| Phase 2 (Wk 14) | Smart Collections + Smart Folders adopted by >3/5 users | Usage analytics |
| Phase 2 (Wk 14) | PDF reports generated >90% success rate | Error tracking |
| Phase 3 (Wk 20) | Graph-RAG improves relevance >15% vs Phase 1 | A/B comparison |
| Phase 3 (Wk 20) | Agentic search handles >80% queries without fallback | Agent success rate |

---

**End of Document**