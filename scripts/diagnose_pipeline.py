#!/usr/bin/env python3
"""
SOWKNOW Pipeline Diagnostic Script
==================================
Run this when throughput is 0/hr but pending items exist.

Usage:
    cd backend && python -m scripts.diagnose_pipeline

Or from repo root:
    PYTHONPATH=backend python scripts/diagnose_pipeline.py
"""
from __future__ import annotations

import os
import sys

if os.path.isdir("/app"):
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def main() -> int:
    print("=" * 60)
    print("SOWKNOW Pipeline Diagnostics")
    print("=" * 60)

    # 1. Database connection & pending/running/failed counts
    print("\n[1] Database pipeline counts")
    try:
        from app.database import SessionLocal
        from app.models.pipeline import PipelineStage, StageEnum, StageStatus
        from sqlalchemy import func

        db = SessionLocal()
        try:
            for s in StageEnum:
                counts = {
                    StageStatus.PENDING: 0,
                    StageStatus.RUNNING: 0,
                    StageStatus.FAILED: 0,
                    StageStatus.COMPLETED: 0,
                    StageStatus.SKIPPED: 0,
                }
                for status, count in (
                    db.query(PipelineStage.status, func.count())
                    .filter(PipelineStage.stage == s)
                    .group_by(PipelineStage.status)
                    .all()
                ):
                    counts[status] = count

                total = sum(counts.values())
                if total > 0 or s in (StageEnum.INDEXED, StageEnum.ENTITIES, StageEnum.ENRICHED):
                    print(
                        f"  {s.value:<12}  pending={counts[StageStatus.PENDING]:>4}  "
                        f"running={counts[StageStatus.RUNNING]:>4}  failed={counts[StageStatus.FAILED]:>4}  "
                        f"completed={counts[StageStatus.COMPLETED]:>6}"
                    )
        finally:
            db.close()
    except Exception as e:
        print(f"  ERROR: {e}")
        return 1

    # 2. Redis queue depths
    print("\n[2] Redis queue depths")
    try:
        from app.core.redis_url import safe_redis_url
        import redis

        r = redis.from_url(safe_redis_url())
        queues = [
            "pipeline.ocr", "pipeline.chunk", "pipeline.embed",
            "pipeline.index", "pipeline.articles", "pipeline.entities",
        ]
        total_depth = 0
        for q in queues:
            depth = r.llen(q)
            total_depth += depth
            max_depth = {"pipeline.embed": 300, "pipeline.ocr": 500, "pipeline.articles": 300,
                         "pipeline.entities": 200, "pipeline.chunk": 300, "pipeline.index": 300}.get(q)
            status = "OK" if (max_depth is None or depth <= max_depth) else "BACKPRESSURE"
            print(f"  {q:<22} depth={depth:>5}  max={max_depth or 'N/A':>4}  [{status}]")

        print(f"  {'TOTAL':<22} depth={total_depth:>5}  max=800  [{'OK' if total_depth <= 800 else 'BACKPRESSURE'}]")
    except Exception as e:
        print(f"  ERROR: Cannot connect to Redis — {e}")
        print("  >>> Redis being down prevents BOTH task dispatch AND consumption <<<")

    # 3. Celery worker inspection
    print("\n[3] Celery worker inspection")
    try:
        from app.celery_app import celery_app

        inspect = celery_app.control.inspect(timeout=5.0)
        stats = inspect.stats()
        active = inspect.active()
        scheduled = inspect.scheduled()

        if not stats:
            print("  ERROR: No Celery workers responded to inspect ping.")
            print("  >>> Workers are DOWN or cannot reach the broker <<<")
        else:
            print(f"  Workers connected: {len(stats)}")
            for name, worker_stats in stats.items():
                pool = worker_stats.get("pool", {}).get("implementation", "unknown")
                concurrency = worker_stats.get("pool", {}).get("max-concurrency", "?")
                print(f"    - {name}  pool={pool}  concurrency={concurrency}")

            if active:
                total_active = sum(len(tasks) for tasks in active.values() if tasks)
                print(f"  Active tasks: {total_active}")
                for name, tasks in active.items():
                    if tasks:
                        for t in tasks:
                            print(f"    - {name}: {t.get('name', '?')}  args={t.get('args', [])}")
            else:
                print("  Active tasks: 0")

            if scheduled:
                total_scheduled = sum(len(tasks) for tasks in scheduled.values() if tasks)
                print(f"  Scheduled tasks: {total_scheduled}")
            else:
                print("  Scheduled tasks: 0")

    except Exception as e:
        print(f"  ERROR: {e}")

    # 4. Sweeper lock
    print("\n[4] Pipeline sweeper lock")
    try:
        from app.core.redis_url import safe_redis_url
        import redis

        r = redis.from_url(safe_redis_url())
        lock_val = r.get("pipeline:sweeper:lock")
        ttl = r.ttl("pipeline:sweeper:lock")
        if lock_val:
            print(f"  Lock EXISTS  value={lock_val.decode()[:50]}  ttl={ttl}s")
            if ttl < 0:
                print("  WARNING: Lock has NO TTL — may be stuck indefinitely!")
                print("  Fix: redis-cli DEL pipeline:sweeper:lock")
        else:
            print("  Lock is free — sweeper can run")
    except Exception as e:
        print(f"  ERROR: {e}")

    # 5. Document status breakdown
    print("\n[5] Document status breakdown")
    try:
        from app.database import SessionLocal
        from app.models.document import Document, DocumentStatus
        from sqlalchemy import func

        db = SessionLocal()
        try:
            for status in DocumentStatus:
                count = db.query(func.count(Document.id)).filter(Document.status == status).scalar()
                print(f"  {status.value:<15} {count:>6}")
        finally:
            db.close()
    except Exception as e:
        print(f"  ERROR: {e}")

    # 6. Recommendations
    print("\n" + "=" * 60)
    print("Recommendations")
    print("=" * 60)

    try:
        from app.celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=5.0)
        stats = inspect.stats()
    except Exception:
        stats = None

    try:
        from app.core.redis_url import safe_redis_url
        import redis
        r = redis.from_url(safe_redis_url())
        r.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    if not redis_ok:
        print("\n🔴 CRITICAL: Redis is unreachable.")
        print("   Action: Start Redis — sudo systemctl start redis")
        print("   Without Redis, Celery cannot queue or consume tasks.")
    elif not stats:
        print("\n🔴 CRITICAL: No Celery workers are connected.")
        print("   Action: Start Celery workers — sudo systemctl start celery")
        print("   Or: docker-compose up -d celery-worker")
    else:
        print("\n🟡 Workers are up but throughput is 0.")
        print("   Possible causes:")
        print("   - Backpressure active (queue depth > limits)")
        print("   - All tasks are FAILED and need retry")
        print("   - Workers are idle because queues are empty (check Redis depths above)")
        print("   Action: Click Retry buttons in dashboard, or run:")
        print("           python -m scripts.recover_pipeline --all --limit 100")

    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
