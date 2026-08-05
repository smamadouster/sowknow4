"""Celery task for Agent Memory distillation (draft v0.1).

Runs one distillation pass over a chat session, following the
collection_request_tasks.py idiom: async runner inside @shared_task with its
own AsyncSessionLocal (NullPool). On failure the task logs and leaves atoms
undistilled — the memory row status, not Celery, is the source of truth, so
no autoretry: a later sweep can re-process the session.
"""

import asyncio
import logging
from uuid import UUID

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="app.tasks.memory_tasks.distill_chat_session",
    queue="collections",
    soft_time_limit=120,  # 2 min
    time_limit=240,  # 4 min
)
def distill_chat_session(self, session_id: str, owner_id: str) -> dict:
    """Distill one chat session into memory atoms (L1)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.database import _async_db_url
    from app.services.memory_service import memory_service

    async def _run() -> dict:
        engine = create_async_engine(_async_db_url, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        try:
            async with session_factory() as db:
                atoms = await memory_service.distill_session(db, UUID(session_id), UUID(owner_id))
                return {
                    "session_id": session_id,
                    "owner_id": owner_id,
                    "atoms_inserted": len(atoms),
                }
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("memory.distill session=%s failed: %s", session_id, exc, exc_info=True)
        return {"session_id": session_id, "error": str(exc)[:500]}
