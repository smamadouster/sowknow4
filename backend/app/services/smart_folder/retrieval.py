"""Multi-Signal Retrieval Service for Smart Folder v2.

Combines direct entity mentions, full-text/vector hybrid search,
graph traversal, co-occurrence expansion, and temporal filtering
to retrieve the most relevant vault assets for a given entity and
query intent.

Phase 2 enhancement: Multi-hop retrieval via co-occurrence analysis
and organization-directed search. When direct entity docs are thin,
expands to related entities (companies, colleagues, locations) found
in the knowledge graph or via co-occurrence patterns.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.knowledge_graph import Entity, EntityRelationship, EntityMention, RelationType
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
    retrieval_source: str = ""  # "mention", "hybrid_search", "graph_traversal", "cooccurrence", "semantic", "keyword"
    entity_context: str | None = None  # Surrounding text if from entity mention
    relation_path: str = "direct"  # "direct" | "graph:{type}:{entity}" | "cooccurrence:{entity}"


@dataclass
class RetrievalContext:
    """Complete retrieval result for a Smart Folder query."""

    primary_assets: list[RetrievedAsset] = field(default_factory=list)
    related_assets: list[RetrievedAsset] = field(default_factory=list)
    total_found: int = 0
    entity_ids_searched: list[UUID] = field(default_factory=list)
    query_used: str = ""
    warnings: list[str] = field(default_factory=list)
    expansion_stats: dict[str, Any] = field(default_factory=dict)


class RetrievalService:
    """Retrieve vault assets using multiple signals including multi-hop expansion."""

    def __init__(
        self,
        hybrid_limit: int = 20,
        mention_limit: int = 20,
        graph_depth: int = 1,
        min_score: float = 0.15,
        cooccurrence_limit: int = 15,
        org_search_limit: int = 10,
    ) -> None:
        self.hybrid_limit = hybrid_limit
        self.mention_limit = mention_limit
        self.graph_depth = graph_depth
        self.min_score = min_score
        self.cooccurrence_limit = cooccurrence_limit
        self.org_search_limit = org_search_limit

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

        Phase 2: Adds co-occurrence expansion and organization-directed
        search when direct entity results are sparse.

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
        expansion_stats: dict[str, int] = {"direct_mentions": 0, "hybrid": 0, "graph": 0, "cooccurrence": 0, "org_search": 0}

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
            expansion_stats["direct_mentions"] = len(mention_assets)

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
                        relation_path="direct",
                    )
                )
            expansion_stats["hybrid"] = len(search_result.get("results", []))
        except Exception as exc:
            logger.warning("Hybrid search failed: %s", exc)
            context.warnings.append(f"Hybrid search error: {exc}")

        # --- Signal 3: Graph Traversal (related entities via explicit relationships) ---
        if entity_id and self.graph_depth > 0:
            graph_assets = await self._retrieve_by_graph_traversal(
                db=db,
                entity_id=entity_id,
                user=user,
                limit=self.hybrid_limit // 2,
                seen_doc_ids=seen_doc_ids,
            )
            for asset in graph_assets:
                if asset.document_id not in seen_doc_ids:
                    seen_doc_ids.add(asset.document_id)
                    context.related_assets.append(asset)
            expansion_stats["graph"] = len(graph_assets)

        # --- Signal 4: Co-occurrence Expansion (Phase 2) ---
        # Find entities that co-occur in the same documents, then search for
        # additional documents about those entities (especially organizations).
        if entity_id:
            cooc_assets = await self._retrieve_by_cooccurrence(
                db=db,
                entity_id=entity_id,
                user=user,
                limit=self.cooccurrence_limit,
                seen_doc_ids=seen_doc_ids,
            )
            for asset in cooc_assets:
                if asset.document_id not in seen_doc_ids:
                    seen_doc_ids.add(asset.document_id)
                    context.related_assets.append(asset)
            expansion_stats["cooccurrence"] = len(cooc_assets)

        # --- Signal 5: Organization-directed search (Phase 2) ---
        # For persons with works_at/founded/ceo_of relationships, do targeted
        # searches for those organizations to find company-level documents.
        if entity_id and entity_name:
            org_assets = await self._retrieve_related_org_docs(
                db=db,
                entity_id=entity_id,
                entity_name=entity_name,
                user=user,
                limit=self.org_search_limit,
                seen_doc_ids=seen_doc_ids,
            )
            for asset in org_assets:
                if asset.document_id not in seen_doc_ids:
                    seen_doc_ids.add(asset.document_id)
                    context.related_assets.append(asset)
            expansion_stats["org_search"] = len(org_assets)

        # --- Signal 6: Focus-aspect semantic boost ---
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
                                relation_path="direct",
                            )
                        )
                except Exception as exc:
                    logger.debug("Focus aspect search failed for '%s': %s", aspect, exc)

        # --- Temporal filter (post-retrieval) ---
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
        context.expansion_stats = expansion_stats

        logger.info(
            "Retrieval complete: %d primary + %d related (stats: %s)",
            len(primary_assets), len(context.related_assets), expansion_stats,
        )

        if context.total_found == 0:
            context.warnings.append("No assets found for the given query and entity.")

        return context

    # French/English stopwords that pollute semantic vectors
    _STOPWORDS = {
        # French
        "me", "faire", "un", "une", "le", "la", "les", "de", "des", "du", "sur",
        "à", "propos", "concernant", "résumer", "résume", "donne", "donner",
        "moi", "information", "informations", "doc", "document", "documents",
        "memo", "mémo", "rapport", "analyse", "synthèse",
        # English
        "a", "an", "the", "me", "give", "make", "write", "tell", "about", "on",
        "regarding", "concerning", "summary", "report", "analysis", "memo",
        "information", "documents", "document", "do", "does", "did", "have", "has",
        "had", "is", "are", "was", "were", "be", "been", "being", "i", "you",
        "he", "she", "it", "we", "they", "my", "your", "his", "her", "its",
        "our", "their", "this", "that", "these", "those", "and", "but", "or",
        "yet", "so", "for", "nor", "as", "at", "by", "from", "in", "into",
        "of", "off", "onto", "out", "over", "to", "up", "with", "within",
        "without", "what", "which", "who", "whom", "whose", "where", "when",
        "why", "how", "all", "any", "both", "each", "few", "more", "most",
        "other", "some", "such", "no", "not", "only", "own", "same", "than",
        "too", "very", "can", "will", "just", "should", "now",
    }

    def _clean_search_query(self, query_text: str) -> str:
        """Remove function words to produce a clean semantic search query."""
        words = query_text.split()
        cleaned = [w for w in words if w.lower().strip("?.,;:!'()") not in self._STOPWORDS]
        return " ".join(cleaned) if cleaned else query_text

    def _build_search_query(
        self,
        query_text: str,
        entity_name: str | None,
        focus_aspects: list[str] | None,
    ) -> str:
        """Build an enriched search query for hybrid search.

        Uses the clean entity name as the primary search term to avoid
        polluting the semantic vector with French/English function words.
        """
        # Prefer entity_name as the clean search term
        if entity_name:
            parts = [entity_name]
            # Add cleaned query text if it contains meaningful extra terms
            cleaned = self._clean_search_query(query_text)
            if cleaned and cleaned.lower() != entity_name.lower():
                # Only add words not already in entity_name
                extra = [w for w in cleaned.split() if w.lower() not in entity_name.lower()]
                if extra:
                    parts.extend(extra)
        else:
            parts = [self._clean_search_query(query_text)]

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
                    relation_path="direct",
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
        """Retrieve assets linked to entities related to the target entity via explicit relationships."""
        # Find related entity IDs (depth 1) with their relationship types
        rel_stmt = select(
            EntityRelationship.target_id,
            EntityRelationship.relation_type,
            EntityRelationship.confidence_score,
        ).where(
            EntityRelationship.source_id == entity_id
        ).union(
            select(
                EntityRelationship.source_id,
                EntityRelationship.relation_type,
                EntityRelationship.confidence_score,
            ).where(
                EntityRelationship.target_id == entity_id
            )
        )
        rel_result = await db.execute(rel_stmt)
        related = rel_result.all()

        if not related:
            return []

        related_entity_ids = [row[0] for row in related]
        rel_type_map = {row[0]: row[1] for row in related}
        rel_conf_map = {row[0]: row[2] for row in related}

        # Fetch entity names for relation_path metadata
        ent_stmt = select(Entity.id, Entity.name).where(Entity.id.in_(related_entity_ids))
        ent_result = await db.execute(ent_stmt)
        ent_names = {row[0]: row[1] for row in ent_result.all()}

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
            rel_type = rel_type_map.get(mention.entity_id, "related")
            rel_name = ent_names.get(mention.entity_id, "unknown")
            confidence = rel_conf_map.get(mention.entity_id, 50)
            score = min(0.75, 0.4 + (confidence / 200))  # 0.4-0.875 based on confidence
            assets.append(
                RetrievedAsset(
                    document_id=mention.document_id,
                    document_name=getattr(mention, "document", None) and mention.document.filename or "Unknown",
                    document_bucket=getattr(mention, "document", None) and mention.document.bucket or "public",
                    chunk_text=mention.context_text,
                    page_number=mention.page_number,
                    score=score,
                    retrieval_source="graph_traversal",
                    relation_path=f"graph:{rel_type}:{rel_name}",
                )
            )
        return assets

    async def _retrieve_by_cooccurrence(
        self,
        db: AsyncSession,
        entity_id: UUID,
        user: Any,
        limit: int,
        seen_doc_ids: set[UUID],
    ) -> list[RetrievedAsset]:
        """Phase 2: Expand retrieval via entity co-occurrence.

        Finds entities that frequently appear in the same documents as the
        target entity, then retrieves OTHER documents about those co-occurring
        entities (especially organizations and people) via direct SQL queries.

        Uses direct DB queries instead of search_service.hybrid_search() to
        avoid session concurrency issues (hybrid_search spawns 5 concurrent
        sub-tasks that can invalidate a shared SQLAlchemy session).
        """
        # Step 1: Find documents that mention the target entity
        doc_stmt = (
            select(EntityMention.document_id)
            .where(EntityMention.entity_id == entity_id)
            .distinct()
        )
        doc_result = await db.execute(doc_stmt)
        target_doc_ids = [row[0] for row in doc_result.all()]

        if not target_doc_ids:
            return []

        # Step 2: Find top co-occurring entities (organizations and people prioritized)
        cooc_stmt = text("""
            SELECT e.id, e.name, e.entity_type, COUNT(DISTINCT em.document_id) as doc_count
            FROM sowknow.entity_mentions em
            JOIN sowknow.entities e ON e.id = em.entity_id
            WHERE em.document_id = ANY(:doc_ids)
              AND e.id != :entity_id
              AND e.entity_type IN ('organization', 'person', 'location')
            GROUP BY e.id, e.name, e.entity_type
            ORDER BY doc_count DESC, e.document_count DESC
            LIMIT :limit
        """)
        cooc_result = await db.execute(
            cooc_stmt,
            {
                "doc_ids": [str(d) for d in target_doc_ids],
                "entity_id": str(entity_id),
                "limit": 10,
            },
        )
        cooc_entities = cooc_result.all()

        if not cooc_entities:
            return []

        logger.info(
            "Co-occurrence expansion: found %d related entities for %s",
            len(cooc_entities), entity_id,
        )

        # Step 3: For each co-occurring entity, find documents where it is mentioned
        # BUT the target entity is NOT mentioned (new contextual docs).
        # Use a single efficient query instead of per-entity hybrid_search.
        cooc_entity_ids = [row[0] for row in cooc_entities]
        cooc_meta = {
            row[0]: {"name": row[1], "type": row[2], "doc_count": row[3]}
            for row in cooc_entities
        }

        # Find documents mentioning co-occurring entities, excluding docs already seen
        # and excluding docs that directly mention the target entity (to get NEW context)
        related_doc_stmt = text("""
            SELECT DISTINCT ON (em.document_id)
                em.document_id,
                em.entity_id,
                em.context_text,
                em.page_number,
                d.filename,
                d.bucket
            FROM sowknow.entity_mentions em
            JOIN sowknow.documents d ON d.id = em.document_id
            WHERE em.entity_id = ANY(:entity_ids)
              AND em.document_id != ALL(:seen_doc_ids)
              AND em.document_id NOT IN (
                  SELECT document_id FROM sowknow.entity_mentions WHERE entity_id = :target_id
              )
            ORDER BY em.document_id, em.confidence_score DESC
            LIMIT :limit
        """)
        related_doc_result = await db.execute(
            related_doc_stmt,
            {
                "entity_ids": [str(e) for e in cooc_entity_ids],
                "seen_doc_ids": [str(d) for d in seen_doc_ids] if seen_doc_ids else ["00000000-0000-0000-0000-000000000000"],
                "target_id": str(entity_id),
                "limit": limit,
            },
        )
        rows = related_doc_result.all()

        assets = []
        seen: set[UUID] = set()
        for row in rows:
            doc_id = row[0]
            ent_id = row[1]
            if doc_id in seen_doc_ids or doc_id in seen:
                continue
            seen.add(doc_id)
            meta = cooc_meta.get(ent_id, {})
            ent_name = meta.get("name", "unknown")
            ent_type = meta.get("type", "unknown")
            doc_count = meta.get("doc_count", 1)
            # Score: base 0.4 + co-occurrence strength (capped at 0.35)
            score = 0.4 + min(0.35, doc_count * 0.03)
            assets.append(
                RetrievedAsset(
                    document_id=doc_id,
                    document_name=row[4] or "Unknown",
                    document_bucket=row[5].value if hasattr(row[5], "value") else str(row[5]) if row[5] else "public",
                    chunk_text=row[2],
                    page_number=row[3],
                    score=score,
                    retrieval_source="cooccurrence",
                    relation_path=f"cooccurrence:{ent_type}:{ent_name}",
                )
            )

        logger.info(
            "Co-occurrence expansion: retrieved %d new contextual documents for %s",
            len(assets), entity_id,
        )
        return assets

    async def _retrieve_related_org_docs(
        self,
        db: AsyncSession,
        entity_id: UUID,
        entity_name: str,
        user: Any,
        limit: int,
        seen_doc_ids: set[UUID],
    ) -> list[RetrievedAsset]:
        """Phase 2: Organization-directed search.

        For persons with works_at/founded/ceo_of/partner_of relationships,
        retrieves documents about those organizations via direct DB queries.
        This finds company-level documents (contracts, financials, minutes)
        that provide context about the person's role even if their name
        doesn't appear on every page.

        Uses direct SQL instead of search_service.hybrid_search() to avoid
        session concurrency issues.
        """
        # Find organization relationships
        org_rel_types = [
            RelationType.WORKS_AT,
            RelationType.FOUNDED,
            RelationType.CEO_OF,
            RelationType.PARTNER_OF,
            RelationType.MEMBER_OF,
            RelationType.OWNED_BY,
        ]

        rel_stmt = select(
            EntityRelationship.target_id,
            EntityRelationship.relation_type,
        ).where(
            EntityRelationship.source_id == entity_id,
            EntityRelationship.relation_type.in_(org_rel_types),
        ).union(
            select(
                EntityRelationship.source_id,
                EntityRelationship.relation_type,
            ).where(
                EntityRelationship.target_id == entity_id,
                EntityRelationship.relation_type.in_(org_rel_types),
            )
        )
        rel_result = await db.execute(rel_stmt)
        related = rel_result.all()

        if not related:
            return []

        org_ids = [row[0] for row in related]
        rel_type_map = {row[0]: row[1] for row in related}

        # Fetch org names
        ent_stmt = select(Entity.id, Entity.name).where(Entity.id.in_(org_ids))
        ent_result = await db.execute(ent_stmt)
        orgs = ent_result.all()

        if not orgs:
            return []

        # Single query: find documents mentioning these orgs but NOT the target entity
        # (to get NEW organizational context docs)
        org_doc_stmt = text("""
            SELECT DISTINCT ON (em.document_id)
                em.document_id,
                em.entity_id,
                em.context_text,
                em.page_number,
                d.filename,
                d.bucket
            FROM sowknow.entity_mentions em
            JOIN sowknow.documents d ON d.id = em.document_id
            WHERE em.entity_id = ANY(:org_ids)
              AND em.document_id != ALL(:seen_doc_ids)
              AND em.document_id NOT IN (
                  SELECT document_id FROM sowknow.entity_mentions WHERE entity_id = :target_id
              )
            ORDER BY em.document_id, em.confidence_score DESC
            LIMIT :limit
        """)
        org_doc_result = await db.execute(
            org_doc_stmt,
            {
                "org_ids": [str(o) for o in org_ids],
                "seen_doc_ids": [str(d) for d in seen_doc_ids] if seen_doc_ids else ["00000000-0000-0000-0000-000000000000"],
                "target_id": str(entity_id),
                "limit": limit,
            },
        )
        rows = org_doc_result.all()

        assets = []
        seen: set[UUID] = set()
        for row in rows:
            doc_id = row[0]
            org_id = row[1]
            if doc_id in seen_doc_ids or doc_id in seen:
                continue
            seen.add(doc_id)
            rel_type = rel_type_map.get(org_id, "related")
            org_name = next((name for oid, name in orgs if oid == org_id), "unknown")
            # Higher score than co-occurrence because relationship is explicit
            score = 0.55
            assets.append(
                RetrievedAsset(
                    document_id=doc_id,
                    document_name=row[4] or "Unknown",
                    document_bucket=row[5].value if hasattr(row[5], "value") else str(row[5]) if row[5] else "public",
                    chunk_text=row[2],
                    page_number=row[3],
                    score=score,
                    retrieval_source="org_search",
                    relation_path=f"org:{rel_type}:{org_name}",
                )
            )

        logger.info(
            "Org-directed search: found %d new docs across %d orgs for %s",
            len(assets), len(orgs), entity_name,
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
