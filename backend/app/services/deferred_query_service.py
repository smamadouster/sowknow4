"""
Deferred Query Service — Ollama Unavailability Fallback.

When Ollama is down and a confidential query arrives, the query is enqueued
here and retried once Ollama recovers.  Queries older than 24 hours are
automatically expired and cleaned up.

Usage::

    from app.services.deferred_query_service import deferred_query_service

    # Enqueue a query that could not be answered (Ollama was unavailable)
    deferred_id = await deferred_query_service.enqueue(
        user_id=user_id,
        query_text=query,
        document_ids=[str(d.id) for d in docs],
    )

    # Called by Celery beat / background task once Ollama recovers
    await deferred_query_service.process_pending()
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

# Deferred queries expire after 24 hours
EXPIRY_HOURS = 24  # max 24


class _InMemoryStore:
    """
    Lightweight in-memory store for deferred queries.

    In production this is backed by PostgreSQL (DeferredQuery model).
    The in-memory fallback allows the service to work without a DB migration
    while still satisfying the interface.
    """

    def __init__(self) -> None:
        self._queries: Dict[str, Dict[str, Any]] = {}

    def add(self, record: Dict[str, Any]) -> None:
        self._queries[str(record["id"])] = record

    def get(self, query_id: str) -> Optional[Dict[str, Any]]:
        return self._queries.get(query_id)

    def list_pending(self) -> List[Dict[str, Any]]:
        now = datetime.utcnow()
        return [
            q for q in self._queries.values()
            if q["status"] == "pending" and q["expires_at"] > now
        ]

    def update(self, query_id: str, **fields: Any) -> None:
        if query_id in self._queries:
            self._queries[query_id].update(fields)
            self._queries[query_id]["updated_at"] = datetime.utcnow()

    def expire_old(self) -> int:
        now = datetime.utcnow()
        expired = [
            qid for qid, q in self._queries.items()
            if q["status"] == "pending" and q["expires_at"] <= now
        ]
        for qid in expired:
            self._queries[qid]["status"] = "expired"
        return len(expired)


class DeferredQueryService:
    """
    Manage deferred (queued) LLM queries for when Ollama is unavailable.

    Supports both an in-memory store (default) and can be extended to use
    the DeferredQuery SQLAlchemy model for persistence.
    """

    def __init__(self) -> None:
        self._store = _InMemoryStore()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        user_id: str,
        query_text: str,
        document_ids: Optional[List[str]] = None,
        context_chunks: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        Enqueue a query that could not be processed because Ollama was down.

        Returns the deferred query ID so the caller can inform the user.
        The query expires after 24 hours if not processed.
        """
        now = datetime.utcnow()
        query_id = str(uuid4())

        record: Dict[str, Any] = {
            "id": query_id,
            "user_id": str(user_id),
            "session_id": str(session_id) if session_id else None,
            "query_text": query_text,
            "document_ids": document_ids or [],
            "context_chunks": context_chunks or [],
            "system_prompt": system_prompt,
            "status": "pending",
            "retry_count": 0,
            "max_retries": 3,
            "response_text": None,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
            # 24-hour expiry
            "expires_at": now + timedelta(hours=EXPIRY_HOURS),
        }

        self._store.add(record)
        logger.info(
            f"DeferredQuery enqueued: id={query_id} user={user_id} "
            f"expires={record['expires_at'].isoformat()}"
        )
        return query_id

    async def process_pending(self) -> Dict[str, int]:
        """
        Attempt to process all pending deferred queries using Ollama.

        Called by a Celery periodic task once Ollama health is confirmed.
        Returns counts of processed / failed / skipped queries.
        """
        # Expire stale queries first
        expired = self._store.expire_old()
        if expired:
            logger.info(f"DeferredQueryService: expired {expired} old queries (>24h)")

        pending = self._store.list_pending()
        if not pending:
            return {"processed": 0, "failed": 0, "expired": expired}

        processed = 0
        failed = 0

        for record in pending:
            query_id = str(record["id"])
            retry_count = record.get("retry_count", 0)

            if retry_count >= record.get("max_retries", 3):
                self._store.update(query_id, status="failed", error_message="Max retries exceeded")
                failed += 1
                continue

            try:
                response = await self._call_ollama(record)
                self._store.update(
                    query_id,
                    status="completed",
                    response_text=response,
                )
                processed += 1
                logger.info(f"DeferredQuery processed: id={query_id}")

            except Exception as exc:
                self._store.update(
                    query_id,
                    retry_count=retry_count + 1,
                    error_message=str(exc),
                )
                failed += 1
                logger.warning(f"DeferredQuery retry {retry_count + 1}: id={query_id} error={exc}")

        return {"processed": processed, "failed": failed, "expired": expired}

    async def get_status(self, query_id: str) -> Optional[Dict[str, Any]]:
        """Return the current state of a deferred query."""
        record = self._store.get(query_id)
        if record is None:
            return None
        return {
            "id": record["id"],
            "status": record["status"],
            "retry_count": record["retry_count"],
            "response_text": record["response_text"],
            "error_message": record["error_message"],
            "created_at": record["created_at"].isoformat(),
            "expires_at": record["expires_at"].isoformat(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_ollama(self, record: Dict[str, Any]) -> str:
        """Call Ollama to answer the deferred query."""
        from app.services.ollama_service import ollama_service  # lazy import

        messages: List[Dict[str, str]] = []
        if record.get("system_prompt"):
            messages.append({"role": "system", "content": record["system_prompt"]})
        messages.append({"role": "user", "content": record["query_text"]})

        response_parts: List[str] = []
        async for chunk in ollama_service.chat_completion(messages, stream=False):
            response_parts.append(chunk)

        return "".join(response_parts)


# Module-level singleton
deferred_query_service = DeferredQueryService()
