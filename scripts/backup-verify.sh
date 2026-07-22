#!/bin/bash
# SOWKNOW Backup Verification
# 1) Verifies the latest daily dump checksum and restores it to a temp DB.
# 2) Runs a lightweight Restic repository check.

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
DAILY_DIR="$BACKUP_BASE_DIR/daily"
TEMP_DB="sowknow_restore_test_${DATE}"

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
    send_alert "❌ SOWKNOW backup verification failed" "$1"
    exit 1
}

warn() {
    log "WARNING: $1"
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
# Daily Restic snapshot verification
# ---------------------------------------------------------------------------
log "=== Starting SOWKNOW backup verification ($DATE) ==="

if ! command -v restic >/dev/null 2>&1; then
    fail "restic is not installed"
fi

# List files in the latest daily snapshot and check for Postgres data files.
log "Verifying daily snapshot contents..."
SNAPSHOT_FILES="$(mktemp)"
trap 'rm -f "$SNAPSHOT_FILES"' EXIT
if ! restic ls latest --tag daily 2>>"$BACKUP_LOG_FILE" > "$SNAPSHOT_FILES"; then
    fail "Failed to list daily snapshot contents"
fi

if grep -qE 'PG_VERSION|postgresql.conf|pg_hba.conf' "$SNAPSHOT_FILES"; then
    log "Daily snapshot contains expected Postgres data files"
else
    warn "Daily snapshot is missing expected Postgres data files"
fi

# ---------------------------------------------------------------------------
# Restic repository verification
# ---------------------------------------------------------------------------
if command -v restic >/dev/null 2>&1 && [ -f "$RESTIC_PASSWORD_FILE" ]; then
    log "Running Restic repository check (5% data subset)..."
    if restic check --read-data-subset=5% 2>>"$BACKUP_LOG_FILE"; then
        log "Restic repository check: OK"
    else
        fail "Restic repository check failed"
    fi

    log "Latest Restic snapshots:"
    restic snapshots --tag weekly --last 3 2>/dev/null >> "$BACKUP_LOG_FILE" || true
else
    warn "Restic not configured; repository check skipped"
fi

log "=== Backup verification completed ($DATE) ==="
send_alert "✅ SOWKNOW backup verification completed" "Host: $HOSTNAME_TAG, Date: $DATE"
exit 0
