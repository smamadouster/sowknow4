#!/usr/bin/env python3
"""Backfill NULL chunk embeddings (chunk-level, P1 follow-up of 2026-07-28 P0).

Why this exists: 179k chunks had NULL embedding_vector while their parent
documents were marked embedding_generated=true (partial stage failures).
Document-level backfill tasks can't see them — this works at chunk level.

Design:
- Idempotent: only touches chunks where embedding_vector IS NULL.
- Concurrent (6 workers × 32-text batches) — the sequential version wasted
  half of each embed server's capacity (round-robin idle). Rate-limited by
  the workers' own pacing, leaves headroom for interactive search.
- Batches claimed via a shared queue; each worker commits its own batch.
- Logs progress to /tmp/backfill_chunks.log.

Run:  docker exec -d -e PYTHONPATH=/app sowknow-celery-heavy python /tmp/backfill_null_chunks.py
"""

import asyncio
import datetime
import os

import httpx
from sqlalchemy import text

from app.database import SessionLocal

EMBED_URLS = os.getenv(
    "EMBED_SERVER_URL", "http://embed-server:8000,http://embed-server-2:8000"
).split(",")
BATCH_FETCH = 4096
BATCH_EMBED = 32
WORKERS = 6
LOG = "/tmp/backfill_chunks.log"

_done = 0
_lock = asyncio.Lock()


def log(msg: str) -> None:
    line = f"{datetime.datetime.utcnow().isoformat()}Z {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


async def worker(wid: int, queue: asyncio.Queue, client: httpx.AsyncClient) -> None:
    global _done
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            return
        batch = item
        url = EMBED_URLS[wid % len(EMBED_URLS)].strip()
        try:
            resp = await client.post(
                f"{url}/embed",
                json={"texts": [r[1] for r in batch]},
                timeout=600,  # 2026-07-28: measured 223-307s per 32-batch on loaded CPU
            )
            resp.raise_for_status()
            vectors = resp.json()
            if len(vectors) != len(batch):
                raise ValueError(f"vector count mismatch {len(vectors)} != {len(batch)}")
            # Sync SQLAlchemy in a thread — keep the loop responsive
            await asyncio.to_thread(_write_batch, batch, vectors)
            async with _lock:
                _done += len(batch)
                done = _done
            if done % 2048 < BATCH_EMBED:
                log(f"progress: {done} chunks embedded")
        except Exception as exc:
            log(f"worker{wid} embed failed ({url}): {str(exc)[:120]} — requeueing")
            await asyncio.sleep(15)
            await queue.put(batch)  # retry later
        finally:
            queue.task_done()
        await asyncio.sleep(0.2)  # light pacing


def _write_batch(batch, vectors) -> None:
    with SessionLocal() as db:
        for row, vec in zip(batch, vectors):
            db.execute(
                text(
                    "UPDATE document_chunks SET embedding_vector = CAST(:v AS vector) "
                    "WHERE id = :id"
                ),
                {"v": "[" + ",".join(map(str, vec)) + "]", "id": str(row[0])},
            )
        db.commit()


async def main() -> None:
    log("backfill start")
    queue: asyncio.Queue = asyncio.Queue(maxsize=WORKERS * 2)
    client = httpx.AsyncClient()
    workers = [asyncio.create_task(worker(i, queue, client)) for i in range(WORKERS)]

    while True:
        rows = await asyncio.to_thread(_fetch_batch)
        if not rows:
            break
        for i in range(0, len(rows), BATCH_EMBED):
            await queue.put(rows[i : i + BATCH_EMBED])

    for _ in workers:
        await queue.put(None)
    await asyncio.gather(*workers)
    await client.aclose()
    log(f"backfill complete: {_done} chunks embedded")


def _fetch_batch():
    with SessionLocal() as db:
        return db.execute(
            text(
                "SELECT id, chunk_text FROM document_chunks "
                "WHERE embedding_vector IS NULL ORDER BY id LIMIT :n"
            ),
            {"n": BATCH_FETCH},
        ).all()


if __name__ == "__main__":
    asyncio.run(main())
