import logging
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.note import (
    NoteCreate,
    NoteListResponse,
    NoteResponse,
    NoteUpdate,
)
from app.schemas.tag import TagResponse
from app.services.note_service import note_service

router = APIRouter(prefix="/notes", tags=["notes"])
logger = logging.getLogger(__name__)


@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    data: NoteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteResponse:
    try:
        note = await note_service.create_note(
            db=db,
            user=current_user,
            title=data.title,
            content=data.content,
            bucket=data.bucket.value,
            tags=[t.model_dump() for t in data.tags],
        )
    except Exception as e:
        logger.error(f"Failed to create note: {e}")
        raise HTTPException(status_code=500, detail="Failed to create note")
    # Check space rules for new note
    try:
        from app.services.space_service import space_service
        await space_service.check_rules_for_new_item(db, "note", note.id)
    except Exception as e:
        logger.warning(f"Space rule check failed for note {note.id}: {e}")
    tags = await note_service.get_tags_for_note(db, note.id)
    return _to_response(note, tags)


@router.get("", response_model=NoteListResponse)
async def list_notes(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    tag: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteListResponse:
    try:
        notes, total = await note_service.list_notes(
            db=db, user=current_user, page=page, page_size=page_size, tag=tag,
        )
    except Exception as e:
        logger.error(f"Failed to list notes: {e}")
        raise HTTPException(status_code=500, detail="Failed to list notes")
    items = []
    for n in notes:
        tags = await note_service.get_tags_for_note(db, n.id)
        items.append(_to_response(n, tags))
    return NoteListResponse(notes=items, total=total, page=page, page_size=page_size)


@router.get("/search", response_model=NoteListResponse)
async def search_notes(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteListResponse:
    notes, total = await note_service.search_notes(
        db=db, user=current_user, query_str=q, page=page, page_size=page_size,
    )
    items = []
    for n in notes:
        tags = await note_service.get_tags_for_note(db, n.id)
        items.append(_to_response(n, tags))
    return NoteListResponse(notes=items, total=total, page=page, page_size=page_size)


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteResponse:
    note = await note_service.get_note(db, note_id, current_user)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    tags = await note_service.get_tags_for_note(db, note.id)
    return _to_response(note, tags)


@router.put("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: UUID,
    data: NoteUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteResponse:
    note = await note_service.get_note(db, note_id, current_user)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    update_dict = data.model_dump(exclude_unset=True)
    if "tags" in update_dict and update_dict["tags"] is not None:
        update_dict["tags"] = [t.model_dump() for t in data.tags]

    note = await note_service.update_note(db, note, update_dict)
    tags = await note_service.get_tags_for_note(db, note.id)
    return _to_response(note, tags)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    note = await note_service.get_note(db, note_id, current_user)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    await note_service.delete_note(db, note)


@router.post("/{note_id}/audio")
async def upload_note_audio(
    note_id: str,
    file: UploadFile = File(...),
    transcript: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload an audio attachment to a note."""
    import os
    import uuid as uuid_mod
    from datetime import datetime

    from app.models.note import Note
    from app.models.note_audio import NoteAudio

    ALLOWED_AUDIO = {"audio/webm", "audio/ogg", "audio/wav", "audio/mpeg"}
    if file.content_type not in ALLOWED_AUDIO:
        raise HTTPException(status_code=400, detail="Invalid audio format")

    # Verify note exists and belongs to user
    result = await db.execute(select(Note).where(Note.id == uuid_mod.UUID(note_id), Note.user_id == current_user.id))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    # Save audio file
    now = datetime.utcnow()
    audio_dir = f"/data/audio/{now.year}/{now.month:02d}"
    os.makedirs(audio_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "audio.webm")[1] or ".webm"
    audio_id = uuid_mod.uuid4()
    file_path = f"{audio_dir}/{audio_id}{ext}"

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    note_audio = NoteAudio(
        id=audio_id,
        note_id=uuid_mod.UUID(note_id),
        file_path=file_path,
        transcript=transcript,
    )
    db.add(note_audio)
    await db.commit()

    return {
        "audio_id": str(audio_id),
        "url": f"/api/v1/voice/audio/{audio_id}/stream",
        "transcript": transcript,
    }


def _to_response(note, tags) -> NoteResponse:
    return NoteResponse(
        id=note.id,
        user_id=note.user_id,
        title=note.title,
        content=note.content,
        bucket=note.bucket,
        tags=[TagResponse.model_validate(t) for t in tags],
        created_at=note.created_at,
        updated_at=note.updated_at,
    )
