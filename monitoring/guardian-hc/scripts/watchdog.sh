#!/bin/bash
###############################################################################
# SOWKNOW4 External Watchdog
#
# Runs OUTSIDE Docker (via cron on the HOST).
# Checks whether the Docker stack itself is healthy and fixes it.
#
# Install on HOST:
#   crontab -e
#   */2 * * * * /var/docker/sowknow4/monitoring/guardian-hc/scripts/watchdog.sh >> /var/log/sowknow4-watchdog.log 2>&1
###############################################################################

set -uo pipefail

# -- Config --
PROJECT_DIR="${SOWKNOW4_DIR:-/var/docker/sowknow4}"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
LOG_FILE="/var/log/sowknow4-watchdog.log"
MAX_LOG_SIZE=5242880  # 5MB

# Telegram alerting (env vars or .env file)
TELEGRAM_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
if [ -z "$TELEGRAM_TOKEN" ] && [ -f "$PROJECT_DIR/.env" ]; then
    TELEGRAM_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d'=' -f2 | tr -d '\n"' )
fi
if [ -z "$TELEGRAM_CHAT_ID" ] && [ -f "$PROJECT_DIR/.env" ]; then
    TELEGRAM_CHAT_ID=$(grep '^TELEGRAM_ADMIN_CHAT_ID=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d'=' -f2 | tr -d '\n"' )
fi

# All SOWKNOW4 containers (sowknow4- prefix per naming convention)
EXPECTED_CONTAINERS="sowknow4-backend sowknow4-postgres sowknow4-redis sowknow4-vault sowknow4-nats sowknow4-celery-worker sowknow4-celery-beat sowknow4-frontend sowknow4-telegram-bot"

# -- Helpers --
timestamp() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(timestamp)] $1"; }

alert() {
    local msg="$1"
    log "ALERT: $msg"
    if [ -n "$TELEGRAM_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "text=*Watchdog Alert | SOWKNOW4*

${msg}" \
            -d "parse_mode=Markdown" \
            --max-time 10 > /dev/null 2>&1
    fi
}

alert_healed() {
    local msg="$1"
    log "HEALED: $msg"
    # Successful self-heals are logged only -- no Telegram notification.
    # Only unresolved failures (via alert()) go to Telegram.
}

# -- Check 1: Are all containers running? --
check_containers() {
    local running=$(docker ps --format '{{.Names}}' 2>/dev/null)
    local missing=""
    local restarted=""

    for container in $EXPECTED_CONTAINERS; do
        if ! echo "$running" | grep -q "^${container}$"; then
            missing="$missing $container"
        fi
    done

    if [ -n "$missing" ]; then
        log "Missing containers:$missing"

        cd "$PROJECT_DIR"
        docker compose up -d 2>&1 | tail -5
        sleep 10

        local still_missing=""
        running=$(docker ps --format '{{.Names}}' 2>/dev/null)
        for container in $missing; do
            if echo "$running" | grep -q "^${container}$"; then
                restarted="$restarted $container"
            else
                still_missing="$still_missing $container"
            fi
        done

        if [ -n "$restarted" ]; then
            alert_healed "Restarted containers:$restarted"
        fi
        if [ -n "$still_missing" ]; then
            alert "Containers STILL DOWN after restart:$still_missing

Possible causes:
- Docker image build error
- Missing .env or secrets
- Port conflicts

Fix: cd $PROJECT_DIR && docker compose build --no-cache && docker compose up -d"
        fi
    fi
}

# -- Check 2: Is the backend API responding? --
check_api() {
    local resp=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://localhost:8001/api/v1/health 2>/dev/null)

    if [ "$resp" != "200" ]; then
        log "Backend API not responding (HTTP $resp)"

        local api_running=$(docker ps --format '{{.Names}}' 2>/dev/null | grep "^sowknow4-backend$")

        if [ -n "$api_running" ]; then
            log "Backend container running but not responding. Restarting..."
            cd "$PROJECT_DIR"
            docker compose restart backend 2>&1
            sleep 15

            resp=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://localhost:8001/api/v1/health 2>/dev/null)
            if [ "$resp" = "200" ]; then
                alert_healed "Backend API was unresponsive. Restarted container. Now healthy."
            else
                log "Backend still broken after restart. Attempting rebuild..."
                docker compose build --no-cache backend 2>&1 | tail -5
                docker compose up -d backend 2>&1
                sleep 20

                resp=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://localhost:8001/api/v1/health 2>/dev/null)
                if [ "$resp" = "200" ]; then
                    alert_healed "Backend API was broken. Rebuilt image + restarted. Now healthy."
                else
                    alert "Backend API STILL DOWN after rebuild.

HTTP status: $resp
Check logs: docker compose logs --tail=50 backend"
                fi
            fi
        else
            log "Backend container not running (handled by check_containers)"
        fi
    fi
}

# -- Check 3: Is the Celery worker healthy? --
check_worker() {
    local worker_running=$(docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | grep "sowknow4-celery-worker")

    if [ -z "$worker_running" ]; then
        log "Celery worker not running (handled by check_containers)"
        return
    fi

    if echo "$worker_running" | grep -qi "restarting"; then
        log "Celery worker is in restart loop"

        local last_log=$(docker compose -f "$COMPOSE_FILE" logs --tail=20 celery-worker 2>/dev/null | tail -10)

        alert "Celery worker in restart loop.

Last logs:
$(echo "$last_log" | head -5)

Common causes:
- Missing Python dependencies
- Embedding model download failure
- Database connection error

Fix: docker compose build --no-cache celery-worker && docker compose up -d celery-worker"
    fi
}

# -- Check 4: Disk critical? --
check_disk() {
    local usage=$(df / --output=pcent | tail -1 | tr -d ' %')

    if [ "$usage" -gt 90 ]; then
        log "DISK CRITICAL: ${usage}%"

        journalctl --vacuum-size=50M 2>/dev/null
        docker system prune -f 2>/dev/null
        find /var/log -name "*.log" -size +50M -delete 2>/dev/null
        apt-get clean 2>/dev/null

        local new_usage=$(df / --output=pcent | tail -1 | tr -d ' %')

        if [ "$new_usage" -lt 85 ]; then
            alert_healed "Disk was at ${usage}%. Emergency cleanup. Now ${new_usage}%."
        else
            alert "Disk at ${new_usage}% AFTER cleanup (was ${usage}%).

Manual intervention needed. Consider:
- Moving old backups
- Clearing Docker volumes
- Adding storage"
        fi
    fi
}

# -- Check 5: Docker daemon alive? --
check_docker_daemon() {
    if ! docker info > /dev/null 2>&1; then
        log "Docker daemon not responding!"

        systemctl restart docker 2>&1
        sleep 10

        if docker info > /dev/null 2>&1; then
            cd "$PROJECT_DIR"
            docker compose up -d 2>&1
            alert_healed "Docker daemon was unresponsive. Restarted Docker + all containers."
        else
            alert "Docker daemon STILL DOWN after restart.

This requires manual SSH access to the server.
Try: systemctl status docker"
        fi
    fi
}

# -- Check 6: Log rotation --
rotate_log() {
    if [ -f "$LOG_FILE" ]; then
        local size=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
        if [ "$size" -gt "$MAX_LOG_SIZE" ]; then
            mv "$LOG_FILE" "${LOG_FILE}.old"
            log "Watchdog log rotated (was ${size} bytes)"
        fi
    fi
}

# -- Main --
main() {
    check_docker_daemon

    if ! docker info > /dev/null 2>&1; then
        return 1
    fi

    check_containers
    check_api
    check_worker
    check_disk
    rotate_log
}

main
