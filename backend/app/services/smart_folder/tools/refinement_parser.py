"""Intent Refiner Tool.

Used in iterative queries to merge new constraints with the original plan.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RefinementParserTool:
    """Tool: Merge refinement constraints with an existing query plan."""

    def merge(
        self,
        original_query: str,
        refinement_query: str,
        original_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Merge a refinement into the original plan.

        Returns an updated plan with new constraints applied.
        """
        plan = dict(original_plan) if original_plan else {}

        refinement_lower = refinement_query.lower()

        # Detect temporal refinements
        if any(kw in refinement_lower for kw in ["last year", "past year", "dernier an", "année dernière"]):
            plan["time_range"] = "last_year"
        elif any(kw in refinement_lower for kw in ["last 5 years", "5 years", "5 ans"]):
            plan["time_range"] = "last_5_years"
        elif any(kw in refinement_lower for kw in ["2020", "2021", "2022", "2023", "2024"]):
            plan["time_range"] = "custom"

        # Detect focus refinements
        focus_keywords = {
            "financial": ["financial", "finance", "bilan", "comptable", "balance sheet"],
            "legal": ["legal", "contract", "law", "juridique", "contrat"],
            "dispute": ["dispute", "conflict", "litige", "réclamation"],
            "health": ["health", "medical", "santé", "médical"],
            "project": ["project", "projet", "deliverable"],
        }

        detected_focus = []
        for focus, keywords in focus_keywords.items():
            if any(kw in refinement_lower for kw in keywords):
                detected_focus.append(focus)

        if detected_focus:
            existing_focus = set(plan.get("focus_aspects", []))
            existing_focus.update(detected_focus)
            plan["focus_aspects"] = list(existing_focus)

        plan["refinement_applied"] = refinement_query
        plan["combined_query"] = f"{original_query} | Refinement: {refinement_query}"

        return plan


refinement_parser = RefinementParserTool()
