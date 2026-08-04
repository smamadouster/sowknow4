#!/usr/bin/env python3
"""
Resumable backfill of search_vector with sowknow.unaccent (migration 036).

Re-stems document_chunks.search_vector and articles.search_vector with the
accent-folded expression used by migration 036's trigger functions, in
id-ordered batches that each commit. Safe to interrupt and re-run: progress is
persisted in a state file (default /tmp/migration036_backfill.state) so a
restart skips completed batches.

Correctness does not depend on this finishing — the app keeps BOTH accented
and unaccented @@ branches (see AGENTS.md), so search is right for every row
at every point of the transition. This backfill's job is to eventually make
the accented branches match nothing so they can be pruned.

Run from the backend container (has psycopg2 + DATABASE_URL):
    python scripts/migration036_backfill.py

The in-place UPDATE is deliberately SLOW on this table (bloated heap + huge
HNSW index → heavy shared-buffer churn), so this is a background job, not a
blocking migration step.
"""

import os
import sys
import time

STATE_FILE = os.environ.get(
    "MIGRATION036_STATE_FILE", "/tmp/migration036_backfill.state"
)
CHUNK_BATCH = int(os.environ.get("MIGRATION036_CHUNK_BATCH", "20000"))
ARTICLE_BATCH = int(os.environ.get("MIGRATION036_ARTICLE_BATCH", "1000"))

SAFE_CFG = (
    "COALESCE((SELECT cfgname::regconfig FROM pg_ts_config "
    "WHERE cfgname = COALESCE(search_language, 'french')), 'french'::regconfig)"
)
CHUNK_EXPR = f"to_tsvector({SAFE_CFG}, sowknow.unaccent(COALESCE(chunk_text, '')))"
ARTICLE_EXPR = (
    f"setweight(to_tsvector({SAFE_CFG}, sowknow.unaccent(COALESCE(title, ''))), 'A') || "
    f"setweight(to_tsvector({SAFE_CFG}, sowknow.unaccent(COALESCE(summary, ''))), 'B') || "
    f"setweight(to_tsvector({SAFE_CFG}, sowknow.unaccent(COALESCE(body, ''))), 'C')"
)


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    state = {}
    with open(STATE_FILE, encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                state[k] = v
    return state


def _save_state(state: dict) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for k, v in state.items():
            f.write(f"{k}={v}\n")
    os.replace(tmp, STATE_FILE)


def _backfill_table(
    cur, table: str, expr: str, batch: int, key: str, state: dict
) -> None:
    last_id = state.get(key)
    t0 = time.time()
    processed = 0
    while True:
        if last_id is None:
            cur.execute(
                f"SELECT id FROM sowknow.{table} ORDER BY id LIMIT %s", (batch,)
            )
        else:
            cur.execute(
                f"SELECT id FROM sowknow.{table} WHERE id > %s ORDER BY id LIMIT %s",
                (last_id, batch),
            )
        id_rows = [r[0] for r in cur.fetchall()]
        if not id_rows:
            break
        cur.execute(
            # Cast the id list to uuid[] — psycopg2 adapts a Python list to
            # text[], and `uuid = ANY(text[])` has no operator.
            f"UPDATE sowknow.{table} SET search_vector = {expr} WHERE id = ANY(%s::uuid[])",
            (id_rows,),
        )
        processed += len(id_rows)
        last_id = id_rows[-1]
        state[key] = str(last_id)
        _save_state(state)
        if len(id_rows) < batch:
            break
        print(f"  [{table}] {processed} rows done, last_id={last_id}", flush=True)
    print(f"[{table}] DONE: {processed} rows in {time.time() - t0:.1f}s", flush=True)


def main() -> int:
    import psycopg2

    dsn = os.environ.get("DATABASE_URL", "postgresql://sowknow@postgres:5432/sowknow")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True  # each batch commits independently
    cur = conn.cursor()
    state = _load_state()

    print("migration036 backfill starting (resumable)", flush=True)
    try:
        _backfill_table(
            cur, "document_chunks", CHUNK_EXPR, CHUNK_BATCH, "chunk_last_id", state
        )
        _backfill_table(
            cur, "articles", ARTICLE_EXPR, ARTICLE_BATCH, "article_last_id", state
        )
    finally:
        cur.close()
        conn.close()
    print("migration036 backfill complete", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
