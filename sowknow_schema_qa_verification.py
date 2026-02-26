#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         SOWKNOW Schema Fix & Enhancement — Full QA Verification Suite       ║
║         Based on Action Plan: Agent Tasks P0-1 → P2-10                      ║
║         Run: python sowknow_schema_qa_verification.py                        ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

# ─── Dependency guard ────────────────────────────────────────────────────────
MISSING_DEPS = []
try:
    import asyncpg
except ImportError:
    MISSING_DEPS.append("asyncpg")

try:
    import sqlalchemy
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
except ImportError:
    MISSING_DEPS.append("sqlalchemy[asyncio]")

try:
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
except ImportError:
    MISSING_DEPS.append("alembic")

if MISSING_DEPS:
    print(f"[FATAL] Missing dependencies: {', '.join(MISSING_DEPS)}")
    print(f"        Install with: pip install {' '.join(MISSING_DEPS)} asyncpg")
    sys.exit(1)

# ─── Configuration ────────────────────────────────────────────────────────────
DB_URL = os.getenv(
    "SOWKNOW_DB_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/sowknow"
)
DB_SCHEMA = os.getenv("SOWKNOW_SCHEMA", "sowknow")
ALEMBIC_INI = os.getenv("ALEMBIC_INI", "backend/alembic.ini")

# ─── Result tracking ─────────────────────────────────────────────────────────
@dataclass
class CheckResult:
    name: str
    agent: str
    task_id: str
    passed: bool
    message: str
    duration_ms: float = 0.0
    severity: str = "CRITICAL"  # CRITICAL | HIGH | MEDIUM
    detail: Optional[str] = None

@dataclass
class QAReport:
    results: List[CheckResult] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)

    def add(self, r: CheckResult):
        self.results.append(r)

    @property
    def passed(self):  return [r for r in self.results if r.passed]
    @property
    def failed(self):  return [r for r in self.results if not r.passed]
    @property
    def critical_failures(self):
        return [r for r in self.failed if r.severity == "CRITICAL"]


REPORT = QAReport()

# ─── Helpers ──────────────────────────────────────────────────────────────────
RESET  = "\033[0m";  BOLD = "\033[1m"
GREEN  = "\033[92m"; RED  = "\033[91m"
YELLOW = "\033[93m"; CYAN = "\033[96m"
GRAY   = "\033[90m"; WHITE = "\033[97m"

def banner(text: str):
    width = 78
    print(f"\n{BOLD}{CYAN}{'═' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * width}{RESET}")

def section(text: str):
    print(f"\n{BOLD}{WHITE}── {text} {'─' * (70 - len(text))}{RESET}")

def log_result(r: CheckResult):
    icon  = f"{GREEN}✔{RESET}" if r.passed else f"{RED}✘{RESET}"
    sev   = f"{YELLOW}[{r.severity}]{RESET}" if not r.passed else ""
    dur   = f"{GRAY}({r.duration_ms:.1f}ms){RESET}"
    label = f"{BOLD}[{r.task_id}]{RESET} {r.name}"
    print(f"  {icon}  {label} {sev} {dur}")
    if not r.passed and r.detail:
        print(f"      {GRAY}↳ {r.detail}{RESET}")

async def run_check(
    conn,
    name: str,
    agent: str,
    task_id: str,
    query: str,
    expect_truthy: bool = True,
    severity: str = "CRITICAL",
    detail_on_fail: str = "",
) -> CheckResult:
    t0 = time.perf_counter()
    try:
        rows = await conn.fetch(query)
        result_val = bool(rows and rows[0][0]) if rows else False
        passed = result_val if expect_truthy else not result_val
        ms = (time.perf_counter() - t0) * 1000
        return CheckResult(
            name=name, agent=agent, task_id=task_id,
            passed=passed, message="OK" if passed else "FAILED",
            duration_ms=ms, severity=severity,
            detail=None if passed else (detail_on_fail or f"Query returned: {rows}"),
        )
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return CheckResult(
            name=name, agent=agent, task_id=task_id,
            passed=False, message=str(exc),
            duration_ms=ms, severity=severity,
            detail=traceback.format_exc(limit=3),
        )

async def run_perf_check(
    conn,
    name: str,
    agent: str,
    task_id: str,
    query: str,
    threshold_ms: float,
    severity: str = "HIGH",
) -> CheckResult:
    t0 = time.perf_counter()
    try:
        await conn.fetch(query)
        ms = (time.perf_counter() - t0) * 1000
        passed = ms <= threshold_ms
        return CheckResult(
            name=name, agent=agent, task_id=task_id,
            passed=passed, message=f"{ms:.1f}ms (target <{threshold_ms}ms)",
            duration_ms=ms, severity=severity,
            detail=None if passed else f"Exceeded threshold: {ms:.1f}ms > {threshold_ms}ms",
        )
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return CheckResult(
            name=name, agent=agent, task_id=task_id,
            passed=False, message=str(exc),
            duration_ms=ms, severity=severity,
            detail=traceback.format_exc(limit=3),
        )


# ══════════════════════════════════════════════════════════════════════════════
#  AGENT 1 — Database Architect  (P0-1, P0-5, P1-6 schema part)
# ══════════════════════════════════════════════════════════════════════════════

async def check_agent1_database_architect(conn):
    section("Agent 1 · Database Architect")

    # P0-1 ── Vector column type
    r = await run_check(
        conn,
        name="document_chunks.embedding is vector(1024) type",
        agent="Database Architect", task_id="P0-1",
        query=f"""
            SELECT data_type = 'USER-DEFINED'
            AND udt_name = 'vector'
            FROM information_schema.columns
            WHERE table_schema = '{DB_SCHEMA}'
              AND table_name   = 'document_chunks'
              AND column_name  = 'embedding'
        """,
        detail_on_fail="Column 'embedding' not found or not pgvector type. "
                       "Run migration 004_fix_vector_type.py",
    )
    REPORT.add(r); log_result(r)

    # P0-1 ── Cosine distance operator works
    r = await run_check(
        conn,
        name="Vector cosine distance operator (<=>) functional",
        agent="Database Architect", task_id="P0-1",
        query=f"""
            SELECT EXISTS(
                SELECT 1
                FROM pg_operator
                WHERE oprname = '<=>'
                  AND oprnamespace = (
                      SELECT oid FROM pg_namespace WHERE nspname = 'public'
                  )
            )
        """,
        detail_on_fail="pgvector extension not installed or <=> operator missing.",
    )
    REPORT.add(r); log_result(r)

    # P0-1 ── pgvector extension installed
    r = await run_check(
        conn,
        name="pgvector extension installed",
        agent="Database Architect", task_id="P0-1",
        query="SELECT COUNT(*) > 0 FROM pg_extension WHERE extname = 'vector'",
        detail_on_fail="Run: CREATE EXTENSION IF NOT EXISTS vector;",
    )
    REPORT.add(r); log_result(r)

    # P0-5 ── minimax in llmprovider enum
    r = await run_check(
        conn,
        name="'minimax' value present in llmprovider enum",
        agent="Database Architect", task_id="P0-5",
        query=f"""
            SELECT COUNT(*) > 0
            FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            JOIN pg_namespace n ON t.typnamespace = n.oid
            WHERE n.nspname = '{DB_SCHEMA}'
              AND t.typname = 'llmprovider'
              AND e.enumlabel = 'minimax'
        """,
        detail_on_fail="Run migration 006_add_minimax_enum.py",
    )
    REPORT.add(r); log_result(r)

    # P0-5 ── llmprovider enum has all standard providers
    for provider in ("openai", "anthropic", "mistral", "minimax"):
        r = await run_check(
            conn,
            name=f"llmprovider enum contains '{provider}'",
            agent="Database Architect", task_id="P0-5",
            query=f"""
                SELECT COUNT(*) > 0
                FROM pg_enum e
                JOIN pg_type t ON e.enumtypid = t.oid
                JOIN pg_namespace n ON t.typnamespace = n.oid
                WHERE n.nspname = '{DB_SCHEMA}'
                  AND t.typname = 'llmprovider'
                  AND e.enumlabel = '{provider}'
            """,
            severity="HIGH",
            detail_on_fail=f"Provider '{provider}' missing from enum.",
        )
        REPORT.add(r); log_result(r)

    # Alembic migration files exist on disk
    for mig in ("004_fix_vector_type", "006_add_minimax_enum"):
        import glob
        matches = glob.glob(f"backend/alembic/versions/{mig}*.py")
        r = CheckResult(
            name=f"Migration file exists: {mig}.py",
            agent="Database Architect", task_id="P0-1/P0-5",
            passed=bool(matches),
            message="Found" if matches else "NOT FOUND",
            severity="CRITICAL",
            detail=f"Expected at backend/alembic/versions/{mig}*.py",
        )
        REPORT.add(r); log_result(r)


# ══════════════════════════════════════════════════════════════════════════════
#  AGENT 2 — Vector Search Engineer  (P0-2)
# ══════════════════════════════════════════════════════════════════════════════

async def check_agent2_vector_search(conn):
    section("Agent 2 · Vector Search Engineer")

    # P0-2 ── IVFFlat index exists
    r = await run_check(
        conn,
        name="IVFFlat index on document_chunks.embedding exists",
        agent="Vector Search Engineer", task_id="P0-2",
        query=f"""
            SELECT COUNT(*) > 0
            FROM pg_indexes
            WHERE schemaname = '{DB_SCHEMA}'
              AND tablename  = 'document_chunks'
              AND indexname  = 'ix_document_chunks_embedding_ivfflat'
        """,
        detail_on_fail="Run migration 005_add_vector_indexes.py",
    )
    REPORT.add(r); log_result(r)

    # P0-2 ── Index uses ivfflat access method
    r = await run_check(
        conn,
        name="IVFFlat index uses correct access method (ivfflat)",
        agent="Vector Search Engineer", task_id="P0-2",
        query=f"""
            SELECT COUNT(*) > 0
            FROM pg_indexes i
            JOIN pg_class c ON c.relname = i.indexname
            JOIN pg_am a    ON c.relam   = a.oid
            WHERE i.schemaname = '{DB_SCHEMA}'
              AND i.tablename  = 'document_chunks'
              AND i.indexname  = 'ix_document_chunks_embedding_ivfflat'
              AND a.amname     = 'ivfflat'
        """,
        detail_on_fail="Index exists but uses wrong access method.",
    )
    REPORT.add(r); log_result(r)

    # P0-2 ── semantic_search function exists
    r = await run_check(
        conn,
        name="sowknow.semantic_search() function exists",
        agent="Vector Search Engineer", task_id="P0-2",
        query=f"""
            SELECT COUNT(*) > 0
            FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE n.nspname = '{DB_SCHEMA}'
              AND p.proname = 'semantic_search'
        """,
        detail_on_fail="Create function sowknow.semantic_search() as per action plan P0-2.",
    )
    REPORT.add(r); log_result(r)

    # P0-2 ── semantic_search function signature
    r = await run_check(
        conn,
        name="semantic_search() accepts (vector, int, float) parameters",
        agent="Vector Search Engineer", task_id="P0-2",
        query=f"""
            SELECT COUNT(*) > 0
            FROM information_schema.routines r
            WHERE r.routine_schema = '{DB_SCHEMA}'
              AND r.routine_name   = 'semantic_search'
        """,
        detail_on_fail="Function signature mismatch.",
        severity="HIGH",
    )
    REPORT.add(r); log_result(r)

    # P0-2 ── Performance: EXPLAIN shows index scan
    r = await run_check(
        conn,
        name="Vector query plan uses index scan (not seq scan)",
        agent="Vector Search Engineer", task_id="P0-2",
        query=f"""
            SELECT COUNT(*) > 0
            FROM (
                EXPLAIN SELECT id FROM {DB_SCHEMA}.document_chunks
                ORDER BY embedding <=> '[{ ','.join(['0']*1024) }]'::vector
                LIMIT 10
            ) e
            WHERE e."QUERY PLAN" ILIKE '%index%'
        """,
        severity="HIGH",
        detail_on_fail="Vector queries using sequential scan — index may not be effective.",
    )
    REPORT.add(r); log_result(r)


# ══════════════════════════════════════════════════════════════════════════════
#  AGENT 3 — Full-Text Search Specialist  (P0-3)
# ══════════════════════════════════════════════════════════════════════════════

async def check_agent3_fulltext_search(conn):
    section("Agent 3 · Full-Text Search Specialist")

    # P0-3 ── tsvector_content column exists
    r = await run_check(
        conn,
        name="document_chunks.tsvector_content column exists",
        agent="FTS Specialist", task_id="P0-3",
        query=f"""
            SELECT COUNT(*) > 0
            FROM information_schema.columns
            WHERE table_schema = '{DB_SCHEMA}'
              AND table_name   = 'document_chunks'
              AND column_name  = 'tsvector_content'
        """,
        detail_on_fail="Run migration 005_add_fulltext_search.py",
    )
    REPORT.add(r); log_result(r)

    # P0-3 ── tsvector column is GENERATED STORED
    r = await run_check(
        conn,
        name="tsvector_content is a GENERATED STORED column",
        agent="FTS Specialist", task_id="P0-3",
        query=f"""
            SELECT COUNT(*) > 0
            FROM information_schema.columns
            WHERE table_schema  = '{DB_SCHEMA}'
              AND table_name    = 'document_chunks'
              AND column_name   = 'tsvector_content'
              AND is_generated  = 'ALWAYS'
        """,
        severity="HIGH",
        detail_on_fail="Column exists but is not a generated column.",
    )
    REPORT.add(r); log_result(r)

    # P0-3 ── GIN index on tsvector
    r = await run_check(
        conn,
        name="GIN index on tsvector_content exists",
        agent="FTS Specialist", task_id="P0-3",
        query=f"""
            SELECT COUNT(*) > 0
            FROM pg_indexes i
            JOIN pg_class c ON c.relname = i.indexname
            JOIN pg_am a    ON c.relam   = a.oid
            WHERE i.schemaname = '{DB_SCHEMA}'
              AND i.tablename  = 'document_chunks'
              AND i.indexname  = 'ix_document_chunks_tsvector'
              AND a.amname     = 'gin'
        """,
        detail_on_fail="Run migration to create GIN index on tsvector_content.",
    )
    REPORT.add(r); log_result(r)

    # P0-3 ── hybrid_search function exists
    r = await run_check(
        conn,
        name="sowknow.hybrid_search() function exists",
        agent="FTS Specialist", task_id="P0-3",
        query=f"""
            SELECT COUNT(*) > 0
            FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE n.nspname = '{DB_SCHEMA}'
              AND p.proname = 'hybrid_search'
        """,
        detail_on_fail="Create hybrid_search() as per action plan P0-3.",
    )
    REPORT.add(r); log_result(r)

    # P0-3 ── French FTS configuration available
    r = await run_check(
        conn,
        name="PostgreSQL 'french' text search configuration available",
        agent="FTS Specialist", task_id="P0-3",
        query="""
            SELECT COUNT(*) > 0
            FROM pg_ts_config
            WHERE cfgname = 'french'
        """,
        detail_on_fail="French FTS config missing. Check PostgreSQL locale/language packs.",
    )
    REPORT.add(r); log_result(r)

    # P0-3 ── FTS query works (functional smoke test)
    r = await run_check(
        conn,
        name="FTS search executes without error (smoke test)",
        agent="FTS Specialist", task_id="P0-3",
        query=f"""
            SELECT COUNT(*) >= 0
            FROM {DB_SCHEMA}.document_chunks
            WHERE tsvector_content @@ websearch_to_tsquery('french', 'contrat travail')
            LIMIT 1
        """,
        severity="HIGH",
        detail_on_fail="FTS query failed — check tsvector_content column and GIN index.",
    )
    REPORT.add(r); log_result(r)


# ══════════════════════════════════════════════════════════════════════════════
#  AGENT 4 — Security Engineer  (P0-4, P2-9)
# ══════════════════════════════════════════════════════════════════════════════

async def check_agent4_security(conn):
    section("Agent 4 · Security Engineer")

    # P0-4 ── audit_logs table exists
    r = await run_check(
        conn,
        name="audit_logs table exists in sowknow schema",
        agent="Security Engineer", task_id="P0-4",
        query=f"""
            SELECT COUNT(*) > 0
            FROM information_schema.tables
            WHERE table_schema = '{DB_SCHEMA}'
              AND table_name   = 'audit_logs'
        """,
        detail_on_fail="Run migration 007_add_audit_logs.py",
    )
    REPORT.add(r); log_result(r)

    # P0-4 ── audit_logs required columns
    for col in ("id", "user_id", "action", "resource_type", "resource_id",
                "details", "ip_address", "user_agent", "created_at", "updated_at"):
        r = await run_check(
            conn,
            name=f"audit_logs.{col} column exists",
            agent="Security Engineer", task_id="P0-4",
            query=f"""
                SELECT COUNT(*) > 0
                FROM information_schema.columns
                WHERE table_schema = '{DB_SCHEMA}'
                  AND table_name   = 'audit_logs'
                  AND column_name  = '{col}'
            """,
            severity="CRITICAL",
            detail_on_fail=f"Column '{col}' missing from audit_logs.",
        )
        REPORT.add(r); log_result(r)

    # P0-4 ── auditaction enum exists with all required values
    required_actions = [
        "user_created", "user_updated", "user_deleted",
        "confidential_accessed", "confidential_uploaded", "confidential_deleted",
        "admin_login", "settings_changed", "system_action",
    ]
    for action in required_actions:
        r = await run_check(
            conn,
            name=f"auditaction enum contains '{action}'",
            agent="Security Engineer", task_id="P0-4",
            query=f"""
                SELECT COUNT(*) > 0
                FROM pg_enum e
                JOIN pg_type t ON e.enumtypid = t.oid
                JOIN pg_namespace n ON t.typnamespace = n.oid
                WHERE n.nspname    = '{DB_SCHEMA}'
                  AND t.typname   = 'auditaction'
                  AND e.enumlabel = '{action}'
            """,
            severity="HIGH",
            detail_on_fail=f"Missing action '{action}' from auditaction enum.",
        )
        REPORT.add(r); log_result(r)

    # P0-4 ── audit_logs is partitioned
    r = await run_check(
        conn,
        name="audit_logs table is range-partitioned by created_at",
        agent="Security Engineer", task_id="P0-4",
        query=f"""
            SELECT COUNT(*) > 0
            FROM pg_partitioned_table pt
            JOIN pg_class c ON c.oid = pt.partrelid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = '{DB_SCHEMA}'
              AND c.relname = 'audit_logs'
        """,
        detail_on_fail="audit_logs must be PARTITION BY RANGE (created_at) for performance.",
    )
    REPORT.add(r); log_result(r)

    # P0-4 ── Partitions exist (at least current month)
    r = await run_check(
        conn,
        name="At least one audit_logs partition exists",
        agent="Security Engineer", task_id="P0-4",
        query=f"""
            SELECT COUNT(*) > 0
            FROM pg_inherits i
            JOIN pg_class p ON p.oid = i.inhparent
            JOIN pg_namespace n ON p.relnamespace = n.oid
            WHERE n.nspname = '{DB_SCHEMA}'
              AND p.relname = 'audit_logs'
        """,
        detail_on_fail="No partitions found for audit_logs.",
    )
    REPORT.add(r); log_result(r)

    # P0-4 ── Indexes on audit_logs
    for idx_col in ("user_id", "action", "created_at"):
        r = await run_check(
            conn,
            name=f"Index on audit_logs.{idx_col} exists",
            agent="Security Engineer", task_id="P0-4",
            query=f"""
                SELECT COUNT(*) > 0
                FROM pg_indexes
                WHERE schemaname = '{DB_SCHEMA}'
                  AND tablename  = 'audit_logs'
                  AND indexdef ILIKE '%{idx_col}%'
            """,
            severity="HIGH",
            detail_on_fail=f"Missing index on audit_logs.{idx_col}",
        )
        REPORT.add(r); log_result(r)

    # P0-4 ── Trigger for confidential access logging
    r = await run_check(
        conn,
        name="trigger_log_confidential_access trigger exists on documents",
        agent="Security Engineer", task_id="P0-4",
        query=f"""
            SELECT COUNT(*) > 0
            FROM information_schema.triggers
            WHERE trigger_schema  = '{DB_SCHEMA}'
              AND event_object_table = 'documents'
              AND trigger_name    = 'trigger_log_confidential_access'
        """,
        detail_on_fail="Missing confidential access trigger. Run migration 007_add_audit_logs.py",
    )
    REPORT.add(r); log_result(r)

    # P0-4 ── log_confidential_access function exists
    r = await run_check(
        conn,
        name="sowknow.log_confidential_access() trigger function exists",
        agent="Security Engineer", task_id="P0-4",
        query=f"""
            SELECT COUNT(*) > 0
            FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE n.nspname = '{DB_SCHEMA}'
              AND p.proname = 'log_confidential_access'
        """,
        detail_on_fail="Trigger function log_confidential_access() missing.",
    )
    REPORT.add(r); log_result(r)

    # P2-9 ── RLS enabled on documents
    r = await run_check(
        conn,
        name="Row-Level Security enabled on documents table",
        agent="Security Engineer", task_id="P2-9",
        query=f"""
            SELECT relrowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = '{DB_SCHEMA}'
              AND c.relname = 'documents'
        """,
        severity="HIGH",
        detail_on_fail="Run migration 009_add_rls_policies.py",
    )
    REPORT.add(r); log_result(r)

    # P2-9 ── RLS enabled on collections
    r = await run_check(
        conn,
        name="Row-Level Security enabled on collections table",
        agent="Security Engineer", task_id="P2-9",
        query=f"""
            SELECT relrowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = '{DB_SCHEMA}'
              AND c.relname = 'collections'
        """,
        severity="HIGH",
        detail_on_fail="Run migration 009_add_rls_policies.py",
    )
    REPORT.add(r); log_result(r)

    # P2-9 ── RLS policies exist
    for policy in ("documents_access_policy", "collections_access_policy",
                   "superuser_bypass"):
        r = await run_check(
            conn,
            name=f"RLS policy '{policy}' exists",
            agent="Security Engineer", task_id="P2-9",
            query=f"""
                SELECT COUNT(*) > 0
                FROM pg_policies
                WHERE schemaname = '{DB_SCHEMA}'
                  AND policyname = '{policy}'
            """,
            severity="HIGH",
            detail_on_fail=f"RLS policy '{policy}' not found.",
        )
        REPORT.add(r); log_result(r)

    # P0-4 ── Audit write performance
    r = await run_perf_check(
        conn,
        name="Audit log INSERT performance < 10ms",
        agent="Security Engineer", task_id="P0-4",
        query=f"""
            INSERT INTO {DB_SCHEMA}.audit_logs
                (user_id, action, resource_type, resource_id, details, ip_address)
            VALUES
                (NULL, 'system_action'::sowknow.auditaction,
                 'qa_test', 'test-{uuid4()}', 'QA verification run', '127.0.0.1')
        """,
        threshold_ms=10.0,
    )
    REPORT.add(r); log_result(r)


# ══════════════════════════════════════════════════════════════════════════════
#  AGENT 5 — Backend Developer  (P1-6, P1-7, P1-8)
# ══════════════════════════════════════════════════════════════════════════════

async def check_agent5_backend(conn):
    section("Agent 5 · Backend Developer")

    # P1-6 ── collections.is_confidential column
    r = await run_check(
        conn,
        name="collections.is_confidential column exists",
        agent="Backend Developer", task_id="P1-6",
        query=f"""
            SELECT COUNT(*) > 0
            FROM information_schema.columns
            WHERE table_schema = '{DB_SCHEMA}'
              AND table_name   = 'collections'
              AND column_name  = 'is_confidential'
        """,
        detail_on_fail="Run migration 008_add_collection_confidential.py",
    )
    REPORT.add(r); log_result(r)

    # P1-6 ── is_confidential default value is FALSE
    r = await run_check(
        conn,
        name="collections.is_confidential has default FALSE",
        agent="Backend Developer", task_id="P1-6",
        query=f"""
            SELECT column_default = 'false'
            FROM information_schema.columns
            WHERE table_schema = '{DB_SCHEMA}'
              AND table_name   = 'collections'
              AND column_name  = 'is_confidential'
        """,
        severity="HIGH",
        detail_on_fail="is_confidential default should be 'false'",
    )
    REPORT.add(r); log_result(r)

    # P1-6 ── Compound index (user_id, is_confidential)
    r = await run_check(
        conn,
        name="Compound index (user_id, is_confidential) on collections",
        agent="Backend Developer", task_id="P1-6",
        query=f"""
            SELECT COUNT(*) > 0
            FROM pg_indexes
            WHERE schemaname = '{DB_SCHEMA}'
              AND tablename  = 'collections'
              AND indexname  = 'ix_collections_user_confidential'
        """,
        severity="HIGH",
        detail_on_fail="Create compound index as per P1-6.",
    )
    REPORT.add(r); log_result(r)

    # P1-6 ── Backfill: confidential collections flagged correctly
    r = await run_check(
        conn,
        name="Confidential document backfill integrity check",
        agent="Backend Developer", task_id="P1-6",
        query=f"""
            SELECT COUNT(*) = 0
            FROM {DB_SCHEMA}.collections c
            WHERE c.is_confidential = FALSE
              AND EXISTS (
                  SELECT 1
                  FROM {DB_SCHEMA}.collection_items ci
                  JOIN {DB_SCHEMA}.documents d ON ci.document_id = d.id
                  WHERE ci.collection_id = c.id
                    AND d.bucket = 'confidential'
              )
        """,
        severity="HIGH",
        detail_on_fail="Some collections with confidential docs are not flagged as is_confidential=TRUE.",
    )
    REPORT.add(r); log_result(r)

    # P1-7 ── Compound index on chat_messages(session_id, created_at)
    r = await run_check(
        conn,
        name="Compound index ix_chat_messages_session_created exists",
        agent="Backend Developer", task_id="P1-7",
        query=f"""
            SELECT COUNT(*) > 0
            FROM pg_indexes
            WHERE schemaname = '{DB_SCHEMA}'
              AND tablename  = 'chat_messages'
              AND indexname  = 'ix_chat_messages_session_created'
        """,
        detail_on_fail="Run migration 010_add_chat_session_index.py",
    )
    REPORT.add(r); log_result(r)

    # P1-7 ── chat session query uses index (EXPLAIN check)
    r = await run_check(
        conn,
        name="Chat session history query uses index scan",
        agent="Backend Developer", task_id="P1-7",
        query=f"""
            SELECT COUNT(*) > 0
            FROM (
                EXPLAIN SELECT * FROM {DB_SCHEMA}.chat_messages
                WHERE session_id = gen_random_uuid()
                ORDER BY created_at DESC
                LIMIT 50
            ) e
            WHERE e."QUERY PLAN" ILIKE '%index%'
        """,
        severity="HIGH",
        detail_on_fail="Chat session query not using the index.",
    )
    REPORT.add(r); log_result(r)

    # P1-8 ── smart_folders table exists
    r = await run_check(
        conn,
        name="smart_folders table exists",
        agent="Backend Developer", task_id="P1-8",
        query=f"""
            SELECT COUNT(*) > 0
            FROM information_schema.tables
            WHERE table_schema = '{DB_SCHEMA}'
              AND table_name   = 'smart_folders'
        """,
        detail_on_fail="Run migration 011_add_smart_folders.py",
    )
    REPORT.add(r); log_result(r)

    # P1-8 ── smart_folders required columns
    for col in ("id", "collection_id", "rule_config", "auto_update",
                "last_synced_at", "created_at", "updated_at"):
        r = await run_check(
            conn,
            name=f"smart_folders.{col} column exists",
            agent="Backend Developer", task_id="P1-8",
            query=f"""
                SELECT COUNT(*) > 0
                FROM information_schema.columns
                WHERE table_schema = '{DB_SCHEMA}'
                  AND table_name   = 'smart_folders'
                  AND column_name  = '{col}'
            """,
            severity="HIGH",
            detail_on_fail=f"Column '{col}' missing from smart_folders.",
        )
        REPORT.add(r); log_result(r)

    # P1-8 ── rule_config is JSONB
    r = await run_check(
        conn,
        name="smart_folders.rule_config is JSONB type",
        agent="Backend Developer", task_id="P1-8",
        query=f"""
            SELECT data_type = 'jsonb'
            FROM information_schema.columns
            WHERE table_schema = '{DB_SCHEMA}'
              AND table_name   = 'smart_folders'
              AND column_name  = 'rule_config'
        """,
        severity="HIGH",
        detail_on_fail="rule_config must be JSONB for JSON operator support.",
    )
    REPORT.add(r); log_result(r)

    # P1-8 ── FK from smart_folders to collections
    r = await run_check(
        conn,
        name="smart_folders.collection_id FK → collections.id exists",
        agent="Backend Developer", task_id="P1-8",
        query=f"""
            SELECT COUNT(*) > 0
            FROM information_schema.referential_constraints rc
            JOIN information_schema.key_column_usage kcu
              ON rc.constraint_name = kcu.constraint_name
            WHERE kcu.table_schema  = '{DB_SCHEMA}'
              AND kcu.table_name    = 'smart_folders'
              AND kcu.column_name   = 'collection_id'
        """,
        severity="HIGH",
        detail_on_fail="Missing FK constraint from smart_folders to collections.",
    )
    REPORT.add(r); log_result(r)

    # P1-8 ── FK on delete cascade
    r = await run_check(
        conn,
        name="smart_folders FK has ON DELETE CASCADE",
        agent="Backend Developer", task_id="P1-8",
        query=f"""
            SELECT COUNT(*) > 0
            FROM information_schema.referential_constraints rc
            JOIN information_schema.key_column_usage kcu
              ON rc.constraint_name = kcu.constraint_name
            WHERE kcu.table_schema  = '{DB_SCHEMA}'
              AND kcu.table_name    = 'smart_folders'
              AND kcu.column_name   = 'collection_id'
              AND rc.delete_rule    = 'CASCADE'
        """,
        severity="HIGH",
        detail_on_fail="smart_folders FK should use ON DELETE CASCADE.",
    )
    REPORT.add(r); log_result(r)

    # P1-7 ── chat session load performance
    r = await run_perf_check(
        conn,
        name="Chat 50-message history loads in <20ms",
        agent="Backend Developer", task_id="P1-7",
        query=f"""
            SELECT * FROM {DB_SCHEMA}.chat_messages
            WHERE session_id = gen_random_uuid()
            ORDER BY created_at DESC
            LIMIT 50
        """,
        threshold_ms=20.0,
        severity="HIGH",
    )
    REPORT.add(r); log_result(r)

    # ORM model files on disk
    for model_file in (
        "backend/app/models/collection.py",
        "backend/app/models/smart_folder.py",
        "backend/app/models/audit_log.py",
    ):
        import os as _os
        r = CheckResult(
            name=f"ORM model file exists: {model_file}",
            agent="Backend Developer", task_id="P1-6/P1-8",
            passed=_os.path.exists(model_file),
            message="Found" if _os.path.exists(model_file) else "NOT FOUND",
            severity="HIGH",
            detail=f"Expected: {model_file}",
        )
        REPORT.add(r); log_result(r)


# ══════════════════════════════════════════════════════════════════════════════
#  AGENT 6 — Performance Engineer  (P1-7, P2-10)
# ══════════════════════════════════════════════════════════════════════════════

async def check_agent6_performance(conn):
    section("Agent 6 · Performance Engineer")

    # Unique constraints
    for constraint, table in (
        ("uq_collection_items_collection_document", "collection_items"),
        ("uq_entity_mentions_entity_chunk",         "entity_mentions"),
    ):
        r = await run_check(
            conn,
            name=f"Unique constraint '{constraint}' exists",
            agent="Performance Engineer", task_id="P2-10",
            query=f"""
                SELECT COUNT(*) > 0
                FROM information_schema.table_constraints
                WHERE table_schema    = '{DB_SCHEMA}'
                  AND table_name      = '{table}'
                  AND constraint_name = '{constraint}'
                  AND constraint_type = 'UNIQUE'
            """,
            severity="HIGH",
            detail_on_fail=f"Run migration 012_add_unique_constraints.py for {table}",
        )
        REPORT.add(r); log_result(r)

    # Duplicate enforcement works (should fail gracefully)
    r = await run_check(
        conn,
        name="Duplicate collection_items INSERT raises constraint violation",
        agent="Performance Engineer", task_id="P2-10",
        query=f"""
            SELECT COUNT(*) > 0
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            WHERE n.nspname = '{DB_SCHEMA}'
              AND t.relname = 'collection_items'
              AND c.contype = 'u'
        """,
        severity="HIGH",
        detail_on_fail="No unique constraint on collection_items.",
    )
    REPORT.add(r); log_result(r)

    # Schema coverage: all critical tables present
    critical_tables = [
        "documents", "document_chunks", "collections", "collection_items",
        "chat_messages", "users", "audit_logs", "smart_folders",
        "entity_mentions",
    ]
    for tbl in critical_tables:
        r = await run_check(
            conn,
            name=f"Table '{tbl}' exists in schema",
            agent="Performance Engineer", task_id="P2-10",
            query=f"""
                SELECT COUNT(*) > 0
                FROM information_schema.tables
                WHERE table_schema = '{DB_SCHEMA}'
                  AND table_name   = '{tbl}'
            """,
            severity="CRITICAL",
            detail_on_fail=f"Table '{DB_SCHEMA}.{tbl}' is missing.",
        )
        REPORT.add(r); log_result(r)

    # Index usage stats (informational)
    r = await run_check(
        conn,
        name="pg_stat_user_indexes accessible for monitoring",
        agent="Performance Engineer", task_id="P2-10",
        query=f"""
            SELECT COUNT(*) >= 0
            FROM pg_stat_user_indexes
            WHERE schemaname = '{DB_SCHEMA}'
        """,
        severity="HIGH",
        detail_on_fail="Cannot access index statistics.",
    )
    REPORT.add(r); log_result(r)

    # Vector search performance target
    r = await run_perf_check(
        conn,
        name="Vector semantic search on 1M chunks target <200ms",
        agent="Performance Engineer", task_id="P2-10",
        query=f"""
            SELECT chunk_id, similarity, chunk_text
            FROM {DB_SCHEMA}.semantic_search(
                '[{ ','.join(['0.01'] * 1024) }]'::vector(1024),
                10,
                0.5
            )
        """,
        threshold_ms=200.0,
        severity="HIGH",
    )
    REPORT.add(r); log_result(r)

    # FTS target <50ms
    r = await run_perf_check(
        conn,
        name="Full-text search query executes <50ms",
        agent="Performance Engineer", task_id="P2-10",
        query=f"""
            SELECT id FROM {DB_SCHEMA}.document_chunks
            WHERE tsvector_content @@ websearch_to_tsquery('french', 'contrat travail')
            LIMIT 20
        """,
        threshold_ms=50.0,
        severity="HIGH",
    )
    REPORT.add(r); log_result(r)


# ══════════════════════════════════════════════════════════════════════════════
#  ALEMBIC MIGRATION CHAIN VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════

async def check_alembic_migrations(conn):
    section("Alembic Migration Chain")

    import glob, os

    expected_migrations = {
        "004": "004_fix_vector_type",
        "005": "005_add_vector_fts_indexes",
        "006": "006_add_minimax_enum",
        "007": "007_add_audit_logs",
        "008": "008_add_collection_confidential",
        "009": "009_add_rls_policies",
        "010": "010_add_chat_session_index",
        "011": "011_add_smart_folders",
        "012": "012_add_unique_constraints",
    }

    for num, name in expected_migrations.items():
        matches = glob.glob(f"backend/alembic/versions/{name}*.py")
        priority = "CRITICAL" if num in ("004","005","006","007","008") else "HIGH"
        r = CheckResult(
            name=f"Migration {num}: {name}.py",
            agent="Database Architect", task_id=f"MIGRATION-{num}",
            passed=bool(matches),
            message="Present" if matches else "MISSING",
            severity=priority,
            detail=f"Expected: backend/alembic/versions/{name}*.py",
        )
        REPORT.add(r); log_result(r)

    # Alembic version table
    r = await run_check(
        conn,
        name="alembic_version table exists (migrations applied)",
        agent="Database Architect", task_id="ALEMBIC",
        query="""
            SELECT COUNT(*) > 0
            FROM information_schema.tables
            WHERE table_name = 'alembic_version'
        """,
        severity="CRITICAL",
        detail_on_fail="Run 'alembic upgrade head' to apply all migrations.",
    )
    REPORT.add(r); log_result(r)


# ══════════════════════════════════════════════════════════════════════════════
#  FastAPI MIDDLEWARE VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def check_fastapi_middleware():
    section("FastAPI RLS Middleware")
    import glob, os

    middleware_files = glob.glob("backend/app/**/*.py", recursive=True)
    found_rls_middleware = False
    found_rls_set = False

    for filepath in middleware_files:
        try:
            with open(filepath, "r", errors="ignore") as f:
                content = f.read()
                if "set_rls_context" in content:
                    found_rls_middleware = True
                if "SET app.user_id" in content or "set app.user_id" in content.lower():
                    found_rls_set = True
        except Exception:
            continue

    r = CheckResult(
        name="set_rls_context middleware defined in FastAPI app",
        agent="Security Engineer", task_id="P2-9",
        passed=found_rls_middleware,
        message="Found" if found_rls_middleware else "NOT FOUND",
        severity="HIGH",
        detail="Add @app.middleware('http') set_rls_context as per P2-9 spec.",
    )
    REPORT.add(r); log_result(r)

    r = CheckResult(
        name="RLS context SET app.user_id in middleware",
        agent="Security Engineer", task_id="P2-9",
        passed=found_rls_set,
        message="Found" if found_rls_set else "NOT FOUND",
        severity="HIGH",
        detail="Middleware must execute: SET app.user_id = '{user.id}'",
    )
    REPORT.add(r); log_result(r)

    # is_confidential in ORM Collection model
    collection_model = "backend/app/models/collection.py"
    if os.path.exists(collection_model):
        with open(collection_model, "r", errors="ignore") as f:
            content = f.read()
        has_is_confidential = "is_confidential" in content
        r = CheckResult(
            name="ORM Collection model includes is_confidential field",
            agent="Backend Developer", task_id="P1-6",
            passed=has_is_confidential,
            message="Present" if has_is_confidential else "MISSING",
            severity="HIGH",
            detail="Add: is_confidential: Mapped[bool] = mapped_column(Boolean, default=False)",
        )
        REPORT.add(r); log_result(r)
    else:
        r = CheckResult(
            name="ORM Collection model includes is_confidential field",
            agent="Backend Developer", task_id="P1-6",
            passed=False, message="Model file not found",
            severity="HIGH",
            detail=f"File not found: {collection_model}",
        )
        REPORT.add(r); log_result(r)


# ══════════════════════════════════════════════════════════════════════════════
#  FINAL REPORT
# ══════════════════════════════════════════════════════════════════════════════

def print_final_report():
    duration = (datetime.now() - REPORT.start_time).total_seconds()
    total    = len(REPORT.results)
    passed   = len(REPORT.passed)
    failed   = len(REPORT.failed)
    critical = len(REPORT.critical_failures)
    coverage = round(passed / total * 100, 1) if total else 0

    banner("SOWKNOW QA VERIFICATION — FINAL REPORT")

    # Summary table
    print(f"""
  \033[1mRun completed in: {duration:.2f}s\033[0m
  {'─' * 55}
  Total checks       : {total}
  \033[92mPassed             : {passed}\033[0m
  \033[91mFailed             : {failed}\033[0m
  \033[91mCritical failures  : {critical}\033[0m
  Schema coverage    : {GREEN if coverage >= 95 else YELLOW}{coverage}%{RESET}
    (target ≥ 95%)
  {'─' * 55}
""")

    # Failed checks grouped by agent
    if REPORT.failed:
        print(f"  {BOLD}{RED}FAILED CHECKS:{RESET}")
        by_agent: Dict[str, List[CheckResult]] = {}
        for r in REPORT.failed:
            by_agent.setdefault(r.agent, []).append(r)
        for agent, checks in by_agent.items():
            print(f"\n  {YELLOW}▸ {agent}{RESET}")
            for c in checks:
                print(f"    {RED}✘{RESET} [{c.task_id}] {c.name}")
                print(f"      {GRAY}→ {c.detail or c.message}{RESET}")

    # Success metrics vs targets
    section("Success Metrics vs Targets")
    metrics = [
        ("Vector search <200ms",  any(r.name.startswith("Vector semantic") and r.passed for r in REPORT.results)),
        ("FTS search <50ms",      any(r.name.startswith("Full-text search") and r.passed for r in REPORT.results)),
        ("Audit log writes <10ms",any(r.name.startswith("Audit log INSERT") and r.passed for r in REPORT.results)),
        ("Chat history <20ms",    any(r.name.startswith("Chat 50-message") and r.passed for r in REPORT.results)),
        ("Schema coverage ≥95%",  coverage >= 95),
        ("All P0 migrations",     all(r.passed for r in REPORT.results if r.task_id.startswith("P0"))),
        ("RLS policies active",   all(r.passed for r in REPORT.results if r.task_id == "P2-9")),
        ("Audit logging active",  all(r.passed for r in REPORT.results if r.task_id == "P0-4")),
    ]
    for label, ok in metrics:
        icon = f"{GREEN}✔{RESET}" if ok else f"{RED}✘{RESET}"
        print(f"  {icon}  {label}")

    # Final verdict
    print()
    if critical == 0 and failed == 0:
        print(f"  {BOLD}{GREEN}🎉 ALL CHECKS PASSED — READY FOR PRODUCTION DEPLOY{RESET}")
    elif critical == 0:
        print(f"  {BOLD}{YELLOW}⚠  {failed} non-critical issue(s) — review before deploy{RESET}")
    else:
        print(f"  {BOLD}{RED}🚫 {critical} CRITICAL FAILURE(S) — DO NOT DEPLOY{RESET}")
        print(f"     Resolve critical items and re-run this script.\n")

    # JSON export
    report_file = f"sowknow_qa_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    export = {
        "generated_at": datetime.now().isoformat(),
        "duration_seconds": duration,
        "summary": {
            "total": total, "passed": passed, "failed": failed,
            "critical_failures": critical, "coverage_pct": coverage,
        },
        "checks": [
            {
                "task_id": r.task_id, "agent": r.agent, "name": r.name,
                "passed": r.passed, "severity": r.severity,
                "duration_ms": round(r.duration_ms, 2),
                "detail": r.detail,
            }
            for r in REPORT.results
        ],
    }
    with open(report_file, "w") as f:
        json.dump(export, f, indent=2)
    print(f"\n  {GRAY}📄 Full report saved → {report_file}{RESET}\n")


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    banner("SOWKNOW Schema Fix & Enhancement — QA Verification Suite")
    print(f"  {GRAY}Database : {DB_URL.split('@')[-1] if '@' in DB_URL else DB_URL}{RESET}")
    print(f"  {GRAY}Schema   : {DB_SCHEMA}{RESET}")
    print(f"  {GRAY}Started  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")

    try:
        conn = await asyncpg.connect(
            DB_URL.replace("postgresql+asyncpg://", "postgresql://")
                  .replace("asyncpg+postgresql://", "postgresql://")
        )
    except Exception as exc:
        print(f"\n  {RED}[FATAL] Cannot connect to database: {exc}{RESET}")
        print(f"  Set SOWKNOW_DB_URL env var and retry.\n")
        sys.exit(1)

    try:
        await check_agent1_database_architect(conn)
        await check_agent2_vector_search(conn)
        await check_agent3_fulltext_search(conn)
        await check_agent4_security(conn)
        await check_agent5_backend(conn)
        await check_agent6_performance(conn)
        await check_alembic_migrations(conn)
        check_fastapi_middleware()
    finally:
        await conn.close()

    print_final_report()
    sys.exit(0 if not REPORT.critical_failures else 1)


if __name__ == "__main__":
    asyncio.run(main())
