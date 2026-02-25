# SOWKNOW Repository Structure Audit Report
**Session ID:** AUDIT-SOWKNOW-001
**Date:** 2026-02-21
**Auditor:** Senior App Development Auditor

---

## Executive Summary

The SOWKNOW repository demonstrates a mature, well-architected codebase with strong configuration management (9/10) and documentation (8.4/10). The core architecture aligns with CLAUDE.md specifications for a privacy-first AI knowledge vault. Primary concerns: directory structure inconsistencies (6.5/10), misplaced telegram-bot location, and a P0 gap where Gemini Flash service is specified but MiniMax is implemented instead.

---

## Summary Table

| Component | Status | Score | Notes |
|-----------|--------|-------|-------|
| Frontend Structure | ✅ | 9/10 | Next.js 14 App Router, proper i18n |
| Backend Structure | ✅ | 9/10 | Feature-based, 25+ services |
| Telegram Bot Location | ⚠️ | - | Expected /telegram-bot, found /backend/telegram_bot |
| Docker Configuration | ✅ | 9/10 | 5 compose variants, 7 Dockerfiles |
| Environment Files | ✅ | 9/10 | Comprehensive .env.example |
| Database Migrations | ✅ | 8/10 | 3 Alembic migrations |
| Documentation | ✅ | 8.4/10 | README 325 lines, 28 additional docs |
| Gemini Flash Service | ❌ | - | P0: Specified in CLAUDE.md, not implemented |
| LLM Routing Service | ⚠️ | - | P1: Logic scattered, not centralized |
| Frontend Tests | ⚠️ | 3/10 | Only spec exists, no actual tests |
| Empty Directories | ⚠️ | - | /tests, /docker empty |

---

## Critical Findings (Must Fix)

| # | Issue | Priority | Location | Recommendation |
|---|-------|----------|----------|----------------|
| 1 | **Gemini Flash service missing** | P0 | N/A | Either add gemini_service.py OR update CLAUDE.md to reflect MiniMax usage |
| 2 | **Telegram-bot misplaced** | P1 | /backend/telegram_bot | Move to /telegram-bot per project spec |
| 3 | **No centralized LLM routing** | P1 | Scattered | Create llm_router_service.py |

---

## Detailed Agent Reports

### Agent-DIR: Directory Structure Analysis
**Rating: 6.5/10**

#### Top-Level Directories Assessment

| Directory Path | Exists? | Purpose | Concern Separation |
|----------------|---------|---------|-------------------|
| `/frontend` | Yes | Next.js 14 PWA frontend with TypeScript, Tailwind, i18n | Good |
| `/backend` | Yes | FastAPI backend with API, models, services, tasks, Celery | Good |
| `/telegram-bot` | No | Expected top-level; actual location: `/backend/telegram_bot` | Poor |
| `/tests` | Yes (empty) | Root-level tests directory - EMPTY | Poor |
| `/backend/tests` | Yes | Actual backend unit/integration tests | Good |
| `/docs` | Yes | Project documentation, reports, guides | Good |
| `/scripts` | Yes | Deployment, monitoring, SSL, backup scripts | Good |
| `/docker` | Yes (empty) | Docker configs - EMPTY (compose files at root) | Poor |
| `/data` | Yes | Data storage: backups, confidential, public buckets | Good |
| `/logs` | Yes | Application logs partitioned by service | Good |
| `/monitoring` | Yes | Prometheus configuration | Good |
| `/nginx` | Yes | Nginx reverse proxy configuration | Good |
| `/sync-agent` | Yes | External synchronization agent module | Fair |
| `/.github` | Yes | GitHub Actions CI/CD workflows | Good |
| `/.pytest_cache` | Yes | Python test cache (should be gitignored) | Fair |
| `/.ruff_cache` | Yes | Ruff linter cache (should be gitignored) | Fair |

#### Structural Anti-Patterns Found

1. **Misplaced telegram-bot**: Expected at `/telegram-bot`, found at `/backend/telegram_bot` - inconsistent with project spec
2. **Empty `/tests` directory**: Root-level tests folder is empty; actual tests are in `/backend/tests`
3. **Empty `/docker` directory**: Docker directory exists but contains nothing; all compose files are at root level
4. **Root directory clutter**: 20+ markdown files at root (Agent reports, deployment guides, etc.) that belong in `/docs`
5. **Artifact file at root**: `=2.7.0` file (likely from pip install typo with `==` syntax)
6. **Duplicate deployment scripts**: `deploy-production.sh` exists at both `/` and `/scripts/`
7. **Test DBs in code directory**: `test.db`, `test_security.db` in `/backend` instead of temp/test location
8. **Cache directories in repo**: `.pytest_cache`, `.ruff_cache` present (should be in `.gitignore`)
9. **Nested tests confusion**: Both `/tests` (empty) and `/frontend/tests` exist alongside `/backend/tests`

#### Positive Patterns

- Clean backend architecture with `/api`, `/models`, `/schemas`, `/services`, `/tasks` separation
- Frontend follows Next.js 14 App Router conventions (`/app`, `/components`, `/lib`)
- Data directory properly partitioned by access level (public/confidential)
- Scripts consolidated with clear naming conventions
- CI/CD via `.github/workflows`

---

### Agent-CONFIG: Configuration Files Audit
**Rating: 9/10**

#### Docker Compose

| File | Status | Services |
|------|--------|----------|
| docker-compose.yml | ✅ | postgres, redis, backend, celery-worker, celery-beat, frontend, nginx, telegram-bot, prometheus |
| docker-compose.production.yml | ✅ | postgres, redis, backend, celery-worker, celery-beat, frontend, nginx, certbot, telegram-bot |
| docker-compose.simple.yml | ✅ | Simplified deployment |
| docker-compose.dev.yml | ✅ | Development environment |
| docker-compose.prebuilt.yml | ✅ | Pre-built image deployment |

#### Environment Files

| File | Status | Variables |
|------|--------|-----------|
| .env.example (root) | ✅ | 17+ variables (SECURITY, DATABASE, APIs, TELEGRAM, ADMIN, APP) |
| backend/.env.example | ✅ | 145 lines with extended config (DATABASE_URL, REDIS_URL, PRIVACY_THRESHOLD, etc.) |
| .env | ✅ | Exists |
| frontend/.env.production | ✅ | Production frontend config |
| backend/.env.production | ✅ | Production backend config |

#### Dockerfiles (7 total)

| Path | Purpose |
|------|---------|
| backend/Dockerfile | Production backend |
| backend/Dockerfile.dev | Development backend |
| backend/Dockerfile.minimal | Minimal backend build |
| backend/Dockerfile.worker | Celery worker |
| backend/Dockerfile.telegram | Telegram bot |
| frontend/Dockerfile | Production frontend |
| frontend/Dockerfile.dev | Development frontend |

#### Dependencies

| File | Purpose |
|------|---------|
| backend/requirements.txt | Main backend dependencies |
| backend/requirements-minimal.txt | Minimal dependencies |
| backend/requirements-telegram.txt | Telegram bot dependencies |
| sync-agent/requirements.txt | Sync agent dependencies |
| frontend/package.json | Next.js frontend dependencies |

---

### Agent-COMP: Missing Components Analysis

#### Critical Missing Items (P0-P1)

| Item | Priority | Description |
|------|----------|-------------|
| Gemini Flash Service | P0 | CLAUDE.md specifies Gemini Flash as primary LLM for public documents, but no `gemini_service.py` exists. System uses MiniMax instead (via OpenRouter/direct API). |
| Centralized LLM Routing Service | P1 | CLAUDE.md specifies "Smart routing based on document context" but no centralized routing service exists. Routing logic is scattered across `chat_service.py` and individual agent files. |

#### Non-Critical Missing Items (P3-P4)

| Item | Priority | Description |
|------|----------|-------------|
| Frontend Test Files | P3 | Only `frontend/tests/TEST_SPECIFICATION.md` exists - no actual Jest/React test files despite Jest being configured. |
| Frontend styles/ Directory | P4 | Empty directory at `frontend/styles/` with no CSS modules or global styles (only `app/globals.css` exists). |

#### Verified Present Components (50+)

| Component | Location |
|-----------|----------|
| **Frontend: Next.js 14** | `/frontend/app/[locale]/` with proper routing |
| **Frontend: TypeScript** | `/frontend/tsconfig.json` |
| **Frontend: Tailwind CSS** | `/frontend/tailwind.config.js` |
| **Frontend: Zustand** | `/frontend/lib/store.ts` |
| **Frontend: next-intl** | `/frontend/app/messages/`, `/frontend/i18n/` |
| **Frontend: API Client** | `/frontend/lib/api.ts` |
| **Backend: FastAPI** | `/backend/app/main.py`, `/backend/app/main_minimal.py` |
| **Backend: API Routes** | `/backend/app/api/` (auth, admin, search, documents, collections, chat, etc.) |
| **Backend: Models** | `/backend/app/models/` (user, document, chat, collection, processing, knowledge_graph) |
| **Backend: Schemas** | `/backend/app/schemas/` (user, document, chat, collection, search, token) |
| **Backend: Services** | `/backend/app/services/` (25+ services including embedding, ollama, minimax, openrouter, chat, search) |
| **Backend: Multi-Agent System** | `/backend/app/services/agents/` (orchestrator, answer, clarification, researcher, verification) |
| **Database: Alembic** | `/backend/alembic/versions/` (001_initial_schema, 002_add_collections, 003_add_knowledge_graph) |
| **Database: PostgreSQL/pgvector** | Configured in docker-compose.yml with `pgvector/pgvector:pg16` |
| **Queue: Celery App** | `/backend/app/celery_app.py` |
| **Queue: Celery Tasks** | `/backend/app/tasks/` (document_tasks, anomaly_tasks) |
| **Queue: Redis** | Configured in docker-compose.yml |
| **AI: Embedding Service** | `/backend/app/services/embedding_service.py` |
| **AI: Ollama Service** | `/backend/app/services/ollama_service.py` |
| **AI: MiniMax Service** | `/backend/app/services/minimax_service.py` |
| **AI: OpenRouter Service** | `/backend/app/services/openrouter_service.py` |
| **AI: PII Detection** | `/backend/app/services/pii_detection_service.py` |
| **Infrastructure: Docker** | 8 containers in `docker-compose.yml` |
| **Infrastructure: Nginx** | `/nginx/nginx.conf`, `/nginx/nginx-http-only.conf` |
| **Backend Tests** | `/backend/tests/` with unit, integration, security, performance, e2e subdirectories |

---

### Agent-DOCS: Documentation Assessment
**Rating: 8.4/10**

#### Documentation Scorecard

| Category | Score | Justification |
|----------|-------|---------------|
| README.md | 9/10 | Comprehensive 325-line README with architecture overview, feature list, project structure, deployment steps (quick + manual), testing, performance metrics, security features, and monitoring. Minor gap: no troubleshooting section. |
| API Documentation | 8/10 | Well-structured API.md (374 lines) with endpoint examples, request/response formats, rate limits, error codes, and streaming docs. FastAPI configured with Swagger UI, ReDoc, and OpenAPI JSON. Gap: some endpoints lack response schema definitions. |
| Migration Files | 8/10 | 3 migration files with proper docstrings, revision IDs, and dates. Migrations cover core schema, collections, and knowledge graph. Gap: only 3 migrations for a Phase 3 system suggests possible schema consolidation or missing incremental migrations. |
| Inline Docs | 8/10 | Strong module-level docstrings (auth.py has security-critical notes), service classes have docstrings with Args documentation. Code is readable with comments. Gap: inconsistent docstring coverage across all services. |
| Additional Docs | 9/10 | Excellent - 28 documentation files including DEPLOYMENT.md, USER_GUIDE.md, UAT_CHECKLIST.md, audit reports, security fixes, compliance matrices, LLM routing flowchart, and phase-specific docs. |
| **OVERALL** | **8.4/10** | Strong documentation foundation with comprehensive README, good API docs, and extensive additional documentation. Minor improvements needed in inline docstring consistency and OpenAPI response schemas. |

#### Files Reviewed

**Core Documentation:**
- `/root/development/src/active/sowknow4/README.md` (325 lines)
- `/root/development/src/active/sowknow4/docs/API.md` (374 lines)
- `/root/development/src/active/sowknow4/docs/DEPLOYMENT.md` (270 lines)
- `/root/development/src/active/sowknow4/docs/USER_GUIDE.md`
- `/root/development/src/active/sowknow4/docs/UAT_CHECKLIST.md`

**Migration Files (3):**
- `/backend/alembic/versions/001_initial_schema.py`
- `/backend/alembic/versions/002_add_collections.py`
- `/backend/alembic/versions/003_add_knowledge_graph.py`

**Additional Docs Folder (28 files):**
- FINAL_COMMERCIAL_READINESS_REPORT.md
- ROLLBACK_PLAN.md
- TROUBLESHOOTING_GUIDE.md
- LLM_ROUTING_FLOWCHART.md
- SECURITY_FIXES_REPORT.md
- AUTH_COMPLIANCE_MATRIX.md
- PHASE2/3 audit reports
- Test execution summaries

#### Documentation Gaps

1. **No TROUBLESHOOTING.md in root** - File exists in docs/ but not prominently linked in README
2. **OpenAPI response schemas** - Some endpoints lack detailed response models in FastAPI
3. **Docstring consistency** - Some services have minimal docstrings compared to auth.py
4. **Migration coverage** - Only 3 migrations for a 3-phase system; may indicate schema changes were squashed
5. **Developer onboarding** - No CONTRIBUTING.md or DEVELOPMENT.md for new contributors
6. **API versioning docs** - No explicit versioning strategy documented

---

## Recommendations (Prioritized)

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| P0 | Align CLAUDE.md with actual LLM implementation (Gemini vs MiniMax) | Low | High - Documentation accuracy |
| P1 | Move telegram-bot to /telegram-bot directory | Low | Medium - Structural consistency |
| P1 | Create centralized llm_router_service.py | Medium | High - Maintainability |
| P2 | Clean empty directories (/tests, /docker) | Low | Low - Cleanliness |
| P2 | Move root markdown files to /docs | Low | Medium - Organization |
| P2 | Remove artifact file (=2.7.0) from root | Low | Low - Cleanliness |
| P2 | Add .pytest_cache, .ruff_cache to .gitignore | Low | Low - Repo hygiene |
| P3 | Add Jest/React frontend tests | Medium | High - Quality assurance |
| P3 | Add CONTRIBUTING.md | Low | Medium - Onboarding |
| P4 | Remove empty styles/ directory or add styles | Low | Low - Cleanliness |

---

## Overall Audit Rating: 7.8/10

**Verdict:** Production-ready with minor structural cleanup needed.

**Strengths:**
- Excellent configuration management
- Strong documentation foundation
- Proper frontend/backend separation
- Comprehensive Docker setup
- Well-organized backend services

**Weaknesses:**
- Documentation/spec misalignment (Gemini vs MiniMax)
- Directory structure inconsistencies
- Scattered LLM routing logic
- Empty/unused directories
- Missing frontend tests

---

## Audit Metadata

| Field | Value |
|-------|-------|
| Session ID | AUDIT-SOWKNOW-001 |
| Date | 2026-02-21 |
| Agents Deployed | 4 (DIR, CONFIG, COMP, DOCS) |
| Execution Mode | Parallel |
| Total Files Analyzed | 100+ |
| Total Directories Analyzed | 50+ |
| Duration | ~5 minutes |
