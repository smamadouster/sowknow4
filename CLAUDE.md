# OpenWolf

@.wolf/OPENWOLF.md

This project uses OpenWolf for context management. Read and follow .wolf/OPENWOLF.md every session. Check .wolf/cerebrum.md before generating code. Check .wolf/anatomy.md before reading files.

# SOWKNOW — Multi-Generational Legacy Knowledge System

## AGENT LEARNINGS (MANDATORY)
- **Before ANY task**, read `AGENT_LEARNINGS.md`. After mistakes, append to it.

## CRITICAL RULES
- **PRIVACY FIRST**: Zero PII to cloud APIs (MiniMax/OpenRouter/PaddleOCR)
- **CONFIDENTIAL ROUTING**: Metadata-only stripping (PRD §1.3) for confidential docs — LLM never sees confidential chunk text. (Ollama local routing was REMOVED 2026-09-05.)
- **VPS CONSTRAINTS**: Total container memory <= 6.4GB (shared VPS)
- **TRI-LLM → OpenRouter tiers (2026-09-05)**: deepseek-v4-flash (simple/standard), deepseek-v4-pro (complex), qwen3.8-max model-level fallback per tier — all via openrouter_service; MiniMax optional. Ollama is UNINSTALLED.
- **RBAC**: Admin (full) | Super User (view all, no edit/delete/manage) | User (public only, confidential invisible)
- **NO GPU**: PaddleOCR + Tesseract fallback, multilingual-e5-large on CPU
- **FRENCH DEFAULT**: FR with full EN support (next-intl)
- **VERIFY BEFORE COMMIT**: `.githooks/pre-commit` runs `scripts/verify_tree.sh --staged` (py_compile + tsc + JSON). For sweeping changes run `scripts/verify_tree.sh --all --imports` first. No pattern-based bulk edits (see AGENT_LEARNINGS.md 2026-09-05).

## CONTAINER & DEVOPS — NON-NEGOTIABLE

> Violating these caused 77GB bloat, 3000+ healthcheck failures, and exposed databases.

- **Deploy surface**: `docker-compose.production.yml` (container names use the `sowknow-` prefix) via `scripts/deploy.sh` — the ONLY sanctioned deploy. `docker-compose.yml` carries legacy `sowknow4-*` names: NEVER run it for container ops on this host (second frontend → port 3000 collision, 2026-09-05).
- **Where does prod run?** Ask the containers, not docs:
  `docker inspect <c> --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'`
  → `/home/development/src/active/sowknow4` (this repo). `/var/docker/sowknow4` is retired.
- **Ports**: NEVER expose internal services (postgres/redis/vault/nats). Only backend (8001:8000) and frontend (3000:3000).
- **Healthchecks**: Every service MUST have a working healthcheck. Celery: use `pgrep`. Backend: match actual endpoint path. Verify after ANY compose change.
- **Images**: Always `python:3.11-slim`. Prune after builds. Multi-stage or slim bases only.
- **Bind mount**: `./backend:/app` overrides image files at runtime. The code in `./backend/` is what runs.
- **nftables**: Docker 29 leaves stale PREROUTING rules on network recreate/reboot — they silently drop all inter-container traffic. A systemd service flushes `ip raw PREROUTING` after every Docker start. NEVER remove this service. Manual fix: `sudo nft flush chain ip raw PREROUTING`.

## STACK
- **Core**: FastAPI + Next.js 14 PWA + PostgreSQL/pgvector + Celery + Redis
- **Frontend**: TypeScript, Tailwind CSS, Zustand, httpOnly JWT cookies
- **Backend**: SQLAlchemy 2.0, Alembic, async endpoints, feature-based structure
- **OCR**: PaddleOCR (Base/Large/Gundam modes) + Tesseract fallback, all local
- **Pipeline**: Celery + Redis async (OCR, embeddings, indexing), 50+ docs/hour
- **Bilingual**: FR/EN via next-intl, AI responds in query language

## DEPLOYMENT
- **Production IS this repo** (`/home/development/src/active/sowknow4`, branch checked out here). Deploy ONLY via `scripts/deploy.sh` (builds ALL image tags, `--no-deps`, smoke-tests). Cold start: `docker compose -f docker-compose.production.yml up -d --no-deps postgres nats redis`, wait for pg_isready, then deploy.sh.
- **Stale-doc warning**: older guides referencing `/var/docker/sowknow4` as production are OUTDATED (directory retired; AGENTS.md is authoritative when docs disagree).
- **Proxy**: Nginx reverse proxy, TLS via Let's Encrypt
- **Backups**: Daily PostgreSQL dumps, weekly encrypted offsite, 7-4-3 retention
- **Admin routes**: In main_minimal.py for security isolation

## SECURITY
- **Auth**: JWT + bcrypt, refresh tokens, httpOnly secure cookies
- **RBAC**: 3-tier with strict bucket isolation. Admin: full access + user mgmt. Super User: view-only confidential. User: public only.
- **Network**: Nginx rate limiting (100/min), CORS, internal Docker network
- **Encryption**: At-rest Fernet encryption for confidential docs, zero PII to cloud
- **Audit**: All confidential access logged with timestamp + user ID
- **Admin API**: `POST /api/v1/admin/users/{id}/reset-password` (admin only, returns temp password)

## TESTING — Collection Orchestrator
- **/test collections**: validate the Collection Requests module (nav → Collection Requests, or `POST /api/v1/collection-requests`) with the reference query:
  **"me rassembler tous les fichiers au sujet de MATFORCE MALI"**
  Expected: clarification → confirmation → grounded deliverable (computed insights only, annotated item list, disclosures). Live scenario harness: `scripts/collection_scenario_check.py`.
- Build stamp: current deployed build (git short hash + UTC time) is shown above the logout button; set at build time by `scripts/deploy.sh` via `NEXT_PUBLIC_BUILD_STAMP`.
