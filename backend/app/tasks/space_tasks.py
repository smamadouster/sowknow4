import logging

from celery import shared_task

from app.tasks.base import log_task_memory

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def sync_space_rules_task(self, space_id: str):
    """Evaluate all active rules for a space and add matching items."""
    log_task_memory("sync_space_rules", "start")
    try:
        import asyncio

        from sqlalchemy import select as sa_select

        from app.database import AsyncSessionLocal
        from app.models.space import Space as SpaceModel
        from app.services.space_service import space_service

        async def _run():
            async with AsyncSessionLocal() as async_db:
                space = (await async_db.execute(
                    sa_select(SpaceModel).where(SpaceModel.id == space_id)
                )).scalar_one_or_none()
                if not space:
                    logger.warning(f"Space {space_id} not found for sync")
                    return 0
                added = await space_service.sync_space_rules(async_db, space)
                logger.info(f"Space {space_id} sync complete: {added} items added")
                return added

        return asyncio.run(_run())

    except Exception as exc:
        logger.error(f"Space sync failed for {space_id}: {exc}")
        raise self.retry(exc=exc, countdown=30)
    finally:
        log_task_memory("sync_space_rules", "end")
