"""General Relationship Narrator Skill.

Default skill for personal/professional/institutional summaries.
Uses deep search + full document reading for rich report generation.
"""

import logging
from typing import Any
from uuid import UUID

from app.services.smart_folder.skills.base import BaseSkill, SkillResult
from app.services.smart_folder.analysis import analysis_service
from app.services.smart_folder.report_generator import report_generator
from app.services.smart_folder.retrieval import retrieval_service
from app.services.smart_folder.tools.document_reader import document_reader

logger = logging.getLogger(__name__)


class GeneralNarrativeSkill(BaseSkill):
    """Skill: General relationship narrative with timelines, patterns, and lessons.

    Phase 1 enhancement: reads full text of top-N documents instead of
    relying solely on chunk snippets, producing richer, evidence-based reports.
    """

    skill_id = "general_narrative"
    skill_name = "General Relationship Narrator"
    description = (
        "Default skill for personal, professional, and institutional summaries. "
        "Produces timelines, pattern extraction, and lesson integration with "
        "full document context and quoted evidence."
    )

    # Number of unique documents to read in full (Phase 2: increased for multi-hop)
    FULL_READ_DOC_COUNT = 25
    # Max chars per document
    MAX_CHARS_PER_DOC = 10000

    async def analyze(self, parameters: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        """Run the general narrative pipeline with full document reading."""
        db = context.get("db")
        user = context.get("user")
        entity_id = parameters.get("entity_id") or context.get("entity_id")
        entity_name = parameters.get("entity_name") or context.get("entity_name")
        relationship_type = parameters.get("relationship_type") or context.get("relationship_type")
        query_text = parameters.get("query") or context.get("query")
        time_start = parameters.get("time_range_start") or context.get("time_range_start")
        time_end = parameters.get("time_range_end") or context.get("time_range_end")
        focus = parameters.get("focus_aspects") or context.get("focus_aspects")

        if not db or not user:
            return SkillResult(
                skill_id=self.skill_id,
                success=False,
                error="Missing db or user in context",
            )

        try:
            # ── 1. Retrieval (multi-signal: mentions + hybrid + graph + semantic) ──
            retrieval = await retrieval_service.retrieve(
                db=db,
                user=user,
                query_text=query_text,
                entity_id=entity_id,
                entity_name=entity_name,
                time_range_start=time_start,
                time_range_end=time_end,
                focus_aspects=focus,
            )

            if retrieval.total_found == 0:
                return SkillResult(
                    skill_id=self.skill_id,
                    success=True,
                    text_summary=f"Aucune information concernant {entity_name or 'cette entité'} n'a été trouvée dans le coffre-fort numérique.",
                    raw_output={
                        "title": f"Smart Folder: {entity_name or 'Inconnu'}",
                        "summary": f"Aucune information concernant {entity_name or 'cette entité'} n'a été trouvée.",
                        "timeline": [],
                        "patterns": [],
                        "trends": [],
                        "issues": [],
                        "learnings": [],
                        "recommendations": [],
                        "raw_markdown": f"# {entity_name or 'Inconnu'}\n\nAucun document ne mentionne cette entité.",
                        "citation_index": {},
                    },
                )

            # ── 2. Full document reading ──
            # Phase 2: Prioritize direct evidence first, then multi-hop context
            # Sort primary (direct) assets higher, but include top related assets too
            primary_assets = sorted(retrieval.primary_assets, key=lambda a: a.score, reverse=True)
            related_assets = sorted(retrieval.related_assets, key=lambda a: a.score, reverse=True)

            seen_doc_ids: set[UUID] = set()
            doc_ids_to_read: list[UUID] = []

            # First pass: all primary (direct) assets
            for asset in primary_assets:
                if asset.document_id not in seen_doc_ids:
                    seen_doc_ids.add(asset.document_id)
                    doc_ids_to_read.append(asset.document_id)

            # Second pass: top related (multi-hop) assets
            for asset in related_assets:
                if asset.document_id not in seen_doc_ids:
                    seen_doc_ids.add(asset.document_id)
                    doc_ids_to_read.append(asset.document_id)
                if len(doc_ids_to_read) >= self.FULL_READ_DOC_COUNT:
                    break

            documents = await document_reader.read_documents(
                document_ids=doc_ids_to_read,
                db=db,
                max_chars=self.MAX_CHARS_PER_DOC,
            )

            # Build a relation_path lookup for context enrichment
            relation_paths: dict[str, str] = {}
            for asset in primary_assets + related_assets:
                relation_paths[str(asset.document_id)] = asset.relation_path

            logger.info(
                "GeneralNarrativeSkill read %d full documents for entity=%s "
                "(primary=%d, related=%d, expansion=%s)",
                len(documents), entity_name,
                len(primary_assets), len(related_assets),
                retrieval.expansion_stats,
            )

            # ── 3. Analysis (milestones, patterns from dedicated tables) ──
            analysis = await analysis_service.analyze(
                db=db,
                entity_id=entity_id,
                time_range_start=time_start,
                time_range_end=time_end,
                focus_aspects=focus,
            )

            # ── 4. Report generation with full document context ──
            report = await report_generator.generate(
                query_text=query_text,
                entity_name=entity_name,
                relationship_type=relationship_type,
                retrieval_context=retrieval,
                analysis_result=analysis,
                full_documents=documents,
            )

            # Build citations from ALL retrieved assets, not just those used in report text
            # This ensures the citation panel shows all sources consulted
            # Phase 2: Include relation_path to distinguish direct vs multi-hop sources
            citation_index: dict[str, dict[str, Any]] = {}
            counter = 1
            all_assets = primary_assets + related_assets
            grade_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0}
            direct_count = 0
            contextual_count = 0
            total_confidence = 0.0
            for asset in all_assets:
                aid = str(asset.document_id)
                if aid not in citation_index:
                    citation_index[aid] = {
                        "number": counter,
                        "asset_id": aid,
                        "preview": (asset.chunk_text or "")[:200],
                        "document_name": asset.document_name,
                        "page_number": asset.page_number,
                        "retrieval_source": asset.retrieval_source,
                        "relation_path": asset.relation_path,
                        "evidence_grade": asset.evidence_grade,
                        "confidence_score": round(asset.confidence_score, 2),
                    }
                    counter += 1
                # Count grades for source quality
                grade_counts[asset.evidence_grade] = grade_counts.get(asset.evidence_grade, 0) + 1
                total_confidence += asset.confidence_score
                if asset.evidence_grade in ("A", "B"):
                    direct_count += 1
                else:
                    contextual_count += 1

            avg_confidence = total_confidence / len(all_assets) if all_assets else 0.0
            overall = "High" if avg_confidence >= 0.7 else "Medium" if avg_confidence >= 0.5 else "Low"

            source_quality = {
                "grade_distribution": grade_counts,
                "overall_confidence": overall,
                "direct_sources_count": direct_count,
                "contextual_sources_count": contextual_count,
                "notes": (
                    f"{grade_counts.get('A', 0)} direct mentions (Grade A), "
                    f"{grade_counts.get('B', 0)} relationship sources (Grade B), "
                    f"{grade_counts.get('C', 0)} co-occurrence sources (Grade C), "
                    f"{grade_counts.get('D', 0)} contextual org sources (Grade D). "
                    f"Average confidence: {round(avg_confidence * 100)}%."
                ),
            }

            return SkillResult(
                skill_id=self.skill_id,
                success=True,
                text_summary=report.summary,
                citations=[
                    {
                        "asset_id": aid,
                        "preview": entry["preview"],
                        "document_name": entry["document_name"],
                        "page_number": entry.get("page_number"),
                        "evidence_grade": entry.get("evidence_grade"),
                        "confidence_score": entry.get("confidence_score"),
                        "relation_path": entry.get("relation_path"),
                        "retrieval_source": entry.get("retrieval_source"),
                    }
                    for aid, entry in citation_index.items()
                ],
                raw_output={
                    "title": report.title,
                    "summary": report.summary,
                    "timeline": report.timeline,
                    "patterns": report.patterns,
                    "trends": report.trends,
                    "issues": report.issues,
                    "learnings": report.learnings,
                    "recommendations": report.recommendations,
                    "raw_markdown": report.raw_markdown,
                    "source_quality": source_quality,
                    "citation_index": citation_index,
                    "source_asset_ids": [str(a.document_id) for a in all_assets],
                    "documents_read": len(documents),
                    "total_chunks_found": retrieval.total_found,
                },
            )
        except Exception as exc:
            logger.exception("GeneralNarrativeSkill failed: %s", exc)
            return SkillResult(
                skill_id=self.skill_id,
                success=False,
                error=str(exc),
            )
