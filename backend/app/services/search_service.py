"""
Hybrid search service combining vector and keyword search
"""

import asyncio
import logging
import re
from typing import Any

from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentBucket, DocumentChunk
from app.models.user import User, UserRole
from app.services.embed_client import embedding_service
from app.services.pii_detection_service import pii_detection_service
from app.services.rerank_service import rerank_passages
from app.services.search_cache import SearchCache

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
        page_number: int | None,
        semantic_score: float,
        keyword_score: float,
        final_score: float,
        result_type: str = "chunk",
        article_id: str | None = None,
        article_title: str | None = None,
        article_summary: str | None = None,
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
        self.result_type = result_type
        self.article_id = article_id
        self.article_title = article_title
        self.article_summary = article_summary


LANGUAGE_MAP = {
    "fr": "french",
    "en": "english",
    "de": "german",
    "es": "spanish",
    "it": "italian",
}


def _get_regconfig(language_code: str | None) -> str:
    """Map a language code to a PostgreSQL text-search config."""
    if not language_code:
        return "simple"
    return LANGUAGE_MAP.get(language_code.lower(), "simple")


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

    def _get_user_bucket_filter(self, user: User) -> list[str]:
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
        db: AsyncSession = None,
        user: User = None,
    ) -> list[SearchResult]:
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

        # Generate query embedding (with cache)
        cached_embedding = SearchCache.get_embedding(query)
        if cached_embedding is not None:
            query_embedding = cached_embedding
        else:
            query_embedding = embedding_service.encode_query(query)
            SearchCache.set_embedding(query, query_embedding)
        embedding_array = ",".join(map(str, query_embedding))

        # Get user bucket filter
        bucket_filter = self._get_user_bucket_filter(user) if user else [DocumentBucket.PUBLIC.value]

        # Build SQL query for vector similarity using pgvector's cosine distance operator
        # Uses embedding_vector column for pgvector operations
        sql_query = text("""
            SELECT
                dc.id as chunk_id,
                dc.document_id,
                COALESCE(d.original_filename, d.filename) as document_name,
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

        result = await db.execute(
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
        db: AsyncSession = None,
        user: User = None,
        regconfig: str = "simple",
    ) -> list[SearchResult]:
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
            regconfig: PostgreSQL text-search config (e.g. 'english', 'french', 'simple')

        Returns:
            List of search results ordered by ts_rank_cd descending
        """
        bucket_filter = self._get_user_bucket_filter(user) if user else [DocumentBucket.PUBLIC.value]

        # plainto_tsquery converts free-form text to a tsquery (automatic AND,
        # stemming, stop-word removal) — safe with parameterised input.
        # regconfig is now passed from the caller based on detected query language.
        sql_query = text("""
            SELECT
                dc.id          AS chunk_id,
                dc.document_id,
                COALESCE(d.original_filename, d.filename) AS document_name,
                d.bucket       AS document_bucket,
                dc.chunk_text,
                dc.chunk_index,
                dc.page_number,
                ts_rank_cd(
                    dc.search_vector,
                    plainto_tsquery(
                        :regconfig::regconfig,
                        :query
                    ),
                    32
                ) AS rank
            FROM sowknow.document_chunks dc
            JOIN sowknow.documents d ON dc.document_id = d.id
            WHERE d.bucket = ANY(:buckets)
              AND dc.search_vector IS NOT NULL
              AND dc.search_vector @@ plainto_tsquery(
                      :regconfig::regconfig,
                      :query
                  )
            ORDER BY rank DESC
            LIMIT :limit OFFSET :offset
        """)

        result = await db.execute(
            sql_query,
            {
                "query": query,
                "regconfig": regconfig,
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
                    final_score=float(row.rank),  # Will be recalculated by hybrid_search
                )
            )

        # Fallback: trigram similarity for typos when tsvector returns <3 results
        if len(search_results) < 3 and len(query.strip()) >= 2:
            fallback = await self._trigram_fallback_search(
                query=query, limit=limit, db=db, user=user
            )
            seen = {r.chunk_id for r in search_results}
            for r in fallback:
                if r.chunk_id not in seen:
                    search_results.append(r)

        return search_results

    async def tag_search(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
        db: AsyncSession = None,
        user: User = None,
    ) -> list[SearchResult]:
        """
        Search for documents by tag name.

        Matches documents that have a tag containing the query string
        (case-insensitive partial match on tag_name).

        Args:
            query: Tag search string (e.g., "doa", "finance", "medical")
            limit: Maximum number of results
            offset: Number of results to skip
            db: Database session
            user: Current user for access control

        Returns:
            List of search results for documents with matching tags
        """
        if not query or len(query.strip()) < 2:
            return []

        bucket_filter = self._get_user_bucket_filter(user) if user else [DocumentBucket.PUBLIC.value]

        sql_query = text("""
            SELECT DISTINCT
                d.id as doc_id,
                d.id as document_id,
                COALESCE(d.original_filename, d.filename) AS document_name,
                d.bucket AS document_bucket,
                d.page_count,
                t.tag_name,
                t.tag_type,
                1.0 AS similarity
            FROM sowknow.documents d
            JOIN sowknow.tags t ON d.id = t.target_id AND t.target_type = 'document'
            WHERE d.bucket = ANY(:buckets)
              AND d.status != 'error'
              AND LOWER(t.tag_name) LIKE LOWER(:query_pattern)
            ORDER BY t.tag_type, t.tag_name
            LIMIT :limit OFFSET :offset
        """)

        result = await db.execute(
            sql_query,
            {
                "query_pattern": f"%{query}%",
                "buckets": bucket_filter,
                "limit": limit,
                "offset": offset,
            },
        )

        search_results = []
        for row in result:
            search_results.append(
                SearchResult(
                    chunk_id=str(row.doc_id),
                    document_id=str(row.document_id),
                    document_name=row.document_name,
                    document_bucket=row.document_bucket,
                    chunk_text=f"[Tag: {row.tag_name} (type: {row.tag_type})]",
                    chunk_index=0,
                    page_number=row.page_count,
                    semantic_score=float(row.similarity),
                    keyword_score=float(row.similarity),
                    final_score=float(row.similarity),
                    result_type="tag_match",
                )
            )

        return search_results

    async def article_semantic_search(
        self,
        query: str,
        limit: int = 30,
        db: AsyncSession = None,
        user: User = None,
    ) -> list[SearchResult]:
        """Semantic search over articles using pgvector."""
        if not embedding_service.can_embed:
            return []

        query_embedding = embedding_service.encode_query(query)
        embedding_array = ",".join(map(str, query_embedding))
        bucket_filter = self._get_user_bucket_filter(user) if user else [DocumentBucket.PUBLIC.value]

        sql_query = text("""
            SELECT
                a.id as article_id,
                a.document_id,
                COALESCE(d.original_filename, d.filename) as document_name,
                a.bucket as document_bucket,
                a.title,
                a.summary,
                a.body,
                1 - (a.embedding_vector <=> :embedding::vector) as similarity
            FROM sowknow.articles a
            JOIN sowknow.documents d ON a.document_id = d.id
            WHERE a.bucket = ANY(:buckets)
            AND a.embedding_vector IS NOT NULL
            AND a.status = 'indexed'
            ORDER BY a.embedding_vector <=> :embedding::vector
            LIMIT :limit
        """)

        result = await db.execute(
            sql_query,
            {
                "embedding": embedding_array,
                "buckets": bucket_filter,
                "limit": limit,
            },
        )

        return [
            SearchResult(
                chunk_id=str(row.article_id),
                document_id=str(row.document_id),
                document_name=row.document_name,
                document_bucket=row.document_bucket,
                chunk_text=row.body,
                chunk_index=0,
                page_number=None,
                semantic_score=float(row.similarity),
                keyword_score=0.0,
                final_score=float(row.similarity),
                result_type="article",
                article_id=str(row.article_id),
                article_title=row.title,
                article_summary=row.summary,
            )
            for row in result
        ]

    async def _trigram_fallback_search(
        self,
        query: str,
        limit: int = 50,
        db: AsyncSession = None,
        user: User = None,
    ) -> list[SearchResult]:
        """
        Fallback keyword search using pg_trgm similarity for typo tolerance.
        Only called when standard tsvector search returns very few results.
        """
        bucket_filter = self._get_user_bucket_filter(user) if user else [DocumentBucket.PUBLIC.value]

        sql_query = text("""
            SELECT
                dc.id as chunk_id,
                dc.document_id,
                COALESCE(d.original_filename, d.filename) as document_name,
                d.bucket as document_bucket,
                dc.chunk_text,
                dc.chunk_index,
                dc.page_number,
                GREATEST(
                    similarity(COALESCE(d.original_filename, d.filename), :query),
                    similarity(COALESCE(d.title, ''), :query),
                    similarity(dc.chunk_text, :query)
                ) as rank
            FROM sowknow.document_chunks dc
            JOIN sowknow.documents d ON dc.document_id = d.id
            WHERE d.bucket = ANY(:buckets)
              AND dc.search_vector IS NOT NULL
              AND (
                  COALESCE(d.original_filename, d.filename) % :query
                  OR COALESCE(d.title, '') % :query
                  OR dc.chunk_text % :query
              )
            ORDER BY rank DESC
            LIMIT :limit
        """)

        result = await db.execute(
            sql_query,
            {
                "query": query,
                "buckets": bucket_filter,
                "limit": limit,
            },
        )

        return [
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
                final_score=float(row.rank),
            )
            for row in result
        ]

    async def article_keyword_search(
        self,
        query: str,
        limit: int = 30,
        db: AsyncSession = None,
        user: User = None,
        regconfig: str = "simple",
    ) -> list[SearchResult]:
        """Full-text search over articles using tsvector."""
        bucket_filter = self._get_user_bucket_filter(user) if user else [DocumentBucket.PUBLIC.value]

        sql_query = text("""
            SELECT
                a.id as article_id,
                a.document_id,
                COALESCE(d.original_filename, d.filename) as document_name,
                a.bucket as document_bucket,
                a.title,
                a.summary,
                a.body,
                ts_rank_cd(
                    a.search_vector,
                    plainto_tsquery(
                        :regconfig::regconfig,
                        :query
                    ),
                    32
                ) AS rank
            FROM sowknow.articles a
            JOIN sowknow.documents d ON a.document_id = d.id
            WHERE a.bucket = ANY(:buckets)
              AND a.search_vector IS NOT NULL
              AND a.search_vector @@ plainto_tsquery(
                      :regconfig::regconfig,
                      :query
                  )
            ORDER BY rank DESC
            LIMIT :limit
        """)

        result = await db.execute(
            sql_query,
            {
                "query": query,
                "regconfig": regconfig,
                "buckets": bucket_filter,
                "limit": limit,
            },
        )

        return [
            SearchResult(
                chunk_id=str(row.article_id),
                document_id=str(row.document_id),
                document_name=row.document_name,
                document_bucket=row.document_bucket,
                chunk_text=row.body,
                chunk_index=0,
                page_number=None,
                semantic_score=0.0,
                keyword_score=float(row.rank),
                final_score=float(row.rank),
                result_type="article",
                article_id=str(row.article_id),
                article_title=row.title,
                article_summary=row.summary,
            )
            for row in result
        ]

    async def hybrid_search(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
        db: AsyncSession = None,
        user: User = None,
        timeout: float = 8.0,
        regconfig: str = "simple",
        rerank: bool = True,
    ) -> dict[str, Any]:
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

        # Run chunk + article + tag searches concurrently; return partial results on timeout
        semantic_task = asyncio.create_task(
            self.semantic_search(query=query, limit=limit * 2, offset=0, db=db, user=user)
        )
        keyword_task = asyncio.create_task(
            self.keyword_search(query=query, limit=limit * 2, offset=0, db=db, user=user, regconfig=regconfig)
        )
        article_semantic_task = asyncio.create_task(
            self.article_semantic_search(query=query, limit=limit, db=db, user=user)
        )
        article_keyword_task = asyncio.create_task(
            self.article_keyword_search(query=query, limit=limit, db=db, user=user, regconfig=regconfig)
        )
        tag_task = asyncio.create_task(self.tag_search(query=query, limit=limit, offset=0, db=db, user=user))

        done, pending = await asyncio.wait(
            {semantic_task, keyword_task, article_semantic_task, article_keyword_task, tag_task},
            timeout=timeout,
        )

        # Cancel any tasks that didn't finish in time
        for task in pending:
            task.cancel()

        def _task_name(task: asyncio.Task) -> str:
            if task is semantic_task:
                return "semantic"
            if task is keyword_task:
                return "keyword"
            if task is article_semantic_task:
                return "article_semantic"
            if task is article_keyword_task:
                return "article_keyword"
            if task is tag_task:
                return "tag"
            return "unknown"

        def _safe_result(task: asyncio.Task) -> list[SearchResult]:
            if task not in done:
                return []
            try:
                return task.result()
            except Exception as exc:
                logger.warning("Search sub-task %s failed: %s", _task_name(task), exc)
                return []

        is_partial = bool(pending)
        if is_partial:
            completed_names = [_task_name(t) for t in done]
            missed_names = [_task_name(t) for t in pending]
            logger.warning(
                "Search timeout (%ss): completed=%s, cancelled=%s. Returning partial results.",
                timeout, completed_names, missed_names,
            )

        semantic_results: list[SearchResult] = _safe_result(semantic_task)
        keyword_results: list[SearchResult] = _safe_result(keyword_task)
        article_sem_results: list[SearchResult] = _safe_result(article_semantic_task)
        article_kw_results: list[SearchResult] = _safe_result(article_keyword_task)
        tag_results: list[SearchResult] = _safe_result(tag_task)

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

        # Add article results with 1.2x boost (articles are more coherent than raw chunks)
        article_boost = 1.2
        for rank, result in enumerate(article_sem_results):
            key = f"article:{result.article_id}"
            score = article_boost / (k + rank + 1)
            if key not in merged_scores:
                merged_scores[key] = {
                    "result": result,
                    "semantic_score": result.semantic_score,
                    "keyword_score": 0.0,
                    "rrf_score": score,
                }
            else:
                merged_scores[key]["rrf_score"] += score
                merged_scores[key]["semantic_score"] = max(
                    merged_scores[key]["semantic_score"],
                    result.semantic_score,
                )

        for rank, result in enumerate(article_kw_results):
            key = f"article:{result.article_id}"
            score = article_boost / (k + rank + 1)
            if key not in merged_scores:
                merged_scores[key] = {
                    "result": result,
                    "semantic_score": 0.0,
                    "keyword_score": result.keyword_score,
                    "rrf_score": score,
                }
            else:
                merged_scores[key]["rrf_score"] += score
                merged_scores[key]["keyword_score"] = max(
                    merged_scores[key]["keyword_score"],
                    result.keyword_score,
                )

        # Add tag match results with 1.5x boost (tag matches are highly relevant)
        tag_boost = 1.5
        for rank, result in enumerate(tag_results):
            key = f"tag:{result.document_id}"
            score = tag_boost / (k + rank + 1)
            if key not in merged_scores:
                merged_scores[key] = {
                    "result": result,
                    "semantic_score": result.semantic_score,
                    "keyword_score": result.keyword_score,
                    "rrf_score": score,
                }
            else:
                merged_scores[key]["rrf_score"] += score
                merged_scores[key]["semantic_score"] = max(
                    merged_scores[key]["semantic_score"],
                    result.semantic_score,
                )
                merged_scores[key]["keyword_score"] = max(
                    merged_scores[key]["keyword_score"],
                    result.keyword_score,
                )

        # Adaptive weights: short queries (<=3 words) benefit more from keyword match
        word_count = len(query.split())
        if word_count <= 3:
            sem_w, kw_w = 0.4, 0.6
        else:
            sem_w, kw_w = self.semantic_weight, self.keyword_weight

        # Dynamic minimum threshold: stricter for short queries
        if word_count <= 3:
            min_threshold = max(self.min_score_threshold, 0.25)
        else:
            min_threshold = max(self.min_score_threshold, 0.15)

        # Calculate final scores
        for _chunk_id, data in merged_scores.items():
            result = data["result"]
            semantic = data["semantic_score"]
            keyword = data["keyword_score"]

            # Combined score using weights
            final_score = sem_w * semantic + kw_w * keyword
            result.final_score = final_score

        # Cross-encoder re-ranking on top candidates (optional, graceful fallback)
        if rerank and len(merged_scores) > 1:
            try:
                top_items = sorted(
                    merged_scores.items(),
                    key=lambda x: x[1]["result"].final_score,
                    reverse=True,
                )[:50]
                passages = [item[1]["result"].chunk_text for item in top_items]
                rerank_scores = await rerank_passages(query, passages)
                if rerank_scores:
                    for idx, score in rerank_scores:
                        key = top_items[idx][0]
                        # Blend RRF score with cross-encoder score
                        old_score = merged_scores[key]["result"].final_score
                        merged_scores[key]["result"].final_score = 0.7 * old_score + 0.3 * score
            except Exception as exc:
                logger.debug("Re-ranking skipped: %s", exc)

        # Filter out low-relevance results
        filtered = {k: v for k, v in merged_scores.items() if v["result"].final_score >= min_threshold}

        # Sort by final score and apply pagination
        sorted_results = sorted(filtered.values(), key=lambda x: x["result"].final_score, reverse=True)

        paginated_results = sorted_results[offset : offset + limit]

        warning = (
            "Search timeout: results may be incomplete (partial keyword and/or semantic results returned)"
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

    async def _keyword_search(
        self,
        query: str,
        db: AsyncSession,
        user: User,
        limit: int = 50,
        regconfig: str = "simple",
    ) -> list:
        """ORM-style tsvector keyword search.

        Applies RBAC bucket filtering and a visibility filter: 'public'
        documents are always accessible; confidential documents require
        elevated role.

        Note: for multi-tenant deployments add a filter for
        organization_id == user.organization_id to scope results.

        Args:
            query:     Raw search string (will be sanitized).
            db:        Active SQLAlchemy async session.
            user:      Authenticated user for RBAC filtering.
            limit:     Maximum rows to return.
            regconfig: PostgreSQL text-search config (e.g. 'english', 'simple').

        Returns:
            List of (DocumentChunk, Document, rank) tuples ordered by rank DESC.
        """
        sanitized_query = self._sanitize_tsquery(query)
        if not sanitized_query:
            return []

        tsquery = func.plainto_tsquery(regconfig, sanitized_query)

        rank_expr = func.ts_rank_cd(
            DocumentChunk.search_vector,
            tsquery,
            32,  # normalization: divide rank by document length + unique words
        )

        # visibility filter: 'public' bucket for Users; all buckets for Admin/SuperUser
        # TODO: add organization_id == user.organization_id filter for multi-tenant
        buckets = self._get_user_bucket_filter(user) if user else [DocumentBucket.PUBLIC.value]

        stmt = (
            select(DocumentChunk, Document, rank_expr.label("rank"))
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.bucket.in_(buckets))
            .where(DocumentChunk.search_vector.op("@@")(tsquery))
            .order_by(desc(rank_expr))
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.all()

    async def _keyword_search_with_metadata(
        self,
        query: str,
        db: AsyncSession,
        user: User,
        limit: int = 50,
        regconfig: str = "simple",
    ) -> list:
        """Keyword search across both chunk_text and JSONB metadata fields.

        Uses func.greatest to combine the tsvector rank from the chunk body and
        the tsvector rank derived from title/source metadata, returning the
        highest of the two scores per row.

        Args:
            query:     Raw search string.
            db:        Active SQLAlchemy async session.
            user:      Authenticated user for RBAC filtering.
            limit:     Maximum rows to return.
            regconfig: PostgreSQL text-search config.

        Returns:
            List of (DocumentChunk, Document, combined_rank) tuples.
        """
        sanitized_query = self._sanitize_tsquery(query)
        if not sanitized_query:
            return []

        tsquery = func.plainto_tsquery(regconfig, sanitized_query)

        text_rank = func.ts_rank_cd(
            DocumentChunk.search_vector,
            tsquery,
            32,  # normalization flag
        )
        meta_rank = func.ts_rank_cd(
            func.to_tsvector(
                regconfig,
                func.coalesce(DocumentChunk.document_metadata["title"].astext, "")
                + " "
                + func.coalesce(DocumentChunk.document_metadata["source"].astext, ""),
            ),
            tsquery,
        )
        combined_rank = func.greatest(text_rank, meta_rank)

        buckets = self._get_user_bucket_filter(user) if user else [DocumentBucket.PUBLIC.value]

        stmt = (
            select(DocumentChunk, Document, combined_rank.label("rank"))
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.bucket.in_(buckets))
            .where(DocumentChunk.search_vector.op("@@")(tsquery))
            .order_by(desc(combined_rank))
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.all()

    async def _get_highlighted_text(
        self,
        db: AsyncSession,
        chunk_text: str,
        query: str,
        language: str = "french",
    ) -> str:
        """Return an HTML snippet with query terms wrapped in <mark> tags.

        Uses PostgreSQL ts_headline with custom StartSel=<mark> / StopSel=</mark>
        to produce browser-renderable highlights.

        Args:
            db:         Active SQLAlchemy async session.
            chunk_text: Raw text to highlight.
            query:      Search query string.
            language:   PostgreSQL text-search configuration name.

        Returns:
            HTML string with matching terms highlighted; falls back to raw
            chunk_text if ts_headline fails.
        """
        try:
            result = await db.execute(
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
            )
            return result.scalar() or chunk_text
        except Exception:
            return chunk_text


    # ──────────────────────────────────────────────────────────────────────
    # Multi-type global search (documents + bookmarks + notes + spaces)
    # ──────────────────────────────────────────────────────────────────────

    def _get_bucket_filter_for_role(self, user: User | None) -> list[str]:
        """Return allowed bucket values based on user role."""
        if not user:
            return ["public"]
        if user.role in (UserRole.ADMIN, UserRole.SUPERUSER):
            return ["public", "confidential"]
        return ["public"]

    async def _search_bookmarks(
        self,
        query: str,
        user: User,
        db: AsyncSession,
        limit: int = 20,
    ) -> list[dict]:
        """ILIKE search on bookmarks (title, description, url) + tag name match."""
        buckets = self._get_bucket_filter_for_role(user)
        pattern = f"%{query}%"

        sql = text("""
            SELECT DISTINCT b.id, b.title, b.description, b.url, b.bucket,
                   b.created_at
            FROM sowknow.bookmarks b
            WHERE b.user_id = :user_id
              AND b.bucket = ANY(:buckets)
              AND (
                  b.title ILIKE :pattern
                  OR b.description ILIKE :pattern
                  OR b.url ILIKE :pattern
                  OR EXISTS (
                      SELECT 1 FROM sowknow.tags t
                      WHERE t.target_type = 'bookmark'
                        AND t.target_id = b.id
                        AND t.tag_name ILIKE :pattern
                  )
              )
            ORDER BY b.created_at DESC
            LIMIT :limit
        """)

        rows = await db.execute(sql, {
            "user_id": str(user.id),
            "buckets": buckets,
            "pattern": pattern,
            "limit": limit,
        })

        results = []
        for row in rows:
            # Fetch tags for this bookmark
            tag_rows = await db.execute(
                text("SELECT tag_name FROM sowknow.tags WHERE target_type = 'bookmark' AND target_id = :tid"),
                {"tid": str(row.id)},
            )
            tags = [tr.tag_name for tr in tag_rows]

            results.append({
                "result_type": "bookmark",
                "id": str(row.id),
                "title": row.title,
                "description": (row.description or row.url or "")[:200],
                "tags": tags,
                "score": 0.8,
                "bucket": row.bucket,
                "url": row.url,
            })
        return results

    async def _search_notes(
        self,
        query: str,
        user: User,
        db: AsyncSession,
        limit: int = 20,
    ) -> list[dict]:
        """ILIKE search on notes (title, content) + tag name match."""
        buckets = self._get_bucket_filter_for_role(user)
        pattern = f"%{query}%"

        sql = text("""
            SELECT DISTINCT n.id, n.title, n.content, n.bucket, n.created_at
            FROM sowknow.notes n
            WHERE n.user_id = :user_id
              AND n.bucket = ANY(:buckets)
              AND (
                  n.title ILIKE :pattern
                  OR n.content ILIKE :pattern
                  OR EXISTS (
                      SELECT 1 FROM sowknow.tags t
                      WHERE t.target_type = 'note'
                        AND t.target_id = n.id
                        AND t.tag_name ILIKE :pattern
                  )
              )
            ORDER BY n.created_at DESC
            LIMIT :limit
        """)

        rows = await db.execute(sql, {
            "user_id": str(user.id),
            "buckets": buckets,
            "pattern": pattern,
            "limit": limit,
        })

        results = []
        for row in rows:
            tag_rows = await db.execute(
                text("SELECT tag_name FROM sowknow.tags WHERE target_type = 'note' AND target_id = :tid"),
                {"tid": str(row.id)},
            )
            tags = [tr.tag_name for tr in tag_rows]

            results.append({
                "result_type": "note",
                "id": str(row.id),
                "title": row.title,
                "description": (row.content or "")[:200],
                "tags": tags,
                "score": 0.8,
                "bucket": row.bucket,
            })
        return results

    async def _search_spaces(
        self,
        query: str,
        user: User,
        db: AsyncSession,
        limit: int = 20,
    ) -> list[dict]:
        """ILIKE search on spaces (name, description)."""
        buckets = self._get_bucket_filter_for_role(user)
        pattern = f"%{query}%"

        sql = text("""
            SELECT s.id, s.name, s.description, s.icon, s.bucket, s.created_at
            FROM sowknow.spaces s
            WHERE s.user_id = :user_id
              AND s.bucket = ANY(:buckets)
              AND (
                  s.name ILIKE :pattern
                  OR s.description ILIKE :pattern
              )
            ORDER BY s.created_at DESC
            LIMIT :limit
        """)

        rows = await db.execute(sql, {
            "user_id": str(user.id),
            "buckets": buckets,
            "pattern": pattern,
            "limit": limit,
        })

        results = []
        for row in rows:
            results.append({
                "result_type": "space",
                "id": str(row.id),
                "title": row.name,
                "description": (row.description or "")[:200],
                "tags": [],
                "score": 0.7,
                "bucket": row.bucket,
                "icon": row.icon,
            })
        return results

    async def search_all_types(
        self,
        query: str,
        types: list[str] | None = None,
        user: User = None,
        db: AsyncSession = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """
        Multi-type search across documents, bookmarks, notes, and spaces.

        Args:
            query: Search query text
            types: List of types to search (default: all). Values: document, bookmark, note, space
            user: Current user for access control
            db: Database session
            page: Page number (1-based)
            page_size: Results per page

        Returns:
            Dictionary with results grouped by type, total counts, and pagination info
        """
        if not types:
            types = ["document", "bookmark", "note", "space"]

        all_results: list[dict] = []
        tasks = []

        # Document search uses existing hybrid search
        if "document" in types:
            tasks.append(("document", self._search_documents_simple(query, user, db, page_size)))

        if "bookmark" in types:
            tasks.append(("bookmark", self._search_bookmarks(query, user, db, page_size)))

        if "note" in types:
            tasks.append(("note", self._search_notes(query, user, db, page_size)))

        if "space" in types:
            tasks.append(("space", self._search_spaces(query, user, db, page_size)))

        # Run all searches concurrently
        if tasks:
            coros = [t[1] for t in tasks]
            results = await asyncio.gather(*coros, return_exceptions=True)
            for (type_name, _), result in zip(tasks, results, strict=False):
                if isinstance(result, Exception):
                    logger.warning("search_all_types: %s search failed: %s", type_name, result)
                    continue
                all_results.extend(result)

        # Sort by score descending
        all_results.sort(key=lambda r: r.get("score", 0), reverse=True)

        # Paginate
        offset = (page - 1) * page_size
        paginated = all_results[offset : offset + page_size]

        return {
            "query": query,
            "results": paginated,
            "total": len(all_results),
            "page": page,
            "page_size": page_size,
            "types_searched": types,
        }

    async def _search_documents_simple(
        self,
        query: str,
        user: User,
        db: AsyncSession,
        limit: int = 20,
    ) -> list[dict]:
        """Convert hybrid search results to the unified dict format."""
        try:
            hybrid_result = await self.hybrid_search(
                query=query, limit=limit, offset=0, db=db, user=user, timeout=5.0,
            )
        except Exception as e:
            logger.warning("Document search failed in search_all_types: %s", e)
            return []

        results = []
        seen_docs: set[str] = set()
        for sr in hybrid_result.get("results", []):
            doc_id = str(sr.document_id)
            if doc_id in seen_docs:
                continue
            seen_docs.add(doc_id)
            results.append({
                "result_type": "document",
                "id": doc_id,
                "title": sr.document_name,
                "description": (sr.chunk_text or "")[:200],
                "tags": [],
                "score": sr.final_score,
                "bucket": sr.document_bucket,
            })
        return results


# Global search service instance
search_service = HybridSearchService()
