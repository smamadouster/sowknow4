#!/bin/bash
# Guardian HC -- Quick Install for SOWKNOW4
set -e

PROJECT_DIR="${1:-/var/docker/sowknow4}"
echo "Guardian HC -- Installing for SOWKNOW4 at: $PROJECT_DIR"

# Install Python package
pip install -e . 2>/dev/null || pip install --break-system-packages -e . 2>/dev/null

# Copy config if none exists
if [ ! -f "$PROJECT_DIR/monitoring/guardian-hc/guardian-hc.sowknow4.yml" ]; then
    echo "Config already in place at monitoring/guardian-hc/guardian-hc.sowknow4.yml"
fi

# Install watchdog cron
bash scripts/install-watchdog.sh "$PROJECT_DIR"

echo ""
echo "Guardian HC installed for SOWKNOW4"
echo ""
echo "Next steps:"
echo "  1. Verify guardian-hc.sowknow4.yml config"
echo "  2. Run: docker compose --profile monitoring up -d"
echo "  3. Or standalone: guardian-hc run guardian-hc.sowknow4.yml"
