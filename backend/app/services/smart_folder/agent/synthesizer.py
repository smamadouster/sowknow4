"""Final Synthesizer for the Smart Folder Agent.

Merges all skill outputs into a final Smart Folder report with strict
citation rules.
"""

import json
import logging
from typing import Any

from app.services.llm_router import llm_router, TaskTier
from app.services.smart_folder.skills.base import SkillResult

logger = logging.getLogger(__name__)


class Synthesizer:
    """Synthesize skill results into a final report."""

    SYSTEM_PROMPT_TEMPLATE = """You are the final synthesizer for a Smart Folder Agent.
You have received outputs from multiple specialized skills.
Your job is to merge them into a single coherent, structured report.

{TONE_INSTRUCTION}

Rules:
1. Use ONLY the provided skill outputs. Do NOT invent facts.
2. Every factual sentence MUST end with a citation marker like [AssetID].
3. If a skill returned visualisations or tables, reference them in the text.
4. If a skill failed, note it briefly and rely on other skills.
5. Output valid JSON with this structure:
{{
  "title": "...",
  "summary": "...",
  "timeline": [...],
  "patterns": [...],
  "trends": [...],
  "issues": [...],
  "learnings": [...],
  "recommendations": [...],
  "raw_markdown": "Full markdown report with inline citations"
}}
"""

    async def synthesize(
        self,
        query: str,
        entity_name: str | None,
        relationship_type: str | None,
        skill_results: dict[str, SkillResult],
    ) -> dict[str, Any]:
        """Merge skill outputs into a final report.

        Args:
            query: Original user query.
            entity_name: Resolved entity name.
            relationship_type: Detected relationship type.
            skill_results: Mapping of step_id → SkillResult.

        Returns:
            Structured report dict.
        """
        from app.services.smart_folder.report_generator import ReportGeneratorService

        tone_map = ReportGeneratorService.TONE_INSTRUCTIONS
        tone_instruction = tone_map.get(relationship_type or "general", tone_map["general"])
        system_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(TONE_INSTRUCTION=tone_instruction)

        # Build context from skill outputs
        context_parts = [
            f"QUERY: {query}",
            f"ENTITY: {entity_name or 'None'}",
            "",
            "=== SKILL OUTPUTS ===",
        ]

        all_citations = []
        for step_id, result in skill_results.items():
            context_parts.append(f"\n--- Skill: {result.skill_id} (step {step_id}) ---")
            context_parts.append(f"Summary: {result.text_summary}")
            if result.data_tables:
                context_parts.append(f"Tables: {json.dumps(result.data_tables, default=str)[:800]}")
            if result.visualisations:
                context_parts.append(f"Visualisations: {len(result.visualisations)} chart(s)")
            if result.error:
                context_parts.append(f"ERROR: {result.error}")
            all_citations.extend(result.citations)

        context_parts.append("\n=== CITATIONS ===")
        for cite in all_citations:
            context_parts.append(f"[{cite.get('asset_id')}]: {cite.get('preview', '')[:200]}")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n".join(context_parts)},
        ]

        try:
            response_chunks = []
            async for chunk in llm_router.generate_completion(
                messages=messages,
                query=query,
                stream=False,
                temperature=0.3,
                max_tokens=4096,
                tier=TaskTier.COMPLEX,
            ):
                response_chunks.append(chunk)

            raw_response = "".join(response_chunks).strip()
            if raw_response.startswith("```json"):
                raw_response = raw_response[7:]
            if raw_response.startswith("```"):
                raw_response = raw_response[3:]
            if raw_response.endswith("```"):
                raw_response = raw_response[:-3]
            raw_response = raw_response.strip()

            return json.loads(raw_response)
        except json.JSONDecodeError as exc:
            logger.warning("Synthesizer returned invalid JSON: %s — raw: %s", exc, raw_response)
            return {
                "title": f"Smart Folder: {entity_name or query}",
                "summary": "The report could not be fully synthesized. Skill outputs are provided below.",
                "raw_markdown": raw_response,
            }
        except Exception as exc:
            logger.exception("Synthesis failed: %s", exc)
            return {
                "title": f"Smart Folder: {entity_name or query}",
                "summary": f"Report synthesis failed: {exc}",
                "raw_markdown": "",
            }


# Module-level singleton
synthesizer = Synthesizer()
