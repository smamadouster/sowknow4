"""Query Parser Service for Smart Folder v2.

Uses an LLM to extract structured parameters from a natural-language request.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.llm_router import llm_router, TaskTier

logger = logging.getLogger(__name__)


@dataclass
class ParsedQuery:
    """Structured output from query parsing."""

    primary_entity: str | None = None
    relationship_type: str | None = None  # personal, professional, institutional, project, general
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    focus_aspects: list[str] | None = None
    temporal_scope_description: str | None = None
    raw_json: dict[str, Any] | None = None


class QueryParserService:
    """Parse natural-language Smart Folder queries into structured parameters."""

    SYSTEM_PROMPT = """You are a query understanding engine for a digital vault application.
Your job is to parse a user's natural-language request into a structured JSON object.

Extract the following fields:
- primary_entity: The main person, organization, project, or concept the user is asking about (string or null)
- relationship_type: The type of relationship implied. MUST be one of: "personal", "professional", "institutional", "project", "general" (string or null)
- temporal_scope_description: How the user describes the time period, e.g. "last 5 years", "all time", "2020-2023" (string or null)
- time_range_start: ISO 8601 datetime if a start date can be inferred, else null
- time_range_end: ISO 8601 datetime if an end date can be inferred, else null
- focus_aspects: List of focus areas mentioned, e.g. ["financial", "legal", "disputes"] (list of strings or null)

Rules:
1. Output ONLY valid JSON. No markdown, no explanations.
2. If the entity is ambiguous, set primary_entity to the best guess and relationship_type to "general".
3. If no time period is mentioned, set temporal_scope_description to "all time" and dates to null.
4. Infer relationship_type from context words:
   - "friend", "family", "wife", "husband", "cousin" → "personal"
   - "colleague", "accountant", "lawyer", "employer" → "professional"
   - "bank", "company", "institution", "university" → "institutional"
   - "project", "initiative", "campaign" → "project"
5. Keep focus_aspects empty if none are specified.
"""

    async def parse(self, query: str) -> ParsedQuery:
        """Parse a natural language query into structured parameters.

        Args:
            query: The user's natural language request.

        Returns:
            ParsedQuery with extracted entity, relationship, time range, and focus.
        """
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": f'Parse this query: "{query}"'},
        ]

        try:
            response_chunks = []
            async for chunk in llm_router.generate_completion(
                messages=messages,
                query=query,
                stream=False,
                temperature=0.1,
                max_tokens=512,
                tier=TaskTier.SIMPLE,
            ):
                response_chunks.append(chunk)

            raw_response = "".join(response_chunks).strip()
            # Clean up markdown code fences if present
            if raw_response.startswith("```json"):
                raw_response = raw_response[7:]
            if raw_response.startswith("```"):
                raw_response = raw_response[3:]
            if raw_response.endswith("```"):
                raw_response = raw_response[:-3]
            raw_response = raw_response.strip()

            data = json.loads(raw_response)

            time_range_start = None
            time_range_end = None
            if data.get("time_range_start"):
                try:
                    time_range_start = datetime.fromisoformat(data["time_range_start"].replace("Z", "+00:00"))
                except ValueError:
                    pass
            if data.get("time_range_end"):
                try:
                    time_range_end = datetime.fromisoformat(data["time_range_end"].replace("Z", "+00:00"))
                except ValueError:
                    pass

            return ParsedQuery(
                primary_entity=data.get("primary_entity"),
                relationship_type=data.get("relationship_type"),
                time_range_start=time_range_start,
                time_range_end=time_range_end,
                focus_aspects=data.get("focus_aspects") or [],
                temporal_scope_description=data.get("temporal_scope_description"),
                raw_json=data,
            )
        except json.JSONDecodeError as exc:
            logger.warning("Query parser returned invalid JSON: %s — raw: %s", exc, raw_response)
            return ParsedQuery(raw_json={"error": "parse_failed", "raw": raw_response})
        except Exception as exc:
            logger.exception("Query parsing failed: %s", exc)
            return ParsedQuery(raw_json={"error": str(exc)})


# Module-level singleton
query_parser = QueryParserService()
