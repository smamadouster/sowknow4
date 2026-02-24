"""
encrypt_existing_confidential.py — Fernet-encrypt pre-existing confidential files
that were stored before at-rest encryption was activated (storage_service.py).

Only touches files in the confidential bucket that do NOT already carry the
.encrypted extension — the script is fully idempotent.

Usage:
    python -m scripts.encrypt_existing_confidential [--dry-run] [--data-dir PATH]

Options:
    --dry-run    List files that would be encrypted without touching them
    --data-dir   Root data directory (default: /data)

Required env var:
    STORAGE_ENCRYPTION_KEY   A valid Fernet key (base64-encoded 32 bytes)
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fernet-encrypt existing confidential files"
    )
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    parser.add_argument("--data-dir", default="/data", metavar="PATH")
    return parser.parse_args()


def _load_fernet():
    key = os.getenv("STORAGE_ENCRYPTION_KEY")
    if not key:
        logger.error("STORAGE_ENCRYPTION_KEY is not set — cannot encrypt")
        sys.exit(1)
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        logger.error(f"Invalid STORAGE_ENCRYPTION_KEY: {exc}")
        sys.exit(1)


def main() -> None:
    args = parse_args()
    confidential_dir = Path(args.data_dir) / "confidential"

    if not confidential_dir.is_dir():
        logger.error(f"Confidential directory not found: {confidential_dir}")
        sys.exit(1)

    fernet = None if args.dry_run else _load_fernet()

    eligible = [
        p for p in confidential_dir.rglob("*")
        if p.is_file() and not p.name.endswith(".encrypted")
    ]

    logger.info(f"Files eligible for encryption: {len(eligible)}")

    if args.dry_run:
        for p in eligible:
            logger.info(f"  [DRY-RUN] would encrypt: {p}")
        return

    encrypted = 0
    errors = 0

    for filepath in eligible:
        try:
            plaintext = filepath.read_bytes()
            ciphertext = fernet.encrypt(plaintext)
            encrypted_path = filepath.with_name(filepath.name + ".encrypted")
            encrypted_path.write_bytes(ciphertext)
            filepath.unlink()
            logger.info(
                f"Encrypted: {filepath.name} -> {encrypted_path.name} "
                f"({len(plaintext)} -> {len(ciphertext)} bytes)"
                f" [{datetime.now(timezone.utc).isoformat()}]"
            )
            encrypted += 1
        except Exception as exc:
            logger.error(f"Failed to encrypt {filepath}: {exc}")
            errors += 1

    logger.info(f"Encryption complete — {encrypted} files encrypted, {errors} errors")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
