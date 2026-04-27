"""Contract / Legal Document Analyser Skill.

Reviews NDAs, contracts, and compliance documents for clause extraction,
obligation listing, and risk flagging.
"""

import logging
import re
from typing import Any

from app.services.smart_folder.skills.base import BaseSkill, SkillResult
from app.services.smart_folder.tools.vault_search import vault_search

logger = logging.getLogger(__name__)


class LegalReviewSkill(BaseSkill):
    """Skill: Extract clauses, obligations, and risks from legal documents."""

    skill_id = "legal_review"
    skill_name = "Contract / Legal Document Analyser"
    description = "Clause extraction, obligation listing, and risk flagging from legal documents."
    required_tools = ["vault_search", "asset_reader"]

    # Simple keyword-based clause extraction (placeholder for LLM-based extraction)
    CLAUSE_PATTERNS = {
        "termination": [
            r"terminat(?:e|ion|ed|ing)",
            r"may be terminated",
            r"notice period",
            r"durée.*résiliation",
        ],
        "liability": [
            r"liabilit(?:y|ies)",
            r"responsabilité",
            r"indemnif(?:y|ication)",
            r"dommages",
        ],
        "confidentiality": [
            r"confidential",
            r"non-disclosure",
            r"secret",
            r"non divulgation",
        ],
        "payment": [
            r"payment",
            r"fee",
            r"compensation",
            r"rémunération",
            r"montant",
        ],
        "governing_law": [
            r"governing law",
            r"applicable law",
            r"droit applicable",
            r"juridiction",
        ],
    }

    async def analyze(self, parameters: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        db = context.get("db")
        user = context.get("user")
        entity_name = parameters.get("entity_name") or context.get("entity_name")
        query = parameters.get("query") or context.get("query")

        if not db or not user:
            return SkillResult(skill_id=self.skill_id, success=False, error="Missing db or user")

        try:
            search_query = f"{entity_name or query} contract NDA agreement legal clause"
            search_result = await vault_search.search(
                query=search_query,
                user=user,
                db=db,
                limit=10,
            )

            documents = search_result.get("results", [])
            clauses_found = {key: [] for key in self.CLAUSE_PATTERNS}
            risks = []

            for doc in documents:
                text = doc.get("text", "")
                for clause_type, patterns in self.CLAUSE_PATTERNS.items():
                    for pattern in patterns:
                        for match in re.finditer(pattern, text, re.IGNORECASE):
                            start = max(0, match.start() - 100)
                            end = min(len(text), match.end() + 100)
                            snippet = text[start:end].replace("\n", " ")
                            clauses_found[clause_type].append({
                                "source_asset_id": doc["asset_id"],
                                "source_name": doc["name"],
                                "snippet": snippet,
                                "matched_term": match.group(0),
                            })

                # Simple risk heuristics
                if "unlimited liability" in text.lower() or "responsabilité illimitée" in text.lower():
                    risks.append({
                        "level": "high",
                        "description": "Unlimited liability clause detected",
                        "source_asset_id": doc["asset_id"],
                    })
                if "no warranty" in text.lower() or "sans garantie" in text.lower():
                    risks.append({
                        "level": "medium",
                        "description": "No warranty clause detected",
                        "source_asset_id": doc["asset_id"],
                    })

            summary_lines = [f"Reviewed {len(documents)} legal document(s)."]
            for clause_type, occurrences in clauses_found.items():
                if occurrences:
                    summary_lines.append(f"- {clause_type.replace('_', ' ').title()}: {len(occurrences)} occurrence(s)")

            if risks:
                summary_lines.append("\nFlagged risks:")
                for risk in risks:
                    summary_lines.append(f"- [{risk['level'].upper()}] {risk['description']}")

            return SkillResult(
                skill_id=self.skill_id,
                success=True,
                text_summary="\n".join(summary_lines),
                data_tables=[{"clauses": clauses_found, "risks": risks}],
                citations=[
                    {"asset_id": d["asset_id"], "preview": d["text"][:200]}
                    for d in documents[:5]
                ],
                raw_output={
                    "document_count": len(documents),
                    "clauses_found": clauses_found,
                    "risks": risks,
                },
            )
        except Exception as exc:
            logger.exception("LegalReviewSkill failed: %s", exc)
            return SkillResult(skill_id=self.skill_id, success=False, error=str(exc))
