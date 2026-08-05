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


@shared_task(
    bind=True,
    name="app.tasks.memory_tasks.build_memory_scenarios",
    queue="collections",
    soft_time_limit=300,  # 5 min
    time_limit=600,  # 10 min
)
def build_memory_scenarios(self) -> dict:
    """Nightly L2 clustering: fold reviewed atoms into memory_scenarios.

    Scans all users with ≥3 reviewed atoms and clusters them deterministically
    (entity/session overlap). Idempotent per atom-set; new scenarios start
    status=pending.
    """
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.database import _async_db_url
    from app.models.memory import MemoryAtom, MemoryStatus
    from app.services.memory_service import memory_service

    async def _run() -> dict:
        engine = create_async_engine(_async_db_url, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        try:
            async with session_factory() as db:
                owners = (
                    (
                        await db.execute(
                            select(MemoryAtom.owner_id)
                            .where(MemoryAtom.status == MemoryStatus.REVIEWED.value)
                            .group_by(MemoryAtom.owner_id)
                            .having(func.count(MemoryAtom.id) >= 3)
                        )
                    )
                    .scalars()
                    .all()
                )
                created = 0
                for owner_id in owners:
                    created += await memory_service.build_scenarios(db, owner_id)
                return {"owners": len(owners), "scenarios_created": created}
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("memory.build_scenarios failed: %s", exc, exc_info=True)
        return {"error": str(exc)[:500]}


@shared_task(
    bind=True,
    name="app.tasks.memory_tasks.build_memory_profiles",
    queue="collections",
    soft_time_limit=300,  # 5 min
    time_limit=600,  # 10 min
)
def build_memory_profiles(self) -> dict:
    """Monthly L3 profile builder: reviewed atoms → persona for each user.

    Idempotent upsert (version+1). Only users with ≥1 reviewed atom/scenario
    get a profile; LLM failures skip the user (never fabricates).
    """
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.database import _async_db_url
    from app.models.memory import MemoryAtom, MemoryStatus
    from app.services.memory_service import memory_service

    async def _run() -> dict:
        engine = create_async_engine(_async_db_url, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        try:
            async with session_factory() as db:
                owners = (
                    (
                        await db.execute(
                            select(MemoryAtom.owner_id)
                            .where(MemoryAtom.status == MemoryStatus.REVIEWED.value)
                            .group_by(MemoryAtom.owner_id)
                            .having(func.count(MemoryAtom.id) >= 1)
                        )
                    )
                    .scalars()
                    .all()
                )
                written = 0
                for owner_id in owners:
                    if await memory_service.build_profile(db, owner_id):
                        written += 1
                return {"owners": len(owners), "profiles_written": written}
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("memory.build_profiles failed: %s", exc, exc_info=True)
        return {"error": str(exc)[:500]}


@shared_task(
    bind=True,
    name="app.tasks.memory_tasks.extract_learned_skills",
    queue="collections",
    soft_time_limit=300,  # 5 min
    time_limit=600,  # 10 min
)
def extract_learned_skills(self, since_days: int = 7) -> dict:
    """Distill reusable runbook skills from recent completed collection runs."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.database import _async_db_url
    from app.services.skill_extraction_service import skill_extraction_service

    async def _run() -> dict:
        engine = create_async_engine(_async_db_url, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        try:
            async with session_factory() as db:
                created = await skill_extraction_service.extract_from_recent(db, since_days=since_days)
                return {"skills_created": created, "since_days": since_days}
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("skill.extract failed: %s", exc, exc_info=True)
        return {"error": str(exc)[:500]}
