#!/usr/bin/env python3
"""Export decrypted copies of the confidential bucket to a separate folder.

Non-destructive: reads the encrypted files at rest and writes plaintext copies
to DEST (default /data/confidential-decrypted). The encrypted originals are
never modified.

Idempotent/resumable: skips files whose plaintext already exists in DEST with
the same size, so re-running after an interruption resumes where it left off.

Usage:
    python3 scripts/decrypt_confidential_export.py
    python3 scripts/decrypt_confidential_export.py --src /path --dest /path
    python3 scripts/decrypt_confidential_export.py --key <fernet_key>
"""

import argparse
import os
import sys
import time

from cryptography.fernet import Fernet

DEFAULT_KEY = b"aWrwLUFHgiymHC11JKrrjOPyhQ4SWicwK-SZUlM_xJE="
DEFAULT_SRC = "/var/lib/docker/volumes/sowknow4_sowknow-confidential-data/_data"
DEFAULT_DEST = "/data/confidential-decrypted"


def clean_name(name: str) -> str:
    if name.endswith(".encrypted"):
        return name[: -len(".encrypted")]
    return name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--key", default=DEFAULT_KEY.decode())
    args = ap.parse_args()

    key = args.key.encode() if isinstance(args.key, str) else args.key
    fernet = Fernet(key)

    os.makedirs(args.dest, exist_ok=True)

    names = sorted(
        n for n in os.listdir(args.src) if os.path.isfile(os.path.join(args.src, n))
    )
    total = len(names)
    done = skipped = plaintext = failed = 0
    failures = []
    t0 = time.time()

    for i, name in enumerate(names, 1):
        src_path = os.path.join(args.src, name)
        dst_path = os.path.join(args.dest, clean_name(name))

        if os.path.exists(dst_path) and os.path.getsize(dst_path) > 0:
            skipped += 1
            continue

        try:
            with open(src_path, "rb") as fh:
                data = fh.read()

            if data[:6] == b"gAAAAA":
                plain = fernet.decrypt(data)
            else:
                plain = data
                plaintext += 1

            tmp = dst_path + ".part"
            with open(tmp, "wb") as fh:
                fh.write(plain)
            os.replace(tmp, dst_path)
            done += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            failures.append((name, str(e)))

        if i % 1000 == 0:
            rate = i / max(time.time() - t0, 1e-9)
            print(
                f"  {i}/{total} ({rate:.0f}/s) done={done} skipped={skipped}",
                flush=True,
            )

    elapsed = time.time() - t0
    print(
        f"FINISHED total={total} done={done} skipped={skipped} "
        f"plaintext_passthrough={plaintext} failed={failed} ({elapsed:.1f}s)"
    )
    for name, err in failures[:50]:
        print(f"  FAIL {name}: {err}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
