#!/usr/bin/env python3
"""
One-time migration script to encrypt existing confidential documents.

This script:
1. Scans the confidential bucket for unencrypted files
2. Encrypts each file in place, adding .encrypted extension
3. Updates the database to track encryption status
4. Logs progress and errors

Usage:
    python scripts/encrypt_confidential_documents.py [--dry-run] [--limit N]

Environment:
    STORAGE_ENCRYPTION_KEY: Required - Fernet key or password for encryption
    STORAGE_ENCRYPTION_SALT: Optional - Salt for key derivation
    DATABASE_URL: Required - PostgreSQL connection string
"""

import argparse
import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.storage_service import (
    StorageService,
    get_encryption_key,
    EncryptionError,
)
from app.models.document import Document, DocumentBucket
from app.database import SessionLocal

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_fernet_key_display(key: Optional[bytes]) -> str:
    """Show masked key for logging"""
    if not key:
        return "NOT SET"
    key_str = key.decode() if isinstance(key, bytes) else key
    if len(key_str) > 8:
        return f"{key_str[:4]}...{key_str[-4:]}"
    return "***"


def migrate_documents(dry_run: bool = False, limit: Optional[int] = None):
    """
    Migrate all confidential documents to encrypted storage.

    Args:
        dry_run: If True, only report files that would be encrypted
        limit: Maximum number of files to process
    """
    logger.info("=" * 60)
    logger.info("Starting confidential document encryption migration")
    logger.info("=" * 60)

    # Check encryption key
    encryption_key = get_encryption_key()
    logger.info(f"Encryption key: {get_fernet_key_display(encryption_key)}")

    if not encryption_key:
        logger.error("STORAGE_ENCRYPTION_KEY not set or invalid")
        logger.error("Cannot proceed with encryption migration")
        sys.exit(1)

    # Initialize storage service
    storage = StorageService()

    if not storage.encryption_enabled:
        logger.error("Encryption not enabled in storage service")
        sys.exit(1)

    logger.info(f"Encryption enabled: {storage.encryption_enabled}")

    # Get confidential bucket path
    confidential_path = storage.confidential_path
    logger.info(f"Confidential bucket path: {confidential_path}")

    if not confidential_path.exists():
        logger.warning(f"Confidential path does not exist: {confidential_path}")
        logger.warning("No documents to migrate")
        return

    # Find unencrypted files
    unencrypted_files = []
    for file_path in confidential_path.iterdir():
        if file_path.is_file() and not file_path.name.endswith(".encrypted"):
            unencrypted_files.append(file_path.name)

    total_files = len(unencrypted_files)
    logger.info(f"Found {total_files} unencrypted files in confidential bucket")

    if limit:
        logger.info(f"Processing limit: {limit} files")
        unencrypted_files = unencrypted_files[:limit]

    if dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN MODE - No files will be modified")
        logger.info("=" * 60)
        for filename in unencrypted_files:
            logger.info(f"Would encrypt: {filename}")
        logger.info(f"Total files that would be encrypted: {len(unencrypted_files)}")
        return

    # Process files
    success_count = 0
    error_count = 0
    skipped_count = 0

    for filename in unencrypted_files:
        try:
            logger.info(f"Encrypting: {filename}")

            # Encrypt the file
            result = storage.encrypt_file(filename, bucket="confidential")

            if result:
                # Update database if needed
                db = SessionLocal()
                try:
                    # Find document by filename (without .encrypted extension)
                    original_filename = filename
                    doc = (
                        db.query(Document)
                        .filter(Document.filename == original_filename)
                        .first()
                    )

                    if doc:
                        # Update filename to include .encrypted
                        new_filename = original_filename + ".encrypted"
                        doc.filename = new_filename
                        doc.metadata = doc.metadata or {}
                        doc.metadata["encrypted"] = True
                        doc.metadata["encrypted_at"] = datetime.utcnow().isoformat()
                        db.commit()
                        logger.info(f"  Updated database: {doc.id}")
                    else:
                        logger.warning(
                            f"  Document not found in database: {original_filename}"
                        )
                finally:
                    db.close()

                success_count += 1
            else:
                logger.error(f"  Failed to encrypt: {filename}")
                error_count += 1

        except Exception as e:
            logger.error(f"  Error processing {filename}: {e}")
            error_count += 1

    # Summary
    logger.info("=" * 60)
    logger.info("MIGRATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total unencrypted files: {total_files}")
    logger.info(f"Successfully encrypted: {success_count}")
    logger.info(f"Errors: {error_count}")
    logger.info(f"Skipped: {skipped_count}")

    if error_count > 0:
        logger.warning(f"Errors occurred during migration - review logs above")
        sys.exit(1)


def rollback_migration(dry_run: bool = False, limit: Optional[int] = None):
    """
    Rollback: Decrypt all encrypted confidential documents.

    WARNING: This is for emergency rollback only. Should not be needed
    if migration was successful.

    Args:
        dry_run: If True, only report files that would be decrypted
        limit: Maximum number of files to process
    """
    logger.info("=" * 60)
    logger.info("Starting confidential document DECRYPTION (ROLLBACK)")
    logger.info("=" * 60)

    # Check encryption key
    encryption_key = get_encryption_key()

    if not encryption_key:
        logger.error("STORAGE_ENCRYPTION_KEY not set or invalid")
        sys.exit(1)

    # Initialize storage service
    storage = StorageService()

    # Get confidential bucket path
    confidential_path = storage.confidential_path

    # Find encrypted files
    encrypted_files = []
    for file_path in confidential_path.iterdir():
        if file_path.is_file() and file_path.name.endswith(".encrypted"):
            encrypted_files.append(file_path.name)

    total_files = len(encrypted_files)
    logger.info(f"Found {total_files} encrypted files in confidential bucket")

    if limit:
        logger.info(f"Processing limit: {limit} files")
        encrypted_files = encrypted_files[:limit]

    if dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN MODE - No files will be modified")
        logger.info("=" * 60)
        for filename in encrypted_files:
            logger.info(f"Would decrypt: {filename}")
        logger.info(f"Total files that would be decrypted: {len(encrypted_files)}")
        return

    # Process files
    success_count = 0
    error_count = 0

    for filename in encrypted_files:
        try:
            logger.info(f"Decrypting: {filename}")

            result = storage.decrypt_file(filename, bucket="confidential")

            if result:
                # Update database
                db = SessionLocal()
                try:
                    encrypted_filename = filename
                    original_filename = filename.replace(".encrypted", "")

                    doc = (
                        db.query(Document)
                        .filter(Document.filename == encrypted_filename)
                        .first()
                    )

                    if doc:
                        doc.filename = original_filename
                        doc.metadata = doc.metadata or {}
                        doc.metadata["encrypted"] = False
                        doc.metadata["decrypted_at"] = datetime.utcnow().isoformat()
                        db.commit()
                        logger.info(f"  Updated database: {doc.id}")
                finally:
                    db.close()

                success_count += 1
            else:
                logger.error(f"  Failed to decrypt: {filename}")
                error_count += 1

        except Exception as e:
            logger.error(f"  Error processing {filename}: {e}")
            error_count += 1

    # Summary
    logger.info("=" * 60)
    logger.info("ROLLBACK COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total encrypted files: {total_files}")
    logger.info(f"Successfully decrypted: {success_count}")
    logger.info(f"Errors: {error_count}")


def verify_encryption():
    """Verify that all confidential documents are encrypted"""
    logger.info("=" * 60)
    logger.info("Verifying confidential document encryption")
    logger.info("=" * 60)

    # Initialize storage
    storage = StorageService()
    confidential_path = storage.confidential_path

    if not confidential_path.exists():
        logger.warning(f"Confidential path does not exist")
        return

    # Find all files
    unencrypted = []
    encrypted = []

    for file_path in confidential_path.iterdir():
        if file_path.is_file():
            if file_path.name.endswith(".encrypted"):
                encrypted.append(file_path.name)
            else:
                unencrypted.append(file_path.name)

    logger.info(f"Encrypted files: {len(encrypted)}")
    logger.info(f"Unencrypted files: {len(unencrypted)}")

    if unencrypted:
        logger.warning("UNENCRYPTED FILES FOUND:")
        for f in unencrypted:
            logger.warning(f"  {f}")
        return False

    logger.info("All confidential documents are encrypted!")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Encrypt or decrypt confidential documents at rest"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit number of files to process"
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Decrypt files instead of encrypting (emergency rollback)",
    )
    parser.add_argument(
        "--verify", action="store_true", help="Verify encryption status only"
    )

    args = parser.parse_args()

    if args.verify:
        success = verify_encryption()
        sys.exit(0 if success else 1)

    if args.rollback:
        rollback_migration(dry_run=args.dry_run, limit=args.limit)
    else:
        migrate_documents(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
