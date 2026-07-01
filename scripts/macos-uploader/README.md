# SOWKNOW macOS Upload Tools

Two scripts that watch your Mac folders and upload documents to SOWKNOW automatically:

1. **SOWKNOW Auto-Uploader** — monitors `~/Desktop/Public` and `~/Desktop/Confidential` and uploads new files to the matching bucket. Runs as a background macOS service.
2. **SOWKNOW Sync Agent** — a flexible sync tool for any local folder (iCloud Drive, Dropbox, Downloads, etc.).

---

## Quick start

### 1. Download the package

From the repo:

```bash
cd ~/Downloads
curl -L -o sowknow-macos-uploader.zip \
  "https://github.com/smamadouster/sowknow4/archive/refs/heads/master.zip"
unzip sowknow-macos-uploader.zip
cd sowknow4-master/scripts/macos-uploader
```

Or, if you have the repo cloned locally:

```bash
cd /path/to/sowknow4/scripts/macos-uploader
```

### 2. Run the installer

```bash
./install.sh
```

The installer will:

- Install Python dependencies (`requests`, `watchdog`, `keyring`)
- Copy the scripts to `~/.sowknow/bin/`
- Create `~/Desktop/Public` and `~/Desktop/Confidential`
- Configure and start the Auto-Uploader background service
- Optionally run the Sync Agent setup

### 3. Authenticate

Choose one of the two authentication methods during install:

- **API key** (recommended if you access SOWKNOW via Tailscale): set `SOWKNOW_BOT_API_KEY`.
- **Email + password**: your regular SOWKNOW credentials.

---

## Manual setup (without the installer)

### Auto-Uploader

```bash
pip3 install --user requests watchdog
mkdir -p ~/Desktop/Public ~/Desktop/Confidential
python3 sowknow-auto-uploader.py --install
python3 sowknow-auto-uploader.py --start-service
```

Set credentials via environment variables:

```bash
export SOWKNOW_BOT_API_KEY="your-api-key"
# OR
export SOWKNOW_EMAIL="you@example.com"
export SOWKNOW_PASSWORD="your-password"
```

### Sync Agent

```bash
pip3 install --user requests watchdog keyring
python3 sowknow_sync.py --setup
python3 sowknow_sync.py --watch
```

---

## Files in this package

| File | Purpose |
|------|---------|
| `sowknow-auto-uploader.py` | Watches Public/Confidential folders and uploads automatically |
| `com.sowknow.autouploader.plist` | macOS `launchd` service template |
| `sowknow_sync.py` | Flexible folder sync agent |
| `requirements.txt` | Python dependencies |
| `install.sh` | One-command installer |
| `README.md` | This file |

---

## Daily operations

### Auto-Uploader

```bash
sowknow-auto-uploader --start-service   # start background service
sowknow-auto-uploader --stop-service    # stop background service
sowknow-auto-uploader --scan            # scan once, no watching
sowknow-auto-uploader --install         # regenerate the launchd plist
```

Logs:

```bash
tail -f ~/Library/Logs/sowknow-auto-uploader.log
tail -f ~/Library/Logs/sowknow-auto-uploader-error.log
```

### Sync Agent

```bash
sowknow-sync --setup    # interactive configuration
sowknow-sync --sync     # one-time sync
sowknow-sync --watch    # continuous sync
```

Logs:

```bash
tail -f ~/.sowknow/sync_agent.log
```

---

## Configuration reference

### Auto-Uploader environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SOWKNOW_URL` | `https://sowknow.gollamtech.com` | SOWKNOW base URL |
| `SOWKNOW_BOT_API_KEY` | — | API key for Tailscale/internal uploads |
| `SOWKNOW_EMAIL` | — | SOWKNOW login email |
| `SOWKNOW_PASSWORD` | — | SOWKNOW login password |
| `SOWKNOW_PUBLIC_DIR` | `~/Desktop/Public` | Public watch folder |
| `SOWKNOW_CONFIDENTIAL_DIR` | `~/Desktop/Confidential` | Confidential watch folder |
| `SMTP_EMAIL` | — | Gmail sender address for reports |
| `SMTP_PASSWORD` | — | Gmail App Password |
| `REPORT_RECIPIENT` | `smamadouster@gmail.com` | Report recipient |
| `REPORT_HOUR` | `18` | Hour (24h) to send daily report |

### Sync Agent config file

`~/.sowknow/sync_config.json`

```json
{
  "api_url": "https://sowknow.gollamtech.com",
  "watch_folders": [
    {"path": "/Users/you/Dropbox", "visibility": "public"},
    {"path": "/Users/you/iCloud", "visibility": "confidential"}
  ],
  "visibility": "public",
  "auto_tag": true,
  "sync_interval": 60
}
```

---

## Troubleshooting

**Installer says Python or pip is missing**
Install Python 3 from [python.org](https://www.python.org/downloads/mac-osx/) or run `xcode-select --install`.

**Uploads fail with 401**
- Check that `SOWKNOW_BOT_API_KEY` is correct, **or**
- Check that `SOWKNOW_EMAIL` / `SOWKNOW_PASSWORD` are correct.

**Auto-Uploader does not start at login**
Run:

```bash
launchctl list | grep com.sowknow.autouploader
```

If it is not listed:

```bash
launchctl load ~/Library/LaunchAgents/com.sowknow.autouploader.plist
```

**Duplicate files are skipped**
This is expected. The uploader tracks SHA256 hashes in `~/.sowknow-uploader-state.json` and `~/.sowknow/sync_state.json` to avoid uploading the same file twice.

**Keyring errors**
The Sync Agent will fall back to storing the token in `~/.sowknow/sync_config.json` if the macOS Keychain is unavailable.

---

## Security notes

- Email/password mode stores credentials in the launchd plist (`~/Library/LaunchAgents/com.sowknow.autouploader.plist`), which is readable only by your user. API-key mode is safer.
- Confidential documents are uploaded with `bucket=confidential` and are isolated in SOWKNOW.
- Source files are never deleted by these scripts.
