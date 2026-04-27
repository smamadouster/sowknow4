"""Smart Folder Skill Registry.

Skills are domain-specific sub-agents selected dynamically based on
classified intent.
"""

from app.services.smart_folder.skills.base import BaseSkill, SkillResult
from app.services.smart_folder.skills.custom_query import CustomQuerySkill
from app.services.smart_folder.skills.financial_analysis import FinancialAnalysisSkill
from app.services.smart_folder.skills.general_narrative import GeneralNarrativeSkill
from app.services.smart_folder.skills.legal_review import LegalReviewSkill
from app.services.smart_folder.skills.project_postmortem import ProjectPostmortemSkill
from app.services.smart_folder.skills.sentiment_tracker import SentimentTrackerSkill

SKILL_REGISTRY: dict[str, type[BaseSkill]] = {
    "general_narrative": GeneralNarrativeSkill,
    "financial_analysis": FinancialAnalysisSkill,
    "legal_review": LegalReviewSkill,
    "project_postmortem": ProjectPostmortemSkill,
    "sentiment_tracker": SentimentTrackerSkill,
    "custom_query": CustomQuerySkill,
}

__all__ = [
    "BaseSkill",
    "SkillResult",
    "SKILL_REGISTRY",
    "GeneralNarrativeSkill",
    "FinancialAnalysisSkill",
    "LegalReviewSkill",
    "ProjectPostmortemSkill",
    "SentimentTrackerSkill",
    "CustomQuerySkill",
]
