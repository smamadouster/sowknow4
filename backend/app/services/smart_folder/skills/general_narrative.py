"""General Relationship Narrator Skill.

Default skill for personal/professional/institutional summaries.
Uses the Phase 2 core pipeline under the hood.
"""

import logging
from typing import Any

from app.services.smart_folder.skills.base import BaseSkill, SkillResult
from app.services.smart_folder.analysis import analysis_service
from app.services.smart_folder.report_generator import report_generator
from app.services.smart_folder.retrieval import retrieval_service

logger = logging.getLogger(__name__)


class GeneralNarrativeSkill(BaseSkill):
    """Skill: General relationship narrative with timelines, patterns, and lessons."""

    skill_id = "general_narrative"
    skill_name = "General Relationship Narrator"
    description = (
        "Default skill for personal, professional, and institutional summaries. "
        "Produces timelines, pattern extraction, and lesson integration."
    )

    async def analyze(self, parameters: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        """Run the general narrative pipeline."""
        db = context.get("db")
        user = context.get("user")
        entity_id = parameters.get("entity_id") or context.get("entity_id")
        entity_name = parameters.get("entity_name") or context.get("entity_name")
        relationship_type = parameters.get("relationship_type") or context.get("relationship_type")
        query_text = parameters.get("query") or context.get("query")
        time_start = parameters.get("time_range_start") or context.get("time_range_start")
        time_end = parameters.get("time_range_end") or context.get("time_range_end")
        focus = parameters.get("focus_aspects") or context.get("focus_aspects")

        if not db or not user:
            return SkillResult(
                skill_id=self.skill_id,
                success=False,
                error="Missing db or user in context",
            )

        try:
            # Retrieval
            retrieval = await retrieval_service.retrieve(
                db=db,
                user=user,
                query_text=query_text,
                entity_id=entity_id,
                entity_name=entity_name,
                time_range_start=time_start,
                time_range_end=time_end,
                focus_aspects=focus,
            )

            # Analysis
            analysis = await analysis_service.analyze(
                db=db,
                entity_id=entity_id,
                time_range_start=time_start,
                time_range_end=time_end,
                focus_aspects=focus,
            )

            # Report generation
            report = await report_generator.generate(
                query_text=query_text,
                entity_name=entity_name,
                relationship_type=relationship_type,
                retrieval_context=retrieval,
                analysis_result=analysis,
            )

            return SkillResult(
                skill_id=self.skill_id,
                success=True,
                text_summary=report.summary,
                citations=[
                    {
                        "asset_id": str(aid),
                        "preview": retrieval.primary_assets[i].chunk_text if i < len(retrieval.primary_assets) else "",
                    }
                    for i, aid in enumerate(report.source_asset_ids)
                ],
                raw_output={
                    "title": report.title,
                    "summary": report.summary,
                    "timeline": report.timeline,
                    "patterns": report.patterns,
                    "trends": report.trends,
                    "issues": report.issues,
                    "learnings": report.learnings,
                    "recommendations": report.recommendations,
                    "raw_markdown": report.raw_markdown,
                    "citation_index": report.citation_index,
                },
            )
        except Exception as exc:
            logger.exception("GeneralNarrativeSkill failed: %s", exc)
            return SkillResult(
                skill_id=self.skill_id,
                success=False,
                error=str(exc),
            )
