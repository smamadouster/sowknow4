# SOWKNOW Documentation

**Complete documentation for the SOWKNOW Multi-Generational Legacy Knowledge System**

---

## Table of Contents

- [Quick Start](#quick-start)
- [Core Documentation](#core-documentation)
- [Guides](#guides)
- [References](#references)

---

## Quick Start

### New to SOWKNOW?

1. **Understand the System**: Read [ARCHITECTURE.md](ARCHITECTURE.md) (15 min read)
2. **Deploy Locally**: Follow [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - Local Development section (20 min)
3. **Run Tests**: Execute test suite with [TESTING.md](TESTING.md) (10 min)
4. **Explore API**: Use [API_REFERENCE.md](API_REFERENCE.md) to interact with endpoints (30 min)

---

## Core Documentation

### Architecture & Design

| Document | Purpose | Audience | Read Time |
|----------|---------|----------|-----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, data flows, tri-LLM routing, RBAC, security | Architects, Senior Devs | 30 min |
| [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) | Setup, deployment, troubleshooting, maintenance | DevOps, Operations | 45 min |
| [API_REFERENCE.md](API_REFERENCE.md) | Complete API endpoint documentation with examples | Developers, API users | 60 min |
| [TESTING.md](TESTING.md) | Testing strategy, setup, writing tests, CI/CD | QA, Developers | 40 min |

### Feature Documentation

| Document | Purpose | Audience |
|----------|---------|----------|
| [../CLAUDE.md](../CLAUDE.md) | Project rules, constraints, configuration | All team members |
| [../MONITORING.md](../MONITORING.md) | Health checks, metrics, alerting, cost tracking | Operations, DevOps |
| [../SECURITY_FIX_SUMMARY.md](../SECURITY_FIX_SUMMARY.md) | Security implementations, audit logs, RBAC | Security, Ops |

---

## Guides

### For Developers

#### Setup & Onboarding

1. **Clone & Setup**
   ```bash
   git clone https://github.com/anomalyco/sowknow4.git
   cd sowknow4
   cp .env.example .env
   # Edit .env with your values
   ```

2. **Start Services** (from [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#local-development))
   ```bash
   docker-compose up -d postgres redis backend frontend celery-worker celery-beat
   ```

3. **Run Migrations**
   ```bash
   docker-compose exec backend alembic upgrade head
   ```

4. **Verify Health**
   ```bash
   curl http://localhost:8001/health
   ```

#### Common Tasks

- **Make API calls**: See [API_REFERENCE.md](API_REFERENCE.md#curl-examples)
- **Write tests**: See [TESTING.md](TESTING.md#writing-tests)
- **Debug issues**: See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#troubleshooting)
- **Understand architecture**: See [ARCHITECTURE.md](ARCHITECTURE.md)
- **Check performance**: See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#performance-tuning)

### For DevOps & Operations

1. **Initial Setup**: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#prerequisites)
2. **Deploy to Production**: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#production-deployment)
3. **Monitor System**: [../MONITORING.md](../MONITORING.md)
4. **Backup & Recovery**: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#backup--recovery)
5. **Troubleshoot**: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#troubleshooting)

### For QA & Testing

1. **Test Environment**: [TESTING.md](TESTING.md#test-environment-setup)
2. **Run Tests**: [TESTING.md](TESTING.md#running-tests)
3. **Write Tests**: [TESTING.md](TESTING.md#writing-tests)
4. **CI/CD**: [TESTING.md](TESTING.md#cicd-integration)
5. **Coverage**: [TESTING.md](TESTING.md#test-coverage)

### For API Integration

1. **Authentication**: [API_REFERENCE.md](API_REFERENCE.md#authentication)
2. **Documents**: [API_REFERENCE.md](API_REFERENCE.md#documents-api)
3. **Search**: [API_REFERENCE.md](API_REFERENCE.md#search--rag)
4. **Collections**: [API_REFERENCE.md](API_REFERENCE.md#collections-api)
5. **Error Handling**: [API_REFERENCE.md](API_REFERENCE.md#error-handling)

---

## References

### System Architecture

```
Frontend (Next.js 14)
    ↓
Nginx/Caddy (Reverse Proxy)
    ↓
FastAPI Backend (8000)
    ↓
├─ PostgreSQL/pgvector (5432)
├─ Redis (6379)
├─ Celery Workers (async tasks)
└─ LLM Providers:
   ├─ Kimi/Moonshot (chat, search)
   ├─ MiniMax/OpenRouter (public docs)
   └─ Ollama (confidential docs)
```

### Key Statistics

| Metric | Value |
|--------|-------|
| Version | 3.0.0 (Phase 3) |
| Status | Production Ready |
| Services | 8 Docker containers |
| Memory Budget | 6.4GB (VPS shared) |
| Search Response | <3s (Kimi), <8s (Ollama) |
| Document Processing | >50 docs/hour |
| API Uptime | >99.5% |
| Cache Hit Rate | >50% |

### Technology Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14, TypeScript, Tailwind CSS, Zustand |
| Backend | FastAPI, Python 3.11+, SQLAlchemy 2.0 |
| Database | PostgreSQL 16, pgvector, Redis 7 |
| Task Queue | Celery, Redis broker |
| Embeddings | multilingual-e5-large (local) |
| OCR | PaddleOCR (primary), Tesseract (fallback) |
| Containerization | Docker, Docker Compose |
| LLMs | Kimi, MiniMax, Ollama |

### Important Files

#### Backend Configuration
- `backend/app/main.py` - FastAPI application
- `backend/app/database.py` - Database connection
- `backend/requirements.txt` - Python dependencies
- `backend/.env.production` - Production secrets

#### Frontend Configuration
- `frontend/app/page.tsx` - Home page
- `frontend/next.config.js` - Build configuration
- `frontend/package.json` - Node dependencies

#### Deployment
- `docker-compose.yml` - Development setup
- `docker-compose.production.yml` - Production setup
- `nginx/nginx.conf` - Web server configuration

#### Database
- `backend/alembic/versions/` - Migration files
- `backend/app/models/` - SQLAlchemy models

### Important Environment Variables

```bash
# Database (CRITICAL)
DATABASE_USER=sowknow
DATABASE_NAME=sowknow
DATABASE_PASSWORD=<secure>

# Security (CRITICAL)
JWT_SECRET=<64+ chars>

# LLM APIs (REQUIRED)
KIMI_API_KEY=sk-<key>
MINIMAX_API_KEY=<key>

# App Settings
APP_ENV=production
DEBUG=False

# See DEPLOYMENT_GUIDE.md for full list
```

---

## Common Tasks

### Deploy to Production

```bash
# 1. Configure .env
nano .env

# 2. Build images
docker-compose -f docker-compose.production.yml build

# 3. Start services
docker-compose -f docker-compose.production.yml up -d

# 4. Run migrations
docker-compose -f docker-compose.production.yml exec backend alembic upgrade head

# See: DEPLOYMENT_GUIDE.md#production-deployment
```

### Run Test Suite

```bash
# All tests
./scripts/run-tests.sh

# Specific category
pytest backend/tests/unit -v
pytest backend/tests/integration -v
pytest backend/tests/e2e -v

# With coverage
pytest --cov=app backend/tests

# See: TESTING.md#running-tests
```

### Check System Health

```bash
# Basic health
curl http://localhost:8001/health

# Detailed health
curl http://localhost:8001/api/v1/health/detailed

# System stats
curl http://localhost:8001/api/v1/monitoring/system

# See: DEPLOYMENT_GUIDE.md#health-checks
```

### Search Documents

```bash
# Via API
curl -X POST http://localhost:8001/api/v1/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "family history", "limit": 10}'

# See: API_REFERENCE.md#search--rag
```

### Upload Document

```bash
curl -X POST http://localhost:8001/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@document.pdf" \
  -F "is_confidential=false"

# See: API_REFERENCE.md#documents-api
```

---

## Documentation Map

```
docs/
├── README.md                    (This file - overview & links)
├── DEPLOYMENT_GUIDE.md          (Setup, deploy, troubleshoot)
├── ARCHITECTURE.md              (System design, data flows)
├── API_REFERENCE.md             (Complete API documentation)
├── TESTING.md                   (Test strategy & how-to)
│
├── ../CLAUDE.md                 (Project config & rules)
├── ../MONITORING.md             (Health checks, metrics)
├── ../SECURITY_FIX_SUMMARY.md   (Security audit & logging)
│
├── ../docker-compose.yml        (Dev environment config)
├── ../docker-compose.production.yml
│
└── ../backend/
    ├── tests/                   (Test files, examples)
    └── app/
        ├── main.py              (FastAPI app)
        ├── models/              (Database models)
        ├── services/            (Business logic)
        └── api/                 (Endpoints)
```

---

## Getting Help

### Documentation

- **Architecture Questions**: See [ARCHITECTURE.md](ARCHITECTURE.md)
- **Deployment Issues**: See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#troubleshooting)
- **API Questions**: See [API_REFERENCE.md](API_REFERENCE.md)
- **Testing Help**: See [TESTING.md](TESTING.md#troubleshooting)

### Logs & Debugging

```bash
# View logs
docker-compose logs -f backend

# Check specific service
docker-compose logs -f celery-worker

# Save to file
docker-compose logs > logs_$(date +%Y%m%d).txt
```

### Check Health

```bash
# Services running?
docker-compose ps

# Database connected?
docker-compose exec postgres pg_isready -U sowknow

# Redis connected?
docker-compose exec redis redis-cli ping

# API responding?
curl -s http://localhost:8001/health | jq .
```

### Performance Issues

- See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#performance-tuning)
- Check [ARCHITECTURE.md](ARCHITECTURE.md#scalability--performance)

---

## Updates & Maintenance

See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#updates--maintenance) for:
- Code updates
- Database migrations
- Dependency updates
- OS/Docker updates

---

## Support & Contact

- **Email**: api-support@gollamtech.com
- **Issues**: https://github.com/anomalyco/sowknow4/issues
- **Docs**: https://sowknow.gollamtech.com/api/docs

---

**SOWKNOW Documentation**
*Version 3.0.0 (Phase 3) - Last Updated: February 24, 2026*
