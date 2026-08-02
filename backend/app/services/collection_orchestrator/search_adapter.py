"""Search Adapter — FR2 execution layer for the Collection Orchestrator.

The ONLY component in the collection layer that calls ``search_service``
(signed contract: docs/COLLECTION_REFACTOR_CONTRACT.md §1). Absorbs the
gaps between the spec's search expectations and the actual search API:

- FR2.1  Filter pushdown: date/doc_type/tag filters are resolved to a set of
         matching ``documents.id`` (SQL WHERE on created_at, filename
         extension/mime_type, document_tags) and results outside that set are
         dropped — pushdown to the database, not client-side filtering of an
         unfiltered corpus.
- FR2.3  Offset pagination with a duplicate-guard on page boundaries
         (chunk_ids are tracked across pages) and the A5 hard cap
         (settings.COLLECTION_MAX_ITEMS); hitting the cap sets truncation
         info on ``last_run_meta``.
- FR2.8  Retries: exponential backoff, max 3 attempts, 30s per-call timeout.
         A spec that fails permanently is recorded as a failed
         QueryExecution and the remaining specs continue (degraded mode,
         FR6.5); if every spec fails, SearchUnavailableError is raised (FR6.4).
- FR2.9  Per-user result cache (Redis): identical confirmed-param sets
         within TTL reuse results. The cache key includes the user id, so
         entries are ACL-scoped and never shared across users.
- FR6.2  ACL trimming count: per spec, the COUNT of documents matching the
         spec's filters across all buckets vs the user's buckets is compared
         and the difference aggregated into ``last_run_meta``
         (``acl_trimmed_count`` / ``acl_trimmed_by_spec``). Counts only —
         never titles or snippets of trimmed documents.

Specs run sequentially: a shared AsyncSession corrupts under concurrent
use (documented codebase constraint, see search_service.hybrid_search).

Returns plain dicts — the caller persists SourceItem / QueryExecution rows.
Run metadata (truncation, cache hit) is exposed on ``last_run_meta``.
"""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import redis as _redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_url import safe_redis_url
from app.models.document import Document, DocumentBucket, DocumentTag
from app.services.collection_orchestrator import audit_logger
from app.services.collection_orchestrator.query_planner import (
    MAX_PAGE_SIZE,
    SearchCallSpec,
    paginate,
)
from app.services.search_service import search_service

logger = logging.getLogger(__name__)

CACHE_KEY_PREFIX = "sowknow:collection:results:"

_redis_client: _redis.Redis | None = None


def _default_max_items() -> int:
    """Lazy settings access — keeps module import free of config/env requirements."""
    from app.core.config import settings

    return settings.COLLECTION_MAX_ITEMS


def _default_cache_ttl() -> int:
    from app.core.config import settings

    return settings.COLLECTION_RESULT_CACHE_TTL


def _get_redis() -> _redis.Redis | None:
    """Lazy module-level Redis client (same pattern as search_cache)."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        client = _redis.from_url(
            safe_redis_url(), decode_responses=True, socket_timeout=5, socket_connect_timeout=5
        )
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception:
        logger.warning("search_adapter: Redis unavailable — result caching disabled")
        return None


class SearchUnavailableError(Exception):
    """All search specs failed permanently (FR6.4) — caller must abort the job."""


class SearchAdapter:
    """Executes SearchCallSpec plans against search_service."""

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        base_backoff: float = 0.5,
        timeout: float = 30.0,
        max_items: int | None = None,
        page_size: int = MAX_PAGE_SIZE,
        cache_ttl: int | None = None,
        cache_enabled: bool = True,
        redis_client: Any = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ):
        self.max_attempts = max_attempts
        self.base_backoff = base_backoff
        self.timeout = timeout
        self.max_items = max_items if max_items is not None else _default_max_items()
        self.page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        self.cache_ttl = cache_ttl if cache_ttl is not None else _default_cache_ttl()
        self.cache_enabled = cache_enabled
        self._redis = redis_client
        self._sleep = sleep or asyncio.sleep
        # Populated after every execute_plan call
        self.last_run_meta: dict[str, Any] = {}

    # ── Public entry point ──────────────────────────────────────────────────
    async def execute_plan(
        self,
        specs: list[SearchCallSpec],
        user: Any,
        db: AsyncSession,
        request_id: Any = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Run all specs sequentially; return (SourceItem dicts, QueryExecution dicts)."""
        self.last_run_meta = {
            "truncated": False,
            "cache_hit": False,
            "total_items": 0,
            "acl_trimmed_count": 0,
            "acl_trimmed_by_spec": [],
        }

        cached = self._cache_get(user, specs)
        if cached is not None:
            self.last_run_meta.update(cached["meta"])
            self.last_run_meta["cache_hit"] = True
            await audit_logger.log_event(
                db,
                request_id=request_id,
                user_id=getattr(user, "id", None),
                stage="retrieve",
                action="search_cache_hit",
                detail={"spec_count": len(specs), "item_count": len(cached["items"])},
            )
            return cached["items"], cached["executions"]

        all_items: list[dict[str, Any]] = []
        executions: list[dict[str, Any]] = []
        seen_chunk_ids: set[str] = set()
        allowed_ids_cache: dict[tuple, set[str] | None] = {}
        truncated = False
        any_success = False

        for spec in specs:
            signature = spec.filter_signature()
            if signature not in allowed_ids_cache:
                allowed_ids_cache[signature] = await self._fetch_document_ids(db, spec)
            allowed_ids = allowed_ids_cache[signature]

            # FR6.2: count matches hidden by ACL bucket trimming (count only).
            trimmed = await self._acl_trimmed_count(db, spec, user)
            self.last_run_meta["acl_trimmed_count"] += trimmed
            self.last_run_meta["acl_trimmed_by_spec"].append(
                {"query_text": spec.query_text, "trimmed_count": trimmed}
            )

            page = spec
            while True:
                started_at = datetime.now(timezone.utc)
                started = time.perf_counter()
                try:
                    response = await self._call_with_retries(page, user, db)
                except Exception as exc:
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    logger.warning("Search spec failed permanently: %s (%s)", asdict(page), exc)
                    executions.append(self._execution_dict(page, request_id, started_at, duration_ms, 0, "failed", str(exc)))
                    await audit_logger.log_event(
                        db,
                        request_id=request_id,
                        user_id=getattr(user, "id", None),
                        stage="retrieve",
                        action="search_call",
                        status="failure",
                        duration_ms=duration_ms,
                        detail={"payload": asdict(page), "error": str(exc)[:500]},
                    )
                    break  # degraded mode (FR6.5): next spec continues
                any_success = True
                duration_ms = int((time.perf_counter() - started) * 1000)

                results = response.get("results", [])
                total = response.get("total", 0)
                executions.append(self._execution_dict(page, request_id, started_at, duration_ms, len(results), "completed", None))
                await audit_logger.log_event(
                    db,
                    request_id=request_id,
                    user_id=getattr(user, "id", None),
                    stage="retrieve",
                    action="search_call",
                    duration_ms=duration_ms,
                    detail={"payload": asdict(page), "result_count": len(results), "total": total},
                )

                new_items: list[dict[str, Any]] = []
                for result in results:
                    key = self._dedup_key(result)
                    if key in seen_chunk_ids:
                        continue  # duplicate-guard on page boundaries (FR2.3)
                    if allowed_ids is not None and str(getattr(result, "document_id", "")) not in allowed_ids:
                        continue  # filter pushdown
                    seen_chunk_ids.add(key)
                    new_items.append(self._result_to_item(result))

                budget = self.max_items - len(all_items)
                if len(new_items) > budget:
                    new_items = new_items[:budget]
                    truncated = True
                all_items.extend(new_items)

                if truncated or len(all_items) >= self.max_items:
                    truncated = True
                    break
                if len(results) < page.limit or page.offset + page.limit >= total:
                    break  # branch exhausted
                next_pages = paginate(page, total, max_items=self.max_items)
                if not next_pages:
                    break
                page = next_pages[0]

            if truncated:
                break

        if not any_success:
            raise SearchUnavailableError(
                f"All {len(specs)} search spec(s) failed permanently — search unavailable"
            )

        await self._enrich_items(db, all_items)

        self.last_run_meta.update({"truncated": truncated, "total_items": len(all_items)})
        self._cache_set(user, specs, all_items, executions)
        return all_items, executions

    # ── FR2.8 retries ───────────────────────────────────────────────────────
    async def _call_with_retries(self, spec: SearchCallSpec, user: Any, db: AsyncSession) -> dict:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await search_service.hybrid_search(
                    query=spec.query_text,
                    limit=spec.limit,
                    offset=spec.offset,
                    db=db,
                    user=user,
                    timeout=self.timeout,
                )
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_attempts:
                    delay = self.base_backoff * (2 ** (attempt - 1))
                    logger.info("Search call attempt %d failed (%s); retrying in %.1fs", attempt, exc, delay)
                    await self._sleep(delay)
        raise last_exc  # type: ignore[misc]

    # ── FR2.1 filter pushdown ───────────────────────────────────────────────
    def _spec_conditions(self, spec: SearchCallSpec) -> list:
        """SQL WHERE conditions for the spec's pushed-down filters."""
        conditions = []
        if spec.date_from:
            conditions.append(Document.created_at >= self._parse_dt(spec.date_from))
        if spec.date_to:
            conditions.append(Document.created_at <= self._parse_dt(spec.date_to))
        if spec.doc_types:
            type_conditions = []
            for doc_type in spec.doc_types:
                dt = doc_type.lower().lstrip(".")
                type_conditions.append(func.lower(Document.original_filename).like(f"%.{dt}"))
                type_conditions.append(Document.mime_type.ilike(f"%{dt}%"))
            conditions.append(or_(*type_conditions))
        if spec.tags:
            conditions.append(
                Document.id.in_(
                    select(DocumentTag.document_id).where(DocumentTag.tag_name.in_(list(spec.tags)))
                )
            )
        return conditions

    async def _fetch_document_ids(self, db: AsyncSession, spec: SearchCallSpec) -> set[str] | None:
        """Document ids matching the spec's pushed-down filters.

        Returns None when the spec carries no filters (no restriction).
        """
        if not (spec.doc_types or spec.tags or spec.date_from or spec.date_to):
            return None

        conditions = self._spec_conditions(spec)
        result = await db.execute(select(Document.id).where(*conditions))
        return {str(row) for row in result.scalars().all()}

    # ── FR6.2 ACL trimming count ────────────────────────────────────────────
    @staticmethod
    def _allowed_buckets(user: Any) -> list[str]:
        """User's searchable ACL buckets (search_service RBAC, read-only)."""
        try:
            return list(search_service._get_user_bucket_filter(user))
        except Exception:
            return [DocumentBucket.PUBLIC.value]

    async def _acl_trimmed_count(self, db: AsyncSession, spec: SearchCallSpec, user: Any) -> int:
        """Documents matching the spec's filters across ALL buckets minus
        those in the user's buckets — i.e. how many matches ACL trimming
        hides. COUNT only; never titles/snippets. Never breaks retrieval.

        Only meaningful when the spec carries filters: without filters the
        difference would be "the whole corpus minus your bucket", which says
        nothing about this request — return 0 (no disclosure) in that case.
        """
        try:
            conditions = self._spec_conditions(spec)
            if not conditions:
                return 0
            base = select(func.count()).select_from(Document)
            base = base.where(*conditions)
            total = int((await db.execute(base)).scalar_one() or 0)
            buckets = self._allowed_buckets(user)
            visible = int(
                (await db.execute(base.where(Document.bucket.in_(buckets)))).scalar_one() or 0
            )
            return max(0, total - visible)
        except Exception as exc:
            logger.debug("acl_trimmed_count failed for spec %s: %s", spec.query_text, exc)
            return 0

    @staticmethod
    def _parse_dt(value: Any) -> Any:
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return value  # let the DB driver complain about genuinely bad input

    # ── Result mapping / enrichment ─────────────────────────────────────────
    @staticmethod
    def _dedup_key(result: Any) -> str:
        chunk_id = getattr(result, "chunk_id", None)
        if chunk_id:
            return str(chunk_id)
        return f"{getattr(result, 'document_id', '')}:{getattr(result, 'chunk_index', '')}:{getattr(result, 'result_type', '')}"

    @staticmethod
    def _result_to_item(result: Any) -> dict[str, Any]:
        document_id = getattr(result, "document_id", None)
        snippet = getattr(result, "chunk_text", None) or getattr(result, "article_summary", None) or ""
        bucket = getattr(result, "document_bucket", None)
        return {
            "document_id": str(document_id) if document_id else None,
            "chunk_id": str(getattr(result, "chunk_id", "") or "") or None,
            "uri": None,  # filled by enrichment
            "title": getattr(result, "document_name", None) or getattr(result, "article_title", None),
            "item_type": None,  # filled by enrichment
            "source": getattr(result, "result_type", None) or "chunk",
            "author": None,  # filled by enrichment
            "item_date": None,  # filled by enrichment
            "relevance_score": float(getattr(result, "final_score", 0.0) or 0.0),
            "snippet": snippet[:800],
            "acl_stamp": getattr(bucket, "value", bucket),  # ACL bucket stamped at retrieval time
            "page_number": getattr(result, "page_number", None),
            "match_source": getattr(result, "match_source", None),
            "status": "ok",
        }

    async def _fetch_documents(self, db: AsyncSession, document_ids: set[str]) -> list[Any]:
        if not document_ids:
            return []
        result = await db.execute(select(Document).where(Document.id.in_(list(document_ids))))
        return list(result.scalars().all())

    async def _enrich_items(self, db: AsyncSession, items: list[dict[str, Any]]) -> None:
        """Fill uri/author/item_date/item_type from the Document ORM."""
        doc_ids = {item["document_id"] for item in items if item.get("document_id")}
        documents = await self._fetch_documents(db, doc_ids)
        by_id = {str(doc.id): doc for doc in documents}
        for item in items:
            doc = by_id.get(str(item.get("document_id")))
            if doc is None:
                continue
            meta = doc.document_metadata or {}
            item["uri"] = doc.file_path
            item["title"] = item.get("title") or doc.original_filename
            item["author"] = meta.get("author") or meta.get("creator") or meta.get("sender")
            item["item_date"] = self._parse_dt(meta.get("date")) if meta.get("date") else doc.created_at
            item["item_type"] = self._extension(doc.original_filename) or (doc.mime_type or "").split("/")[-1] or None
            if not item.get("acl_stamp"):
                bucket = doc.bucket
                item["acl_stamp"] = getattr(bucket, "value", bucket)

    @staticmethod
    def _extension(filename: str | None) -> str | None:
        if filename and "." in filename:
            return filename.rsplit(".", 1)[-1].lower()
        return None

    # ── QueryExecution dict ─────────────────────────────────────────────────
    @staticmethod
    def _execution_dict(
        spec: SearchCallSpec,
        request_id: Any,
        started_at: datetime,
        duration_ms: int,
        result_count: int,
        status: str,
        error: str | None,
    ) -> dict[str, Any]:
        return {
            "request_id": str(request_id) if request_id else None,
            "search_call_payload": asdict(spec),
            "started_at": started_at,
            "duration_ms": duration_ms,
            "result_count": result_count,
            "status": status,
            "error": error,
        }

    # ── FR2.9 per-user result cache ─────────────────────────────────────────
    def _cache_key(self, user: Any, specs: list[SearchCallSpec]) -> str:
        payload = json.dumps(
            {"user": str(getattr(user, "id", "")), "specs": [asdict(s) for s in specs]},
            sort_keys=True,
            default=str,
        )
        return CACHE_KEY_PREFIX + hashlib.sha256(payload.encode()).hexdigest()

    def _redis_or_none(self) -> Any:
        return self._redis if self._redis is not None else _get_redis()

    def _cache_get(self, user: Any, specs: list[SearchCallSpec]) -> dict[str, Any] | None:
        if not self.cache_enabled:
            return None
        redis = self._redis_or_none()
        if redis is None:
            return None
        try:
            raw = redis.get(self._cache_key(user, specs))
            if not raw:
                return None
            data = json.loads(raw)
            for item in data["items"]:
                if isinstance(item.get("item_date"), str):
                    item["item_date"] = self._parse_dt(item["item_date"])
            return data
        except Exception as exc:
            logger.debug("search_adapter cache get error: %s", exc)
            return None

    def _cache_set(
        self,
        user: Any,
        specs: list[SearchCallSpec],
        items: list[dict[str, Any]],
        executions: list[dict[str, Any]],
    ) -> None:
        if not self.cache_enabled:
            return
        redis = self._redis_or_none()
        if redis is None:
            return
        try:
            payload = json.dumps(
                {"items": items, "executions": executions, "meta": self.last_run_meta},
                default=str,
            )
            redis.setex(self._cache_key(user, specs), self.cache_ttl, payload)
        except Exception as exc:
            logger.debug("search_adapter cache set error: %s", exc)
