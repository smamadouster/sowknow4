#!/bin/bash
# SOWKNOW Weekly Full Backup
# Creates an encrypted, deduplicated Restic snapshot of:
#   - the daily dump directory (consistent database)
#   - critical Docker volumes
#   - host configuration files
# Then applies weekly retention.

set -euo pipefail

# ---------------------------------------------------------------------------
# Locate project root and load configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Safely load KEY=VALUE pairs from an env file without executing commands.
load_env_file() {
    local file="$1"
    local line key value
    [ -f "$file" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            ''|\#*) continue ;;
        esac
        case "$line" in
            *=*) ;;
            *) continue ;;
        esac
        key="${line%%=*}"
        value="${line#*=}"
        key="$(echo "$key" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        case "$key" in
            [A-Za-z_][A-Za-z0-9_]*) ;;
            *) continue ;;
        esac
        value="$(echo "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        case "$value" in
            \"*\") value="${value#\"}"; value="${value%\"}" ;;
            \'*\') value="${value#\'}"; value="${value%\'}" ;;
        esac
        export "$key=$value"
    done < "$file"
}

# shellcheck source=/dev/null
source "$SCRIPT_DIR/.backup.env"

# Load project secrets safely.
load_env_file "$PROJECT_ROOT/.env"
load_env_file "$PROJECT_ROOT/.secrets"

# Re-source backup env so backup-specific overrides take precedence.
# shellcheck source=/dev/null
source "$SCRIPT_DIR/.backup.env"

# ---------------------------------------------------------------------------
# Resolve final values
# ---------------------------------------------------------------------------
BACKUP_TELEGRAM_CHAT_ID="${BACKUP_TELEGRAM_CHAT_ID:-${TELEGRAM_CHAT_ID:-${TELEGRAM_ADMIN_CHAT_ID:-}}}"
BACKUP_ALERT_EMAIL_FROM="${BACKUP_ALERT_EMAIL_FROM:-${ALERT_FROM_EMAIL:-}}"
BACKUP_ALERT_EMAIL_TO="${BACKUP_ALERT_EMAIL_TO:-${ADMIN_EMAILS:-}}"

DATE="$(date +%Y%m%d)"
DATETIME="$(date '+%Y-%m-%d %H:%M:%S')"
HOSTNAME_TAG="$(hostname -s)"
RETENTION_WEEKS="${BACKUP_WEEKLY_RETENTION_WEEKS:-4}"

export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE

# ---------------------------------------------------------------------------
# Logging and alerting helpers
# ---------------------------------------------------------------------------
log() {
    mkdir -p "$BACKUP_LOG_DIR"
    echo "[$DATETIME] $1" | tee -a "$BACKUP_LOG_FILE"
}

fail() {
    log "ERROR: $1"
    send_alert "❌ SOWKNOW weekly full backup failed" "$1"
    exit 1
}

send_alert() {
    local subject="$1"
    local body="$2"

    if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${BACKUP_TELEGRAM_CHAT_ID:-}" ]; then
        curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${BACKUP_TELEGRAM_CHAT_ID}" \
            -d "text=${subject}%0A${body}" \
            -d "parse_mode=HTML" >/dev/null 2>&1 || true
    fi

    if [ -n "$BACKUP_ALERT_EMAIL_FROM" ] && [ -n "$BACKUP_ALERT_EMAIL_TO" ] && command -v sendmail >/dev/null 2>&1; then
        {
            echo "From: $BACKUP_ALERT_EMAIL_FROM"
            echo "To: $BACKUP_ALERT_EMAIL_TO"
            echo "Subject: $subject"
            echo ""
            echo "$body"
        } | sendmail -t || true
    fi
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
log "=== Starting SOWKNOW weekly full backup ($DATE) ==="

if ! command -v restic >/dev/null 2>&1; then
    fail "restic is not installed"
fi

mkdir -p "$BACKUP_BASE_DIR"

# ---------------------------------------------------------------------------
# Restic password file
# ---------------------------------------------------------------------------
if [ ! -f "$RESTIC_PASSWORD_FILE" ]; then
    mkdir -p "$(dirname "$RESTIC_PASSWORD_FILE")"
    openssl rand -base64 48 > "$RESTIC_PASSWORD_FILE"
    chmod 600 "$RESTIC_PASSWORD_FILE"
    log "Generated Restic password file: $RESTIC_PASSWORD_FILE"
fi

# ---------------------------------------------------------------------------
# Initialize repository if needed
# ---------------------------------------------------------------------------
if ! restic snapshots >/dev/null 2>&1; then
    log "Initializing Restic repository at $RESTIC_REPOSITORY..."
    if ! restic init; then
        fail "Failed to initialize Restic repository"
    fi
    log "Repository initialized"
fi

# ---------------------------------------------------------------------------
# Build backup target list
# ---------------------------------------------------------------------------
BACKUP_TARGETS=()

# Daily dumps (the consistent database backup).
if [ -d "$BACKUP_BASE_DIR/daily" ]; then
    BACKUP_TARGETS+=("$BACKUP_BASE_DIR/daily")
fi

# Docker volumes at their host mountpoints.
DOCKER_VOLUME_ROOT="/var/lib/docker/volumes"
for vol in $BACKUP_FULL_VOLUMES; do
    vol_path="$DOCKER_VOLUME_ROOT/${vol}/_data"
    if [ -d "$vol_path" ]; then
        BACKUP_TARGETS+=("$vol_path")
    else
        log "WARNING: Docker volume path not found, skipping: $vol_path"
    fi
done

# Host configuration paths relative to project root.
for rel_path in $BACKUP_FULL_HOST_PATHS; do
    host_path="$PROJECT_ROOT/$rel_path"
    if [ -e "$host_path" ]; then
        BACKUP_TARGETS+=("$host_path")
    else
        log "WARNING: Host path not found, skipping: $host_path"
    fi
done

if [ ${#BACKUP_TARGETS[@]} -eq 0 ]; then
    fail "No backup targets found"
fi

log "Backup targets: ${BACKUP_TARGETS[*]}"

# ---------------------------------------------------------------------------
# Run backup
# ---------------------------------------------------------------------------
log "Running Restic backup..."
if ! restic backup \
    --tag "weekly" \
    --tag "host:$HOSTNAME_TAG" \
    --tag "date:$DATE" \
    --exclude-if-present .nobackup \
    --exclude '**/.cache' \
    --exclude '**/node_modules' \
    --exclude '**/__pycache__' \
    --exclude '**/tmp/*' \
    --exclude '*.log' \
    "${BACKUP_TARGETS[@]}" 2>>"$BACKUP_LOG_FILE"; then
    fail "Restic backup failed"
fi

# ---------------------------------------------------------------------------
# Apply retention
# ---------------------------------------------------------------------------
log "Applying retention: keeping $RETENTION_WEEKS weekly snapshots..."
if ! restic forget --tag weekly --keep-weekly "$RETENTION_WEEKS" --prune 2>>"$BACKUP_LOG_FILE"; then
    log "WARNING: Restic forget/prune failed"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
SNAPSHOT_COUNT="$(restic snapshots --tag weekly --json 2>/dev/null | grep -c '"time"' || echo 0)"
log "Weekly full backup completed successfully. Weekly snapshots: $SNAPSHOT_COUNT"
log "Latest snapshots:"
restic snapshots --tag weekly --last 3 2>/dev/null >> "$BACKUP_LOG_FILE" || true

send_alert "✅ SOWKNOW weekly full backup completed" "Host: $HOSTNAME_TAG, Date: $DATE, Weekly snapshots: $SNAPSHOT_COUNT"
exit 0
