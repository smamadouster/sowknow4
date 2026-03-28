#!/usr/bin/env bash
# =============================================================================
# SOWKNOW4 Docker Infrastructure Audit Script
# =============================================================================
# Audits the docker-compose.yml, Dockerfiles, and running containers against
# the 20 most common Docker multi-container issues (2026 reference).
#
# Usage:  ./scripts/docker-audit.sh [--live]
#   --live   Also inspect running containers (requires Docker access)
#   (default) Static analysis only (compose + Dockerfiles)
#
# Output: Scored report with PASS / WARN / FAIL per check.
# =============================================================================

set -uo pipefail
# NOTE: No -e flag. Many grep commands intentionally return 1 (no match).

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
LIVE_MODE=false
[[ "${1:-}" == "--live" ]] && LIVE_MODE=true

# --- Colours & counters ------------------------------------------------------
RED='\033[0;31m'; YEL='\033[0;33m'; GRN='\033[0;32m'; CYN='\033[0;36m'; RST='\033[0m'
PASS_N=0; WARN_N=0; FAIL_N=0; SKIP_N=0

pass()  { ((PASS_N++)); printf "  ${GRN}[PASS]${RST}  %s\n" "$1"; }
warn()  { ((WARN_N++)); printf "  ${YEL}[WARN]${RST}  %s\n" "$1"; }
fail()  { ((FAIL_N++)); printf "  ${RED}[FAIL]${RST}  %s\n" "$1"; }
skip()  { ((SKIP_N++)); printf "  ${CYN}[SKIP]${RST}  %s\n" "$1"; }
header(){ printf "\n${CYN}=== CHECK %s: %s ===${RST}\n" "$1" "$2"; }

# --- Pre-flight ---------------------------------------------------------------
if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "ERROR: docker-compose.yml not found at $COMPOSE_FILE"
    exit 1
fi

DOCKERFILES=$(find "$PROJECT_DIR" -maxdepth 3 -name 'Dockerfile*' \
    ! -path '*/node_modules/*' ! -path '*/venv/*' ! -path '*/.git/*' 2>/dev/null)

echo "========================================================================"
echo "  SOWKNOW4 Docker Infrastructure Audit"
echo "  Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Mode: $(if $LIVE_MODE; then echo 'LIVE (static + running containers)'; else echo 'STATIC (compose + Dockerfiles only)'; fi)"
echo "  Compose: $COMPOSE_FILE"
echo "========================================================================"

# =============================================================================
# LIST A — Single-container issues (10 checks)
# =============================================================================

# ---------------------------------------------------------------------------
header "A1" "Port Conflicts — no duplicate host port bindings"
# ---------------------------------------------------------------------------
HOST_PORTS=$(grep -E '^\s*-\s*"[0-9]+:[0-9]+"' "$COMPOSE_FILE" | sed 's/.*"\([0-9]*\):.*/\1/' | sort)
DUPES=$(echo "$HOST_PORTS" | uniq -d)
if [[ -z "$HOST_PORTS" ]]; then
    warn "No host ports found — verify services are reachable"
elif [[ -n "$DUPES" ]]; then
    fail "Duplicate host ports: $DUPES"
else
    pass "No duplicate host port bindings (exposed: $(echo $HOST_PORTS | tr '\n' ' '))"
fi

# Also check: internal services must NOT expose ports
INTERNAL_SERVICES="postgres redis vault nats"
for svc in $INTERNAL_SERVICES; do
    if grep -A30 "^  ${svc}:" "$COMPOSE_FILE" | grep -B0 -A30 "container_name" | grep -q '^\s*ports:'; then
        fail "$svc exposes host ports — violates zero-trust port policy"
    else
        pass "$svc has no host port exposure (internal-only)"
    fi
done

# ---------------------------------------------------------------------------
header "A2" "Resource Exhaustion — CPU & memory limits on every service"
# ---------------------------------------------------------------------------
# Extract all service names from compose
# Extract only actual services (between 'services:' and 'networks:'/'volumes:')
SERVICES=$(sed -n '/^services:/,/^\(networks:\|volumes:\)/p' "$COMPOSE_FILE" \
    | grep -E '^  [a-z][a-z0-9_-]*:$' | sed 's/://;s/^ *//')
ALL_HAVE_LIMITS=true
for svc in $SERVICES; do
    # Check if this service block has deploy.resources.limits
    SVC_BLOCK=$(sed -n "/^  ${svc}:/,/^  [a-z]/p" "$COMPOSE_FILE")
    if echo "$SVC_BLOCK" | grep -q 'memory:' && echo "$SVC_BLOCK" | grep -q 'cpus:'; then
        MEM=$(echo "$SVC_BLOCK" | grep 'memory:' | head -1 | awk '{print $2}')
        CPU=$(echo "$SVC_BLOCK" | grep 'cpus:' | head -1 | awk '{print $2}' | tr -d "'")
        pass "$svc has limits: memory=$MEM cpus=$CPU"
    else
        fail "$svc is MISSING memory/cpu limits"
        ALL_HAVE_LIMITS=false
    fi
done

# Sum total memory
TOTAL_MEM=$(grep 'memory:' "$COMPOSE_FILE" | awk '{print $2}' | sed 's/M//' | paste -sd+ | bc 2>/dev/null || echo "?")
if [[ "$TOTAL_MEM" != "?" ]]; then
    echo "  -> Total memory allocated: ${TOTAL_MEM}MB"
    if (( TOTAL_MEM > 30000 )); then
        warn "Total memory (${TOTAL_MEM}MB) exceeds 30GB — tight on 32GB VPS"
    else
        pass "Total memory (${TOTAL_MEM}MB) fits within 32GB VPS"
    fi
fi

# ---------------------------------------------------------------------------
header "A3" "Bloated Image Sizes — slim bases & multi-stage builds"
# ---------------------------------------------------------------------------
for df in $DOCKERFILES; do
    REL=$(realpath --relative-to="$PROJECT_DIR" "$df" 2>/dev/null || echo "$df")
    BASE_IMAGES=$(grep '^FROM ' "$df" | awk '{print $2}')
    STAGES=$(grep -c '^FROM ' "$df")

    for img in $BASE_IMAGES; do
        if echo "$img" | grep -qE '(slim|alpine|distroless)'; then
            pass "$REL uses slim/alpine base: $img"
        elif echo "$img" | grep -qE 'AS (builder|build)'; then
            pass "$REL build stage uses: $img (multi-stage OK)"
        else
            # Check if it's an intermediate stage in a multi-stage build
            if (( STAGES > 1 )); then
                warn "$REL base $img is not slim, but multi-stage build mitigates"
            else
                fail "$REL uses non-slim base without multi-stage: $img"
            fi
        fi
    done

    if (( STAGES > 1 )); then
        pass "$REL uses multi-stage build ($STAGES stages)"
    elif echo "$REL" | grep -qi 'frontend' && ! echo "$REL" | grep -qi '\.dev'; then
        fail "$REL should use multi-stage build"
    elif echo "$REL" | grep -qi '\.dev'; then
        warn "$REL has no multi-stage build (acceptable for dev-only Dockerfile)"
    fi
done

# ---------------------------------------------------------------------------
header "A4" "Security & Misconfigurations — non-root user, no hardcoded secrets"
# ---------------------------------------------------------------------------
for df in $DOCKERFILES; do
    REL=$(realpath --relative-to="$PROJECT_DIR" "$df" 2>/dev/null || echo "$df")

    # Check for USER instruction
    if grep -q '^USER ' "$df"; then
        USER_VAL=$(grep '^USER ' "$df" | tail -1 | awk '{print $2}')
        if [[ "$USER_VAL" == "root" ]]; then
            fail "$REL runs as root"
        else
            pass "$REL runs as non-root user: $USER_VAL"
        fi
    else
        warn "$REL has no USER instruction (defaults to root)"
    fi

    # Check for hardcoded secrets/passwords in Dockerfile
    if grep -iE '(password|secret|api_key|token)=' "$df" | grep -vE '(ARG|ENV.*\$|#)' | grep -qi '[a-z0-9]'; then
        fail "$REL may contain hardcoded secrets"
    else
        pass "$REL has no hardcoded secrets"
    fi
done

# Check .env.example for placeholder patterns (not real values)
if [[ -f "$PROJECT_DIR/.env.example" ]]; then
    REAL_LOOKING=$(grep -E '(PASSWORD|SECRET|KEY|TOKEN)=' "$PROJECT_DIR/.env.example" \
        | grep -vE '(REPLACE_WITH|your_|changeme|placeholder|example|sowknow-dev-token)' \
        | grep -vE '^#' || true)
    if [[ -n "$REAL_LOOKING" ]]; then
        warn ".env.example may contain real-looking credentials — review these lines:"
        echo "$REAL_LOOKING" | head -5 | sed 's/^/         /'
    else
        pass ".env.example uses placeholder values"
    fi
fi

# Check .gitignore excludes .env
if grep -q '^\.env$\|^\.env\b' "$PROJECT_DIR/.gitignore" 2>/dev/null; then
    pass ".gitignore excludes .env files"
else
    fail ".gitignore does NOT exclude .env — secrets could be committed"
fi

# ---------------------------------------------------------------------------
header "A5" "Health Check Discipline — every service has a healthcheck"
# ---------------------------------------------------------------------------
for svc in $SERVICES; do
    SVC_BLOCK=$(sed -n "/^  ${svc}:/,/^  [a-z]/p" "$COMPOSE_FILE")
    if echo "$SVC_BLOCK" | grep -q 'healthcheck:'; then
        # Check for start_period (important for slow-starting apps)
        if echo "$SVC_BLOCK" | grep -q 'start_period:'; then
            pass "$svc has healthcheck with start_period"
        else
            warn "$svc has healthcheck but no start_period (may false-alarm on slow startup)"
        fi
    else
        fail "$svc has NO healthcheck defined"
    fi
done

# ---------------------------------------------------------------------------
header "A6" "Architecture Mismatch — platform pinning"
# ---------------------------------------------------------------------------
if grep -q 'platform:' "$COMPOSE_FILE"; then
    pass "Compose file specifies platform constraints"
else
    warn "No platform: directive in compose — OK if all images match host arch (amd64)"
    echo "  -> Recommendation: add 'platform: linux/amd64' to services for reproducibility"
fi

# ---------------------------------------------------------------------------
header "A7" "Storage & Volume Issues — log rotation, named volumes"
# ---------------------------------------------------------------------------
# Check log rotation
if grep -qE 'max-size|max-file' "$COMPOSE_FILE"; then
    MAX_SIZE=$(grep 'max-size' "$COMPOSE_FILE" | head -1 | awk -F'"' '{print $2}')
    MAX_FILE=$(grep 'max-file' "$COMPOSE_FILE" | head -1 | awk -F'"' '{print $2}')
    pass "Log rotation configured: max-size=$MAX_SIZE, max-file=$MAX_FILE"
else
    fail "No log rotation configured — logs will grow unbounded"
fi

# Check for named volumes (not just bind mounts)
NAMED_VOLS=$(grep -c '^\s*sowknow-' "$COMPOSE_FILE" | head -1 || echo 0)
if (( NAMED_VOLS > 0 )); then
    pass "Uses named volumes for persistent data ($NAMED_VOLS volume references)"
else
    warn "No named volumes found — data may not persist across container recreation"
fi

# Check for tmpfs or ephemeral storage where appropriate
if grep -q 'celerybeat-schedule' "$COMPOSE_FILE"; then
    if grep -q '/tmp/celerybeat' "$COMPOSE_FILE"; then
        pass "Celery beat schedule uses /tmp (ephemeral, no volume leak)"
    fi
fi

# ---------------------------------------------------------------------------
header "A8" "Non-Root User Permissions — volume ownership"
# ---------------------------------------------------------------------------
for df in $DOCKERFILES; do
    REL=$(realpath --relative-to="$PROJECT_DIR" "$df" 2>/dev/null || echo "$df")
    if grep -q 'chown' "$df"; then
        pass "$REL sets file ownership (chown found)"
    elif grep -q '^USER ' "$df"; then
        warn "$REL switches to non-root but has no explicit chown — may hit permission errors on volumes"
    fi
done

# Check bind mounts that might have permission issues
BIND_MOUNTS=$(grep -E '\./[a-z].*:/[a-z]' "$COMPOSE_FILE" || true)
if [[ -n "$BIND_MOUNTS" ]]; then
    echo "  -> Bind mounts detected (may need host permission alignment):"
    echo "$BIND_MOUNTS" | sed 's/^/         /'
    warn "Bind mounts found — ensure host dirs are writable by container UID 1001"
fi

# ---------------------------------------------------------------------------
header "A9" "Network Complexity — single bridge, service-name DNS"
# ---------------------------------------------------------------------------
NET_COUNT=$(grep -c 'driver: bridge' "$COMPOSE_FILE" || echo 0)
if (( NET_COUNT == 1 )); then
    pass "Single bridge network (sowknow-net) — simple topology"
else
    warn "Multiple networks detected ($NET_COUNT) — verify inter-service connectivity"
fi

# Check all services are on sowknow-net
for svc in $SERVICES; do
    SVC_BLOCK=$(sed -n "/^  ${svc}:/,/^  [a-z]/p" "$COMPOSE_FILE")
    if echo "$SVC_BLOCK" | grep -q 'sowknow-net'; then
        : # OK
    else
        warn "$svc may not be on sowknow-net"
    fi
done

# Check for localhost references (should use service names)
LOCALHOST_REFS=$(grep -n 'localhost' "$COMPOSE_FILE" | grep -v '127.0.0.1.*healthcheck\|127.0.0.1.*health\|localhost:8000.*health\|localhost:3000\|localhost:9090' || true)
if [[ -n "$LOCALHOST_REFS" ]]; then
    warn "Found localhost references that may not resolve inter-container:"
    echo "$LOCALHOST_REFS" | sed 's/^/         /'
else
    pass "No problematic localhost references — services use DNS names"
fi

# ---------------------------------------------------------------------------
header "A10" "Unvetted Base Images — trusted sources, pinned versions"
# ---------------------------------------------------------------------------
for df in $DOCKERFILES; do
    REL=$(realpath --relative-to="$PROJECT_DIR" "$df" 2>/dev/null || echo "$df")
    BASES=$(grep '^FROM ' "$df" | awk '{print $2}')
    for img in $BASES; do
        # Check for :latest tag
        if echo "$img" | grep -q ':latest'; then
            fail "$REL uses :latest tag: $img — non-deterministic builds"
        elif echo "$img" | grep -qE ':[0-9a-z]'; then
            pass "$REL pins version: $img"
        else
            fail "$REL has no tag (implicit :latest): $img"
        fi

        # Check for official/known publishers
        if echo "$img" | grep -qE '^(python|node|nginx|redis|postgres|pgvector|hashicorp|nats|prom|certbot)'; then
            pass "$REL uses official/trusted image: $img"
        fi
    done
done

# Also check compose images
COMPOSE_IMAGES=$(grep '^\s*image:' "$COMPOSE_FILE" | awk '{print $2}')
for img in $COMPOSE_IMAGES; do
    if echo "$img" | grep -q ':latest'; then
        fail "Compose uses :latest: $img — pin to specific version"
    elif echo "$img" | grep -qE ':[0-9]'; then
        pass "Compose pins version: $img"
    fi
done

# =============================================================================
# LIST B — Multi-container / distributed issues (10 checks)
# =============================================================================

# ---------------------------------------------------------------------------
header "B1" "Resource Contention (Noisy Neighbor) — per-service limits & total budget"
# ---------------------------------------------------------------------------
# Already checked individual limits in A2, now check for contention risk
CELERY_MEM=$(grep -A15 'celery-worker:' "$COMPOSE_FILE" | grep 'memory:' | head -1 | awk '{print $2}' | sed 's/M//')
if [[ -n "$CELERY_MEM" ]] && (( CELERY_MEM > 4000 )); then
    warn "celery-worker has ${CELERY_MEM}MB limit — largest consumer, monitor for OOM"
else
    pass "celery-worker memory is reasonable"
fi

# Check concurrency setting
if grep -q 'concurrency=1' "$COMPOSE_FILE"; then
    pass "Celery worker concurrency=1 (prevents RAM explosion with embedding model)"
else
    warn "Celery worker concurrency not set to 1 — risk of OOM with large models"
fi

# ---------------------------------------------------------------------------
header "B2" "Networking & Service Discovery — depends_on with conditions"
# ---------------------------------------------------------------------------
# Check for depends_on with condition: service_healthy (not just service_started)
HEALTHY_DEPS=$(grep -c 'condition: service_healthy' "$COMPOSE_FILE" || echo 0)
STARTED_DEPS=$(grep -c 'condition: service_started' "$COMPOSE_FILE" || echo 0)
BARE_DEPS=$(grep -B0 -A1 'depends_on:' "$COMPOSE_FILE" | grep -c '^\s*-\s' || echo 0)

if (( HEALTHY_DEPS > 0 )); then
    pass "$HEALTHY_DEPS dependencies use condition: service_healthy"
fi
if (( BARE_DEPS > 0 )); then
    warn "$BARE_DEPS bare depends_on entries (no health condition) — container starts before dependency is ready"
fi

# Check that backend waits for all infra
BACKEND_BLOCK=$(sed -n '/^  backend:/,/^  [a-z]/p' "$COMPOSE_FILE")
for dep in postgres redis vault nats; do
    if echo "$BACKEND_BLOCK" | grep -q "$dep"; then
        if echo "$BACKEND_BLOCK" | grep -A1 "$dep:" | grep -q 'service_healthy'; then
            pass "backend waits for $dep to be healthy"
        else
            warn "backend depends on $dep but doesn't wait for healthy"
        fi
    fi
done

# ---------------------------------------------------------------------------
header "B3" "Circular Dependencies & Startup Order"
# ---------------------------------------------------------------------------
# Check celery-beat depends_on — it should wait for healthy, not just started
BEAT_BLOCK=$(sed -n '/^  celery-beat:/,/^  [a-z]/p' "$COMPOSE_FILE")
if echo "$BEAT_BLOCK" | grep -q 'depends_on:'; then
    if echo "$BEAT_BLOCK" | grep -q 'service_healthy'; then
        pass "celery-beat uses service_healthy conditions"
    else
        warn "celery-beat depends_on without service_healthy — may start before DB/Redis are ready"
    fi
fi

# Detect any circular dependency patterns
# Parse depends_on blocks to extract service->dependency pairs, then check for A->B and B->A
echo "  -> Checking for circular dependency patterns..."
FOUND_CIRCULAR=false
DEPMAP_FILE=$(mktemp)
# Build dependency map: "service dependency" per line
CURRENT_SVC=""
IN_DEPENDS=false
while IFS= read -r line; do
    # Match service definition (exactly 2 leading spaces)
    if [[ "$line" =~ ^\ \ [a-z][a-z0-9_-]*:$ ]]; then
        CURRENT_SVC=$(echo "$line" | sed 's/^ *//;s/:$//')
        IN_DEPENDS=false
    elif [[ "$line" =~ ^\ {4}depends_on: ]]; then
        IN_DEPENDS=true
    elif $IN_DEPENDS; then
        # Lines under depends_on that reference services (e.g. "      postgres:" or "      - postgres")
        if [[ "$line" =~ ^\ {6}[a-z] ]] || [[ "$line" =~ ^\ {6}-\ [a-z] ]]; then
            DEP=$(echo "$line" | sed 's/^ *//;s/^- //;s/:$//')
            echo "$CURRENT_SVC $DEP" >> "$DEPMAP_FILE"
        elif [[ "$line" =~ ^\ {8} ]]; then
            : # Indented sub-key (condition:), skip
        else
            IN_DEPENDS=false
        fi
    fi
done < "$COMPOSE_FILE"

while read -r svc dep; do
    if grep -q "^${dep} ${svc}$" "$DEPMAP_FILE" 2>/dev/null; then
        fail "Circular dependency detected: $svc <-> $dep"
        FOUND_CIRCULAR=true
    fi
done < "$DEPMAP_FILE"
rm -f "$DEPMAP_FILE"
$FOUND_CIRCULAR || pass "No circular dependencies detected"

# ---------------------------------------------------------------------------
header "B4" "Storage & Data Persistence — volumes for stateful services"
# ---------------------------------------------------------------------------
STATEFUL="postgres redis vault nats"
for svc in $STATEFUL; do
    SVC_BLOCK=$(sed -n "/^  ${svc}:/,/^  [a-z]/p" "$COMPOSE_FILE")
    if echo "$SVC_BLOCK" | grep -qE 'sowknow-.*-data:'; then
        pass "$svc uses a named volume for persistent data"
    else
        fail "$svc has NO named volume — data will be lost on recreation"
    fi
done

# Check backups volume
if grep -q 'sowknow-backups' "$COMPOSE_FILE"; then
    pass "Backup volume (sowknow-backups) is defined"
else
    warn "No dedicated backup volume found"
fi

# ---------------------------------------------------------------------------
header "B5" "Zombie Processes & Signal Handling — init/tini"
# ---------------------------------------------------------------------------
INIT_FOUND=false
for df in $DOCKERFILES; do
    REL=$(realpath --relative-to="$PROJECT_DIR" "$df" 2>/dev/null || echo "$df")
    if grep -qiE 'tini|dumb-init' "$df"; then
        pass "$REL uses init system (tini/dumb-init)"
        INIT_FOUND=true
    fi
done

# Check compose for init: true
if grep -q 'init: true' "$COMPOSE_FILE"; then
    pass "Compose uses init: true for signal handling"
    INIT_FOUND=true
fi

if ! $INIT_FOUND; then
    warn "No init system (tini/dumb-init) or init:true found — risk of zombie processes and 10s shutdown delays"
    echo "  -> Fix: add 'init: true' to services in docker-compose.yml, or use tini in Dockerfiles"
fi

# Check for exec form CMD (proper signal forwarding)
for df in $DOCKERFILES; do
    REL=$(realpath --relative-to="$PROJECT_DIR" "$df" 2>/dev/null || echo "$df")
    CMD_LINE=$(grep '^CMD ' "$df" | tail -1)
    if echo "$CMD_LINE" | grep -q '^\s*CMD\s*\['; then
        pass "$REL uses exec-form CMD (good signal handling)"
    elif echo "$CMD_LINE" | grep -q 'exec '; then
        pass "$REL uses exec in shell-form CMD (signal forwarding OK)"
    elif [[ -n "$CMD_LINE" ]]; then
        warn "$REL uses shell-form CMD without exec — PID 1 is /bin/sh, not the app"
    fi
done

# ---------------------------------------------------------------------------
header "B6" "Image Tag Pinning — no :latest in production"
# ---------------------------------------------------------------------------
LATEST_COUNT=0
ALL_IMAGES=$(grep '^\s*image:' "$COMPOSE_FILE" | awk '{print $2}')
for img in $ALL_IMAGES; do
    if echo "$img" | grep -q ':latest'; then
        fail "Production compose uses :latest — $img"
        ((LATEST_COUNT++))
    elif echo "$img" | grep -qE ':[0-9a-z]'; then
        pass "Pinned: $img"
    else
        fail "No tag (implicit :latest): $img"
        ((LATEST_COUNT++))
    fi
done
if (( LATEST_COUNT == 0 )); then
    pass "All compose images are version-pinned"
fi

# ---------------------------------------------------------------------------
header "B7" "Security — root, docker.sock, capabilities"
# ---------------------------------------------------------------------------
# Docker socket exposure
if grep -q 'docker.sock' "$COMPOSE_FILE"; then
    SOCK_SVC=$(grep -B20 'docker.sock' "$COMPOSE_FILE" | grep 'container_name:' | tail -1 | awk '{print $2}')
    if grep -A5 'docker.sock' "$COMPOSE_FILE" | grep -q ':ro'; then
        warn "Docker socket mounted in $SOCK_SVC (read-only) — still a privilege escalation vector"
    else
        fail "Docker socket mounted in $SOCK_SVC WITHOUT read-only — full host control"
    fi
else
    pass "No Docker socket mounted"
fi

# Privileged mode
if grep -q 'privileged: true' "$COMPOSE_FILE"; then
    fail "Privileged containers found — full host access"
else
    pass "No privileged containers"
fi

# Capabilities
CAP_ADDS=$(grep -A2 'cap_add:' "$COMPOSE_FILE" | grep '^\s*-' | awk '{print $2}')
if [[ -n "$CAP_ADDS" ]]; then
    for cap in $CAP_ADDS; do
        if [[ "$cap" == "IPC_LOCK" ]]; then
            pass "cap_add IPC_LOCK for Vault (expected — prevents secret swapping)"
        elif [[ "$cap" == "SYS_ADMIN" || "$cap" == "NET_ADMIN" || "$cap" == "ALL" ]]; then
            fail "Dangerous capability: $cap"
        else
            warn "Extra capability: $cap — verify necessity"
        fi
    done
else
    pass "No extra capabilities added (except Vault IPC_LOCK)"
fi

# security_opt / no-new-privileges
if grep -q 'no-new-privileges' "$COMPOSE_FILE"; then
    pass "security_opt: no-new-privileges is set"
else
    warn "no-new-privileges not set — consider adding 'security_opt: [no-new-privileges:true]' to services"
fi

# read_only filesystem
if grep -q 'read_only: true' "$COMPOSE_FILE"; then
    pass "Some services use read-only root filesystem"
else
    warn "No read_only: true found — consider for stateless services (redis, nats)"
fi

# ---------------------------------------------------------------------------
header "B8" "Logging & Observability — centralized logging config"
# ---------------------------------------------------------------------------
# Check for x-logging anchor (shared config)
if grep -q 'x-logging' "$COMPOSE_FILE"; then
    pass "Shared logging config via YAML anchor (x-logging)"
fi

# Check that all services reference the logging config
MISSING_LOG=0
for svc in $SERVICES; do
    SVC_BLOCK=$(sed -n "/^  ${svc}:/,/^  [a-z]/p" "$COMPOSE_FILE")
    if echo "$SVC_BLOCK" | grep -qE 'logging:'; then
        : # OK
    else
        # Profile services may not need it
        if echo "$SVC_BLOCK" | grep -q 'profiles:'; then
            : # Optional, skip
        else
            warn "$svc has no logging configuration"
            ((MISSING_LOG++))
        fi
    fi
done
(( MISSING_LOG == 0 )) && pass "All core services have logging configured"

# Check for structured logging / correlation IDs in app code
if grep -rql 'correlation.id\|request_id\|trace_id\|X-Request-ID' "$PROJECT_DIR/backend/app/" 2>/dev/null; then
    pass "Application code has request correlation ID support"
else
    warn "No correlation/trace ID found in backend — harder to trace cross-service requests"
fi

# ---------------------------------------------------------------------------
header "B9" "Secret Management — env files, vault integration"
# ---------------------------------------------------------------------------
# .env excluded from git
if [[ -f "$PROJECT_DIR/.gitignore" ]]; then
    if grep -qE '^\.env$' "$PROJECT_DIR/.gitignore"; then
        pass ".env is in .gitignore"
    else
        fail ".env NOT in .gitignore — secrets may leak"
    fi
    if grep -q '\.secrets' "$PROJECT_DIR/.gitignore"; then
        pass ".secrets is in .gitignore"
    else
        warn ".secrets file referenced in compose but not found in .gitignore"
    fi
fi

# Vault integration
if grep -q 'vault' "$COMPOSE_FILE"; then
    pass "HashiCorp Vault service is configured"
fi

# Check for required-variable syntax (prevents empty secrets)
REQUIRED_VARS=$(grep -oE '\$\{[A-Z_]+:\?' "$COMPOSE_FILE" | sort -u | wc -l)
if (( REQUIRED_VARS > 0 )); then
    pass "$REQUIRED_VARS env vars use \${VAR:?msg} syntax (fail-fast on missing secrets)"
else
    warn "No required-variable syntax found — services may start with empty credentials"
fi

# Check for dev-mode vault token in compose
if grep -q 'sowknow-dev-token' "$COMPOSE_FILE"; then
    warn "Dev-mode Vault token (sowknow-dev-token) found in compose — ensure production uses proper auth"
fi

# ---------------------------------------------------------------------------
header "B10" "Configuration Drift — single Dockerfile per service, env injection"
# ---------------------------------------------------------------------------
# Count compose files (should be exactly 2: docker-compose.yml + docker-compose.dev.yml)
COMPOSE_COUNT=$(find "$PROJECT_DIR" -maxdepth 1 -name 'docker-compose*.yml' | wc -l)
if (( COMPOSE_COUNT == 1 )); then
    pass "Single docker-compose.yml (source of truth)"
elif (( COMPOSE_COUNT == 2 )); then
    if [[ -f "$PROJECT_DIR/docker-compose.dev.yml" ]]; then
        pass "Two compose files: production + dev (allowed per CLAUDE.md)"
    else
        OTHER=$(find "$PROJECT_DIR" -maxdepth 1 -name 'docker-compose*.yml' ! -name 'docker-compose.yml' -printf '%f\n')
        fail "Extra compose file: $OTHER — CLAUDE.md allows only docker-compose.yml + docker-compose.dev.yml"
    fi
else
    fail "$COMPOSE_COUNT compose files found — CLAUDE.md mandates a single source of truth"
    find "$PROJECT_DIR" -maxdepth 1 -name 'docker-compose*.yml' -printf '         %f\n'
fi

# Check env injection pattern (should use .env, not hardcoded)
HARDCODED_ENV=$(grep -P '^\s*-\s*[A-Z_]+=(?!.*\$\{)' "$COMPOSE_FILE" 2>/dev/null | grep -vE '(PYTHONPATH|NODE_ENV|NEXT_PUBLIC|APP_ENV)' | head -5 || true)
if [[ -n "$HARDCODED_ENV" ]]; then
    warn "Some env vars are hardcoded in compose (not injected from .env):"
    echo "$HARDCODED_ENV" | sed 's/^/         /'
else
    pass "Environment variables are injected from .env (no hardcoded secrets in compose)"
fi

# Naming convention check
echo "  -> Checking container naming convention (sowknow4- prefix)..."
BAD_NAMES=$(grep 'container_name:' "$COMPOSE_FILE" | grep -v 'sowknow4-' || true)
if [[ -n "$BAD_NAMES" ]]; then
    fail "Containers without sowknow4- prefix found:"
    echo "$BAD_NAMES" | sed 's/^/         /'
else
    pass "All containers use sowknow4- prefix"
fi

# =============================================================================
# LIVE CHECKS (only with --live flag)
# =============================================================================
if $LIVE_MODE; then
    echo ""
    echo "========================================================================"
    echo "  LIVE CONTAINER CHECKS"
    echo "========================================================================"

    if ! command -v docker &>/dev/null; then
        fail "Docker CLI not found — cannot run live checks"
    elif ! docker info &>/dev/null 2>&1; then
        fail "Docker daemon not reachable — cannot run live checks"
    else
        # --- Container health status ---
        header "L1" "Running Container Health Status"
        CONTAINERS=$(docker ps --filter "name=sowknow4" --format '{{.Names}}' 2>/dev/null || true)
        if [[ -z "$CONTAINERS" ]]; then
            warn "No sowknow4 containers running"
        else
            for ctr in $CONTAINERS; do
                HEALTH=$(docker inspect --format '{{.State.Health.Status}}' "$ctr" 2>/dev/null || echo "no-healthcheck")
                STATUS=$(docker inspect --format '{{.State.Status}}' "$ctr" 2>/dev/null || echo "unknown")
                if [[ "$HEALTH" == "healthy" ]]; then
                    pass "$ctr: $STATUS ($HEALTH)"
                elif [[ "$HEALTH" == "unhealthy" ]]; then
                    fail "$ctr: $STATUS ($HEALTH)"
                    # Show last healthcheck log
                    docker inspect --format '{{range .State.Health.Log}}{{.Output}}{{end}}' "$ctr" 2>/dev/null | tail -3 | sed 's/^/         /'
                elif [[ "$HEALTH" == "starting" ]]; then
                    warn "$ctr: $STATUS (still starting)"
                else
                    warn "$ctr: $STATUS (no healthcheck or $HEALTH)"
                fi
            done
        fi

        # --- Resource usage ---
        header "L2" "Live Resource Usage (docker stats snapshot)"
        docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" \
            $(docker ps --filter "name=sowknow4" -q 2>/dev/null) 2>/dev/null | head -20 || warn "Could not get stats"

        # --- Restart counts ---
        header "L3" "Container Restart Counts"
        HIGH_RESTART=false
        for ctr in $CONTAINERS; do
            RESTARTS=$(docker inspect --format '{{.RestartCount}}' "$ctr" 2>/dev/null || echo "?")
            if [[ "$RESTARTS" != "?" ]] && (( RESTARTS > 5 )); then
                fail "$ctr has restarted $RESTARTS times (possible crash loop)"
                HIGH_RESTART=true
            elif [[ "$RESTARTS" != "?" ]] && (( RESTARTS > 0 )); then
                warn "$ctr has restarted $RESTARTS times"
            else
                pass "$ctr: $RESTARTS restarts"
            fi
        done

        # --- Disk usage ---
        header "L4" "Docker Disk Usage"
        docker system df 2>/dev/null || warn "Could not check disk usage"
        RECLAIMABLE=$(docker system df 2>/dev/null | grep 'Images' | awk '{print $NF}' | tr -d '()%' || echo "0")
        if [[ "$RECLAIMABLE" =~ ^[0-9]+$ ]] && (( RECLAIMABLE > 50 )); then
            warn "Over 50% reclaimable image space — run 'docker system prune -f'"
        fi

        # --- OOM kills ---
        header "L5" "OOM Kill Detection"
        OOM_FOUND=false
        for ctr in $CONTAINERS; do
            OOM=$(docker inspect --format '{{.State.OOMKilled}}' "$ctr" 2>/dev/null || echo "false")
            if [[ "$OOM" == "true" ]]; then
                fail "$ctr was OOM-killed — increase memory limit or reduce load"
                OOM_FOUND=true
            fi
        done
        $OOM_FOUND || pass "No containers have been OOM-killed"
    fi
else
    echo ""
    echo "  (Run with --live flag to also check running containers)"
fi

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo "========================================================================"
echo "  AUDIT SUMMARY"
echo "========================================================================"
TOTAL=$((PASS_N + WARN_N + FAIL_N))
if (( TOTAL == 0 )); then
    echo "  No checks were executed."
    exit 1
fi

SCORE=$(( (PASS_N * 100) / TOTAL ))
printf "  ${GRN}PASS: %d${RST}  |  ${YEL}WARN: %d${RST}  |  ${RED}FAIL: %d${RST}  |  SKIP: %d\n" "$PASS_N" "$WARN_N" "$FAIL_N" "$SKIP_N"
printf "  Score: %d%% (%d/%d checks passed)\n" "$SCORE" "$PASS_N" "$TOTAL"

if (( FAIL_N == 0 && WARN_N <= 3 )); then
    printf "\n  ${GRN}VERDICT: PRODUCTION READY${RST} (minor warnings only)\n"
elif (( FAIL_N == 0 )); then
    printf "\n  ${YEL}VERDICT: ACCEPTABLE${RST} (no failures, but review warnings)\n"
elif (( FAIL_N <= 3 )); then
    printf "\n  ${YEL}VERDICT: NEEDS ATTENTION${RST} (fix failures before deploying)\n"
else
    printf "\n  ${RED}VERDICT: NOT PRODUCTION READY${RST} (multiple failures)\n"
fi

echo "========================================================================"
echo ""
exit $FAIL_N
