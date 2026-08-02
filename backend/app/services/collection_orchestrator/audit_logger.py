"""Audit Logger — FR8.1 full audit chain for collection requests.

Append-only writer for ``CollectionAuditEvent`` rows (spec §2.7). Every stage
of the collection pipeline (clarify → plan → retrieve → process → extract →
analyse → summarise → validate → package → export) records structured events
so the full query→summary chain is reconstructable per request_id.

The logger never raises: audit failure must not break a user-facing job,
but it is always logged as an error.
"""

import hashlib
import hmac
import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_orchestrator import CollectionAuditEvent

logger = logging.getLogger(__name__)

# Stage enum values per spec §2.7
STAGES = (
    "clarify",
    "plan",
    "retrieve",
    "process",
    "extract",
    "analyse",
    "summarise",
    "validate",
    "package",
    "export",
    "cancel",
)

COMPONENT_VERSION = "collection-orchestrator 1.0.0"


async def log_event(
    db: AsyncSession,
    *,
    request_id: UUID,
    user_id: UUID | None,
    stage: str,
    action: str,
    status: str = "success",
    input_ref: str | None = None,
    output_ref: str | None = None,
    component_version: str = COMPONENT_VERSION,
    duration_ms: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append one audit event. Never raises (audit must not break the job)."""
    if stage not in STAGES:
        logger.warning("Unknown audit stage %r — recording anyway", stage)
    try:
        event = CollectionAuditEvent(
            request_id=request_id,
            user_id=user_id,
            stage=stage,
            action=action,
            status=status,
            input_ref=input_ref,
            output_ref=output_ref,
            component_version=component_version,
            duration_ms=duration_ms,
            detail=detail or {},
        )
        db.add(event)
        await db.flush()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Audit event write failed (request=%s stage=%s): %s", request_id, stage, exc)


@asynccontextmanager
async def audit_stage(
    db: AsyncSession,
    *,
    request_id: UUID,
    user_id: UUID | None,
    stage: str,
    action: str,
    input_ref: str | None = None,
    detail: dict[str, Any] | None = None,
):
    """Context manager: times a stage block and audits success/failure.

    Yields a ``set_output`` callable so the stage can attach output_ref and
    merge extra detail before the event is written.
    """
    started = time.perf_counter()
    output: dict[str, Any] = {"output_ref": None, "detail": dict(detail or {})}

    def set_output(output_ref: str | None = None, **extra_detail: Any) -> None:
        output["output_ref"] = output_ref
        output["detail"].update(extra_detail)

    try:
        yield set_output
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        await log_event(
            db,
            request_id=request_id,
            user_id=user_id,
            stage=stage,
            action=action,
            status="failure",
            input_ref=input_ref,
            duration_ms=elapsed,
            detail={**output["detail"], "error": str(exc)[:500]},
        )
        raise
    elapsed = int((time.perf_counter() - started) * 1000)
    await log_event(
        db,
        request_id=request_id,
        user_id=user_id,
        stage=stage,
        action=action,
        status="success",
        input_ref=input_ref,
        output_ref=output["output_ref"],
        duration_ms=elapsed,
        detail=output["detail"],
    )


# ---------------------------------------------------------------------------
# FR8.4 — retention & privacy
# ---------------------------------------------------------------------------

def pseudonymise_user_id(user_id: Any) -> str | None:
    """Stable salted pseudonym for a user id in audit exports (FR8.4).

    HMAC-SHA256 keyed with the server-side JWT_SECRET: deterministic (the
    same user always maps to the same pseudonym inside an export) but not
    reversible without the server secret. None passes through.
    """
    if user_id is None:
        return None
    from app.core.config import settings

    digest = hmac.new(
        settings.JWT_SECRET.encode("utf-8"),
        str(user_id).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"user_{digest[:32]}"


async def purge_expired_audit_events(
    db: AsyncSession, retention_days: int | None = None
) -> int:
    """FR8.4: DELETE audit events older than the retention window
    (default ``settings.COLLECTION_AUDIT_RETENTION_DAYS``, 7 years).

    Returns the number of rows deleted. This is the ONLY sanctioned
    deletion path for the append-only audit trail; the retention window is
    a compliance knob, not a cleanup shortcut.
    """
    from app.core.config import settings

    days = retention_days or settings.COLLECTION_AUDIT_RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        delete(CollectionAuditEvent).where(CollectionAuditEvent.timestamp < cutoff)
    )
    deleted = result.rowcount or 0
    if deleted:
        logger.info("Purged %d collection audit event(s) older than %d days", deleted, days)
    await db.commit()
    return deleted
