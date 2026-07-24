#!/usr/bin/env python3
"""Encrypt existing confidential files at rest (one-time migration).

The confidential bucket was stored PLAINTEXT until 2026-07-24 because
STORAGE_ENCRYPTION_KEY was never set in production (7,111 documents /
12,611 files affected, including .txt sidecars holding extracted text).

This script encrypts every file in /data/confidential IN PLACE (no renames,
no DB changes). Read paths tolerate the mixed state:
  - storage_service.get_file auto-decrypts for bucket=confidential and
    falls back to raw bytes for legacy plaintext
  - the pipeline OCR/chunk stages use decrypt_bytes_lenient

Idempotent: files that already decrypt with the configured key are skipped.

Usage (inside the backend container, key must be set):
    python scripts/encrypt_confidential_at_rest.py          # dry-run
    python scripts/encrypt_confidential_at_rest.py --apply  # write changes
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.storage_service import storage_service  # noqa: E402

CONFIDENTIAL_DIR = "/data/confidential"


def main() -> None:
    apply = "--apply" in sys.argv

    if not storage_service.encryption_ready:
        print("ERROR: STORAGE_ENCRYPTION_KEY is not set — cannot encrypt.")
        sys.exit(1)

    fernet = storage_service._fernet  # migration tooling; use the same key

    encrypted_already = 0
    to_encrypt = 0
    encrypted_now = 0
    errors = 0

    for entry in sorted(os.listdir(CONFIDENTIAL_DIR)):
        path = os.path.join(CONFIDENTIAL_DIR, entry)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as e:
            print(f"READ-ERROR {entry}: {e}")
            errors += 1
            continue

        try:
            fernet.decrypt(data)
            encrypted_already += 1
            continue
        except Exception:
            pass  # plaintext — needs encryption

        to_encrypt += 1
        if apply:
            try:
                token = fernet.encrypt(data)
                tmp = path + ".enc-tmp"
                with open(tmp, "wb") as fh:
                    fh.write(token)
                os.replace(tmp, path)
                encrypted_now += 1
                if encrypted_now % 500 == 0:
                    print(f"progress: {encrypted_now} encrypted…", flush=True)
            except Exception as e:
                print(f"ENCRYPT-ERROR {entry}: {e}")
                errors += 1

    mode = "APPLY" if apply else "DRY-RUN"
    print(
        f"[{mode}] already_encrypted={encrypted_already} "
        f"plaintext_found={to_encrypt} encrypted_now={encrypted_now} errors={errors}"
    )
    if not apply and to_encrypt:
        print("Re-run with --apply to encrypt.")


if __name__ == "__main__":
    main()
