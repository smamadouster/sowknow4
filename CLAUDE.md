# OpenWolf

@.wolf/OPENWOLF.md

This project uses OpenWolf for context management. Read and follow .wolf/OPENWOLF.md every session. Check .wolf/cerebrum.md before generating code. Check .wolf/anatomy.md before reading files.

# SOWKNOW — Multi-Generational Legacy Knowledge System

## AGENT LEARNINGS (MANDATORY)
- **Before ANY task**, read `AGENT_LEARNINGS.md`. After mistakes, append to it.

## CRITICAL RULES
- **PRIVACY FIRST**: Zero PII to cloud APIs (MiniMax/OpenRouter/PaddleOCR)
- **CONFIDENTIAL ROUTING**: Auto-switch to Ollama (mistral:7b local) for confidential docs
- **VPS CONSTRAINTS**: Total container memory <= 6.4GB (shared VPS)
- **TRI-LLM**: MiniMax M2.7 (search/articles), Mistral Small 2603 via OpenRouter (chat/collections/telegram), Ollama mistral:7b (confidential)
- **RBAC**: Admin (full) | Super User (view all, no edit/delete/manage) | User (public only, confidential invisible)
- **NO GPU**: PaddleOCR + Tesseract fallback, multilingual-e5-large on CPU
- **FRENCH DEFAULT**: FR with full EN support (next-intl)

## CONTAINER & DEVOPS — NON-NEGOTIABLE

> Violating these caused 77GB bloat, 3000+ healthcheck failures, and exposed databases.

- **ONE compose file**: `docker-compose.yml` = production truth. `docker-compose.dev.yml` for dev. NO other variants.
- **Naming**: ALL containers use `sowknow4-` prefix (e.g., `sowknow4-backend`)
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
- **Production**: /var/docker/sowknow4, 8 Docker containers, sowknow-net network
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
