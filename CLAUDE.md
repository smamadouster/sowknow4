# Project Configuration - SOWKNOW Multi-Generational Legacy Knowledge System

## CRITICAL RULES
- **PRIVACY FIRST**: Zero PII ever sent to cloud APIs (Gemini Flash/Hunyuan-OCR)
- **CONFIDENTIAL ROUTING**: Auto-switch to shared Ollama when confidential documents detected
- **VPS RESOURCE CONSTRAINTS**: Total SOWKNOW container memory <= 6.4GB (shared 16GB VPS)
- **DUAL-LLM STRATEGY**: Gemini Flash for public docs, shared Ollama for confidential docs
- **ROLE-BASED ACCESS**: Strict RBAC with 3 roles: Admin (full), Super User (view all), User (public only)
- **NO GPU**: OCR via Hunyuan API, embeddings via CPU with multilingual-e5-large
- **FRENCH DEFAULT**: Interface defaults to French with full English support

## PROJECT CONTEXT
- **Project Type**: Privacy-first AI-powered legacy knowledge vault with conversational interface
- **Primary Goal**: Transform 100GB+ of scattered digital life into queryable wisdom system
- **Core Stack**: FastAPI + Next.js + PostgreSQL/pgvector + Celery + Redis
- **AI Stack**: Gemini Flash (Google Generative AI API) + shared Ollama + multilingual-e5-large embeddings
- **Architecture**: Containerized microservices (8 containers) on shared Hostinger VPS
- **Key Innovation**: Dual-LLM routing with automatic privacy protection for confidential docs; context caching for up to 80% cost reduction on repeated queries

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
- **Fallback Handling**: Tesseract OCR fallback, Gemini Flash retry logic, Ollama graceful degradation

## MEMORY MANAGEMENT
- **Context Storage**: PostgreSQL for all persistent data (vectors, chat history, metadata)
- **Decision Tracking**: Audit logs for confidential access, LLM routing decisions logged
- **Session Management**: Redis for chat sessions, JWT refresh tokens
- **Embedding Cache**: multilingual-e5-large model loaded in Celery worker (1.3GB)
- **Prompt Optimization**: Gemini Flash context caching for up to 80% cost reduction on repeated queries
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
- **Performance Tracking**: Search latency (<3s Gemini, <8s Ollama), processing throughput (>50 docs/hour)
- **Error Monitoring**: 5xx error rate alerts (>5%), processing queue depth (>100)
- **Cost Analytics**: Daily Gemini API cost tracking with cache hit-rate metrics, budget caps
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
