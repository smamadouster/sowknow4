#!/usr/bin/env python3
"""
SOWKNOW Recovery & Deployment Runbook
=====================================
Date: April 5, 2026
Status: 3,026 documents stuck (full reprocess needed), 3 status-fix-only

THIS IS THE SINGLE SOURCE OF TRUTH.
Ignore all previous partial plans. Execute these phases in order.

Prerequisites:
  - SSH access to the VPS
  - Docker Compose access to SOWKNOW stack
  - This script saved to the VPS at ~/sowknow_runbook.py

Usage:
  python3 sowknow_runbook.py phase1   # Diagnose current state
  python3 sowknow_runbook.py phase2   # Deploy code changes
  python3 sowknow_runbook.py phase3   # Fix the 3 easy docs
  python3 sowknow_runbook.py phase4   # Test batch of 10
  python3 sowknow_runbook.py phase5   # Controlled bulk recovery
  python3 sowknow_runbook.py status   # Check progress at any time
  python3 sowknow_runbook.py stop     # Emergency stop
"""

import subprocess
import sys
import time
import json
from datetime import datetime

# ============================================================
# CONFIGURATION — Edit these to match your actual setup
# ============================================================

# Docker container names (run `docker ps` to verify)
BACKEND_CONTAINER = "sowknow4-backend"
CELERY_CONTAINER = "sowknow4-celery-worker"
BEAT_CONTAINER = "sowknow4-celery-beat"
DB_CONTAINER = "sowknow4-postgres"
REDIS_CONTAINER = "sowknow4-redis"

# Docker compose service names (must match docker-compose.yml)
CELERY_SERVICE = "celery-worker"
BEAT_SERVICE = "celery-beat"
BACKEND_SERVICE = "backend"

# Docker compose project directory on the VPS
COMPOSE_DIR = "/var/docker/sowknow4"

# Database connection (inside the DB container)
DB_NAME = "sowknow"
DB_USER = "sowknow"

# Recovery settings
BATCH_SIZE = 10           # docs per test batch (phase 4)
BULK_BATCH = 50           # docs per recovery cycle (phase 5)
SLEEP_BETWEEN_BATCHES = 30  # seconds between batches

# Celery queues (must match celery_app.py task_routes)
CELERY_QUEUES = ["celery", "document_processing", "scheduled", "collections"]


def run(cmd, capture=True, check=True):
    """Run a shell command and return output."""
    print(f"  $ {cmd}")
    result = subprocess.run(
        cmd, shell=True, capture_output=capture,
        text=True, timeout=120
    )
    if check and result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        return None
    return result.stdout.strip() if capture else None


def docker_exec(container, cmd):
    """Execute a command inside a Docker container."""
    return run(f'docker exec {container} {cmd}')


def redis_cli(cmd):
    """Run a redis-cli command using the container's own REDIS_PASSWORD."""
    return run(
        f"docker exec {REDIS_CONTAINER} sh -c "
        f"'REDISCLI_AUTH=$REDIS_PASSWORD redis-cli {cmd}'",
        check=False
    )


def db_query(sql, container=None):
    """Run a SQL query against the SOWKNOW database."""
    c = container or DB_CONTAINER
    escaped = sql.replace("'", "'\\''")
    return run(f"docker exec {c} psql -U {DB_USER} -d {DB_NAME} -t -A -c '{escaped}'")


def has_pipeline_stage_column():
    """Check if the pipeline_stage column exists in the documents table."""
    result = db_query("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'documents'
          AND column_name = 'pipeline_stage'
    """)
    return result is not None and result.strip() == "1"


def header(text):
    width = 60
    print()
    print("=" * width)
    print(f"  {text}")
    print("=" * width)
    print()


# ============================================================
# PHASE 1: DIAGNOSE
# Understand exactly what you're dealing with before touching
# anything. This phase is read-only — nothing changes.
# ============================================================

def phase1():
    header("PHASE 1: DIAGNOSTIC SNAPSHOT")

    print("1.1 Container Status")
    print("-" * 40)
    for name in [BACKEND_CONTAINER, CELERY_CONTAINER, BEAT_CONTAINER,
                 DB_CONTAINER, REDIS_CONTAINER]:
        status = run(f"docker inspect -f '{{{{.State.Status}}}}' {name}", check=False)
        oom = run(f"docker inspect -f '{{{{.State.OOMKilled}}}}' {name}", check=False)
        restarts = run(f"docker inspect -f '{{{{.RestartCount}}}}' {name}", check=False)
        print(f"  {name}: status={status}, oom_killed={oom}, restarts={restarts}")
    print()

    # Check if pipeline_stage column exists before querying it
    has_pipeline = has_pipeline_stage_column()

    print("1.2 Document Pipeline State")
    print("-" * 40)
    if has_pipeline:
        result = db_query("""
            SELECT
                COALESCE(pipeline_stage, status::text) as stage,
                COUNT(*) as count
            FROM documents
            GROUP BY COALESCE(pipeline_stage, status::text)
            ORDER BY count DESC
        """)
    else:
        print("  (pipeline_stage column not yet created — showing status only)")
        result = db_query("""
            SELECT status as stage, COUNT(*) as count
            FROM documents
            GROUP BY status
            ORDER BY count DESC
        """)
    if result:
        print("  Stage                | Count")
        print("  " + "-" * 35)
        for line in result.strip().split("\n"):
            if "|" in line:
                parts = line.split("|")
                print(f"  {parts[0].strip():22s} | {parts[1].strip()}")
    print()

    print("1.3 Error Documents Breakdown")
    print("-" * 40)
    result = db_query("""
        SELECT
            CASE
                WHEN EXISTS(
                    SELECT 1 FROM document_chunks dc
                    WHERE dc.document_id = d.id AND dc.embedding_vector IS NOT NULL
                ) THEN 'status_fix_only'
                WHEN EXISTS(
                    SELECT 1 FROM document_chunks dc
                    WHERE dc.document_id = d.id
                ) THEN 'embed_only'
                ELSE 'full_reprocess'
            END as category,
            COUNT(*) as count
        FROM documents d
        WHERE d.status = 'error'
        GROUP BY category
        ORDER BY count DESC
    """)
    if result:
        for line in result.strip().split("\n"):
            if "|" in line:
                parts = line.split("|")
                print(f"  {parts[0].strip():22s} | {parts[1].strip()}")
    else:
        print("  No error documents found.")
    print()

    print("1.4 Celery Queue Depth")
    print("-" * 40)
    for queue in CELERY_QUEUES:
        depth = redis_cli(f"LLEN {queue}")
        print(f"  {queue}: {depth or '0'} tasks")
    print()

    print("1.5 Active Celery Tasks")
    print("-" * 40)
    active = docker_exec(CELERY_CONTAINER,
        "celery -A app inspect active --json 2>/dev/null || echo '{}'")
    if active and active != "{}":
        try:
            data = json.loads(active)
            for worker, tasks in data.items():
                print(f"  Worker {worker}: {len(tasks)} active tasks")
                for t in tasks[:3]:
                    print(f"    - {t.get('name', 'unknown')} (started: {t.get('time_start', '?')})")
        except json.JSONDecodeError:
            print(f"  Raw output: {active[:200]}")
    else:
        print("  No active tasks (or worker not responding)")
    print()

    print("1.6 Disk Space")
    print("-" * 40)
    run("df -h / | tail -1", capture=False)
    print()

    print("1.7 Memory Usage")
    print("-" * 40)
    run("docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' | head -10",
        capture=False)
    print()

    print("1.8 Recent Errors in Celery Logs (last 20 errors)")
    print("-" * 40)
    errors = run(
        f"docker logs {CELERY_CONTAINER} --tail 500 2>&1 | "
        r"grep -E '(ERROR|CRITICAL|Traceback|MemoryError|OOM|NUL|\\x00)' | tail -20",
        check=False
    )
    if errors:
        for line in errors.split("\n")[:20]:
            print(f"  {line[:120]}")
    else:
        print("  No recent errors found")

    print()
    print("=" * 60)
    print("  PHASE 1 COMPLETE")
    print("  Review the output above. If everything looks stable,")
    print("  proceed to: python3 sowknow_runbook.py phase2")
    print("=" * 60)


# ============================================================
# PHASE 2: DEPLOY CODE CHANGES
# This deploys the NUL byte fix, pipeline stages, throttled
# recovery, and entity extraction fixes.
# ============================================================

def phase2():
    header("PHASE 2: DEPLOY CODE CHANGES")

    print("Step 2.1: Stop Celery worker and beat (prevent recovery flood)")
    print("-" * 40)
    run(f"docker stop {CELERY_CONTAINER} {BEAT_CONTAINER}", check=False)
    time.sleep(3)

    # Verify they're stopped
    for c in [CELERY_CONTAINER, BEAT_CONTAINER]:
        status = run(f"docker inspect -f '{{{{.State.Status}}}}' {c}", check=False)
        print(f"  {c}: {status}")
    print()

    print("Step 2.2: Pull latest code")
    print("-" * 40)
    result = run(f"cd {COMPOSE_DIR} && git pull", check=False)
    if result:
        print(f"  {result[:200]}")
    print()

    print("Step 2.3: Run database migration (add pipeline_stage columns)")
    print("-" * 40)
    # The bind mount means backend code is live from ./backend, so run
    # alembic from the backend container which has the latest code.
    result = docker_exec(BACKEND_CONTAINER,
        "alembic upgrade head 2>&1")
    if result:
        print(f"  Migration output: {result[:300]}")
    else:
        print("  WARNING: Migration may have failed. Check manually:")
        print(f"    docker exec {BACKEND_CONTAINER} alembic upgrade head")
        print()
        confirm = input("  Continue anyway? (y/n): ").strip().lower()
        if confirm != "y":
            print("  Aborting. Fix migration and re-run phase2.")
            return
    print()

    print("Step 2.4: Verify migration — check pipeline_stage column exists")
    print("-" * 40)
    if has_pipeline_stage_column():
        print("  pipeline_stage column: EXISTS")
    else:
        print("  FATAL: pipeline_stage column not found!")
        print("  The migration did not apply correctly.")
        print("  Fix this before continuing.")
        return
    print()

    print("Step 2.5: Rebuild and restart Celery worker + beat")
    print("-" * 40)
    # docker compose up takes SERVICE names, not container names
    run(f"cd {COMPOSE_DIR} && docker compose up -d --build "
        f"{CELERY_SERVICE} {BEAT_SERVICE}", check=False, capture=False)
    print()
    print("  Waiting 15 seconds for workers to initialize...")
    time.sleep(15)

    # Verify they're running (use container names for inspect)
    for c in [CELERY_CONTAINER, BEAT_CONTAINER]:
        status = run(f"docker inspect -f '{{{{.State.Status}}}}' {c}", check=False)
        health = run(f"docker inspect -f '{{{{.State.Health.Status}}}}' {c}", check=False)
        print(f"  {c}: status={status}, health={health}")
    print()

    print("Step 2.6: Verify worker is healthy")
    print("-" * 40)
    ping = docker_exec(CELERY_CONTAINER,
        "celery -A app inspect ping 2>/dev/null || echo 'FAILED'")
    if ping and "pong" in ping.lower():
        print("  Worker responding: YES")
    else:
        print("  WARNING: Worker not responding to ping.")
        print(f"  Check logs: docker logs {CELERY_CONTAINER} --tail 50")
    print()

    print("Step 2.7: Check for NUL byte fix in deployed code")
    print("-" * 40)
    nul_check = docker_exec(BACKEND_CONTAINER,
        r"grep -rn 'x00\|NUL\|nul_byte\|sanitize' /app/app/tasks/document_tasks.py 2>/dev/null | head -5")
    if nul_check:
        print("  NUL byte sanitization: FOUND in code")
        for line in nul_check.split("\n")[:3]:
            print(f"    {line[:100]}")
    else:
        print("  WARNING: NUL byte fix not detected in deployed code!")
        print("  Make sure document_tasks.py has the \\x00 replacement.")
    print()

    print("=" * 60)
    print("  PHASE 2 COMPLETE")
    print("  Code deployed, migration applied, workers running.")
    print("  Proceed to: python3 sowknow_runbook.py phase3")
    print("=" * 60)


# ============================================================
# PHASE 3: FIX THE EASY WINS
# The 3 status-fix-only documents — just need status updated.
# This validates the pipeline stage logic works correctly.
# ============================================================

def phase3():
    header("PHASE 3: FIX STATUS-ONLY DOCUMENTS (3 docs)")

    print("Step 3.1: Identify status-fix-only documents")
    print("-" * 40)
    result = db_query("""
        SELECT d.id, d.title, d.status, d.pipeline_stage
        FROM documents d
        WHERE d.status = 'error'
          AND EXISTS(
              SELECT 1 FROM document_chunks dc
              WHERE dc.document_id = d.id AND dc.embedding_vector IS NOT NULL
          )
    """)
    if not result or result.strip() == "":
        print("  No status-fix-only documents found.")
        print("  Skipping to phase4.")
        return

    print("  Found documents:")
    doc_ids = []
    for line in result.strip().split("\n"):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 1 and parts[0].isdigit():
            doc_ids.append(parts[0])
            title = parts[1][:50] if len(parts) > 1 else "?"
            print(f"    ID={parts[0]}, title={title}")
    print()

    if not doc_ids:
        print("  No documents to fix.")
        return

    print(f"  Found {len(doc_ids)} document(s) to fix.")
    print()

    print("Step 3.2: Update status to 'indexed' and pipeline_stage to 'indexed'")
    print("-" * 40)
    ids_str = ",".join(doc_ids)
    result = db_query(f"""
        UPDATE documents
        SET status = 'indexed',
            pipeline_stage = 'indexed',
            pipeline_error = NULL,
            updated_at = NOW()
        WHERE id IN ({ids_str})
        RETURNING id, title
    """)
    if result:
        count = len([l for l in result.strip().split("\n") if l.strip()])
        print(f"  Fixed {count} document(s).")
    print()

    print("Step 3.3: Verify fix")
    print("-" * 40)
    result = db_query(f"""
        SELECT id, status, pipeline_stage FROM documents
        WHERE id IN ({ids_str})
    """)
    if result:
        for line in result.strip().split("\n"):
            print(f"  {line}")
    print()

    print("=" * 60)
    print(f"  PHASE 3 COMPLETE — {len(doc_ids)} document(s) unblocked.")
    print("  Proceed to: python3 sowknow_runbook.py phase4")
    print("=" * 60)


# ============================================================
# PHASE 4: TEST BATCH
# Process 10 documents through the full pipeline.
# Watch closely for NUL byte errors, OOM, API failures.
# DO NOT PROCEED TO PHASE 5 UNTIL THIS SUCCEEDS CLEANLY.
# ============================================================

def phase4():
    header("PHASE 4: TEST BATCH (10 documents)")

    print("Step 4.1: Select 10 test documents (oldest first)")
    print("-" * 40)
    result = db_query(f"""
        SELECT id, title, file_type, created_at
        FROM documents
        WHERE status = 'error'
          AND NOT EXISTS(
              SELECT 1 FROM document_chunks dc
              WHERE dc.document_id = documents.id
          )
        ORDER BY created_at ASC
        LIMIT {BATCH_SIZE}
    """)

    if not result or result.strip() == "":
        print("  No error documents needing full reprocessing found.")
        return

    doc_ids = []
    print("  Selected documents:")
    for line in result.strip().split("\n"):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 1 and parts[0].isdigit():
            doc_ids.append(parts[0])
            title = parts[1][:40] if len(parts) > 1 else "?"
            ftype = parts[2] if len(parts) > 2 else "?"
            print(f"    ID={parts[0]}, type={ftype}, title={title}")
    print()

    if not doc_ids:
        print("  No documents selected.")
        return

    ids_str = ",".join(doc_ids)

    print("Step 4.2: Reset these documents to 'pending' for reprocessing")
    print("-" * 40)
    db_query(f"""
        UPDATE documents
        SET status = 'pending',
            pipeline_stage = 'uploaded',
            pipeline_error = NULL,
            pipeline_retry_count = 0,
            updated_at = NOW()
        WHERE id IN ({ids_str})
    """)
    print(f"  Reset {len(doc_ids)} documents to pending/uploaded.")
    print()

    print("Step 4.3: Trigger processing")
    print("-" * 40)
    print("  Option A — Wait for the recover_pending_documents beat task")
    print("             (runs every 10 minutes automatically)")
    print()
    print("  Option B — Trigger immediately:")
    print(f"    docker exec {CELERY_CONTAINER} celery -A app call "
          "app.tasks.anomaly_tasks.recover_pending_documents")
    print()

    trigger = input("  Trigger immediately? (y/n): ").strip().lower()
    if trigger == "y":
        result = docker_exec(CELERY_CONTAINER,
            "celery -A app call app.tasks.anomaly_tasks.recover_pending_documents 2>&1")
        if result:
            print(f"  Triggered: {result[:100]}")
        else:
            print("  WARNING: Trigger may have failed. The beat scheduler will pick it up.")
    print()

    print("Step 4.4: MONITOR — Watch the logs live")
    print("-" * 40)
    print("  Run this in a separate terminal and watch for 10-15 minutes:")
    print(f"    docker logs {CELERY_CONTAINER} -f --tail 50 2>&1 | "
          r"grep -E '(process_document|pipeline_stage|ERROR|SUCCESS|NUL|embed)'")
    print()
    print("  WHAT TO LOOK FOR:")
    print("    [OK]  'pipeline_stage: ocr_complete' — OCR working")
    print("    [OK]  'pipeline_stage: chunked' — Chunking working (NUL byte fix works)")
    print("    [OK]  'pipeline_stage: indexed' — Full pipeline success")
    print("    [BAD] 'NUL byte' or '\\x00' — NUL fix not deployed correctly")
    print("    [BAD] 'MemoryError' or 'OOMKilled' — Worker needs more memory")
    print("    [BAD] 'TencentAPIError' — OCR API issue (check rate limits/credits)")
    print()

    print("Step 4.5: After 10-15 minutes, check results")
    print("-" * 40)
    print("  Run: python3 sowknow_runbook.py status")
    print()
    print("  Expected: 10 documents moved from 'error' to 'indexed'")
    print("  If ALL 10 succeed → proceed to phase5")
    print("  If SOME fail → inspect the failures:")
    print(f"    docker exec {DB_CONTAINER} psql -U {DB_USER} -d {DB_NAME} \\")
    print(f"      -c \"SELECT id, pipeline_stage, pipeline_error FROM documents WHERE id IN ({ids_str})\"")
    print()

    print("=" * 60)
    print("  PHASE 4 STARTED — Monitor logs, then check status.")
    print("  Once all 10 succeed: python3 sowknow_runbook.py phase5")
    print("=" * 60)


# ============================================================
# PHASE 5: CONTROLLED BULK RECOVERY
# Process remaining ~3,016 documents in managed batches.
# This runs autonomously but with safety limits.
# ============================================================

def phase5():
    header("PHASE 5: BULK RECOVERY")

    # Pre-flight: verify pipeline_stage column exists
    if not has_pipeline_stage_column():
        print("  FATAL: pipeline_stage column not found. Run phase2 first.")
        return

    # Check counts
    result = db_query("""
        SELECT COUNT(*) FROM documents
        WHERE status = 'indexed' AND pipeline_stage = 'indexed'
    """)
    indexed_count = int(result.strip()) if result else 0

    result = db_query("""
        SELECT COUNT(*) FROM documents
        WHERE status = 'error'
          AND NOT EXISTS(
              SELECT 1 FROM document_chunks dc
              WHERE dc.document_id = documents.id
          )
    """)
    remaining = int(result.strip()) if result else 0

    print(f"  Currently indexed: {indexed_count}")
    print(f"  Remaining to process: {remaining}")
    print()

    if remaining == 0:
        print("  No documents remaining! All done.")
        return

    total_batches = (remaining + BULK_BATCH - 1) // BULK_BATCH
    est_time_hours = (remaining * 60) / 3600  # ~60s per doc estimate

    print(f"  Plan: {remaining} docs in batches of {BULK_BATCH}")
    print(f"  Estimated batches: {total_batches}")
    print(f"  Estimated time: {est_time_hours:.1f} hours")
    print(f"  (at ~60 seconds per document, processing sequentially)")
    print()

    confirm = input("  Start bulk recovery? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("  Aborted.")
        return

    print()
    print("  STRATEGY: Reset documents in batches of 50 to 'pending'.")
    print("  The throttled recovery task will process them gradually.")
    print("  Auto-pauses if >5 failures in 5 minutes.")
    print()

    batch_num = 0
    total_reset = 0

    while True:
        # Check how many are currently pending/processing
        in_flight = db_query("""
            SELECT COUNT(*) FROM documents
            WHERE status IN ('pending', 'processing')
              OR pipeline_stage IN ('ocr_pending', 'chunking', 'embedding')
        """)
        in_flight_count = int(in_flight.strip()) if in_flight else 0

        if in_flight_count > BULK_BATCH:
            print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
                  f"{in_flight_count} docs still in flight. "
                  f"Waiting {SLEEP_BETWEEN_BATCHES}s...")
            time.sleep(SLEEP_BETWEEN_BATCHES)
            continue

        # Get next batch
        result = db_query(f"""
            SELECT id FROM documents
            WHERE status = 'error'
              AND (pipeline_stage IS NULL OR pipeline_stage NOT IN ('indexed'))
              AND NOT EXISTS(
                  SELECT 1 FROM document_chunks dc
                  WHERE dc.document_id = documents.id
              )
            ORDER BY created_at ASC
            LIMIT {BULK_BATCH}
        """)

        if not result or result.strip() == "":
            print(f"\n  All documents have been queued for recovery!")
            break

        ids = [line.strip() for line in result.strip().split("\n")
               if line.strip() and line.strip().isdigit()]

        if not ids:
            print(f"\n  No more valid document IDs to process.")
            break

        ids_str = ",".join(ids)

        batch_num += 1
        total_reset += len(ids)

        db_query(f"""
            UPDATE documents
            SET status = 'pending',
                pipeline_stage = 'uploaded',
                pipeline_error = NULL,
                pipeline_retry_count = 0,
                updated_at = NOW()
            WHERE id IN ({ids_str})
        """)

        print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
              f"Batch {batch_num}: Reset {len(ids)} docs to pending. "
              f"Total queued: {total_reset}/{remaining}")

        # Check for recent failures — circuit breaker
        error_check = db_query("""
            SELECT COUNT(*) FROM documents
            WHERE pipeline_stage LIKE '%failed%'
              AND pipeline_last_attempt > NOW() - INTERVAL '5 minutes'
        """)
        recent_failures = int(error_check.strip()) if error_check else 0
        if recent_failures > 5:
            print(f"\n  CIRCUIT BREAKER: {recent_failures} failures in last 5 minutes!")
            print("  Pausing bulk recovery. Investigate before resuming.")
            print(f"  Check errors:")
            print(f"    docker exec {DB_CONTAINER} psql -U {DB_USER} -d {DB_NAME} \\")
            print(f"      -c \"SELECT id, pipeline_stage, LEFT(pipeline_error, 80) "
                  f"FROM documents WHERE pipeline_stage LIKE '%failed%' "
                  f"AND pipeline_last_attempt > NOW() - INTERVAL '5 minutes'\"")
            print(f"  Resume with: python3 sowknow_runbook.py phase5")
            break

        time.sleep(SLEEP_BETWEEN_BATCHES)

    print()
    print("=" * 60)
    print("  PHASE 5 IN PROGRESS")
    print(f"  {total_reset} documents queued for recovery.")
    print("  Monitor with: python3 sowknow_runbook.py status")
    print("  Emergency stop: python3 sowknow_runbook.py stop")
    print("=" * 60)


# ============================================================
# STATUS: Check progress at any time
# ============================================================

def status():
    header("RECOVERY STATUS")

    has_pipeline = has_pipeline_stage_column()

    print("Document Pipeline Distribution")
    print("-" * 40)
    if has_pipeline:
        result = db_query("""
            SELECT
                COALESCE(pipeline_stage, status::text) as stage,
                COUNT(*) as count
            FROM documents
            GROUP BY COALESCE(pipeline_stage, status::text)
            ORDER BY count DESC
        """)
    else:
        result = db_query("""
            SELECT status as stage, COUNT(*) as count
            FROM documents
            GROUP BY status
            ORDER BY count DESC
        """)
    if result:
        total = 0
        for line in result.strip().split("\n"):
            if "|" in line:
                parts = [p.strip() for p in line.split("|")]
                count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                total += count
                bar = "#" * min(50, count // 10)
                print(f"  {parts[0]:25s} | {count:5d} {bar}")
        print(f"  {'TOTAL':25s} | {total:5d}")
    print()

    if has_pipeline:
        print("Recent Failures (last hour)")
        print("-" * 40)
        result = db_query("""
            SELECT id, pipeline_stage, LEFT(pipeline_error, 80) as error
            FROM documents
            WHERE pipeline_stage LIKE '%failed%'
              AND pipeline_last_attempt > NOW() - INTERVAL '1 hour'
            ORDER BY pipeline_last_attempt DESC
            LIMIT 10
        """)
        if result and result.strip():
            for line in result.strip().split("\n"):
                print(f"  {line}")
        else:
            print("  None")
        print()

    print("Processing Throughput (docs completed in last hour)")
    print("-" * 40)
    if has_pipeline:
        result = db_query("""
            SELECT COUNT(*) FROM documents
            WHERE pipeline_stage = 'indexed'
              AND updated_at > NOW() - INTERVAL '1 hour'
        """)
    else:
        result = db_query("""
            SELECT COUNT(*) FROM documents
            WHERE status = 'indexed'
              AND updated_at > NOW() - INTERVAL '1 hour'
        """)
    hourly = int(result.strip()) if result and result.strip().isdigit() else 0
    print(f"  {hourly} documents/hour")
    if hourly > 0:
        remaining = db_query("""
            SELECT COUNT(*) FROM documents
            WHERE status = 'error'
              AND NOT EXISTS(
                  SELECT 1 FROM document_chunks dc
                  WHERE dc.document_id = documents.id
              )
        """)
        rem = int(remaining.strip()) if remaining and remaining.strip().isdigit() else 0
        if rem > 0:
            eta_hours = rem / max(hourly, 1)
            print(f"  Remaining: {rem} docs")
            print(f"  ETA: ~{eta_hours:.1f} hours")
    print()

    print("Celery Queue Depths")
    print("-" * 40)
    for queue in CELERY_QUEUES:
        depth = redis_cli(f"LLEN {queue}")
        print(f"  {queue}: {depth or '0'}")
    print()

    print("Worker Memory")
    print("-" * 40)
    run(f"docker stats {CELERY_CONTAINER} --no-stream --format "
        "'{{{{.MemUsage}}}} ({{{{.MemPerc}}}})'", capture=False)


# ============================================================
# EMERGENCY STOP
# ============================================================

def stop():
    header("EMERGENCY STOP")
    print("Stopping Celery worker and beat...")
    run(f"docker stop {CELERY_CONTAINER} {BEAT_CONTAINER}", check=False)
    print()

    # Check queue depths
    print("Tasks remaining in queues:")
    for queue in CELERY_QUEUES:
        depth = redis_cli(f"LLEN {queue}")
        print(f"  {queue}: {depth or '0'}")
    print()

    print("To clear ALL queues (DESTRUCTIVE):")
    for queue in CELERY_QUEUES:
        print(f"  docker exec {REDIS_CONTAINER} sh -c 'REDISCLI_AUTH=$REDIS_PASSWORD redis-cli DEL {queue}'")
    print()
    print("To resume after fixing issues:")
    print(f"  docker start {CELERY_CONTAINER} {BEAT_CONTAINER}")


# ============================================================
# MAIN
# ============================================================

PHASES = {
    "phase1": phase1,
    "phase2": phase2,
    "phase3": phase3,
    "phase4": phase4,
    "phase5": phase5,
    "status": status,
    "stop": stop,
}

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in PHASES:
        print(__doc__)
        print("Available commands:")
        for name in PHASES:
            print(f"  python3 sowknow_runbook.py {name}")
        sys.exit(1)

    phase = sys.argv[1]
    PHASES[phase]()

if __name__ == "__main__":
    main()
