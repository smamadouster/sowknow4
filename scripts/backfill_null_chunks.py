#!/usr/bin/env python3
"""Backfill NULL chunk embeddings (chunk-level, P1 follow-up of 2026-07-28 P0).

Why this exists: 179k chunks had NULL embedding_vector while their parent
documents were marked embedding_generated=true (partial stage failures).
Document-level backfill tasks can't see them — this works at chunk level.

Design:
- Idempotent: only touches chunks where embedding_vector IS NULL.
- Batched (64/request), round-robins the two embed replicas, commits per
  batch, logs progress to /tmp/backfill_chunks.log.
- Polite: small sleep between batches; yields to search traffic.

Run inside celery-heavy:  docker exec -d -e PYTHONPATH=/app sowknow-celery-heavy python /tmp/backfill_null_chunks.py
"""

import os
import time
import datetime
import httpx
from sqlalchemy import text

from app.database import SessionLocal

EMBED_URLS = os.getenv(
    "EMBED_SERVER_URL", "http://embed-server:8000,http://embed-server-2:8000"
).split(",")
BATCH_FETCH = 512
BATCH_EMBED = 32  # 2026-07-28: sweet spot — 64 timed out, 16 too slow (29h ETA)
LOG = "/tmp/backfill_chunks.log"


def log(msg: str) -> None:
    line = f"{datetime.datetime.utcnow().isoformat()}Z {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def main() -> None:
    total_done = 0
    url_idx = 0
    client = httpx.Client(timeout=300)
    log("backfill start")
    while True:
        with SessionLocal() as db:
            rows = db.execute(
                text(
                    "SELECT id, chunk_text FROM document_chunks "
                    "WHERE embedding_vector IS NULL ORDER BY id LIMIT :n"
                ),
                {"n": BATCH_FETCH},
            ).all()
            if not rows:
                break
            for i in range(0, len(rows), BATCH_EMBED):
                batch = rows[i : i + BATCH_EMBED]
                url = EMBED_URLS[url_idx % len(EMBED_URLS)].strip()
                url_idx += 1
                try:
                    resp = client.post(f"{url}/embed", json={"texts": [r[1] for r in batch]})
                    resp.raise_for_status()
                    vectors = resp.json()
                except Exception as exc:
                    log(f"embed call failed ({url}): {str(exc)[:150]} — sleeping 30s")
                    time.sleep(30)
                    continue
                if len(vectors) != len(batch):
                    log(f"vector count mismatch {len(vectors)} != {len(batch)} — skipping batch")
                    continue
                for row, vec in zip(batch, vectors):
                    db.execute(
                        text(
                            "UPDATE document_chunks SET embedding_vector = CAST(:v AS vector) "
                            "WHERE id = :id"
                        ),
                        {"v": "[" + ",".join(map(str, vec)) + "]", "id": str(row[0])},
                    )
                db.commit()
                total_done += len(batch)
                if total_done % 2048 < BATCH_EMBED:
                    log(f"progress: {total_done} chunks embedded")
                time.sleep(0.3)  # overnight window: light throttle, embed compute dominates anyway
    log(f"backfill complete: {total_done} chunks embedded")


if __name__ == "__main__":
    main()
