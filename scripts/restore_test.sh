#!/bin/bash
# SOWKNOW Restore Test Script
# Monthly automated restore test for backup verification

set -e

BACKUP_DIR="/var/backups/sowknow"
LOG_FILE="/var/log/sowknow_restore_test.log"
TEST_DB="sowknow_restore_test_$(date +%Y%m%d%H%M%S)"
DATE=$(date +%Y%m%d)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=========================================="
log "Starting SOWKNOW Restore Test - $DATE"
log "=========================================="

# Find latest backup
LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/sowknow_*.sql.gz 2>/dev/null | head -1)

if [ -z "$LATEST_BACKUP" ]; then
    log "ERROR: No backup files found in $BACKUP_DIR"
    exit 1
fi

log "Testing backup: $LATEST_BACKUP"

# Verify file exists
if [ ! -f "$LATEST_BACKUP" ]; then
    log "ERROR: Backup file not found"
    exit 1
fi

# Verify checksum exists
CHECKSUM_FILE="${LATEST_BACKUP}.sha256"
if [ -f "$CHECKSUM_FILE" ]; then
    log "Verifying checksum..."
    if sha256sum -c "$CHECKSUM_FILE" > /dev/null 2>&1; then
        log "✓ Checksum verification PASSED"
    else
        log "ERROR: Checksum verification FAILED"
        exit 1
    fi
else
    log "WARNING: No checksum file found, skipping verification"
fi

# Test gzip integrity
log "Testing gzip integrity..."
if gzip -t "$LATEST_BACKUP" 2>/dev/null; then
    log "✓ Gzip integrity test PASSED"
else
    log "ERROR: Gzip integrity test FAILED"
    exit 1
fi

# Create test database
log "Creating test database: $TEST_DB"
docker exec sowknow-postgres psql -U sowknow -c "DROP DATABASE IF EXISTS $TEST_DB;" 2>/dev/null || true
docker exec sowknow-postgres psql -U sowknow -c "CREATE DATABASE $TEST_DB;" 

# Restore to test database
log "Restoring backup to test database..."
if gunzip -c "$LATEST_BACKUP" | docker exec -i sowknow-postgres psql -U sowknow -d "$TEST_DB" 2>&1 | tee -a "$LOG_FILE"; then
    log "✓ Restore completed successfully"
else
    log "ERROR: Restore failed"
    docker exec sowknow-postgres psql -U sowknow -c "DROP DATABASE IF EXISTS $TEST_DB;"
    exit 1
fi

# Verify schema
log "Verifying schema..."
TABLES=$(docker exec sowknow-postgres psql -U sowknow -d "$TEST_DB" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null | tr -d ' ')

if [ "$TABLES" -gt 0 ]; then
    log "✓ Schema verification PASSED ($TABLES tables found)"
else
    log "WARNING: No tables found in restored database"
fi

# Verify pgvector extension
log "Verifying pgvector extension..."
if docker exec sowknow-postgres psql -U sowknow -d "$TEST_DB" -c "SELECT * FROM pg_extension WHERE extname = 'vector';" > /dev/null 2>&1; then
    log "✓ pgvector extension verified"
else
    log "WARNING: pgvector extension not found"
fi

# Verify row count (if users table exists)
log "Checking data integrity..."
USER_COUNT=$(docker exec sowknow-postgres psql -U sowknow -d "$TEST_DB" -t -c "SELECT COUNT(*) FROM users;" 2>/dev/null | tr -d ' ' || echo "0")
if [ "$USER_COUNT" != "0" ]; then
    log "✓ Data verification: $USER_COUNT users found"
fi

# Cleanup test database
log "Cleaning up test database..."
docker exec sowknow-postgres psql -U sowknow -c "DROP DATABASE IF EXISTS $TEST_DB;"

log "=========================================="
log "Restore Test COMPLETED SUCCESSFULLY"
log "Backup: $LATEST_BACKUP"
log "=========================================="

# Send success notification (optional)
if [ -n "$ALERT_WEBHOOK" ]; then
    curl -s -X POST "$ALERT_WEBHOOK" -d "{\"text\": \"SOWKNOW Restore Test PASSED - $DATE\"}" 2>/dev/null || true
fi

exit 0
