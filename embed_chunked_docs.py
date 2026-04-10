#!/usr/bin/env python3
"""
Embed the 4,084 chunked documents that have chunks but no embeddings.
Queues recompute_embeddings_for_document tasks in controlled batches,
starting with smallest docs first for fastest progress.

Usage:
  python3 embed_chunked_docs.py start     # Begin embedding
  python3 embed_chunked_docs.py status    # Check progress
  python3 embed_chunked_docs.py stop      # Emergency stop
"""

import subprocess
import sys
import time
from datetime import datetime

DB_CONTAINER = "sowknow4-postgres"
CELERY_CONTAINER = "sowknow4-celery-worker"
REDIS_CONTAINER = "sowknow4-redis"
DB_NAME = "sowknow"
DB_USER = "sowknow"

# Batch settings
QUEUE_BATCH = 20         # docs to queue at once
MAX_IN_QUEUE = 30        # max tasks in document_processing before waiting
STAGGER_SECONDS = 2      # countdown between tasks within a batch
POLL_INTERVAL = 30       # seconds between queue depth checks


def run(cmd, check=False):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    if check and result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        return None
    return result.stdout.strip()


def db_query(sql):
    escaped = sql.replace("'", "'\\''")
    return run(f"docker exec {DB_CONTAINER} psql -U {DB_USER} -d {DB_NAME} -t -A -c '{escaped}'")


def redis_cmd(cmd):
    return run(
        f"docker exec {REDIS_CONTAINER} sh -c "
        f"'REDISCLI_AUTH=$REDIS_PASSWORD redis-cli {cmd}'"
    )


def queue_depth():
    """Current document_processing queue depth."""
    result = redis_cmd("LLEN document_processing")
    try:
        return int(result)
    except (ValueError, TypeError):
        return 0


def get_next_batch(batch_size):
    """Get the next batch of chunked docs without embeddings, smallest first."""
    result = db_query(f"""
        SELECT d.id
        FROM documents d
        WHERE d.pipeline_stage = 'chunked'
          AND d.status::text = 'indexed'
          AND d.embedding_generated = false
        ORDER BY d.chunk_count ASC NULLS LAST, d.created_at ASC
        LIMIT {batch_size}
    """)
    if not result or result.strip() == "":
        return []
    return [line.strip() for line in result.strip().split("\n") if line.strip()]


def queue_embeddings(doc_ids):
    """Queue recompute_embeddings_for_document tasks via celery call."""
    for i, doc_id in enumerate(doc_ids):
        countdown = i * STAGGER_SECONDS
        run(
            f"docker exec {CELERY_CONTAINER} celery -A app.celery_app call "
            f"app.tasks.embedding_tasks.recompute_embeddings_for_document "
            f"--args='[\"{doc_id}\"]' --countdown={countdown} 2>&1"
        )


def mark_pipeline_indexed(doc_ids):
    """After embedding completes, update pipeline_stage to 'indexed'."""
    ids_str = ",".join(f"'{d}'" for d in doc_ids)
    db_query(f"""
        UPDATE documents
        SET pipeline_stage = 'indexed'
        WHERE id IN ({ids_str})
          AND embedding_generated = true
    """)


def start():
    # Get initial counts
    total = db_query("""
        SELECT COUNT(*) FROM documents
        WHERE pipeline_stage = 'chunked'
          AND status::text = 'indexed'
          AND embedding_generated = false
    """)
    total = int(total.strip()) if total else 0

    print(f"  Documents to embed: {total}")
    if total == 0:
        print("  Nothing to do!")
        return

    print(f"  Strategy: Queue {QUEUE_BATCH} docs at a time, smallest first")
    print(f"  Backpressure: wait if queue > {MAX_IN_QUEUE}")
    print(f"  Stagger: {STAGGER_SECONDS}s between tasks in a batch")
    print()

    total_queued = 0
    batch_num = 0

    while True:
        # Backpressure check
        depth = queue_depth()
        if depth > MAX_IN_QUEUE:
            print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
                  f"Queue depth {depth} > {MAX_IN_QUEUE}, waiting {POLL_INTERVAL}s...")
            time.sleep(POLL_INTERVAL)
            continue

        # Get next batch
        doc_ids = get_next_batch(QUEUE_BATCH)
        if not doc_ids:
            print(f"\n  All documents queued! Total: {total_queued}")
            break

        batch_num += 1
        total_queued += len(doc_ids)

        # Queue them
        queue_embeddings(doc_ids)

        # Check how many have completed embedding so far
        done = db_query("""
            SELECT COUNT(*) FROM documents
            WHERE pipeline_stage = 'chunked'
              AND embedding_generated = true
        """)
        done_count = int(done.strip()) if done and done.strip().isdigit() else 0

        # Update completed ones to 'indexed' pipeline_stage
        if done_count > 0:
            db_query("""
                UPDATE documents
                SET pipeline_stage = 'indexed'
                WHERE pipeline_stage = 'chunked'
                  AND embedding_generated = true
            """)

        remaining = total - total_queued
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
              f"Batch {batch_num}: queued {len(doc_ids)} docs "
              f"(total queued: {total_queued}, "
              f"embedded: {done_count}, "
              f"remaining: {max(0, remaining)})")

        time.sleep(POLL_INTERVAL)

    print()
    print("  Monitor progress with: python3 embed_chunked_docs.py status")
    print("  Emergency stop: python3 embed_chunked_docs.py stop")


def status():
    print("  Embedding Progress")
    print("  " + "-" * 40)

    chunked_no_embed = db_query("""
        SELECT COUNT(*) FROM documents
        WHERE pipeline_stage = 'chunked'
          AND embedding_generated = false
    """)
    chunked_with_embed = db_query("""
        SELECT COUNT(*) FROM documents
        WHERE pipeline_stage = 'chunked'
          AND embedding_generated = true
    """)
    indexed = db_query("""
        SELECT COUNT(*) FROM documents
        WHERE pipeline_stage = 'indexed'
    """)

    c_no = int(chunked_no_embed.strip()) if chunked_no_embed and chunked_no_embed.strip().isdigit() else 0
    c_yes = int(chunked_with_embed.strip()) if chunked_with_embed and chunked_with_embed.strip().isdigit() else 0
    idx = int(indexed.strip()) if indexed and indexed.strip().isdigit() else 0

    print(f"  Chunked (no embedding):  {c_no}")
    print(f"  Chunked (embedded):      {c_yes}")
    print(f"  Indexed:                 {idx}")
    print()

    depth = queue_depth()
    print(f"  document_processing queue: {depth} tasks")
    print()

    # Worker status
    cpu = run("docker stats sowknow4-celery-worker --no-stream --format '{{.CPUPerc}} {{.MemUsage}}'")
    print(f"  Worker: {cpu}")


def stop():
    print("  Flushing document_processing queue...")
    redis_cmd("DEL document_processing")
    print("  Done. Worker will finish current task then idle.")


COMMANDS = {"start": start, "status": status, "stop": stop}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
