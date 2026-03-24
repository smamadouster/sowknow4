# Project Configuration - SOWKNOW Multi-Generational Legacy Knowledge System

## CRITICAL RULES
- **PRIVACY FIRST**: Zero PII ever sent to cloud APIs (MiniMax/OpenRouter/PaddleOCR)
- **CONFIDENTIAL ROUTING**: Auto-switch to shared Ollama (mistral:7b local) when confidential documents detected
- **VPS RESOURCE CONSTRAINTS**: Total SOWKNOW container memory <= 6.4GB (shared 16GB VPS)
- **TRI-LLM STRATEGY**: MiniMax M2.7 for search/articles, Mistral Small 2603 (OpenRouter) for chat/collections/telegram, Ollama (mistral:7b local) for confidential docs
- **ROLE-BASED ACCESS**: Strict RBAC with 3 roles: Admin (full), Super User (view all), User (public only)
- **NO GPU**: OCR via PaddleOCR with Tesseract fallback, embeddings via CPU with multilingual-e5-large
- **FRENCH DEFAULT**: Interface defaults to French with full English support

## **>>> CONTAINER & DEVOPS DISCIPLINE — MANDATORY <<<**

> **THESE RULES ARE NON-NEGOTIABLE. VIOLATING THEM CAUSED 77GB IMAGE BLOAT, 3000+ HEALTHCHECK FAILURES, AND PUBLIC DATABASE EXPOSURE. DO NOT SKIP.**

### **ONE COMPOSE FILE TO RULE THEM ALL**
- **`docker-compose.yml`** is the SINGLE SOURCE OF TRUTH for production. Period.
- **`docker-compose.dev.yml`** is the ONLY other allowed compose file (for local dev).
- **NEVER create** `docker-compose.production.yml`, `docker-compose.simple.yml`, `docker-compose.prebuilt.yml`, or any other variant. Archived copies exist in `docker/archived-compose/` as a cautionary tale.
- If you need environment-specific behavior, use **profiles** or **environment variables**, not separate files.

### **NAMING CONVENTION**
- **ALL containers MUST use the `sowknow4-` prefix.** No `sowknow-`, no bare names.
- Pattern: `sowknow4-{service}` (e.g., `sowknow4-backend`, `sowknow4-postgres`, `sowknow4-frontend`)
- This prevents collisions with other projects (ghostshell, etc.) on the shared VPS.

### **PORT EXPOSURE — ZERO TRUST**
- **NEVER expose internal service ports to the host.** PostgreSQL (5432), Redis (6379), Vault (8200), NATS (4222/8222) must have NO `ports:` directive.
- Only **backend (8001:8000)** and **frontend (3000:3000)** are exposed.
- To access internal services for debugging: `docker exec -it sowknow4-postgres psql -U sowknow`
- Optional services (nginx, prometheus) use **profiles** and only expose their required ports.

### **HEALTHCHECK DISCIPLINE**
- Every service MUST have a healthcheck that ACTUALLY WORKS. Test it: `docker inspect --format '{{json .State.Health}}' <container>`
- Backend healthcheck must match the ACTUAL endpoint path (`/api/v1/health` via bind-mounted main.py, or `/health` via Dockerfile.minimal's renamed main.py).
- Celery worker healthcheck: use simple `pgrep` — complex Python healthchecks break when dependencies have import errors.
- **After ANY compose change, run `docker compose up -d` and verify ALL containers show `(healthy)` within 5 minutes.** Fix before committing.

### **IMAGE HYGIENE**
- Run `docker system df` before and after builds. If reclaimable > 50%, run `docker system prune -f`.
- Never leave dangling images. After a successful build+deploy: `docker image prune -f`
- Dockerfiles must use multi-stage builds or slim base images. No `python:3.11` (1GB+), always `python:3.11-slim`.

### **BIND MOUNT AWARENESS**
- The `./backend:/app` bind mount **overrides all files built into the image**. This means Dockerfile `COPY` and `RUN mv` commands for app files are irrelevant at runtime.
- The app that runs is whatever is in `./backend/`, not what was built. Keep this in mind for healthchecks and entrypoints.

## PROJECT CONTEXT
- **Project Type**: Privacy-first AI-powered legacy knowledge vault with conversational interface
- **Primary Goal**: Transform 100GB+ of scattered digital life into queryable wisdom system
- **Core Stack**: FastAPI + Next.js + PostgreSQL/pgvector + Celery + Redis
- **AI Stack**: MiniMax M2.7 (search/articles) + Mistral Small 2603 via OpenRouter (chat/telegram/collections) + Ollama mistral:7b (confidential docs) + multilingual-e5-large embeddings
- **Architecture**: Containerized microservices (8 containers) on shared Hostinger VPS
- **Key Innovation**: Tri-LLM routing with automatic privacy protection for confidential docs; OpenRouter caching for cost optimization

## DEVELOPMENT PATTERNS
- **Frontend**: Next.js 14 PWA with TypeScript, Tailwind CSS, Zustand state management
- **Backend**: FastAPI async endpoints, SQLAlchemy 2.0 ORM, Alembic migrations
- **File Organization**: Feature-based structure, clear separation between public/confidential logic
- **API Design**: RESTful with JWT auth, httpOnly cookies (not localStorage)
- **Error Handling**: Graceful degradation - UI never crashes on backend failures
- **Testing Strategy**: E2E testing for critical paths, manual validation by 5 users at launch
- **Language Support**: Bilingual (FR/EN) with next-intl, AI responses in query language

## SWARM ORCHESTRATION
- **Agent Coordination**: Phase 3 implements multi-agent search (Clarifier, Researcher, Verifier, Answerer)
- **Task Distribution**: Celery with Redis for async processing (OCR, embeddings, indexing)
- **Parallel Execution**: Batch processing of documents (50+/hour), concurrent user limit: 5
- **LLM Routing Logic**: Smart routing based on document context and user role
- **Pipeline Orchestration**: Sequential document processing pipeline with status tracking
- **Fallback Handling**: Tesseract OCR fallback, MiniMax retry logic, Ollama graceful degradation

## MEMORY MANAGEMENT
- **Context Storage**: PostgreSQL for all persistent data (vectors, chat history, metadata)
- **Decision Tracking**: Audit logs for confidential access, LLM routing decisions logged
- **Session Management**: Redis for chat sessions, JWT refresh tokens
- **Embedding Cache**: multilingual-e5-large model loaded in Celery worker (1.3GB)
- **Prompt Optimization**: OpenRouter response caching for cost optimization on repeated queries
- **Knowledge Persistence**: Daily backups, encrypted cold storage, 7-4-3 retention policy

## DEPLOYMENT & CI/CD
- **Production Directory**: /var/docker/sowknow4
- **Container Strategy**: 8 Docker containers with strict memory limits, sowknow-net internal network
- **Build Process**: Docker Compose for all SOWKNOW services (Ollama excluded - shared instance)
- **Health Checks**: Mandatory /health endpoints, 30-60s intervals with alerting
- **Deployment**: Hostinger VPS with Nginx reverse proxy, TLS via Let's Encrypt
- **Monitoring**: Container health, VPS memory (80% threshold), API costs, processing anomalies
- **Backup Strategy**: Daily PostgreSQL dumps, weekly encrypted offsite, monthly restore tests
- **Admin Routes**: Administrative endpoints are located in main_minimal.py for security isolation

## MONITORING & ANALYTICS
- **Performance Tracking**: Search latency (<3s MiniMax/OpenRouter, <8s Ollama), processing throughput (>50 docs/hour)
- **Error Monitoring**: 5xx error rate alerts (>5%), processing queue depth (>100)
- **Cost Analytics**: Daily MiniMax/OpenRouter API cost tracking with cache hit-rate metrics, budget caps
- **Quality Metrics**: OCR accuracy (>97%), search relevance (>90% satisfaction), cache hit-rate (>50% target)
- **User Analytics**: Feature adoption (Smart Collections/Folders >3/5 users)
- **System Health**: Daily anomaly reports (09:00 AM) for stuck processing jobs, cache effectiveness monitoring
- **Success Metrics**: Information retrieval time reduction (>70%), system uptime (>99.5%), cache cost savings (>60%)

## SECURITY & COMPLIANCE
- **Authentication**: JWT with bcrypt hashing, refresh tokens, httpOnly secure cookies
- **Authorization**: 3-tier RBAC with strict bucket isolation (confidential invisible to Users)
  - **Admin**: Full access to all documents, user management, system configuration
  - **Super User**: VIEW-ONLY access to confidential documents; cannot modify, delete, or manage users
  - **User**: Access to public documents only; confidential documents are completely invisible

### RBAC Permissions Matrix

| Permission | Admin | Super User | User |
|------------|-------|------------|------|
| View Public Documents | Yes | Yes | Yes |
| View Confidential Documents | Yes | Yes (View-Only) | No |
| Upload Public Documents | Yes | Yes | Yes |
| Upload Confidential Documents | Yes | Yes | Yes |
| Delete Documents | Yes | No | No (Own only) |
| Manage Users | Yes | No | No |
| Reset User Passwords | Yes | No | No |
| System Configuration | Yes | No | No |
| Access Audit Logs | Yes | No | No |

- **Network Security**: Nginx rate limiting (100/min), CORS restrictions, internal Docker network
- **Data Protection**: At-rest encryption, zero PII to cloud, Ollama-only for confidential processing
- **Secret Management**: .env files excluded from Git, API keys in environment variables
- **Audit Trail**: All confidential access logged with timestamp and user ID
- **Compliance**: Privacy-by-design, data minimization, purpose limitation for legacy preservation

## ADMIN API ENDPOINTS

### Password Management
- **POST /api/v1/admin/users/{id}/reset-password**
  - **Description**: Reset a user's password to a secure temporary password
  - **Access**: Admin only
  - **Request Body**: None
  - **Response**: `{ "new_password": "temporary_password_string" }`
  - **Behavior**: Generates a cryptographically secure temporary password, hashes it with bcrypt, and returns the plain text password for secure delivery to the user
  - **Audit**: All password resets are logged with admin ID, target user ID, and timestamp

## OCR CONFIGURATION

### OCR Engine Stack
- **Primary**: PaddleOCR (open source, CPU-based, multilingual)
- **Fallback**: Tesseract OCR (open source, CPU-based)
- **Privacy**: All OCR processing done locally - zero PII sent to cloud APIs

### OCR Processing Modes

| Mode | Image Size | Use Case | Passes |
|------|------------|----------|--------|
| Base | 1024x1024 | Standard documents, receipts, forms | 1 pass |
| Large | 1280x1280 | High-resolution images, detailed photos | 1 pass |
| Gundam | Multi-pass | Complex documents, handwriting, degraded text | 3 passes + merging |

### Mode Specifications

**Base Mode (1024x1024)**
- Single pass OCR
- Fast processing for standard documents
- Best for: receipts, invoices, standard forms, clear print

**Large Mode (1280x1280)**
- Single pass with higher resolution
- Better detail capture
- Best for: high-resolution photos, detailed images, small text

**Gundam Mode (Multi-pass)**
- 3 passes at different scales (0.5x, 1x, 1.5x)
- Result merging with confidence scoring
- Best for: complex layouts, handwriting, degraded/old documents

### OCR Audit Logging
- All OCR operations logged with engine used (paddle/tesseract)
- Mode selection recorded for each document
- Processing time tracked
- Confidence scores stored for quality metrics
