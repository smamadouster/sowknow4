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

import requests
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# =============================================================================
# CONFIG — edit these or set as environment variables
# =============================================================================
SOWKNOW_URL = os.getenv("SOWKNOW_URL", "https://sowknow.gollamtech.com")
SOWKNOW_EMAIL = os.getenv("SOWKNOW_EMAIL", "")  # your SOWKNOW login email
SOWKNOW_PASSWORD = os.getenv("SOWKNOW_PASSWORD", "")  # your SOWKNOW password

PUBLIC_DIR = os.path.expanduser(os.getenv("SOWKNOW_PUBLIC_DIR", "~/Desktop/Public"))
CONFIDENTIAL_DIR = os.path.expanduser(os.getenv("SOWKNOW_CONFIDENTIAL_DIR", "~/Desktop/Confidential"))

# Email report settings
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")  # sender Gmail address
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")  # Gmail App Password (not your login password)
REPORT_RECIPIENT = os.getenv("REPORT_RECIPIENT", "smamadouster@gmail.com")
REPORT_HOUR = 18  # 6 PM

# State file to track uploaded files across restarts
STATE_FILE = os.path.expanduser("~/.sowknow-uploader-state.json")
LOG_FILE = os.path.expanduser("~/Library/Logs/sowknow-auto-uploader.log")

# Supported file extensions
SUPPORTED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".txt", ".csv", ".json", ".xml", ".html", ".htm", ".md", ".rtf",
}

# =============================================================================
# LOGGING
# =============================================================================
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
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
        self.uploaded: dict[str, dict] = {}  # sha256 -> {filename, bucket, timestamp}
        self.daily_uploads: list[dict] = []
        self.daily_errors: list[dict] = []
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    data = json.load(f)
                self.uploaded = data.get("uploaded", {})
                self.daily_uploads = data.get("daily_uploads", [])
                self.daily_errors = data.get("daily_errors", [])
            except (json.JSONDecodeError, KeyError):
                log.warning("Corrupt state file, starting fresh")

    def save(self):
        with open(self.path, "w") as f:
            json.dump({
                "uploaded": self.uploaded,
                "daily_uploads": self.daily_uploads,
                "daily_errors": self.daily_errors,
            }, f, indent=2)

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

    def flush_daily(self) -> tuple[list[dict], list[dict]]:
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
    def __init__(self, base_url: str, email: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SOWKNOW-AutoUploader/1.0"})
        self._authenticated = False

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
                log.info("Authenticated to SOWKNOW successfully")
                return True
            log.error(f"Login failed: {resp.status_code} {resp.text[:200]}")
            return False
        except requests.RequestException as e:
            log.error(f"Login request failed: {e}")
            return False

    def ensure_auth(self) -> bool:
        if self._authenticated:
            # Check an auth-required endpoint to verify token is still valid
            try:
                r = self.session.get(f"{self.base_url}/api/v1/auth/me", timeout=10)
                if r.status_code == 200:
                    return True
            except requests.RequestException:
                pass
            # Token expired or invalid, re-login
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
                    log.info(f"Uploaded (retry): {filename} -> {bucket}")
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


def process_file(filepath: str, bucket: str, client: SowknowClient, state: UploadState):
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
    # Wait for file to finish writing (size stable for 2 seconds)
    prev_size = -1
    for _ in range(10):
        try:
            curr_size = os.path.getsize(filepath)
        except OSError:
            return
        if curr_size == prev_size and curr_size > 0:
            break
        prev_size = curr_size
        time.sleep(1)

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


def scan_existing(directory: str, bucket: str, client: SowknowClient, state: UploadState):
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
    def __init__(self, bucket: str, client: SowknowClient, state: UploadState):
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


def _send_report_email(uploads: list[dict], errors: list[dict]):
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


# =============================================================================
# MAIN
# =============================================================================
def main():
    if not SOWKNOW_EMAIL or not SOWKNOW_PASSWORD:
        log.error("Set SOWKNOW_EMAIL and SOWKNOW_PASSWORD (env vars or edit CONFIG section)")
        sys.exit(1)

    # Ensure watch directories exist
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    os.makedirs(CONFIDENTIAL_DIR, exist_ok=True)

    state = UploadState(STATE_FILE)
    client = SowknowClient(SOWKNOW_URL, SOWKNOW_EMAIL, SOWKNOW_PASSWORD)

    log.info(f"SOWKNOW Auto-Uploader starting")
    log.info(f"  API:          {SOWKNOW_URL}")
    log.info(f"  Public dir:   {PUBLIC_DIR}")
    log.info(f"  Confid. dir:  {CONFIDENTIAL_DIR}")
    log.info(f"  State file:   {STATE_FILE}")

    # Initial login
    if not client.login():
        log.error("Initial login failed — will retry on first upload")

    # Scan existing files on startup
    log.info("Scanning existing files...")
    scan_existing(PUBLIC_DIR, "public", client, state)
    scan_existing(CONFIDENTIAL_DIR, "confidential", client, state)
    log.info("Initial scan complete")

    # Start daily report thread
    stop_event = Event()
    report_thread = Thread(target=send_daily_report, args=(state, stop_event), daemon=True)
    report_thread.start()

    # Start filesystem watchers
    observer = Observer()
    observer.schedule(UploadHandler("public", client, state), PUBLIC_DIR, recursive=False)
    observer.schedule(UploadHandler("confidential", client, state), CONFIDENTIAL_DIR, recursive=False)
    observer.start()

    log.info("Watching for new documents... (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        stop_event.set()
        observer.stop()
        observer.join()
        log.info("Stopped.")


if __name__ == "__main__":
    main()
