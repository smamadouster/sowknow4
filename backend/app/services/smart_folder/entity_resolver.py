"""Entity Resolver Service for Smart Folder v2.

Resolves a natural-language entity name to a canonical Entity record
using exact match, alias matching, and fuzzy matching.
"""

import logging
from dataclasses import dataclass
from typing import Sequence

from difflib import SequenceMatcher, get_close_matches
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_graph import Entity

logger = logging.getLogger(__name__)


@dataclass
class ResolutionResult:
    """Result of entity resolution."""

    entity: Entity | None = None
    match_type: str | None = None  # "exact", "alias", "fuzzy", "none"
    confidence: float = 0.0  # 0-100
    candidates: list[Entity] | None = None


class EntityResolverService:
    """Resolve entity names to canonical Entity records."""

    FUZZY_THRESHOLD = 75  # Minimum fuzzy score to consider a match
    TOP_K_CANDIDATES = 5

    async def resolve(
        self,
        db: AsyncSession,
        name: str,
        user_id: str | None = None,
    ) -> ResolutionResult:
        """Resolve an entity name to a canonical Entity.

        Resolution order:
        1. Exact match on entity.name (case-insensitive)
        2. Alias match (entity.aliases contains the name)
        3. Fuzzy match on entity.name

        Args:
            db: Async database session.
            name: The entity name to resolve.
            user_id: Optional user ID for scoping (currently unused).

        Returns:
            ResolutionResult with the matched entity and metadata.
        """
        if not name or not name.strip():
            return ResolutionResult(match_type="none", confidence=0.0)

        normalized = name.strip().lower()

        # 1. Exact match (case-insensitive)
        exact_stmt = select(Entity).where(func.lower(Entity.name) == normalized)
        exact_result = await db.execute(exact_stmt)
        exact_entity = exact_result.scalar_one_or_none()
        if exact_entity:
            return ResolutionResult(
                entity=exact_entity,
                match_type="exact",
                confidence=100.0,
            )

        # 2. Alias match ( PostgreSQL JSONB contains )
        alias_stmt = select(Entity).where(
            Entity.aliases.isnot(None),
            Entity.aliases.op("@>")([name]),
        )
        alias_result = await db.execute(alias_stmt)
        alias_entity = alias_result.scalar_one_or_none()
        if alias_entity:
            return ResolutionResult(
                entity=alias_entity,
                match_type="alias",
                confidence=95.0,
            )

        # 3. Fuzzy match — fetch all entity names, score them
        all_stmt = select(Entity.id, Entity.name).order_by(Entity.name)
        all_result = await db.execute(all_stmt)
        rows = all_result.all()

        if not rows:
            return ResolutionResult(match_type="none", confidence=0.0)

        choices = {row.name: row.id for row in rows}
        choice_names = list(choices.keys())

        # Use difflib for fuzzy matching
        close_matches = get_close_matches(
            name, choice_names, n=self.TOP_K_CANDIDATES, cutoff=0.5
        )

        scored_matches = []
        for match_name in close_matches:
            score = SequenceMatcher(None, name.lower(), match_name.lower()).ratio() * 100
            scored_matches.append((match_name, score))

        # Also check simple containment for short queries
        for choice_name in choice_names:
            if name.lower() in choice_name.lower() or choice_name.lower() in name.lower():
                score = SequenceMatcher(None, name.lower(), choice_name.lower()).ratio() * 100
                scored_matches.append((choice_name, score))

        # Deduplicate and sort by score descending
        seen_names = set()
        unique_matches = []
        for match_name, score in sorted(scored_matches, key=lambda x: x[1], reverse=True):
            if match_name not in seen_names:
                seen_names.add(match_name)
                unique_matches.append((match_name, score))

        if unique_matches and unique_matches[0][1] >= self.FUZZY_THRESHOLD:
            best_name, best_score = unique_matches[0]
            best_id = choices[best_name]

            # Fetch the full entity
            entity_stmt = select(Entity).where(Entity.id == best_id)
            entity_result = await db.execute(entity_stmt)
            best_entity = entity_result.scalar_one_or_none()

            if best_entity:
                # Gather top candidates for user confirmation if needed
                candidate_ids = [
                    choices[m[0]] for m in unique_matches if m[1] >= self.FUZZY_THRESHOLD
                ]
                candidates = []
                if len(candidate_ids) > 1:
                    cand_stmt = select(Entity).where(Entity.id.in_(candidate_ids[:3]))
                    cand_result = await db.execute(cand_stmt)
                    candidates = list(cand_result.scalars().all())

                return ResolutionResult(
                    entity=best_entity,
                    match_type="fuzzy",
                    confidence=float(best_score),
                    candidates=candidates or None,
                )

        return ResolutionResult(match_type="none", confidence=0.0)

    async def search_candidates(
        self,
        db: AsyncSession,
        name: str,
        limit: int = 10,
    ) -> Sequence[Entity]:
        """Return a list of candidate entities for manual selection.

        Args:
            db: Async database session.
            name: Partial or full entity name.
            limit: Maximum candidates to return.

        Returns:
            List of candidate Entity objects ordered by relevance.
        """
        if not name or not name.strip():
            return []

        pattern = f"%{name.strip()}%"
        stmt = (
            select(Entity)
            .where(
                or_(
                    Entity.name.ilike(pattern),
                    Entity.aliases.isnot(None),
                    # JSONB string search fallback — works for simple aliases
                )
            )
            .order_by(Entity.name)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()


# Module-level singleton
entity_resolver = EntityResolverService()
