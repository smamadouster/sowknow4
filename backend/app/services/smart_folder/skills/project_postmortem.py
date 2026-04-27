"""Project Retrospective Skill.

Milestone vs actual comparison, blocker analysis, and team contribution summary.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.milestone import Milestone
from app.services.smart_folder.skills.base import BaseSkill, SkillResult
from app.services.smart_folder.tools.vault_search import vault_search

logger = logging.getLogger(__name__)


class ProjectPostmortemSkill(BaseSkill):
    """Skill: Project retrospective with milestone comparison and blocker analysis."""

    skill_id = "project_postmortem"
    skill_name = "Project Retrospective"
    description = "Milestone vs actual comparison, blocker analysis, and team contribution summary."
    required_tools = ["vault_search"]

    async def analyze(self, parameters: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        db = context.get("db")
        user = context.get("user")
        entity_name = parameters.get("entity_name") or context.get("entity_name")
        query = parameters.get("query") or context.get("query")

        if not db or not user:
            return SkillResult(skill_id=self.skill_id, success=False, error="Missing db or user")

        try:
            search_query = f"{entity_name or query} project milestone deliverable blocker team"
            search_result = await vault_search.search(
                query=search_query,
                user=user,
                db=db,
                limit=15,
            )

            documents = search_result.get("results", [])

            # Fetch milestones for this entity if it exists
            milestones = []
            entity_id = parameters.get("entity_id") or context.get("entity_id")
            if entity_id and isinstance(db, AsyncSession):
                stmt = select(Milestone).where(Milestone.entity_id == entity_id).order_by(Milestone.date)
                ms_result = await db.execute(stmt)
                milestones = [
                    {
                        "title": m.title,
                        "date": m.date.isoformat() if m.date else None,
                        "description": m.description,
                        "importance": m.importance,
                    }
                    for m in ms_result.scalars().all()
                ]

            # Simple blocker detection heuristic
            blocker_keywords = ["blocker", "blocked", "delay", "overdue", "risk", "issue", "problem"]
            blockers = []
            for doc in documents:
                text_lower = doc.get("text", "").lower()
                for kw in blocker_keywords:
                    if kw in text_lower:
                        blockers.append({
                            "source_asset_id": doc["asset_id"],
                            "source_name": doc["name"],
                            "keyword": kw,
                        })
                        break

            summary_lines = [f"Reviewed {len(documents)} project document(s)."]
            if milestones:
                summary_lines.append(f"Found {len(milestones)} milestone(s):")
                for ms in milestones:
                    summary_lines.append(f"- {ms['date'] or 'Undated'}: {ms['title']}")

            if blockers:
                summary_lines.append(f"\nDetected {len(blockers)} potential blocker reference(s).")

            return SkillResult(
                skill_id=self.skill_id,
                success=True,
                text_summary="\n".join(summary_lines),
                data_tables=[{"milestones": milestones, "blockers": blockers}],
                citations=[
                    {"asset_id": d["asset_id"], "preview": d["text"][:200]}
                    for d in documents[:5]
                ],
                raw_output={
                    "document_count": len(documents),
                    "milestones": milestones,
                    "blockers": blockers,
                },
            )
        except Exception as exc:
            logger.exception("ProjectPostmortemSkill failed: %s", exc)
            return SkillResult(skill_id=self.skill_id, success=False, error=str(exc))
