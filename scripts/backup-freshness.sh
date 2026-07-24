#!/bin/bash
# SOWKNOW Backup Freshness Check
# Alerts when the newest daily Restic snapshot is older than 25 hours —
# a backup job that silently stops (wrong cron path Feb–Jul 2026, found
# 2026-07-24) is indistinguishable from a working one until restore day.

set -euo pipefail

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
load_env_file "$PROJECT_ROOT/.env"
load_env_file "$PROJECT_ROOT/.secrets"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/.backup.env"

BACKUP_TELEGRAM_CHAT_ID="${BACKUP_TELEGRAM_CHAT_ID:-${TELEGRAM_CHAT_ID:-${TELEGRAM_ADMIN_CHAT_ID:-}}}"
BACKUP_ALERT_EMAIL_FROM="${BACKUP_ALERT_EMAIL_FROM:-${ALERT_FROM_EMAIL:-}}"
BACKUP_ALERT_EMAIL_TO="${BACKUP_ALERT_EMAIL_TO:-${ADMIN_EMAILS:-}}"
FRESHNESS_LIMIT_HOURS="${BACKUP_FRESHNESS_LIMIT_HOURS:-25}"

export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE

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

latest_epoch="$(restic snapshots --tag daily --json --no-lock 2>/dev/null \
    | python3 -c "import json,sys; s=json.load(sys.stdin); print(int(__import__('datetime').datetime.fromisoformat(max(x['time'] for x in s).replace('Z','+00:00')).timestamp()))" \
    2>/dev/null || echo 0)"

if [ "$latest_epoch" = "0" ]; then
    send_alert "🔴 SOWKNOW backup freshness: NO daily snapshot found" \
        "restic snapshots --tag daily returned nothing on $(hostname -s). The backup pipeline is broken."
    exit 1
fi

now_epoch="$(date +%s)"
age_hours=$(( (now_epoch - latest_epoch) / 3600 ))

if [ "$age_hours" -gt "$FRESHNESS_LIMIT_HOURS" ]; then
    send_alert "🔴 SOWKNOW backup stale: ${age_hours}h since last daily snapshot" \
        "Limit is ${FRESHNESS_LIMIT_HOURS}h on $(hostname -s). Check /etc/cron.d/sowknow and /var/log/sowknow/backup.log."
    exit 1
fi

exit 0
