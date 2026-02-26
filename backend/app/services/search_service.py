"""
Hybrid search service combining vector and keyword search
"""

import asyncio
import logging
import re
from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import text, func, desc

from app.models.document import Document, DocumentChunk, DocumentBucket
from app.models.user import User, UserRole
from app.services.embedding_service import embedding_service
from app.services.pii_detection_service import pii_detection_service

logger = logging.getLogger(__name__)


class SearchResult:
    """Container for search results with relevance scores"""

    def __init__(
        self,
        chunk_id: str,
        document_id: str,
        document_name: str,
        document_bucket: str,
        chunk_text: str,
        chunk_index: int,
        page_number: Optional[int],
        semantic_score: float,
        keyword_score: float,
        final_score: float,
    ):
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.document_name = document_name
        self.document_bucket = document_bucket
        self.chunk_text = chunk_text
        self.chunk_index = chunk_index
        self.page_number = page_number
        self.semantic_score = semantic_score
        self.keyword_score = keyword_score
        self.final_score = final_score


class HybridSearchService:
    """Service for hybrid semantic and keyword search"""

    def __init__(
        self,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        min_score_threshold: float = 0.1,
    ):
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight
        self.min_score_threshold = min_score_threshold

    def _get_user_bucket_filter(self, user: User) -> List[str]:
        """
        Get allowed buckets for user based on role.

        Role-Based Access Control (RBAC) - VIEW-ONLY access for search:

        ┌──────────────────────────────────────────────────────────────────────────────┐
        │ SEARCH ACCESS LEVELS (VIEW-ONLY - no upload/delete/modify permissions)       │
        ├──────────────────────────────────────────────────────────────────────────────┤
        │ ADMIN (full_access):              PUBLIC + CONFIDENTIAL buckets               │
        │ SUPERUSER (read_only_trusted):    PUBLIC + CONFIDENTIAL buckets               │
        │                                   ⚠️  VIEW-ONLY for confidential documents    │
        │                                   ⚠️  Can SEE but NOT upload/delete/modify    │
        │ USER (public_only):               PUBLIC bucket only                          │
        └──────────────────────────────────────────────────────────────────────────────┘

        IMPORTANT: SuperUser role has VIEW-ONLY access to confidential documents.
        - SuperUsers can SEARCH and READ confidential documents
        - SuperUsers CANNOT upload to confidential bucket
        - SuperUsers CANNOT delete or modify confidential documents
        - This is a search-specific permission; actual document operations are
          enforced separately in document_service.py

        Args:
            user: Current user requesting bucket filter

        Returns:
            List of allowed bucket values for search operations:
            - [DocumentBucket.PUBLIC.value, DocumentBucket.CONFIDENTIAL.value] for Admin/SuperUser
            - [DocumentBucket.PUBLIC.value] for regular Users
        """
        if user.role == UserRole.ADMIN:
            # Admins see all documents
            return [DocumentBucket.PUBLIC.value, DocumentBucket.CONFIDENTIAL.value]
        elif user.role == UserRole.SUPERUSER:
            # Super users see all documents (VIEW-ONLY for confidential)
            return [DocumentBucket.PUBLIC.value, DocumentBucket.CONFIDENTIAL.value]
        else:
            # Regular users only see public documents
            return [DocumentBucket.PUBLIC.value]

    async def semantic_search(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
        db: Session = None,
        user: User = None,
    ) -> List[SearchResult]:
        """
        Perform vector similarity search using pgvector.

        Returns an empty list when the embedding model is unavailable (backend
        container runs without sentence_transformers — heavy ML is exclusively
        in the celery-worker).  Hybrid search will fall back to keyword-only.

        Args:
            query: Search query text
            limit: Maximum number of results
            offset: Number of results to skip
            db: Database session
            user: Current user for access control

        Returns:
            List of search results
        """
        # Skip semantic search when model is unavailable (backend container)
        if not embedding_service.can_embed:
            logger.info(
                "Semantic search skipped: embedding model not loaded in this container "
                "(backend runs requirements-minimal.txt without sentence_transformers). "
                "Keyword-only results will be returned."
            )
            return []

        # Generate query embedding
        query_embedding = embedding_service.encode_single(query)
        embedding_array = ",".join(map(str, query_embedding))

        # Get user bucket filter
        bucket_filter = (
            self._get_user_bucket_filter(user)
            if user
            else [DocumentBucket.PUBLIC.value]
        )

        # Build SQL query for vector similarity using pgvector's cosine distance operator
        # Uses embedding_vector column for pgvector operations
        sql_query = text("""
            SELECT
                dc.id as chunk_id,
                dc.document_id,
                d.filename as document_name,
                d.bucket as document_bucket,
                dc.chunk_text,
                dc.chunk_index,
                dc.page_number,
                1 - (dc.embedding_vector <=> :embedding::vector) as similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.bucket = ANY(:buckets)
            AND dc.embedding_vector IS NOT NULL
            ORDER BY dc.embedding_vector <=> :embedding::vector
            LIMIT :limit OFFSET :offset
        """)

        result = db.execute(
            sql_query,
            {
                "embedding": embedding_array,
                "buckets": bucket_filter,
                "limit": limit,
                "offset": offset,
            },
        )

        search_results = []
        for row in result:
            search_results.append(
                SearchResult(
                    chunk_id=str(row.chunk_id),
                    document_id=str(row.document_id),
                    document_name=row.document_name,
                    document_bucket=row.document_bucket,
                    chunk_text=row.chunk_text,
                    chunk_index=row.chunk_index,
                    page_number=row.page_number,
                    semantic_score=float(row.similarity),
                    keyword_score=0.0,
                    final_score=float(row.similarity),  # Will be recalculated
                )
            )

        return search_results

    async def keyword_search(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
        db: Session = None,
        user: User = None,
    ) -> List[SearchResult]:
        """
        Perform keyword full-text search using PostgreSQL tsvector.

        Uses the GIN-indexed search_vector column with ts_rank_cd scoring and
        per-row language stemming.  Falls back to an empty list when
        search_vector has not been populated yet (e.g. before migration 009).

        Args:
            query: Search query text
            limit: Maximum number of results
            offset: Number of results to skip
            db: Database session
            user: Current user for access control

        Returns:
            List of search results ordered by ts_rank_cd descending
        """
        bucket_filter = (
            self._get_user_bucket_filter(user)
            if user
            else [DocumentBucket.PUBLIC.value]
        )

        # plainto_tsquery converts free-form text to a tsquery (automatic AND,
        # stemming, stop-word removal) — safe with parameterised input.
        # Using the per-row search_language regconfig ensures correct stemming
        # for each document's language (french, english, etc.).
        sql_query = text("""
            SELECT
                dc.id          AS chunk_id,
                dc.document_id,
                d.filename     AS document_name,
                d.bucket       AS document_bucket,
                dc.chunk_text,
                dc.chunk_index,
                dc.page_number,
                ts_rank_cd(
                    dc.search_vector,
                    plainto_tsquery(
                        COALESCE(dc.search_language, 'french')::regconfig,
                        :query
                    ),
                    32
                ) AS rank
            FROM sowknow.document_chunks dc
            JOIN sowknow.documents d ON dc.document_id = d.id
            WHERE d.bucket = ANY(:buckets)
              AND dc.search_vector IS NOT NULL
              AND dc.search_vector @@ plainto_tsquery(
                      COALESCE(dc.search_language, 'french')::regconfig,
                      :query
                  )
            ORDER BY rank DESC
            LIMIT :limit OFFSET :offset
        """)

        result = db.execute(
            sql_query,
            {
                "query": query,
                "buckets": bucket_filter,
                "limit": limit,
                "offset": offset,
            },
        )

        search_results = []
        for row in result:
            search_results.append(
                SearchResult(
                    chunk_id=str(row.chunk_id),
                    document_id=str(row.document_id),
                    document_name=row.document_name,
                    document_bucket=row.document_bucket,
                    chunk_text=row.chunk_text,
                    chunk_index=row.chunk_index,
                    page_number=row.page_number,
                    semantic_score=0.0,
                    keyword_score=float(row.rank),
                    final_score=float(
                        row.rank
                    ),  # Will be recalculated by hybrid_search
                )
            )

        return search_results

    async def hybrid_search(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
        db: Session = None,
        user: User = None,
        timeout: float = 3.0,
    ) -> Dict[str, Any]:
        """
        Perform hybrid search combining semantic and keyword results.

        Both sub-searches run concurrently.  If the overall wall-clock time
        exceeds ``timeout`` seconds any pending sub-search is cancelled and the
        result is marked ``partial=True`` with a human-readable ``warning``.

        Args:
            query: Search query text
            limit: Maximum number of results
            offset: Number of results to skip
            db: Database session
            user: Current user for access control
            timeout: Maximum seconds to wait before returning partial results

        Returns:
            Dictionary with results, metadata, and optional partial/warning flags
        """
        # Check for PII in query for privacy protection
        has_pii = pii_detection_service.detect_pii(query)
        pii_summary = None

        if has_pii:
            pii_summary = pii_detection_service.get_pii_summary(query)
            logger.warning(
                f"PII detected in search query by user {user.email if user else 'unknown'}: {pii_summary['detected_types']}"
            )

        # Run both searches concurrently; return partial results on timeout
        semantic_task = asyncio.create_task(
            self.semantic_search(
                query=query, limit=limit * 2, offset=0, db=db, user=user
            )
        )
        keyword_task = asyncio.create_task(
            self.keyword_search(
                query=query, limit=limit * 2, offset=0, db=db, user=user
            )
        )

        done, pending = await asyncio.wait(
            {semantic_task, keyword_task},
            timeout=timeout,
        )

        # Cancel any tasks that didn't finish in time
        for task in pending:
            task.cancel()

        is_partial = bool(pending)
        if is_partial:
            completed_names = [
                "semantic" if t is semantic_task else "keyword" for t in done
            ]
            missed_names = [
                "semantic" if t is semantic_task else "keyword" for t in pending
            ]
            logger.warning(
                f"Search timeout ({timeout}s): completed={completed_names}, "
                f"cancelled={missed_names}. Returning partial results."
            )

        semantic_results: List[SearchResult] = (
            semantic_task.result() if semantic_task in done else []
        )
        keyword_results: List[SearchResult] = (
            keyword_task.result() if keyword_task in done else []
        )

        # Merge results using RRF (Reciprocal Rank Fusion)
        merged_scores = {}

        # Add semantic scores (k=60)
        k = 60
        for rank, result in enumerate(semantic_results):
            score = 1 / (k + rank + 1)
            if result.chunk_id not in merged_scores:
                merged_scores[result.chunk_id] = {
                    "result": result,
                    "semantic_score": result.semantic_score,
                    "keyword_score": result.keyword_score,
                    "rrf_score": score,
                }
            else:
                merged_scores[result.chunk_id]["rrf_score"] += score
                merged_scores[result.chunk_id]["semantic_score"] = max(
                    merged_scores[result.chunk_id]["semantic_score"],
                    result.semantic_score,
                )

        # Add keyword scores (k=60)
        for rank, result in enumerate(keyword_results):
            score = 1 / (k + rank + 1)
            if result.chunk_id not in merged_scores:
                merged_scores[result.chunk_id] = {
                    "result": result,
                    "semantic_score": result.semantic_score,
                    "keyword_score": result.keyword_score,
                    "rrf_score": score,
                }
            else:
                merged_scores[result.chunk_id]["rrf_score"] += score
                merged_scores[result.chunk_id]["keyword_score"] = max(
                    merged_scores[result.chunk_id]["keyword_score"],
                    result.keyword_score,
                )

        # Calculate final scores
        for chunk_id, data in merged_scores.items():
            result = data["result"]
            semantic = data["semantic_score"]
            keyword = data["keyword_score"]

            # Combined score using weights
            final_score = (
                self.semantic_weight * semantic + self.keyword_weight * keyword
            )
            result.final_score = final_score

        # Sort by final score and apply pagination
        sorted_results = sorted(
            merged_scores.values(), key=lambda x: x["result"].final_score, reverse=True
        )

        paginated_results = sorted_results[offset : offset + limit]

        warning = (
            "Search timeout: results may be incomplete (partial keyword and/or "
            "semantic results returned)"
            if is_partial
            else None
        )

        return {
            "query": query,
            "results": [item["result"] for item in paginated_results],
            "total": len(sorted_results),
            "offset": offset,
            "limit": limit,
            "has_pii": has_pii,
            "pii_summary": pii_summary,
            "partial": is_partial,
            "warning": warning,
        }


    # ──────────────────────────────────────────────────────────────────────
    # ORM-style helper methods for tsvector full-text search
    # These companion methods expose the same full-text search logic via
    # SQLAlchemy ORM expressions instead of raw SQL strings.
    # ──────────────────────────────────────────────────────────────────────

    def _sanitize_tsquery(self, query: str) -> str:
        """Strip characters that have special meaning in tsquery syntax.

        Removes: & | ! ( ) < > :
        Returns a cleaned, whitespace-normalised string safe to pass to
        plainto_tsquery / phraseto_tsquery.
        """
        sanitized = re.sub(r"[&|!()<>:]+", " ", query).strip()
        return " ".join(sanitized.split())

    def _keyword_search(
        self,
        query: str,
        db: Session,
        user: User,
        limit: int = 50,
        language: str = "french",
    ) -> List:
        """ORM-style tsvector keyword search.

        Applies RBAC bucket filtering and a visibility filter: 'public'
        documents are always accessible; confidential documents require
        elevated role.

        Note: for multi-tenant deployments add a filter for
        organization_id == user.organization_id to scope results.

        Args:
            query:    Raw search string (will be sanitized).
            db:       Active SQLAlchemy session.
            user:     Authenticated user for RBAC filtering.
            limit:    Maximum rows to return.
            language: Default text-search config (per-row config is preferred).

        Returns:
            List of (DocumentChunk, Document, rank) tuples ordered by rank DESC.
        """
        sanitized_query = self._sanitize_tsquery(query)
        if not sanitized_query:
            return []

        tsquery = func.plainto_tsquery(language, sanitized_query)

        rank_expr = func.ts_rank_cd(
            DocumentChunk.search_vector,
            tsquery,
            32  # normalization: divide rank by document length + unique words
        )

        # visibility filter: 'public' bucket for Users; all buckets for Admin/SuperUser
        # TODO: add organization_id == user.organization_id filter for multi-tenant
        buckets = (
            self._get_user_bucket_filter(user)
            if user
            else [DocumentBucket.PUBLIC.value]
        )

        return (
            db.query(DocumentChunk, Document, rank_expr.label("rank"))
            .join(Document, DocumentChunk.document_id == Document.id)
            .filter(Document.bucket.in_(buckets))
            .filter(DocumentChunk.search_vector.op("@@")(tsquery))
            .order_by(desc(rank_expr))
            .limit(limit)
            .all()
        )

    def _keyword_search_with_metadata(
        self,
        query: str,
        db: Session,
        user: User,
        limit: int = 50,
        language: str = "french",
    ) -> List:
        """Keyword search across both chunk_text and JSONB metadata fields.

        Uses func.greatest to combine the tsvector rank from the chunk body and
        the tsvector rank derived from title/source metadata, returning the
        highest of the two scores per row.

        Args:
            query:    Raw search string.
            db:       Active SQLAlchemy session.
            user:     Authenticated user for RBAC filtering.
            limit:    Maximum rows to return.
            language: Default text-search config.

        Returns:
            List of (DocumentChunk, Document, combined_rank) tuples.
        """
        sanitized_query = self._sanitize_tsquery(query)
        if not sanitized_query:
            return []

        tsquery = func.plainto_tsquery(language, sanitized_query)

        text_rank = func.ts_rank_cd(
            DocumentChunk.search_vector,
            tsquery,
            32  # normalization flag
        )
        meta_rank = func.ts_rank_cd(
            func.to_tsvector(
                language,
                func.coalesce(
                    DocumentChunk.document_metadata["title"].astext, ""
                )
                + " "
                + func.coalesce(
                    DocumentChunk.document_metadata["source"].astext, ""
                ),
            ),
            tsquery,
        )
        combined_rank = func.greatest(text_rank, meta_rank)

        buckets = (
            self._get_user_bucket_filter(user)
            if user
            else [DocumentBucket.PUBLIC.value]
        )

        return (
            db.query(DocumentChunk, Document, combined_rank.label("rank"))
            .join(Document, DocumentChunk.document_id == Document.id)
            .filter(Document.bucket.in_(buckets))
            .filter(DocumentChunk.search_vector.op("@@")(tsquery))
            .order_by(desc(combined_rank))
            .limit(limit)
            .all()
        )

    def _get_highlighted_text(
        self,
        db: Session,
        chunk_text: str,
        query: str,
        language: str = "french",
    ) -> str:
        """Return an HTML snippet with query terms wrapped in <mark> tags.

        Uses PostgreSQL ts_headline with custom StartSel=<mark> / StopSel=</mark>
        to produce browser-renderable highlights.

        Args:
            db:         Active SQLAlchemy session.
            chunk_text: Raw text to highlight.
            query:      Search query string.
            language:   PostgreSQL text-search configuration name.

        Returns:
            HTML string with matching terms highlighted; falls back to raw
            chunk_text if ts_headline fails.
        """
        try:
            result = db.execute(
                text(
                    """
                    SELECT ts_headline(
                        :lang::regconfig,
                        :content,
                        plainto_tsquery(:lang::regconfig, :query),
                        'StartSel=<mark>, StopSel=</mark>, MaxWords=35, MinWords=15'
                    )
                    """
                ),
                {"lang": language, "content": chunk_text, "query": query},
            ).scalar()
            return result or chunk_text
        except Exception:
            return chunk_text


# Global search service instance
search_service = HybridSearchService()
