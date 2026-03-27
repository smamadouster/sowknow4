"""
Root conftest.py — adds backend/ to sys.path so `from app.xxx import ...` works
in all tests under tests/.
"""

import os
import sys
from pathlib import Path

# Add backend/ to the front of sys.path so app imports resolve
BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Set minimal environment variables before any app module is imported
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-do-not-use-in-production")
os.environ.setdefault("CELERY_MEMORY_WARNING_MB", "1400")
os.environ.setdefault("REPORTS_DIR", "/tmp/sowknow_test_reports")
