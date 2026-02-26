"""
Unit test conftest — lightweight fixtures for tests that do not need a real DB.

This conftest intentionally avoids importing app.main, app.database, or
any other module that triggers async-engine creation or external service
connections.  Tests in this directory should be runnable in any environment
that has the project dependencies installed (i.e. without Docker or PostgreSQL).

Integration/E2E tests that need the full stack should use the root-level
tests/conftest.py which requires Docker + PostgreSQL.
"""
import os

# Prevent the parent conftest from failing on missing DB connection.
# We set a placeholder URL; pure-unit tests never touch the DB.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_unit.db")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("JWT_SECRET", "unit-test-secret-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
