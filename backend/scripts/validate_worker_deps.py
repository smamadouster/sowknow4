#!/usr/bin/env python3
"""Validate that all required extraction dependencies are available.
Called from worker-entrypoint.sh before starting the Celery worker.
Exits with code 1 if any required dependency is missing.
"""
import importlib.util
import subprocess
import sys

REQUIRED = {
    "Python packages": [
        ("xlrd", "xlrd"),
        ("openpyxl", "openpyxl"),
        ("python-pptx", "pptx"),
        ("spacy", "spacy"),
        ("sentence_transformers", "sentence_transformers"),
    ],
    "System binaries": [
        ("Tesseract OCR", "tesseract"),
        ("antiword (legacy .doc)", "antiword"),
        ("catppt (legacy .ppt)", "catppt"),
        ("whisper-cpp", "whisper-cpp"),
    ],
}


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _has_binary(name: str) -> bool:
    return subprocess.run(["which", name], capture_output=True).returncode == 0


def main() -> int:
    failed = False
    for category, items in REQUIRED.items():
        for label, key in items:
            if category == "Python packages":
                ok = _has_module(key)
            else:
                ok = _has_binary(key)
            status = "✓" if ok else "✗ MISSING"
            print(f"  [{status}] {label}")
            if not ok:
                failed = True

    if failed:
        print("\nFATAL: One or more required dependencies are missing. Worker will not start.")
        print("Install missing packages and restart the worker container.")
        return 1

    print("\nAll dependencies validated. Worker starting...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
