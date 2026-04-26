"""
Context Block Service — Working Memory Layer (Sprint 2)

Generates a compressed system context block (~2000 tokens) that captures
static knowledge base information every agent needs.  The block is assembled
once and cached in Redis, not regenerated per query.
"""

import logging
from datetime import UTC, datetime

import redis as _redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_url import safe_redis_url
from app.models.document import DocumentBucket

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------
CONTEXT_BLOCK_KEY = "sowknow:context_block"
CONTEXT_BLOCK_TTL = 3600  # 1 hour

_redis_client: _redis.Redis | None = None


def _get_redis() -> _redis.Redis | None:
    """Lazy-initialise and return a Redis client.  Returns None on failure."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        _redis_client = _redis.from_url(
            safe_redis_url(),
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        _redis_client.ping()
        return _redis_client
    except Exception:
        logger.warning("context_block_service: Redis unavailable — caching disabled")
        _redis_client = None
        return None


# ---------------------------------------------------------------------------
# Static fallback block (used when DB/Redis are both unreachable)
# ---------------------------------------------------------------------------
_STATIC_BLOCK = """[SOWKNOW Context Block — v1.0 — static fallback]

IDENTITY:
  System: SOWKNOW Multi-Generational Legacy Knowledge System
  Languages: French (primary), English (secondary)

VAULT:
  Status: database unavailable — stats unknown

ROUTING RULES:
  Cloud LLMs (OpenRouter/MiniMax): All documents
"""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

async def generate_context_block(db: AsyncSession) -> str:
    """Query document stats, entity counts, and corpus info to build a
    compressed context block string.

    Handles missing tables / empty database gracefully.
    """
    try:
        return await _build_block(db)
    except Exception:
        logger.exception("context_block_service: failed to generate block — returning static fallback")
        return _STATIC_BLOCK


async def get_cached_context_block(db: AsyncSession) -> str:
    """Return the cached context block from Redis.  Falls back to
    generating (and caching) a fresh block if the cache is empty."""
    r = _get_redis()
    if r is not None:
        try:
            cached = r.get(CONTEXT_BLOCK_KEY)
            if cached is not None:
                return cached
        except Exception:
            logger.warning("context_block_service: Redis read failed — regenerating")

    block = await generate_context_block(db)

    # Attempt to cache
    if r is not None:
        try:
            r.setex(CONTEXT_BLOCK_KEY, CONTEXT_BLOCK_TTL, block)
        except Exception:
            logger.warning("context_block_service: Redis write failed — block not cached")

    return block


def invalidate_context_block() -> None:
    """Clear the cached context block from Redis.

    Call this when documents are added/deleted or entities change.
    """
    r = _get_redis()
    if r is not None:
        try:
            r.delete(CONTEXT_BLOCK_KEY)
        except Exception:
            logger.warning("context_block_service: failed to invalidate cache")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _build_block(db: AsyncSession) -> str:
    """Assemble the context block from live database data."""

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    # -- Document stats by bucket -------------------------------------------
    public_count, public_pages = await _doc_stats(db, DocumentBucket.PUBLIC)
    confidential_count, confidential_pages = await _doc_stats(db, DocumentBucket.CONFIDENTIAL)

    # -- Date range ---------------------------------------------------------
    earliest, latest = await _date_range(db)

    # -- Format distribution ------------------------------------------------
    format_dist = await _format_distribution(db)

    # -- Top topics (from DocumentTag) --------------------------------------
    top_topics = await _top_topics(db)

    # -- Entity counts (graceful if table missing) --------------------------
    entity_summary = await _entity_summary(db)

    # -- Assemble block -----------------------------------------------------
    lines = [
        f"[SOWKNOW Context Block — v1.0 — Generated {now}]",
        "",
        "IDENTITY:",
        "  System: SOWKNOW Multi-Generational Legacy Knowledge System",
        "  Languages: French (primary), English (secondary)",
        "",
        "VAULT:",
        f"  Public documents: {public_count} ({public_pages} pages)",
        f"  Confidential documents: {confidential_count} (access: Admin + Super User only)",
    ]

    if top_topics:
        lines.append(f"  Top topics: {', '.join(top_topics)}")

    if entity_summary:
        lines.append(f"  Entities: {entity_summary}")

    lines += [
        "",
        "CORPUS SUMMARY:",
        f"  Date range: {earliest or 'N/A'} to {latest or 'N/A'}",
        f"  Format distribution: {format_dist or 'N/A'}",
        "",
        "ROUTING RULES:",
        "  Cloud LLMs (OpenRouter/MiniMax): All documents",
    ]

    return "\n".join(lines)


async def _doc_stats(db: AsyncSession, bucket: DocumentBucket) -> tuple[int, int]:
    """Return (count, total_pages) for documents in the given bucket."""
    try:
        result = await db.execute(
            text(
                "SELECT COUNT(*), COALESCE(SUM(page_count), 0) "
                "FROM sowknow.documents "
                "WHERE bucket = :bucket AND status != 'error'"
            ),
            {"bucket": bucket.value},
        )
        row = result.one_or_none()
        if row:
            return int(row[0]), int(row[1])
    except Exception:
        logger.debug("context_block_service: _doc_stats failed for %s", bucket)
    return 0, 0


async def _date_range(db: AsyncSession) -> tuple[str | None, str | None]:
    """Return (earliest_date, latest_date) as ISO strings."""
    try:
        result = await db.execute(
            text(
                "SELECT MIN(created_at)::date, MAX(created_at)::date "
                "FROM sowknow.documents WHERE status != 'error'"
            )
        )
        row = result.one_or_none()
        if row and row[0]:
            return str(row[0]), str(row[1])
    except Exception:
        logger.debug("context_block_service: _date_range failed")
    return None, None


async def _format_distribution(db: AsyncSession) -> str:
    """Return a compact string like 'PDF: 42, DOCX: 12, JPG: 5'."""
    try:
        result = await db.execute(
            text(
                "SELECT mime_type, COUNT(*) as cnt "
                "FROM sowknow.documents WHERE status != 'error' "
                "GROUP BY mime_type ORDER BY cnt DESC LIMIT 8"
            )
        )
        rows = result.all()
        if not rows:
            return ""
        parts = []
        for mime, cnt in rows:
            # Shorten mime_type: "application/pdf" -> "PDF"
            short = _shorten_mime(mime)
            parts.append(f"{short}: {cnt}")
        return ", ".join(parts)
    except Exception:
        logger.debug("context_block_service: _format_distribution failed")
    return ""


async def _top_topics(db: AsyncSession, limit: int = 8) -> list[str]:
    """Return top topic tags by frequency."""
    try:
        result = await db.execute(
            text(
                "SELECT tag_name, COUNT(*) as cnt "
                "FROM sowknow.document_tags "
                "WHERE tag_type = 'topic' "
                "GROUP BY tag_name ORDER BY cnt DESC LIMIT :lim"
            ),
            {"lim": limit},
        )
        rows = result.all()
        return [row[0] for row in rows]
    except Exception:
        logger.debug("context_block_service: _top_topics failed (table may not exist)")
    return []


async def _entity_summary(db: AsyncSession) -> str:
    """Return a compact entity summary like '23 persons, 15 organizations, 8 locations'."""
    try:
        result = await db.execute(
            text(
                "SELECT entity_type, COUNT(*) as cnt "
                "FROM sowknow.entities "
                "GROUP BY entity_type ORDER BY cnt DESC LIMIT 5"
            )
        )
        rows = result.all()
        if not rows:
            return ""
        parts = [f"{cnt} {etype}s" for etype, cnt in rows]
        return ", ".join(parts)
    except Exception:
        logger.debug("context_block_service: _entity_summary failed (table may not exist)")
    return ""


def _shorten_mime(mime: str) -> str:
    """Convert a MIME type to a short human label."""
    _map = {
        "application/pdf": "PDF",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PPTX",
        "application/msword": "DOC",
        "application/vnd.ms-excel": "XLS",
        "text/plain": "TXT",
        "text/csv": "CSV",
        "text/xml": "XML",
        "application/xml": "XML",
        "image/jpeg": "JPG",
        "image/png": "PNG",
        "image/tiff": "TIFF",
        "image/webp": "WEBP",
    }
    return _map.get(mime, mime.split("/")[-1].upper() if mime else "UNKNOWN")
