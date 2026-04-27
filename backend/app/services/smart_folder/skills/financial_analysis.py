"""Financial Statement Analyser Skill.

Queries mentioning balance sheet, P&L, cash flow, or financial health
trigger this skill. Parses structured financial docs, computes ratios,
trend tables, and chart generation.
"""

import logging
from typing import Any

from app.services.smart_folder.skills.base import BaseSkill, SkillResult
from app.services.smart_folder.tools.asset_reader import asset_reader
from app.services.smart_folder.tools.chart_generator import chart_generator
from app.services.smart_folder.tools.ratio_calculator import ratio_calculator
from app.services.smart_folder.tools.table_extractor import table_extractor
from app.services.smart_folder.tools.trend_analyzer import trend_analyzer
from app.services.smart_folder.tools.vault_search import vault_search

logger = logging.getLogger(__name__)


class FinancialAnalysisSkill(BaseSkill):
    """Skill: Deep financial document analysis with ratios and charts."""

    skill_id = "financial_analysis"
    skill_name = "Financial Statement Analyser"
    description = (
        "Parses balance sheets, income statements, and cash flow documents. "
        "Computes ratios, detects trends, and generates charts."
    )
    required_tools = [
        "vault_search",
        "asset_reader",
        "table_extractor",
        "ratio_calculator",
        "trend_analyzer",
        "chart_generator",
    ]

    async def analyze(self, parameters: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        db = context.get("db")
        user = context.get("user")
        entity_name = parameters.get("entity_name") or context.get("entity_name")
        query = parameters.get("query") or context.get("query")
        time_start = parameters.get("time_range_start") or context.get("time_range_start")
        time_end = parameters.get("time_range_end") or context.get("time_range_end")

        if not db or not user:
            return SkillResult(skill_id=self.skill_id, success=False, error="Missing db or user")

        try:
            # Step 1: Retrieve financial documents
            search_query = f"{entity_name or query} balance sheet income statement financial"
            search_result = await vault_search.search(
                query=search_query,
                user=user,
                db=db,
                limit=15,
            )

            documents = search_result.get("results", [])
            if not documents:
                return SkillResult(
                    skill_id=self.skill_id,
                    success=True,
                    text_summary="No financial documents were found for this entity.",
                )

            # Step 2: Extract tables from top documents
            all_tables = []
            for doc in documents[:5]:
                text = doc.get("text", "")
                tables = table_extractor.extract(text)
                for t in tables:
                    t["source_asset_id"] = doc["asset_id"]
                    t["source_name"] = doc["name"]
                all_tables.extend(tables)

            # Step 3: Compute ratios for each table
            ratio_results = []
            for table in all_tables:
                ratios = ratio_calculator.compute_ratios(table)
                ratios["source"] = table.get("source_name", "Unknown")
                ratios["source_asset_id"] = table.get("source_asset_id")
                ratio_results.append(ratios)

            # Step 4: Trend analysis on extracted numeric values
            trend_visualisations = []
            for result in ratio_results:
                extracted = result.get("extracted_values", {})
                if "assets" in extracted and "liabilities" in extracted:
                    values = [extracted.get("assets", 0), extracted.get("liabilities", 0)]
                    labels = ["Assets", "Liabilities"]
                    trend_data = [{"category": l, "value": v} for l, v in zip(labels, values)]
                    spec = chart_generator.bar_chart(
                        data=trend_data,
                        x_field="category",
                        y_field="value",
                        title=f"Assets vs Liabilities — {result['source']}",
                    )
                    trend_visualisations.append({
                        "type": "vega-lite",
                        "title": f"Assets vs Liabilities — {result['source']}",
                        "spec": spec,
                        "source_asset_id": result.get("source_asset_id"),
                    })

            # Step 5: Build summary text
            summary_lines = [f"Analysed {len(documents)} financial document(s)."]
            if ratio_results:
                summary_lines.append("Computed ratios from extracted balance sheet data:")
                for rr in ratio_results:
                    ratios = rr.get("ratios", {})
                    if ratios:
                        summary_lines.append(
                            f"- {rr['source']}: " + ", ".join(
                                f"{k}={v}" for k, v in ratios.items()
                            )
                        )

            return SkillResult(
                skill_id=self.skill_id,
                success=True,
                text_summary="\n".join(summary_lines),
                data_tables=ratio_results,
                visualisations=trend_visualisations,
                citations=[
                    {"asset_id": d["asset_id"], "preview": d["text"][:200]}
                    for d in documents[:5]
                ],
                raw_output={
                    "document_count": len(documents),
                    "table_count": len(all_tables),
                    "ratio_results": ratio_results,
                },
            )
        except Exception as exc:
            logger.exception("FinancialAnalysisSkill failed: %s", exc)
            return SkillResult(skill_id=self.skill_id, success=False, error=str(exc))
