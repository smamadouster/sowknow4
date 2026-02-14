#!/bin/bash
# SOWKNOW Alert Monitoring Script
# Checks alerts via backend API and sends notifications
# Run this via cron: */5 * * * * /root/development/src/active/sowknow4/scripts/monitor-alerts.sh

set -e

API_URL="${API_URL:-http://localhost:8000}"
ALERT_LOG="/var/log/sowknow-alerts.log"
MAX_LOG_SIZE=10485760

log_alert() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] $message" | tee -a "$ALERT_LOG"
    
    # Rotate log if too large
    if [ -f "$ALERT_LOG" ] && [ $(stat -f%z "$ALERT_LOG" 2>/dev/null || stat -c%s "$ALERT_LOG" 2>/dev/null) -gt $MAX_LOG_SIZE ]; then
        mv "$ALERT_LOG" "${ALERT_LOG}.old"
    fi
}

check_service() {
    local name="$1"
    local url="$2"
    
    if curl -sf "$url" > /dev/null 2>&1; then
        echo "OK"
    else
        echo "FAIL"
    fi
}

# Check API health first
echo "=== SOWKNOW Alert Monitor - $(date) ==="

HEALTH_RESPONSE=$(curl -sf "${API_URL}/health" 2>/dev/null || echo '{}')

if echo "$HEALTH_RESPONSE" | grep -q '"status": "healthy"'; then
    echo "API: OK"
else
    log_alert "CRITICAL: Backend API unhealthy or unreachable"
    exit 1
fi

# Get system metrics
echo ""
echo "--- System Metrics ---"
SYSTEM_METRICS=$(curl -sf "${API_URL}/api/v1/monitoring/system" 2>/dev/null || echo '{}')

if command -v jq > /dev/null 2>&1; then
    MEM_PERCENT=$(echo "$SYSTEM_METRICS" | jq -r '.monitoring.memory.percent // 0')
    DISK_PERCENT=$(echo "$SYSTEM_METRICS" | jq -r '.monitoring.disk.percent // 0')
    
    echo "Memory: ${MEM_PERCENT}%"
    echo "Disk: ${DISK_PERCENT}%"
    
    # Check memory threshold (PRD: >80% = CRITICAL)
    if (( $(echo "$MEM_PERCENT > 80" | bc -l 2>/dev/null || echo "0") )); then
        log_alert "CRITICAL: VPS memory at ${MEM_PERCENT}% (threshold: 80%)"
    fi
    
    # Check disk threshold (PRD: >85% = CRITICAL)
    if (( $(echo "$DISK_PERCENT > 85" | bc -l 2>/dev/null || echo "0") )); then
        log_alert "CRITICAL: Disk usage at ${DISK_PERCENT}% (threshold: 85%)"
    fi
else
    echo "jq not available, skipping detailed metrics"
fi

# Get queue depth
echo ""
echo "--- Queue Status ---"
QUEUE_METRICS=$(curl -sf "${API_URL}/api/v1/monitoring/queue" 2>/dev/null || echo '{}')

if command -v jq > /dev/null 2>&1; then
    QUEUE_DEPTH=$(echo "$QUEUE_METRICS" | jq -r '.queue_depth // 0')
    echo "Queue Depth: $QUEUE_DEPTH"
    
    # Check queue threshold (PRD: >100 = WARNING)
    if [ "$QUEUE_DEPTH" -gt 100 ] 2>/dev/null; then
        log_alert "WARNING: Celery queue depth at $QUEUE_DEPTH (threshold: 100)"
    fi
fi

# Get active alerts
echo ""
echo "--- Active Alerts ---"
ALERTS=$(curl -sf "${API_URL}/api/v1/monitoring/alerts" 2>/dev/null || echo '[]')

if command -v jq > /dev/null 2>&1; then
    ALERT_COUNT=$(echo "$ALERTS" | jq 'length')
    echo "Active Alerts: $ALERT_COUNT"
    
    if [ "$ALERT_COUNT" -gt 0 ]; then
        echo "$ALERTS" | jq -r '.[] | "  - \(.name): \(.threshold)"'
        log_alert "ALERT: $ALERT_COUNT active monitoring alerts"
    fi
else
    echo "Active Alerts: (jq not available)"
fi

# Check error rate (5xx errors)
echo ""
echo "--- Error Rate ---"
ERROR_RATE=$(curl -sf "${API_URL}/api/v1/monitoring/system" 2>/dev/null | jq -r '.error_rate // 0' 2>/dev/null || echo "0")
echo "Error Rate: ${ERROR_RATE}%"

# PRD: >5% error rate = CRITICAL
if command -v bc > /dev/null 2>&1 && (( $(echo "$ERROR_RATE > 5" | bc -l 2>/dev/null || echo "0") )); then
    log_alert "CRITICAL: 5xx error rate at ${ERROR_RATE}% (threshold: 5%)"
fi

echo ""
echo "=== Monitoring Complete ==="
