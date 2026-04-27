"""Report Generator Service for Smart Folder v2.

Builds structured LLM context, generates a cited report with tone adaptation,
and post-processes citation markers into a numbered index.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.services.llm_router import llm_router, TaskTier
from app.services.smart_folder.analysis import AnalysisResult
from app.services.smart_folder.retrieval import RetrievedAsset, RetrievalContext

logger = logging.getLogger(__name__)


@dataclass
class GeneratedReport:
    """Final generated Smart Folder report with citations."""

    title: str = ""
    summary: str = ""
    timeline: list[dict[str, Any]] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    trends: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    learnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    raw_markdown: str = ""
    citation_index: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_asset_ids: list[UUID] = field(default_factory=list)


class ReportGeneratorService:
    """Generate a structured, cited Smart Folder report."""

    # Tone instructions per relationship type
    TONE_INSTRUCTIONS = {
        "personal": (
            "Use a warm, personal tone. Highlight shared experiences, emotional significance, "
            "photos/events where mentioned, and the human side of the relationship. "
            "Avoid cold or financial language unless explicitly requested."
        ),
        "professional": (
            "Use a formal, business-like tone. Focus on work delivered, reliability, "
            "contractual outcomes, professional milestones, and performance. "
            "Be concise and factual."
        ),
        "institutional": (
            "Use a factual, analytical tone. Emphasize financial details, contract terms, "
            "risk assessment, compliance, and institutional metrics. "
            "Be precise and data-driven."
        ),
        "project": (
            "Use an outcome-oriented tone. Focus on milestones, deliverables, blockers, "
            "team contributions, timeline adherence, and project health. "
            "Include quantitative progress where available."
        ),
        "general": (
            "Use a balanced, informative tone. Cover the breadth of the relationship or topic "
            "without over-indexing on any single dimension."
        ),
    }

    SYSTEM_PROMPT_TEMPLATE = """You are a validity-checked report generator for a digital vault.
Your task is to produce a structured report about a user's relationship or topic,
using ONLY the provided context. You must NEVER invent facts not present in the context.

{TONE_INSTRUCTION}

Rules:
1. Use ONLY the provided context (retrieved assets, milestones, patterns, trends, issues, learnings).
2. Every factual sentence MUST end with a citation marker like [AssetID].
   Example: "The account was opened in March 2010 [doc_123e4567]."
3. If a fact has multiple sources, use multiple markers: [doc_123e4567][doc_abcdef].
4. If there is insufficient data for a section, state "Insufficient data" and omit the section.
5. If evidence is contradictory, note the contradiction and cite both sources.
6. Do NOT include a "References" or "Sources" section — citations are inline only.
7. Output valid JSON with the following structure:

{{
  "title": "Smart Folder: ...",
  "summary": "2-3 sentence overview with citations",
  "timeline": [
    {{"date": "YYYY-MM-DD", "title": "...", "description": "... [AssetID]"}}
  ],
  "patterns": ["Pattern description [AssetID]", ...],
  "trends": ["Trend description [AssetID]", ...],
  "issues": ["Issue description [AssetID]", ...],
  "learnings": ["Learning description [AssetID]", ...],
  "recommendations": ["Recommendation [AssetID]", ...],
  "raw_markdown": "Full report as markdown with inline citations"
}}
"""

    async def generate(
        self,
        query_text: str,
        entity_name: str | None,
        relationship_type: str | None,
        retrieval_context: RetrievalContext,
        analysis_result: AnalysisResult,
    ) -> GeneratedReport:
        """Generate a cited Smart Folder report.

        Args:
            query_text: Original user query.
            entity_name: Resolved canonical entity name.
            relationship_type: Detected relationship type.
            retrieval_context: Retrieved vault assets.
            analysis_result: Structured analysis findings.

        Returns:
            GeneratedReport with structured content and citation index.
        """
        tone_instruction = self.TONE_INSTRUCTIONS.get(
            relationship_type or "general", self.TONE_INSTRUCTIONS["general"]
        )
        system_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(TONE_INSTRUCTION=tone_instruction)

        context = self._build_context_string(
            entity_name=entity_name,
            query_text=query_text,
            retrieval_context=retrieval_context,
            analysis_result=analysis_result,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ]

        try:
            response_chunks = []
            async for chunk in llm_router.generate_completion(
                messages=messages,
                query=query_text,
                stream=False,
                temperature=0.3,
                max_tokens=4096,
                tier=TaskTier.COMPLEX,
            ):
                response_chunks.append(chunk)

            raw_response = "".join(response_chunks).strip()
            # Clean markdown fences
            if raw_response.startswith("```json"):
                raw_response = raw_response[7:]
            if raw_response.startswith("```"):
                raw_response = raw_response[3:]
            if raw_response.endswith("```"):
                raw_response = raw_response[:-3]
            raw_response = raw_response.strip()

            # Strip OpenRouter __USAGE__ metadata that may be appended after JSON
            if "\n__USAGE__:" in raw_response:
                raw_response = raw_response.split("\n__USAGE__:")[0].strip()

            data = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            logger.warning("Report generator returned invalid JSON: %s — raw: %s", exc, raw_response)
            # Fallback: return a minimal report with the raw text
            return self._fallback_report(raw_response)
        except Exception as exc:
            logger.exception("Report generation failed: %s", exc)
            return self._fallback_report(f"Report generation failed: {exc}")

        # Post-process: replace [AssetID] with numbered [N] and build citation index
        citation_index, source_asset_ids = self._build_citation_index(
            data, retrieval_context
        )

        # Replace asset IDs in all text fields with numbered citations
        data = self._renumber_citations(data, citation_index)

        return GeneratedReport(
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            timeline=data.get("timeline", []),
            patterns=data.get("patterns", []),
            trends=data.get("trends", []),
            issues=data.get("issues", []),
            learnings=data.get("learnings", []),
            recommendations=data.get("recommendations", []),
            raw_markdown=data.get("raw_markdown", ""),
            citation_index=citation_index,
            source_asset_ids=list(source_asset_ids),
        )

    def _build_context_string(
        self,
        entity_name: str | None,
        query_text: str,
        retrieval_context: RetrievalContext,
        analysis_result: AnalysisResult,
    ) -> str:
        """Assemble a concise, structured context string for the LLM."""
        lines = [
            f"QUERY: {query_text}",
            f"ENTITY: {entity_name or 'Not specified'}",
            "",
            "=== RETRIEVED ASSETS ===",
        ]

        asset_map: dict[str, RetrievedAsset] = {}
        for asset in retrieval_context.primary_assets:
            asset_map[str(asset.document_id)] = asset
            snippet = (asset.chunk_text or "")[:400].replace("\n", " ")
            lines.append(
                f"ASSET [{asset.document_id}] {asset.document_name} ({asset.retrieval_source}): {snippet}"
            )

        if retrieval_context.related_assets:
            lines.append("\n=== RELATED ASSETS (via graph) ===")
            for asset in retrieval_context.related_assets:
                asset_map[str(asset.document_id)] = asset
                snippet = (asset.chunk_text or "")[:300].replace("\n", " ")
                lines.append(
                    f"ASSET [{asset.document_id}] {asset.document_name}: {snippet}"
                )

        lines.append("\n=== MILESTONES ===")
        for ms in analysis_result.milestones:
            date_str = ms.get("date") or "Undated"
            lines.append(f"- {date_str}: {ms['title']} — {ms.get('description', '')}")
            if ms.get("linked_asset_ids"):
                lines.append(f"  Sources: {', '.join(ms['linked_asset_ids'])}")

        lines.append("\n=== PATTERNS ===")
        for pat in analysis_result.patterns:
            lines.append(f"- {pat['description']} (confidence: {pat['confidence']})")

        lines.append("\n=== TRENDS ===")
        for tr in analysis_result.trends:
            lines.append(f"- {tr['description']} (confidence: {tr['confidence']})")

        lines.append("\n=== ISSUES ===")
        for issue in analysis_result.issues:
            lines.append(f"- {issue['description']} (confidence: {issue['confidence']})")

        lines.append("\n=== LEARNINGS ===")
        for learning in analysis_result.learnings:
            lines.append(f"- {learning['description']} (confidence: {learning['confidence']})")

        lines.append(
            "\nInstructions: Generate the report JSON using ONLY the context above. "
            "Every factual claim MUST have a citation like [AssetID]."
        )

        return "\n".join(lines)

    def _build_citation_index(
        self,
        data: dict[str, Any],
        retrieval_context: RetrievalContext,
    ) -> tuple[dict[str, dict[str, Any]], set[UUID]]:
        """Extract unique asset IDs from the report, build numbered citation index."""
        all_text = json.dumps(data)
        # Find all [AssetID] patterns
        asset_id_pattern = re.compile(r"\[([a-f0-9\-]{36})\]")
        matches = asset_id_pattern.findall(all_text)

        # Build asset lookup from retrieval context
        asset_lookup: dict[str, RetrievedAsset] = {}
        for asset in retrieval_context.primary_assets + retrieval_context.related_assets:
            asset_lookup[str(asset.document_id)] = asset

        citation_index: dict[str, dict[str, Any]] = {}
        source_asset_ids: set[UUID] = set()
        counter = 1

        for match in matches:
            if match in citation_index:
                continue
            asset = asset_lookup.get(match)
            citation_index[match] = {
                "number": counter,
                "asset_id": match,
                "preview": (asset.chunk_text or "")[:200] if asset else "Source unavailable",
                "document_name": asset.document_name if asset else "Unknown",
                "page_number": asset.page_number if asset else None,
            }
            source_asset_ids.add(UUID(match))
            counter += 1

        return citation_index, source_asset_ids

    def _renumber_citations(
        self,
        data: dict[str, Any],
        citation_index: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Replace [AssetID] with numbered [N] in all text fields."""
        # Build reverse mapping: asset_id -> number
        number_map = {
            asset_id: str(entry["number"])
            for asset_id, entry in citation_index.items()
        }

        def replace_in_value(value: Any) -> Any:
            if isinstance(value, str):
                for asset_id, num in number_map.items():
                    value = value.replace(f"[{asset_id}]", f"[{num}]")
                return value
            elif isinstance(value, list):
                return [replace_in_value(v) for v in value]
            elif isinstance(value, dict):
                return {k: replace_in_value(v) for k, v in value.items()}
            return value

        return replace_in_value(data)

    def _fallback_report(self, raw_text: str) -> GeneratedReport:
        """Return a minimal report when generation fails."""
        return GeneratedReport(
            title="Smart Folder Report",
            summary="The report could not be fully generated. Raw output is provided below.",
            raw_markdown=raw_text,
        )


# Module-level singleton
report_generator = ReportGeneratorService()
