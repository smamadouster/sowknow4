"""Communication Sentiment Analyser Skill.

Overlays sentiment on email/SMS threads. Polarity over time, relationship health index.
"""

import logging
import re
from typing import Any

from app.services.smart_folder.skills.base import BaseSkill, SkillResult
from app.services.smart_folder.tools.vault_search import vault_search

logger = logging.getLogger(__name__)


class SentimentTrackerSkill(BaseSkill):
    """Skill: Track sentiment polarity over time in communication threads."""

    skill_id = "sentiment_tracker"
    skill_name = "Communication Sentiment Analyser"
    description = "Sentiment polarity over time and relationship health index from communications."
    required_tools = ["vault_search"]

    # Simple lexicon-based sentiment (placeholder for a real model)
    POSITIVE_WORDS = {
        "good", "great", "excellent", "happy", "pleased", "thank", "thanks", "appreciate",
        "love", "wonderful", "fantastic", "success", "successful", "agree", "positive",
        "bon", "bien", "merci", "excellent", "heureux", "satisfait", "succès",
    }
    NEGATIVE_WORDS = {
        "bad", "terrible", "angry", "disappointed", "frustrated", "complaint", "unhappy",
        "wrong", "error", "fail", "failure", "refuse", "reject", "negative", "problem",
        "mauvais", "terrible", "fâché", "déçu", "frustré", "plainte", "erreur", "échec",
    }

    def _score_text(self, text: str) -> float:
        """Return a simple sentiment score between -1 and 1."""
        words = re.findall(r"\b\w+\b", text.lower())
        pos = sum(1 for w in words if w in self.POSITIVE_WORDS)
        neg = sum(1 for w in words if w in self.NEGATIVE_WORDS)
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total

    async def analyze(self, parameters: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        db = context.get("db")
        user = context.get("user")
        entity_name = parameters.get("entity_name") or context.get("entity_name")
        query = parameters.get("query") or context.get("query")

        if not db or not user:
            return SkillResult(skill_id=self.skill_id, success=False, error="Missing db or user")

        try:
            search_query = f"{entity_name or query} email message communication thread"
            search_result = await vault_search.search(
                query=search_query,
                user=user,
                db=db,
                limit=20,
            )

            documents = search_result.get("results", [])
            scores = []
            timeline = []

            for doc in documents:
                text = doc.get("text", "")
                score = self._score_text(text)
                scores.append(score)
                timeline.append({
                    "asset_id": doc["asset_id"],
                    "name": doc["name"],
                    "score": round(score, 3),
                })

            if scores:
                avg_score = sum(scores) / len(scores)
                health = "healthy" if avg_score > 0.1 else "strained" if avg_score < -0.1 else "neutral"
            else:
                avg_score = 0.0
                health = "unknown"

            summary = (
                f"Analysed {len(documents)} communication(s). "
                f"Average sentiment: {avg_score:+.2f} ({health})."
            )

            return SkillResult(
                skill_id=self.skill_id,
                success=True,
                text_summary=summary,
                data_tables=[{"timeline": timeline, "average_score": round(avg_score, 3), "health": health}],
                citations=[
                    {"asset_id": d["asset_id"], "preview": d["text"][:200]}
                    for d in documents[:5]
                ],
                raw_output={
                    "document_count": len(documents),
                    "average_sentiment": round(avg_score, 3),
                    "health_index": health,
                    "timeline": timeline,
                },
            )
        except Exception as exc:
            logger.exception("SentimentTrackerSkill failed: %s", exc)
            return SkillResult(skill_id=self.skill_id, success=False, error=str(exc))
