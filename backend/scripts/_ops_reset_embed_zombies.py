#!/usr/bin/env python3
"""
Ops script: Reset zombie embedded tasks that are "running" for >1 hour
but have empty Celery queues. Run inside backend container.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")
os.chdir("/app")

from app.database import AsyncSessionLocal
from app.models.pipeline import PipelineStage, StageStatus, StageEnum
from sqlalchemy import select, update

STALE_MINUTES = 60


async def main():
    async with AsyncSessionLocal() as db:
        # Find zombie embedded tasks
        result = await db.execute(
            select(PipelineStage)
            .where(
                PipelineStage.stage == StageEnum.EMBEDDED,
                PipelineStage.status == StageStatus.RUNNING,
                PipelineStage.updated_at < datetime.now(timezone.utc) - __import__("datetime").timedelta(minutes=STALE_MINUTES),
            )
        )
        zombies = result.scalars().all()

        if not zombies:
            print("No zombie embedded tasks found.")
            return

        print(f"Found {len(zombies)} zombie embedded task(s) (running >{STALE_MINUTES} min):")
        for z in zombies:
            print(f"  doc={z.document_id}  updated_at={z.updated_at}  attempt={z.attempt}/{z.max_attempts}")

        # Reset to pending so the orchestrator re-dispatches them
        for z in zombies:
            z.status = StageStatus.PENDING
            z.attempt = 0
            z.started_at = None
            z.error_message = "Zombie task reset by ops journal: running >1h with empty Celery queue"
            z.updated_at = datetime.now(timezone.utc)

        await db.commit()
        print(f"\nReset {len(zombies)} task(s) to PENDING.")


if __name__ == "__main__":
    asyncio.run(main())
