"""SOWKNOW Agentic Search — FastAPI Router"""

import asyncio
import json
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.document import DocumentBucket
from app.models.user import User, UserRole
from app.services.input_guard import input_guard
from app.services.search_agent import (
    build_citations,
    build_search_queries,
    generate_suggestions,
    parse_intent,
    rerank_and_build_results,
    run_agentic_search,
    synthesize_answer,
)
from app.services.search_models import (
    AgenticSearchRequest,
    AgenticSearchResponse,
    QueryIntent,
    RawChunk,
    SearchMode,
)
from app.services.search_service import HybridSearchService, _get_regconfig

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["Search"])

MAX_CONCURRENT_SEARCHES = 5
_search_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)


def _role_from_user(user: User) -> UserRole:
    try:
        return UserRole(user.role)
    except ValueError:
        return UserRole.USER


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _convert_search_results_to_chunks(search_results) -> list[RawChunk]:
    """Convert search_service.SearchResult objects to RawChunk models."""
    chunks = []
    for sr in search_results:
        try:
            bucket = DocumentBucket(sr.document_bucket) if sr.document_bucket else DocumentBucket.PUBLIC
        except Exception:
            bucket = DocumentBucket.PUBLIC
        chunks.append(RawChunk(
            chunk_id=sr.chunk_id,
            document_id=sr.document_id,
            document_title=sr.document_name,
            document_bucket=bucket,
            document_type=sr.document_name.rsplit(".", 1)[-1] if "." in sr.document_name else "unknown",
            chunk_index=sr.chunk_index,
            page_number=sr.page_number,
            text=sr.chunk_text,
            semantic_score=sr.semantic_score,
            fts_rank=sr.keyword_score,
            rrf_score=sr.final_score,
            tags=[],
        ))
    return chunks


def _deduplicate_chunks(chunks: list[RawChunk]) -> list[RawChunk]:
    seen: set[UUID] = set()
    result = []
    for c in chunks:
        if c.chunk_id not in seen:
            seen.add(c.chunk_id)
            result.append(c)
    return result


@router.post("", response_model=AgenticSearchResponse)
async def search(
    request: AgenticSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgenticSearchResponse:
    # --- InputGuard pre-processing ---
    try:
        guard_result = await input_guard.process(
            query=request.query,
            user_role=current_user.role.value if hasattr(current_user, 'role') else "user",
            document_ids=None,
        )
        logger.info(
            "InputGuard: lang=%s intent=%s vault=%s pii=%s",
            guard_result.language, guard_result.intent,
            guard_result.vault_hint, guard_result.pii_detected,
        )
        if guard_result.pii_detected:
            logger.warning("InputGuard: PII detected in search query from user %s", current_user.id)
        if guard_result.is_duplicate:
            return AgenticSearchResponse(
                query=request.query,
                parsed_intent=QueryIntent.FACTUAL,
                results=[],
                citations=[],
                total_found=0,
                has_confidential_results=False,
                search_time_ms=0,
                answer_synthesis="Cette requête est en cours de traitement. / This query is already being processed.",
            )
    except Exception as e:
        logger.warning("InputGuard: guard processing failed, continuing without guard: %s", e)

    if _search_semaphore._value == 0:
        raise HTTPException(
            status_code=429,
            detail="Too many concurrent searches. Please retry.",
            headers={"Retry-After": "5"},
        )
    async with _search_semaphore:
        user_role = _role_from_user(current_user)
        try:
            response = await run_agentic_search(
                db=db, request=request, user_role=user_role,
                user_id=current_user.id, user=current_user,
            )
            await _save_search_history(db, current_user.id, response)
            return response
        except Exception as exc:
            logger.exception("Search pipeline error for user %s: %s", current_user.id, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="La recherche a rencontre une erreur. Veuillez reessayer.",
            ) from exc


@router.post("/stream")
async def search_stream(
    request: AgenticSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    user_role = _role_from_user(current_user)

    # --- InputGuard pre-processing ---
    try:
        guard_result = await input_guard.process(
            query=request.query,
            user_role=current_user.role.value if hasattr(current_user, 'role') else "user",
            document_ids=None,
        )
        logger.info(
            "InputGuard[stream]: lang=%s intent=%s vault=%s pii=%s",
            guard_result.language, guard_result.intent,
            guard_result.vault_hint, guard_result.pii_detected,
        )
        if guard_result.pii_detected:
            logger.warning("InputGuard: PII detected in streaming search from user %s", current_user.id)
        if guard_result.is_duplicate:
            async def _dup_gen():
                yield _sse_event("error", {
                    "message": "Cette requête est en cours de traitement. / This query is already being processed.",
                    "duplicate": True,
                })
            return StreamingResponse(
                _dup_gen(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
    except Exception as e:
        logger.warning("InputGuard: guard processing failed, continuing without guard: %s", e)

    async def event_generator():
        start = time.monotonic()
        try:
            yield _sse_event("stage", {"stage": "intent", "message": "Analyse de votre requete..."})
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

            queries = build_search_queries(intent, request.query)
            yield _sse_event("stage", {"stage": "retrieval", "message": f"Recherche dans {len(queries)} requete(s)..."})

            search_service = HybridSearchService()

            async def _search_one(query_text: str) -> list[RawChunk]:
                result = await search_service.hybrid_search(
                    query=query_text, limit=request.top_k * 3,
                    offset=0, db=db, user=current_user,
                    regconfig=_get_regconfig(intent.detected_language),
                )
                return _convert_search_results_to_chunks(result.get("results", []))

            sub_results = await asyncio.gather(*[_search_one(qt) for qt in queries], return_exceptions=True)
            all_chunks: list[RawChunk] = []
            for res in sub_results:
                if isinstance(res, Exception):
                    logger.warning("Streaming sub-query failed: %s", res)
                    continue
                all_chunks.extend(res)

            all_chunks = _deduplicate_chunks(all_chunks)

            yield _sse_event("stage", {
                "stage": "reranking",
                "message": f"{len(all_chunks)} extraits recuperes, reclassement...",
            })

            results, has_confidential = rerank_and_build_results(
                all_chunks, request.query, intent, request.top_k, user_role,
            )
            yield _sse_event("results", {
                "results": [r.model_dump() for r in results],
                "total_found": len(results),
                "has_confidential_results": has_confidential,
            })

            mode = request.mode
            if mode == SearchMode.AUTO:
                mode = SearchMode.FAST if len(request.query.split()) <= 5 else SearchMode.DEEP

            model_used = None
            if results and (
                mode == SearchMode.DEEP
                or intent.requires_synthesis
                or intent.intent in (QueryIntent.SYNTHESIS, QueryIntent.TEMPORAL, QueryIntent.COMPARATIVE, QueryIntent.FINANCIAL)
            ):
                yield _sse_event("stage", {"stage": "synthesis", "message": "Synthese de la reponse..."})
                answer, model_used = await synthesize_answer(
                    request.query, results, all_chunks, intent, has_confidential, intent.detected_language,
                )
                yield _sse_event("synthesis", {
                    "answer": answer, "model": model_used, "language": intent.detected_language,
                })

            if request.include_suggestions and results:
                suggestions = await generate_suggestions(request.query, results, intent, has_confidential)
                yield _sse_event("suggestions", {"suggestions": [s.model_dump() for s in suggestions]})

            citations = build_citations(results, all_chunks)
            yield _sse_event("citations", {"citations": [c.model_dump() for c in citations]})

            elapsed_ms = int((time.monotonic() - start) * 1000)
            yield _sse_event("done", {
                "total_found": len(results),
                "model": model_used,
                "has_confidential": has_confidential,
                "search_time_ms": elapsed_ms,
            })

        except Exception as exc:
            logger.exception("Streaming search error: %s", exc)
            yield _sse_event("error", {"message": "Erreur lors de la recherche. Veuillez reessayer."})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/global")
async def search_global(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    types: str = Query(
        default="document,bookmark,note,space",
        description="Comma-separated list of types to search: document,bookmark,note,space",
    ),
    page: int = Query(default=1, ge=1, le=100),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Multi-type global search across documents, bookmarks, notes, and spaces.
    Returns unified results with result_type, id, title, description, tags, score.
    """
    type_list = [t.strip() for t in types.split(",") if t.strip()]
    valid_types = {"document", "bookmark", "note", "space"}
    type_list = [t for t in type_list if t in valid_types]
    if not type_list:
        type_list = list(valid_types)

    search_svc = HybridSearchService()
    result = await search_svc.search_all_types(
        query=q,
        types=type_list,
        user=current_user,
        db=db,
        page=page,
        page_size=page_size,
    )
    return result


@router.post("/intent")
async def get_intent(
    payload: dict,
    current_user: User = Depends(get_current_user),
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


@router.get("/history")
async def search_history(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        sql_text("""
            SELECT query, parsed_intent, result_count, search_time_ms, performed_at
            FROM sowknow.search_history
            WHERE user_id = :uid
            ORDER BY performed_at DESC
            LIMIT :lim
        """),
        {"uid": str(current_user.id), "lim": limit},
    )).mappings().all()
    return [dict(r) for r in rows]


async def _save_search_history(db: AsyncSession, user_id: UUID, response: AgenticSearchResponse):
    try:
        await db.execute(
            sql_text("""
                INSERT INTO sowknow.search_history
                    (user_id, query, parsed_intent, result_count, has_confidential_results,
                     llm_model_used, search_time_ms)
                VALUES (:uid, :query, :intent, :count, :conf, :model, :time_ms)
            """),
            {
                "uid": str(user_id),
                "query": response.query,
                "intent": response.parsed_intent.value,
                "count": response.total_found,
                "conf": response.has_confidential_results,
                "model": response.llm_model_used,
                "time_ms": response.search_time_ms,
            },
        )
        await db.commit()
    except Exception as exc:
        logger.warning("Failed to save search history: %s", exc)
