"""Collection Requests API — Collection Orchestrator endpoints.

Full request lifecycle: create (FR1 clarification start) → clarify rounds →
confirm (immutable params, enqueue Celery job) → status / SSE stream →
annotated items (FR5.4) → deliverable view / PDF export (FR5) → audit chain
export (FR8.1).

Every endpoint is owner-scoped: a SmartFolder belonging to another user is
indistinguishable from a missing one (404, never a 403 leak).
"""

import asyncio
import csv
import io
import json
import logging
import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_superuser_or_admin
from app.database import get_db
from app.models.collection_orchestrator import (
    AnalysisResult,
    Annotation,
    ClarificationSession,
    CollectionAuditEvent,
    Deliverable,
    FactSet,
    QueryExecution,
    SourceItem,
)
from app.models.smart_folder import CollectionJobState, SmartFolder, SmartFolderStatus
from app.models.user import User
from app.schemas.collection_orchestrator import (
    ClarificationAnswer,
    ClarificationPayload,
    ClarificationStepResponse,
    CollectionJobStatusResponse,
    CollectionRequestCreate,
    CollectionRequestCreated,
    ConfirmEnqueueResponse,
)
from app.services.collection_orchestrator import audit_logger
from app.services.collection_orchestrator.conversation_manager import conversation_manager
from app.services.collection_orchestrator import packaging_service
from app.services.collection_orchestrator.metrics import (
    compute_metrics,
    evaluate_alerts,
)

router = APIRouter(prefix="/collection-requests", tags=["collection-requests"])
logger = logging.getLogger(__name__)

SSE_MAX_POLLS = 120        # ~3 minutes at 1.5s intervals
SSE_POLL_INTERVAL = 1.5

STATE_STEPS: dict[str, tuple[str, str, int]] = {
    CollectionJobState.QUEUED.value: ("queued", "Job queued…", 5),
    CollectionJobState.SEARCHING.value: ("searching", "Searching your vault…", 20),
    CollectionJobState.PROCESSING.value: ("processing", "Deduplicating and ranking…", 40),
    CollectionJobState.ANALYSING.value: ("analysing", "Extracting and analysing facts…", 60),
    CollectionJobState.SUMMARISING.value: ("summarising", "Writing the grounded summary…", 80),
    CollectionJobState.PACKAGING.value: ("packaging", "Packaging the deliverable…", 90),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_owned_folder(
    db: AsyncSession, request_id: UUID, user: User
) -> SmartFolder:
    result = await db.execute(
        select(SmartFolder).where(
            SmartFolder.id == request_id,
            SmartFolder.user_id == user.id,
        )
    )
    folder = result.scalar_one_or_none()
    if folder is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection request not found",
        )
    return folder


async def _get_session(
    db: AsyncSession, request_id: UUID
) -> ClarificationSession | None:
    result = await db.execute(
        select(ClarificationSession)
        .where(ClarificationSession.request_id == request_id)
        .order_by(ClarificationSession.created_at.desc())
    )
    return result.scalars().first()


def _clarification_payload(session: ClarificationSession) -> ClarificationPayload:
    rounds = session.rounds or []
    current = rounds[-1] if rounds else {}
    return ClarificationPayload(
        questions=current.get("questions") or [],
        round=current.get("round", len(rounds) or 1),
        max_rounds=conversation_manager.max_rounds,
        extracted=session.extracted_entities or [],
        intent=session.extracted_intent,
    )


def _confirmation_payload(session: ClarificationSession) -> dict[str, Any]:
    return {
        "params": conversation_manager.build_confirmed_params(session),
        "assumptions": session.assumptions or [],
        "analysis_types": session.analysis_types or [],
    }


async def _latest_deliverable(
    db: AsyncSession, request_id: UUID
) -> Deliverable | None:
    result = await db.execute(
        select(Deliverable)
        .where(Deliverable.request_id == request_id)
        .order_by(Deliverable.version.desc())
    )
    return result.scalars().first()


async def _items_with_annotations(
    db: AsyncSession, request_id: UUID, include_gated: bool = False
) -> list[dict[str, Any]]:
    """SourceItem dicts with annotation/tags attached; duplicates grouped
    under their canonical item as related_items.

    Items below the absolute relevance gate (status="gated_below_threshold")
    are excluded unless include_gated=True — they are retrieval noise, not
    results (spec Scenario 4 doctrine).
    """
    items_result = await db.execute(
        select(SourceItem).where(SourceItem.request_id == request_id)
    )
    rows = list(items_result.scalars().all())
    if not include_gated:
        rows = [r for r in rows if r.status != "gated_below_threshold"]
    if not rows:
        return []
    ann_result = await db.execute(
        select(Annotation).where(Annotation.item_id.in_([r.id for r in rows]))
    )
    annotations = ann_result.scalars().all()
    ann_by_item: dict[Any, list[Annotation]] = {}
    for ann in annotations:
        ann_by_item.setdefault(ann.item_id, []).append(ann)

    def _to_dict(row: SourceItem) -> dict[str, Any]:
        anns = ann_by_item.get(row.id) or []
        first = anns[0] if anns else None
        return {
            "id": row.id,
            "document_id": row.document_id,
            "title": row.title,
            "annotation": first.annotation_text if first else None,
            "category_tags": (first.category_tags if first else None) or [],
            "item_date": row.item_date,
            "source": row.source,
            "author": row.author,
            "snippet": row.snippet,
            "rank_position": row.rank_position,
            "relevance_score": row.relevance_score,
            "status": row.status,
            "page_number": None,
            "canonical_id": row.canonical_id,
            "related_items": [],
        }

    by_id = {row.id: _to_dict(row) for row in rows}
    canonical: list[dict[str, Any]] = []
    for row in rows:
        entry = by_id[row.id]
        if row.canonical_id and row.canonical_id in by_id:
            by_id[row.canonical_id]["related_items"].append({
                "id": row.id,
                "document_id": row.document_id,
                "title": row.title,
            })
        else:
            canonical.append(entry)
    return canonical


async def _analyses_for_request(
    db: AsyncSession, request_id: UUID
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(AnalysisResult)
        .join(FactSet, AnalysisResult.factset_id == FactSet.id)
        .where(FactSet.request_id == request_id)
    )
    return [
        {
            "analysis_type": row.analysis_type,
            "output": row.output,
            "provenance": row.provenance,
        }
        for row in result.scalars().all()
    ]


# ---------------------------------------------------------------------------
# POST /collection-requests — create + start clarification (FR1.1)
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=None)
async def create_collection_request(
    body: CollectionRequestCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Create a collection request and start the clarification session.

    FR6.7 idempotency: a repeated (user, idempotency_key) returns the
    existing request (200) instead of creating a duplicate.
    """
    if body.idempotency_key:
        existing_result = await db.execute(
            select(SmartFolder).where(
                SmartFolder.user_id == current_user.id,
                SmartFolder.idempotency_key == body.idempotency_key,
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            session = await _get_session(db, existing.id)
            payload = (
                _clarification_payload(session)
                if session is not None
                else ClarificationPayload(max_rounds=conversation_manager.max_rounds)
            )
            response.status_code = status.HTTP_200_OK
            return CollectionRequestCreated(request_id=existing.id, clarification=payload)

    folder = SmartFolder(
        id=uuid.uuid4(),  # explicit so the id is known pre-commit
        user_id=current_user.id,
        name=body.query[:80],
        query_text=body.query,
        status=SmartFolderStatus.DRAFT.value,
        job_state=CollectionJobState.CLARIFYING.value,
        idempotency_key=body.idempotency_key,
    )
    db.add(folder)
    await db.flush()

    session = await conversation_manager.start_session(folder, current_user, db)
    await audit_logger.log_event(
        db,
        request_id=folder.id,
        user_id=current_user.id,
        stage="clarify",
        action="request_created",
        detail={"query": body.query[:500], "idempotency_key": body.idempotency_key},
    )
    await db.commit()

    return CollectionRequestCreated(
        request_id=folder.id,
        clarification=_clarification_payload(session),
    )


# ---------------------------------------------------------------------------
# GET /collection-requests/metrics/overview — FR8.2/FR8.3 (admin/superuser)
# Declared BEFORE any /{request_id} route: a path-param route declared first
# would match "metrics" and fail UUID validation with a 422.
# ---------------------------------------------------------------------------

@router.get("/metrics/overview", response_model=None)
async def get_collection_metrics_overview(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(require_superuser_or_admin),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """FR8.2 operational metrics + FR8.3 active alerts (admin/superuser only).

    Every active alert is logged at WARNING level — that log line is the
    hook point for the existing monitoring (guardian-hc scrapes logs).
    """
    metrics = await compute_metrics(db, since_days=days)
    alerts = evaluate_alerts(metrics)
    for alert in alerts:
        logger.warning(
            "collection-metrics alert kind=%s severity=%s value=%s threshold=%s: %s",
            alert["kind"], alert["severity"], alert["value"],
            alert["threshold"], alert["message"],
        )
    return {"metrics": metrics, "alerts": alerts, "alert_count": len(alerts)}


# ---------------------------------------------------------------------------
# POST /{id}/clarify — answer a round (or skip)
# ---------------------------------------------------------------------------

@router.post("/{request_id}/clarify", response_model=None)
async def answer_clarification(
    request_id: UUID,
    body: ClarificationAnswer,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    folder = await _get_owned_folder(db, request_id, current_user)
    if folder.job_state not in (
        CollectionJobState.CLARIFYING.value,
        CollectionJobState.DRAFT.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Clarification is no longer open for this request",
        )
    session = await _get_session(db, request_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clarification session not found",
        )

    result = await conversation_manager.process_answer(
        session, body.answers, body.skip, current_user, db
    )
    await db.commit()

    if result.get("complete"):
        return ClarificationStepResponse(
            ready_to_confirm=True,
            confirmation=_confirmation_payload(session),
            round=len(session.rounds or []) or 1,
            max_rounds=conversation_manager.max_rounds,
        )
    return ClarificationStepResponse(
        ready_to_confirm=False,
        questions=result.get("questions") or [],
        round=len(session.rounds or []) or 1,
        max_rounds=conversation_manager.max_rounds,
    )


# ---------------------------------------------------------------------------
# POST /{id}/confirm — freeze params + enqueue the job
# ---------------------------------------------------------------------------

@router.post("/{request_id}/confirm", status_code=status.HTTP_202_ACCEPTED, response_model=None)
async def confirm_collection_request(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    from app.tasks.collection_request_tasks import run_collection_request_task

    folder = await _get_owned_folder(db, request_id, current_user)
    if folder.job_state == CollectionJobState.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request has been cancelled",
        )
    if folder.confirmed_params is not None:
        # Confirmed params are immutable once written.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Parameters already confirmed for this request",
        )
    session = await _get_session(db, request_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clarification session not found",
        )

    params = await conversation_manager.confirm(session, current_user, db)
    folder.confirmed_params = params
    folder.job_state = CollectionJobState.QUEUED.value

    try:
        task = run_collection_request_task.delay(str(folder.id), str(current_user.id))
    except Exception as exc:
        logger.error("Failed to queue collection request %s: %s", request_id, exc, exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to queue collection job.",
        )

    folder.celery_task_id = task.id
    await db.commit()
    return ConfirmEnqueueResponse(request_id=folder.id, task_id=task.id)


# ---------------------------------------------------------------------------
# POST /{id}/cancel — §2.4 cooperative cancellation (owner only)
# ---------------------------------------------------------------------------

def _revoke_task(task_id: str) -> None:
    """Best-effort Celery revoke; never blocks the cancel itself."""
    try:
        from app.celery_app import celery_app

        celery_app.control.revoke(task_id, terminate=True)
    except Exception as exc:
        logger.warning("Celery revoke failed for task %s: %s", task_id, exc)


@router.post("/{request_id}/cancel", response_model=None)
async def cancel_collection_request(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Cancel a collection request.

    Active jobs: job_state → "cancelled" (terminal) and the Celery task is
    revoked; the pipeline additionally re-reads job_state at every stage
    boundary and aborts cleanly (cooperative cancel). Cancel during
    clarification simply marks the request cancelled.
    """
    folder = await _get_owned_folder(db, request_id, current_user)
    if folder.job_state in (
        CollectionJobState.COMPLETED.value,
        CollectionJobState.FAILED.value,
        CollectionJobState.CANCELLED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is already {folder.job_state}",
        )
    previous_state = folder.job_state
    task_id = folder.celery_task_id
    folder.job_state = CollectionJobState.CANCELLED.value
    if task_id:
        _revoke_task(task_id)
    await audit_logger.log_event(
        db,
        request_id=folder.id,
        user_id=current_user.id,
        stage="cancel",
        action="job_cancelled",
        detail={"previous_state": previous_state, "task_revoked": bool(task_id)},
    )
    await db.commit()
    return {"request_id": str(folder.id), "job_state": folder.job_state}


# ---------------------------------------------------------------------------
# GET /{id}/status
# ---------------------------------------------------------------------------

@router.get("/{request_id}/status", response_model=None)
async def get_collection_request_status(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    folder = await _get_owned_folder(db, request_id, current_user)
    deliverable = None
    if folder.job_state == CollectionJobState.COMPLETED.value:
        deliverable = await _latest_deliverable(db, request_id)
    return CollectionJobStatusResponse(
        request_id=folder.id,
        job_state=folder.job_state,
        checkpoint=folder.checkpoint,
        error_message=folder.error_message,
        deliverable_id=deliverable.id if deliverable else None,
    )


# ---------------------------------------------------------------------------
# GET /{id}/stream — SSE over the SmartFolder job_state (source of truth)
# ---------------------------------------------------------------------------

@router.get("/{request_id}/stream", response_model=None)
async def stream_collection_request(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    folder = await _get_owned_folder(db, request_id, current_user)
    user_id = current_user.id

    async def event_generator():
        last_state: str | None = None
        for _ in range(SSE_MAX_POLLS):
            result = await db.execute(
                select(SmartFolder)
                .where(SmartFolder.id == request_id, SmartFolder.user_id == user_id)
                .execution_options(populate_existing=True)
            )
            sf = result.scalar_one_or_none()
            if sf is None:
                yield f'event: error\ndata: {json.dumps({"error": "Collection request not found"})}\n\n'
                return

            state = sf.job_state
            if state != last_state:
                last_state = state
                if state in STATE_STEPS:
                    step, message, pct = STATE_STEPS[state]
                    yield (
                        "event: step\n"
                        f'data: {json.dumps({"step": step, "message": message, "progress_percent": pct})}\n\n'
                    )

            if state == CollectionJobState.COMPLETED.value:
                deliverable = await _latest_deliverable(db, request_id)
                payload = json.dumps({
                    "request_id": str(request_id),
                    "deliverable_id": str(deliverable.id) if deliverable else None,
                })
                yield f"event: complete\ndata: {payload}\n\n"
                return

            if state in (
                CollectionJobState.FAILED.value,
                CollectionJobState.CANCELLED.value,
            ):
                payload = json.dumps({"error": sf.error_message or f"Job {state}"})
                yield f"event: error\ndata: {payload}\n\n"
                return

            await asyncio.sleep(SSE_POLL_INTERVAL)

        payload = json.dumps({
            "step": "timeout",
            "message": "Still processing — poll GET /collection-requests/"
                       f"{request_id}/status for progress.",
        })
        yield f"event: step\ndata: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# GET /{id}/items — FR5.4 annotated list with filtering / sorting / paging
# ---------------------------------------------------------------------------

@router.get("/{request_id}/items", response_model=None)
async def list_collection_items(
    request_id: UUID,
    tag: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    sort: str = Query("rank", pattern="^(rank|date)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_gated: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await _get_owned_folder(db, request_id, current_user)
    items = await _items_with_annotations(db, request_id, include_gated=include_gated)

    if tag:
        items = [it for it in items if tag in (it.get("category_tags") or [])]
    if date_from:
        items = [
            it for it in items
            if it.get("item_date") is not None and it["item_date"] >= date_from
        ]
    if date_to:
        items = [
            it for it in items
            if it.get("item_date") is not None and it["item_date"] <= date_to
        ]

    reverse = order == "desc"
    if sort == "rank":
        items.sort(
            key=lambda it: (it.get("rank_position") is None, it.get("rank_position") or 0),
            reverse=reverse,
        )
    else:
        items.sort(
            key=lambda it: (it.get("item_date") is None, it.get("item_date") or datetime.min),
            reverse=reverse,
        )

    total = len(items)
    window = items[(page - 1) * page_size : page * page_size]
    return {
        "items": [packaging_service._item_view(it) for it in window],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# GET /{id}/deliverable — in-app view JSON (FR5.1)
# ---------------------------------------------------------------------------

@router.get("/{request_id}/deliverable", response_model=None)
async def get_collection_deliverable(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await _get_owned_folder(db, request_id, current_user)
    deliverable = await _latest_deliverable(db, request_id)
    if deliverable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deliverable not found",
        )
    items = await _items_with_annotations(db, request_id)
    analyses = await _analyses_for_request(db, request_id)
    return packaging_service.build_in_app_view(deliverable, items, analyses)


# ---------------------------------------------------------------------------
# GET /{id}/deliverable/export — PDF (FR5.6) or Word (FR5.2) export
# ---------------------------------------------------------------------------

@router.get("/{request_id}/deliverable/export", response_model=None)
async def export_collection_deliverable(
    request_id: UUID,
    format: str = Query("pdf", pattern="^(pdf|docx)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await _get_owned_folder(db, request_id, current_user)
    deliverable = await _latest_deliverable(db, request_id)
    if deliverable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deliverable not found",
        )
    items = await _items_with_annotations(db, request_id)
    analyses = await _analyses_for_request(db, request_id)
    view = packaging_service.build_in_app_view(deliverable, items, analyses)

    if format == "docx":
        payload = packaging_service.export_docx(deliverable, view)
        media_type = (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        )
    else:
        payload = packaging_service.export_pdf(deliverable, view)
        media_type = "application/pdf"

    await audit_logger.log_event(
        db,
        request_id=request_id,
        user_id=current_user.id,
        stage="export",
        action=f"export_{format}",
        detail={"deliverable_id": str(deliverable.id), "item_count": len(items)},
    )
    await db.commit()

    filename = f"sowknow_collection_{request_id}.{format}"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# GET /{id}/audit — FR8.1 audit chain export (json | csv)
# ---------------------------------------------------------------------------

@router.get("/{request_id}/audit", response_model=None)
async def export_audit_chain(
    request_id: UUID,
    format: str = Query("json", pattern="^(json|csv)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """FR8.1 audit chain export (json | csv), owner-scoped.

    FR8.4 privacy: when ``COLLECTION_AUDIT_PSEUDONYMISE`` is enabled the
    ``user_id`` field of every exported event is replaced by a stable
    salted HMAC-SHA256 pseudonym (see
    ``audit_logger.pseudonymise_user_id``) — deterministic within and
    across exports, reversible only with the server secret. The export
    itself is recorded in the audit trail either way.
    """
    from app.core.config import settings

    await _get_owned_folder(db, request_id, current_user)
    result = await db.execute(
        select(CollectionAuditEvent)
        .where(CollectionAuditEvent.request_id == request_id)
        .order_by(CollectionAuditEvent.timestamp.asc())
    )
    events = list(result.scalars().all())

    await audit_logger.log_event(
        db,
        request_id=request_id,
        user_id=current_user.id,
        stage="export",
        action="audit_export",
        detail={"format": format, "event_count": len(events)},
    )
    await db.commit()

    pseudonymise = settings.COLLECTION_AUDIT_PSEUDONYMISE

    def _user_id(event: CollectionAuditEvent) -> str | None:
        raw = getattr(event, "user_id", None)
        if pseudonymise:
            return audit_logger.pseudonymise_user_id(raw)
        return str(raw) if raw is not None else None

    def _row(event: CollectionAuditEvent) -> dict[str, Any]:
        return {
            "id": str(event.id),
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            "stage": event.stage,
            "action": event.action,
            "status": event.status,
            "input_ref": event.input_ref,
            "output_ref": event.output_ref,
            "component_version": event.component_version,
            "duration_ms": event.duration_ms,
            "detail": event.detail,
            "user_id": _user_id(event),
        }

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "id", "timestamp", "stage", "action", "status",
            "input_ref", "output_ref", "component_version", "duration_ms",
            "detail", "user_id",
        ])
        for event in events:
            row = _row(event)
            writer.writerow([
                row["id"], row["timestamp"], row["stage"], row["action"],
                row["status"], row["input_ref"], row["output_ref"],
                row["component_version"], row["duration_ms"],
                json.dumps(row["detail"], default=str), row["user_id"],
            ])
        buffer.seek(0)
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="collection_audit_{request_id}.csv"'
            },
        )

    return {
        "request_id": str(request_id),
        "pseudonymised": pseudonymise,
        "events": [_row(e) for e in events],
    }


# ---------------------------------------------------------------------------
# POST /{id}/rerun — FR5.5 re-execute with fresh retrieval, new version
# ---------------------------------------------------------------------------

@router.post("/{request_id}/rerun", status_code=status.HTTP_202_ACCEPTED, response_model=None)
async def rerun_collection_request(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """FR5.5: re-run the pipeline for the same confirmed_params.

    Fresh retrieval — the checkpoint is reset, NOT reused, and the previous
    run's working artifacts (SourceItems, QueryExecutions, FactSets with
    their analyses/insights) are deleted so stage reloads never mix two
    generations. Deliverables are KEPT: the new run packages version
    max(existing)+1 (see pipeline_runner._next_deliverable_version). The
    append-only audit trail is untouched.
    """
    from sqlalchemy import delete

    from app.tasks.collection_request_tasks import run_collection_request_task

    folder = await _get_owned_folder(db, request_id, current_user)
    if folder.confirmed_params is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request has no confirmed parameters to re-run",
        )
    if folder.job_state not in (
        CollectionJobState.COMPLETED.value,
        CollectionJobState.FAILED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot re-run while job is {folder.job_state}",
        )

    existing_versions = (
        await db.execute(
            select(Deliverable.version).where(Deliverable.request_id == request_id)
        )
    ).scalars().all()

    # Drop the previous run's working set (DB-level ON DELETE CASCADE
    # removes annotations, analysis results and insights); deliverables and
    # audit events survive.
    for model in (SourceItem, QueryExecution, FactSet):
        await db.execute(delete(model).where(model.request_id == request_id))

    folder.job_state = CollectionJobState.QUEUED.value
    folder.checkpoint = None  # fresh retrieval, no resume
    folder.error_message = None

    try:
        task = run_collection_request_task.delay(str(folder.id), str(current_user.id))
    except Exception as exc:
        logger.error("Failed to queue rerun for %s: %s", request_id, exc, exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to queue collection job.",
        )

    folder.celery_task_id = task.id
    await audit_logger.log_event(
        db,
        request_id=folder.id,
        user_id=current_user.id,
        stage="package",
        action="job_rerun",
        detail={
            "previous_versions": sorted(existing_versions),
            "fresh_retrieval": True,
        },
    )
    await db.commit()
    return {
        "request_id": str(folder.id),
        "task_id": task.id,
        "previous_versions": sorted(existing_versions),
        "next_version": (max(existing_versions) + 1) if existing_versions else 1,
    }


# ---------------------------------------------------------------------------
# GET /{id}/deliverable/diff — FR5.5 per-section diff between two versions
# ---------------------------------------------------------------------------

@router.get("/{request_id}/deliverable/diff", response_model=None)
async def diff_collection_deliverables(
    request_id: UUID,
    from_version: int = Query(..., ge=1),
    to_version: int = Query(..., ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """FR5.5: per-section line diff of summary_md between two deliverable
    versions (FR4.2.2 section split) + changed disclosures."""
    await _get_owned_folder(db, request_id, current_user)
    result = await db.execute(
        select(Deliverable).where(Deliverable.request_id == request_id)
    )
    by_version = {d.version: d for d in result.scalars().all()}
    missing = [v for v in (from_version, to_version) if v not in by_version]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deliverable version(s) not found: {missing}",
        )
    diff = packaging_service.diff_deliverables(
        by_version[from_version], by_version[to_version]
    )
    return {"request_id": str(request_id), **diff}


# ---------------------------------------------------------------------------
# GET /{id}/deliverable/reproducibility — FR8.5 deterministic re-run check
# ---------------------------------------------------------------------------

@router.get("/{request_id}/deliverable/reproducibility", response_model=None)
async def check_deliverable_reproducibility(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """FR8.5: re-run the deterministic analysis over the stored FactSet and
    compare outputs exactly. ``matches`` is True/False, or None when the
    analysis code version changed since the stored run."""
    from app.services.collection_orchestrator.reproducibility import (
        compare_reproduction,
        reproduce_analysis,
    )

    folder = await _get_owned_folder(db, request_id, current_user)
    try:
        reproduction = await reproduce_analysis(db, folder.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    comparison = compare_reproduction(reproduction)
    return {"request_id": str(request_id), **comparison}
