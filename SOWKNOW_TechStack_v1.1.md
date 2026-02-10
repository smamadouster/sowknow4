# SOWKNOW Multi-Generational Legacy Knowledge System
## Technical Stack Specification v1.2

**Date:** February 2026
**Classification:** CONFIDENTIAL
**Version History:** v1.2 - Updated for Gemini Flash migration (February 10, 2026)

---

## 1. Architecture Overview

SOWKNOW follows a containerized microservices architecture deployed on a Hostinger VPS (16GB RAM, 200GB disk) shared with other projects. All SOWKNOW-specific services run in Docker containers with enforced resource limits. The system uses a dual-LLM strategy: Gemini Flash via Google Generative AI API for general AI features with context caching for cost optimization, and the shared Ollama instance for confidential document processing.

### 1.1 Critical Architecture Decision: Shared Ollama

The VPS runs a shared Ollama instance that serves multiple projects (including GhostShell). SOWKNOW connects to this existing instance via `LOCAL_LLM_URL` (default: `http://localhost:11434`) rather than deploying its own container. This means SOWKNOW does not manage, start, stop, or allocate resources for Ollama. The shared Ollama RAM footprint is outside SOWKNOW's resource budget.

### 1.2 High-Level Service Map

| Layer | Technology | Managed By | Function |
|-------|------------|------------|----------|
| Frontend | Next.js 14 (PWA) | SOWKNOW | Web application, SSR, client-side routing |
| API Gateway | FastAPI (Python 3.11+) | SOWKNOW | REST API, auth, request routing |
| Task Queue | Celery + Redis | SOWKNOW | Async document processing, OCR, embedding |
| Database | PostgreSQL 16 + pgvector | SOWKNOW | Metadata, vectors, full-text search, chat history |
| Cloud LLM | Gemini Flash 1.5/2.0/3.0 (Google Generative AI API) | External | Smart features, RAG synthesis, reports, Telegram chat with context caching |
| Local LLM | Ollama (shared instance) | Shared/External | Confidential document processing only |
| Embeddings | multilingual-e5-large | SOWKNOW | Vector generation for RAG pipeline (runs in Celery worker) |
| OCR | Hunyuan-OCR (Tencent API) | External | Text extraction from images and scanned PDFs |
| Bot | python-telegram-bot | SOWKNOW | Telegram upload + chat interface |

### 1.3 Service Communication

All SOWKNOW containers communicate via a dedicated Docker internal network (`sowknow-net`). The FastAPI backend serves as the central hub. Redis handles both the Celery task queue and session caching. PostgreSQL is the single source of truth for all persistent data. The Telegram bot communicates with the backend via internal API calls. Ollama is accessed via host network (`localhost:11434`). Gemini Flash and Hunyuan-OCR are accessed via HTTPS to their respective APIs. Only the Nginx reverse proxy is exposed to the internet.

---

## 2. Frontend Stack

### 2.1 Core Framework

| Component | Technology | Version | Rationale |
|-----------|------------|---------|-----------|
| Framework | Next.js | 14.x | SSR, file-based routing, PWA support, instant transitions |
| Language | TypeScript | 5.x | Type safety, better DX, IDE support |
| Styling | Tailwind CSS | 3.x | Utility-first, rapid prototyping, responsive design |
| State Management | Zustand | 4.x | Lightweight, minimal boilerplate |
| HTTP Client | Axios | 1.x | Interceptors for JWT, request/response transformation |
| Chat UI | Custom + react-markdown | - | Streaming responses, markdown rendering, citations |
| File Upload | react-dropzone | - | Drag-and-drop, file validation, progress tracking |
| Icons | Lucide React | - | Consistent icon set, tree-shakeable |
| Charts | Recharts | 2.x | Dashboard statistics and document analytics |
| PWA | next-pwa | - | Service worker, offline capability, home screen install |
| i18n | next-intl | - | French (default) and English localization |

### 2.2 Design System

Card-based layout with clean aesthetic inspired by the Legal-BERT Cost Dashboard. Light background (`#F8F9FA`) with high-contrast content cards. Bold accent colors: Yellow (`#FFEB3B`) for highlights, Blue (`#2196F3`) for actions, Pink (`#E91E63`) for alerts, Green (`#4CAF50`) for healthy states. Font stack: Inter (headings), system-ui (body). Responsive breakpoints: mobile (< 768px), tablet (768-1024px), desktop (> 1024px). Animations at 150-250ms with prefers-reduced-motion support.

### 2.3 Key Patterns

- Server-Side Rendering for initial page load
- Client-side routing for instant tab transitions
- JWT stored in httpOnly cookies (not localStorage)
- Streaming fetch for Gemini Flash chat responses (ReadableStream API)
- Graceful degradation: UI never crashes on backend failures
- Role-based UI rendering: Admin-only components conditionally shown
- Model indicator: always shows whether Gemini Flash or Ollama is active with cache hit/miss indicators

---

## 3. Backend Stack

### 3.1 API Framework

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Framework | FastAPI (Python 3.11+) | Async support, auto-generated OpenAPI docs, type validation |
| ORM | SQLAlchemy 2.0 + Alembic | Mature ORM, migration management, async support |
| Auth | python-jose (JWT) + passlib | Industry-standard JWT with bcrypt password hashing |
| Task Queue | Celery 5.x | Distributed task processing for OCR, embedding, indexing |
| Message Broker | Redis 7.x | Celery broker + session cache + rate limiting |
| File Storage | Local filesystem (Docker volumes) | Mounted volumes for Public and Confidential buckets |
| Logging | structlog (JSON) | Structured JSON logging for monitoring and debugging |
| LLM Client | google-generativeai (async) | Async client for Gemini Flash API with context caching support |
| Fallback LLM Client | httpx (async) | Async HTTP client for Ollama calls |

### 3.2 LLM Integration Layer

The backend implements an LLM router that selects the appropriate model based on document context and cache availability:

| Decision Point | Route To | Implementation |
|----------------|----------|----------------|
| Query involves only Public documents | Gemini Flash (Google Generative AI API) | Default path via GEMINI_API_KEY with context caching |
| Query involves any Confidential document | Ollama (shared instance) | Redirect to LOCAL_LLM_URL |
| Smart Folders content generation | Gemini Flash (Google Generative AI API) | Always cloud for quality with context caching |
| Smart Folders with Admin + Confidential docs | Ollama (shared instance) | Privacy override for admin vault queries |
| Telegram chat (general) | Gemini Flash (Google Generative AI API) | Default for all Telegram interactions with context caching |
| Telegram chat (confidential context) | Ollama (shared instance) | Auto-detected from retrieved docs |
| Report generation (public) | Gemini Flash (Google Generative AI API) | Cloud for long-form generation quality with context caching |
| Embedding generation | multilingual-e5-large (local) | Always local, runs in Celery worker |

### 3.3 API Structure

| Endpoint Group | Key Endpoints | Auth |
|----------------|---------------|------|
| Auth | `POST /api/auth/login`, `/register`, `/refresh` | No (login/register) |
| Documents | `GET/POST/PUT/DELETE /api/documents` | Role-based |
| Upload | `POST /api/upload` (multipart) | Admin only |
| Search | `POST /api/search` (hybrid semantic + keyword) | Role-scoped |
| Chat | `POST /api/chat/sessions`, `/api/chat/{id}/message` | Yes |
| Collections | `POST/GET /api/collections` | Yes |
| Smart Folders | `POST /api/smart-folders/generate` | Yes |
| Reports | `POST /api/reports/generate`, `GET /api/reports/{id}/pdf` | Yes |
| Health | `GET /health` | No |
| Admin | `GET /api/admin/stats`, `/api/admin/anomalies` | Admin only |
| Users | `GET/POST/PUT /api/admin/users` | Admin only |

### 3.4 Document Processing Pipeline

When a document is uploaded, it enters an asynchronous pipeline managed by Celery:

1. **File Validation**: Check format, size, virus scan
2. **Storage**: Save to Public or Confidential bucket (filesystem)
3. **OCR**: If image/scanned PDF, send to Hunyuan-OCR API for text extraction
4. **Text Extraction**: For native PDFs/DOCX, extract directly via PyPDF2/python-docx
5. **Chunking**: Recursive character splitter (512 tokens, 50 token overlap)
6. **Embedding**: Generate 1024-dim vectors using multilingual-e5-large (local)
7. **Indexing**: Store chunks + vectors in PostgreSQL (pgvector) with full-text index
8. **Categorization**: AI auto-tag with topic, entities, language, importance
9. **Status Update**: Mark document as 'indexed' and update metadata

---

## 4. Database Layer

### 4.1 PostgreSQL + pgvector (Unified)

PostgreSQL serves as the single database engine for all data needs. This avoids the complexity and RAM overhead of Elasticsearch on a shared 16GB VPS. pgvector provides vector similarity search while built-in full-text search (tsvector/tsquery) handles keyword matching.

**Why Not Elasticsearch for MVP?**
- Elasticsearch requires 2-4GB RAM minimum, consuming shared VPS resources
- PostgreSQL full-text search with GIN indexes handles keyword search for <100K documents
- One database to manage, backup, and monitor reduces operational complexity
- Elasticsearch can be added in Phase 3 if search scale demands it

### 4.2 Core Data Models

| Table | Key Fields | Purpose |
|-------|------------|---------|
| users | id, email, hashed_password, role, is_superuser, can_access_confidential | User accounts and RBAC |
| documents | id, filename, file_path, bucket (public/confidential), status, size, mime_type, language | Document metadata |
| document_tags | id, document_id, tag_name, auto_generated | Tags and categorization |
| document_chunks | id, document_id, chunk_text, chunk_index, embedding (vector(1024)), tsvector_content | Text chunks with embeddings |
| chat_sessions | id, user_id, title, document_scope, created_at | Conversation sessions |
| chat_messages | id, session_id, role, content, sources_json, llm_used, created_at | Chat history (tracks which LLM was used) |
| collections | id, user_id, name, original_query, document_ids, ai_summary | Saved smart collections |
| smart_folders | id, user_id, topic, generated_content, source_document_ids, created_at | AI-generated articles |
| processing_queue | id, document_id, task_type, status, started_at, error_message | Async processing tracking |

### 4.3 Hybrid Search

**Semantic Search**: pgvector cosine similarity (`<=>` operator) on embedding column. Query "vacation expenses" finds "trip costs", "travel spending", "holiday budget".

**Full-Text Search**: PostgreSQL tsvector/tsquery with GIN index. French and English stemming via language-specific dictionaries (`french`/`english` configurations).

**Hybrid Scoring**: `relevance = (0.7 × semantic_score) + (0.3 × keyword_score)`. Weights configurable. Results filtered by user role (non-admin never sees Confidential chunks).

---

## 5. AI/ML Pipeline

### 5.1 LLM Strategy

| Aspect | Gemini Flash (Public Docs) | Ollama (Confidential Docs) |
|--------|---------------------------|----------------------------|
| Provider | Google Generative AI (generativelanguage.googleapis.com) | Shared VPS instance (localhost:11434) |
| Model | Gemini Flash 1.5/2.0/3.0 | mistral:7b-instruct (or loaded model) |
| Context Window | 1M+ tokens (8x improvement) | Depends on loaded model |
| Context Caching | Yes (up to 80% cost reduction) | No |
| Use Cases | RAG synthesis, Smart Folders, Smart Collections, reports, Telegram chat | Confidential doc Q&A, vault queries |
| Latency | 1-3s first token (<1s cached) | 2-5s first token (CPU inference) |
| Cost | Per-token pricing via Google (with cache cost tracking) | Free (shared local compute) |
| RAM Impact on SOWKNOW | None (API call) | None (shared instance, external to SOWKNOW budget) |
| Privacy | No PII sent, no confidential docs ever | Full privacy, everything local |
| Routing | Default for all non-confidential contexts | Auto-triggered when confidential docs detected |
| Streaming | Yes (SSE) | Yes (Ollama streaming API) |

### 5.2 Embedding Model

| Property | Value |
|----------|-------|
| Model | intfloat/multilingual-e5-large |
| Dimensions | 1024 |
| Languages | 100+ languages (excellent French/English performance) |
| RAM Footprint | ~1.3GB loaded in Celery worker |
| Inference | CPU (adequate for batch processing at 50+ docs/hour) |
| Hosting | Local via sentence-transformers Python library |
| Alternative (lighter) | intfloat/multilingual-e5-base (768 dims, ~900MB) |
| Why This Model | Best multilingual retrieval model; FR/EN equally strong; proven in production RAG systems |

The embedding model runs inside the Celery worker container. At ~1.3GB resident memory, it fits within the worker's 1.5GB allocation. If the shared VPS is under memory pressure, multilingual-e5-base (768 dimensions, ~900MB) is the drop-in fallback with ~5% retrieval quality reduction.

### 5.3 OCR Strategy

| Mode | Resolution | Use Case | Est. Cost |
|------|------------|----------|-----------|
| Base | 1024x1024 | Standard documents, typed text, simple forms | ~$0.001/page |
| Large | 1280x1280 | Complex layouts, multi-column, tables | ~$0.002/page |
| Gundam | Variable | Handwriting, detailed illustrations, old scans | ~$0.003/page |

**Fallback**: Tesseract OCR (local, with French/English packs) as degraded fallback (~85-90% accuracy vs >97% Hunyuan).

---

## 6. Infrastructure & DevOps

### 6.1 Docker Compose (SOWKNOW Services Only)

These are the containers managed by SOWKNOW's `docker-compose.yml`. Ollama is **NOT** included as it runs as a shared system service.

| Service | Image | Memory Limit | CPU Limit | Ports |
|---------|-------|--------------|-----------|-------|
| nginx | nginx:alpine | 256MB | 0.5 | 80, 443 (external) |
| frontend | node:20-alpine (Next.js) | 512MB | 1.0 | 3000 (internal) |
| backend | python:3.11-slim (FastAPI) | 1024MB | 1.0 | 8000 (internal) |
| celery-worker | python:3.11-slim | 1536MB | 1.5 | - (no ports) |
| celery-beat | python:3.11-slim | 256MB | 0.25 | - (no ports) |
| redis | redis:7-alpine | 512MB | 0.5 | 6379 (internal) |
| postgres | pgvector/pgvector:pg16 | 2048MB | 1.5 | 5432 (internal) |
| telegram-bot | python:3.11-slim | 256MB | 0.5 | - (no ports) |

**Total SOWKNOW RAM Budget**: ~6.4GB allocated across 8 containers. The Celery worker (1.5GB) hosts the multilingual-e5-large embedding model (~1.3GB). Remaining VPS RAM is available for the shared Ollama instance, OS, and other projects.

**Ollama Connection**: SOWKNOW connects to Ollama via host network. In `docker-compose.yml`, the backend and celery-worker services use `extra_hosts: ["host.docker.internal:host-gateway"]` or `network_mode: host` to reach `localhost:11434` where Ollama listens.

### 6.2 Health Checks & Monitoring

| Service | Health Check | Interval | Alert Condition |
|---------|--------------|----------|-----------------|
| backend | `GET /health` (HTTP 200) | 30s | 3 consecutive failures |
| postgres | `pg_isready -U sowknow` | 30s | Connection refused |
| redis | `redis-cli ping` | 30s | No PONG response |
| ollama (shared) | `GET http://localhost:11434/api/tags` | 60s | Connection refused (warn, not critical) |
| celery | `celery inspect ping` | 60s | No workers responding |
| nginx | `curl -f http://localhost/health` | 30s | 502/503 response |
| moonshot API | Ping via `/api/health` (custom) | 300s | 3 consecutive timeouts |

**Alerting Rules**
- SOWKNOW total memory >6GB sustained for 5 min: WARNING
- VPS total memory >80% for 5 min: CRITICAL (impacts shared services)
- 5xx error rate >5% over 5 min: CRITICAL
- Processing queue depth >100: WARNING
- Disk usage >85%: CRITICAL
- Ollama unreachable: WARNING (graceful fallback to Kimi 2.5 for non-confidential)

### 6.3 Storage Architecture

| Volume | Mount Path | Purpose | Size Est. |
|--------|------------|---------|-----------|
| sowknow-public | /data/public | Public document storage | ~80GB |
| sowknow-confidential | /data/confidential | Encrypted confidential storage | ~20GB |
| sowknow-postgres | /var/lib/postgresql/data | Database + vectors | ~30GB |
| sowknow-redis | /data | Redis persistence (RDB) | ~512MB |
| sowknow-backups | /backups | Automated database backups | ~20GB |

### 6.4 Secrets Management

| Secret | Description |
|--------|-------------|
| DATABASE_URL | PostgreSQL connection string |
| REDIS_URL | Redis connection string |
| JWT_SECRET | 256-bit random key for JWT signing |
| GEMINI_API_KEY | Google Generative AI authentication key for Gemini Flash |
| HUNYUAN_API_KEY | Tencent Cloud OCR API key |
| LOCAL_LLM_URL | Ollama endpoint (default: http://localhost:11434) |
| TELEGRAM_BOT_TOKEN | Telegram bot authentication token |
| ADMIN_EMAIL | Initial admin account email |
| ADMIN_PASSWORD | Initial admin password (changed on first login) |

### 6.5 Backup Strategy

- Daily automated PostgreSQL dump (pg_dump) compressed and stored locally
- Weekly encrypted backup to offsite storage (configurable)
- Document files: filesystem-level rsync to backup volume
- Retention: 7 daily, 4 weekly, 3 monthly
- Backup validation: automated restore test monthly

---

## 7. Security Architecture

### 7.1 Network Security

- Nginx reverse proxy as single entry point with TLS termination
- All SOWKNOW inter-service communication on Docker internal network
- PostgreSQL and Redis only accessible from Docker network
- Ollama accessed via host network (localhost only, not internet-exposed)
- Rate limiting at Nginx: 100 requests/min per IP
- CORS configured for specific frontend domain only

### 7.2 Authentication Flow

1. User submits email/password to `POST /api/auth/login`
2. Backend validates credentials against bcrypt hash in PostgreSQL
3. On success, issues JWT access token (15 min) + refresh token (7 days)
4. JWT stored in httpOnly secure cookie (not localStorage)
5. Every API request includes JWT; backend validates and extracts user role
6. Refresh token used to obtain new access token without re-login
7. Telegram auth: bot token + user ID mapping to SOWKNOW account

### 7.3 Confidential Data Protection

Defense-in-depth for the Confidential bucket:

- **Storage Isolation**: Separate filesystem directory with restricted OS permissions
- **Database Filtering**: All queries automatically exclude confidential documents for non-admin users
- **Metadata Hiding**: Non-admin users cannot see even document names or counts
- **LLM Routing**: Confidential docs in retrieval context triggers auto-switch to Ollama
- **Zero PII to Cloud**: No personal identifiers ever sent to Gemini Flash or Hunyuan-OCR
- **Audit Log**: All confidential document access logged with timestamp and user ID

### 7.4 Gemini Flash API Security

- API key stored in .env, never in source code or Git
- Request sanitization: strip any PII from prompts before sending to Gemini Flash
- Content filtering: verify no confidential chunk IDs leak into cloud API requests
- Cost monitoring: daily budget cap aligned with existing API usage patterns, track cache hit-rate for cost optimization
- Cache management: monitor cache hit-rate to ensure cost-effective context caching usage

---

## 8. Monitoring & Observability (New for v1.2)

### 8.1 Context Caching Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| Cache Hit Rate | Percentage of queries served from cache | >50% |
| Cache Cost Savings | Tokens saved via caching | >60% |
| Average Cache Latency | Response time for cached queries | <1s |
| Cache Utilization | Number of active cached contexts | Track growth |

### 8.2 API Performance Monitoring

| Metric | Gemini Flash | Ollama |
|--------|--------------|--------|
| First Token Latency | <2s (<1s cached) | <5s |
| Total Response Time | <3s (<1s cached) | <8s |
| Error Rate | <2% | <5% |
| Daily Token Usage | Track with cost | N/A |

### 8.3 Cost Tracking Dashboard

- Daily Gemini API costs by endpoint
- Cache hit/miss visualization
- Token usage trends
- Cost per query breakdown
- Budget alerts at 80% of daily cap

---

**End of Document**

**Version 1.2 Changes Summary:**
- Migrated from Kimi 2.5 (Moonshot API) to Gemini Flash (Google Generative AI API)
- Added context caching support with up to 80% cost reduction
- Updated context window from 128k to 1M+ tokens
- Added cache monitoring and metrics tracking
- Updated security section for Gemini Flash API
- Added new monitoring section for cache effectiveness