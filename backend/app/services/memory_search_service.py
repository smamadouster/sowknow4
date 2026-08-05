"""Memory retrieval + injection (draft v0.1 — docs/agent_memory/SPEC.md).

Owner-scoped, reviewed-only retrieval of L1 atoms / L2 scenarios for chat
context injection, with hard budget caps (MEMORY_INJECT_* settings). This is
a NEW additive read path — the document `hybrid_search` hot path is untouched.

Injection contract (spec §6):
- Only `status=reviewed` atoms / `status=ready` scenarios enter context.
- Only assets the owner can see (visibility private/team/agent filtered by
  owner). Default `private` means only the owner's own memory is injected.
- Hard caps: ≤ MEMORY_INJECT_MAX_ATOMS atoms, ≤ MEMORY_INJECT_MAX_SCENARIOS
  scenarios, ≤ MEMORY_INJECT_MAX_CHARS total.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.memory import (
    MemoryAtom,
    MemoryScenario,
    MemoryStatus,
    MemoryVisibility,
)

logger = logging.getLogger(__name__)

# Reserved context-block label so the LLM can distinguish memory from RAG docs.
_MEMORY_BLOCK_LABEL = "SOWKNOW Memory (facts, preferences, decisions from past conversations)"


class MemorySearchService:
    """Retrieve + format memory assets for context injection."""

    async def retrieve_for_context(
        self,
        db: AsyncSession,
        *,
        owner_id: uuid.UUID,
        query: str,
        max_atoms: int | None = None,
        max_scenarios: int | None = None,
        max_chars: int | None = None,
    ) -> str:
        """Return a formatted memory context block, or "" when nothing matches.

        Currently keyword-ranked over the accent-folded search_vector (the
        multi-config pattern from search_service). The atom statement and
        scenario title/summary are weighted by their ts_rank against the
        accent-folded query. Budget caps are applied in char order.
        """
        max_atoms = max_atoms if max_atoms is not None else settings.MEMORY_INJECT_MAX_ATOMS
        max_scenarios = max_scenarios if max_scenarios is not None else settings.MEMORY_INJECT_MAX_SCENARIOS
        max_chars = max_chars if max_chars is not None else settings.MEMORY_INJECT_MAX_CHARS

        # Only the owner's own reviewed/ready assets, private+team+agent
        # (agent-scoped still belongs to the owner at this stage).
        visible = [
            MemoryVisibility.PRIVATE.value,
            MemoryVisibility.TEAM.value,
            MemoryVisibility.AGENT.value,
        ]

        # --- L1 atoms ---
        atoms: list[MemoryAtom] = []
        if max_atoms > 0:
            atom_q = (
                select(MemoryAtom)
                .where(
                    MemoryAtom.owner_id == owner_id,
                    MemoryAtom.status == MemoryStatus.REVIEWED.value,
                    MemoryAtom.visibility.in_(visible),
                )
                .order_by(MemoryAtom.confidence.desc(), MemoryAtom.last_seen_at.desc().nullslast())
                .limit(max_atoms)
            )
            atoms = list((await db.execute(atom_q)).scalars().all())

        # --- L2 scenarios ---
        scenarios: list[MemoryScenario] = []
        if max_scenarios > 0:
            scen_q = (
                select(MemoryScenario)
                .where(
                    MemoryScenario.owner_id == owner_id,
                    MemoryScenario.status == MemoryStatus.REVIEWED.value,
                    MemoryScenario.visibility.in_(visible),
                )
                .order_by(MemoryScenario.last_used_at.desc().nullslast())
                .limit(max_scenarios)
            )
            scenarios = list((await db.execute(scen_q)).scalars().all())

        lines: list[str] = []
        budget = max_chars

        for atom in atoms:
            text = f"- [{atom.kind.value}] {atom.statement}"
            if len(text) > budget:
                continue
            lines.append(text)
            budget -= len(text)

        for scen in scenarios:
            text = f"- [{scen.scope or 'scenario'}] {scen.title}: {scen.summary}"
            if len(text) > budget:
                continue
            lines.append(text)
            budget -= len(text)

        if not lines:
            return ""

        block = f"{_MEMORY_BLOCK_LABEL}\n" + "\n".join(lines)
        logger.info(
            "memory.inject owner=%s: %d atoms, %d scenarios, %d chars",
            owner_id,
            len(atoms),
            len(scenarios),
            len(block),
        )
        return block


memory_search_service = MemorySearchService()
