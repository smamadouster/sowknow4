"""Intent Classifier + Planner for the Smart Folder Agent.

Uses an LLM to classify intent and decompose the request into a JSON task plan
referencing skill IDs from the Skill Registry.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.llm_router import llm_router, TaskTier
from app.services.smart_folder.skills import SKILL_REGISTRY

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    """A single step in the execution plan."""

    step_id: str
    skill_id: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)


@dataclass
class Plan:
    """Full execution plan produced by the planner."""

    intent: str
    primary_skill: str
    steps: list[PlanStep]
    reasoning: str = ""


class Planner:
    """Classify intent and generate a skill execution plan."""

    SYSTEM_PROMPT = """You are the planner for a Smart Folder Agent.
Your job is to classify the user's request and output a JSON execution plan.

Available skills:
- general_narrative: Default for personal/professional/institutional summaries
- financial_analysis: For balance sheet, P&L, cash flow, financial health queries
- legal_review: For contract review, NDA analysis, compliance checks
- project_postmortem: For project retrospectives and milestone reviews
- sentiment_tracker: For communication sentiment over time
- custom_query: Fallback for novel or unstructured requests

Output ONLY valid JSON with this structure:
{
  "intent": "brief description of classified intent",
  "primary_skill": "one of the skill IDs above",
  "reasoning": "why this skill was chosen",
  "steps": [
    {
      "step_id": "1",
      "skill_id": "skill_name",
      "description": "what this step does",
      "parameters": { "key": "value" },
      "dependencies": []
    }
  ]
}

Rules:
1. If the query mentions "balance sheet", "P&L", "financial health", "cash flow", "ratio" → financial_analysis
2. If the query mentions "contract", "NDA", "legal", "clause", "compliance" → legal_review
3. If the query mentions "project", "retrospective", "how did X go", "milestone" → project_postmortem
4. If the query mentions "sentiment", "tone", "communication health" → sentiment_tracker
5. Otherwise → general_narrative (default) or custom_query if completely novel
6. Output ONLY JSON. No markdown, no explanations outside the JSON.
"""

    async def plan(
        self,
        query: str,
        entity_name: str | None = None,
        relationship_type: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> Plan:
        """Generate an execution plan for the given query.

        Args:
            query: Natural language request.
            entity_name: Resolved entity name.
            relationship_type: Detected relationship type.
            context: Optional additional context.

        Returns:
            Plan with classified intent and ordered steps.
        """
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Query: {query}\nEntity: {entity_name or 'None'}\nRelationship: {relationship_type or 'None'}",
            },
        ]

        try:
            response_chunks = []
            async for chunk in llm_router.generate_completion(
                messages=messages,
                query=query,
                stream=False,
                temperature=0.1,
                max_tokens=1024,
                tier=TaskTier.SIMPLE,
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

            data = json.loads(raw_response)

            steps = []
            for step_data in data.get("steps", []):
                steps.append(
                    PlanStep(
                        step_id=step_data.get("step_id", "1"),
                        skill_id=step_data.get("skill_id", "general_narrative"),
                        description=step_data.get("description", ""),
                        parameters=step_data.get("parameters", {}),
                        dependencies=step_data.get("dependencies", []),
                    )
                )

            primary_skill = data.get("primary_skill", "general_narrative")
            # Validate skill exists
            if primary_skill not in SKILL_REGISTRY:
                logger.warning("Planner chose unknown skill '%s', falling back to general_narrative", primary_skill)
                primary_skill = "general_narrative"
                steps = [PlanStep(step_id="1", skill_id="general_narrative", description="Fallback narrative generation")]

            return Plan(
                intent=data.get("intent", "unknown"),
                primary_skill=primary_skill,
                steps=steps,
                reasoning=data.get("reasoning", ""),
            )
        except json.JSONDecodeError as exc:
            logger.warning("Planner returned invalid JSON: %s — raw: %s", exc, raw_response)
            return Plan(
                intent="unknown",
                primary_skill="general_narrative",
                steps=[PlanStep(step_id="1", skill_id="general_narrative", description="Fallback due to parse error")],
                reasoning="Planner JSON parse failed",
            )
        except Exception as exc:
            logger.exception("Planning failed: %s", exc)
            return Plan(
                intent="unknown",
                primary_skill="general_narrative",
                steps=[PlanStep(step_id="1", skill_id="general_narrative", description="Fallback due to error")],
                reasoning=str(exc),
            )


# Module-level singleton
planner = Planner()
