"""Smart Folder Agent Runner.

High-level orchestrator that ties together the agentic pipeline:
1. Parse query (or reuse stored context)
2. Plan (classify intent + decompose)
3. Execute skills
4. Synthesize final report
5. Persist results
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.smart_folder import SmartFolder, SmartFolderReport, SmartFolderStatus
from app.models.user import User
from app.services.smart_folder.agent.executor import SkillExecutor
from app.services.smart_folder.agent.planner import Planner
from app.services.smart_folder.agent.synthesizer import Synthesizer
from app.services.smart_folder.entity_resolver import entity_resolver
from app.services.smart_folder.query_parser import query_parser
from app.services.smart_folder.report_generator import report_generator

logger = logging.getLogger(__name__)


class SmartFolderAgentRunner:
    """Run the full agentic Smart Folder pipeline."""

    def __init__(self) -> None:
        self.planner = Planner()
        self.executor = SkillExecutor()
        self.synthesizer = Synthesizer()

    async def run(
        self,
        db: AsyncSession,
        user: User,
        query: str,
        smart_folder: SmartFolder,
        refinement_query: str | None = None,
    ) -> dict[str, Any]:
        """Run the agentic pipeline end-to-end.

        Args:
            db: Async database session.
            user: Current user.
            query: Natural language query (original or combined with refinement).
            smart_folder: The SmartFolder record to update.
            refinement_query: Optional refinement constraint.

        Returns:
            Dict with report data and metadata.
        """
        # --- Step 1: Parse Query (if new) ---
        entity_id = smart_folder.entity_id
        entity_name = smart_folder.entity.name if smart_folder.entity else None
        relationship_type = smart_folder.relationship_type

        if not entity_id:
            parsed = await query_parser.parse(query)
            if parsed.primary_entity:
                smart_folder.query_text = query
                if parsed.relationship_type:
                    smart_folder.relationship_type = parsed.relationship_type
                if parsed.time_range_start:
                    smart_folder.time_range_start = parsed.time_range_start
                if parsed.time_range_end:
                    smart_folder.time_range_end = parsed.time_range_end
                if parsed.focus_aspects:
                    smart_folder.focus_aspects = parsed.focus_aspects
                await db.commit()

            # Resolve entity
            if parsed.primary_entity:
                resolution = await entity_resolver.resolve(db, parsed.primary_entity)
                if resolution.entity:
                    entity_id = resolution.entity.id
                    entity_name = resolution.entity.name
                    smart_folder.entity_id = entity_id
                    smart_folder.name = f"Smart Folder: {entity_name}"
                    await db.commit()
                else:
                    smart_folder.status = SmartFolderStatus.FAILED
                    smart_folder.error_message = (
                        f"Entity '{parsed.primary_entity}' not recognised."
                    )
                    await db.commit()
                    return {
                        "smart_folder_id": str(smart_folder.id),
                        "status": "failed",
                        "error": smart_folder.error_message,
                        "entity_not_recognised": True,
                        "candidates": [
                            {"id": str(c.id), "name": c.name, "type": c.entity_type.value}
                            for c in (resolution.candidates or [])
                        ],
                    }

        # --- Step 2: Plan ---
        plan = await self.planner.plan(
            query=query,
            entity_name=entity_name,
            relationship_type=relationship_type,
        )

        logger.info(
            "Agent plan | intent=%s primary_skill=%s steps=%d sf=%s",
            plan.intent,
            plan.primary_skill,
            len(plan.steps),
            smart_folder.id,
        )

        # --- Step 3: Execute Skills ---
        execution_context = {
            "db": db,
            "user": user,
            "query": query,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "relationship_type": relationship_type,
            "time_range_start": smart_folder.time_range_start,
            "time_range_end": smart_folder.time_range_end,
            "focus_aspects": smart_folder.focus_aspects,
        }

        skill_results = await self.executor.execute(plan, execution_context)

        # Check if all skills failed
        all_failed = all(not r.success for r in skill_results.values())
        if all_failed:
            errors = ", ".join(
                f"{sid}: {r.error}" for sid, r in skill_results.items() if not r.success
            )
            smart_folder.status = SmartFolderStatus.FAILED
            smart_folder.error_message = f"All skills failed: {errors}"
            await db.commit()
            return {
                "smart_folder_id": str(smart_folder.id),
                "status": "failed",
                "error": smart_folder.error_message,
            }

        # --- Step 4: Synthesize ---
        # If only one skill (general_narrative) succeeded and returned a full report,
        # we can use its raw_output directly to avoid an extra LLM call.
        successful_results = [r for r in skill_results.values() if r.success]

        if (
            len(successful_results) == 1
            and successful_results[0].skill_id == "general_narrative"
            and successful_results[0].raw_output
        ):
            synthesized = successful_results[0].raw_output
        else:
            synthesized = await self.synthesizer.synthesize(
                query=query,
                entity_name=entity_name,
                relationship_type=relationship_type,
                skill_results=skill_results,
            )

        # --- Step 5: Build citation index from all skill citations ---
        citation_index: dict[str, dict[str, Any]] = {}
        source_asset_ids: list[str] = []
        counter = 1
        for result in successful_results:
            for cite in result.citations:
                aid = cite.get("asset_id")
                if aid and aid not in citation_index:
                    citation_index[aid] = {
                        "number": counter,
                        "asset_id": aid,
                        "preview": cite.get("preview", "")[:200],
                        "document_name": cite.get("document_name", "Unknown"),
                    }
                    source_asset_ids.append(aid)
                    counter += 1

        # Renumber citations in synthesized text
        def renumber(obj: Any) -> Any:
            if isinstance(obj, str):
                for aid, entry in citation_index.items():
                    obj = obj.replace(f"[{aid}]", f"[{entry['number']}]")
                return obj
            if isinstance(obj, list):
                return [renumber(v) for v in obj]
            if isinstance(obj, dict):
                return {k: renumber(v) for k, v in obj.items()}
            return obj

        synthesized = renumber(synthesized)

        # --- Step 6: Persist Report ---
        report = SmartFolderReport(
            smart_folder_id=smart_folder.id,
            generated_content={
                "title": synthesized.get("title", ""),
                "summary": synthesized.get("summary", ""),
                "timeline": synthesized.get("timeline", []),
                "patterns": synthesized.get("patterns", []),
                "trends": synthesized.get("trends", []),
                "issues": synthesized.get("issues", []),
                "learnings": synthesized.get("learnings", []),
                "recommendations": synthesized.get("recommendations", []),
                "raw_markdown": synthesized.get("raw_markdown", ""),
            },
            source_asset_ids=source_asset_ids,
            citation_index=citation_index,
            refinement_query=refinement_query,
        )
        db.add(report)

        smart_folder.status = SmartFolderStatus.READY
        smart_folder.error_message = None
        await db.commit()
        await db.refresh(report)

        return {
            "smart_folder_id": str(smart_folder.id),
            "report_id": str(report.id),
            "status": "completed",
            "title": synthesized.get("title", ""),
            "summary": synthesized.get("summary", ""),
            "source_count": len(source_asset_ids),
            "skills_used": [r.skill_id for r in successful_results],
        }


# Module-level singleton
agent_runner = SmartFolderAgentRunner()
