"""
Hybrid search service combining vector and keyword search
"""
import logging
from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import text, func, or_, and_

from app.models.document import Document, DocumentChunk, DocumentBucket
from app.models.user import User, UserRole
from app.services.embedding_service import embedding_service

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
        final_score: float
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
        min_score_threshold: float = 0.1
    ):
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight
        self.min_score_threshold = min_score_threshold

    def _get_user_bucket_filter(self, user: User) -> List[str]:
        """
        Get allowed buckets for user based on role

        Args:
            user: Current user

        Returns:
            List of allowed bucket values
        """
        if user.role == UserRole.ADMIN:
            # Admins see all documents
            return [DocumentBucket.PUBLIC.value, DocumentBucket.CONFIDENTIAL.value]
        elif user.role == UserRole.SUPERUSER:
            # Super users see all documents
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
        user: User = None
    ) -> List[SearchResult]:
        """
        Perform vector similarity search using pgvector

        Args:
            query: Search query text
            limit: Maximum number of results
            offset: Number of results to skip
            db: Database session
            user: Current user for access control

        Returns:
            List of search results
        """
        # Generate query embedding
        query_embedding = embedding_service.encode_single(query)
        embedding_array = ",".join(map(str, query_embedding))

        # Get user bucket filter
        bucket_filter = self._get_user_bucket_filter(user) if user else [DocumentBucket.PUBLIC.value]

        # Build SQL query for vector similarity
        sql_query = text("""
            SELECT
                dc.id as chunk_id,
                dc.document_id,
                d.filename as document_name,
                d.bucket as document_bucket,
                dc.chunk_text,
                dc.chunk_index,
                dc.page_number,
                1 - (dc.embedding <=> :embedding::vector) as similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.bucket = ANY(:buckets)
            ORDER BY dc.embedding <=> :embedding::vector
            LIMIT :limit OFFSET :offset
        """)

        result = db.execute(
            sql_query,
            {
                "embedding": embedding_array,
                "buckets": bucket_filter,
                "limit": limit,
                "offset": offset
            }
        )

        search_results = []
        for row in result:
            search_results.append(SearchResult(
                chunk_id=str(row.chunk_id),
                document_id=str(row.document_id),
                document_name=row.document_name,
                document_bucket=row.document_bucket,
                chunk_text=row.chunk_text,
                chunk_index=row.chunk_index,
                page_number=row.page_number,
                semantic_score=float(row.similarity),
                keyword_score=0.0,
                final_score=float(row.similarity)  # Will be recalculated
            ))

        return search_results

    async def keyword_search(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
        db: Session = None,
        user: User = None
    ) -> List[SearchResult]:
        """
        Perform keyword full-text search using PostgreSQL

        Args:
            query: Search query text
            limit: Maximum number of results
            offset: Number of results to skip
            db: Database session
            user: Current user for access control

        Returns:
            List of search results
        """
        # Get user bucket filter
        bucket_filter = self._get_user_bucket_filter(user) if user else [DocumentBucket.PUBLIC.value]

        # Build query for full-text search
        query_parts = query.split()
        where_conditions = []

        # Search in document filename
        for part in query_parts:
            where_conditions.append(Document.filename.ilike(f"%{part}%"))

        # Search in chunk text
        for part in query_parts:
            where_conditions.append(DocumentChunk.chunk_text.ilike(f"%{part}%"))

        # Base query
        q = db.query(
            DocumentChunk.id,
            DocumentChunk.document_id,
            Document.filename,
            Document.bucket,
            DocumentChunk.chunk_text,
            DocumentChunk.chunk_index,
            DocumentChunk.page_number
        ).join(
            Document,
            DocumentChunk.document_id == Document.id
        ).filter(
            Document.bucket.in_(bucket_filter)
        )

        # Apply search conditions
        if where_conditions:
            q = q.filter(or_(*where_conditions))

        # Order by creation date (newest first)
        q = q.order_by(Document.created_at.desc())

        # Apply pagination
        q = q.limit(limit).offset(offset)

        results = q.all()

        search_results = []
        for row in results:
            # Calculate simple keyword score based on query term frequency
            chunk_text_lower = row.chunk_text.lower()
            filename_lower = row.filename.lower()
            query_lower = query.lower()

            # Count occurrences
            score = 0.0
            for part in query_parts:
                if part.lower() in chunk_text_lower:
                    score += 0.1
                if part.lower() in filename_lower:
                    score += 0.05

            # Normalize score
            score = min(score, 1.0)

            search_results.append(SearchResult(
                chunk_id=str(row.id),
                document_id=str(row.document_id),
                document_name=row.filename,
                document_bucket=row.bucket.value,
                chunk_text=row.chunk_text,
                chunk_index=row.chunk_index,
                page_number=row.page_number,
                semantic_score=0.0,
                keyword_score=score,
                final_score=score  # Will be recalculated
            ))

        return search_results

    async def hybrid_search(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
        db: Session = None,
        user: User = None
    ) -> Dict[str, Any]:
        """
        Perform hybrid search combining semantic and keyword results

        Args:
            query: Search query text
            limit: Maximum number of results
            offset: Number of results to skip
            db: Database session
            user: Current user for access control

        Returns:
            Dictionary with results and metadata
        """
        # Get both search results
        semantic_results = await self.semantic_search(
            query=query,
            limit=limit * 2,  # Get more to merge
            offset=0,
            db=db,
            user=user
        )

        keyword_results = await self.keyword_search(
            query=query,
            limit=limit * 2,
            offset=0,
            db=db,
            user=user
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
                    "rrf_score": score
                }
            else:
                merged_scores[result.chunk_id]["rrf_score"] += score
                merged_scores[result.chunk_id]["semantic_score"] = max(
                    merged_scores[result.chunk_id]["semantic_score"],
                    result.semantic_score
                )

        # Add keyword scores (k=60)
        for rank, result in enumerate(keyword_results):
            score = 1 / (k + rank + 1)
            if result.chunk_id not in merged_scores:
                merged_scores[result.chunk_id] = {
                    "result": result,
                    "semantic_score": result.semantic_score,
                    "keyword_score": result.keyword_score,
                    "rrf_score": score
                }
            else:
                merged_scores[result.chunk_id]["rrf_score"] += score
                merged_scores[result.chunk_id]["keyword_score"] = max(
                    merged_scores[result.chunk_id]["keyword_score"],
                    result.keyword_score
                )

        # Calculate final scores
        for chunk_id, data in merged_scores.items():
            result = data["result"]
            semantic = data["semantic_score"]
            keyword = data["keyword_score"]

            # Combined score using weights
            final_score = (
                self.semantic_weight * semantic +
                self.keyword_weight * keyword
            )
            result.final_score = final_score

        # Sort by final score and apply pagination
        sorted_results = sorted(
            merged_scores.values(),
            key=lambda x: x["result"].final_score,
            reverse=True
        )

        paginated_results = sorted_results[offset:offset + limit]

        return {
            "query": query,
            "results": [item["result"] for item in paginated_results],
            "total": len(sorted_results),
            "offset": offset,
            "limit": limit
        }


# Global search service instance
search_service = HybridSearchService()
