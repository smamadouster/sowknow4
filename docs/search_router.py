"""
SOWKNOW Agentic Search — FastAPI Router
Exposes the search pipeline as REST + Server-Sent Events endpoints.
All routes enforce JWT authentication and role extraction.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user, CurrentUser
from .database import get_db
from .search_agent import (
    build_search_queries,
    build_citations,
    embed_query,
    generate_suggestions,
    hybrid_retrieve,
    parse_intent,
    rerank_and_build_results,
    run_agentic_search,
    synthesize_answer,
)
from .search_models import (
    AgentTrace,
    SearchMode,
    SearchRequest,
    SearchResponse,
    UserRole,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["Search"])


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _role_from_user(user: CurrentUser) -> UserRole:
    try:
        return UserRole(user.role)
    except ValueError:
        return UserRole.USER


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/search — Main agentic search (JSON response)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=SearchResponse,
    summary="Agentic search",
    description=(
        "Full 6-stage agentic search pipeline. "
        "Returns ranked results, synthesized answer, citations, and suggestions. "
        "Confidential results are only visible to Admin and Super User roles."
    ),
)
async def search(
    request: SearchRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    user_role = _role_from_user(current_user)
    try:
        return await run_agentic_search(
            db=db,
            request=request,
            user_role=user_role,
            user_id=current_user.id,
        )
    except Exception as exc:
        logger.exception("Search pipeline error for user %s: %s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="La recherche a rencontré une erreur. Veuillez réessayer.",
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/search/stream — Streaming search with SSE progress events
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/stream",
    summary="Streaming agentic search (SSE)",
    description=(
        "Same as /api/search but emits Server-Sent Events for each pipeline stage, "
        "allowing the UI to progressively display intent, results, then the synthesized answer."
    ),
)
async def search_stream(
    request: SearchRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    user_role = _role_from_user(current_user)

    async def event_generator():
        try:
            # ── Stage 1: Intent ──────────────────────────────────────────────
            yield _sse_event("stage", {"stage": "intent", "message": "Analyse de votre requête…"})
            intent = await parse_intent(request.query)
            yield _sse_event("intent", {
                "intent": intent.intent.value,
                "confidence": intent.confidence,
                "keywords": intent.keywords,
                "sub_queries": intent.sub_queries,
                "language": intent.detected_language,
            })

            if request.language:
                intent.detected_language = request.language

            # ── Stage 2: Query expansion ─────────────────────────────────────
            queries = build_search_queries(intent, request.query)
            yield _sse_event("stage", {"stage": "retrieval", "message": f"Recherche dans {len(queries)} requête(s)…"})

            # ── Stage 3: Hybrid retrieval ─────────────────────────────────────
            raw_chunks = await hybrid_retrieve(db, queries, user_role, request)
            yield _sse_event("stage", {
                "stage": "reranking",
                "message": f"{len(raw_chunks)} extraits récupérés, reclassement…",
            })

            # ── Stage 4: Re-rank ──────────────────────────────────────────────
            results, has_confidential = rerank_and_build_results(
                raw_chunks, request.query, intent, request.top_k, user_role
            )
            # Stream results immediately — user sees them before synthesis
            yield _sse_event("results", {
                "results": [r.model_dump() for r in results],
                "total_found": len(results),
                "has_confidential_results": has_confidential,
            })

            # ── Stage 5: Synthesis ────────────────────────────────────────────
            model_used = None
            if results and (
                request.mode == SearchMode.DEEP
                or intent.requires_synthesis
                or request.mode == SearchMode.AUTO
            ):
                yield _sse_event("stage", {"stage": "synthesis", "message": "Synthèse de la réponse…"})
                answer, model_used = await synthesize_answer(
                    request.query, results, raw_chunks, intent, has_confidential, intent.detected_language
                )
                yield _sse_event("synthesis", {
                    "answer": answer,
                    "model": model_used,
                    "language": intent.detected_language,
                })

            # ── Stage 6: Suggestions ──────────────────────────────────────────
            if request.include_suggestions and results:
                suggestions = await generate_suggestions(request.query, results, intent, has_confidential)
                yield _sse_event("suggestions", {"suggestions": [s.model_dump() for s in suggestions]})

            # ── Citations ─────────────────────────────────────────────────────
            citations = build_citations(results, raw_chunks)
            yield _sse_event("citations", {"citations": [c.model_dump() for c in citations]})

            # ── Done ──────────────────────────────────────────────────────────
            yield _sse_event("done", {
                "total_found": len(results),
                "model": model_used,
                "has_confidential": has_confidential,
            })

        except Exception as exc:
            logger.exception("Streaming search error: %s", exc)
            yield _sse_event("error", {"message": "Erreur lors de la recherche. Veuillez réessayer."})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/search/intent — Lightweight intent preview (no retrieval)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/intent",
    summary="Parse query intent only",
    description="Returns intent classification without executing the full search. Useful for UI previews.",
)
async def get_intent(
    payload: dict,
    current_user: CurrentUser = Depends(get_current_user),
):
    query = payload.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")
    intent = await parse_intent(query)
    return {
        "intent": intent.intent.value,
        "confidence": intent.confidence,
        "keywords": intent.keywords,
        "sub_queries": intent.sub_queries,
        "language": intent.detected_language,
        "requires_synthesis": intent.requires_synthesis,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/search/history — Recent searches for the current user
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/history",
    summary="User search history",
    description="Returns the last 20 searches for the authenticated user.",
)
async def search_history(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import text as sql_text
    rows = (await db.execute(
        sql_text("""
            SELECT query, parsed_intent, result_count, search_time_ms, performed_at
            FROM search_history
            WHERE user_id = :uid
            ORDER BY performed_at DESC
            LIMIT :lim
        """),
        {"uid": str(current_user.id), "lim": limit},
    )).mappings().all()
    return [dict(r) for r in rows]
