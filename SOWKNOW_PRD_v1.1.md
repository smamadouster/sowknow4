# SOWKNOW Multi-Generational Legacy Knowledge System
## Product Requirements Document v1.1

**Date:** February 2026
**Classification:** CONFIDENTIAL

---

## 1. Vision & Strategic Overview

SOWKNOW is a multi-generational legacy knowledge system that unifies scattered digital life into an intelligent, conversational wisdom vault. Unlike standard document managers, it preserves not just documents but the context, relationships, and personal significance behind them, creating a living digital heritage accessible to the curator and future generations.

### 1.1 Problem Statement

Over 100GB of personal and professional knowledge is scattered across Mac HDD, iCloud, Dropbox, Google Drive, iPhone photos, and various digital libraries. Critical information is difficult to find, impossible to cross-reference, and at risk of being lost to future generations. Existing solutions lack the privacy controls, multi-language support, and contextual understanding required for a true legacy knowledge system.

### 1.2 Product Vision

Build a privacy-first, AI-powered knowledge vault that transforms raw document archives into an intelligent, queryable wisdom system. The platform combines OCR-powered document ingestion, semantic search with RAG, and conversational AI to enable natural-language interaction with an entire lifetime of accumulated knowledge.

### 1.3 AI Strategy

SOWKNOW uses a dual-LLM architecture aligned with the broader Aicha platform ecosystem:

- **Gemini Flash (Google Generative AI API):** Primary cloud LLM for all intelligent features including RAG answer synthesis, Smart Folders content generation, Smart Collections analysis, report generation, and Telegram chat. Selected for its 1M+ token context window (8x improvement), strong multilingual performance (French/English), context caching (up to 80% cost reduction), and competitive pricing.

- **Ollama (Shared VPS Instance):** Local LLM for confidential document processing. The existing shared Ollama installation on the VPS handles all queries that involve Confidential bucket documents, ensuring zero exposure of sensitive personal information to external APIs. No dedicated container needed as Ollama is already running and shared across projects.

- **multilingual-e5-large (Local):** Embedding model for vector generation. Runs locally via sentence-transformers for generating 1024-dimensional vectors optimized for French/English semantic search. Powers the RAG retrieval pipeline.

### 1.4 Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Information retrieval time reduction | >70% | Average query-to-answer time vs. manual search |
| OCR text extraction accuracy | >97% | Automated quality checks on processed documents |
| System uptime | >99.5% | Health check monitoring |
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

**Public Bucket:** All general documents accessible to all authenticated users. Documents here are indexed, searchable, and processed through Gemini Flash via Google Generative AI API for AI features with context caching enabled for cost optimization.

**Confidential Bucket:** Sensitive documents (IDs, passports, financial records) completely invisible to non-admin users. Not even metadata is exposed. When processed by AI, confidential documents are routed exclusively through the shared Ollama instance on the VPS and never sent to any cloud API.

**Supported File Formats**
PDF, DOCX, PPTX, XLSX, TXT, MD, JSON, Images (JPG, PNG, HEIC), Videos, EPUB

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

**OCR Processing (Hunyuan-OCR via API)**
Since the hosting VPS has no GPU, Hunyuan-OCR is accessed via the Tencent Cloud API. Three processing modes:

- **Base Mode (1024x1024):** Standard documents, typed text, forms
- **Large Mode (1280x1280):** Complex layouts, multi-column documents, tables
- **Gundam Mode:** Detailed illustrations, handwritten notes, scanned photos

Primary language: French. Secondary: English. Auto-detection applies appropriate OCR model settings.

**RAG Pipeline**
1. **Text Extraction:** OCR for images/scans, direct extraction for PDFs/DOCX
2. **Chunking:** Recursive character text splitter (512 tokens, 50 token overlap)
3. **Embedding:** multilingual-e5-large model (local, 1024 dimensions) for French/English
4. **Vector Storage:** PostgreSQL with pgvector extension
5. **Retrieval:** Hybrid search combining pgvector cosine similarity + PostgreSQL full-text search
6. **Generation:** Gemini Flash synthesizes answers from retrieved chunks with source citations, using context caching for cost optimization
7. **Confidential Override:** If retrieved chunks include Confidential docs, generation routes to Ollama instead

**Intelligent Categorization**
- AI auto-tagging by topic, project, date, and importance level
- Automatic similarity grouping (all IDs, all balance sheets, all solar energy docs)
- Entity extraction: people, organizations, concepts, locations
- Relationship mapping across document sources and time periods

### 3.3 Conversational AI Chat System

The chat system provides a persistent, threaded conversation interface powered by Gemini Flash for general queries and Ollama for confidential document contexts. Supports context-aware queries, temporal reasoning, multi-turn conversations, and context caching for repeated queries.

**Core Chat Features**
- Persistent chat sessions with full history
- Streaming responses with typing effect
- Source document citations in every response
- Ability to scope queries to specific document sets or collections
- Multi-language support (French/English queries and responses)
- Automatic LLM routing: Gemini Flash for public context, Ollama for confidential context
- Context caching indicators showing cache hits/misses for cost optimization

**Query Examples**
- **Context-Aware:** "What was I learning about quantum physics in 2020?"
- **Cross-Reference:** "Show me all documents related to our family vacation planning"
- **Synthesis:** "What insights do I have about leadership across all my notes?"
- **Financial:** "Check the trend of assets on the balance sheets for the last 10 years"
- **Temporal:** "How has my thinking on solar energy evolved over time?"

### 3.4 Smart Collections & Report Generation

Users can create AI-powered collections by describing what they want in natural language. The system uses Gemini Flash to automatically gather relevant documents, analyze them, and generate reports with context caching for cost-effective repeated queries. Admin requests on confidential documents route analysis through Ollama.

**Collection Workflow**
1. User describes the collection in natural language (up to 500 characters)
2. System parses intent: keywords, date ranges, entities, document types
3. Hybrid search gathers relevant documents (up to 100 per collection)
4. Gemini Flash generates summary, identifies themes, and produces requested analysis with context caching enabled
5. User can ask follow-up questions scoped to the gathered documents
6. Collection can be saved, named, and exported as PDF

**Report Types**

| Report Type | Length | Use Case |
|-------------|--------|----------|
| Short Summary | 1-2 pages | Quick overview, key findings, executive brief |
| Standard Report | 3-5 pages | Detailed analysis with sections, supporting evidence |
| Comprehensive Report | 5-10+ pages | Full synthesis with timeline, cross-references, appendices |

### 3.5 Smart Folders / Smart Content

Users provide a topic or subject, and the system uses Gemini Flash to search all related documents (Public bucket for regular users; Public + Confidential for Admin), analyze them, and automatically generate an article or content piece. The generated content is saved as a new document in the database. Context caching optimizes repeated queries on similar topics.

**Workflow**
1. User inputs a topic/subject via the Smart Folders tab
2. System searches all related documents using hybrid search
3. Gemini Flash analyzes gathered documents and generates article/content with context caching
4. New document is automatically created in the database with the generated content
5. Admin requests include Confidential documents in the analysis (routed via Ollama)
6. Generated content includes source citations and can be exported as PDF

### 3.6 Telegram Bot Integration

The Telegram bot serves as a mobile-first interface for document upload, knowledge queries, and conversational chat powered by Gemini Flash with context caching for cost-efficient repeated queries.

**Upload Capabilities**
- File upload via attachment (paperclip) — default visibility: Private
- Visibility control via caption: `public` or `confidential`
- Support for comments and tags in caption during upload
- Direct photo/scan upload from iPhone camera

**Chat & Search via Telegram**
- Natural language queries against the knowledge base (powered by Gemini Flash)
- Search results with document citations
- Multi-turn conversation support with session memory and context caching
- French/English language support

### 3.7 Web Application & PWA

The web application provides the full-featured interface built as a Progressive Web App (PWA) for mobile access via home screen shortcut.

**Navigation Tabs**

| Tab | All Users | Admin Only | Description |
|-----|-----------|-------------|-------------|
| Search | Yes | - | Semantic search interface with natural language queries |
| Documents | Yes | - | List view with last 50 documents, metadata, status indicators |
| Assistant AI | Yes | - | Chat interface for conversational queries (Gemini Flash / Ollama) with cache indicators |
| Collections | Yes | - | Saved smart collections with follow-up capability |
| Smart Folders | Yes | - | AI-generated article/content from document analysis (Gemini Flash with context caching) |
| Dashboard | - | Yes | System health, stats, processing anomalies |
| Admin/Settings | - | Yes | User management, system configuration |

**Dashboard (Admin)**
Total Documents count, Uploads Today, Pages Indexed, Processing Queue status. Daily anomaly report at 09:00 AM showing all documents stuck in 'processing' status for more than 24 hours. Graceful handling of API downtime with non-intrusive empty states.

### 3.8 Processing Anomaly Monitoring

Every day at 09:00 AM, the Admin dashboard surfaces an 'Anomalies Bucket' showing all documents that have been in 'processing' status for more than 24 hours. This enables proactive identification and resolution of stuck documents in the OCR/indexing pipeline.

---

## 4. Non-Functional Requirements

### 4.1 Performance

| Requirement | Target |
|-------------|--------|
| Page load time (web) | <2 seconds via Next.js client-side routing |
| Search response time | <3 seconds for semantic search queries (<1s with context cache hit) |
| Document processing | >50 documents/hour sustained throughput |
| Chat response (streaming) | First token <2 seconds (Gemini Flash), <1s (cached), <5s (Ollama) |
| Concurrent users | 5 simultaneous users without degradation |
| File upload size limit | 100MB per file, 500MB per batch |

### 4.2 Reliability & Resilience

The UI must never crash due to backend failures. All API calls implement graceful degradation with user-friendly error states. Health checks mandatory for all HTTP services. Docker containers include resource limits and automatic restart policies. Shared Ollama instance monitored for availability but managed externally.

### 4.3 Security Requirements

| Requirement | Implementation |
|-------------|----------------|
| Authentication | JWT-based email/password authentication |
| Vault Isolation | Confidential bucket completely invisible to non-admin users |
| LLM Privacy | Zero exposure of personal information to Gemini Flash or any external API |
| Confidential AI | Shared Ollama instance processes confidential documents exclusively |
| Secrets Management | No secrets in Git; .env files excluded from VCS |
| Data Encryption | At-rest encryption for all stored documents |
| Container Isolation | Separate Docker containers for each SOWKNOW service with resource limits |
| Database Isolation | Separate database container with restricted network access |

### 4.4 Infrastructure Constraints

| Resource | Specification |
|----------|---------------|
| VPS Provider | Hostinger |
| RAM | 16GB (shared with other projects including Ollama) |
| Disk | 200GB |
| GPU | None (OCR via cloud API) |
| Ollama | Shared instance, already running on VPS (not managed by SOWKNOW) |
| Container Memory Limit | 512MB per SOWKNOW service (except PostgreSQL: 2GB) |
| Health Check Endpoint | Mandatory /health for all HTTP services |
| Alert Threshold | Memory >80% for 5 min, 5xx error rate >5% |

---

## 5. Design System

### 5.1 Visual Identity

The design follows a clean, modern card-based aesthetic inspired by the existing Legal-BERT Cost Dashboard. Light background with high-contrast cards, vibrant accent colors, and clear status indicators. Draws from Neo-Brutalism principles with strong visual hierarchy and bold typography.

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

Cards with subtle shadows and rounded corners for all content blocks. Status indicators with color-coded badges (green for healthy/indexed, yellow for processing, red for error). Progress bars for upload and processing queues. Responsive grid layout. Animations at 150-250ms with reduced-motion support. Always-visible model indicator showing which AI model is active (Gemini Flash or Ollama) with cache hit/miss indicators.

### 5.3 Language & Localization

Default interface language: French. Full English support via language selector. All AI responses in the language of the user query. Document processing supports French and English content. Language selector accessible from the main navigation bar.

---

## 6. MVP Scope & Phasing Strategy

### 6.1 Phase 1: Core MVP (Weeks 1-8)

The MVP delivers the essential document-to-insight pipeline: upload, process, search, and chat.

| Feature | Scope | Priority |
|----------|-------|----------|
| Web App Shell | Next.js PWA with all navigation tabs, auth, responsive layout | P0 |
| Document Upload | Drag-and-drop with batch processing queue and status indicators | P0 |
| OCR Processing | Hunyuan-OCR via API (Base + Large modes) with French/English | P0 |
| RAG Pipeline | Chunking, embedding (multilingual-e5-large), pgvector storage | P0 |
| Hybrid Search | pgvector semantic + PostgreSQL full-text search combined | P0 |
| Chat Interface | Persistent sessions, streaming (Gemini Flash with context caching), source citations | P0 |
| Vault System | Public/Confidential bucket separation with role-based visibility | P0 |
| Auth System | JWT email/password with 3 roles (Admin, Super User, User) | P0 |
| Telegram Bot | Upload (with caption tags) + chat/search (Gemini Flash) | P0 |
| Document List | Metadata display with status indicators and pagination | P0 |
| Dashboard (Admin) | Stats, processing queue, daily anomaly report (09:00 AM) | P0 |
| Confidential Routing | Auto-switch to shared Ollama when confidential docs in context | P0 |

### 6.2 Phase 2: Intelligence Layer (Weeks 9-14)

| Feature | Scope | Priority |
|----------|-------|----------|
| Smart Collections | Natural language collection creation with Gemini Flash analysis and context caching | P1 |
| Smart Folders | AI-generated articles/content from document analysis (Gemini Flash with context caching) | P1 |
| Report Generation | Short/Standard/Comprehensive PDF export with citations | P1 |
| Intent Parser | LLM-based query routing with temporal and entity extraction | P1 |
| AI Auto-Tagging | Automatic topic, date, importance tagging on ingestion | P1 |
| Similarity Grouping | Auto-cluster similar documents | P1 |
| Collection Save | Persist collections with name, query, document IDs, summary | P1 |
| Source Sync Agent | Mac-based agent for manual iCloud/Dropbox sync | P1 |

### 6.3 Phase 3: Advanced Reasoning (Weeks 15-20)

| Feature | Scope | Priority |
|----------|-------|----------|
| Knowledge Graph | Entity extraction, relationship mapping, timeline construction | P2 |
| Graph-RAG | Graph-augmented retrieval for conceptually related documents | P2 |
| Synthesis Engine | Map-Reduce pipeline for broad questions across many documents | P2 |
| Agentic Search | Multi-agent: Clarifier, Researcher, Verifier, Answerer | P2 |
| Temporal Reasoning | Understanding thought evolution over time periods | P2 |
| Progressive Revelation | Time-based access control for sensitive content to heirs | P2 |
| Family Context Builder | Explaining curator values and document significance | P2 |
| Advanced Visualizations | Charts, graphs, timelines for document analytics | P2 |

---

## 7. Risk Mitigation

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Privacy breach via LLM | Critical | Low | Vault isolation, Ollama for confidential, no PII to Gemini Flash |
| OCR API unavailability | High | Medium | Queue with retry logic, Tesseract fallback for basic OCR |
| Shared Ollama overloaded | Medium | Medium | Request queuing, timeout handling, graceful fallback messaging |
| VPS resource contention | High | Medium | Docker resource limits per service, monitoring alerts, stagger heavy jobs |
| Gemini API downtime | High | Low | Retry with exponential backoff, leverage context cache during outages, queue pending requests |
| Data loss | Critical | Low | Automated backups, encrypted cold storage, multi-source redundancy |
| Search quality degradation | Medium | Low | Hybrid search tuning, relevance feedback loop |
| Multi-language accuracy | Medium | Medium | multilingual-e5-large embeddings, language-specific OCR tuning |

---

## 8. Future Considerations

Potential monetization of the platform if the concept proves successful. Scheduled automated reports on configurable intervals. Email notifications for collection updates. Shared collections between users. Integration with Fabric data extraction pipeline. Additional language support beyond French and English. Advanced visualization capabilities including interactive timelines and knowledge maps. Native mobile application if PWA proves insufficient.

---

**End of Document**