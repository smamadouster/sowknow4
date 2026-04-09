# Guardian v2.0 — Autonomous Observability & Self-Healing Agent

**Date**: 2026-04-09
**Status**: Approved
**Replaces**: Guardian HC v1.3.0 (reactive container health checker)

## Vision

Transform Guardian from a reactive container health poller into a full autonomous observability agent that monitors functional modules, detects silent failures, predicts incidents from trends, learns from history, and auto-heals aggressively without user intervention.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Architecture | Modular agent with plugin system | Clean separation, testable, ship incrementally |
| Healing posture | Aggressive | Auto-heal everything possible, alert only for code-level bugs |
| Metrics storage | PostgreSQL + SQLite fallback buffer | Rich querying; buffer locally if postgres is down |
| Dashboard | Port 9090, internal access only | No subdomain needed for SOWKNOW scale |
| Telegram | Commands + daily brief at 06:00 | Primary alert channel |
| Resource cap | <256MB RAM | Lean; 48h raw metrics, 14d hourly aggregates |

## Agent Architecture

Guardian v2 runs as a single Python process with 6 named agents, each backed by a plugin:

| Agent | Role | Plugin |
|---|---|---|
| **Watcher** | Monitors all probes, detects anomalies and silent failures | `probes` + `sentinel` |
| **Healer** | Executes auto-heal actions across all modules | All plugins delegate heal execution through Healer agent; owns restart tracker, cooldowns, and heal verification |
| **Debugger** | Root-cause analysis, incident correlation | `correlator` (existing, enhanced) |
| **Learner** | Builds and refines patterns from incidents and metrics | `memory` |
| **Reporter** | Daily briefs, Telegram commands, dashboard | `reporter` |
| **Archivist** | Metrics collection, retention, cleanup | `trends` |

### Plugin Interface

Every plugin implements:

```python
class GuardianPlugin:
    name: str
    enabled: bool

    async def check(self, context: CheckContext) -> list[CheckResult]
    async def heal(self, result: CheckResult) -> HealResult | None
    async def analyze(self, context: AnalysisContext) -> list[Insight]
```

- `check()` — runs during patrol cycles, returns pass/fail/warning results
- `heal()` — called automatically when check fails, returns what it did
- `analyze()` — runs on deep patrol cycle, produces trend insights or predictions

Plugins are loaded from config and registered with the core engine. Existing checkers (container, disk, memory, SSL, network, etc.) become the **infrastructure plugin** — same code wrapped in the plugin interface. Zero behavior regression.

### Patrol Integration

| Patrol | Interval | Plugins called |
|---|---|---|
| Critical | 2min | infrastructure, probes (JWT, Redis, Celery) |
| Standard | 10min | infrastructure, probes (all), sentinel |
| Deep | 1hr | all + analyze() on trends and memory |

## Module-Level Monitoring

Guardian monitors 8 functional modules, not just containers:

| Module | Containers involved | Key probes |
|---|---|---|
| **Authentication Service** | backend | JWT issuance/verification, login flow, refresh tokens |
| **Document Pipeline** | celery-heavy, celery-light, backend | OCR throughput, embedding completion rate, stuck docs |
| **Search & Retrieval** | backend, postgres | Query latency, embedding quality, pgvector health |
| **Collections Engine** | celery-collections, backend | Smart collections pipeline throughput |
| **Chat / LLM Service** | backend | OpenRouter/MiniMax connectivity, response time |
| **Telegram Bot** | telegram-bot | Bot responsiveness, command processing |
| **Storage Layer** | postgres, redis, vault | Connection pools, memory, locks, unsealed status |
| **Infrastructure** | all | Docker network, Nginx upstream, disk, CPU/memory, SSL |

## Pillar 1: Deep Application Probes (Watcher)

| Probe | What it tests | Method | Heal action |
|---|---|---|---|
| **JWT validity** | Auth tokens can be issued and verified | `GET /api/v1/health/auth-check` (new endpoint) — generate test token, verify signature + expiry | Restart backend; if key mismatch, alert as code-level bug |
| **Redis deep** | Responsive + memory healthy + eviction working | `PING`, `INFO memory`, `DBSIZE`, check `used_memory_rss` vs `maxmemory` | `MEMORY PURGE`, flush expired keys, restart Redis if unresponsive |
| **PostgreSQL deep** | Connections available, no long-running locks | `pg_stat_activity` (active vs max), `pg_locks` (blocked >30s), table bloat | Kill idle-in-transaction >5min, `pg_terminate_backend` for stuck connections |
| **Nginx upstream** | Reverse proxy routing correctly | HTTP probe through Nginx, check response headers | `nginx -s reload`; if config broken, alert for manual fix |
| **Auth flow** | Full login cycle works end-to-end | POST `/api/v1/auth/login` with `guardian-probe` service account, verify JWT + refresh | Restart backend; if persistent, flag as code-level auth bug |
| **Celery task completion** | Workers completing tasks, not just consuming | Submit `guardian.ping` probe task, verify completion within 30s | Restart stuck worker, purge zombie tasks |
| **Embedding pipeline** | Documents flowing through pipeline | Check `pipeline_status` for docs stuck in `processing` >10min | Restart celery-heavy, re-queue stuck documents |

**Service account**: `guardian-probe` user in database with read-only access + auth test capability. Created once during setup.

**New backend endpoint**: `GET /api/v1/health/deep` returns:
```json
{
  "db_connected": true,
  "last_write": "2026-04-09T...",
  "active_connections": 12,
  "celery_ping": true,
  "jwt_valid": true
}
```

## Pillar 2: Silent Failure Detection (Sentinel)

| Silent failure | Detection method | Threshold | Heal action |
|---|---|---|---|
| **Celery consuming but not completing** | Compare `tasks_received` vs `tasks_completed` over 10min window | Ratio <50% for 2 consecutive checks | Kill stuck workers, restart container, re-queue orphaned tasks |
| **Backend returning 200 but stale data** | `/api/v1/health/deep` `last_write` timestamp >5min stale while writes should be happening | Staleness >5min | Restart backend, check pg connection pool |
| **Queue growing but not draining** | Monitor Redis queue lengths over time — monotonically increasing for 3+ checks | Queue depth increasing for 30min | Restart celery workers, apply backpressure (pause ingestion) |
| **Embedding pipeline stuck** | Docs in `processing` state >10min, no new `completed` docs in 15min | 0 completions in 15min while queue >0 | Re-queue stuck docs, restart celery-heavy |
| **Frontend serving but API failing** | Probe frontend → backend API chain, frontend up but API bridge returning 502/503 | 3 consecutive proxy failures | Restart backend, reload Nginx |
| **Telegram bot unresponsive** | Send `/ping` via API, expect pong within 10s | No pong for 2 consecutive checks | Restart telegram-bot container |
| **Redis memory leak** | Track `used_memory_rss` trend, growing >5%/hr without corresponding `DBSIZE` growth | 5%/hr for 3+ hours | `MEMORY PURGE`, if persistent restart Redis |

## Pillar 3: Trend Analysis & Prediction (Archivist)

### Metrics Collected (every standard patrol — 10min)

| Metric | Source |
|---|---|
| Container memory/CPU | `docker stats` |
| Redis `used_memory_rss`, `connected_clients`, `DBSIZE` | `INFO` command |
| PostgreSQL `active_connections`, `idle_in_transaction`, `deadlocks` | `pg_stat_activity`, `pg_stat_database` |
| Celery queue depths (per queue) | Redis `LLEN` |
| Backend response time | Probe HTTP latency |
| Disk usage % | `df` |
| VPS load average, steal % | `/proc/loadavg`, `/proc/stat` |

### Database Schema

```sql
CREATE TABLE guardian_metrics (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    metric VARCHAR(64) NOT NULL,
    service VARCHAR(32),
    value FLOAT NOT NULL,
    tags JSONB DEFAULT '{}'
);
CREATE INDEX idx_metrics_ts_metric ON guardian_metrics (metric, ts DESC);

-- Hourly aggregates for 14-day retention
CREATE TABLE guardian_metrics_hourly (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    metric VARCHAR(64) NOT NULL,
    service VARCHAR(32),
    avg_value FLOAT NOT NULL,
    min_value FLOAT NOT NULL,
    max_value FLOAT NOT NULL,
    sample_count INT NOT NULL
);
CREATE INDEX idx_metrics_hourly_ts ON guardian_metrics_hourly (metric, ts DESC);
```

**Retention**: 48h raw data, 14d hourly aggregates. Nightly sweep aggregates and purges. Estimated footprint: ~5-10MB.

### Analysis (runs on deep patrol — 1hr)

- **Slope detection**: Linear regression on last 6h per metric. If slope predicts threshold breach within 4h, fire predictive alert.
- **Anomaly detection**: Current value vs 24h rolling mean ± 2 standard deviations. Flag outliers.
- **Capacity alerts**: Percentage-of-max warnings (e.g., "PostgreSQL connections at 80% of max_connections").

### Preventive Heals

When trend analysis predicts a breach, Guardian acts immediately:

- Redis memory trending high → `MEMORY PURGE` + expire stale keys
- Disk trending toward 85% → docker prune + log rotation early
- Queue depth climbing steadily → apply backpressure before explosion
- PostgreSQL connections climbing → kill idle-in-transaction sessions

### PostgreSQL Fallback Buffer

When postgres is unreachable, metrics buffer to a local SQLite file (max 10MB). Flushed to postgres on recovery. Prevents circular dependency.

## Pillar 4: Incident Learning (Learner)

### Pattern Storage

```sql
CREATE TABLE guardian_patterns (
    id SERIAL PRIMARY KEY,
    pattern_name VARCHAR(128) NOT NULL,
    trigger_conditions JSONB NOT NULL,
    predicted_outcome VARCHAR(256),
    recommended_action VARCHAR(256),
    confidence FLOAT DEFAULT 0.5,
    times_matched INT DEFAULT 0,
    times_correct INT DEFAULT 0,
    last_matched TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    active BOOLEAN DEFAULT true
);
```

### Learning Process

1. **Bootstrap**: On first run, read `.wolf/buglog.json` and `incidents.jsonl`. Extract cause-effect pairs and seed `guardian_patterns`.

2. **Runtime correlation**: After each incident is resolved, log the metrics from the 30min window before the incident. Over time, build a library of precursor patterns.

3. **Confidence scoring**: Each pattern starts at 0.5. Confirmed prediction → +0.1 (cap 0.95). False prediction → -0.05 (floor 0.1). Patterns below 0.2 auto-deactivated.

4. **Preventive action**: On each analysis cycle, check current metrics against active patterns. If a high-confidence pattern (>0.7) matches, execute recommended action before the incident and log: "PREVENTED: [pattern_name] — took [action] because [conditions matched]."

### Bootstrap Patterns from SOWKNOW History

| Pattern | Trigger | Preventive action |
|---|---|---|
| Docker nftables cascade | Network probe fails + restart count >3 in 10min | Flush iptables PREROUTING rules immediately |
| Redis OOM cascade | `redis.memory_rss` >85% + `celery.queue_depth` rising | `MEMORY PURGE` + pause celery ingestion |
| Backend restart loop | Restart tracker >2 + HTTP probe still failing | Stop restarting, alert as code-level bug, attach recent logs |
| Entity queue explosion | `celery.entity_queue` growing >50/min + light worker CPU >90% | Apply backpressure (queue cap), restart light worker |
| Redis password mismatch | `redis.auth_error` detected | Alert immediately — credential config issue |

### Threshold Recommendations

Like DroitAssist, when a pattern fires excessively (>100 times), Learner recommends raising the threshold in the daily brief:
> "redis.memory_rss: WARNING threshold fired 142 times this week — consider raising from 70% to 80%"

## Interfaces

### Web Dashboard (port 9090)

Server-rendered HTML + Tailwind CDN + server-side SVG charts. No JS framework. Zero extra dependencies.

| Page | Content |
|---|---|
| **Overview** | All 8 modules with status (green/yellow/red), last check time, uptime %. Agent health table. |
| **Probes** | Deep probe results per module with 24h sparklines |
| **Trends** | Metric charts (SVG), 24h/48h/14d views, threshold lines, predicted breach markers |
| **Incidents** | Timeline view, correlated groups, heal actions. Filter by module/severity/time |
| **Patterns** | Learned patterns table: name, confidence, times matched, active toggle. Manual pattern creation |
| **Logs** | Live tail of Guardian structured logs |

### Telegram Commands

| Command | Response |
|---|---|
| `/guardian` or `/gstatus` | Quick status: all modules + active incidents |
| `/gtrends` | Top 5 trending metrics with direction arrows and predicted breach time |
| `/gprobes` | Deep probe results summary |
| `/gpatterns` | Active patterns with confidence scores |
| `/gincidents [hours]` | Recent incidents, default last 6h |
| `/glearn` | New patterns, confidence changes |
| `/gheal <service>` | Force heal cycle on specific service |
| `/gsilence <minutes>` | Suppress alerts for N minutes (maintenance window) |

### Daily Intelligence Brief (06:00, Telegram + email)

Format aligned with DroitAssist HC:

```
🟢 Guardian SOWKNOW — Daily Intelligence Report
mercredi 9 avril 2026

System Status: HEALTHY
8 Healthy | 0 Degraded | 0 Unhealthy | 3 Auto-Heals

Module Status
Module                    Status    Checks (24h)
✅ Authentication Service  healthy   288
✅ Document Pipeline       healthy   144
✅ Search & Retrieval      healthy   288
✅ Collections Engine      healthy   144
✅ Chat / LLM Service      healthy   288
✅ Telegram Bot            healthy   288
✅ Storage Layer           healthy   288
✅ Infrastructure          healthy   720

Guardian Agents
ID    Name        Health
GA-0  Watcher     healthy
GA-1  Healer      healthy
GA-2  Debugger    healthy
GA-3  Learner     healthy
GA-4  Reporter    healthy
GA-5  Archivist   healthy

🧠 Learned Patterns
- redis-memory-cascade: confidence 0.85 (matched 4x, correct 4x)
- nftables-routing-failure: confidence 0.90 (matched 6x, correct 6x)

📈 Trend Warnings
- Disk usage: 72% → projected 85% in ~6 days
- Redis memory: stable at 45%

Threshold Recommendations
- (none this week)

Total checks (24h): 2448 | Heals: 3 | Preventions: 1
Report generated in: 280ms | Dashboard: localhost:9090
```

## File Structure

```
monitoring/guardian-hc/
├── guardian_hc/
│   ├── __init__.py
│   ├── core.py                 # Slim engine: scheduling, plugin registry, state
│   ├── plugin.py               # Base GuardianPlugin class + CheckResult/HealResult/Insight types
│   ├── config.py               # GuardianConfig, ServiceConfig, ModuleConfig
│   ├── db.py                   # PostgreSQL connection + SQLite fallback buffer
│   ├── agents.py               # Agent persona definitions and health tracking
│   │
│   ├── plugins/
│   │   ├── __init__.py
│   │   ├── infrastructure.py   # Wraps existing checks/healers (container, disk, SSL, network, etc.)
│   │   ├── probes.py           # Deep application probes (JWT, Redis, PG, Nginx, auth flow, Celery, pipeline)
│   │   ├── sentinel.py         # Silent failure detection
│   │   ├── trends.py           # Metrics collection + trend analysis + preventive heals
│   │   └── memory.py           # Incident learning engine + pattern matching
│   │
│   ├── checks/                 # Existing check modules (unchanged)
│   │   ├── containers.py
│   │   ├── http_health.py
│   │   ├── tcp_health.py
│   │   ├── disk.py
│   │   ├── memory.py
│   │   ├── ssl_check.py
│   │   ├── config_drift.py
│   │   ├── network_health.py
│   │   ├── celery_health.py
│   │   ├── vps_load.py
│   │   └── ollama_health.py
│   │
│   ├── healers/                # Existing healers (unchanged)
│   │   ├── container_healer.py
│   │   ├── disk_healer.py
│   │   ├── ssl_healer.py
│   │   ├── memory_healer.py
│   │   └── network_healer.py
│   │
│   ├── patrol/
│   │   └── runner.py           # Enhanced patrol runner — calls plugins
│   │
│   ├── alerts.py               # Existing AlertManager (enhanced with rich formatting)
│   ├── correlator.py           # Existing IncidentCorrelator (enhanced)
│   ├── daily_report.py         # Enhanced daily brief (DroitAssist format)
│   ├── dashboard.py            # Enhanced dashboard (6 pages, SVG charts)
│   ├── dashboard.html          # Dashboard template
│   └── cli.py                  # CLI entry point
│
├── guardian-hc.sowknow4.yml    # Enhanced config with plugins + modules
├── Dockerfile
├── setup.py
├── scripts/
│   ├── preflight.sh
│   ├── install-watchdog.sh
│   ├── watchdog.sh
│   └── bootstrap-patterns.py   # One-time: seed patterns from buglog + incidents
│
└── tests/
    ├── test_core_events.py
    ├── test_correlator.py
    ├── test_probes.py
    ├── test_sentinel.py
    ├── test_trends.py
    └── test_memory.py
```

## Backend Changes Required

1. **New endpoint**: `GET /api/v1/health/deep` — returns db_connected, last_write, active_connections, celery_ping, jwt_valid
2. **New endpoint**: `GET /api/v1/health/auth-check` — generates and verifies a test JWT token
3. **Service account**: `guardian-probe` user seeded in database with limited permissions
4. **Celery probe task**: `guardian.ping` task registered in celery workers — lightweight no-op that confirms task routing and execution

## Config Evolution

```yaml
# guardian-hc.sowknow4.yml additions

version: "2.0"

plugins:
  infrastructure:
    enabled: true
  probes:
    enabled: true
    service_account: "guardian-probe"
  sentinel:
    enabled: true
  trends:
    enabled: true
    retention_raw: "48h"
    retention_hourly: "14d"
  memory:
    enabled: true
    bootstrap_sources:
      - ".wolf/buglog.json"
      - "/var/docker/sowknow4/logs/incidents.jsonl"

modules:
  - name: "Authentication Service"
    services: [backend]
    probes: [jwt_validity, auth_flow]
  - name: "Document Pipeline"
    services: [celery-heavy, celery-light, backend]
    probes: [embedding_pipeline, celery_completion]
  - name: "Search & Retrieval"
    services: [backend, postgres]
    probes: [query_latency]
  - name: "Collections Engine"
    services: [celery-collections, backend]
    probes: [celery_completion]
  - name: "Chat / LLM Service"
    services: [backend]
    probes: [llm_connectivity]
  - name: "Telegram Bot"
    services: [telegram-bot]
    probes: [bot_responsiveness]
  - name: "Storage Layer"
    services: [postgres, redis, vault]
    probes: [redis_deep, postgres_deep, vault_unseal]
  - name: "Infrastructure"
    services: [frontend, backend]
    probes: [nginx_upstream, disk, memory, network, ssl]

database:
  host: "postgres"
  port: 5432
  dbname: "sowknow4"
  user: "guardian"
  password: "${GUARDIAN_DB_PASSWORD}"
  fallback_sqlite: "/tmp/guardian-metrics-buffer.db"

agents:
  - id: "GA-0"
    name: "Watcher"
    plugins: [probes, sentinel]
  - id: "GA-1"
    name: "Healer"
    role: "heal-executor"  # Not a plugin — orchestrates heal() calls from all plugins
  - id: "GA-2"
    name: "Debugger"
    plugins: [correlator]
  - id: "GA-3"
    name: "Learner"
    plugins: [memory]
  - id: "GA-4"
    name: "Reporter"
    plugins: [reporter]
  - id: "GA-5"
    name: "Archivist"
    plugins: [trends]

daily_report:
  time: "06:00"
  timezone: "America/Toronto"
  channels: [telegram, email]
```

## Migration Path

Guardian v2 is backward-compatible. Existing checks and healers are wrapped, not replaced. Migration:

1. Add PostgreSQL tables (`guardian_metrics`, `guardian_metrics_hourly`, `guardian_patterns`)
2. Create `guardian` DB user + `guardian-probe` service account
3. Refactor `core.py` into slim engine + plugin registry
4. Wrap existing checks/healers into `infrastructure` plugin
5. Add new plugins one at a time: probes → sentinel → trends → memory
6. Add backend health endpoints (`/health/deep`, `/health/auth-check`)
7. Register `guardian.ping` Celery task
8. Enhance dashboard and daily report
9. Bootstrap patterns from buglog + incidents
10. Test each agent independently, then full integration
