"""Multi-Signal Retrieval Service for Smart Folder v2.

Combines direct entity mentions, full-text/vector hybrid search,
graph traversal, and temporal filtering to retrieve the most
relevant vault assets for a given entity and query intent.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.knowledge_graph import EntityRelationship, EntityMention
from app.services.search_service import search_service

logger = logging.getLogger(__name__)


@dataclass
class RetrievedAsset:
    """A single retrieved vault asset with metadata."""

    document_id: UUID
    document_name: str
    document_bucket: str
    chunk_text: str | None = None
    chunk_index: int | None = None
    page_number: int | None = None
    score: float = 0.0
    retrieval_source: str = ""  # "mention", "hybrid_search", "graph_traversal", "semantic", "keyword"
    entity_context: str | None = None  # Surrounding text if from entity mention


@dataclass
class RetrievalContext:
    """Complete retrieval result for a Smart Folder query."""

    primary_assets: list[RetrievedAsset] = field(default_factory=list)
    related_assets: list[RetrievedAsset] = field(default_factory=list)
    total_found: int = 0
    entity_ids_searched: list[UUID] = field(default_factory=list)
    query_used: str = ""
    warnings: list[str] = field(default_factory=list)


class RetrievalService:
    """Retrieve vault assets using multiple signals."""

    def __init__(
        self,
        hybrid_limit: int = 20,
        mention_limit: int = 20,
        graph_depth: int = 1,
        min_score: float = 0.15,
    ) -> None:
        self.hybrid_limit = hybrid_limit
        self.mention_limit = mention_limit
        self.graph_depth = graph_depth
        self.min_score = min_score

    async def retrieve(
        self,
        db: AsyncSession,
        user: Any,  # User model instance
        query_text: str,
        entity_id: UUID | None = None,
        entity_name: str | None = None,
        time_range_start: datetime | None = None,
        time_range_end: datetime | None = None,
        focus_aspects: list[str] | None = None,
    ) -> RetrievalContext:
        """Run multi-signal retrieval for a Smart Folder query.

        Args:
            db: Async database session.
            user: Current user (for RBAC bucket filtering).
            query_text: The natural language query.
            entity_id: Resolved canonical entity ID.
            entity_name: Resolved canonical entity name.
            time_range_start: Optional temporal filter start.
            time_range_end: Optional temporal filter end.
            focus_aspects: Optional focus aspects to boost.

        Returns:
            RetrievalContext with primary and related assets.
        """
        context = RetrievalContext(query_used=query_text)
        seen_doc_ids: set[UUID] = set()
        primary_assets: list[RetrievedAsset] = []

        # --- Signal 1: Entity Mentions (direct tag) ---
        if entity_id:
            mention_assets = await self._retrieve_by_entity_mentions(
                db=db,
                entity_id=entity_id,
                limit=self.mention_limit,
            )
            for asset in mention_assets:
                if asset.document_id not in seen_doc_ids:
                    seen_doc_ids.add(asset.document_id)
                    primary_assets.append(asset)
            context.entity_ids_searched.append(entity_id)

        # --- Signal 2: Hybrid Search (keyword + vector) ---
        search_query = self._build_search_query(query_text, entity_name, focus_aspects)
        try:
            search_result = await search_service.hybrid_search(
                query=search_query,
                limit=self.hybrid_limit,
                offset=0,
                db=db,
                user=user,
                timeout=8.0,
                rerank=True,
            )
            for result in search_result.get("results", []):
                doc_id = UUID(result.document_id) if isinstance(result.document_id, str) else result.document_id
                if doc_id in seen_doc_ids:
                    continue
                if result.final_score < self.min_score:
                    continue
                seen_doc_ids.add(doc_id)
                primary_assets.append(
                    RetrievedAsset(
                        document_id=doc_id,
                        document_name=result.document_name,
                        document_bucket=result.document_bucket,
                        chunk_text=result.chunk_text,
                        chunk_index=result.chunk_index,
                        page_number=result.page_number,
                        score=result.final_score,
                        retrieval_source="hybrid_search",
                    )
                )
        except Exception as exc:
            logger.warning("Hybrid search failed: %s", exc)
            context.warnings.append(f"Hybrid search error: {exc}")

        # --- Signal 3: Graph Traversal (related entities) ---
        if entity_id and self.graph_depth > 0:
            related_assets = await self._retrieve_by_graph_traversal(
                db=db,
                entity_id=entity_id,
                user=user,
                limit=self.hybrid_limit // 2,
                seen_doc_ids=seen_doc_ids,
            )
            for asset in related_assets:
                if asset.document_id not in seen_doc_ids:
                    seen_doc_ids.add(asset.document_id)
                    context.related_assets.append(asset)

        # --- Signal 4: Focus-aspect semantic boost ---
        if focus_aspects:
            for aspect in focus_aspects:
                aspect_query = f"{entity_name or query_text} {aspect}"
                try:
                    aspect_result = await search_service.semantic_search(
                        query=aspect_query,
                        limit=5,
                        db=db,
                        user=user,
                    )
                    for result in aspect_result:
                        doc_id = UUID(result.document_id) if isinstance(result.document_id, str) else result.document_id
                        if doc_id in seen_doc_ids:
                            continue
                        seen_doc_ids.add(doc_id)
                        primary_assets.append(
                            RetrievedAsset(
                                document_id=doc_id,
                                document_name=result.document_name,
                                document_bucket=result.document_bucket,
                                chunk_text=result.chunk_text,
                                chunk_index=result.chunk_index,
                                page_number=result.page_number,
                                score=result.final_score * 0.9,  # Slight discount
                                retrieval_source="semantic_focus",
                            )
                        )
                except Exception as exc:
                    logger.debug("Focus aspect search failed for '%s': %s", aspect, exc)

        # --- Temporal filter (post-retrieval, since chunks don't always have dates) ---
        if time_range_start or time_range_end:
            primary_assets = await self._apply_temporal_filter(
                db=db,
                assets=primary_assets,
                start=time_range_start,
                end=time_range_end,
            )
            context.related_assets = await self._apply_temporal_filter(
                db=db,
                assets=context.related_assets,
                start=time_range_start,
                end=time_range_end,
            )

        # Deduplicate and sort by score
        primary_assets.sort(key=lambda a: a.score, reverse=True)
        context.primary_assets = primary_assets
        context.total_found = len(primary_assets) + len(context.related_assets)

        if context.total_found == 0:
            context.warnings.append("No assets found for the given query and entity.")

        return context

    def _build_search_query(
        self,
        query_text: str,
        entity_name: str | None,
        focus_aspects: list[str] | None,
    ) -> str:
        """Build an enriched search query for hybrid search."""
        parts = [query_text]
        if entity_name and entity_name.lower() not in query_text.lower():
            parts.append(entity_name)
        if focus_aspects:
            parts.extend(focus_aspects)
        return " ".join(parts)

    async def _retrieve_by_entity_mentions(
        self,
        db: AsyncSession,
        entity_id: UUID,
        limit: int,
    ) -> list[RetrievedAsset]:
        """Retrieve assets where the entity is explicitly mentioned."""
        stmt = (
            select(EntityMention)
            .where(EntityMention.entity_id == entity_id)
            .order_by(EntityMention.confidence_score.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        mentions = result.scalars().all()

        assets = []
        seen: set[UUID] = set()
        for mention in mentions:
            if mention.document_id in seen:
                continue
            seen.add(mention.document_id)
            assets.append(
                RetrievedAsset(
                    document_id=mention.document_id,
                    document_name=getattr(mention, "document", None) and mention.document.filename or "Unknown",
                    document_bucket=getattr(mention, "document", None) and mention.document.bucket or "public",
                    chunk_text=mention.context_text,
                    page_number=mention.page_number,
                    score=1.0,
                    retrieval_source="mention",
                    entity_context=mention.context_text,
                )
            )
        return assets

    async def _retrieve_by_graph_traversal(
        self,
        db: AsyncSession,
        entity_id: UUID,
        user: Any,
        limit: int,
        seen_doc_ids: set[UUID],
    ) -> list[RetrievedAsset]:
        """Retrieve assets linked to entities related to the target entity."""
        # Find related entity IDs (depth 1)
        rel_stmt = select(EntityRelationship.target_id).where(
            EntityRelationship.source_id == entity_id
        ).union(
            select(EntityRelationship.source_id).where(
                EntityRelationship.target_id == entity_id
            )
        )
        rel_result = await db.execute(rel_stmt)
        related_entity_ids = [row[0] for row in rel_result.all()]

        if not related_entity_ids:
            return []

        # Find mentions of related entities
        mention_stmt = (
            select(EntityMention)
            .where(EntityMention.entity_id.in_(related_entity_ids))
            .limit(limit)
        )
        mention_result = await db.execute(mention_stmt)
        mentions = mention_result.scalars().all()

        assets = []
        seen: set[UUID] = set()
        for mention in mentions:
            if mention.document_id in seen_doc_ids or mention.document_id in seen:
                continue
            seen.add(mention.document_id)
            assets.append(
                RetrievedAsset(
                    document_id=mention.document_id,
                    document_name=getattr(mention, "document", None) and mention.document.filename or "Unknown",
                    document_bucket=getattr(mention, "document", None) and mention.document.bucket or "public",
                    chunk_text=mention.context_text,
                    page_number=mention.page_number,
                    score=0.6,  # Lower score for graph-derived assets
                    retrieval_source="graph_traversal",
                )
            )
        return assets

    async def _apply_temporal_filter(
        self,
        db: AsyncSession,
        assets: list[RetrievedAsset],
        start: datetime | None,
        end: datetime | None,
    ) -> list[RetrievedAsset]:
        """Filter assets by document creation date if temporal bounds are set."""
        if not start and not end:
            return assets

        doc_ids = [a.document_id for a in assets]
        if not doc_ids:
            return assets

        stmt = select(Document.id, Document.created_at).where(Document.id.in_(doc_ids))
        result = await db.execute(stmt)
        doc_dates = {row[0]: row[1] for row in result.all()}

        filtered = []
        for asset in assets:
            doc_date = doc_dates.get(asset.document_id)
            if not doc_date:
                filtered.append(asset)
                continue
            if start and doc_date < start:
                continue
            if end and doc_date > end:
                continue
            filtered.append(asset)
        return filtered


# Module-level singleton
retrieval_service = RetrievalService()
