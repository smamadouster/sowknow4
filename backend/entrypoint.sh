#!/bin/sh
set -e

# Fix permissions for backup directory
if [ -d /app/backups ]; then
    chmod -R 777 /app/backups 2>/dev/null || true
fi

# Execute main command
exec "$@"
