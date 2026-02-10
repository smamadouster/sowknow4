"""
Intent Parser Service for Smart Collections

Uses Gemini Flash to extract structured intent from natural language queries,
including keywords, date ranges, entities, and document types.
"""
import os
import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from enum import Enum
import re

from app.services.gemini_service import gemini_service, GeminiUsageMetadata
from app.models.user import UserRole

logger = logging.getLogger(__name__)


class DocumentType(Enum):
    """Document types that can be filtered"""
    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"
    TXT = "txt"
    MD = "md"
    JSON = "json"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    ALL = "all"


class DateRange(Enum):
    """Predefined date range types"""
    TODAY = "today"
    YESTERDAY = "yesterday"
    THIS_WEEK = "this_week"
    LAST_WEEK = "last_week"
    THIS_MONTH = "this_month"
    LAST_MONTH = "last_month"
    THIS_YEAR = "this_year"
    LAST_YEAR = "last_year"
    CUSTOM = "custom"


class ParsedIntent:
    """Structured intent from natural language query"""

    def __init__(
        self,
        query: str,
        keywords: List[str] = None,
        date_range: Optional[Dict[str, Any]] = None,
        entities: List[Dict[str, str]] = None,
        document_types: List[str] = None,
        collection_name: Optional[str] = None,
        confidence: float = 0.0,
        raw_response: str = ""
    ):
        self.query = query
        self.keywords = keywords or []
        self.date_range = date_range or {}
        self.entities = entities or []
        self.document_types = document_types or [DocumentType.ALL.value]
        self.collection_name = collection_name
        self.confidence = confidence
        self.raw_response = raw_response

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "query": self.query,
            "keywords": self.keywords,
            "date_range": self.date_range,
            "entities": self.entities,
            "document_types": self.document_types,
            "collection_name": self.collection_name,
            "confidence": self.confidence
        }

    def to_search_filter(self) -> Dict[str, Any]:
        """Convert to search filter for document queries"""
        filter_dict = {
            "keywords": self.keywords,
            "document_types": self.document_types
        }

        # Add date range if present
        if self.date_range:
            filter_dict["date_range"] = self._resolve_date_range()

        # Add entities for entity-based filtering
        if self.entities:
            filter_dict["entities"] = [e["name"] for e in self.entities]

        return filter_dict

    def _resolve_date_range(self) -> Optional[Dict[str, str]]:
        """Resolve date range to actual start/end dates"""
        if not self.date_range or self.date_range.get("type") == DateRange.CUSTOM.value:
            return self.date_range.get("custom")

        now = datetime.utcnow()
        range_type = self.date_range.get("type", "")

        if range_type == DateRange.TODAY.value:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif range_type == DateRange.YESTERDAY.value:
            end = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start = end - timedelta(days=1)
        elif range_type == DateRange.THIS_WEEK.value:
            start = now - timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(weeks=1)
        elif range_type == DateRange.LAST_WEEK.value:
            end = now - timedelta(days=now.weekday())
            end = end.replace(hour=0, minute=0, second=0, microsecond=0)
            start = end - timedelta(weeks=1)
        elif range_type == DateRange.THIS_MONTH.value:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # Move to first day of next month
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1, day=1)
            else:
                end = start.replace(month=start.month + 1, day=1)
        elif range_type == DateRange.LAST_MONTH.value:
            # First day of this month
            this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = this_month_start
            # First day of last month
            if this_month_start.month == 1:
                start = this_month_start.replace(year=this_month_start.year - 1, month=12, day=1)
            else:
                start = this_month_start.replace(month=this_month_start.month - 1, day=1)
        elif range_type == DateRange.THIS_YEAR.value:
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = start.replace(year=start.year + 1)
        elif range_type == DateRange.LAST_YEAR.value:
            this_year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = this_year_start
            start = this_year_start.replace(year=this_year_start.year - 1)
        else:
            return None

        return {
            "start": start.isoformat(),
            "end": end.isoformat()
        }


class IntentParserService:
    """Service for parsing natural language queries into structured intent"""

    def __init__(self):
        self.gemini_service = gemini_service
        self._intent_prompt_template = self._get_intent_prompt_template()

    def _get_intent_prompt_template(self) -> str:
        """Get the system prompt for intent parsing"""
        return """You are an intent parser for SOWKNOW, a legacy knowledge management system. Your task is to extract structured information from natural language queries about documents.

Analyze the user's query and extract:
1. **keywords**: Main search terms (2-5 most important words/phrases)
2. **date_range**: Time period if specified (today, yesterday, this_week, last_week, this_month, last_month, this_year, last_year, or custom with start/end dates)
3. **entities**: Named entities mentioned (people, organizations, locations, concepts)
4. **document_types**: Specific file types if mentioned (pdf, image, docx, txt, md, json, spreadsheet, presentation)
5. **collection_name**: A concise name for this collection (3-6 words)

IMPORTANT RULES:
- If no date is mentioned, use "all_time" for date_range type
- If no document type is mentioned, use ["all"]
- Extract entities even if not explicitly searched for (they may be in the documents)
- For collection_name, create a descriptive but concise title
- Respond ONLY with valid JSON, no explanations

Response format (JSON only):
```json
{
  "keywords": ["keyword1", "keyword2", "keyword3"],
  "date_range": {
    "type": "this_month|last_year|custom|all_time",
    "custom": {
      "start": "YYYY-MM-DD",
      "end": "YYYY-MM-DD"
    }
  },
  "entities": [
    {"type": "person|organization|location|concept", "name": "Entity Name"}
  ],
  "document_types": ["pdf", "image"],
  "collection_name": "Descriptive Collection Name"
}
```

Examples:

Query: "Show me all financial documents from 2023"
Response:
{
  "keywords": ["financial", "documents"],
  "date_range": {"type": "custom", "custom": {"start": "2023-01-01", "end": "2023-12-31"}},
  "entities": [],
  "document_types": ["all"],
  "collection_name": "Financial Documents 2023"
}

Query: "Photos from my vacation in France last summer"
Response:
{
  "keywords": ["vacation", "photos", "summer"],
  "date_range": {"type": "custom", "custom": {"start": "2024-06-01", "end": "2024-08-31"}},
  "entities": [{"type": "location", "name": "France"}],
  "document_types": ["image"],
  "collection_name": "France Vacation Photos"
}

Query: "All contracts with Company XYZ"
Response:
{
  "keywords": ["contracts"],
  "date_range": {"type": "all_time"},
  "entities": [{"type": "organization", "name": "Company XYZ"}],
  "document_types": ["all"],
  "collection_name": "Company XYZ Contracts"
}

Query: "Documents related to John's birthday last week"
Response:
{
  "keywords": ["birthday", "documents"],
  "date_range": {"type": "last_week"},
  "entities": [{"type": "person", "name": "John"}],
  "document_types": ["all"],
  "collection_name": "John's Birthday Documents"
}

Query: "Recent PDF reports about sales"
Response:
{
  "keywords": ["sales", "reports", "recent"],
  "date_range": {"type": "this_month"},
  "entities": [],
  "document_types": ["pdf"],
  "collection_name": "Recent Sales Reports"
}

Now parse the user's query:"""

    def _extract_current_year_context(self) -> str:
        """Get current year/month context for relative date parsing"""
        now = datetime.utcnow()
        return f"Current date: {now.strftime('%Y-%m-%d')}\nCurrent year: {now.year}\nCurrent month: {now.strftime('%B')}"

    def _fallback_parse(self, query: str) -> ParsedIntent:
        """
        Fallback rule-based parsing when Gemini is unavailable

        This ensures basic functionality even if the API is down.
        """
        query_lower = query.lower()
        keywords = []
        entities = []
        date_range = {"type": "all_time"}
        document_types = ["all"]
        collection_name = None

        # Extract keywords - remove common words and keep meaningful terms
        stop_words = {
            "show", "me", "all", "the", "a", "an", "from", "to", "with", "about",
            "related", "and", "or", "for", "in", "at", "on", "recent", "latest"
        }

        words = re.findall(r'\b\w+\b', query)
        keywords = [w for w in words if w.lower() not in stop_words and len(w) > 2]

        # Document type detection
        if any(word in query_lower for word in ["pdf", "document"]):
            document_types.append("pdf")
        if any(word in query_lower for word in ["photo", "image", "picture", "jpg", "png"]):
            document_types.append("image")
        if any(word in query_lower for word in ["spreadsheet", "excel", "xls"]):
            document_types.append("spreadsheet")
        if any(word in query_lower for word in ["presentation", "powerpoint", "slides"]):
            document_types.append("presentation")

        if len(document_types) > 1:
            document_types = ["all"]  # Multiple types specified means all

        # Date range detection
        if "today" in query_lower:
            date_range = {"type": "today"}
        elif "yesterday" in query_lower:
            date_range = {"type": "yesterday"}
        elif "this week" in query_lower or "current week" in query_lower:
            date_range = {"type": "this_week"}
        elif "last week" in query_lower:
            date_range = {"type": "last_week"}
        elif "this month" in query_lower or "current month" in query_lower:
            date_range = {"type": "this_month"}
        elif "last month" in query_lower:
            date_range = {"type": "last_month"}
        elif "this year" in query_lower or "current year" in query_lower:
            date_range = {"type": "this_year"}
        elif "last year" in query_lower:
            date_range = {"type": "last_year"}
        elif "recent" in query_lower:
            date_range = {"type": "this_month"}

        # Year-specific parsing (e.g., "2023", "from 2020")
        year_match = re.search(r'\b(20\d{2})\b', query)
        if year_match:
            year = int(year_match.group(1))
            now = datetime.utcnow()
            if year == now.year:
                date_range = {"type": "this_year"}
            elif year == now.year - 1:
                date_range = {"type": "last_year"}
            else:
                date_range = {
                    "type": "custom",
                    "custom": {
                        "start": f"{year}-01-01",
                        "end": f"{year}-12-31"
                    }
                }

        # Generate collection name from keywords
        if keywords:
            collection_name = " ".join(keywords[:4]).title()
        else:
            collection_name = "My Collection"

        return ParsedIntent(
            query=query,
            keywords=keywords[:10],  # Limit keywords
            date_range=date_range,
            entities=entities,
            document_types=document_types,
            collection_name=collection_name,
            confidence=0.6,  # Lower confidence for fallback
            raw_response="fallback_parsing"
        )

    async def parse_intent(
        self,
        query: str,
        user_language: str = "en"
    ) -> ParsedIntent:
        """
        Parse natural language query into structured intent

        Args:
            query: Natural language query from user
            user_language: User's preferred language (en/fr)

        Returns:
            ParsedIntent object with structured information
        """
        if not query or not query.strip():
            return ParsedIntent(
                query="",
                keywords=[],
                collection_name="Empty Collection",
                confidence=0.0
            )

        try:
            # Build the prompt
            context = self._extract_current_year_context()
            prompt = f"{context}\n\n{self._intent_prompt_template}\n\nQuery: {query}"

            messages = [
                {"role": "system", "content": "You are a precise JSON-only intent parser. Respond only with valid JSON, no explanations or markdown."},
                {"role": "user", "content": prompt}
            ]

            # Call Gemini API
            response_parts = []
            async for chunk in self.gemini_service.chat_completion(
                messages=messages,
                stream=False,
                temperature=0.3,  # Lower temperature for consistent parsing
                max_tokens=1024
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response_parts.append(chunk)

            response_text = "".join(response_parts).strip()

            # Extract JSON from response (handle markdown code blocks)
            json_text = self._extract_json(response_text)

            if json_text:
                intent_data = json.loads(json_text)

                # Build ParsedIntent from Gemini response
                return ParsedIntent(
                    query=query,
                    keywords=intent_data.get("keywords", []),
                    date_range=intent_data.get("date_range", {"type": "all_time"}),
                    entities=intent_data.get("entities", []),
                    document_types=intent_data.get("document_types", ["all"]),
                    collection_name=intent_data.get("collection_name", self._generate_fallback_name(query)),
                    confidence=0.9,  # High confidence for Gemini-parsed intent
                    raw_response=json_text
                )
            else:
                logger.warning(f"Failed to extract JSON from Gemini response: {response_text}")
                return self._fallback_parse(query)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse intent JSON: {e}")
            return self._fallback_parse(query)
        except Exception as e:
            logger.error(f"Error parsing intent: {e}", exc_info=True)
            return self._fallback_parse(query)

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON from response, handling markdown code blocks"""
        text = text.strip()

        # Remove markdown code blocks if present
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.rfind("```")
            if end > start:
                text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.rfind("```")
            if end > start:
                text = text[start:end].strip()

        # Try to find JSON object boundaries
        text = text.strip()
        if text.startswith("{"):
            # Find matching closing brace
            brace_count = 0
            end_pos = 0
            for i, char in enumerate(text):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = i + 1
                        break
            if end_pos > 0:
                return text[:end_pos]

        return None

    def _generate_fallback_name(self, query: str) -> str:
        """Generate a collection name from query when parsing fails"""
        # Take first 5 meaningful words
        words = query.split()
        meaningful = [w for w in words if len(w) > 2][:5]
        return " ".join(meaningful).title() if meaningful else "My Collection"

    async def parse_batch_intents(
        self,
        queries: List[str],
        user_language: str = "en"
    ) -> List[ParsedIntent]:
        """
        Parse multiple queries in batch

        Args:
            queries: List of natural language queries
            user_language: User's preferred language

        Returns:
            List of ParsedIntent objects
        """
        results = []
        for query in queries:
            intent = await self.parse_intent(query, user_language)
            results.append(intent)
        return results


# Global intent parser service instance
intent_parser_service = IntentParserService()
