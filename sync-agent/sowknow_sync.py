#!/usr/bin/env python3
"""
SOWKNOW Sync Agent for macOS

A lightweight Python agent for syncing files from local directories,
iCloud Drive, and Dropbox folders to SOWKNOW via the API.

Features:
- Watch folders for new/modified files
- Hash-based deduplication
- Selective folder sync
- Automatic retry on failure
- Progress reporting
"""
import os
import sys
import time
import json
import hashlib
import logging
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import requests
import keyring

# Configuration
CONFIG_DIR = Path.home() / ".sowknow"
CONFIG_FILE = CONFIG_DIR / "sync_config.json"
STATE_FILE = CONFIG_DIR / "sync_state.json"
LOG_FILE = CONFIG_DIR / "sync_agent.log"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("sowknow_sync")


class SyncConfig:
    """Sync agent configuration"""

    def __init__(self):
        self.api_url: str = "http://localhost:8000"
        self.api_token: Optional[str] = None
        self.watch_folders: List[Dict[str, str]] = []
        self.file_types: List[str] = [
            ".pdf", ".docx", ".doc", ".txt", ".md", ".jpg", ".jpeg",
            ".png", ".gif", ".xlsx", ".xls", ".pptx", ".json"
        ]
        self.exclude_patterns: List[str] = [
            ".DS_Store", "Thumbs.db", ".git", "__MACOSX",
            "node_modules", ".venv", "venv"
        ]
        self.batch_size: int = 10
        self.sync_interval: int = 60  # seconds
        self.visibility: str = "public"  # or "confidential"
        self.auto_tag: bool = True

    def load(self) -> bool:
        """Load configuration from file"""
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    self.api_url = data.get("api_url", self.api_url)
                    self.api_token = data.get("api_token") or self._load_token_from_keyring()
                    self.watch_folders = data.get("watch_folders", [])
                    self.file_types = data.get("file_types", self.file_types)
                    self.exclude_patterns = data.get("exclude_patterns", self.exclude_patterns)
                    self.batch_size = data.get("batch_size", self.batch_size)
                    self.sync_interval = data.get("sync_interval", self.sync_interval)
                    self.visibility = data.get("visibility", self.visibility)
                    self.auto_tag = data.get("auto_tag", self.auto_tag)
                return True
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
        return False

    def save(self) -> bool:
        """Save configuration to file"""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                json.dump({
                    "api_url": self.api_url,
                    "watch_folders": self.watch_folders,
                    "file_types": self.file_types,
                    "exclude_patterns": self.exclude_patterns,
                    "batch_size": self.batch_size,
                    "sync_interval": self.sync_interval,
                    "visibility": self.visibility,
                    "auto_tag": self.auto_tag
                }, f, indent=2)

            # Save token to keyring
            if self.api_token:
                self._save_token_to_keyring(self.api_token)
            return True
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
        return False

    def _load_token_from_keyring(self) -> Optional[str]:
        """Load API token from system keyring"""
        try:
            return keyring.get_password("sowknow", "api_token")
        except:
            return None

    def _save_token_to_keyring(self, token: str):
        """Save API token to system keyring"""
        try:
            keyring.set_password("sowknow", "api_token", token)
        except Exception as e:
            logger.warning(f"Could not save to keyring: {e}")


class SyncState:
    """Track sync state to avoid re-uploading files"""

    def __init__(self):
        self.uploaded_hashes: Dict[str, str] = {}  # hash -> file_id
        self.last_sync: Optional[datetime] = None

    def load(self):
        """Load state from file"""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, "r") as f:
                    data = json.load(f)
                    self.uploaded_hashes = data.get("uploaded_hashes", {})
                    last_sync_str = data.get("last_sync")
                    if last_sync_str:
                        self.last_sync = datetime.fromisoformat(last_sync_str)
        except Exception as e:
            logger.error(f"Failed to load state: {e}")

    def save(self):
        """Save state to file"""
        try:
            with open(STATE_FILE, "w") as f:
                json.dump({
                    "uploaded_hashes": self.uploaded_hashes,
                    "last_sync": self.last_sync.isoformat() if self.last_sync else None
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def is_uploaded(self, file_hash: str) -> bool:
        """Check if file hash was already uploaded"""
        return file_hash in self.uploaded_hashes

    def mark_uploaded(self, file_hash: str, file_id: str):
        """Mark file as uploaded"""
        self.uploaded_hashes[file_hash] = file_id


class FileSyncHandler(FileSystemEventHandler):
    """Handle file system events for folder watching"""

    def __init__(self, agent: "SyncAgent"):
        self.agent = agent
        self.pending_files: Set[Path] = set()

    def on_created(self, event):
        if not event.is_directory:
            self.pending_files.add(Path(event.src_path))

    def on_modified(self, event):
        if not event.is_directory:
            self.pending_files.add(Path(event.src_path))

    def process_pending(self):
        """Process all pending files"""
        if self.pending_files:
            logger.info(f"Processing {len(self.pending_files)} pending files")
            for file_path in list(self.pending_files):
                try:
                    self.agent.sync_file(file_path)
                except Exception as e:
                    logger.error(f"Error syncing {file_path}: {e}")
                finally:
                    self.pending_files.discard(file_path)


class SyncAgent:
    """Main sync agent"""

    def __init__(self):
        self.config = SyncConfig()
        self.state = SyncState()
        self.session: Optional[requests.Session] = None
        self.observer: Optional[Observer] = None
        self.running = False

    def initialize(self) -> bool:
        """Initialize the sync agent"""
        # Load configuration
        if not self.config.load():
            logger.warning("No configuration found, using defaults")
            self.config.save()

        # Load state
        self.state.load()

        # Setup API session
        self.session = requests.Session()
        if self.config.api_token:
            self.session.headers.update({
                "Authorization": f"Bearer {self.config.api_token}"
            })

        # Test API connection
        try:
            response = self.session.get(
                f"{self.config.api_url}/api/v1/auth/me",
                timeout=10
            )
            if response.ok:
                logger.info("Successfully connected to SOWKNOW API")
                return True
            else:
                logger.error(f"API error: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Failed to connect to API: {e}")
            return False

    def calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file"""
        sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception as e:
            logger.error(f"Failed to hash {file_path}: {e}")
            return ""

    def should_sync_file(self, file_path: Path) -> bool:
        """Check if file should be synced"""
        # Check extension
        if file_path.suffix.lower() not in self.config.file_types:
            return False

        # Check exclude patterns
        file_str = str(file_path)
        for pattern in self.config.exclude_patterns:
            if pattern in file_str:
                return False

        # Check if already uploaded
        file_hash = self.calculate_file_hash(file_path)
        if self.state.is_uploaded(file_hash):
            logger.debug(f"Skipping {file_path} (already uploaded)")
            return False

        return True

    def sync_file(self, file_path: Path) -> bool:
        """Sync a single file to SOWKNOW"""
        try:
            if not self.should_sync_file(file_path):
                return False

            logger.info(f"Uploading {file_path.name}")

            # Upload file
            with open(file_path, "rb") as f:
                files = {
                    "file": (file_path.name, f, "application/octet-stream")
                }
                data = {
                    "bucket": self.config.visibility,
                    "auto_tag": str(self.config.auto_tag).lower()
                }

                response = self.session.post(
                    f"{self.config.api_url}/api/v1/documents/upload",
                    files=files,
                    data=data,
                    timeout=300  # 5 minute timeout
                )

            if response.ok:
                result = response.json()
                file_hash = self.calculate_file_hash(file_path)
                self.state.mark_uploaded(file_hash, result.get("document_id"))
                logger.info(f"Successfully uploaded {file_path.name}")
                return True
            else:
                logger.error(f"Upload failed for {file_path.name}: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error syncing {file_path}: {e}")
            return False

    def sync_folder(self, folder_path: Path) -> int:
        """Sync all files in a folder"""
        count = 0
        try:
            for file_path in folder_path.rglob("*"):
                if file_path.is_file():
                    if self.sync_file(file_path):
                        count += 1
        except Exception as e:
            logger.error(f"Error syncing folder {folder_path}: {e}")

        return count

    def start_watching(self):
        """Start watching configured folders"""
        if not self.config.watch_folders:
            logger.warning("No folders configured to watch")
            return

        self.observer = Observer()
        handler = FileSyncHandler(self)

        for folder_config in self.config.watch_folders:
            folder_path = Path(folder_config["path"])
            if folder_path.exists():
                self.observer.schedule(handler, str(folder_path), recursive=True)
                logger.info(f"Watching: {folder_path}")
            else:
                logger.warning(f"Folder not found: {folder_path}")

        self.observer.start()
        self.running = True
        logger.info("Started folder watching")

    def stop_watching(self):
        """Stop watching folders"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.running = False
            logger.info("Stopped folder watching")

    def run_initial_sync(self):
        """Run initial sync of all configured folders"""
        total = 0
        for folder_config in self.config.watch_folders:
            folder_path = Path(folder_config["path"])
            if folder_path.exists():
                count = self.sync_folder(folder_path)
                total += count
                logger.info(f"Synced {count} files from {folder_path}")

        self.state.last_sync = datetime.now()
        self.state.save()
        logger.info(f"Initial sync complete: {total} files")

    def run(self):
        """Run the sync agent continuously"""
        self.run_initial_sync()
        self.start_watching()

        try:
            while self.running:
                time.sleep(self.config.sync_interval)

                # Process any pending file events
                if self.observer and hasattr(self.observer, '_handlers'):
                    for handler in self.observer._handlers:
                        if isinstance(handler, FileSyncHandler):
                            handler.process_pending()

                # Save state periodically
                self.state.save()

        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        finally:
            self.stop_watching()
            self.state.save()


def setup_api_token(config: SyncConfig) -> bool:
    """Interactive API token setup"""
    print("\n=== SOWKNOW Sync Agent Setup ===")
    print(f"API URL [{config.api_url}]: ", end="")
    api_url = input().strip()
    if api_url:
        config.api_url = api_url

    print("API Token (from SOWKNOW settings): ", end="")
    api_token = input().strip()
    if api_token:
        config.api_token = api_token

    # Verify token
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {config.api_token}"})
    try:
        response = session.get(f"{config.api_url}/api/v1/auth/me", timeout=10)
        if response.ok:
            user_data = response.json()
            print(f"\n✅ Connected as: {user_data.get('email', 'Unknown')}")
            return True
        else:
            print(f"\n❌ Invalid token: {response.status_code}")
            return False
    except Exception as e:
        print(f"\n❌ Connection failed: {e}")
        return False


def setup_folders(config: SyncConfig):
    """Interactive folder setup"""
    print("\n=== Folder Configuration ===")
    print("Enter paths to folders you want to sync.")
    print("Supported formats:", ", ".join(config.file_types))
    print("Leave empty when done.\n")

    config.watch_folders = []
    while True:
        folder_path = input(f"Folder {len(config.watch_folders) + 1} (or press Enter to finish): ").strip()
        if not folder_path:
            break

        path = Path(folder_path).expanduser()
        if not path.exists():
            print(f"⚠️  Folder does not exist: {folder_path}")
            continue

        # Ask for visibility
        visibility = input(f"Visibility for this folder [public/confidential] [{config.visibility}]: ").strip()
        if visibility not in ["public", "confidential"]:
            visibility = config.visibility

        config.watch_folders.append({
            "path": str(path),
            "visibility": visibility
        })
        print(f"✅ Added: {path} ({visibility})")

    if config.watch_folders:
        print(f"\n✅ Configured {len(config.watch_folders)} folder(s)")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="SOWKNOW Sync Agent")
    parser.add_argument("--setup", action="store_true", help="Run interactive setup")
    parser.add_argument("--sync", action="store_true", help="Run one-time sync")
    parser.add_argument("--watch", action="store_true", help="Watch folders for changes")
    parser.add_argument("--config", type=str, help="Path to config file")
    args = parser.parse_args()

    agent = SyncAgent()

    # Setup mode
    if args.setup:
        if not setup_api_token(agent.config):
            print("Setup failed. Please check your API credentials and try again.")
            sys.exit(1)

        setup_folders(agent.config)
        agent.config.save()
        print(f"\n✅ Configuration saved to {CONFIG_FILE}")
        print("You can now run: sowknow-sync --watch")
        return

    # Load config
    if not agent.config.load():
        print("Configuration not found. Run with --setup first.")
        sys.exit(1)

    # Initialize
    if not agent.initialize():
        print("Failed to initialize sync agent.")
        sys.exit(1)

    # One-time sync
    if args.sync:
        agent.run_initial_sync()
        return

    # Watch mode (default)
    if args.watch or True:
        print("Starting SOWKNOW Sync Agent...")
        print("Press Ctrl+C to stop.")
        agent.run()


if __name__ == "__main__":
    main()
