#!/usr/bin/env python3
"""
Resumable backfill: distill existing chat sessions into memory atoms (L1).

Walks chat_sessions in id-ordered batches, distilling each opted-in (or all,
when --all) session through memory_service.distill_session (which calls the
LLM). Progress is persisted in a state file (default
/tmp/memory_backfill.state) so a restart skips completed sessions — the id
window MUST advance (WHERE id > :last_id), mirroring the migration036_backfill
lesson about not re-processing the same first rows forever.

Run from the backend container (has asyncpg + DATABASE_URL):
    python scripts/memory_backfill.py          # opted-in sessions only
    python scripts/memory_backfill.py --all    # every session
    python scripts/memory_backfill.py --batch 5 --state /tmp/x.state
"""

import argparse
import os
import sys
import time
from pathlib import Path
from uuid import UUID

# The backend app package lives one directory above this script (inside the
# backend container it is /app/app). Ensure it is importable regardless of
# where the script is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STATE_FILE = os.environ.get("MEMORY_BACKFILL_STATE", "/tmp/memory_backfill.state")
BATCH = 20


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


async def _distill_batch(session_factory, session_ids, *, all_sessions: bool) -> int:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.chat import ChatSession
    from app.services.memory_service import memory_service

    inserted = 0
    async with session_factory() as db:
        sessions = (
            (
                await db.execute(
                    select(ChatSession).where(ChatSession.id.in_(session_ids))
                )
            )
            .scalars()
            .all()
        )
        for s in sessions:
            if not all_sessions and not getattr(s, "memory_enabled", False):
                continue
            if s.user_id is None:
                continue
            try:
                atoms = await memory_service.distill_session(db, s.id, s.user_id)
                inserted += len(atoms)
            except Exception as exc:
                print(f"  ! session {s.id} failed: {str(exc)[:200]}", flush=True)
    return inserted


async def main() -> int:
    import asyncio

    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import NullPool

    from app.database import _async_db_url

    parser = argparse.ArgumentParser(
        description="Distill existing chat sessions into memory atoms"
    )
    parser.add_argument(
        "--all", action="store_true", help="distill every session, not just opted-in"
    )
    parser.add_argument("--batch", type=int, default=BATCH, help="sessions per batch")
    parser.add_argument("--state", default=None, help="state file path")
    parser.add_argument(
        "--limit", type=int, default=0, help="max sessions to process (0 = all)"
    )
    args = parser.parse_args()

    global STATE_FILE
    STATE_FILE = args.state or os.environ.get(
        "MEMORY_BACKFILL_STATE", "/tmp/memory_backfill.state"
    )

    engine = create_async_engine(_async_db_url, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    state = _load_state()
    last_id = state.get("last_id")
    processed = 0
    t0 = time.time()

    from sqlalchemy import select

    from app.models.chat import ChatSession

    try:
        while True:
            async with session_factory() as db:
                if last_id is None:
                    q = (
                        select(ChatSession.id)
                        .order_by(ChatSession.id)
                        .limit(args.batch)
                    )
                else:
                    q = (
                        select(ChatSession.id)
                        .where(ChatSession.id > UUID(last_id))
                        .order_by(ChatSession.id)
                        .limit(args.batch)
                    )
                ids = list((await db.execute(q)).scalars().all())
            if not ids:
                break
            inserted = await _distill_batch(session_factory, ids, all_sessions=args.all)
            processed += len(ids)
            last_id = str(ids[-1])
            state["last_id"] = last_id
            _save_state(state)
            print(
                f"  {processed} sessions done (last_id={last_id}, +{inserted} atoms)",
                flush=True,
            )
            if args.limit and processed >= args.limit:
                break
    finally:
        await engine.dispose()
    print(
        f"memory backfill complete: {processed} sessions in {time.time() - t0:.1f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))
