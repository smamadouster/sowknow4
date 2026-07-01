#!/usr/bin/env python3
"""
SOWKNOW Auto-Uploader for macOS
================================
Watches ~/Desktop/Public and ~/Desktop/Confidential folders.
Automatically uploads new documents to SOWKNOW with the correct bucket.
Deduplicates via local SHA256 tracking. Sends daily email report at 6 PM.

Requirements: pip3 install requests watchdog

Configuration: edit the CONFIG section below or set environment variables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import smtplib
import sys
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from threading import Event, Thread
from typing import Dict, List, Optional

import requests
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# =============================================================================
# CONFIG — edit these or set as environment variables
# =============================================================================
SOWKNOW_URL = os.getenv("SOWKNOW_URL", "https://sowknow.gollamtech.com")
SOWKNOW_EMAIL = os.getenv("SOWKNOW_EMAIL", "")  # your SOWKNOW login email
SOWKNOW_PASSWORD = os.getenv("SOWKNOW_PASSWORD", "")  # your SOWKNOW password
SOWKNOW_BOT_API_KEY = os.getenv("SOWKNOW_BOT_API_KEY", "")  # API key for login-free uploads via Tailscale

PUBLIC_DIR = os.path.expanduser(os.getenv("SOWKNOW_PUBLIC_DIR", "~/Desktop/Public"))
CONFIDENTIAL_DIR = os.path.expanduser(os.getenv("SOWKNOW_CONFIDENTIAL_DIR", "~/Desktop/Confidential"))

# Email report settings
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")  # sender Gmail address
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")  # Gmail App Password (not your login password)
REPORT_RECIPIENT = os.getenv("REPORT_RECIPIENT", "smamadouster@gmail.com")
REPORT_HOUR = int(os.getenv("REPORT_HOUR", "18"))  # 6 PM local time

# State file to track uploaded files across restarts
STATE_FILE = os.path.expanduser(os.getenv("SOWKNOW_STATE_FILE", "~/.sowknow-uploader-state.json"))
LOG_FILE = os.path.expanduser(os.getenv("SOWKNOW_LOG_FILE", "~/Library/Logs/sowknow-auto-uploader.log"))

# Supported file extensions
SUPPORTED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".txt", ".csv", ".json", ".xml", ".html", ".htm", ".md", ".rtf",
}

# =============================================================================
# LOGGING
# =============================================================================
os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("sowknow-uploader")


# =============================================================================
# STATE MANAGEMENT — tracks uploaded file hashes to prevent duplicates
# =============================================================================
class UploadState:
    def __init__(self, path: str):
        self.path = path
        self.uploaded: Dict[str, dict] = {}  # sha256 -> {filename, bucket, timestamp}
        self.daily_uploads: List[dict] = []
        self.daily_errors: List[dict] = []
        self._load()

    def _load(self):
        # Clean up any stale temp file from a prior crash
        tmp = self.path + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    data = json.load(f)
                self.uploaded = data.get("uploaded", {})
                self.daily_uploads = data.get("daily_uploads", [])
                self.daily_errors = data.get("daily_errors", [])
            except (json.JSONDecodeError, KeyError, OSError):
                log.warning("Corrupt state file, starting fresh")

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({
                "uploaded": self.uploaded,
                "daily_uploads": self.daily_uploads,
                "daily_errors": self.daily_errors,
            }, f, indent=2)
        os.replace(tmp, self.path)  # atomic on POSIX

    def is_uploaded(self, sha256: str) -> bool:
        return sha256 in self.uploaded

    def mark_uploaded(self, sha256: str, filename: str, bucket: str):
        now = datetime.now().isoformat()
        self.uploaded[sha256] = {"filename": filename, "bucket": bucket, "timestamp": now}
        self.daily_uploads.append({"filename": filename, "bucket": bucket, "timestamp": now})
        self.save()

    def record_error(self, filename: str, bucket: str, error: str):
        self.daily_errors.append({
            "filename": filename, "bucket": bucket,
            "error": error, "timestamp": datetime.now().isoformat(),
        })
        self.save()

    def flush_daily(self) -> tuple[List[dict], List[dict]]:
        uploads = list(self.daily_uploads)
        errors = list(self.daily_errors)
        self.daily_uploads = []
        self.daily_errors = []
        self.save()
        return uploads, errors


# =============================================================================
# SOWKNOW API CLIENT
# =============================================================================
class SowknowClient:
    # Proactively re-login after this many minutes (well before token expiry)
    TOKEN_REFRESH_INTERVAL = 45 * 60  # 45 minutes in seconds

    def __init__(self, base_url: str, email: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SOWKNOW-AutoUploader/1.0"})
        self._authenticated = False
        self._login_time: float = 0  # epoch time of last successful login
        self._upload_count: int = 0  # uploads since last login

    def login(self) -> bool:
        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/auth/login",
                data={"username": self.email, "password": self.password},
                timeout=30,
            )
            if resp.status_code == 200:
                # Extract access_token cookie and use as Bearer header
                # to bypass CSRF middleware (Bearer requests are exempt)
                access_token = self.session.cookies.get("access_token")
                if access_token:
                    self.session.headers["Authorization"] = f"Bearer {access_token}"
                self._authenticated = True
                self._login_time = time.time()
                self._upload_count = 0
                log.info("Authenticated to SOWKNOW successfully")
                return True
            log.error(f"Login failed: {resp.status_code} {resp.text[:200]}")
            return False
        except requests.RequestException as e:
            log.error(f"Login request failed: {e}")
            return False

    def _token_age(self) -> float:
        """Seconds since last login."""
        return time.time() - self._login_time if self._login_time else float("inf")

    def ensure_auth(self) -> bool:
        if self._authenticated:
            # Proactively refresh if token is getting old (don't wait for 401)
            if self._token_age() > self.TOKEN_REFRESH_INTERVAL:
                log.info(f"Proactive token refresh after {int(self._token_age())}s / {self._upload_count} uploads")
                self._authenticated = False
                return self.login()
            # Verify token is still valid
            try:
                r = self.session.get(f"{self.base_url}/api/v1/auth/me", timeout=10)
                if r.status_code == 200:
                    return True
            except requests.RequestException:
                pass
            # Token expired or invalid, re-login
            log.info("Token validation failed, re-authenticating...")
            self._authenticated = False
        return self.login()

    def upload(self, filepath: str, bucket: str) -> dict:
        if not self.ensure_auth():
            raise ConnectionError("Cannot authenticate to SOWKNOW")

        filename = os.path.basename(filepath)
        with open(filepath, "rb") as f:
            resp = self.session.post(
                f"{self.base_url}/api/v1/documents/upload",
                files={"file": (filename, f)},
                data={"bucket": bucket},
                timeout=120,
            )

        if resp.status_code in (200, 201, 202):
            self._upload_count += 1
            log.info(f"Uploaded: {filename} -> {bucket}")
            return resp.json()

        # If 401, try re-auth once
        if resp.status_code == 401:
            self._authenticated = False
            if self.ensure_auth():
                with open(filepath, "rb") as f:
                    resp = self.session.post(
                        f"{self.base_url}/api/v1/documents/upload",
                        files={"file": (filename, f)},
                        data={"bucket": bucket},
                        timeout=120,
                    )
                if resp.status_code in (200, 201, 202):
                    self._upload_count += 1
                    log.info(f"Uploaded (retry): {filename} -> {bucket}")
                    return resp.json()

        raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text[:300]}")


class ApiKeyClient:
    """Upload client using BOT_API_KEY — no login, no tokens, no CSRF."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "SOWKNOW-AutoUploader/2.0",
            "X-Bot-Api-Key": self.api_key,
        })

    def login(self) -> bool:
        """No-op — API key mode doesn't need login."""
        log.info("API key mode: no login required")
        return True

    def ensure_auth(self) -> bool:
        """Always authenticated — API key is static."""
        return True

    def upload(self, filepath: str, bucket: str) -> dict:
        filename = os.path.basename(filepath)
        with open(filepath, "rb") as f:
            resp = self.session.post(
                f"{self.base_url}/api/v1/internal/upload",
                files={"file": (filename, f)},
                data={"bucket": bucket},
                timeout=120,
            )

        if resp.status_code in (200, 201, 202):
            log.info(f"Uploaded: {filename} -> {bucket}")
            return resp.json()

        raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text[:300]}")


# =============================================================================
# FILE HASH
# =============================================================================
def file_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# =============================================================================
# UPLOAD LOGIC
# =============================================================================
def is_supported(filepath: str) -> bool:
    return Path(filepath).suffix.lower() in SUPPORTED_EXTENSIONS


def wait_for_write_complete(filepath: str, timeout: int = 10) -> bool:
    """Wait until file size is stable (file finished copying)."""
    prev_size = -1
    for _ in range(timeout):
        try:
            curr_size = os.path.getsize(filepath)
        except OSError:
            return False
        if curr_size == prev_size and curr_size > 0:
            return True
        prev_size = curr_size
        time.sleep(1)
    return True  # proceed anyway after timeout


def process_file(filepath: str, bucket: str, client, state: UploadState):
    """Process a single file: check duplicate, upload, update state."""
    filename = os.path.basename(filepath)

    if not os.path.isfile(filepath):
        return
    if not is_supported(filepath):
        log.debug(f"Skipping unsupported file: {filename}")
        return
    # Skip hidden/temp files
    if filename.startswith(".") or filename.startswith("~"):
        return

    if not wait_for_write_complete(filepath):
        return

    try:
        sha = file_sha256(filepath)
    except OSError as e:
        log.error(f"Cannot read {filename}: {e}")
        state.record_error(filename, bucket, str(e))
        return

    if state.is_uploaded(sha):
        log.info(f"Duplicate skipped: {filename} (hash already uploaded)")
        return

    try:
        client.upload(filepath, bucket)
        state.mark_uploaded(sha, filename, bucket)
    except Exception as e:
        log.error(f"Upload failed for {filename}: {e}")
        state.record_error(filename, bucket, str(e))


def scan_existing(directory: str, bucket: str, client, state: UploadState):
    """Scan directory for files not yet uploaded."""
    if not os.path.isdir(directory):
        log.warning(f"Directory does not exist: {directory}")
        return
    for entry in sorted(os.listdir(directory)):
        filepath = os.path.join(directory, entry)
        if os.path.isfile(filepath):
            process_file(filepath, bucket, client, state)


# =============================================================================
# WATCHDOG HANDLER
# =============================================================================
class UploadHandler(FileSystemEventHandler):
    def __init__(self, bucket: str, client, state: UploadState):
        self.bucket = bucket
        self.client = client
        self.state = state

    def on_created(self, event):
        if event.is_directory:
            return
        # Small delay to let the file finish copying
        time.sleep(2)
        process_file(event.src_path, self.bucket, self.client, self.state)

    def on_moved(self, event):
        if event.is_directory:
            return
        time.sleep(2)
        process_file(event.dest_path, self.bucket, self.client, self.state)


# =============================================================================
# DAILY EMAIL REPORT
# =============================================================================
def send_daily_report(state: UploadState, stop_event: Event):
    """Background thread: sends daily report at REPORT_HOUR."""
    while not stop_event.is_set():
        now = datetime.now()
        # Next report time today or tomorrow
        target = now.replace(hour=REPORT_HOUR, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        log.info(f"Next report scheduled at {target.strftime('%Y-%m-%d %H:%M')}")

        if stop_event.wait(timeout=wait_seconds):
            break  # shutting down

        # Time to send report
        uploads, errors = state.flush_daily()
        try:
            _send_report_email(uploads, errors)
        except Exception as e:
            log.error(f"Failed to send daily report: {e}")


def _send_report_email(uploads: List[dict], errors: List[dict]):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        log.warning("SMTP not configured — skipping email report (check SMTP_EMAIL / SMTP_PASSWORD)")
        # Still log the report locally
        log.info(f"DAILY REPORT: {len(uploads)} uploads, {len(errors)} errors")
        return

    date_str = datetime.now().strftime("%Y-%m-%d")
    subject = f"SOWKNOW Auto-Uploader Report — {date_str}"

    body_lines = [
        f"SOWKNOW Auto-Uploader Daily Report",
        f"Date: {date_str}",
        f"",
        f"UPLOADS: {len(uploads)}",
        f"{'='*50}",
    ]
    if uploads:
        for u in uploads:
            body_lines.append(f"  [{u['bucket'].upper():>14}] {u['filename']}  ({u['timestamp']})")
    else:
        body_lines.append("  No documents uploaded today.")

    body_lines += [
        f"",
        f"ERRORS: {len(errors)}",
        f"{'='*50}",
    ]
    if errors:
        for e in errors:
            body_lines.append(f"  [{e['bucket'].upper():>14}] {e['filename']}")
            body_lines.append(f"    Error: {e['error']}")
            body_lines.append(f"    Time:  {e['timestamp']}")
    else:
        body_lines.append("  No errors today.")

    body_lines += ["", "-- SOWKNOW Auto-Uploader"]

    msg = MIMEText("\n".join(body_lines))
    msg["Subject"] = subject
    msg["From"] = SMTP_EMAIL
    msg["To"] = REPORT_RECIPIENT

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, [REPORT_RECIPIENT], msg.as_string())

    log.info(f"Daily report sent to {REPORT_RECIPIENT}: {len(uploads)} uploads, {len(errors)} errors")


def install_launchd_plist():
    """Install the launchd plist to run the auto-uploader at login."""
    home = Path.home()
    launch_agents = home / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)

    plist_path = launch_agents / "com.sowknow.autouploader.plist"

    script_path = os.path.realpath(__file__)
    log_dir = home / "Library" / "Logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    env = {
        "SOWKNOW_URL": SOWKNOW_URL,
        "SOWKNOW_EMAIL": SOWKNOW_EMAIL,
        "SOWKNOW_PASSWORD": SOWKNOW_PASSWORD,
        "SOWKNOW_BOT_API_KEY": SOWKNOW_BOT_API_KEY,
        "SMTP_EMAIL": SMTP_EMAIL,
        "SMTP_PASSWORD": SMTP_PASSWORD,
        "REPORT_RECIPIENT": REPORT_RECIPIENT,
    }

    env_xml = "\n".join(
        f"            <key>{k}</key>\n            <string>{v}</string>"
        for k, v in env.items() if v
    )

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.sowknow.autouploader</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/env</string>
        <string>python3</string>
        <string>{script_path}</string>
    </array>

    <key>EnvironmentVariables</key>
    <dict>
{env_xml}
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>{log_dir}/sowknow-auto-uploader.log</string>

    <key>StandardErrorPath</key>
    <string>{log_dir}/sowknow-auto-uploader-error.log</string>

    <key>WorkingDirectory</key>
    <string>{home}</string>
</dict>
</plist>
"""
    with open(plist_path, "w") as f:
        f.write(plist)

    log.info(f"Installed launchd plist: {plist_path}")
    print(f"Installed launchd plist: {plist_path}")
    print("Load it now with:")
    print(f"  launchctl load {plist_path}")
    print("Or use --start-service to load it automatically.")


def start_service():
    """Load and start the launchd service."""
    home = Path.home()
    plist_path = home / "Library" / "LaunchAgents" / "com.sowknow.autouploader.plist"
    if not plist_path.exists():
        log.error(f"Plist not found: {plist_path}. Run with --install first.")
        return
    os.system(f"launchctl load '{plist_path}'")
    log.info("Started com.sowknow.autouploader service")
    print("Started com.sowknow.autouploader service")


def stop_service():
    """Stop and unload the launchd service."""
    home = Path.home()
    plist_path = home / "Library" / "LaunchAgents" / "com.sowknow.autouploader.plist"
    if plist_path.exists():
        os.system(f"launchctl unload '{plist_path}'")
    log.info("Stopped com.sowknow.autouploader service")
    print("Stopped com.sowknow.autouploader service")


# =============================================================================
# MAIN
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="SOWKNOW Auto-Uploader for macOS")
    parser.add_argument("--install", action="store_true", help="Install launchd plist")
    parser.add_argument("--start-service", action="store_true", help="Load launchd service")
    parser.add_argument("--stop-service", action="store_true", help="Unload launchd service")
    parser.add_argument("--scan", action="store_true", help="Scan once and exit (no watching)")
    args = parser.parse_args()

    if args.stop_service:
        stop_service()
        return

    if args.install:
        install_launchd_plist()
        return

    if args.start_service:
        start_service()
        return

    # Ensure watch directories exist
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    os.makedirs(CONFIDENTIAL_DIR, exist_ok=True)

    state = UploadState(STATE_FILE)

    # Select auth mode: API key (Tailscale) or OAuth2 login
    if SOWKNOW_BOT_API_KEY:
        log.info("Using API key mode (Tailscale / no login)")
        client = ApiKeyClient(SOWKNOW_URL, SOWKNOW_BOT_API_KEY)
    else:
        if not SOWKNOW_EMAIL or not SOWKNOW_PASSWORD:
            log.error("Set SOWKNOW_BOT_API_KEY (preferred) or SOWKNOW_EMAIL + SOWKNOW_PASSWORD")
            sys.exit(1)
        log.info("Using OAuth2 login mode")
        client = SowknowClient(SOWKNOW_URL, SOWKNOW_EMAIL, SOWKNOW_PASSWORD)

    log.info(f"SOWKNOW Auto-Uploader starting")
    log.info(f"  API:          {SOWKNOW_URL}")
    log.info(f"  Auth mode:    {'API key' if SOWKNOW_BOT_API_KEY else 'OAuth2 login'}")
    log.info(f"  Public dir:   {PUBLIC_DIR}")
    log.info(f"  Confid. dir:  {CONFIDENTIAL_DIR}")
    log.info(f"  State file:   {STATE_FILE}")

    # Initial login (no-op in API key mode)
    if not client.login():
        log.error("Initial login failed — will retry on first upload")

    # Scan existing files on startup
    log.info("Scanning existing files...")
    scan_existing(PUBLIC_DIR, "public", client, state)
    scan_existing(CONFIDENTIAL_DIR, "confidential", client, state)
    log.info("Initial scan complete")

    if args.scan:
        return

    # Start filesystem watchers before daily report thread
    observer = Observer()
    observer.schedule(UploadHandler("public", client, state), PUBLIC_DIR, recursive=False)
    observer.schedule(UploadHandler("confidential", client, state), CONFIDENTIAL_DIR, recursive=False)
    observer.start()

    # Start daily report thread
    stop_event = Event()
    report_thread = Thread(target=send_daily_report, args=(state, stop_event), daemon=True)
    report_thread.start()

    # Periodic re-scan interval (seconds) — catches files missed by watchdog
    RESCAN_INTERVAL = 5 * 60  # 5 minutes

    log.info("Watching for new documents... (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(RESCAN_INTERVAL)
            log.debug("Periodic re-scan...")
            scan_existing(PUBLIC_DIR, "public", client, state)
            scan_existing(CONFIDENTIAL_DIR, "confidential", client, state)
    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        stop_event.set()
        observer.stop()
        observer.join()
        log.info("Stopped.")


if __name__ == "__main__":
    main()
