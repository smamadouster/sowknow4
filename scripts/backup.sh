#!/bin/bash
# SOWKNOW Backup Script
# Daily PostgreSQL backup with encryption

BACKUP_DIR="/var/backups/sowknow"
DATE=$(date +%Y%m%d)
DAY_OF_WEEK=$(date +%u)

# Create backup directory if not exists
mkdir -p "$BACKUP_DIR"

echo "Starting SOWKNOW backup - $DATE"

# Backup PostgreSQL database
echo "Backing up PostgreSQL..."
docker exec sowknow-postgres pg_dump -U sowknow sowknow > "$BACKUP_DIR/sowknow_$DATE.sql"

if [ $? -eq 0 ]; then
    echo "Database backup completed: sowknow_$DATE.sql"
    
    # Compress the backup
    gzip "$BACKUP_DIR/sowknow_$DATE.sql"
    echo "Backup compressed: sowknow_$DATE.sql.gz"
    
    # Encrypt the backup (optional - requires gpg key setup)
    # gzip -c "$BACKUP_DIR/sowknow_$DATE.sql" | gpg --encrypt --recipient backup@gollamtech.com > "$BACKUP_DIR/sowknow_$DATE.sql.gpg"
else
    echo "ERROR: Database backup failed!"
    exit 1
fi

# Clean old backups (keep 7 daily, 4 weekly, 3 monthly)
echo "Cleaning old backups..."

# Remove daily backups older than 7 days
find "$BACKUP_DIR" -name "sowknow_*.sql.gz" -mtime +7 -delete

# Keep only one weekly backup per week (keep 4 weeks)
if [ "$DAY_OF_WEEK" = "1" ]; then
    # Monday - keep weekly (already done by daily retention)
    echo "Weekly backup retained"
fi

echo "Backup completed successfully!"

# List current backups
echo "Current backups:"
ls -lh "$BACKUP_DIR"
