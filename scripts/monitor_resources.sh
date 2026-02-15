#!/bin/bash
# SOWKNOW Resource Monitoring Script
# Monitors container memory, VPS memory, and 5xx error rate
# Run via cron every 5 minutes: */5 * * * * /root/development/src/active/sowknow4/scripts/monitor_resources.sh

set -euo pipefail

ALERT_EMAIL="${ALERT_EMAIL:-admin@sowknow.local}"
WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"
ALERT_LOG="/var/log/sowknow-monitor.log"
SOWKNOW_MEMORY_THRESHOLD_MB=6144
VPS_MEMORY_THRESHOLD=80
ERROR_RATE_THRESHOLD=5

log_alert() {
    local level="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local log_entry="[$timestamp] [$level] $message"
    
    echo "$log_entry" | tee -a "$ALERT_LOG"
    
    if [ -n "$WEBHOOK_URL" ]; then
        send_webhook "$level" "$message"
    fi
    
    if [ -n "$ALERT_EMAIL" ]; then
        send_email "$level" "$message"
    fi
}

send_webhook() {
    local level="$1"
    local message="$2"
    local payload=$(cat <<EOF
{
    "text": "[SOWKNOW Alert] $level: $message",
    "attachments": [{
        "color": "$( [ "$level" = "CRITICAL" ] && echo "danger" || echo "warning" )",
        "fields": [
            {"title": "Alert Level", "value": "$level", "short": true},
            {"title": "Message", "value": "$message", "short": false}
        ]
    }]
}
EOF
)
    curl -sf -X POST -H "Content-Type: application/json" -d "$payload" "$WEBHOOK_URL" 2>/dev/null || true
}

send_email() {
    local level="$1"
    local message="$2"
    local subject="[SOWKNOW] $level Alert"
    echo "$message" | mail -s "$subject" "$ALERT_EMAIL" 2>/dev/null || true
}

get_sowknow_memory_mb() {
    local total_mem=0
    local containers
    
    containers=$(docker ps --filter "name=sowknow" --format "{{.Names}}" 2>/dev/null || echo "")
    
    if [ -z "$containers" ]; then
        echo "0"
        return
    fi
    
    for container in $containers; do
        local mem_usage
        mem_usage=$(docker stats --no-stream --format "{{.MemUsage}}" "$container" 2>/dev/null | awk -F'/' '{print $1}' | sed 's/[^0-9.]//g' || echo "0")
        if [ -n "$mem_usage" ] && [ "$mem_usage" != "0" ]; then
            total_mem=$(echo "$total_mem + $mem_usage" | bc -l 2>/dev/null || echo "$total_mem")
        fi
    done
    
    printf "%.0f" "$total_mem"
}

get_vps_memory_percent() {
    free | grep Mem | awk '{printf "%.1f", ($3/$2) * 100.0}'
}

get_5xx_error_rate() {
    local nginx_container="sowknow4-nginx"
    
    if ! docker ps --format "{{.Names}}" | grep -q "^${nginx_container}$"; then
        echo "0"
        return
    fi
    
    local total_requests
    local error_requests
    
    total_requests=$(docker logs "$nginx_container" --since 5m 2>&1 | grep -c 'HTTP/1.1"' || echo "0")
    error_requests=$(docker logs "$nginx_container" --since 5m 2>&1 | grep -cE 'HTTP/1.1" 5[0-9]{2}' || echo "0")
    
    if [ "$total_requests" -eq 0 ]; then
        echo "0"
        return
    fi
    
    local error_rate
    error_rate=$(echo "scale=2; $error_requests * 100 / $total_requests" | bc -l)
    printf "%.2f" "$error_rate"
}

check_sowknow_memory() {
    local mem_mb
    mem_mb=$(get_sowknow_memory_mb)
    
    echo "SOWKNOW Container Memory: ${mem_mb}MB (threshold: ${SOWKNOW_MEMORY_THRESHOLD_MB}MB)"
    
    if (( $(echo "$mem_mb > $SOWKNOW_MEMORY_THRESHOLD_MB" | bc -l 2>/dev/null || echo "0") )); then
        log_alert "WARNING" "SOWKNOW memory usage: ${mem_mb}MB (threshold: 6GB)"
        return 1
    fi
    
    return 0
}

check_vps_memory() {
    local mem_percent
    mem_percent=$(get_vps_memory_percent)
    
    echo "VPS Memory Usage: ${mem_percent}% (threshold: ${VPS_MEMORY_THRESHOLD}%)"
    
    if (( $(echo "$mem_percent > $VPS_MEMORY_THRESHOLD" | bc -l 2>/dev/null || echo "0") )); then
        log_alert "CRITICAL" "VPS memory usage: ${mem_percent}% (threshold: ${VPS_MEMORY_THRESHOLD}%)"
        return 1
    fi
    
    return 0
}

check_error_rate() {
    local error_rate
    error_rate=$(get_5xx_error_rate)
    
    echo "5xx Error Rate (5min): ${error_rate}% (threshold: ${ERROR_RATE_THRESHOLD}%)"
    
    if (( $(echo "$error_rate > $ERROR_RATE_THRESHOLD" | bc -l 2>/dev/null || echo "0") )); then
        log_alert "CRITICAL" "5xx error rate: ${error_rate}% (threshold: ${ERROR_RATE_THRESHOLD}%)"
        return 1
    fi
    
    return 0
}

main() {
    echo "=== SOWKNOW Resource Monitor - $(date) ==="
    
    local exit_code=0
    
    echo ""
    echo "--- Container Memory ---"
    check_sowknow_memory || exit_code=1
    
    echo ""
    echo "--- VPS Memory ---"
    check_vps_memory || exit_code=1
    
    echo ""
    echo "--- Error Rate ---"
    check_error_rate || exit_code=1
    
    echo ""
    echo "=== Monitor Complete ==="
    
    exit $exit_code
}

main "$@"
