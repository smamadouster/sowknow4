#!/bin/bash
# Log rotation script for SOWKNOW
# Run this via cron or manually

set -e

LOG_DIR="/root/development/src/active/sowknow4/logs"
ARCHIVE_DIR="$LOG_DIR/archive"
RETENTION_DAYS=30

# Create directories
mkdir -p "$LOG_DIR/app" "$LOG_DIR/celery" "$LOG_DIR/nginx" "$ARCHIVE_DIR"

echo "========================================="
echo "SOWKNOW Log Rotation"
echo "========================================="
echo "Log directory: $LOG_DIR"
echo "Archive directory: $ARCHIVE_DIR"
echo "Retention days: $RETENTION_DAYS"
echo ""

# Function to rotate logs
rotate_logs() {
    local log_dir=$1
    local pattern=$2

    if [ -d "$log_dir" ]; then
        # Find and rotate logs
        find "$log_dir" -name "$pattern" -type f -size +10M | while read log_file; do
            timestamp=$(date +%Y%m%d_%H%M%S)
            base_name=$(basename "$log_file")
            archive_file="$ARCHIVE_DIR/${base_name}.$timestamp.gz"

            echo "Rotating: $log_file -> $archive_file"
            gzip -c "$log_file" > "$archive_file"
            > "$log_file"  # Truncate original file
        done
    fi
}

# Rotate application logs
echo "Rotating application logs..."
rotate_logs "$LOG_DIR/app" "*.log"

# Rotate celery logs
echo "Rotating celery logs..."
rotate_logs "$LOG_DIR/celery" "*.log"

# Rotate nginx logs
echo "Rotating nginx logs..."
rotate_logs "$LOG_DIR/nginx" "*.log"

# Clean old archived logs
echo ""
echo "Cleaning old archives (older than $RETENTION_DAYS days)..."
find "$ARCHIVE_DIR" -name "*.gz" -type f -mtime +$RETENTION_DAYS -delete

# Show disk usage
echo ""
echo "Disk usage:"
du -sh "$LOG_DIR"/* 2>/dev/null || true
du -sh "$ARCHIVE_DIR" 2>/dev/null || true

echo ""
echo "✅ Log rotation complete!"
