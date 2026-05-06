#!/usr/bin/env python3
"""
Emergency pipeline unblock script.

1. Purges poisoned Celery tasks from pipeline.embed and pipeline.entities queues.
2. Marks poison documents as ERROR so the sweeper does not re-dispatch them.
3. Reports queue state before/after.
"""

import asyncio
import base64
import json
import os
import sys

os.chdir("/app")
sys.path.insert(0, "/app")

import redis.asyncio as aioredis
from sqlalchemy import update

from app.database import AsyncSessionLocal
from app.models.document import Document


REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "Tata266Zx88")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:6379/0"

EMBED_POISON_DOC_IDS = {
    "63c57a15-b1d2-4e9d-9b2f-3062557858ab",
    "d0f69d17-f15c-4341-8ae8-ef7d7f080f9a",
}

ENTITY_MAX_DUPLICATES = 5


def _extract_doc_id_from_task(raw: bytes) -> str | None:
    """Best-effort parse of a Celery task message to get the doc_id from argsrepr."""
    try:
        data = json.loads(raw)
        body_b64 = data.get("body", "")
        body = base64.b64decode(body_b64)
        payload = json.loads(body)
        # payload is [[args], {}, {chain: [...]}]
        if payload and isinstance(payload[0], list) and len(payload[0]) > 0:
            doc_id = payload[0][0]
            if isinstance(doc_id, str) and len(doc_id) == 36:
                return doc_id
    except Exception:
        pass
    # fallback: grep argsrepr from the raw JSON string
    try:
        text = raw.decode("utf-8", errors="ignore")
        import re
        m = re.search(r"argsrepr.*?'([a-f0-9-]{36})'", text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


async def purge_queue(redis: aioredis.Redis, queue_name: str, poison_ids: set[str]) -> int:
    removed = 0
    length = await redis.llen(queue_name)
    if length == 0:
        return 0

    items = await redis.lrange(queue_name, 0, length - 1)
    keep = []
    for item in items:
        doc_id = _extract_doc_id_from_task(item)
        if doc_id in poison_ids:
            removed += 1
        else:
            keep.append(item)

    if removed:
        await redis.delete(queue_name)
        if keep:
            await redis.rpush(queue_name, *keep)
    return removed


async def main():
    redis = aioredis.from_url(REDIS_URL, decode_responses=False)

    # --- EMBED QUEUE ---
    embed_len_before = await redis.llen("pipeline.embed")
    embed_removed = await purge_queue(redis, "pipeline.embed", EMBED_POISON_DOC_IDS)
    embed_len_after = await redis.llen("pipeline.embed")

    # --- ENTITIES QUEUE ---
    entities_len_before = await redis.llen("pipeline.entities")
    entity_items = await redis.lrange("pipeline.entities", 0, entities_len_before - 1)
    entity_doc_counts: dict[str, int] = {}
    for item in entity_items:
        doc_id = _extract_doc_id_from_task(item)
        if doc_id:
            entity_doc_counts[doc_id] = entity_doc_counts.get(doc_id, 0) + 1

    entity_poison_ids = {
        doc_id for doc_id, count in entity_doc_counts.items()
        if count >= ENTITY_MAX_DUPLICATES
    }
    entity_removed = await purge_queue(redis, "pipeline.entities", entity_poison_ids)
    entities_len_after = await redis.llen("pipeline.entities")

    # --- MARK POISON DOCS AS ERROR ---
    all_poison_ids = EMBED_POISON_DOC_IDS | entity_poison_ids
    async with AsyncSessionLocal() as db:
        if all_poison_ids:
            result = await db.execute(
                update(Document)
                .where(Document.id.in_(list(all_poison_ids)))
                .where(Document.status != "error")
                .values(
                    status="error",
                    pipeline_error="Quarantined by unblock script: poison pill (excessive retries/queue flooding)",
                    pipeline_stage="error",
                )
            )
            await db.commit()
            updated_rows = result.rowcount
        else:
            updated_rows = 0

        # Also mark any doc with >5000 chunks as error if it's still not indexed
        result2 = await db.execute(
            update(Document)
            .where(Document.chunk_count > 5000)
            .where(Document.status.notin_(["indexed", "error"]))
            .values(
                status="error",
                pipeline_error="Quarantined: legacy oversized document (>5000 chunks)",
                pipeline_stage="error",
            )
        )
        await db.commit()
        oversized_rows = result2.rowcount

    print("=" * 60)
    print("PIPELINE UNBLOCK RESULTS")
    print("=" * 60)
    print(f"\nEmbed queue:  {embed_len_before} -> {embed_len_after} (removed {embed_removed})")
    print(f"  Poison docs: {EMBED_POISON_DOC_IDS}")
    print(f"\nEntity queue: {entities_len_before} -> {entities_len_after} (removed {entity_removed})")
    print(f"  Poison docs ({len(entity_poison_ids)}): {sorted(entity_poison_ids)[:10]}{'...' if len(entity_poison_ids) > 10 else ''}")
    print(f"\nDB updates:   {updated_rows} poison docs marked error")
    print(f"              {oversized_rows} oversized non-indexed docs marked error")
    print("\nNext steps:")
    print("  1. Restart celery-heavy and celery-entities workers to kill in-flight poison tasks.")
    print("  2. Monitor queue depths with: redis-cli LLEN pipeline.embed / pipeline.entities")
    print("=" * 60)

    await redis.close()


if __name__ == "__main__":
    asyncio.run(main())
