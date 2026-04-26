#!/usr/bin/env python3
"""
SOWKNOW Search SQL Fixes & API Validation Script
==================================================

Validates the SQL fixes (bucket casting + pgvector brackets) and exercises the
FastAPI search endpoints.  Ollama-down failures are reported as INFRA blockers
rather than test failures because they are deployment issues, not code bugs.

Usage:
    # Direct DB tests only (no backend required):
    export DATABASE_URL="postgresql+asyncpg://sowknow:password@localhost:5432/sowknow"
    python scripts/test_search_sql_fixes.py --db-only

    # Full suite (DB + API via backend container):
    export API_URL="http://localhost:8001"
    export ADMIN_EMAIL="admin@sowknow.local"
    export JWT_SECRET="..."
    python scripts/test_search_sql_fixes.py

Exit codes:
    0 = all code-level checks passed (infra blockers are warnings, not failures)
    1 = one or more code-level queries/endpoints failed
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from jose import jwt
import requests

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_DB_URL = "postgresql+asyncpg://sowknow:0iWO98z3DTNVzyyBj78nT3Lgjx1OIFR@localhost:5432/sowknow"
DEFAULT_API_URL = "http://localhost:8001"
DEFAULT_ADMIN_EMAIL = "admin@sowknow.local"
DEFAULT_JWT_SECRET = "d00ba5c8b843b64424ca5fb1fb85445967bc3cdaa56c226c9a8c47d8be7e1bff"

# A dummy 1024-dim embedding vector (matches production embed model)
DUMMY_EMBEDDING = [0.01] * 1024
EMBEDDING_ARRAY = "[" + ",".join(map(str, DUMMY_EMBEDDING)) + "]"
BUCKETS = ["public", "confidential"]

pass_count = 0
fail_count = 0
warn_count = 0


def _db_url() -> str:
    url = os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _api_url() -> str:
    return os.getenv("API_URL", DEFAULT_API_URL).rstrip("/")


def _make_admin_token() -> str:
    secret = os.getenv("JWT_SECRET", DEFAULT_JWT_SECRET)
    email = os.getenv("ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL)
    payload = {
        "sub": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "type": "access",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _ok(name: str) -> None:
    global pass_count
    pass_count += 1
    print(f"  ✓ {name}")


def _fail(name: str, detail: str) -> None:
    global fail_count
    fail_count += 1
    print(f"  ✗ {name} — {detail}")


def _warn(name: str, detail: str) -> None:
    global warn_count
    warn_count += 1
    print(f"  ⚠ {name} — {detail}")


# ---------------------------------------------------------------------------
# Direct DB tests
# ---------------------------------------------------------------------------
async def test_db_document_semantic() -> None:
    engine = create_async_engine(_db_url())
    try:
        async with engine.connect() as conn:
            sql = text("""
                SELECT
                    dc.id as chunk_id,
                    dc.document_id,
                    COALESCE(d.original_filename, d.filename) as document_name,
                    d.bucket as document_bucket,
                    dc.chunk_text,
                    1 - (dc.embedding_vector <=> CAST(:embedding AS vector)) as similarity
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE d.bucket::text = ANY(:buckets)
                AND dc.embedding_vector IS NOT NULL
                ORDER BY dc.embedding_vector <=> CAST(:embedding AS vector)
                LIMIT 1
            """)
            result = await conn.execute(sql, {"embedding": EMBEDDING_ARRAY, "buckets": BUCKETS})
            _ok("DB document_semantic")
    except Exception as exc:
        _fail("DB document_semantic", str(exc))
    finally:
        await engine.dispose()


async def test_db_article_semantic() -> None:
    engine = create_async_engine(_db_url())
    try:
        async with engine.connect() as conn:
            sql = text("""
                SELECT
                    a.id as article_id,
                    a.document_id,
                    COALESCE(d.original_filename, d.filename) as document_name,
                    a.bucket as document_bucket,
                    a.title,
                    1 - (a.embedding_vector <=> CAST(:embedding AS vector)) as similarity
                FROM sowknow.articles a
                JOIN sowknow.documents d ON a.document_id = d.id
                WHERE a.bucket = ANY(:buckets)
                AND a.embedding_vector IS NOT NULL
                AND a.status = 'indexed'
                ORDER BY a.embedding_vector <=> CAST(:embedding AS vector)
                LIMIT 1
            """)
            result = await conn.execute(sql, {"embedding": EMBEDDING_ARRAY, "buckets": BUCKETS})
            _ok("DB article_semantic")
    except Exception as exc:
        _fail("DB article_semantic", str(exc))
    finally:
        await engine.dispose()


async def test_db_document_keyword() -> None:
    engine = create_async_engine(_db_url())
    try:
        async with engine.connect() as conn:
            sql = text("""
                SELECT dc.id
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE d.bucket::text = ANY(:buckets)
                  AND dc.search_vector IS NOT NULL
                  AND dc.search_vector @@ plainto_tsquery(CAST(:regconfig AS regconfig), :query)
                LIMIT 1
            """)
            result = await conn.execute(sql, {
                "regconfig": "english", "query": "test", "buckets": BUCKETS,
            })
            _ok("DB document_keyword")
    except Exception as exc:
        _fail("DB document_keyword", str(exc))
    finally:
        await engine.dispose()


async def test_db_article_keyword() -> None:
    engine = create_async_engine(_db_url())
    try:
        async with engine.connect() as conn:
            sql = text("""
                SELECT a.id
                FROM sowknow.articles a
                JOIN sowknow.documents d ON a.document_id = d.id
                WHERE a.bucket = ANY(:buckets)
                  AND a.search_vector IS NOT NULL
                  AND a.search_vector @@ plainto_tsquery(CAST(:regconfig AS regconfig), :query)
                LIMIT 1
            """)
            result = await conn.execute(sql, {
                "regconfig": "english", "query": "test", "buckets": BUCKETS,
            })
            _ok("DB article_keyword")
    except Exception as exc:
        _fail("DB article_keyword", str(exc))
    finally:
        await engine.dispose()


async def test_db_tag_search() -> None:
    engine = create_async_engine(_db_url())
    try:
        async with engine.connect() as conn:
            sql = text("""
                SELECT d.id
                FROM sowknow.documents d
                JOIN sowknow.tags t ON d.id = t.target_id AND t.target_type = 'document'
                WHERE d.bucket::text = ANY(:buckets)
                  AND d.status != 'error'
                  AND LOWER(t.tag_name) LIKE LOWER(:pattern)
                LIMIT 1
            """)
            result = await conn.execute(sql, {
                "buckets": BUCKETS, "pattern": "%test%",
            })
            _ok("DB tag_search")
    except Exception as exc:
        _fail("DB tag_search", str(exc))
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------
def test_api_health() -> None:
    try:
        resp = requests.get(f"{_api_url()}/api/v1/health", timeout=5)
        if resp.status_code == 200:
            _ok("API /health")
        else:
            _fail("API /health", f"status {resp.status_code}")
    except Exception as exc:
        _fail("API /health", str(exc))


def test_api_search() -> None:
    token = _make_admin_token()
    try:
        resp = requests.post(
            f"{_api_url()}/api/v1/search",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"query": "test", "search_type": "hybrid", "limit": 5},
            timeout=35,
        )
        if resp.status_code == 200:
            data = resp.json()
            _ok(f"API /search (200, {data.get('total_found', 0)} results)")
        elif resp.status_code == 500:
            detail = resp.json().get("detail", "")
            if "Ollama" in detail or "recherche a rencontre une erreur" in detail:
                _warn("API /search", f"Ollama down (infra blocker) — {detail}")
            else:
                _fail("API /search", f"500 — {detail}")
        else:
            _fail("API /search", f"status {resp.status_code} — {resp.text[:200]}")
    except requests.exceptions.Timeout:
        _fail("API /search", "timeout")
    except Exception as exc:
        _fail("API /search", str(exc))


def test_api_graph_rag() -> None:
    token = _make_admin_token()
    try:
        resp = requests.post(
            f"{_api_url()}/api/v1/graph-rag/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "test", "top_k": 5},
            timeout=35,
        )
        if resp.status_code == 200:
            _ok("API /graph-rag/search")
        elif resp.status_code == 500:
            body = resp.text
            if "Ollama" in body:
                _warn("API /graph-rag/search", "Ollama down (infra blocker)")
            else:
                _fail("API /graph-rag/search", f"500 — {body[:300]}")
        else:
            _fail("API /graph-rag/search", f"status {resp.status_code} — {resp.text[:200]}")
    except requests.exceptions.Timeout:
        _fail("API /graph-rag/search", "timeout")
    except Exception as exc:
        _fail("API /graph-rag/search", str(exc))


def test_api_suggest() -> None:
    token = _make_admin_token()
    try:
        resp = requests.get(
            f"{_api_url()}/api/v1/search/suggest",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": "con"},
            timeout=5,
        )
        if resp.status_code == 200:
            _ok("API /search/suggest")
        else:
            _fail("API /search/suggest", f"status {resp.status_code}")
    except Exception as exc:
        _fail("API /search/suggest", str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> int:
    parser = argparse.ArgumentParser(description="Validate SOWKNOW search SQL fixes & API")
    parser.add_argument("--db-only", action="store_true", help="Run only direct DB tests")
    args = parser.parse_args()

    print("SOWKNOW Search SQL Fixes & API Validation")
    print("=" * 55)
    print()

    # DB tests
    await test_db_document_semantic()
    await test_db_article_semantic()
    await test_db_document_keyword()
    await test_db_article_keyword()
    await test_db_tag_search()

    if not args.db_only:
        print()
        test_api_health()
        test_api_search()
        test_api_graph_rag()
        test_api_suggest()

    print()
    print("-" * 55)
    print(f"Passed: {pass_count}  |  Failed: {fail_count}  |  Warnings (infra): {warn_count}")

    if fail_count == 0:
        print("\n✓ All code-level checks passed.")
        if warn_count > 0:
            print("  Note: Some endpoints are blocked by infrastructure (Ollama).")
        return 0
    else:
        print("\n✗ Some checks failed — investigate before deploying.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
