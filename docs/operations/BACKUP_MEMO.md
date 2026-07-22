# SOWKNOW Backup Memo

## What is automated

- **Daily backup** runs every day at 02:00 via cron.
  - Script: `scripts/backup.sh`
  - Backs up: Postgres volume + host config (`.env`, `.secrets`, compose files, nginx, scripts)
  - Stores: Restic snapshot tagged `daily` in `/var/backups/sowknow/restic-repo`
  - Retention: 7 daily snapshots

- **Weekly full backup** runs every Sunday at 03:00 via cron.
  - Script: `scripts/backup-full.sh`
  - Backs up: all critical Docker volumes + config
  - Stores: Restic snapshot tagged `weekly`
  - Retention: 4 weekly snapshots

- **Verification** runs every Monday at 04:00 via cron.
  - Script: `scripts/backup-verify.sh`
  - Checks snapshot contents + runs `restic check --read-data-subset=5%`

## What you need to do manually

### Daily
- Nothing. Just watch for failure alerts.

### Weekly (Sunday/Monday)
- Nothing. Verification runs automatically.

### Monthly
1. Check backup log:
   ```bash
   tail -50 /var/log/sowknow/backup.log
   ```
2. Confirm snapshots exist:
   ```bash
   restic -r /var/backups/sowknow/restic-repo --password-file /var/backups/sowknow/.restic-password snapshots
   ```
3. Optional: restore one file to a temp folder to prove it works.

### Quarterly
1. Refresh your offsite copies:
   - Copy `restic-repo` and `.restic-password` to your MacBook.
   - Copy to external disk.
   - (Optional) upload to cloud storage.
2. Test restore from the offsite copy on your Mac:
   ```bash
   restic -r ~/sowknow-backups/restic-repo --password-file ~/sowknow-backups/.restic-password restore latest --tag weekly --target ~/sowknow-test-restore
   ```

## If an alert says backup failed

1. Check the log:
   ```bash
   tail -100 /var/log/sowknow/backup.log
   ```
2. Make sure Postgres is healthy:
   ```bash
   docker ps | grep sowknow-postgres
   ```
3. Re-run the failed script manually:
   ```bash
   /home/development/src/active/sowknow4/scripts/backup.sh
   ```
4. If Restic reports a lock, unlock it:
   ```bash
   restic -r /var/backups/sowknow/restic-repo --password-file /var/backups/sowknow/.restic-password unlock
   ```

## Where everything lives

| Item | Location |
|---|---|
| Restic repo | `/var/backups/sowknow/restic-repo` |
| Password file | `/var/backups/sowknow/.restic-password` |
| Log file | `/var/log/sowknow/backup.log` |
| Config | `scripts/.backup.env` |
| Scripts | `scripts/backup.sh`, `scripts/backup-full.sh`, `scripts/backup-verify.sh` |
| Cron example | `scripts/crontab.example` |

## Critical reminders

- **Do not lose `.restic-password`.** Without it, the backup is unreadable.
- Keep at least one offsite copy (MacBook, external disk, or cloud).
- Alerts go to Telegram/email only if `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` or `ALERT_FROM_EMAIL`/`ADMIN_EMAILS` are set in `.env`.
