"""
backfill_embeddings.py — populate the pgvector embedding_vector column for
document chunks that were processed before migration 004_add_pgvector_column.

Usage:
    python -m scripts.backfill_embeddings [--dry-run] [--batch-size N]

Options:
    --dry-run      Scan and report counts without writing anything (default: False)
    --batch-size   Number of chunks to process per commit cycle (default: 100)
"""

import argparse
import json
import logging
import os
import sys

from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill pgvector embedding_vector column")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    parser.add_argument("--batch-size", type=int, default=100, metavar="N")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not DATABASE_URL:
        logger.error("DATABASE_URL environment variable is not set")
        sys.exit(1)

    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        # Count chunks eligible for backfill
        count_row = conn.execute(
            text(
                "SELECT COUNT(*) FROM document_chunks "
                "WHERE embedding_vector IS NULL "
                "  AND metadata->>'embedding' IS NOT NULL"
            )
        ).fetchone()
        total = count_row[0] if count_row else 0
        logger.info(f"Chunks eligible for backfill: {total}")

        if total == 0:
            logger.info("Nothing to backfill — exiting")
            return

        if args.dry_run:
            logger.info("Dry-run mode: no changes written")
            return

        # Fetch and process in batches
        processed = 0
        errors = 0
        offset = 0

        while True:
            rows = conn.execute(
                text(
                    "SELECT id, metadata FROM document_chunks "
                    "WHERE embedding_vector IS NULL "
                    "  AND metadata->>'embedding' IS NOT NULL "
                    "ORDER BY id "
                    "LIMIT :limit OFFSET :offset"
                ),
                {"limit": args.batch_size, "offset": offset},
            ).fetchall()

            if not rows:
                break

            for row in rows:
                chunk_id, metadata = row[0], row[1]
                try:
                    if isinstance(metadata, str):
                        metadata = json.loads(metadata)
                    embedding = metadata.get("embedding")
                    if not embedding:
                        continue

                    # Write to the vector column using a cast
                    vector_literal = "[" + ",".join(str(v) for v in embedding) + "]"
                    conn.execute(
                        text(
                            "UPDATE document_chunks "
                            "SET embedding_vector = :vec::vector "
                            "WHERE id = :id"
                        ),
                        {"vec": vector_literal, "id": chunk_id},
                    )
                    processed += 1
                except Exception as exc:
                    logger.warning(f"Chunk {chunk_id}: {exc}")
                    errors += 1

            conn.commit()
            offset += args.batch_size
            logger.info(f"Progress: {processed} written, {errors} errors (batch offset {offset})")

        logger.info(f"Backfill complete — {processed} updated, {errors} errors")


if __name__ == "__main__":
    main()
