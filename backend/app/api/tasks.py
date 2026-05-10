import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.task import (
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskUpdate,
)
from app.schemas.tag import TagResponse
from app.services.task_service import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    try:
        task = await task_service.create_task(
            db=db,
            user=current_user,
            title=data.title,
            description=data.description,
            status=data.status.value,
            priority=data.priority.value,
            due_date=data.due_date,
            alarm_at=data.alarm_at,
            notes=data.notes,
            bucket=data.bucket.value,
            tags=[t.model_dump() for t in data.tags],
        )
    except Exception as e:
        logger.error(f"Failed to create task: {e}")
        raise HTTPException(status_code=500, detail="Failed to create task")
    # Check space rules for new task
    try:
        from app.services.space_service import space_service
        await space_service.check_rules_for_new_item(db, "task", task.id)
    except Exception as e:
        logger.warning(f"Space rule check failed for task {task.id}: {e}")
    tags = await task_service.get_tags_for_task(db, task.id)
    return _to_response(task, tags)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    tag: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskListResponse:
    try:
        tasks, total = await task_service.list_tasks(
            db=db, user=current_user, page=page, page_size=page_size, tag=tag,
        )
    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        raise HTTPException(status_code=500, detail="Failed to list tasks")
    items = []
    for t in tasks:
        tags = await task_service.get_tags_for_task(db, t.id)
        items.append(_to_response(t, tags))
    return TaskListResponse(tasks=items, total=total, page=page, page_size=page_size)


@router.get("/search", response_model=TaskListResponse)
async def search_tasks(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskListResponse:
    tasks, total = await task_service.search_tasks(
        db=db, user=current_user, query_str=q, page=page, page_size=page_size,
    )
    items = []
    for t in tasks:
        tags = await task_service.get_tags_for_task(db, t.id)
        items.append(_to_response(t, tags))
    return TaskListResponse(tasks=items, total=total, page=page, page_size=page_size)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task = await task_service.get_task(db, task_id, current_user)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    tags = await task_service.get_tags_for_task(db, task.id)
    return _to_response(task, tags)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    data: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task = await task_service.get_task(db, task_id, current_user)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    update_dict = data.model_dump(exclude_unset=True)
    if "tags" in update_dict and update_dict["tags"] is not None:
        update_dict["tags"] = [t.model_dump() for t in data.tags]

    task = await task_service.update_task(db, task, update_dict)
    tags = await task_service.get_tags_for_task(db, task.id)
    return _to_response(task, tags)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    task = await task_service.get_task(db, task_id, current_user)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    await task_service.delete_task(db, task)


def _to_response(task, tags) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        user_id=task.user_id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        due_date=task.due_date,
        alarm_at=task.alarm_at,
        alarm_triggered=task.alarm_triggered,
        notes=task.notes,
        bucket=task.bucket,
        tags=[TagResponse.model_validate(t) for t in tags],
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
