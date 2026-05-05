#!/usr/bin/env python3
"""
SOWKNOW Pipeline Recovery Script
================================
Bulk-retry failed pipeline stages in the correct upstream-to-downstream order.

Usage:
    cd backend && python -m scripts.recover_pipeline --limit 50

Or from repo root:
    PYTHONPATH=backend python scripts/recover_pipeline.py --limit 50

Environment:
    DATABASE_URL, REDIS_URL, and broker connection must be available.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Sequence

# Allow running from repo root or inside Docker container
if os.path.isdir("/app"):
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("pipeline.recovery")

# Ordered stages — upstream first
STAGES = ["uploaded", "ocr", "chunked", "embedded", "indexed", "articles", "entities", "enriched"]


def _get_db():
    from app.database import SessionLocal
    return SessionLocal()


def retry_failed_stages(stage: str | None = None, limit: int = 100, dry_run: bool = False) -> dict:
    """Sync version of the retry logic for CLI usage."""
    from app.models.document import Document, DocumentStatus
    from app.models.pipeline import PipelineStage, StageEnum, StageStatus
    from app.tasks.pipeline_orchestrator import dispatch_document

    db = _get_db()
    try:
        query = db.query(PipelineStage).filter(PipelineStage.status == StageStatus.FAILED)
        if stage:
            query = query.filter(PipelineStage.stage == StageEnum(stage))

        rows = query.order_by(PipelineStage.updated_at.desc()).limit(limit).all()

        retried = 0
        skipped = 0
        for ps in rows:
            doc = db.query(Document).filter(Document.id == ps.document_id).first()
            if doc and doc.status == DocumentStatus.ERROR:
                skipped += 1
                continue

            if not dry_run:
                ps.status = StageStatus.PENDING
                ps.attempt = 0
                ps.error_message = None
                ps.started_at = None
                ps.completed_at = None
                db.commit()

                result = dispatch_document(str(ps.document_id), from_stage=ps.stage)
                if result == "dispatched":
                    retried += 1
                else:
                    skipped += 1
                    logger.warning("Dispatch blocked for %s stage %s: %s", ps.document_id, ps.stage.value, result)
            else:
                logger.info("[DRY-RUN] Would retry %s stage %s", ps.document_id, ps.stage.value)
                retried += 1

        return {"retried": retried, "skipped": skipped, "stage": stage, "limit": limit}
    finally:
        db.close()


def show_status() -> None:
    """Print a quick text table of pipeline status."""
    from app.models.pipeline import PipelineStage, StageEnum, StageStatus

    db = _get_db()
    try:
        print("\n" + "=" * 60)
        print("Current Pipeline Status")
        print("=" * 60)
        print(f"{'Stage':<12} {'Pending':>8} {'Running':>8} {'Failed':>8} {'Completed':>10}")
        print("-" * 60)

        for s in StageEnum:
            counts = {
                StageStatus.PENDING: 0,
                StageStatus.RUNNING: 0,
                StageStatus.FAILED: 0,
                StageStatus.COMPLETED: 0,
            }
            for status, count in (
                db.query(PipelineStage.status, db.func.count())
                .filter(PipelineStage.stage == s)
                .group_by(PipelineStage.status)
                .all()
            ):
                counts[status] = count

            print(
                f"{s.value:<12} "
                f"{counts[StageStatus.PENDING]:>8} "
                f"{counts[StageStatus.RUNNING]:>8} "
                f"{counts[StageStatus.FAILED]:>8} "
                f"{counts[StageStatus.COMPLETED]:>10}"
            )
        print("=" * 60 + "\n")
    finally:
        db.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retry failed SOWKNOW pipeline stages")
    parser.add_argument("--stage", choices=STAGES, help="Retry only one stage")
    parser.add_argument("--limit", type=int, default=100, help="Max documents to retry per stage (default: 100)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be retried without dispatching")
    parser.add_argument("--all", action="store_true", help="Retry all failed stages in upstream-to-downstream order")
    parser.add_argument("--status", action="store_true", help="Print status table and exit")
    args = parser.parse_args(argv)

    if args.status:
        show_status()
        return 0

    if args.dry_run:
        logger.info("DRY RUN — no tasks will be dispatched")

    if args.all:
        # Retry in upstream-to-downstream order
        total_retried = 0
        total_skipped = 0
        for stage in STAGES:
            result = retry_failed_stages(stage=stage, limit=args.limit, dry_run=args.dry_run)
            logger.info(
                "Stage %-10s: retried=%d skipped=%d",
                stage,
                result["retried"],
                result["skipped"],
            )
            total_retried += result["retried"]
            total_skipped += result["skipped"]
        logger.info("TOTAL: retried=%d skipped=%d", total_retried, total_skipped)
    else:
        result = retry_failed_stages(stage=args.stage, limit=args.limit, dry_run=args.dry_run)
        logger.info("Retried %d, skipped %d", result["retried"], result["skipped"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
