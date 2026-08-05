"""Skill Extraction Service (draft — docs/agent_memory/SPEC.md extension).

Distills reusable runbook skills from real work — completed collection runs
(collection_audit_events) — so the agent accumulates operational knowledge
instead of re-learning procedures. Skills are stored as `draft` and only
become `active` after review, mirroring the atom review doctrine.

Source (current): collection_audit_events, which carry a chronological trace
of stage/action/status per collection job. A completed job with ≥3 stages
yields one candidate skill.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.collection_orchestrator import CollectionAuditEvent
from app.models.learned_skill import LearnedSkill, SkillStatus
from app.services.agent_identity import build_service_prompt
from app.services.llm_gateway import llm_gateway
from app.services.smart_folder.query_parser import extract_first_json

logger = logging.getLogger(__name__)

_SKILL_MISSION = (
    "Distill reusable runbook skills from completed work so future agents "
    "repeat proven procedures instead of rediscovering them."
)

_SKILL_CONSTRAINTS = (
    "- You MUST base the skill ONLY on the audit trace provided\n"
    "- You MUST NOT invent steps that are absent from the trace\n"
    "- You MUST output concise, ordered, executable steps\n"
    "- Validation rules must be checkable from the trace/outputs"
)

_SKILL_SYSTEM_PROMPT = build_service_prompt(
    service_name="SOWKNOW Skill Distillation Agent",
    mission=_SKILL_MISSION,
    constraints=_SKILL_CONSTRAINTS,
    task_prompt="""Analyse la trace d'audit d'un travail realise et extrais un runbook reutilisable.
Retourne **uniquement** un objet JSON :

{
  "title": "<titre court du runbook>",
  "trigger": "<quand utiliser ce runbook / contexte>",
  "steps": ["<etape 1>", "<etape 2>", ...],
  "validation": ["<controle de succes 1>", ...]
}

Regles :
- Base-toi uniquement sur la trace fournie.
- 3 a 8 etapes maximum, concises et ordonnees.
- Si la trace est trop pauvre pour un runbook, retourne {"skip": true}.""",
)


class SkillExtractionService:
    """Distill collection audit traces into draft skills."""

    MIN_STAGES = 3

    async def extract_from_recent(
        self,
        db: AsyncSession,
        *,
        since_days: int = 7,
        owner_id: uuid.UUID | None = None,
    ) -> int:
        """Scan recent completed collection jobs and distill one skill each."""
        since = datetime.now(timezone.utc) - timedelta(days=since_days)

        # Group audit events by request, keeping only jobs with ≥ MIN_STAGES.
        rows = (
            (
                await db.execute(
                    select(CollectionAuditEvent)
                    .where(
                        CollectionAuditEvent.timestamp >= since,
                        CollectionAuditEvent.user_id.isnot(None),
                    )
                    .order_by(CollectionAuditEvent.timestamp.asc())
                )
            )
            .scalars()
            .all()
        )

        jobs: dict[uuid.UUID, list[CollectionAuditEvent]] = {}
        for ev in rows:
            jobs.setdefault(ev.request_id, []).append(ev)

        created = 0
        for request_id, events in jobs.items():
            if len(events) < self.MIN_STAGES:
                continue
            if owner_id is not None:
                owner = next((e.user_id for e in events if e.user_id is not None), None)
                if owner is None or owner != owner_id:
                    continue
            try:
                skill = await self._distill(events)
                if skill is not None:
                    db.add(skill)
                    created += 1
            except Exception as exc:
                logger.warning("skill.extract job=%s failed: %s", request_id, exc)

        if created:
            await db.commit()
        logger.info("skill.extract: %d skill(s) distilled from %d job(s)", created, len(jobs))
        return created

    async def _distill(self, events: list[CollectionAuditEvent]) -> LearnedSkill | None:
        """LLM-pass one audit trace → LearnedSkill draft, or None to skip."""
        trace = "\n".join(
            f"[{ev.timestamp.strftime('%m-%d %H:%M')}] {ev.stage}/{ev.action} → {ev.status} ({ev.duration_ms}ms)"
            for ev in events[:40]
        )
        try:
            import asyncio

            raw = await asyncio.wait_for(
                llm_gateway.chat_completion_non_stream(
                    messages=[
                        {"role": "system", "content": _SKILL_SYSTEM_PROMPT},
                        {"role": "user", "content": trace},
                    ],
                    temperature=0.2,
                    max_tokens=1000,
                ),
                timeout=30.0,
            )
            data = extract_first_json(raw)
            if not isinstance(data, dict) or data.get("skip"):
                return None
            title = str(data.get("title", "")).strip()
            trigger = str(data.get("trigger", "")).strip()
            steps = [str(s) for s in (data.get("steps") or []) if str(s).strip()]
            validation = [str(v) for v in (data.get("validation") or []) if str(v).strip()]
            if len(title) < 3 or not steps:
                return None
            owner = next((e.user_id for e in events if e.user_id is not None), None)
            return LearnedSkill(
                id=uuid.uuid4(),
                owner_id=owner,
                title=title[:500],
                trigger=trigger[:2000],
                steps=steps[:8],
                validation=validation[:6],
                source_type="collection",
                source_ref=str(events[0].request_id),
                status=SkillStatus.DRAFT.value,
                version=1,
            )
        except Exception as exc:
            logger.warning("skill.distill failed: %s", exc)
            return None


skill_extraction_service = SkillExtractionService()
