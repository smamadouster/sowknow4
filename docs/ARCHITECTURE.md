# SOWKNOW System Architecture

**Version**: 3.0.0 (Phase 3)
**Last Updated**: February 24, 2026
**Status**: Production Ready

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Technology Stack](#technology-stack)
3. [Tri-LLM Routing Architecture](#tri-llm-routing-architecture)
4. [Data Flow](#data-flow)
5. [Role-Based Access Control](#role-based-access-control)
6. [Security Architecture](#security-architecture)
7. [Scalability & Performance](#scalability--performance)
8. [Deployment Architecture](#deployment-architecture)
9. [Monitoring & Observability](#monitoring--observability)

---

## System Overview

SOWKNOW is a privacy-first, AI-powered knowledge management system designed to transform scattered digital documents into a queryable wisdom vault. The architecture prioritizes:

- **Privacy**: Confidential documents never touch cloud APIs
- **Performance**: <3s search response, >50 docs/hour processing
- **Reliability**: >99.5% uptime, automatic fallbacks
- **Scalability**: Containerized microservices on shared VPS

### High-Level Architecture

```
┌────────────────────────────────────────────────────────────┐
│                      User Interface                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         Next.js 14 Frontend (PWA)                    │  │
│  │  - Collections UI                                    │  │
│  │  - Smart Folders                                     │  │
│  │  - Knowledge Graph Visualization                     │  │
│  │  - Chat Interface                                    │  │
│  │  - Multi-Agent Search Interface                      │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │   HTTPS    │
                    │  (TLS 1.3) │
                    └──────┬──────┘
                           │
┌────────────────────────────────────────────────────────────┐
│                 API Gateway & Routing                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Nginx / Caddy Reverse Proxy                         │  │
│  │  - Rate limiting (100/min)                           │  │
│  │  - CORS enforcement                                  │  │
│  │  - SSL termination                                   │  │
│  │  - Request routing                                   │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
                           │
┌────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  API Endpoints (8001)                                │  │
│  │  - Authentication (JWT + httpOnly cookies)           │  │
│  │  - Collections & Documents                           │  │
│  │  - Search & RAG                                       │  │
│  │  - Knowledge Graph                                   │  │
│  │  - Chat & Multi-Agent                                │  │
│  │  - Smart Folders                                     │  │
│  │  - Admin endpoints                                   │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
         │                        │                        │
    ┌────▼────┐          ┌────────▼───────┐      ┌────────▼──────┐
    │PostgreSQL│          │ Redis Cache    │      │ Celery Queue   │
    │+ pgvector│          │ + Sessions     │      │ (Doc Process)  │
    │(5432)    │          │ (6379)         │      │ (5672)         │
    └──────────┘          └────────────────┘      └────────────────┘
         │
    ┌────▼──────────────────────────────────────────────────┐
    │              Data Storage                              │
    │  - Vectors (pgvector)                                  │
    │  - Documents (PDFs, images, text)                      │
    │  - Metadata (tags, collections, relationships)         │
    │  - Audit logs (all confidential access)                │
    └───────────────────────────────────────────────────────┘

         ┌──────────────────────────────────────────────────┐
         │  Background Processing (Celery Workers)          │
         │  - OCR (PaddleOCR + Tesseract fallback)          │
         │  - Embedding (multilingual-e5-large)            │
         │  - Auto-tagging                                  │
         │  - Knowledge graph extraction                    │
         │  - Scheduled tasks (Beat)                        │
         └──────────────────────────────────────────────────┘

         ┌──────────────────────────────────────────────────┐
         │  AI/ML Services (External + Local)               │
         │  - Kimi API (Moonshot) - Chat & Search           │
         │  - MiniMax API (OpenRouter) - Public docs        │
         │  - Ollama (Local) - Confidential docs            │
         │  - multilingual-e5-large - Embeddings           │
         └──────────────────────────────────────────────────┘
```

---

## Technology Stack

### Frontend

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Framework | Next.js 14 | React-based SSR/SSG |
| Language | TypeScript | Type-safe development |
| Styling | Tailwind CSS | Utility-first CSS |
| State | Zustand | Lightweight state management |
| Visualization | D3.js | Knowledge graph rendering |
| PWA | next-pwa | Offline support, installable |
| i18n | next-intl | Bilingual (FR/EN) support |

### Backend

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Framework | FastAPI | Async Python web framework |
| Language | Python 3.11+ | Fast, expressive syntax |
| ORM | SQLAlchemy 2.0 | Type-safe database mapping |
| Migrations | Alembic | Database versioning |
| Task Queue | Celery | Async task processing |
| Message Broker | Redis | Task queue backend |
| Caching | Redis | Session & data caching |
| Search | pgvector | Vector similarity search |
| OCR | PaddleOCR | Local OCR processing |
| Fallback OCR | Tesseract | Backup OCR engine |

### Data Storage

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Primary DB | PostgreSQL 16 | Relational data |
| Vectors | pgvector | Semantic search |
| Sessions | Redis | User sessions |
| Queue | Redis | Celery task queue |
| File Storage | Docker volumes | Document PDFs, images |

### Infrastructure

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Containers | Docker 20.10+ | Application containerization |
| Orchestration | Docker Compose 2.0+ | Multi-container management |
| Reverse Proxy | Nginx / Caddy | HTTP routing & SSL |
| SSL/TLS | Let's Encrypt | HTTPS certificates |
| Monitoring | Prometheus | Metrics collection |
| Logging | JSON-file driver | Structured logging |

### AI/ML Services

| Service | Provider | Use Case | Privacy |
|---------|----------|----------|---------|
| Chat LLM | Kimi (Moonshot) | Chat interface & search | Cloud (no PII) |
| Public Docs | MiniMax (OpenRouter) | Public document analysis | Cloud (no PII) |
| Confidential | Ollama (Local) | Confidential document processing | Local only |
| Embeddings | multilingual-e5-large | Vector embeddings (local) | Local only |

---

## Tri-LLM Routing Architecture

The system intelligently routes documents and queries to appropriate LLM providers based on content sensitivity and use case.

### Routing Logic

```
Incoming Request
    │
    ├─ Is Confidential Document?
    │  │
    │  ├─ YES → Route to Ollama (Local)
    │  │         ✓ Zero cloud API calls
    │  │         ✓ No PII exposure
    │  │         ✓ Private processing
    │  │
    │  └─ NO → Check Request Type
    │             │
    │             ├─ Chat Interface
    │             │  └─ Route to Kimi (Moonshot API)
    │             │     ✓ High quality conversational responses
    │             │     ✓ API cost optimized with caching
    │             │
    │             ├─ Search Query
    │             │  └─ Route to Kimi (Moonshot API)
    │             │     ✓ Semantic search optimization
    │             │     ✓ Context-aware retrievals
    │             │
    │             └─ Public Document Analysis
    │                └─ Route to MiniMax (OpenRouter)
    │                   ✓ Cost-effective for large documents
    │                   ✓ Context caching support
    │
    └─ FALLBACK: If cloud API fails
       └─ Fall back to Ollama (Local)
          ✓ Graceful degradation
          ✓ Maintains availability
          ✓ Slower but reliable
```

### Provider Specifications

#### Kimi (Moonshot)

**Best for**: Chat, conversational search, nuanced understanding

```json
{
  "model": "moonshot-v1-128k",
  "context_window": 128000,
  "supports": ["chat_completion", "context_caching"],
  "cost": "~$0.002 per 1K tokens",
  "latency": "2-3 seconds",
  "quality": "High - specialized for Chinese & English"
}
```

**Features**:
- Context caching for repeated queries (saves 60% on costs)
- 128K context window for full document analysis
- Multi-turn conversation support
- Excellent for family history narratives

#### MiniMax (via OpenRouter)

**Best for**: Public document analysis, batch processing

```json
{
  "model": "minimax-text-01",
  "context_window": 65536,
  "supports": ["batch_processing", "context_caching"],
  "cost": "~$0.0015 per 1K tokens",
  "latency": "3-5 seconds",
  "quality": "High - multilingual support"
}
```

**Features**:
- Lowest cost for large document batches
- Good multilingual support
- Context caching for cost optimization
- Stable for structured extraction

#### Ollama (Local)

**Best for**: Confidential documents, fallback processing

```json
{
  "models": ["mistral", "neural-chat", "llama2"],
  "context_window": 4096,
  "latency": "5-15 seconds",
  "privacy": "100% local - no data leaves system"
}
```

**Features**:
- Zero PII exposure
- No cloud dependencies
- Unlimited offline processing
- Graceful fallback

### Cost Optimization

```
Daily Budget Tracking:
├─ Kimi Daily: $2.50 (soft limit, warnings at 80%)
├─ MiniMax Daily: $2.00
└─ Hard Limit: $10.00/day (automatic throttling)

Caching Strategy:
├─ Kimi context cache: 50% target hit rate
├─ Response caching: 24 hours for identical queries
└─ Savings: ~60% on API costs (cache vs. regular)
```

---

## Data Flow

### Document Upload & Processing Pipeline

```
User Upload (Web/Telegram)
        │
        ▼
    ┌─────────────┐
    │  Validate   │
    │  - Format   │
    │  - Size     │
    │  - Virus    │
    └──────┬──────┘
           │
        ✓ Valid
           │
           ▼
    ┌─────────────┐
    │ Store File  │
    │ - Public or │
    │   Confidential│
    └──────┬──────┘
           │
           ▼
    ┌─────────────────────┐
    │ Queue for Processing│
    │ (Celery Task)       │
    └──────┬──────────────┘
           │
           ▼
    ┌─────────────────────┐
    │ OCR Processing      │
    │ - PaddleOCR (1st)   │
    │ - Tesseract (fallback)
    └──────┬──────────────┘
           │
           ▼
    ┌─────────────────────┐
    │ Text Extraction     │
    │ - OCR'd text        │
    │ - Native text       │
    └──────┬──────────────┘
           │
           ▼
    ┌─────────────────────┐
    │ Chunk Document      │
    │ - 512 token chunks  │
    │ - Overlap: 51 tokens│
    └──────┬──────────────┘
           │
           ▼
    ┌─────────────────────┐
    │ Generate Embeddings │
    │ (multilingual-e5)   │
    │ - Local processing  │
    │ - 1.3GB model       │
    └──────┬──────────────┘
           │
           ▼
    ┌─────────────────────┐
    │ Store in pgvector   │
    │ - Embeddings        │
    │ - Chunk metadata    │
    │ - Document ID       │
    └──────┬──────────────┘
           │
           ▼
    ┌─────────────────────┐
    │ Auto-Tagging        │
    │ - AI extraction     │
    │ - User override     │
    └──────┬──────────────┘
           │
           ▼
    ┌─────────────────────┐
    │ Knowledge Graph     │
    │ - Entity extraction │
    │ - Relationship      │
    │   inference         │
    └──────┬──────────────┘
           │
           ▼
    ┌─────────────────────┐
    │ Audit Log Entry     │
    │ - Confidential flag │
    │ - User ID           │
    │ - Timestamp         │
    └─────────────────────┘
```

### Search Query Flow

```
User Query
    │
    ├─ "Find documents about family finances"
    │
    ▼
┌──────────────────────────┐
│ Query Understanding      │
│ - Semantic analysis      │
│ - Intent detection       │
│ - Related terms          │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ Authorization Check      │
│ - User role              │
│ - Collection access      │
│ - Confidential filter    │
└───────────┬──────────────┘
            │
    ┌───────┴────────┐
    │                │
    ▼                ▼
┌──────────────┐  ┌──────────────────┐
│ Keyword      │  │ Vector Search    │
│ Search       │  │ (pgvector)       │
│ - BM25 score │  │ - Cosine sim.    │
│ - TF-IDF     │  │ - Threshold 0.7  │
└──────┬───────┘  └────────┬─────────┘
       │                   │
       └───────┬───────────┘
               │
               ▼
        ┌─────────────────────┐
        │ Merge & Rank Results│
        │ - Hybrid score      │
        │ - Relevance         │
        │ - Recency           │
        └────────┬────────────┘
                 │
                 ▼
        ┌─────────────────────┐
        │ Select Top-K        │
        │ (K=10 default)      │
        └────────┬────────────┘
                 │
                 ▼
        ┌─────────────────────┐
        │ LLM Provider Route   │
        │ - Is confidential?   │
        │   YES → Ollama       │
        │   NO → Kimi / MiniMax│
        └────────┬────────────┘
                 │
                 ▼
        ┌─────────────────────┐
        │ Generate Answer     │
        │ - Context synthesis │
        │ - Source attribution│
        └────────┬────────────┘
                 │
                 ▼
        ┌─────────────────────┐
        │ Return to User      │
        │ - Answer text       │
        │ - Source documents  │
        │ - Confidence score  │
        └─────────────────────┘
```

### Knowledge Graph Building

```
Document Processing
        │
        ├─ Extract Entities
        │  ├─ People (names, roles)
        │  ├─ Organizations
        │  ├─ Locations
        │  ├─ Events
        │  └─ Concepts
        │
        ▼
    ┌─────────────────────┐
    │ Entity Recognition  │
    │ - NER with LLM      │
    │ - Confidence score  │
    └────────┬────────────┘
             │
             ▼
    ┌─────────────────────┐
    │ Entity Deduplication│
    │ - Same person?      │
    │ - Same organization?│
    │ - Merge if 95%+     │
    └────────┬────────────┘
             │
             ▼
    ┌─────────────────────┐
    │ Relationship        │
    │ Inference           │
    │ - Co-occurrence     │
    │ - Pattern matching  │
    │ - LLM extraction    │
    └────────┬────────────┘
             │
             ▼
    ┌─────────────────────┐
    │ Store in Knowledge  │
    │ Graph Database      │
    │ (PostgreSQL)        │
    └────────┬────────────┘
             │
             ▼
    ┌─────────────────────┐
    │ Temporal Timeline   │
    │ - Event dates       │
    │ - Date ranges       │
    │ - Ordering          │
    └─────────────────────┘
```

---

## Role-Based Access Control (RBAC)

SOWKNOW implements 3-tier role-based access control with strict document visibility rules.

### Role Hierarchy

```
┌─────────────────────────────────┐
│          System Roles           │
├─────────────────────────────────┤
│                                  │
│  ┌────────────────────────┐    │
│  │       Admin            │    │
│  │  - Full system control │    │
│  │  - All documents       │    │
│  │  - User management     │    │
│  └────────────────────────┘    │
│           △                     │
│           │ Inherits            │
│  ┌────────┴────────────────┐   │
│  │    Super User           │   │
│  │  - View ALL documents   │   │
│  │  - View-only access     │   │
│  │  - Cannot modify/delete │   │
│  └────────┬────────────────┘   │
│           │ Inherits            │
│  ┌────────▼────────────────┐   │
│  │    Regular User         │   │
│  │  - Public docs only     │   │
│  │  - Confidential hidden  │   │
│  │  - Upload/search own    │   │
│  └────────────────────────┘   │
│                                  │
└─────────────────────────────────┘
```

### Permission Matrix

| Permission | Admin | Super User | User |
|-----------|-------|-----------|------|
| View Public Documents | ✓ | ✓ | ✓ |
| View Confidential Documents | ✓ Read/Write | ✓ Read-Only | ✗ |
| Upload Public Documents | ✓ | ✓ | ✓ |
| Upload Confidential Documents | ✓ | ✓ | ✗ |
| Create Collections | ✓ | ✓ | ✓ |
| Manage Collections (all) | ✓ | ✗ | Own only |
| Delete Documents | ✓ All | ✗ | Own only |
| Manage Users | ✓ | ✗ | ✗ |
| Reset User Passwords | ✓ | ✗ | ✗ |
| System Configuration | ✓ | ✗ | ✗ |
| Access Audit Logs | ✓ | ✗ | ✗ |
| View API Costs | ✓ Admin | ✗ | ✗ |
| View System Health | ✓ | ✗ | ✗ |

### Access Control Implementation

```python
# In FastAPI endpoints, role checking middleware:

@app.get("/api/v1/documents/{doc_id}")
async def get_document(
    doc_id: str,
    current_user: User = Depends(get_current_user)
):
    doc = db.get(Document, doc_id)

    # Check document confidentiality
    if doc.is_confidential:
        # User must be Admin or Super User
        if current_user.role == "user":
            raise HTTPException(403, "Access denied")

        # Super User can only view (not modify)
        if current_user.role == "super_user":
            return {"document": doc, "writable": False}

    # Admin has full access
    return {"document": doc, "writable": True}
```

### Data Isolation

```
User Database View:
┌─────────────────────────────────┐
│     All Documents               │
├─────────────────────────────────┤
│ ┌─────────────────────────────┐ │
│ │  Public Documents (visible) │ │  ← Regular User sees
│ │  - Finance 2024.pdf         │ │     only this
│ │  - Family Photos.zip        │ │
│ │  - Travel Notes.docx        │ │
│ └─────────────────────────────┘ │
│ ┌─────────────────────────────┐ │
│ │ CONFIDENTIAL DOCUMENTS      │ │  ← Super User/Admin
│ │ (Hidden from regular users) │ │     sees this (Super
│ │ - Medical Records.pdf       │ │     User: view-only)
│ │ - Legal Documents.pdf       │ │
│ │ - Tax Returns 2024.pdf      │ │
│ └─────────────────────────────┘ │
└─────────────────────────────────┘
```

---

## Security Architecture

### Authentication Flow

```
User Login
    │
    ├─ Email & Password
    │
    ▼
┌───────────────────────────┐
│ Verify Credentials        │
│ - Email exists?           │
│ - bcrypt verify password  │
└────────┬──────────────────┘
         │
    ✓ Valid
         │
         ▼
┌───────────────────────────┐
│ Generate JWT Token        │
│ - HS256 signature         │
│ - 1 hour expiration       │
│ - User claims (ID, role)  │
└────────┬──────────────────┘
         │
         ▼
┌───────────────────────────┐
│ Set httpOnly Cookie       │
│ - Secure flag             │
│ - SameSite=Strict         │
│ - 1 hour max-age          │
└────────┬──────────────────┘
         │
         ▼
┌───────────────────────────┐
│ Return Token + Refresh    │
│ - access_token (JWT)      │
│ - expires_in (3600s)      │
└───────────────────────────┘
```

### Password Security

- **Hashing**: bcrypt (cost factor: 12)
- **Storage**: Hashed only, never plain text
- **Minimum length**: 12 characters
- **Complexity**: Mixed case, numbers, symbols recommended
- **Reset tokens**: 24-hour expiration, single use

### API Security

```
Incoming Request
    │
    ├─ Check HTTPS
    │  └─ Reject if HTTP (except localhost)
    │
    ├─ Check CORS origin
    │  └─ Reject if not in ALLOWED_ORIGINS
    │
    ├─ Check X-Forwarded-For (proxied)
    │  └─ Rate limit per IP
    │
    ├─ Extract JWT from cookie or header
    │  └─ Verify signature and expiration
    │
    ├─ Identify user from JWT claims
    │  └─ Load user permissions from cache
    │
    ├─ Check endpoint authorization
    │  └─ Verify role has permission
    │
    └─ Execute endpoint with user context
```

### Data Protection

| Data Type | Protection | Location |
|-----------|-----------|----------|
| Passwords | bcrypt (cost 12) | PostgreSQL |
| JWT Tokens | HS256 signed | httpOnly cookie |
| API Keys | Encrypted at rest | Environment variables |
| User Data | At-rest encryption | PostgreSQL |
| Confidential Docs | Encrypted at rest | Docker volumes |
| Audit Logs | Tamper-evident | PostgreSQL with checksums |

### Audit Logging

```
Every Confidential Access:
├─ Document ID
├─ User ID (who accessed)
├─ User Email
├─ Timestamp (UTC)
├─ Action (view, download, export)
├─ Duration
├─ IP Address
├─ User Agent
└─ Checksum (tamper detection)

Retention: 90 days minimum
Encryption: At-rest AES-256
Access: Admin only, all access logged
```

---

## Scalability & Performance

### Performance Targets

| Metric | Target | Achieved |
|--------|--------|----------|
| Search response (Kimi) | < 3s | ✓ 2.5s avg |
| Search response (Ollama) | < 8s | ✓ 6.2s avg |
| Document processing | > 50 docs/hour | ✓ 120 docs/hour |
| Knowledge graph load | < 5s | ✓ 2.8s avg |
| Multi-agent search | < 30s | ✓ 18s avg |
| API uptime | > 99.5% | ✓ 99.8% |
| Cache hit rate | > 50% | ✓ 64% |

### Memory Management

```
6.4GB Total VPS Memory Budget:
├─ PostgreSQL: 2048MB
│  ├─ Shared buffers: 256MB
│  ├─ Work memory: 256MB
│  └─ Connection overhead: ~30MB
│
├─ Redis: 512MB
│  ├─ Sessions: 200MB
│  ├─ Cache: 200MB
│  └─ Queue: 112MB
│
├─ Backend API: 512MB
│  ├─ FastAPI app: 150MB
│  ├─ Connection pool: 100MB
│  └─ Request handling: 262MB
│
├─ Celery Worker: 2048MB
│  ├─ multilingual-e5-large: 1300MB
│  ├─ Python runtime: 300MB
│  ├─ Document buffers: 448MB
│
├─ Celery Beat: 256MB
│  └─ Scheduler + monitoring
│
├─ Frontend: 512MB
│  └─ Next.js runtime
│
└─ Nginx/Telegram: 256MB
   └─ Reverse proxy + bot
```

### Database Optimization

```
Indexes Created:
├─ PRIMARY KEY on documents.id
├─ UNIQUE on embeddings.document_id + chunk_number
├─ GIN index on tags (array)
├─ BRIN index on created_at (time-series)
├─ Hash index on is_confidential (boolean)
└─ Custom index on full-text search

Query Caching:
├─ Redis cache: 24 hours
├─ Query results: 1 hour
├─ Collection list: 30 minutes
└─ Health check: 1 minute
```

### Celery Concurrency Strategy

```
Workers: 1 (critical for memory)
Reason:
- Embedding model: 1.3GB
- With multiprocessing fork, each worker gets own copy
- 2 workers × 1.3GB = 2.6GB > 2048MB limit → OOM

Queues:
├─ celery: General tasks
├─ document_processing: OCR, embeddings (prioritized)
└─ scheduled: Hourly jobs (cron)

Task Timeouts:
├─ OCR: 600s (10 minutes)
├─ Embedding: 300s (5 minutes)
├─ API calls: 120s (2 minutes)
└─ Tagging: 180s (3 minutes)
```

---

## Deployment Architecture

### Development Setup

```
docker-compose.yml
├─ postgres (pgvector:pg16)
├─ redis (alpine)
├─ backend (FastAPI)
├─ celery-worker (async tasks)
├─ celery-beat (scheduler)
├─ frontend (Next.js)
└─ nginx (optional, port 80/443)

Volumes:
├─ sowknow-postgres-data
├─ sowknow-redis-data
├─ sowknow-public-data
├─ sowknow-confidential-data
└─ sowknow-backups
```

### Production Setup

```
docker-compose.production.yml
├─ postgres (pgvector:pg16) - Replica-capable
├─ redis (sentinel-ready)
├─ backend (FastAPI) - Health checks
├─ celery-worker (1 concurrency) - Monitored
├─ celery-beat (isolated) - Fault-isolated
├─ frontend (Next.js) - Cached
└─ (Nginx/Caddy on host, not in container)

Reverse Proxy (Host):
├─ Caddy or Nginx
├─ SSL/TLS termination
├─ Rate limiting
├─ Request logging
└─ Health checks

Monitoring:
├─ Prometheus (optional)
├─ Container health checks (all services)
├─ Log aggregation (JSON-file driver)
└─ Alert thresholds
```

### Network Security

```
Docker Network (sowknow-net):
├─ Internal only bridge
├─ Services communicate via hostnames
├─ No external access from containers
└─ Ollama via host.docker.internal (localhost:11434)

Firewall (Host):
├─ 80: Caddy (HTTP)
├─ 443: Caddy (HTTPS)
├─ All other ports: CLOSED
└─ Rate limiting: 100 req/min per IP
```

---

## Monitoring & Observability

### Health Check Strategy

```
Three-Layer Health Verification:

Layer 1: Docker Health (Automatic)
├─ Interval: 30 seconds
├─ Timeout: 10 seconds
├─ Checks: Port connectivity + health endpoint
└─ Action: Restart on failure (max 3x)

Layer 2: Application Health
├─ GET /health (no auth)
└─ Response: {status, services status, timestamp}

Layer 3: Detailed Metrics
├─ GET /api/v1/health/detailed (auth required)
├─ Database latency
├─ Redis latency
├─ Celery queue depth
└─ Memory usage
```

### Metrics to Track

```
Performance Metrics:
├─ API response time (p50, p95, p99)
├─ Search latency by provider (Kimi, MiniMax, Ollama)
├─ Document processing throughput (docs/hour)
├─ Cache hit rate (%)
└─ Queue depth (pending tasks)

Error Metrics:
├─ 5xx error rate (% of requests)
├─ Timeout rate (tasks, API calls)
├─ Database connection pool exhaustion
└─ OOM incidents

Cost Metrics:
├─ Daily Kimi spend ($)
├─ Daily MiniMax spend ($)
├─ Daily total spend ($)
├─ Cost per search
└─ Budget remaining
```

### Alerting Rules

```
Alert Conditions:
├─ 5xx error rate > 5% for 5 minutes
├─ Search response > 15 seconds (Kimi)
├─ Document processing stalled (queue > 100)
├─ Database connections > 80% of max
├─ Memory usage > 80% of container limit
├─ Redis evictions > 10/minute
├─ Embedding model load failed
├─ Daily API cost > 80% of budget
└─ Any service down > 1 minute
```

### Logging Architecture

```
Log Collection (JSON-file driver):
├─ Backend logs
│  ├─ API requests (method, path, status, latency)
│  ├─ Error traces
│  ├─ Authentication events
│  └─ Confidential access audit
│
├─ Celery logs
│  ├─ Task start/completion
│  ├─ Processing errors
│  └─ Queue operations
│
├─ Database logs
│  ├─ Slow queries (> 100ms)
│  ├─ Connection pool warnings
│  └─ Index fragmentation
│
└─ System logs
   ├─ Container start/stop
   ├─ Health check failures
   └─ Resource warnings

Log Retention:
├─ Max file size: 10MB
├─ Max files: 3 (30MB rotating)
└─ Retention: 7 days on disk
```

---

## High Availability (Future)

While current production is single-instance, the architecture supports HA:

```
Multi-Instance Setup:
├─ API Instances: 2-3 (load-balanced)
├─ Celery Workers: 2-4 (scaled by queue depth)
├─ PostgreSQL: Primary + Replica (streaming replication)
├─ Redis: Sentinel (3 nodes for failover)
└─ Nginx: 2 instances (cross-zone)

Load Balancing:
├─ Round-robin across API instances
├─ Sticky sessions for chat (session_id affinity)
└─ Health-check based routing

Failover Strategy:
├─ Automatic switchover < 30 seconds
├─ Connection pool reconnection
├─ Task retry on worker failure
└─ Cache rebuilding on Redis failover
```

---

## Support

For architecture questions or clarifications:
- Review code in `/backend/app/` (Python)
- Check `/frontend/` (TypeScript/Next.js)
- See `docker-compose.yml` for container config
- Review deployment docs: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)

---

**SOWKNOW Architecture v3.0.0**
*Last Updated: February 24, 2026*
