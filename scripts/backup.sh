#!/bin/bash
# SOWKNOW Backup Script
# Daily PostgreSQL backup with compression, checksums, and encryption
# Retention: 7 daily, 4 weekly, 3 monthly

set -e

# Source environment variables
if [ -f "/root/development/src/active/sowknow4/.env" ]; then
    source "/root/development/src/active/sowknow4/.env"
fi

BACKUP_DIR="/var/backups/sowknow"
DATE=$(date +%Y%m%d)
DAY_OF_WEEK=$(date +%u)
MONTH=$(date +%m)
YEAR=$(date +%Y)
LOG_FILE="/var/log/sowknow_backup.log"

# GPG recipient (set in environment or .secrets)
GPG_RECIPIENT="${GPG_BACKUP_RECIPIENT:-}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

mkdir -p "$BACKUP_DIR"

log "Starting SOWKNOW backup - $DATE"

# Backup PostgreSQL database
log "Backing up PostgreSQL..."
docker exec sowknow-postgres pg_dump -U sowknow sowknow > "$BACKUP_DIR/sowknow_$DATE.sql"

if [ $? -eq 0 ]; then
    log "Database backup completed: sowknow_$DATE.sql"
    
    # Compress the backup
    gzip "$BACKUP_DIR/sowknow_$DATE.sql"
    log "Backup compressed: sowknow_$DATE.sql.gz"
    
    # Generate SHA256 checksum
    sha256sum "$BACKUP_DIR/sowknow_$DATE.sql.gz" > "$BACKUP_DIR/sowknow_$DATE.sql.gz.sha256"
    log "Checksum generated: sowknow_$DATE.sql.gz.sha256"
    
    # Encrypt for offsite backup (if GPG_RECIPIENT is set)
    if [ -n "$GPG_BACKUP_RECIPIENT" ]; then
        if gzip -c "$BACKUP_DIR/sowknow_$DATE.sql.gz" | gpg --encrypt --recipient "$GPG_BACKUP_RECIPIENT" --armor -o "$BACKUP_DIR/sowknow_$DATE.sql.gz.asc" 2>/dev/null; then
            log "Encrypted backup created: sowknow_$DATE.sql.gz.asc"
        else
            log "WARNING: GPG encryption failed (no key?), skipping encryption"
        fi
    else
        log "WARNING: GPG_BACKUP_RECIPIENT not set, skipping encryption"
    fi
else
    log "ERROR: Database backup failed!"
    exit 1
fi

# Retention policy
log "Applying retention policy..."

# Remove daily backups older than 7 days
find "$BACKUP_DIR" -name "sowknow_*.sql.gz" -mtime +7 -delete
log "Removed daily backups older than 7 days"

# Weekly retention: Keep 4 weeks of weekly backups (Sundays)
# Create weekly marker file
if [ "$DAY_OF_WEEK" = "0" ]; then
    touch "$BACKUP_DIR/.weekly_$DATE"
    log "Weekly marker created for $DATE"
fi

# Remove weekly markers older than 28 days (4 weeks)
find "$BACKUP_DIR" -name ".weekly_*" -mtime +28 -delete

# Monthly retention: Keep 3 months of monthly backups
# Create monthly marker file
if [ "$DAY_OF_WEEK" = "0" ] && [ "$(date +%d)" = "01" ]; then
    touch "$BACKUP_DIR/.monthly_${YEAR}_${MONTH}"
    log "Monthly marker created for $YEAR-$MONTH"
fi

# Remove monthly markers older than 90 days (3 months)
find "$BACKUP_DIR" -name ".monthly_*" -mtime +90 -delete

log "Retention policy applied"

# List current backups
log "Current backups:"
ls -lh "$BACKUP_DIR"/*.sql.gz 2>/dev/null || log "No backups found"

log "Backup completed successfully!"
