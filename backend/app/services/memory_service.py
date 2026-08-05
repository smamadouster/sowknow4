"""Memory Service (draft v0.1 — docs/agent_memory/SPEC.md).

Distills chat conversations into persistent L1 memory atoms, deduplicated
against the owner's existing atoms and grounded (traceable) so no fabricated
memory is stored. Also builds L2 scenario clusters and the L3 profile.

Guarding principles (mirroring the Collection Orchestrator doctrine):
- Nothing is stored unless it is traceable to a source message (grounding).
- New atoms start `status=pending`; they never enter search/context before a
  human/agent reviews them (`reviewed`).
- `visibility` defaults to `private` — no leak by default.
- LLM failures are non-fatal: an empty result is returned, never a guess.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chat import ChatMessage, MessageRole
from app.models.memory import (
    MemoryAtom,
    MemoryAtomKind,
    MemoryStatus,
    MemoryVisibility,
)
from app.services.agent_identity import build_service_prompt
from app.services.embed_client import embedding_service
from app.services.llm_gateway import llm_gateway
from app.services.smart_folder.query_parser import extract_first_json

logger = logging.getLogger(__name__)


def _record_metric(name: str, value: float, labels: dict | None = None) -> None:
    """Best-effort Prometheus counter increment — never breaks distilling."""
    try:
        from app.services.prometheus_metrics import get_metrics

        get_metrics().counter(name, help_text=f"sowknow memory {name}", labels=list((labels or {}).keys())).inc(
            delta=value, labels=labels or {}
        )
    except Exception:
        pass


_MEMORY_MISSION = (
    "Distill durable, reusable facts from chat conversations so future agents "
    "inherit context instead of re-learning it."
)

_MEMORY_CONSTRAINTS = (
    "- You MUST only extract statements explicitly present in the conversation\n"
    "- You MUST NOT invent, infer beyond the text, or fabricate memory\n"
    "- You MUST prefer concise, self-contained, one-line statements in the "
    "user's language (French by default)\n"
    "- You MUST tag each atom with the source message index it came from\n"
    "- Preferences and constraints are as valuable as facts — include them"
)

_MEMORY_SYSTEM_PROMPT = build_service_prompt(
    service_name="SOWKNOW Memory Distillation Agent",
    mission=_MEMORY_MISSION,
    constraints=_MEMORY_CONSTRAINTS,
    task_prompt="""Analyse la conversation fournie et extrais les informations durables.
Retourne **uniquement** un objet JSON (pas de markdown, pas d'explication) :

{
  "atoms": [
    {
      "kind": "fact|preference|constraint|decision",
      "statement": "<une phrase concise, autonome>",
      "confidence": <0-100>,
      "source_message_index": <indice 0-base du message source dans la liste>
    }
  ]
}

Regles :
- N'invente rien. Chaque atome doit etre directement appuye par un message.
- Si aucune information durable, retourne {"atoms": []}.
- source_message_index doit pointer vers un message reel de la liste fournie.
- Statement en francais si la conversation est en francais, sinon en anglais.""",
)

_MEMORY_PROFILE_SYSTEM_PROMPT = build_service_prompt(
    service_name="SOWKNOW Memory Profile Agent",
    mission=_MEMORY_MISSION,
    constraints=_MEMORY_CONSTRAINTS,
    task_prompt="""Analyse les faits, preferences, contraintes et scenarios revises de l'utilisateur
et retourne **uniquement** un objet JSON (pas de markdown, pas d'explication) :

{
  "persona": {
    "communication_pref": "<langue / ton / style prefere>",
    "priorities": ["<priorite 1>", "<priorite 2>"],
    "decision_style": "<style de decision observe>"
  },
  "stable_patterns": ["<pattern stable 1>", "<pattern stable 2>"]
}

Regles :
- N'invente jamais un trait absent des donnees fournies.
- Reste concis : 2-4 priorites, 2-5 patterns.
- Si trop peu de donnees pour un champ, omets-le plutot que de deviner.""",
)


def _message_index(message: Any, messages: list[Any]) -> int:
    """Index of a message in the source list (by id, else positional)."""
    mid = getattr(message, "id", None)
    for i, m in enumerate(messages):
        if getattr(m, "id", None) == mid:
            return i
    return -1


class MemoryService:
    """Distillation + dedup + grounding for L1 atoms."""

    # ------------------------------------------------------------------
    # Extract atoms from a session
    # ------------------------------------------------------------------

    async def distill_session(self, db: AsyncSession, session_id: uuid.UUID, owner_id: uuid.UUID) -> list[MemoryAtom]:
        """Run one distillation pass over a chat session.

        Loads the session's messages (bounded), asks the LLM for candidate
        atoms, grounds each (traceable to a real message), dedups against the
        owner's existing atoms, and inserts new ones with status=pending.
        """
        messages = (
            (
                await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        if len(messages) < settings.MEMORY_DISTILL_MIN_MESSAGES:
            logger.info(
                "memory.distill skip: session %s has %d messages (< %d)",
                session_id,
                len(messages),
                settings.MEMORY_DISTILL_MIN_MESSAGES,
            )
            return []

        # Only user/assistant turns carry content worth distilling.
        transcript = [
            {"role": msg.role.value, "content": msg.content}
            for msg in messages
            if msg.role in (MessageRole.USER, MessageRole.ASSISTANT)
        ]
        if not transcript:
            return []

        candidates = await self._llm_extract(transcript, session_id=session_id)
        if not candidates:
            return []

        existing = await self._existing_statements(db, owner_id)
        inserted: list[MemoryAtom] = []
        now = datetime.now(timezone.utc)

        for cand in candidates:
            atom = await self._build_atom(
                db,
                owner_id=owner_id,
                session_id=session_id,
                messages=messages,
                transcript=transcript,
                candidate=cand,
                existing_statements=existing,
                now=now,
            )
            if atom is not None:
                db.add(atom)
                inserted.append(atom)

        if inserted:
            await db.commit()
            for a in inserted:
                await db.refresh(a)
        _record_metric("sowknow_memory_atoms_distilled_total", len(inserted))
        logger.info(
            "memory.distill session=%s: %d candidate(s), %d inserted",
            session_id,
            len(candidates),
            len(inserted),
        )
        return inserted

    # ------------------------------------------------------------------
    # LLM extraction
    # ------------------------------------------------------------------

    async def _llm_extract(
        self, transcript: list[dict[str, str]], *, session_id: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        """Call the LLM for candidate atoms. Returns [] on any failure.

        The system prompt MUST be part of the messages sent (not dropped) —
        the bare transcript without JSON instructions yields prose, not atoms.
        A per-session collection_id scopes the OpenRouter cache so a memory
        extraction never collides with an unrelated conversation's cached
        response.
        """
        user_prompt = "Conversation (index: role — content):\n\n" + "\n".join(
            f"[{i}] {m['role']} — {m['content'][:600]}" for i, m in enumerate(transcript)
        )
        try:
            raw = await asyncio.wait_for(
                llm_gateway.chat_completion_non_stream(
                    messages=[
                        {"role": "system", "content": _MEMORY_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.1,
                    max_tokens=1500,
                    collection_id=f"memory:{session_id}" if session_id else None,
                ),
                timeout=30.0,
            )
            data = extract_first_json(raw)
            atoms = data.get("atoms", []) if isinstance(data, dict) else []
            if not isinstance(atoms, list):
                atoms = []
            return [a for a in atoms[: settings.MEMORY_ATOM_MAX] if isinstance(a, dict)]
        except asyncio.TimeoutError:
            logger.warning("memory.extract timeout — returning no atoms")
            return []
        except Exception as exc:
            logger.warning("memory.extract failed, returning no atoms: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Grounding + dedup
    # ------------------------------------------------------------------

    async def _existing_statements(self, db: AsyncSession, owner_id: uuid.UUID) -> list[str]:
        rows = (
            (
                await db.execute(
                    select(MemoryAtom.statement).where(
                        MemoryAtom.owner_id == owner_id,
                        MemoryAtom.status.in_([MemoryStatus.PENDING.value, MemoryStatus.REVIEWED.value]),
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _build_atom(
        self,
        db: AsyncSession,
        *,
        owner_id: uuid.UUID,
        session_id: uuid.UUID,
        messages: list[ChatMessage],
        transcript: list[dict[str, str]],
        candidate: dict[str, Any],
        existing_statements: list[str],
        now: datetime,
    ) -> MemoryAtom | None:
        """Validate + dedup one candidate. Returns None when it must be dropped."""
        statement = str(candidate.get("statement", "")).strip()
        if len(statement) < 8:
            return None

        # Grounding: the statement must be traceable to a real source message.
        idx = candidate.get("source_message_index")
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = -1
        if idx < 0 or idx >= len(transcript):
            logger.info("memory.grounding drop: no valid source index for %r", statement[:60])
            return None
        source_msg = messages[idx] if idx < len(messages) else None
        if source_msg is None:
            return None

        # Kind + confidence validation.
        try:
            kind = MemoryAtomKind(candidate.get("kind", "fact"))
        except ValueError:
            kind = MemoryAtomKind.FACT
        try:
            confidence = max(0, min(100, int(candidate.get("confidence", 50))))
        except (TypeError, ValueError):
            confidence = 50
        if confidence < settings.MEMORY_ATOM_MIN_CONFIDENCE:
            logger.info(
                "memory.confidence drop: %r (%d < %d)", statement[:50], confidence, settings.MEMORY_ATOM_MIN_CONFIDENCE
            )
            return None

        # Semantic dedup against the owner's existing atoms.
        if existing_statements:
            try:
                similar = await self._most_similar(statement, existing_statements)
                if similar is not None:
                    logger.info("memory.dedup drop (sim=%.3f): %r", similar, statement[:60])
                    return None
            except Exception as exc:
                # Dedup failure must not fabricate duplicates; proceed to insert.
                logger.warning("memory.dedup failed, proceeding: %s", exc)

        return MemoryAtom(
            id=uuid.uuid4(),
            owner_id=owner_id,
            kind=kind,
            statement=statement,
            confidence=confidence,
            source_message_ids=[str(source_msg.id)],
            source_session_ids=[str(session_id)],
            entity_ids=list(candidate.get("entity_ids", []) or []),
            visibility=MemoryVisibility.PRIVATE,
            status=MemoryStatus.PENDING,
            first_seen_at=now,
            last_seen_at=now,
        )

    async def _most_similar(self, statement: str, existing: list[str]) -> float | None:
        """Cosine similarity of `statement` vs the closest existing statement,
        or None when embedding is unavailable."""
        if not existing:
            return None
        try:
            batch = [statement] + existing[:50]
            vectors = await embedding_service.encode_async(batch)
        except Exception as exc:
            # Embed unavailability must not block distillation — skip dedup.
            logger.warning("memory.dedup embed unavailable, skipping: %s", exc)
            return None
        if not vectors or len(vectors) != len(batch):
            return None
        target = vectors[0]
        best = 0.0
        for vec in vectors[1:]:
            sim = _cosine(target, vec)
            if sim > best:
                best = sim
        return best if best >= settings.MEMORY_ATOM_SIM_THRESHOLD else None

    # ------------------------------------------------------------------
    # L2 scenario clustering
    # ------------------------------------------------------------------

    async def build_scenarios(self, db: AsyncSession, owner_id: uuid.UUID) -> int:
        """Cluster the owner's reviewed atoms into memory_scenarios (L2).

        Deterministic greedy clustering by entity overlap then shared source
        sessions: atoms sharing an entity id (or a source session) form a
        cluster. A cluster becomes a scenario when it has ≥ 3 atoms and its
        atom set differs from every existing scenario's atom set (idempotent).
        New scenarios start status=pending and are never injected before
        review.
        """
        from app.models.memory import MemoryScenario

        atoms = (
            (
                await db.execute(
                    select(MemoryAtom)
                    .where(
                        MemoryAtom.owner_id == owner_id,
                        MemoryAtom.status == MemoryStatus.REVIEWED.value,
                    )
                    .order_by(MemoryAtom.confidence.desc())
                )
            )
            .scalars()
            .all()
        )
        if len(atoms) < 3:
            logger.info("memory.scenarios skip owner=%s: %d reviewed atoms (< 3)", owner_id, len(atoms))
            return 0

        # Greedy cluster: start a cluster with the highest-confidence atom,
        # then absorb any atom sharing an entity or a source session with it.
        remaining = list(atoms)
        clusters: list[list[MemoryAtom]] = []
        while remaining:
            seed = remaining.pop(0)
            cluster = [seed]
            seed_entities = set(seed.entity_ids or [])
            seed_sessions = set(seed.source_session_ids or [])
            changed = True
            while changed:
                changed = False
                for atom in list(remaining):
                    a_entities = set(atom.entity_ids or [])
                    a_sessions = set(atom.source_session_ids or [])
                    if (seed_entities & a_entities) or (seed_sessions & a_sessions):
                        cluster.append(atom)
                        seed_entities |= a_entities
                        seed_sessions |= a_sessions
                        remaining.remove(atom)
                        changed = True
            clusters.append(cluster)

        # Existing scenario atom sets (idempotency).
        existing = (await db.execute(select(MemoryScenario).where(MemoryScenario.owner_id == owner_id))).scalars().all()
        existing_atom_sets = [set(s.atom_ids or []) for s in existing]

        created = 0
        for cluster in clusters:
            if len(cluster) < 3:
                continue
            atom_ids = {str(a.id) for a in cluster}
            if any(atom_ids == prev for prev in existing_atom_sets):
                continue
            # Title = the highest-confidence atom's kind+statement snippet.
            top = max(cluster, key=lambda a: a.confidence)
            title = f"{top.kind.value}: {top.statement[:100]}"
            summary = "\n".join(f"- {a.statement}" for a in cluster[:8])
            sessions = sorted({s for a in cluster for s in (a.source_session_ids or [])})
            entities = sorted({e for a in cluster for e in (a.entity_ids or [])})
            db.add(
                MemoryScenario(
                    id=uuid.uuid4(),
                    owner_id=owner_id,
                    title=title,
                    summary=summary,
                    scope=",".join(entities) if entities else "auto-cluster",
                    atom_ids=sorted(atom_ids),
                    source_session_ids=sessions,
                    visibility=MemoryVisibility.PRIVATE,
                    status=MemoryStatus.PENDING,
                )
            )
            created += 1

        if created:
            await db.commit()
        logger.info("memory.scenarios owner=%s: %d cluster(s) created", owner_id, created)
        return created

    # ------------------------------------------------------------------
    # L3 profile building
    # ------------------------------------------------------------------

    async def build_profile(self, db: AsyncSession, owner_id: uuid.UUID) -> bool:
        """Build/refresh the owner's L3 profile from reviewed atoms + scenarios.

        One LLM pass over the owner's reviewed atoms (and any ready scenarios)
        produces a compact persona + stable patterns. The profile is upserted
        with version+1. Only `status=reviewed` atoms feed the profile — raw
        pending memory never shapes it. Returns True when a profile was written.
        """
        from app.models.memory import MemoryProfile, MemoryScenario

        atoms = (
            (
                await db.execute(
                    select(MemoryAtom)
                    .where(
                        MemoryAtom.owner_id == owner_id,
                        MemoryAtom.status == MemoryStatus.REVIEWED.value,
                    )
                    .order_by(MemoryAtom.confidence.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        scenarios = (
            (
                await db.execute(
                    select(MemoryScenario)
                    .where(
                        MemoryScenario.owner_id == owner_id,
                        MemoryScenario.status == MemoryStatus.REVIEWED.value,
                    )
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        if not atoms and not scenarios:
            logger.info("memory.profile skip owner=%s: no reviewed assets", owner_id)
            return False

        statements = [a.statement for a in atoms]
        scenario_lines = [f"{s.title}: {s.summary}" for s in scenarios]
        source = "\n".join(["[atoms]"] + statements + ["[scenarios]"] + scenario_lines)

        persona, patterns = await self._llm_profile(source)
        if persona is None and patterns is None:
            return False

        existing = (await db.execute(select(MemoryProfile).where(MemoryProfile.owner_id == owner_id))).scalars().first()
        if existing is None:
            db.add(
                MemoryProfile(
                    id=uuid.uuid4(),
                    owner_id=owner_id,
                    persona=persona or {},
                    stable_patterns=patterns or [],
                    version=1,
                )
            )
        else:
            existing.persona = persona or existing.persona
            existing.stable_patterns = patterns or existing.stable_patterns
            existing.version = (existing.version or 1) + 1
        await db.commit()
        _record_metric("sowknow_memory_profiles_built_total", 1)
        logger.info("memory.profile owner=%s: profile written", owner_id)
        return True

    async def _llm_profile(self, source: str) -> tuple[dict | None, list | None]:
        """LLM pass: atoms+scenarios → {persona, stable_patterns}. Returns
        (None, None) on any failure — never fabricates a profile."""
        user_prompt = "Faits, preferences, contraintes et scenarios revises de l'utilisateur :\n\n" + source[:4000]
        try:
            raw = await asyncio.wait_for(
                llm_gateway.chat_completion_non_stream(
                    messages=[
                        {"role": "system", "content": _MEMORY_PROFILE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                    max_tokens=1200,
                ),
                timeout=30.0,
            )
            data = extract_first_json(raw)
            if not isinstance(data, dict):
                return None, None
            persona = data.get("persona")
            patterns = data.get("stable_patterns")
            if not isinstance(persona, dict):
                persona = None
            if not isinstance(patterns, list):
                patterns = None
            return persona, patterns
        except asyncio.TimeoutError:
            logger.warning("memory.profile LLM timeout — skipping")
            return None, None
        except Exception as exc:
            logger.warning("memory.profile LLM failed — skipping: %s", exc)
            return None, None


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


memory_service = MemoryService()
