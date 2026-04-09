# AlertIQ-SOWKNOW — Incident Correlation Layer for Guardian HC

**Date**: 2026-04-09
**Status**: Approved
**Author**: Mamadou Sow + Claude

## Overview

An in-process correlation module inside Guardian HC that groups patrol check results into structured incidents, deduplicates alerts (alert-once with escalation reminders), and outputs to Telegram + a JSONL incident log file.

**What this is NOT**: This does not replace Guardian's check/heal logic. Guardian continues to detect failures and auto-heal. This module sits between the check cycle output and alert delivery, adding correlation, deduplication, and structured formatting.

## Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Integration | In-process module inside Guardian HC | No new container (VPS memory constraints), Guardian already has all context |
| Correlation scope | Patrol-scoped | One patrol run = one correlation window. Patrol boundary is the natural grouping. Unresolved incidents carry forward for dedup. |
| Suppression | Alert-once + escalation reminder | First occurrence → OPEN alert. Ongoing → suppress. 5 consecutive patrols OR RestartTracker suppression → ESCALATION alert. Recovery → RESOLVED alert. |
| Ownership | Single owner (`Platform Admin`), no routing | Solo operator. Schema has `owner` field for future multi-team routing. |
| Output | Telegram Markdown + JSONL log file | Telegram for real-time. JSONL for queryable incident history and post-mortems. |

## AlertEvent Schema

Every check failure in `run_check_cycle()` produces a structured `AlertEvent` instead of a raw string message.

```python
@dataclass
class AlertEvent:
    event_id: str              # "{patrol_level}-{service}-{check_type}-{timestamp_hash}"
    severity: str              # CRITICAL | HIGH | WARNING | INFO
    service: str               # "postgres", "backend", "celery-heavy", "disk", "network", etc.
    container: str | None      # "sowknow4-backend" or None for system checks (disk, vps_load)
    check_type: str            # see Check Types table below
    patrol_level: str          # "critical" | "standard" | "deep"
    timestamp: datetime        # UTC
    summary: str               # max 80 chars
    details: str               # full context
    heal_attempted: bool       # was auto-heal tried?
    heal_success: bool | None  # True/False/None (not attempted)
    heal_action: str | None    # "docker restart sowknow4-postgres" or None
    restart_attempts: int      # from RestartTracker
    restart_suppressed: bool   # True if RestartTracker blocked the restart
```

### Check Types

| check_type | Source |
|---|---|
| `container_down` | Container not running |
| `http_unhealthy` | HTTP health check failed (backend, frontend) |
| `tcp_unhealthy` | TCP health check failed (postgres, redis, vault, nats) |
| `memory_critical` | Container memory > 90% |
| `disk_warning` | Disk usage > 70% |
| `disk_critical` | Disk usage > 85% |
| `celery_queue_critical` | Queue depth > max_queue_depth (200) |
| `celery_down` | Celery worker container not running |
| `network_broken` | Stale nftables + failed probes |
| `ssl_expiring` | Certificate < 14 days to expiry |
| `vps_load_high` | Load average or steal time above threshold |
| `restart_suppressed` | RestartTracker blocked restart (5+ failed attempts) |

### Severity Assignment Rules

| Condition | Severity |
|---|---|
| Network broken (stale nftables + probes failing) | CRITICAL |
| Container down + heal failed or suppressed | CRITICAL |
| Celery queue depth > max_queue_depth | CRITICAL |
| Restart suppressed (5+ failed attempts) | CRITICAL |
| HTTP/TCP health check failed + heal in progress | HIGH |
| Memory > 90% | HIGH |
| Disk > 85% | HIGH |
| SSL < 3 days + auto-renew failed | HIGH |
| Disk > 70% | WARNING |
| VPS load/steal above threshold | WARNING |
| SSL < 14 days | WARNING |
| Container down + heal succeeded | INFO (auto-resolved) |

## Incident Model

The correlator groups `AlertEvent`s into `Incident` objects.

```python
@dataclass
class Incident:
    incident_id: str           # "INC-{YYYYMMDD}-{seq}" e.g. "INC-20260409-003"
    severity: str              # highest severity in the group
    root_cause: AlertEvent     # the event identified as primary failure
    related_events: list[AlertEvent]  # downstream/dependent events
    status: str                # "open" | "escalated" | "resolved"
    opened_at: datetime
    last_seen_at: datetime     # updated each patrol where it's still active
    patrol_count: int          # consecutive patrols this has been active
    escalated_at: datetime | None
    resolved_at: datetime | None
    suppressed_count: int      # how many repeat alerts were suppressed
    owner: str                 # "Platform Admin"
```

### Incident ID Sequence

Daily counter stored in the state file:

```json
{
  "sequence": {"date": "2026-04-09", "counter": 3},
  "active": { ... }
}
```

Resets to 1 each new day. On startup, if date doesn't match today, reset to 1. If state file missing, start at 1.

## Dependency Map

Hardcoded causal relationships based on SOWKNOW4 architecture. When both a cause and its effect appear in the same patrol, they get grouped into one incident.

```python
DEPENDENCY_MAP = {
    # if postgres is down, these will also fail
    "postgres": ["backend", "celery-light", "celery-heavy", "celery-collections"],

    # if redis is down, these will also fail
    "redis": ["backend", "celery-light", "celery-heavy", "celery-collections", "celery-beat"],

    # if backend is down, frontend API calls fail
    "backend": ["frontend"],

    # if network is broken, everything cross-container fails
    "network": ["postgres", "redis", "vault", "nats", "backend", "frontend",
                 "celery-light", "celery-heavy", "celery-collections"],

    # if vault is down, backend may fail on secret lookups
    "vault": ["backend"],
}
```

### Correlation Algorithm

Per patrol run:

1. Collect all `AlertEvent`s from the patrol results
2. **Root cause identification**: For each pair of failing services, check if one is in the other's dependency list. The upstream service is the root cause.
3. **Transitive grouping**: If postgres is the root cause of backend, and backend is the root cause of frontend, all three go into one incident with postgres as root.
4. **Ungrouped failures**: Any failing service with no dependency relationship to others becomes its own incident (e.g., disk warning stands alone).
5. **System-level override**: If `network` is failing, ALL other failures get grouped under it — network is always the root cause when present.

### Active Incident Lifecycle

The correlator maintains an `active_incidents: dict[str, Incident]` map keyed by root cause service name:

- **New failure**: No active incident for this root cause → create incident, set status `"open"`, send OPEN alert to Telegram, append to JSONL
- **Ongoing failure**: Active incident exists → increment `patrol_count`, update `last_seen_at`, increment `suppressed_count`. NO Telegram message.
- **Escalation trigger**: `patrol_count >= 5` (10 min on critical tier) OR `RestartTracker` enters suppression → set status `"escalated"`, send ESCALATION alert, append to JSONL
- **Resolution**: Root cause service passes health check → set status `"resolved"`, send RESOLVED alert, append to JSONL, remove from active map
- **Auto-expiry**: Active incidents older than 24h with no activity get auto-expired and removed

## Telegram Output Format

Three message types. Plain text with line breaks (no Markdown tables — they render poorly on mobile).

### OPEN — New Incident

```
🔴 INCIDENT OPEN — INC-20260409-003

PostgreSQL down → backend, celery-light, celery-heavy cascading

Severity: CRITICAL
Root cause: postgres — TCP health check failed (port 5432 unreachable)
Affected: backend (HTTP 503), celery-light (down), celery-heavy (down)

Auto-heal: docker restart sowknow4-postgres ✅ attempted
Post-heal: ❌ verification failed (attempt 2/5)

Next check in 2 min. Will escalate if unresolved after 5 checks.
```

Standalone (ungrouped) incidents:

```
🟠 INCIDENT OPEN — INC-20260409-004

Disk usage warning

Severity: WARNING
Service: disk — 73% usage (146G / 200G)

Auto-heal: docker prune ✅ reclaimed 4.2G
Status: monitoring — will re-check in 10 min.
```

### ESCALATION — Unresolved after threshold

```
🔴🔴 ESCALATION — INC-20260409-003

PostgreSQL has been down for 10+ minutes (5 consecutive checks)

Restart SUPPRESSED: 5 attempts failed, next retry in 300s
Container likely has a CODE BUG — restarting won't fix it.

Affected services: backend, celery-light, celery-heavy
MANUAL INTERVENTION REQUIRED

Suggested: check postgres logs
  docker logs sowknow4-postgres --tail 50
```

### RESOLVED

```
✅ RESOLVED — INC-20260409-003

PostgreSQL recovered after 3 patrols (6 min)

Auto-healed: docker restart sowknow4-postgres
All dependent services back online: backend, celery-light, celery-heavy
Suppressed alerts: 2
```

## JSON Log File

### Location

`/var/docker/sowknow4/logs/incidents.jsonl`

One JSON line per incident lifecycle event (OPEN, ESCALATION, RESOLVED). An incident that opens, escalates, and resolves produces 3 lines.

### OPEN event

```json
{
  "incident_id": "INC-20260409-003",
  "event_type": "open",
  "timestamp": "2026-04-09T14:22:08Z",
  "severity": "CRITICAL",
  "root_cause": {
    "service": "postgres",
    "container": "sowknow4-postgres",
    "check_type": "tcp_unhealthy",
    "summary": "TCP health check failed (port 5432 unreachable)",
    "details": "TCP connect to postgres:5432 timed out after 10s"
  },
  "related_services": [
    {"service": "backend", "check_type": "http_unhealthy", "summary": "HTTP 503 on /api/v1/health"},
    {"service": "celery-light", "check_type": "container_down", "summary": "Container not running"},
    {"service": "celery-heavy", "check_type": "container_down", "summary": "Container not running"}
  ],
  "heal": {
    "attempted": true,
    "action": "docker restart sowknow4-postgres",
    "success": false,
    "restart_attempts": 2,
    "suppressed": false
  },
  "patrol_level": "critical",
  "patrol_count": 1,
  "suppressed_count": 0,
  "owner": "Platform Admin"
}
```

### ESCALATION event

Same structure with `"event_type": "escalated"` and updated `patrol_count`/`suppressed_count`.

### RESOLVED event

```json
{
  "incident_id": "INC-20260409-003",
  "event_type": "resolved",
  "timestamp": "2026-04-09T14:28:12Z",
  "severity": "CRITICAL",
  "root_cause": {
    "service": "postgres",
    "container": "sowknow4-postgres",
    "check_type": "tcp_unhealthy",
    "summary": "TCP health check failed (port 5432 unreachable)"
  },
  "related_services": ["backend", "celery-light", "celery-heavy"],
  "heal": {
    "attempted": true,
    "action": "docker restart sowknow4-postgres",
    "success": true,
    "restart_attempts": 3
  },
  "duration_seconds": 364,
  "patrol_count": 3,
  "suppressed_count": 2,
  "owner": "Platform Admin"
}
```

### Rotation

No built-in rotation. Relies on existing `log_max_size: 50M` from disk healer config. At ~500 bytes per line, that's ~100K incident events before 50MB. Queryable via `jq`:

```bash
# All critical incidents
cat incidents.jsonl | jq 'select(.severity == "CRITICAL")'

# All postgres incidents
cat incidents.jsonl | jq 'select(.root_cause.service == "postgres")'

# Unresolved (opened but never resolved)
cat incidents.jsonl | jq -s 'group_by(.incident_id) | map(select(all(.event_type != "resolved"))) | flatten'
```

## Integration into core.py

### What changes

**Initialize**: `run_check_cycle()` adds `results["events"] = []` at the top, alongside existing `results["checks"]`. The `results` dict is passed through to `_try_heal_container()` which already receives it as a parameter.

**Remove**: All 8 direct `alert_manager.send()` calls in `run_check_cycle()` and `_try_heal_container()`.

**Replace with**: Each failure appends an `AlertEvent` to `results["events"]` list. Example:

```python
# BEFORE (core.py ~line 233)
await self.alert_manager.send(
    f"*{svc.name}* is running but failing health checks | RESTART SUPPRESSED: {msg}")

# AFTER
results["events"].append(AlertEvent(
    service=svc.name, container=svc.container,
    check_type="restart_suppressed", severity="CRITICAL",
    summary=f"{svc.name} restart suppressed after {tracker.attempts} attempts",
    details=msg, heal_attempted=True, heal_success=False,
    restart_attempts=tracker.attempts, restart_suppressed=True,
    patrol_level=level, timestamp=datetime.now(timezone.utc),
    event_id=f"{level}-{svc.name}-restart_suppressed-{int(datetime.now(timezone.utc).timestamp())}",
    heal_action=None,
))
```

### New patrol flow

```
PatrolRunner calls run_check_cycle(level)
    ↓
run_check_cycle() returns results dict with results["events"] list
    ↓
PatrolRunner calls correlator.process(results)
    ↓
IncidentCorrelator:
  1. Groups events using DEPENDENCY_MAP
  2. Checks active_incidents for dedup
  3. New → format Telegram msg + append JSONL + send via AlertManager
  4. Ongoing → suppress (increment counter)
  5. Escalation threshold → format escalation msg + append JSONL + send
  6. Previously failing, now healthy → resolve + send RESOLVED
    ↓
AlertManager.send() only called by correlator
```

### What stays the same

- `run_check_cycle()` still does all checks and healing — no change to check/heal logic
- `RestartTracker` unchanged — correlator reads its state, doesn't modify it
- `_try_heal_container()` still performs restarts — stops sending alerts, records outcome in results
- `log_action()` / `_history` unchanged — correlator is additive
- Daily report unchanged — runs on its own schedule, reads from `_history`

### New file

```
monitoring/guardian-hc/guardian_hc/correlator.py
```

Contains:
- `AlertEvent` dataclass
- `Incident` dataclass
- `IncidentCorrelator` class (process, correlate, dedup, format, persist)
- `DEPENDENCY_MAP` dict
- Telegram message formatters (open, escalation, resolved)
- JSONL writer

### State persistence

`active_incidents` map + sequence counter persisted to `/tmp/guardian-active-incidents.json` (same pattern as `guardian-restart-trackers.json`). Loaded on startup, saved after each patrol. Incidents older than 24h with no activity auto-expire.

## Testing Strategy

- **Unit tests**: Correlator logic — dependency grouping, dedup, escalation threshold, resolution detection. Use synthetic `AlertEvent` lists, no Docker/network dependency.
- **Integration test**: Mock `run_check_cycle()` returning a results dict with events, verify correlator produces correct Telegram messages and JSONL entries.
- **Manual validation**: Run Guardian in dev with simulated failures (stop a container, watch the correlation output).
