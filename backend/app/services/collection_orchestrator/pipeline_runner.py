"""Pipeline Runner — orchestrates the full collection job end to end.

Stages, in order (each wrapped in ``audit_logger.audit_stage`` and persisted
as it goes; ``SmartFolder.job_state`` + ``checkpoint`` are updated and
committed at every stage boundary so a crashed job leaves a truthful trail):

1. RETRIEVE   (searching)   plan_searches → SearchAdapter.execute_plan →
             QueryExecution + SourceItem rows. SearchUnavailableError →
             job_state="failed" (FR6.4). Partial spec failure → degraded
             disclosure (FR6.5). Zero items → completed with a zero-result
             deliverable (executed queries + relaxation suggestions, NO
             summary — FR6.1).
2. PROCESS    (processing)  dedup (canonical_id links; duplicates kept with
             status "ok"), rank (rank_position + relevance_score), annotate
             (Annotation rows).
3. EXTRACT    (analysing)   snippets are the Phase-1 content source;
             ExtractionPipeline.extract → FactSet v1. Unparseable items →
             SourceItem.status="content_unavailable" (FR6.6).
4. ANALYSE    AnalysisEngine.run over above-threshold facts → AnalysisResult
             rows + Insight rows (statements rendered from computed values,
             validation_status="validated" — they ARE the computed truths).
5. SUMMARISE  (summarising) SummaryGenerator.generate; None → no fabricated
             summary. Else GroundingValidator.validate_with_regeneration
             (max 2 attempts) + FR4.2.5 disclosure footer when sentences
             were stripped.
6. PACKAGE    (packaging)   Deliverable v1 (summary, item_list_ref, appendix,
             disclosures) → job_state="completed".

Concurrency guard: a user may have at most
``settings.COLLECTION_MAX_CONCURRENT_JOBS_PER_USER`` active jobs; beyond
that ``TooManyJobsError`` is raised (the API layer maps it to 429).

Idempotency: the API layer dedupes creation by idempotency key; the runner
itself is safe to re-enter for the same smart folder — a terminal job_state
returns the current state without redoing any work.

Phase-2 job hardening (§2.4):
- Resume from checkpoint: a FAILED job (or a crashed non-terminal one)
  re-enters at the stage AFTER ``checkpoint.last_stage`` — completed stage
  outputs (SourceItems, ranked rows, FactSet, AnalysisResults) are reloaded
  from the DB instead of being re-paid. COMPLETED/CANCELLED stay terminal.
- Cooperative cancellation: each stage boundary re-reads ``job_state``
  (``db.refresh``) and aborts cleanly when it flipped to "cancelled".
- FR6.3 analysis budget: only the top ``COLLECTION_ANALYSIS_BUDGET`` ranked
  items are annotated/extracted/analysed; the rest are kept listed with
  status "excluded_budget".
- FR6.8 partial deliverable: a summarise-stage failure (LLM outage) no
  longer fails the job — the deliverable is packaged with the annotated
  list + computed analyses and a "summary unavailable" disclosure.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_orchestrator import (
    AnalysisResult,
    Annotation,
    Deliverable,
    FactSet,
    Insight,
    QueryExecution,
    SourceItem,
)
from app.models.smart_folder import CollectionJobState, SmartFolder
from app.models.user import User
from app.services.collection_orchestrator import audit_logger
from app.services.collection_orchestrator.analysis_engine import (
    CORRELATION_LABEL,
    AnalysisEngine,
)
from app.services.collection_orchestrator.extraction_pipeline import ExtractionPipeline
from app.services.collection_orchestrator.grounding_validator import GroundingValidator
from app.services.collection_orchestrator.query_planner import plan_searches
from app.services.collection_orchestrator.result_processor import (
    RANKING_VERSION,
    ResultProcessor,
)
from app.services.collection_orchestrator.search_adapter import (
    SearchAdapter,
    SearchUnavailableError,
)
from app.services.collection_orchestrator.summary_generator import (
    SummaryGenerator,
    format_number,
)

logger = logging.getLogger(__name__)

TERMINAL_STATES = (
    CollectionJobState.COMPLETED.value,
    CollectionJobState.FAILED.value,
    CollectionJobState.CANCELLED.value,
)
ACTIVE_STATES = (
    CollectionJobState.QUEUED.value,
    CollectionJobState.SEARCHING.value,
    CollectionJobState.PROCESSING.value,
    CollectionJobState.ANALYSING.value,
    CollectionJobState.SUMMARISING.value,
    CollectionJobState.PACKAGING.value,
)

# FR6.1 relaxation suggestions for the zero-result outcome
RELAXATION_SUGGESTIONS = (
    "Widen the date range (or remove the date filter).",
    "Reduce the number of entities / filters in the request.",
    "Try alternative spellings or synonyms for key names.",
)

INSUFFICIENT_SUMMARY_NOTE = "insufficient data for summary"
# FR6.8 — summarise stage failed (LLM outage): deliverable ships partial.
SUMMARY_UNAVAILABLE_NOTE = (
    "summary unavailable — partial deliverable "
    "(annotated items and computed analyses only)"
)

# FR6.3 — items per batch when building extraction contents (keeps
# 100k-item jobs from materialising one giant dict in a single pass).
EXTRACTION_BATCH_SIZE = 500

# Conflicts are stashed on the extract checkpoint so an extract-resume can
# rebuild the full extraction dict from the FactSet without recomputing.
MAX_CHECKPOINT_CONFLICTS = 200

# Stage boundaries where a cancelled job stops (checked via db.refresh).
_RESUME_STATES = {
    "retrieve": CollectionJobState.PROCESSING.value,
    "process": CollectionJobState.ANALYSING.value,
    "extract": CollectionJobState.ANALYSING.value,
    "analyse": CollectionJobState.SUMMARISING.value,
}


class TooManyJobsError(Exception):
    """User already has COLLECTION_MAX_CONCURRENT_JOBS_PER_USER active jobs."""


async def _next_deliverable_version(db: AsyncSession, request_id: UUID) -> int:
    """FR5.5: deliverables are versioned per request — a re-run creates
    version max(existing)+1 instead of overwriting version 1."""
    result = await db.execute(
        select(func.max(Deliverable.version)).where(
            Deliverable.request_id == request_id
        )
    )
    return (result.scalar_one() or 0) + 1


def _max_concurrent_jobs() -> int:
    from app.core.config import settings

    return settings.COLLECTION_MAX_CONCURRENT_JOBS_PER_USER


def _relevance_gate() -> float:
    from app.core.config import settings

    return settings.COLLECTION_RELEVANCE_GATE


def _analysis_budget() -> int:
    from app.core.config import settings

    return settings.COLLECTION_ANALYSIS_BUDGET


def _show_trimmed_count() -> bool:
    from app.core.config import settings

    return settings.COLLECTION_SHOW_TRIMMED_COUNT


def _batched(seq: list, size: int):
    for start in range(0, len(seq), size):
        yield seq[start:start + size]


def _as_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _as_dt(value: Any) -> datetime | None:
    """Coerce datetimes that may arrive as ISO strings (FR2.9 cache replays
    JSON-round-trip datetimes to strings)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class PipelineRunner:
    """Runs the collection pipeline for one SmartFolder request."""

    def __init__(
        self,
        *,
        search_adapter: SearchAdapter | None = None,
        result_processor: ResultProcessor | None = None,
        extraction_pipeline: ExtractionPipeline | None = None,
        analysis_engine: AnalysisEngine | None = None,
        summary_generator: SummaryGenerator | None = None,
        grounding_validator: GroundingValidator | None = None,
    ):
        self.search_adapter = search_adapter or SearchAdapter()
        self.result_processor = result_processor or ResultProcessor()
        self.extraction_pipeline = extraction_pipeline or ExtractionPipeline()
        self.analysis_engine = analysis_engine or AnalysisEngine()
        self.summary_generator = summary_generator or SummaryGenerator()
        self.grounding_validator = grounding_validator or GroundingValidator()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    async def run(
        self,
        smart_folder_id: UUID,
        user_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        sf = await self._load_folder(db, smart_folder_id, user_id)
        if sf is None:
            raise ValueError(f"SmartFolder {smart_folder_id} not found for user {user_id}")

        # Idempotent re-entry: completed/cancelled jobs are never re-run.
        # A FAILED job resumes from its checkpoint (FR6.4 retry path); a
        # failed job with no usable checkpoint simply re-runs from scratch.
        if sf.job_state in (
            CollectionJobState.COMPLETED.value,
            CollectionJobState.CANCELLED.value,
        ):
            return await self._status_dict(db, sf)

        await self._enforce_concurrency_guard(db, sf, user_id)

        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            raise ValueError(f"User {user_id} not found")

        confirmed_params = dict(sf.confirmed_params or {})
        confirmed_params.setdefault("query_text", sf.query_text)

        # ── Checkpoint resume (§2.4): reload completed stage outputs ─────
        resume_point = await self._determine_resume_point(db, sf)

        items: list[dict] | None = None
        executions: list[dict] = []
        ranked: list[dict] = []
        rows_by_item: dict[int, SourceItem] = {}
        gate_info: dict[str, Any] | None = None
        extraction: dict[str, Any] | None = None
        factset: FactSet | None = None
        analyses: list[dict] = []
        insights: list[dict] = []

        if resume_point is not None:
            await self._mark_resumed(db, sf, resume_point)
            items, executions = await self._reload_items_and_executions(db, sf)
        if resume_point in ("process", "extract", "analyse"):
            ranked, rows_by_item, gate_info = await self._reload_processed(db, sf)
        if resume_point in ("extract", "analyse"):
            extraction, factset = await self._reload_extraction(db, sf)
        if resume_point == "analyse":
            analyses, insights = await self._reload_analyses(db, sf)

        # ── 1. RETRIEVE ──────────────────────────────────────────────────
        if resume_point is None:
            items, executions = await self._stage_retrieve(db, sf, user, confirmed_params)
            if items is None:  # failed / zero-result terminal paths already handled
                return await self._status_dict(db, sf)

        # ── 2. PROCESS ───────────────────────────────────────────────────
        if resume_point in (None, "retrieve"):
            if await self._cancel_requested(db, sf):
                return await self._status_dict(db, sf)
            ranked, rows_by_item, gate_info = await self._stage_process(
                db, sf, user, items, confirmed_params
            )
            if not ranked:
                # Relevance-gated to zero — terminal deliverable already written.
                return await self._status_dict(db, sf)

        # ── 3. EXTRACT ───────────────────────────────────────────────────
        if resume_point in (None, "retrieve", "process"):
            if await self._cancel_requested(db, sf):
                return await self._status_dict(db, sf)
            extraction, factset = await self._stage_extract(db, sf, ranked, rows_by_item)

        # ── 4. ANALYSE ───────────────────────────────────────────────────
        if resume_point != "analyse":
            if await self._cancel_requested(db, sf):
                return await self._status_dict(db, sf)
            analyses, insights = await self._stage_analyse(
                db, sf, extraction["facts"], confirmed_params, factset
            )

        # ── 5. SUMMARISE ─────────────────────────────────────────────────
        if await self._cancel_requested(db, sf):
            return await self._status_dict(db, sf)
        summary_unavailable = False
        try:
            final_md, removed = await self._stage_summarise(
                db, sf, user, ranked, analyses, insights, confirmed_params
            )
        except Exception as exc:
            # FR6.8: an LLM outage must not fail the whole job — package a
            # partial deliverable (annotated list + completed analyses).
            logger.error(
                "Summarise failed for %s — packaging partial deliverable: %s",
                sf.id, exc, exc_info=True,
            )
            await audit_logger.log_event(
                db,
                request_id=sf.id,
                user_id=sf.user_id,
                stage="summarise",
                action="summary_failed_partial",
                status="failure",
                detail={"error": str(exc)[:500]},
            )
            await self._set_state(
                db, sf, CollectionJobState.PACKAGING.value, "summarise",
                summary=None, note=SUMMARY_UNAVAILABLE_NOTE,
            )
            final_md, removed, summary_unavailable = None, [], True

        # ── 6. PACKAGE ───────────────────────────────────────────────────
        deliverable = await self._stage_package(
            db, sf, final_md, removed, items, executions, analyses, extraction, insights,
            gate_info=gate_info,
            summary_unavailable=summary_unavailable,
        )

        return await self._status_dict(db, sf, deliverable=deliverable)

    # ------------------------------------------------------------------
    # Loading / guards / status
    # ------------------------------------------------------------------
    async def _load_folder(
        self, db: AsyncSession, smart_folder_id: UUID, user_id: UUID
    ) -> SmartFolder | None:
        result = await db.execute(
            select(SmartFolder).where(
                SmartFolder.id == smart_folder_id,
                SmartFolder.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _enforce_concurrency_guard(
        self, db: AsyncSession, sf: SmartFolder, user_id: UUID
    ) -> None:
        result = await db.execute(
            select(func.count())
            .select_from(SmartFolder)
            .where(
                SmartFolder.user_id == user_id,
                SmartFolder.id != sf.id,
                SmartFolder.celery_task_id.isnot(None),
                SmartFolder.job_state.in_(ACTIVE_STATES),
            )
        )
        active = result.scalar_one() or 0
        if active >= _max_concurrent_jobs():
            raise TooManyJobsError(
                f"User already has {active} active collection job(s) "
                f"(max {_max_concurrent_jobs()})"
            )

    async def _status_dict(
        self, db: AsyncSession, sf: SmartFolder, deliverable: Deliverable | None = None
    ) -> dict[str, Any]:
        if deliverable is None:
            result = await db.execute(
                select(Deliverable)
                .where(Deliverable.request_id == sf.id)
                .order_by(Deliverable.version.desc())
            )
            deliverable = result.scalars().first()
        return {
            "status": sf.job_state,
            "smart_folder_id": str(sf.id),
            "job_state": sf.job_state,
            "deliverable_id": str(deliverable.id) if deliverable else None,
            "error": sf.error_message,
            "checkpoint": sf.checkpoint,
        }

    async def _set_state(
        self, db: AsyncSession, sf: SmartFolder, state: str, last_stage: str, **refs: Any
    ) -> None:
        sf.job_state = state
        sf.checkpoint = {
            "last_stage": last_stage,
            "stage_outputs_refs": refs,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.commit()

    async def _fail(self, db: AsyncSession, sf: SmartFolder, message: str) -> None:
        sf.job_state = CollectionJobState.FAILED.value
        sf.error_message = message[:2000]
        await audit_logger.log_event(
            db,
            request_id=sf.id,
            user_id=sf.user_id,
            stage="retrieve",
            action="job_failed",
            status="failure",
            detail={"error": message[:500]},
        )
        await db.commit()

    # ------------------------------------------------------------------
    # Checkpoint resume + cooperative cancellation (§2.4)
    # ------------------------------------------------------------------
    async def _determine_resume_point(self, db: AsyncSession, sf: SmartFolder) -> str | None:
        """Stage to resume FROM (its outputs are reloaded, not recomputed).

        Degrades gracefully toward a full re-run when the rows a completed
        stage should have persisted are missing (e.g. partial flush).
        """
        checkpoint = sf.checkpoint or {}
        last = checkpoint.get("last_stage")
        if last in ("analyse", "summarise"):
            result = await db.execute(
                select(func.count())
                .select_from(AnalysisResult)
                .join(FactSet, AnalysisResult.factset_id == FactSet.id)
                .where(FactSet.request_id == sf.id)
            )
            if (result.scalar_one() or 0) > 0:
                return "analyse"
            last = "extract"
        if last == "extract":
            if await self._latest_factset(db, sf) is not None:
                return "extract"
            last = "process"
        if last == "process":
            result = await db.execute(
                select(func.count())
                .select_from(SourceItem)
                .where(
                    SourceItem.request_id == sf.id,
                    SourceItem.rank_position.isnot(None),
                )
            )
            if (result.scalar_one() or 0) > 0:
                return "process"
            last = "retrieve"
        if last == "retrieve":
            result = await db.execute(
                select(func.count())
                .select_from(SourceItem)
                .where(SourceItem.request_id == sf.id)
            )
            if (result.scalar_one() or 0) > 0:
                return "retrieve"
        return None

    async def _mark_resumed(self, db: AsyncSession, sf: SmartFolder, resume_point: str) -> None:
        checkpoint = dict(sf.checkpoint or {})
        sf.job_state = _RESUME_STATES[resume_point]
        sf.error_message = None  # stale failure message from the previous run
        await audit_logger.log_event(
            db,
            request_id=sf.id,
            user_id=sf.user_id,
            stage=resume_point,
            action="job_resumed",
            detail={
                "from_stage": resume_point,
                "retry_count": checkpoint.get("retry_count", 0),
            },
        )
        await db.commit()

    async def _cancel_requested(self, db: AsyncSession, sf: SmartFolder) -> bool:
        """Cooperative cancellation: the cancel endpoint flips job_state to
        "cancelled" from its own session; re-read it at each stage boundary
        and stop cleanly when set. CANCELLED is terminal."""
        try:
            await db.refresh(sf)
        except Exception as exc:  # defensive: a refresh glitch must not kill the job
            logger.warning("Cancel check refresh failed for %s: %s", sf.id, exc)
            return False
        if sf.job_state != CollectionJobState.CANCELLED.value:
            return False
        await audit_logger.log_event(
            db,
            request_id=sf.id,
            user_id=sf.user_id,
            stage="cancel",
            action="job_cancelled",
            detail={"last_stage": (sf.checkpoint or {}).get("last_stage")},
        )
        await db.commit()
        return True

    @staticmethod
    def _row_to_item_dict(row: SourceItem) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "document_id": str(row.document_id) if row.document_id else None,
            "uri": row.uri,
            "title": row.title,
            "item_type": row.item_type,
            "source": row.source,
            "author": row.author,
            "item_date": row.item_date,
            "relevance_score": row.relevance_score,
            "snippet": row.snippet,
            "acl_stamp": row.acl_stamp,
            "content_hash": row.content_hash,
            "simhash": row.simhash,
            "rank_position": row.rank_position,
            "status": row.status or "ok",
        }

    async def _reload_items_and_executions(
        self, db: AsyncSession, sf: SmartFolder
    ) -> tuple[list[dict], list[dict]]:
        result = await db.execute(
            select(SourceItem).where(SourceItem.request_id == sf.id)
        )
        items = [self._row_to_item_dict(row) for row in result.scalars().all()]
        result = await db.execute(
            select(QueryExecution).where(QueryExecution.request_id == sf.id)
        )
        executions = []
        for execution in result.scalars().all():
            payload = dict(execution.search_call_payload or {})
            error = payload.pop("_error", None)
            executions.append({
                "search_call_payload": payload,
                "started_at": execution.started_at,
                "duration_ms": execution.duration_ms,
                "result_count": execution.result_count,
                "status": execution.status,
                "error": error,
            })
        return items, executions

    async def _reload_processed(
        self, db: AsyncSession, sf: SmartFolder
    ) -> tuple[list[dict], dict[int, SourceItem], dict[str, Any]]:
        """Reload the ranked set persisted by the process stage: rows with a
        rank_position, excluding gated / budget-excluded items."""
        result = await db.execute(
            select(SourceItem)
            .where(
                SourceItem.request_id == sf.id,
                SourceItem.rank_position.isnot(None),
                SourceItem.status.notin_(("gated_below_threshold", "excluded_budget")),
            )
            .order_by(SourceItem.rank_position)
        )
        rows = list(result.scalars().all())
        ranked: list[dict] = []
        rows_by_item: dict[int, SourceItem] = {}
        for row in rows:
            item = self._row_to_item_dict(row)
            item["ranking_detail"] = {"final_score": row.relevance_score or 0.0}
            ranked.append(item)
            rows_by_item[id(item)] = row
        refs = (sf.checkpoint or {}).get("stage_outputs_refs") or {}
        gate_info = refs.get("relevance_gate") or {
            "threshold": _relevance_gate(),
            "items_kept": len(ranked),
            "items_gated": 0,
        }
        return ranked, rows_by_item, gate_info

    async def _latest_factset(self, db: AsyncSession, sf: SmartFolder) -> FactSet | None:
        result = await db.execute(
            select(FactSet)
            .where(FactSet.request_id == sf.id)
            .order_by(FactSet.version.desc())
        )
        return result.scalars().first()

    async def _reload_extraction(
        self, db: AsyncSession, sf: SmartFolder
    ) -> tuple[dict[str, Any], FactSet]:
        """Rebuild the extraction dict from the persisted FactSet; conflicts
        ride on the extract checkpoint (they are not part of the FactSet)."""
        factset = await self._latest_factset(db, sf)
        threshold = self.extraction_pipeline.confidence_threshold
        all_facts = list(factset.facts or [])
        facts = [f for f in all_facts if (f.get("confidence") or 0) >= threshold]
        low_confidence = [f for f in all_facts if (f.get("confidence") or 0) < threshold]
        refs = (sf.checkpoint or {}).get("stage_outputs_refs") or {}
        extraction = {
            "facts": facts,
            "low_confidence": low_confidence,
            "unparseable": [],
            "normalization_notes": list(factset.normalization_notes or []),
            "conflicts": list(refs.get("conflicts") or []),
        }
        return extraction, factset

    async def _reload_analyses(
        self, db: AsyncSession, sf: SmartFolder
    ) -> tuple[list[dict], list[dict]]:
        """Reload persisted AnalysisResult rows; insight dicts are re-rendered
        deterministically from the outputs (Insight rows already exist)."""
        result = await db.execute(
            select(AnalysisResult)
            .join(FactSet, AnalysisResult.factset_id == FactSet.id)
            .where(FactSet.request_id == sf.id)
        )
        analyses = [
            {
                "analysis_type": row.analysis_type,
                "inputs": row.inputs,
                "output": row.output,
                "thresholds_used": row.thresholds_used,
                "provenance": row.provenance or [],
                "code_version": row.code_version,
            }
            for row in result.scalars().all()
        ]
        insights: list[dict] = []
        for analysis in analyses:
            for insight in self._insights_for_analysis(analysis):
                insight["_analysis_type"] = analysis.get("analysis_type")
                insights.append(insight)
        return analyses, insights

    # ------------------------------------------------------------------
    # Stage 1 — RETRIEVE
    # ------------------------------------------------------------------
    async def _stage_retrieve(
        self,
        db: AsyncSession,
        sf: SmartFolder,
        user: User,
        confirmed_params: dict[str, Any],
    ) -> tuple[list[dict] | None, list[dict]]:
        """Returns (items, executions); items=None means a terminal path ran."""
        sf.job_state = CollectionJobState.SEARCHING.value
        await db.commit()

        specs = plan_searches(confirmed_params)
        try:
            async with audit_logger.audit_stage(
                db,
                request_id=sf.id,
                user_id=user.id,
                stage="retrieve",
                action="execute_search_plan",
                detail={"spec_count": len(specs)},
            ) as set_output:
                if not specs:
                    items, executions = [], []
                else:
                    items, executions = await self.search_adapter.execute_plan(
                        specs, user, db, request_id=sf.id
                    )
                set_output(item_count=len(items), execution_count=len(executions))
        except SearchUnavailableError as exc:
            await self._fail(db, sf, str(exc))
            return None, []

        # Persist QueryExecution rows (error is folded into the payload —
        # the model has no dedicated error column).
        for execution in executions:
            payload = dict(execution.get("search_call_payload") or {})
            if execution.get("error"):
                payload["_error"] = str(execution["error"])[:500]
            db.add(QueryExecution(
                request_id=sf.id,
                search_call_payload=payload,
                started_at=_as_dt(execution.get("started_at")),
                duration_ms=execution.get("duration_ms"),
                result_count=execution.get("result_count"),
                status=execution.get("status"),
            ))
        await db.flush()

        # Persist SourceItem rows.
        for item in items:
            db.add(self._source_item_row(sf.id, item))
        await db.flush()

        failed_specs = [e for e in executions if e.get("status") == "failed"]
        refs: dict[str, Any] = {
            "query_executions": len(executions),
            "source_items": len(items),
        }
        if failed_specs:
            # FR6.5 degraded-mode disclosure lives on the checkpoint and is
            # re-attached to the deliverable at packaging time.
            refs["degraded_sources"] = [
                {
                    "payload": e.get("search_call_payload"),
                    "error": str(e.get("error"))[:300],
                }
                for e in failed_specs
            ]
        await self._set_state(
            db, sf, CollectionJobState.PROCESSING.value, "retrieve", **refs
        )

        if not items:
            await self._zero_result_deliverable(db, sf, executions)
            return None, executions
        return items, executions

    @staticmethod
    def _source_item_row(request_id: UUID, item: dict[str, Any]) -> SourceItem:
        return SourceItem(
            request_id=request_id,
            execution_id=None,  # items are not spec-linked in Phase 1
            document_id=_as_uuid(item.get("document_id")),
            uri=item.get("uri"),
            title=item.get("title"),
            item_type=item.get("item_type"),
            source=item.get("source"),
            author=item.get("author"),
            item_date=_as_dt(item.get("item_date")),
            relevance_score=item.get("relevance_score"),
            snippet=item.get("snippet"),
            acl_stamp=item.get("acl_stamp"),
            content_hash=item.get("content_hash"),
            simhash=item.get("simhash"),
            rank_position=item.get("rank_position"),
            status=item.get("status") or "ok",
        )

    async def _zero_result_deliverable(
        self,
        db: AsyncSession,
        sf: SmartFolder,
        executions: list[dict],
        extra_disclosures: list[dict] | None = None,
    ) -> None:
        """FR6.1: zero results → deliverable with executed queries +
        relaxation suggestions; NO summary is fabricated."""
        async with audit_logger.audit_stage(
            db,
            request_id=sf.id,
            user_id=sf.user_id,
            stage="package",
            action="zero_result_deliverable",
            detail={"executed_queries": len(executions)},
        ):
            deliverable = Deliverable(
                request_id=sf.id,
                version=await _next_deliverable_version(db, sf.id),
                summary_md=None,
                item_list_ref=f"api://collection-requests/{sf.id}/items",
                appendix={
                    "outcome": "zero_results",
                    "executed_queries": [
                        e.get("search_call_payload") for e in executions
                    ],
                    "relaxation_suggestions": list(RELAXATION_SUGGESTIONS),
                },
                disclosures=[{
                    "type": "zero_results",
                    "message": (
                        "No items matched the confirmed parameters. "
                        "No summary was generated."
                    ),
                    "relaxation_suggestions": list(RELAXATION_SUGGESTIONS),
                }] + list(extra_disclosures or []),
            )
            db.add(deliverable)
            await db.flush()
        sf.job_state = CollectionJobState.COMPLETED.value
        sf.checkpoint = {
            "last_stage": "package",
            "stage_outputs_refs": {
                "deliverable_id": str(deliverable.id),
                "outcome": "zero_results",
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.commit()

    # ------------------------------------------------------------------
    # Stage 2 — PROCESS (dedup / rank / annotate)
    # ------------------------------------------------------------------
    async def _stage_process(
        self,
        db: AsyncSession,
        sf: SmartFolder,
        user: User,
        items: list[dict],
        confirmed_params: dict[str, Any],
    ) -> tuple[list[dict], dict[int, SourceItem], dict[str, Any]]:
        gate_info: dict[str, Any] = {
            "threshold": _relevance_gate(),
            "items_kept": 0,
            "items_gated": 0,
        }
        gated_out: list[dict] = []
        async with audit_logger.audit_stage(
            db,
            request_id=sf.id,
            user_id=user.id,
            stage="process",
            action="dedup_rank_annotate",
            input_ref=f"items:{len(items)}",
        ) as set_output:
            canonical_items, duplicates_map = self.result_processor.dedup(items)
            # Rerank against the FOCUSED search query (not the raw request
            # sentence) so the cross-encoder compares the item to the real
            # topic, not filler words (2026-08-04).
            rerank_query = str(
                confirmed_params.get("search_query")
                or confirmed_params.get("query_text")
                or ""
            )
            ranked_all = await self.result_processor.rank(
                canonical_items,
                rerank_query,
                db=db,
                request_id=sf.id,
                user_id=user.id,
            )
            # Absolute relevance gate (search doctrine: never trust raw vector
            # top-N without a gate; marginal semantic matches are not results
            # — spec Scenario 4). Gated items stay persisted with a distinct
            # status but are excluded from annotation/extraction/analysis.
            gate = gate_info["threshold"]
            ranked: list[dict] = []
            for it in ranked_all:
                # Gate on the cross-encoder rerank confidence (_gate_score),
                # not the blended final score — the blend compressed every
                # match to ~0.5-0.6 and let unrelated docs through (2026-08-04).
                score = it.get("_gate_score", (it.get("ranking_detail") or {}).get("final_score", 0.0))
                (ranked if score >= gate else gated_out).append(it)
            gate_info["items_kept"] = len(ranked)
            gate_info["items_gated"] = len(gated_out)
            gate_scores = [it.get("_gate_score", 0.0) for it in ranked_all]
            gate_info["gate_score_min"] = round(min(gate_scores), 3) if gate_scores else None
            gate_info["gate_score_max"] = round(max(gate_scores), 3) if gate_scores else None
            gate_info["gate_score_median"] = (
                round(sorted(gate_scores)[len(gate_scores) // 2], 3) if gate_scores else None
            )
            # FR6.3 analysis budget: only the top-N by rank_position are
            # annotated/extracted/analysed; the rest stay listed with
            # status "excluded_budget" (NFR-3 bound on huge jobs).
            budget = _analysis_budget()
            budget_excluded: list[dict] = []
            if len(ranked) > budget:
                budget_excluded = ranked[budget:]
                ranked = ranked[:budget]
            gate_info["analysis_budget"] = budget
            gate_info["items_processed"] = len(ranked)
            gate_info["items_excluded_budget"] = len(budget_excluded)
            annotations = (
                await self.result_processor.annotate(ranked, confirmed_params, user)
                if ranked
                else []
            )
            set_output(
                canonical_count=len(canonical_items),
                duplicate_count=sum(len(v) for v in duplicates_map.values()),
                relevance_gate=gate_info,
            )

        # Reload the rows persisted in stage 1 and align them with the item
        # dicts (dedup/rank/annotate mutate the same dict objects).
        result = await db.execute(
            select(SourceItem).where(SourceItem.request_id == sf.id)
        )
        rows = list(result.scalars().all())
        rows_by_key = {
            (r.document_id and str(r.document_id), r.snippet): r for r in rows
        }
        rows_by_item: dict[int, SourceItem] = {}
        used: set[int] = set()
        for item in items:
            key = (item.get("document_id") and str(item["document_id"]), item.get("snippet"))
            row = rows_by_key.get(key)
            if row is None or id(row) in used:
                # Fallback: match on content hash (set by dedup).
                row = next(
                    (r for r in rows
                     if id(r) not in used and r.content_hash == item.get("content_hash")),
                    None,
                )
            if row is not None:
                used.add(id(row))
                rows_by_item[id(item)] = row

        # Dedup persistence: hashes + canonical links (duplicates kept, FR3.3).
        for item in items:
            row = rows_by_item.get(id(item))
            if row is None:
                continue
            row.content_hash = item.get("content_hash")
            row.simhash = item.get("simhash")
        gated_ids = {id(it) for it in gated_out}
        for item in items:
            if id(item) in gated_ids:
                row = rows_by_item.get(id(item))
                if row is not None:
                    row.status = "gated_below_threshold"
        budget_excluded_ids = {id(it) for it in budget_excluded}
        for item in items:
            if id(item) in budget_excluded_ids:
                row = rows_by_item.get(id(item))
                if row is not None:
                    row.status = "excluded_budget"
        for canonical_hash, dups in duplicates_map.items():
            canonical_row = next(
                (rows_by_item[id(it)] for it in canonical_items
                 if it.get("content_hash") == canonical_hash and id(it) in rows_by_item),
                None,
            )
            for dup in dups:
                dup_row = rows_by_item.get(id(dup))
                if dup_row is not None and canonical_row is not None:
                    dup_row.canonical_id = canonical_row.id

        # Ranking persistence.
        for item in ranked:
            row = rows_by_item.get(id(item))
            if row is not None:
                row.rank_position = item.get("rank_position")
                detail = item.get("ranking_detail") or {}
                row.relevance_score = (
                    item.get("_gate_score")
                    or detail.get("final_score", row.relevance_score)
                )

        # Annotation persistence.
        for annotation in annotations:
            item = ranked[annotation["item_index"]]
            row = rows_by_item.get(id(item))
            if row is None:
                continue
            db.add(Annotation(
                item_id=row.id,
                annotation_text=annotation.get("annotation_text"),
                evidence_offsets=annotation.get("evidence_offsets") or [],
                category_tags=annotation.get("category_tags") or [],
                rank_position=annotation.get("rank_position"),
            ))
        await db.flush()

        if not ranked:
            # Everything retrieved was gated out → honest zero-result outcome
            # (spec Scenario 4); no annotation/extraction/summary over noise.
            await self._zero_result_deliverable(
                db,
                sf,
                [],
                extra_disclosures=[{
                    "type": "relevance_gate",
                    **gate_info,
                    "message": (
                        f"{gate_info['items_gated']} candidate(s) were retrieved "
                        f"but none passed the absolute relevance gate "
                        f"({gate_info['threshold']}). No summary was generated."
                    ),
                }],
            )
            return [], rows_by_item, gate_info

        await self._set_state(
            db,
            sf,
            CollectionJobState.ANALYSING.value,
            "process",
            canonical_items=len(ranked),
            duplicates=sum(len(v) for v in duplicates_map.values()),
            ranking_version=RANKING_VERSION,
            relevance_gate=gate_info,
        )
        return ranked, rows_by_item, gate_info

    # ------------------------------------------------------------------
    # Stage 3 — EXTRACT
    # ------------------------------------------------------------------
    async def _stage_extract(
        self,
        db: AsyncSession,
        sf: SmartFolder,
        ranked: list[dict],
        rows_by_item: dict[int, SourceItem],
    ) -> tuple[dict[str, Any], FactSet]:
        # Phase 1: the item snippet IS the content.
        for item in ranked:
            row = rows_by_item.get(id(item))
            if row is not None:
                item["id"] = str(row.id)
        # FR6.3/NFR-3: build the contents map in batches so very large jobs
        # never materialise it in a single pass.
        contents: dict[str, str] = {}
        for batch in _batched(ranked, EXTRACTION_BATCH_SIZE):
            contents.update({
                item["id"]: item.get("snippet") or ""
                for item in batch
                if item.get("id")
            })

        async with audit_logger.audit_stage(
            db,
            request_id=sf.id,
            user_id=sf.user_id,
            stage="extract",
            action="extract_facts",
            input_ref=f"items:{len(contents)}",
        ) as set_output:
            extraction = self.extraction_pipeline.extract(ranked, contents)
            set_output(
                fact_count=len(extraction["facts"]),
                low_confidence_count=len(extraction["low_confidence"]),
                unparseable_count=len(extraction["unparseable"]),
                conflict_count=len(extraction["conflicts"]),
            )

        # FR6.6: unparseable items are disclosed, never silently dropped.
        for item in ranked:
            if item.get("id") in {str(u) for u in extraction["unparseable"]}:
                row = rows_by_item.get(id(item))
                if row is not None:
                    row.status = "content_unavailable"

        factset = FactSet(
            request_id=sf.id,
            version=1,
            facts=extraction["facts"] + extraction["low_confidence"],
            normalization_notes=extraction["normalization_notes"],
        )
        db.add(factset)
        await db.flush()

        await self._set_state(
            db,
            sf,
            CollectionJobState.ANALYSING.value,
            "extract",
            factset_id=str(factset.id),
            fact_count=len(extraction["facts"]),
            # Conflicts ride on the checkpoint so an extract-resume can
            # rebuild the extraction dict without recomputing (§2.4).
            conflicts=extraction["conflicts"][:MAX_CHECKPOINT_CONFLICTS],
        )
        return extraction, factset

    # ------------------------------------------------------------------
    # Stage 4 — ANALYSE
    # ------------------------------------------------------------------
    async def _stage_analyse(
        self,
        db: AsyncSession,
        sf: SmartFolder,
        facts: list[dict],
        confirmed_params: dict[str, Any],
        factset: FactSet,
    ) -> tuple[list[dict], list[dict]]:
        analysis_types = list(confirmed_params.get("analysis_types") or ["descriptive"])

        async with audit_logger.audit_stage(
            db,
            request_id=sf.id,
            user_id=sf.user_id,
            stage="analyse",
            action="run_analyses",
            input_ref=f"factset:{factset.id}",
            detail={"analysis_types": analysis_types, "fact_count": len(facts)},
        ) as set_output:
            analyses = self.analysis_engine.run(facts, analysis_types)
            insights = self._build_insights(analyses)
            set_output(analysis_count=len(analyses), insight_count=len(insights))

        analysis_rows: list[AnalysisResult] = []
        for analysis in analyses:
            row = AnalysisResult(
                factset_id=factset.id,
                analysis_type=analysis.get("analysis_type"),
                inputs=analysis.get("inputs"),
                output=analysis.get("output"),
                thresholds_used=analysis.get("thresholds_used"),
                provenance=analysis.get("provenance") or [],
                code_version=analysis.get("code_version"),
            )
            db.add(row)
            analysis_rows.append(row)
        await db.flush()

        # Insights are derived from computed outputs — they ARE the computed
        # truths, so they are persisted as validated.
        insight_index = 0
        for analysis, row in zip(analyses, analysis_rows):
            for insight in self._insights_for_analysis(analysis):
                db.add(Insight(
                    analysis_id=row.id,
                    statement=insight["statement"],
                    source_refs=insight.get("source_refs") or [],
                    validation_status="validated",
                ))
                insights[insight_index]["_analysis_type"] = analysis.get("analysis_type")
                insight_index += 1
        await db.flush()

        await self._set_state(
            db,
            sf,
            CollectionJobState.SUMMARISING.value,
            "analyse",
            analysis_results=len(analysis_rows),
            insights=len(insights),
        )
        return analyses, insights

    def _build_insights(self, analyses: list[dict]) -> list[dict]:
        insights: list[dict] = []
        for analysis in analyses:
            insights.extend(self._insights_for_analysis(analysis))
        return insights

    @staticmethod
    def _unit_suffix(unit: str | None) -> str:
        return f" {unit}" if unit and unit != "%" else ""

    @staticmethod
    def _insights_for_analysis(analysis: dict) -> list[dict]:
        """Render insight statements from computed values (format_number)."""
        insights: list[dict] = []
        output = analysis.get("output") or {}
        analysis_type = analysis.get("analysis_type")
        if analysis_type == "descriptive":
            for metric in output.get("metrics") or []:
                unit = metric.get("unit")
                refs = [
                    ref
                    for value in metric.get("values") or []
                    for ref in value.get("source_refs") or []
                ]
                label = metric.get("metric")
                detail = (
                    f"total {format_number(metric.get('total'), unit)}"
                    f"{PipelineRunner._unit_suffix(unit)} across "
                    f"{metric.get('count')} values "
                    f"(min {format_number(metric.get('min'), unit)}, "
                    f"max {format_number(metric.get('max'), unit)})"
                )
                # A metric literally named "total" must not read
                # "total: total …".
                statement = (
                    detail if str(label or "").lower() == "total"
                    else f"{label}: {detail}"
                )
                insights.append({
                    "statement": statement,
                    "source_refs": refs,
                    "validation_status": "validated",
                })
        elif analysis_type == "trend":
            for trend in output.get("trends") or []:
                if not trend.get("sufficient_data"):
                    continue
                refs = [
                    ref
                    for point in trend.get("points") or []
                    for ref in point.get("source_refs") or []
                ]
                insights.append({
                    "statement": (
                        f"{trend.get('metric')} shows a {trend.get('direction')} "
                        f"trend (slope {format_number(trend.get('slope'))}) over "
                        f"{len(trend.get('points') or [])} time points"
                    ),
                    "source_refs": refs,
                    "validation_status": "validated",
                })
        elif analysis_type == "anomaly":
            for metric in output.get("metrics") or []:
                if not metric.get("sufficient_data"):
                    continue
                anomalies = metric.get("anomalies") or []
                if not anomalies:
                    continue
                unit = metric.get("unit")
                refs = [
                    ref
                    for anomaly in anomalies
                    for ref in anomaly.get("source_refs") or []
                ]
                examples = ", ".join(
                    f"{format_number(a.get('value'), unit)}"
                    f"{PipelineRunner._unit_suffix(unit)}"
                    f" on {a.get('date') or 'unknown date'}"
                    for a in anomalies[:3]
                )
                count = len(anomalies)
                insights.append({
                    "statement": (
                        f"{metric.get('metric')}: {count} "
                        f"{'anomaly' if count == 1 else 'anomalies'} "
                        f"detected ({examples})"
                    ),
                    "source_refs": refs,
                    "validation_status": "validated",
                })
        elif analysis_type == "comparison":
            for comparison in output.get("comparisons") or []:
                ranking = comparison.get("ranking") or []
                if len(ranking) < 2:
                    continue
                unit = comparison.get("unit")
                top, runner_up = ranking[0], ranking[1]
                pairwise = comparison.get("pairwise") or []
                diff = pairwise[0].get("total_difference") if pairwise else None
                family = comparison.get("family")
                prefix = f"{family}: " if family else ""
                insights.append({
                    "statement": (
                        f"{prefix}{top.get('label')} leads {runner_up.get('label')} "
                        f"by {format_number(diff, unit)}"
                        f"{PipelineRunner._unit_suffix(unit)} "
                        f"(total {format_number(top.get('total'), unit)} vs "
                        f"{format_number(runner_up.get('total'), unit)})"
                    ),
                    "source_refs": (
                        (top.get("source_refs") or [])
                        + (runner_up.get("source_refs") or [])
                    ),
                    "validation_status": "validated",
                })
        elif analysis_type == "correlation":
            for correlation in output.get("correlations") or []:
                insights.append({
                    "statement": (
                        f"{correlation.get('metric_a')} vs "
                        f"{correlation.get('metric_b')}: "
                        f"r = {format_number(correlation.get('r'))} across "
                        f"{correlation.get('n')} paired observations "
                        f"({CORRELATION_LABEL})"  # FR4.1.5 — statement tail
                    ),
                    "source_refs": correlation.get("source_refs") or [],
                    "validation_status": "validated",
                })
        return insights

    # ------------------------------------------------------------------
    # Stage 5 — SUMMARISE
    # ------------------------------------------------------------------
    async def _stage_summarise(
        self,
        db: AsyncSession,
        sf: SmartFolder,
        user: User,
        ranked: list[dict],
        analyses: list[dict],
        insights: list[dict],
        confirmed_params: dict[str, Any],
    ) -> tuple[str | None, list[str]]:
        if not insights:
            # FR6.1: nothing validated to narrate — no summary, no LLM call.
            await audit_logger.log_event(
                db,
                request_id=sf.id,
                user_id=user.id,
                stage="summarise",
                action="summary_skipped",
                detail={"reason": INSUFFICIENT_SUMMARY_NOTE},
            )
            await self._set_state(
                db, sf, CollectionJobState.PACKAGING.value, "summarise",
                summary=None, note=INSUFFICIENT_SUMMARY_NOTE,
            )
            return None, []

        user_context = {
            "user_id": str(user.id),
            "has_confidential": any(
                it.get("acl_stamp") == "confidential" for it in ranked
            ),
        }
        insight_payloads = [
            {k: v for k, v in insight.items() if not k.startswith("_")}
            for insight in insights
        ]

        # Rich memo (2026-08-04): the summary LLM may read the ranked items'
        # full snippets (as verified source material) to dig each document,
        # while every figure still has to come from the computed insights.
        source_items = ranked[: self.summary_generator.MAX_SOURCE_ITEMS]
        source_refs = [
            {"title": it.get("title"), "document_id": it.get("document_id")}
            for it in ranked
            if it.get("document_id")
        ]
        # Numbers traceable to a cited source excerpt are grounded (rich memo).
        source_numbers: set[float] = set()
        for it in ranked:
            source_numbers.update(
                self.grounding_validator._numbers_in(it.get("snippet") or "")
            )

        async def _generate() -> str | None:
            return await self.summary_generator.generate(
                insight_payloads, analyses, confirmed_params, user_context,
                source_items=source_items,
            )

        async with audit_logger.audit_stage(
            db,
            request_id=sf.id,
            user_id=user.id,
            stage="summarise",
            action="generate_grounded_summary",
        ) as set_output:
            final_md, report, removed = await self.grounding_validator.validate_with_regeneration(
                _generate,
                analyses,
                insight_payloads,
                max_attempts=2,
                db=db,
                request_id=sf.id,
                user_id=user.id,
                source_refs=source_refs,
                source_numbers=source_numbers,
            )
            set_output(
                validation_passed=report.passed,
                checked_claims=report.checked_claims,
                removed_claims=len(removed),
            )

        if final_md and removed:
            # FR4.2.5 disclosure footer.
            final_md += (
                f"\n\n---\n*{len(removed)} statement(s) were removed during "
                "grounding validation because they could not be traced to "
                "computed data. See the disclosures section.*"
            )

        await self._set_state(
            db, sf, CollectionJobState.PACKAGING.value, "summarise",
            summary="generated" if final_md else None,
            removed_claims=len(removed),
        )
        return final_md, removed

    # ------------------------------------------------------------------
    # Stage 6 — PACKAGE
    # ------------------------------------------------------------------
    async def _stage_package(
        self,
        db: AsyncSession,
        sf: SmartFolder,
        final_md: str | None,
        removed: list[str],
        items: list[dict],
        executions: list[dict],
        analyses: list[dict],
        extraction: dict[str, Any],
        insights: list[dict],
        gate_info: dict[str, Any] | None = None,
        summary_unavailable: bool = False,
    ) -> Deliverable:
        meta = getattr(self.search_adapter, "last_run_meta", {}) or {}

        disclosures: list[dict[str, Any]] = []
        # Absolute relevance gate (Scenario 4 doctrine).
        if gate_info and gate_info.get("items_gated"):
            disclosures.append({
                "type": "relevance_gate",
                **gate_info,
                "message": (
                    f"{gate_info['items_gated']} low-relevance candidate(s) "
                    f"excluded by the absolute relevance gate "
                    f"({gate_info['threshold']})."
                ),
            })
        # FR6.3 truncation / ranking-rule disclosure. items_retrieved is
        # everything search returned; items_processed is what actually went
        # through annotation/extraction/analysis (post-gate, post-budget).
        process_info = gate_info or {}
        disclosures.append({
            "type": "truncation",
            "items_retrieved": len(items),
            "items_processed": process_info.get("items_processed", len(items)),
            "items_gated": process_info.get("items_gated", 0),
            "analysis_budget": process_info.get("analysis_budget"),
            "truncated": bool(meta.get("truncated")),
            "cache_hit": bool(meta.get("cache_hit")),
            "ranking_rule": (
                f"ranking v{RANKING_VERSION}: "
                "0.55*search + 0.25*rerank + 0.10*recency + 0.10*type_weight"
            ),
        })
        # FR6.2 ACL trimming disclosure — COUNT ONLY, never titles/snippets
        # of trimmed items. Tenant-configurable via COLLECTION_SHOW_TRIMMED_COUNT.
        trimmed_count = meta.get("acl_trimmed_count")
        if trimmed_count:
            if _show_trimmed_count():
                disclosures.append({
                    "type": "acl_trimming",
                    "trimmed_count": trimmed_count,
                    "shown": True,
                    "message": (
                        f"{trimmed_count} document(s) matched the request "
                        "filters but sit outside your access level and were "
                        "excluded."
                    ),
                })
            else:
                disclosures.append({
                    "type": "acl_trimming",
                    "shown": False,
                    "message": (
                        "Some matching documents sit outside your access "
                        "level and were excluded."
                    ),
                })
        # FR6.5 degraded sources.
        failed_specs = [e for e in executions if e.get("status") == "failed"]
        if failed_specs:
            disclosures.append({
                "type": "degraded_sources",
                "failed_queries": [
                    {
                        "payload": e.get("search_call_payload"),
                        "error": str(e.get("error"))[:300],
                    }
                    for e in failed_specs
                ],
            })
        # FR4.2.5 removed claims.
        if removed:
            disclosures.append({
                "type": "removed_claims",
                "count": len(removed),
                "sentences": removed,
            })
        # FR4.1.8 conflicts.
        if extraction.get("conflicts"):
            disclosures.append({
                "type": "conflicts",
                "count": len(extraction["conflicts"]),
                "conflicts": extraction["conflicts"],
            })
        if final_md is None:
            disclosures.append({
                "type": "no_summary",
                "message": (
                    SUMMARY_UNAVAILABLE_NOTE if summary_unavailable
                    else INSUFFICIENT_SUMMARY_NOTE
                ),
            })

        async with audit_logger.audit_stage(
            db,
            request_id=sf.id,
            user_id=sf.user_id,
            stage="package",
            action="create_deliverable",
        ) as set_output:
            deliverable = Deliverable(
                request_id=sf.id,
                version=await _next_deliverable_version(db, sf.id),
                summary_md=final_md,
                item_list_ref=f"api://collection-requests/{sf.id}/items",
                appendix={
                    "analyses": [
                        {
                            "analysis_type": a.get("analysis_type"),
                            "output": a.get("output"),
                            "provenance": a.get("provenance"),
                        }
                        for a in analyses
                    ],
                    "conflicts": extraction.get("conflicts") or [],
                    "low_confidence_fact_count": len(extraction.get("low_confidence") or []),
                    "normalization_notes": extraction.get("normalization_notes") or [],
                    "insight_count": len(insights),
                    "links_permission_bound": True,
                },
                disclosures=disclosures,
            )
            db.add(deliverable)
            await db.flush()
            set_output(output_ref=f"deliverable:{deliverable.id}")

        sf.job_state = CollectionJobState.COMPLETED.value
        sf.error_message = None  # clear any stale message from a retried run
        sf.checkpoint = {
            "last_stage": "package",
            "stage_outputs_refs": {"deliverable_id": str(deliverable.id)},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.commit()
        return deliverable


# Lazy singleton — keeps module import free of config/env requirements
# (ExtractionPipeline reads settings at construction).
_default_runner: PipelineRunner | None = None


def get_pipeline_runner() -> PipelineRunner:
    global _default_runner
    if _default_runner is None:
        _default_runner = PipelineRunner()
    return _default_runner
