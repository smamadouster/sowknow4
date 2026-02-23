#!/usr/bin/env python3
"""
Backfill script for migrating embeddings from JSONB to pgvector column.

This script migrates existing embeddings stored in document_chunks.metadata->'embedding'
to the new embedding_vector column using pgvector.

Usage:
    python scripts/backfill_embeddings_to_vector.py [--dry-run] [--batch-size N]

Options:
    --dry-run     Run without making changes
    --batch-size N  Number of records to process per batch (default: 100)
"""

import os
import sys
import argparse
import logging
from typing import List, Dict, Any

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection from environment variables."""
    from sqlalchemy import create_engine

    db_url = os.getenv(
        "DATABASE_URL", "postgresql://sowknow:sowknow@localhost:5432/sowknow"
    )
    engine = create_engine(db_url)
    return engine


def count_chunks_to_migrate(engine) -> int:
    """Count chunks that have embeddings in JSONB but not in vector column."""
    from sqlalchemy import text

    query = text("""
        SELECT COUNT(*) 
        FROM sowknow.document_chunks
        WHERE metadata ? 'embedding'
        AND metadata->>'embedding' IS NOT NULL
        AND (metadata->>'embedding')::text != 'null'
        AND embedding_vector IS NULL
    """)

    with engine.connect() as conn:
        result = conn.execute(query)
        return result.scalar() or 0


def fetch_chunks_batch(engine, batch_size: int, offset: int) -> List[Dict[str, Any]]:
    """Fetch a batch of chunks that need migration."""
    from sqlalchemy import text

    query = text("""
        SELECT id, metadata->>'embedding' as embedding_json
        FROM sowknow.document_chunks
        WHERE metadata ? 'embedding'
        AND metadata->>'embedding' IS NOT NULL
        AND (metadata->>'embedding')::text != 'null'
        AND embedding_vector IS NULL
        ORDER BY id
        LIMIT :limit OFFSET :offset
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {"limit": batch_size, "offset": offset})
        return [dict(row._mapping) for row in result]


def parse_embedding(embedding_json: str) -> List[float]:
    """Parse embedding from JSON string to list of floats."""
    import json

    try:
        embedding = json.loads(embedding_json)
        if isinstance(embedding, list):
            return [float(x) for x in embedding]
        return None
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(f"Failed to parse embedding: {e}")
        return None


def update_chunk_embedding(engine, chunk_id: str, embedding: List[float]):
    """Update a single chunk's embedding_vector column."""
    from sqlalchemy import text

    # Convert to PostgreSQL array format
    embedding_array = "[" + ",".join(map(str, embedding)) + "]"

    query = text("""
        UPDATE sowknow.document_chunks
        SET embedding_vector = :embedding::vector
        WHERE id = :chunk_id
    """)

    with engine.connect() as conn:
        conn.execute(query, {"embedding": embedding_array, "chunk_id": chunk_id})
        conn.commit()


def backfill_embeddings(dry_run: bool = False, batch_size: int = 100):
    """
    Backfill embeddings from JSONB to vector column.

    Args:
        dry_run: If True, only count and report, don't make changes
        batch_size: Number of records to process per batch
    """
    engine = get_db_connection()

    # Count total records to migrate
    total = count_chunks_to_migrate(engine)
    logger.info(f"Found {total} chunks to migrate")

    if dry_run:
        logger.info("DRY RUN - No changes will be made")
        return

    if total == 0:
        logger.info("No chunks need migration")
        return

    # Process in batches
    offset = 0
    migrated = 0
    failed = 0

    while offset < total:
        chunks = fetch_chunks_batch(engine, batch_size, offset)

        if not chunks:
            break

        for chunk in chunks:
            try:
                embedding = parse_embedding(chunk["embedding_json"])
                if embedding and len(embedding) == 1024:
                    update_chunk_embedding(engine, chunk["id"], embedding)
                    migrated += 1
                else:
                    logger.warning(
                        f"Invalid embedding length for chunk {chunk['id']}: {len(embedding) if embedding else 'None'}"
                    )
                    failed += 1
            except Exception as e:
                logger.error(f"Failed to migrate chunk {chunk['id']}: {e}")
                failed += 1

        offset += batch_size
        logger.info(
            f"Progress: {offset}/{total} ({migrated} migrated, {failed} failed)"
        )

    logger.info(f"Migration complete: {migrated} migrated, {failed} failed")


def verify_migration(engine) -> Dict[str, Any]:
    """Verify the migration results."""
    from sqlalchemy import text

    # Count chunks with embeddings in vector column
    query_vector = text("""
        SELECT COUNT(*) 
        FROM sowknow.document_chunks
        WHERE embedding_vector IS NOT NULL
    """)

    # Count chunks still only in JSONB
    query_jsonb = text("""
        SELECT COUNT(*) 
        FROM sowknow.document_chunks
        WHERE metadata ? 'embedding'
        AND embedding_vector IS NULL
    """)

    with engine.connect() as conn:
        vector_count = conn.execute(query_vector).scalar() or 0
        jsonb_count = conn.execute(query_jsonb).scalar() or 0

    return {
        "chunks_with_vector": vector_count,
        "chunks_still_jsonb": jsonb_count,
        "migration_complete": jsonb_count == 0,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Backfill embeddings from JSONB to pgvector column"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run without making changes"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of records to process per batch (default: 100)",
    )
    parser.add_argument(
        "--verify", action="store_true", help="Only verify migration status"
    )

    args = parser.parse_args()

    engine = get_db_connection()

    if args.verify:
        result = verify_migration(engine)
        logger.info(f"Verification results: {result}")
        return

    backfill_embeddings(dry_run=args.dry_run, batch_size=args.batch_size)

    # Verify after migration
    result = verify_migration(engine)
    logger.info(f"Final verification: {result}")


if __name__ == "__main__":
    main()
