#!/bin/bash
# Test script for monitor_resources.sh thresholds

set -euo pipefail

SCRIPT="/root/development/src/active/sowknow4/scripts/monitor_resources.sh"
TEST_LOG="/tmp/monitor-test.log"

echo "=== Testing monitor_resources.sh ==="

echo ""
echo "1. Testing SOWKNOW memory threshold (6GB = 6144MB)"
echo "   Current threshold: 6144MB"
echo "   Test: Check that threshold is correctly set"
grep -q "SOWKNOW_MEMORY_THRESHOLD_MB=6144" "$SCRIPT" && echo "   PASS: SOWKNOW memory threshold is 6144MB" || echo "   FAIL: Wrong threshold"

echo ""
echo "2. Testing VPS memory threshold (80%)"
echo "   Current threshold: 80%"
echo "   Test: Check that threshold is correctly set"
grep -q "VPS_MEMORY_THRESHOLD=80" "$SCRIPT" && echo "   PASS: VPS memory threshold is 80%" || echo "   FAIL: Wrong threshold"

echo ""
echo "3. Testing 5xx error rate threshold (5%)"
echo "   Current threshold: 5%"
echo "   Test: Check that threshold is correctly set"
grep -q "ERROR_RATE_THRESHOLD=5" "$SCRIPT" && echo "   PASS: Error rate threshold is 5%" || echo "   FAIL: Wrong threshold"

echo ""
echo "4. Testing cron job entry exists"
grep -q "monitor_resources.sh" /root/development/src/active/sowknow4/scripts/crontab.example && echo "   PASS: Cron job entry exists" || echo "   FAIL: No cron job entry"

echo ""
echo "5. Testing Prometheus service in docker-compose"
grep -q "sowknow4-prometheus" /root/development/src/active/sowknow4/docker-compose.yml && echo "   PASS: Prometheus service defined" || echo "   FAIL: No Prometheus service"

echo ""
echo "6. Testing Prometheus config exists"
[ -f /root/development/src/active/sowknow4/monitoring/prometheus.yml ] && echo "   PASS: Prometheus config exists" || echo "   FAIL: No Prometheus config"

echo ""
echo "7. Running actual monitoring script"
bash "$SCRIPT" > "$TEST_LOG" 2>&1 || true
echo "   Output:"
cat "$TEST_LOG" | sed 's/^/   /'

echo ""
echo "=== All Tests Complete ==="
