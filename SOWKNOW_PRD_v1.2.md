# SOWKNOW Multi-Generational Legacy Knowledge System
## Product Requirements Document v1.2

**Date:** February 2026
**Last updated:** April 2026
**Classification:** CONFIDENTIAL

---

## 1. Vision & Strategic Overview

SOWKNOW is a multi-generational legacy knowledge system that unifies scattered digital life into an intelligent, conversational wisdom vault. Unlike standard document managers, it preserves not just documents but the context, relationships, and personal significance behind them, creating a living digital heritage accessible to the curator and future generations.

### 1.1 Problem Statement

Over 100GB of personal and professional knowledge is scattered across Mac HDD, iCloud, Dropbox, Google Drive, iPhone photos, and various digital libraries. Critical information is difficult to find, impossible to cross-reference, and at risk of being lost to future generations. Existing solutions lack the privacy controls, multi-language support, and contextual understanding required for a true legacy knowledge system.

### 1.2 Product Vision

Build a privacy-first, AI-powered knowledge vault that transforms raw document archives into an intelligent, queryable wisdom system. The platform combines OCR-powered document ingestion, semantic search with RAG, and conversational AI to enable natural-language interaction with an entire lifetime of accumulated knowledge.

### 1.3 AI Strategy

SOWKNOW uses a tri-LLM architecture:

- **OpenRouter (Mistral Small 2603):** Primary LLM for all intelligent features including RAG answer synthesis, Smart Collections analysis, report generation, chat queries, and Telegram chat. Selected for its strong multilingual performance (French/English) and competitive pricing. MiniMax M2.7 is the fallback provider for search and article generation tasks.

- **Metadata-Only Cloud Routing (Confidential documents):** Confidential document processing strips raw content at the service layer (`chat_service.py`) before the LLM prompt is assembled. This means cloud providers (OpenRouter/MiniMax) can be used even for confidential queries — the sensitive text never reaches the API. Ollama (local LLM) is **not currently running** on the VPS; it was intentionally removed due to CPU performance constraints. If Ollama is re-added (planned as Phase 7C candidate with Gemma 2B), it will automatically become the preferred provider for confidential queries via the existing router logic.

- **multilingual-e5-large (Local):** Embedding model for vector generation. Runs locally via sentence-transformers for generating 1024-dimensional vectors optimized for French/English semantic search. Powers the RAG retrieval pipeline.

### 1.4 Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Information retrieval time reduction | >70% | Average query-to-answer time vs. manual search |
| OCR text extraction accuracy | >97% | Automated quality checks on processed documents |
| System uptime | Not formally measured | Health checks were broken until Phase 4 fix; monitoring being established |
| Search result relevance | >90% user satisfaction | Relevance scoring on first 5 results |
| Document processing throughput | >50 docs/hour | Queue processing metrics |
| Multi-language accuracy | >95% for FR/EN | Cross-language query testing |

---

## 2. User Personas & Roles

### 2.1 Primary Personas

**Legacy Curator (Admin)**
- Full system owner with administrative control over all documents, users, and settings
- Manages 100GB+ of content across multiple platforms and formats
- Requires intelligent organization, OCR processing, and cross-source search
- Needs privacy controls to separate sensitive documents from general knowledge base

**Knowledge Heirs (Super Users)**
- Family members who inherit access to curated knowledge
- Can view and search all documents including Confidential section
- Cannot create, modify, or delete documents
- Benefit from contextual explanations and progressive revelation of sensitive content

**General Users**
- Limited access to Public section only
- Can search and download public documents
- No visibility into Confidential section (not even metadata)
- Dashboard restrictions: Upload, Settings, and Knowledge Graph hidden

### 2.2 Role-Based Access Control Matrix

| Capability | Admin | Super User | User |
|------------|-------|------------|------|
| View Public Documents | Yes | Yes | Yes |
| View Confidential Documents | Yes | Yes | No (invisible) |
| Download Public Documents | Yes | Yes | Yes |
| Download Confidential Documents | Yes | Yes | No |
| Upload Documents | Yes | No | No |
| Modify Documents | Yes | No | No |
| Delete Documents | Yes | No | No |
| Access Dashboard | Full | Limited | Restricted |
| Access Settings | Yes | No | No |
| Access Knowledge Graph | Yes | Yes | No |
| Manage Users | Yes | No | No |
| Search Confidential | Yes | Yes | No |
| View Processing Anomalies | Yes | No | No |

---

## 3. Functional Requirements

### 3.1 Document Management

The system manages documents organized into two completely separate storage buckets:

**Public Bucket:** All general documents accessible to all authenticated users. Documents here are indexed, searchable, and processed through OpenRouter (Mistral Small 2603) for AI features.

**Confidential Bucket:** Sensitive documents (IDs, passports, financial records) completely invisible to non-admin users. Not even metadata is exposed. When processed by AI, confidential document content is stripped at the service layer before the LLM prompt — only metadata references reach the cloud provider. This preserves privacy without requiring a local LLM. Confidential access is fully audit-logged with timestamp and user ID.

**Supported File Formats**
PDF, DOCX, PPTX, XLSX, TXT, MD, JSON, Images (JPG, PNG, HEIC), Videos, EPUB, CSV, XML, TIFF, Audio (OGG/voice notes)

**Document Operations**

| Operation | Description | Admin | Others |
|-----------|-------------|-------|---------|
| Upload | Single or batch upload with drag-and-drop interface | Yes | No |
| View | Document viewer with metadata display | All | Public only |
| Modify | Edit metadata, tags, bucket assignment | Yes | No |
| Delete | Remove documents with confirmation | Yes | No |
| Download | Download original file | All | Public only |
| Tag | Add/remove tags for organization | Yes | No |
| Search | Semantic + keyword search | All buckets | Public only |

### 3.2 AI-Powered Processing Pipeline

**OCR Processing (PaddleOCR + Tesseract Fallback)**
Since the hosting VPS has no GPU, all OCR runs locally. PaddleOCR is the primary engine with Tesseract as fallback. Three processing modes:

- **Base Mode (1024x1024):** Standard documents, typed text, forms
- **Large Mode (1280x1280):** Complex layouts, multi-column documents, tables
- **Gundam Mode:** Detailed illustrations, handwritten notes, scanned photos

Primary language: French. Secondary: English. Auto-detection applies appropriate OCR model settings.

**RAG Pipeline**
1. **Text Extraction:** OCR for images/scans, direct extraction for PDFs/DOCX
2. **Chunking:** Recursive character text splitter (512 tokens, 50 token overlap)
3. **Embedding:** multilingual-e5-large model (local, 1024 dimensions) for French/English
4. **Vector Storage:** PostgreSQL with pgvector extension
5. **Retrieval:** Hybrid search combining pgvector cosine similarity + PostgreSQL full-text search with 1.5x RRF tag boost
6. **Generation:** OpenRouter (Mistral Small 2603) synthesizes answers from retrieved chunks with source citations
7. **Confidential Handling:** If retrieved chunks include Confidential docs, raw content is stripped to metadata at the service layer before prompt assembly — privacy is preserved at the application layer, not the router layer

**Intelligent Categorization**
- AI auto-tagging by topic, project, date, and importance level
- Automatic similarity grouping (all IDs, all balance sheets, all solar energy docs)
- Entity extraction: people, organizations, concepts, locations (AgentOrchestrator + 4 agents exist in code; identity profiles being improved)
- Relationship mapping across document sources and time periods

**Voice Transcription**
Telegram voice notes (OGG/OPUS) are processed by whisper-cpp (statically linked) using the ggml-small model (466MB). Encrypted OGG files are decrypted before streaming to whisper. Language is set explicitly via `--language` flag to prevent mislabeling (iOS Safari Web Speech API ignores `lang` attribute for non-default languages). Transcription runs on the celery-light worker.

### 3.3 Conversational AI Chat System

The chat system provides a persistent, threaded conversation interface powered by OpenRouter (Mistral Small 2603) for all queries — both public and confidential contexts. For confidential contexts, content stripping at the service layer ensures no raw sensitive text reaches the provider.

**Core Chat Features**
- Persistent chat sessions with full history
- Streaming responses with typing effect
- Source document citations in every response
- Ability to scope queries to specific document sets or collections
- Multi-language support (French/English queries and responses)
- LLM routing: OpenRouter primary, MiniMax M2.7 fallback; confidential uses metadata-only context

**Query Examples**
- **Context-Aware:** "What was I learning about quantum physics in 2020?"
- **Cross-Reference:** "Show me all documents related to our family vacation planning"
- **Synthesis:** "What insights do I have about leadership across all my notes?"
- **Financial:** "Check the trend of assets on the balance sheets for the last 10 years"
- **Temporal:** "How has my thinking on solar energy evolved over time?"

### 3.4 Smart Collections & Report Generation

Users can create AI-powered collections by describing what they want in natural language. The system uses OpenRouter (Mistral Small 2603) to automatically gather relevant documents, analyze them, and generate reports.

**Collection Workflow**
1. User describes the collection in natural language (up to 500 characters)
2. System parses intent: keywords, date ranges, entities, document types
3. Hybrid search gathers relevant documents (up to 100 per collection)
4. OpenRouter generates summary, identifies themes, and produces requested analysis
5. User can ask follow-up questions scoped to the gathered documents
6. Collection can be saved, named, and exported as PDF

**Report Types**

| Report Type | Length | Use Case |
|-------------|--------|----------|
| Short Summary | 1-2 pages | Quick overview, key findings, executive brief |
| Standard Report | 3-5 pages | Detailed analysis with sections, supporting evidence |
| Comprehensive Report | 5-10+ pages | Full synthesis with timeline, cross-references, appendices |

Collections processing is handled by a dedicated **celery-collections** worker — completely isolated from the document pipeline workers to prevent queue starvation.

### 3.5 Smart Folders / Smart Content (Articles)

Users provide a topic or subject, and the system uses MiniMax M2.7 to search all related documents (Public bucket for regular users; Public + Confidential metadata for Admin), analyze them, and automatically generate an article or content piece. The generated content is saved as a new document in the database.

**Workflow**
1. User inputs a topic/subject via the Smart Folders tab
2. System searches all related documents using hybrid search
3. MiniMax M2.7 analyzes gathered documents and generates article/content
4. New document is automatically created in the database with the generated content
5. Admin requests include Confidential document metadata in the analysis
6. Generated content includes source citations and can be exported as PDF

### 3.6 Telegram Bot Integration

The Telegram bot serves as a mobile-first interface for document upload, knowledge queries, conversational chat, and voice note transcription powered by OpenRouter (Mistral Small 2603).

**Upload Capabilities**
- File upload via attachment (paperclip) — default visibility: Private
- Visibility control via caption: `public` or `confidential`
- Support for comments and tags in caption during upload
- Direct photo/scan upload from iPhone camera

**Chat & Search via Telegram**
- Natural language queries against the knowledge base (powered by OpenRouter)
- Search results with document citations; bucket filtering fixed in Phase 7A
- Multi-turn conversation support with session memory
- French/English language support

**Voice Notes**
- Voice messages transcribed via whisper-cpp (ggml-small, local, no cloud dependency)
- Transcription language set explicitly to avoid iOS Safari locale mismatch
- Transcribed text is treated as a standard chat query after processing

### 3.7 Web Application & PWA

The web application provides the full-featured interface built as a Progressive Web App (PWA) for mobile access via home screen shortcut. Optimized for iPhone Safari with bottom tab navigation, mobile sheets, FAB gestures, and per-page mobile layouts.

**Navigation Tabs**

| Tab | All Users | Admin Only | Description |
|-----|-----------|-------------|-------------|
| Search | Yes | - | Semantic search interface with natural language queries |
| Documents | Yes | - | List view with last 50 documents, metadata, status indicators |
| Assistant AI | Yes | - | Chat interface for conversational queries (OpenRouter / metadata-only for confidential) |
| Collections | Yes | - | Saved smart collections with follow-up capability |
| Smart Folders | Yes | - | AI-generated article/content from document analysis (MiniMax M2.7) |
| Dashboard | - | Yes | System health, stats, pipeline funnel panel, live upload chart (10s polling) |
| Admin/Settings | - | Yes | User management, system configuration |

**Dashboard (Admin)**
Total Documents count, Uploads Today, Pages Indexed, Processing Queue status, live pipeline funnel panel, real uploads chart with 10-second polling. Daily anomaly report at 09:00 AM showing all documents stuck in 'processing' status for more than 24 hours. Graceful handling of API downtime with non-intrusive empty states.

### 3.8 Processing Anomaly Monitoring

Every day at 09:00 AM, the Admin dashboard surfaces an 'Anomalies Bucket' showing all documents that have been in 'processing' status for more than 24 hours. This enables proactive identification and resolution of stuck documents in the OCR/indexing pipeline.

### 3.9 Agentic Search

An `AgentOrchestrator` with 4 agents (Clarifier, Researcher, Verifier, Answerer) exists in the codebase. Identity profiles for agents are being refined. This is not a future feature — the infrastructure is deployed; the current work focuses on improving agent identity and response quality.

---

## 4. Non-Functional Requirements

### 4.1 Performance

| Requirement | Target |
|-------------|--------|
| Page load time (web) | <2 seconds via Next.js client-side routing |
| Search response time | <3 seconds for semantic search queries |
| Document processing | >50 documents/hour sustained throughput |
| Chat response (streaming) | First token <2 seconds (OpenRouter) |
| Concurrent users | 5 simultaneous users without degradation |
| File upload size limit | 100MB per file, 500MB per batch |

### 4.2 Reliability & Resilience

The UI must never crash due to backend failures. All API calls implement graceful degradation with user-friendly error states. Health checks mandatory for all HTTP services. Docker containers include resource limits and automatic restart policies.

**Guardian HC (3-Layer Self-Healing Monitoring)**
- Layer 1: Host watchdog — monitors Docker daemon and container health from the host
- Layer 2: Container guardian — monitors inter-service connectivity and triggers heals
- Layer 3: Preflight checks — validates configuration and secrets before service start

Guardian also handles the Docker 29.x nftables bug (stale PREROUTING rules that break container networking after host network changes).

### 4.3 Security Requirements

| Requirement | Implementation |
|-------------|----------------|
| Authentication | JWT-based email/password authentication |
| Vault Isolation | Confidential bucket completely invisible to non-admin users |
| LLM Privacy | Confidential document content stripped to metadata before any cloud API call |
| Confidential AI | Metadata-only context assembly at service layer (chat_service.py); audit log for every confidential access |
| Secrets Management | No secrets in Git; .env files excluded from VCS; HashiCorp Vault for runtime secrets |
| Data Encryption | At-rest Fernet encryption for confidential documents |
| Container Isolation | Separate Docker containers for each SOWKNOW service with resource limits |
| Database Isolation | Separate database container with restricted network access |
| InputGuard Middleware | Privacy guard inspects inputs; 59 files reference vault/privacy/confidential handling |
| Admin API | POST /api/v1/admin/users/{id}/reset-password (admin only, returns temp password) |

### 4.4 Infrastructure Constraints

| Resource | Specification |
|----------|---------------|
| VPS Provider | Hostinger |
| RAM | 31GB (upgraded 2026-03-23) |
| Disk | 200GB |
| GPU | None — all OCR and embeddings run locally on CPU |
| Ollama | NOT running (intentionally removed; too slow on CPU); may return as Phase 7C with Gemma 2B |
| Redis memory limit | 768MB (raised from 512MB; allows room for BGSAVE fork overhead) |
| celery-heavy memory limit | 4GB |
| celery-light memory limit | 2GB |
| Other services | Varies per service |
| Health Check Endpoint | Mandatory /health for all HTTP services |
| Alert Threshold | Memory >80% for 5 min, 5xx error rate >5% |

---

## 5. Design System

### 5.1 Visual Identity

The design follows a dark vault aesthetic with glassmorphism elements, strong visual hierarchy, and bold typography. Navigation inspired by mobile-first native app feel (bottom tabs, sheet overlays, FAB).

**Color Palette**

| Token | Hex | Usage |
|-------|-----|-------|
| Primary Background | #FFFFFF / #F8F9FA | Page and card backgrounds |
| Dark Accent | #1A1A2E | Headers, primary text, navigation |
| Yellow Accent | #FFEB3B | Highlights, warnings, active states |
| Blue Accent | #2196F3 | Links, primary actions, connected states |
| Pink/Red Accent | #E91E63 | Alerts, confidential markers, critical actions |
| Green | #4CAF50 | Success states, healthy indicators, online status |
| Gray | #E0E0E0 / #999999 | Borders, secondary text, disabled states |

### 5.2 Component Patterns

Cards with subtle shadows and rounded corners for all content blocks. Status indicators with color-coded badges (green for healthy/indexed, yellow for processing, red for error). Progress bars for upload and processing queues. Responsive grid layout. Animations at 150-250ms with reduced-motion support. Model indicator showing which AI provider is active (OpenRouter or MiniMax).

### 5.3 Language & Localization

Default interface language: French. Full English support via language selector (next-intl). All AI responses in the language of the user query. Document processing supports French and English content. Language selector accessible from the main navigation bar.

---

## 6. MVP Scope & Phasing Strategy

### 6.1 Phase 1: Core MVP (Weeks 1-8) — COMPLETE

The MVP delivers the essential document-to-insight pipeline: upload, process, search, and chat.

| Feature | Scope | Priority | Status |
|----------|-------|----------|--------|
| Web App Shell | Next.js PWA with all navigation tabs, auth, responsive layout | P0 | Done |
| Document Upload | Drag-and-drop with batch processing queue and status indicators | P0 | Done |
| OCR Processing | PaddleOCR + Tesseract fallback (Base + Large + Gundam modes) with French/English | P0 | Done |
| RAG Pipeline | Chunking, embedding (multilingual-e5-large), pgvector storage | P0 | Done |
| Hybrid Search | pgvector semantic + PostgreSQL full-text search combined | P0 | Done |
| Chat Interface | Persistent sessions, streaming (OpenRouter), source citations | P0 | Done |
| Vault System | Public/Confidential bucket separation with role-based visibility | P0 | Done |
| Auth System | JWT email/password with 3 roles (Admin, Super User, User) | P0 | Done |
| Telegram Bot | Upload (with caption tags) + chat/search (OpenRouter) | P0 | Done |
| Document List | Metadata display with status indicators and pagination | P0 | Done |
| Dashboard (Admin) | Stats, processing queue, daily anomaly report (09:00 AM) | P0 | Done |
| Confidential Routing | Metadata-only stripping at service layer; no local LLM required | P0 | Done |

### 6.2 Phase 2: Intelligence Layer (Weeks 9-14) — COMPLETE

| Feature | Scope | Priority | Status |
|----------|-------|----------|--------|
| Smart Collections | Natural language collection creation with OpenRouter analysis | P1 | Done |
| Smart Folders | AI-generated articles/content from document analysis (MiniMax M2.7) | P1 | Done |
| Report Generation | Short/Standard/Comprehensive PDF export with citations | P1 | Done |
| Intent Parser | LLM-based query routing with temporal and entity extraction | P1 | Done |
| AI Auto-Tagging | Automatic topic, date, importance tagging on ingestion | P1 | Done |
| Similarity Grouping | Auto-cluster similar documents | P1 | Done |
| Collection Save | Persist collections with name, query, document IDs, summary | P1 | Done |
| Source Sync Agent | Mac-based agent for manual iCloud/Dropbox sync | P1 | Done |

### 6.3 Phase 3: Advanced Reasoning (Weeks 15-20) — PARTIAL

| Feature | Scope | Priority | Status |
|----------|-------|----------|--------|
| Knowledge Graph | Entity extraction, relationship mapping, timeline construction | P2 | Module drafted (6 Python files); not yet in live pipeline |
| Graph-RAG | Graph-augmented retrieval for conceptually related documents | P2 | Pending knowledge graph activation |
| Synthesis Engine | Map-Reduce pipeline for broad questions across many documents | P2 | In progress |
| Agentic Search | Multi-agent: Clarifier, Researcher, Verifier, Answerer | P2 | AgentOrchestrator + 4 agents deployed; identity profiles in improvement |
| Temporal Reasoning | Understanding thought evolution over time periods | P2 | Partial |
| Progressive Revelation | Time-based access control for sensitive content to heirs | P2 | Planned |
| Family Context Builder | Explaining curator values and document significance | P2 | Planned |
| Advanced Visualizations | Charts, graphs, timelines for document analytics | P2 | Dashboard funnel panel done |

### 6.4 Phase 4–7: Infrastructure & Resilience — COMPLETE

| Feature | Description | Status |
|---------|-------------|--------|
| Pipeline State Machine | Light/heavy workers, sweeper, orchestrator with backpressure | Done (Phase 4-5) |
| Health Check Fixes | Backend now checks actual /health endpoint; workers test broker connectivity | Done (Phase 4) |
| Guardian HC | 3-layer self-healing: host watchdog + container guardian + preflight | Done (Phase 6) |
| Voice Transcription | whisper-cpp (static build) + ggml-small, Telegram OGG decryption, explicit language flag | Done (Phase 7) |
| Telegram Bucket Filter | Search bucket filtering in Telegram bot | Done (Phase 7A) |
| Queue Separation | celery-collections dedicated worker; sweep throttling with backpressure gates | Done |
| Mobile PWA | Bottom tabs, MobileSheet, FAB, gestures, per-page mobile layouts | Done |

---

## 7. Risk Mitigation

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Privacy breach via LLM | Critical | Low | Vault isolation + metadata-only content stripping at service layer; no raw confidential text to cloud |
| OCR API unavailability | High | Medium | All OCR is local (PaddleOCR + Tesseract); no external OCR dependency |
| VPS resource contention | High | Medium | Docker resource limits per service; Redis 768MB with allkeys-lru eviction; Guardian HC auto-heals |
| OpenRouter downtime | High | Low | Retry with exponential backoff; MiniMax M2.7 fallback; queue pending requests |
| Redis OOM crash | High | Medium | allkeys-lru eviction policy; 768MB limit with BGSAVE overhead headroom; vm.overcommit_memory=1 |
| Data loss | Critical | Low | Automated backups, encrypted cold storage, multi-source redundancy |
| Search quality degradation | Medium | Low | Hybrid search tuning, 1.5x RRF tag boost, relevance feedback loop |
| Multi-language accuracy | Medium | Medium | multilingual-e5-large embeddings, language-specific OCR tuning |
| Health monitoring gaps | Medium | Medium (historical) | Fixed in Phase 4: backend now checks real endpoint; workers test broker connectivity |
| Docker nftables bug (29.x) | High | Low | Guardian HC auto-detects stale PREROUTING rules and triggers heal |

---

## 8. New and Notable Features (April 2026)

This section captures features built after the original PRD v1.1 (February 2026) that are material to system understanding and debugging.

### 8.1 Queue Separation (celery-collections)

Smart Collections processing runs on a fully isolated `celery-collections` worker with its own queue. This prevents long-running collection generation jobs from starving the document pipeline (OCR/embed). The collections queue uses the same Redis broker but has independent concurrency settings.

### 8.2 Sweep Throttling & Backpressure

The pipeline sweeper (5-minute cycle) enforces a 500-document-per-queue-per-sweep cap. Backpressure gates prevent the sweeper from dispatching new tasks when the queue is already saturated. If Redis is unavailable during a sweep cycle, the backpressure bypass triggers — this was root cause of the April 2026 queue explosion incident.

### 8.3 InputGuard Middleware

A privacy guard middleware inspects all incoming requests and query parameters for PII indicators. 59 files in the codebase reference vault/privacy/confidential handling patterns. InputGuard is the central enforcement point before any content reaches LLM routing.

### 8.4 Knowledge Graph (Draft)

6 Python modules implement entity extraction, relationship mapping, and timeline construction. The knowledge graph is not yet wired into the live RAG pipeline; activation is tracked as a separate work item. The schema and extraction logic are complete.

### 8.5 Voice Transcription Pipeline

End-to-end voice flow for Telegram:
1. User sends voice note (OGG/OPUS) via Telegram
2. Bot downloads and decrypts the file (Fernet-encrypted at rest)
3. `whisper-cpp` (statically compiled, ggml-small model, 466MB) transcribes the audio
4. `--language` flag is set explicitly to prevent iOS Safari locale mismatch bug
5. Transcribed text is processed as a standard chat query

### 8.6 Guardian HC (Self-Healing Monitoring)

Three independent monitoring layers run on the production VPS:
1. **Host watchdog:** Monitors Docker daemon health and triggers restarts from the host
2. **Container guardian:** Monitors service interconnects; handles the Docker 29.x nftables PREROUTING stale-rules bug
3. **Preflight checks:** Validates secrets and Vault auto-unseal (VAULT_UNSEAL_KEY) before service start

Guardian runs outside Docker to survive container failures.

---

## 9. Future Considerations

Potential monetization of the platform if the concept proves successful. Scheduled automated reports on configurable intervals. Email notifications for collection updates. Shared collections between users. Integration with Fabric data extraction pipeline. Additional language support beyond French and English. Advanced visualization capabilities including interactive timelines and knowledge maps. Native mobile application if PWA proves insufficient. Ollama re-integration (Gemma 2B candidate) as Phase 7C for fully local confidential query processing.

---

**End of Document**
