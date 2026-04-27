"""Unstructured Deep Search Skill.

Fallback for novel requests. Uses vector+keyword search and LLM-powered Q&A over raw assets.
"""

import logging
from typing import Any

from app.services.smart_folder.skills.base import BaseSkill, SkillResult
from app.services.smart_folder.tools.vault_search import vault_search

logger = logging.getLogger(__name__)


class CustomQuerySkill(BaseSkill):
    """Skill: Deep search and Q&A over raw assets for novel queries."""

    skill_id = "custom_query"
    skill_name = "Unstructured Deep Search"
    description = "Fallback skill for requests that don't match any specialized domain."
    required_tools = ["vault_search"]

    async def analyze(self, parameters: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        db = context.get("db")
        user = context.get("user")
        query = parameters.get("query") or context.get("query")

        if not db or not user:
            return SkillResult(skill_id=self.skill_id, success=False, error="Missing db or user")

        try:
            search_result = await vault_search.search(
                query=query,
                user=user,
                db=db,
                limit=20,
            )

            documents = search_result.get("results", [])

            summary = f"Deep search returned {len(documents)} result(s) for: {query}"

            return SkillResult(
                skill_id=self.skill_id,
                success=True,
                text_summary=summary,
                citations=[
                    {"asset_id": d["asset_id"], "preview": d["text"][:300]}
                    for d in documents[:8]
                ],
                raw_output={
                    "document_count": len(documents),
                    "query": query,
                },
            )
        except Exception as exc:
            logger.exception("CustomQuerySkill failed: %s", exc)
            return SkillResult(skill_id=self.skill_id, success=False, error=str(exc))
