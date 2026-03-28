#!/bin/bash
###############################################################################
# Install the SOWKNOW4 External Watchdog on the HOST
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${1:-/var/docker/sowknow4}"
WATCHDOG="$SCRIPT_DIR/watchdog.sh"

echo "Installing SOWKNOW4 External Watchdog"
echo "  Project: $PROJECT_DIR"
echo "  Watchdog: $WATCHDOG"
echo ""

chmod +x "$WATCHDOG"

CRON_LINE="*/2 * * * * SOWKNOW4_DIR=$PROJECT_DIR $WATCHDOG >> /var/log/sowknow4-watchdog.log 2>&1"

# Remove existing entry (idempotent)
crontab -l 2>/dev/null | grep -v "sowknow4-watchdog\|watchdog.sh.*sowknow4" | crontab -

# Add new entry
(crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -

echo "Watchdog installed in crontab (runs every 2 minutes)"
echo ""
echo "Verify: crontab -l | grep watchdog"
echo "Logs:   tail -f /var/log/sowknow4-watchdog.log"
echo ""

echo "Running initial check..."
SOWKNOW4_DIR="$PROJECT_DIR" bash "$WATCHDOG"
echo ""
echo "Done. The watchdog is now active."
