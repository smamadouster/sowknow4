# Reusable Docker Project Backup Template (Restic)

This is a copy-paste-ready guide for adding the same daily/weekly Restic backup pattern to any Docker Compose project.

---

## 1. Prerequisites

- Linux host with `bash`, `docker`, `docker compose`, and `cron`.
- `restic` installed. To install on the server:
  ```bash
  sudo apt-get install restic
  # or
  sudo wget -O /usr/local/bin/restic https://github.com/restic/restic/releases/download/v0.17.3/restic_0.17.3_linux_amd64
  sudo chmod +x /usr/local/bin/restic
  ```
- Backup disk or folder with enough free space (at least 2× the size of the data you are backing up).
- A safe place to store the password file offsite (password manager, encrypted USB, etc.).

---

## 2. Choose paths

Pick or create these locations on the server:

```bash
PROJECT_ROOT=/opt/myapp                     # where docker-compose.yml lives
BACKUP_BASE=/var/backups/myapp              # where the restic repo will live
REPO_PATH=$BACKUP_BASE/restic-repo
PASSWORD_FILE=$BACKUP_BASE/.restic-password
LOG_DIR=/var/log/myapp
```

Create them:

```bash
sudo mkdir -p "$BACKUP_BASE" "$LOG_DIR"
sudo chmod 700 "$BACKUP_BASE"
```

---

## 3. Generate and save the Restic password

Generate a strong password and store it in the password file:

```bash
openssl rand -base64 32 | sudo tee "$PASSWORD_FILE" >/dev/null
sudo chmod 600 "$PASSWORD_FILE"
```

**Important:** copy this password to your password manager or another safe place now. Losing it means losing the backup.

---

## 4. Initialize the Restic repository

```bash
sudo restic init --repo "$REPO_PATH" --password-file "$PASSWORD_FILE"
```

Expected output: `created restic repository ... at $REPO_PATH`.

---

## 5. Create the backup scripts

Create these four files inside `$PROJECT_ROOT/scripts/`.

### 5.1 `.backup.env` — configuration

```bash
# Project name (used for tags and alerts)
BACKUP_PROJECT=myapp

# Restic repository and password
RESTIC_REPO=/var/backups/myapp/restic-repo
RESTIC_PASSWORD_FILE=/var/backups/myapp/.restic-password

# What to back up
BACKUP_PROJECT_ROOT=/opt/myapp
BACKUP_CONFIG_PATHS="/opt/myapp/.env /opt/myapp/docker-compose.yml /opt/myapp/nginx /opt/myapp/scripts"
BACKUP_DB_VOLUME=myapp_postgres-data
BACKUP_ALL_VOLUMES="myapp_postgres-data myapp_redis-data myapp_uploads-data"

# Retention
DAILY_RETENTION=7
WEEKLY_RETENTION=4

# Logging
BACKUP_LOG_DIR=/var/log/myapp
BACKUP_LOG_FILE=/var/log/myapp/backup.log

# Optional alerting (leave empty to disable)
TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""
ADMIN_EMAILS=""
ALERT_FROM_EMAIL=""
```

Adjust the volume names to match the ones shown by:

```bash
docker volume ls
```

### 5.2 `backup.sh` — daily DB + config snapshot

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.backup.env"

export RESTIC_REPOSITORY="$RESTIC_REPO"
export RESTIC_PASSWORD_FILE="$RESTIC_PASSWORD_FILE"

mkdir -p "$BACKUP_LOG_DIR"
exec >> "$BACKUP_LOG_FILE" 2>&1

echo "=== Daily backup started $(date -Iseconds) ==="

# Dump the database volume to a temp folder
DB_DUMP_DIR="$BACKUP_PROJECT_ROOT/.backup-tmp/db"
rm -rf "$DB_DUMP_DIR"
mkdir -p "$DB_DUMP_DIR"

docker run --rm \
  -v "${BACKUP_DB_VOLUME}:/var/lib/postgresql/data:ro" \
  -v "$DB_DUMP_DIR:/out" \
  alpine:3.19 \
  sh -c 'cp -a /var/lib/postgresql/data/. /out/'

# Build include list
INCLUDE_ARGS=()
for p in $BACKUP_CONFIG_PATHS; do
  [ -e "$p" ] && INCLUDE_ARGS+=("--include" "$p")
done
INCLUDE_ARGS+=("--include" "$DB_DUMP_DIR")

restic backup \
  --tag daily \
  --tag "host:$(hostname)" \
  --tag "date:$(date +%Y%m%d)" \
  "${INCLUDE_ARGS[@]}" \
  "$BACKUP_PROJECT_ROOT"

restic forget --tag daily --keep-daily "$DAILY_RETENTION" --prune

echo "=== Daily backup finished $(date -Iseconds) ==="
```

### 5.3 `backup-full.sh` — weekly full snapshot

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.backup.env"

export RESTIC_REPOSITORY="$RESTIC_REPO"
export RESTIC_PASSWORD_FILE="$RESTIC_PASSWORD_FILE"

mkdir -p "$BACKUP_LOG_DIR"
exec >> "$BACKUP_LOG_FILE" 2>&1

echo "=== Weekly full backup started $(date -Iseconds) ==="

# Dump all listed volumes under one temp folder
VOL_DUMP_DIR="$BACKUP_PROJECT_ROOT/.backup-tmp/volumes"
rm -rf "$VOL_DUMP_DIR"
mkdir -p "$VOL_DUMP_DIR"

for vol in $BACKUP_ALL_VOLUMES; do
  safe_name=$(echo "$vol" | tr '/' '_')
  target="$VOL_DUMP_DIR/$safe_name"
  mkdir -p "$target"
  docker run --rm \
    -v "${vol}:/vol-src:ro" \
    -v "$target:/vol-dst" \
    alpine:3.19 \
    sh -c 'cp -a /vol-src/. /vol-dst/'
done

# Build include list
INCLUDE_ARGS=()
for p in $BACKUP_CONFIG_PATHS; do
  [ -e "$p" ] && INCLUDE_ARGS+=("--include" "$p")
done
INCLUDE_ARGS+=("--include" "$VOL_DUMP_DIR")

restic backup \
  --tag weekly \
  --tag "host:$(hostname)" \
  --tag "date:$(date +%Y%m%d)" \
  "${INCLUDE_ARGS[@]}" \
  "$BACKUP_PROJECT_ROOT"

restic forget --tag weekly --keep-weekly "$WEEKLY_RETENTION" --prune

echo "=== Weekly full backup finished $(date -Iseconds) ==="
```

### 5.4 `backup-verify.sh` — verification

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.backup.env"

export RESTIC_REPOSITORY="$RESTIC_REPO"
export RESTIC_PASSWORD_FILE="$RESTIC_PASSWORD_FILE"

mkdir -p "$BACKUP_LOG_DIR"
exec >> "$BACKUP_LOG_FILE" 2>&1

echo "=== Backup verification started $(date -Iseconds) ==="

restic snapshots
restic check --read-data-subset=5%

echo "=== Backup verification finished $(date -Iseconds) ==="
```

### 5.5 Make scripts executable

```bash
chmod +x "$PROJECT_ROOT/scripts/backup.sh"
chmod +x "$PROJECT_ROOT/scripts/backup-full.sh"
chmod +x "$PROJECT_ROOT/scripts/backup-verify.sh"
```

---

## 6. Schedule with cron

Edit root crontab:

```bash
sudo crontab -e
```

Add:

```cron
# Daily DB + config backup at 02:00
0 2 * * * /opt/myapp/scripts/backup.sh

# Weekly full backup Sunday at 03:00
0 3 * * 0 /opt/myapp/scripts/backup-full.sh

# Verification Monday at 04:00
0 4 * * 1 /opt/myapp/scripts/backup-verify.sh
```

Replace `/opt/myapp/scripts/` with the real path.

---

## 7. Run first backups

```bash
# Daily
sudo /opt/myapp/scripts/backup.sh

# Weekly full
sudo /opt/myapp/scripts/backup-full.sh

# Verify
sudo /opt/myapp/scripts/backup-verify.sh

# List snapshots
sudo restic -r "$REPO_PATH" --password-file "$PASSWORD_FILE" snapshots
```

---

## 8. Copy the backup offsite

On your local machine (MacBook example), install restic:

```bash
brew install restic
```

Then copy the repository and password file. Replace `YOUR_SERVER_IP` with the server IP or hostname:

```bash
mkdir -p ~/myapp-backups
rsync -avz --progress root@YOUR_SERVER_IP:/var/backups/myapp/restic-repo ~/myapp-backups/
rsync -avz --progress root@YOUR_SERVER_IP:/var/backups/myapp/.restic-password ~/myapp-backups/
```

To copy to an external disk:

```bash
rsync -avz --progress root@YOUR_SERVER_IP:/var/backups/myapp/restic-repo /Volumes/MyExternalDisk/myapp-backups/
rsync -avz --progress root@YOUR_SERVER_IP:/var/backups/myapp/.restic-password /Volumes/MyExternalDisk/myapp-backups/
```

To use cloud storage (iCloud, Dropbox, S3, etc.), sync the `restic-repo` folder and `.restic-password` with your chosen tool. Do **not** store the password inside the same cloud folder as the repo if the cloud account is shared.

---

## 9. Test a restore

On the machine that holds the copy:

```bash
restic -r ~/myapp-backups/restic-repo --password-file ~/myapp-backups/.restic-password snapshots

# Restore the latest weekly snapshot to a temp folder
restic -r ~/myapp-backups/restic-repo --password-file ~/myapp-backups/.restic-password \
  restore latest --tag weekly --target ~/myapp-test-restore
```

Verify the files are readable. If restoring Postgres data, stop the container and copy the data back, or restore from a SQL dump if your workflow uses dumps instead of volume copies.

---

## 10. Checklist for each new project

- [ ] Install `restic` on the server.
- [ ] Create backup directory and password file.
- [ ] Save the password in a password manager.
- [ ] Initialize the Restic repository.
- [ ] Adapt `.backup.env` with real project paths and Docker volume names.
- [ ] Create the three scripts and make them executable.
- [ ] Add cron entries.
- [ ] Run the first daily and weekly backups.
- [ ] Run verification.
- [ ] Copy repo + password offsite.
- [ ] Test restore from the offsite copy.
