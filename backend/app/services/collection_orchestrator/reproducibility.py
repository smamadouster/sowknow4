"""Reproducibility check — FR8.5.

Re-runs the deterministic AnalysisEngine over the STORED FactSet of a
collection request, using the analysis types recorded in
``confirmed_params`` and the thresholds recorded on each stored
AnalysisResult, and compares the fresh outputs against the stored ones.
Exact JSON equality is expected: the engine is deterministic, so any
difference means the stored data was tampered with or the facts changed.

When the stored ``code_version`` differs from the current
``ANALYSIS_CODE_VERSION`` the comparison is not meaningful — the result
reports ``matches=None`` with a "code version changed" note instead.
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_orchestrator import AnalysisResult, FactSet
from app.models.smart_folder import SmartFolder
from app.services.collection_orchestrator.analysis_engine import (
    ANALYSIS_CODE_VERSION,
    AnalysisEngine,
)

logger = logging.getLogger(__name__)

CODE_VERSION_CHANGED_NOTE = (
    "code version changed — stored outputs were produced by a different "
    "analysis code version; exact comparison is not meaningful"
)


async def reproduce_analysis(db: AsyncSession, request_id: UUID) -> dict[str, Any]:
    """Re-run the analysis for a request from its stored FactSet.

    Returns {analyses, stored, factset_id, fact_count, analysis_types}:
    ``analyses`` are the fresh engine results, ``stored`` the persisted
    AnalysisResult payloads (analysis_type / output / thresholds_used /
    code_version).
    """
    from app.core.config import settings

    folder = (
        await db.execute(select(SmartFolder).where(SmartFolder.id == request_id))
    ).scalar_one_or_none()
    if folder is None:
        raise ValueError(f"Collection request {request_id} not found")

    factset = (
        await db.execute(
            select(FactSet)
            .where(FactSet.request_id == request_id)
            .order_by(FactSet.version.desc())
        )
    ).scalars().first()
    if factset is None:
        raise ValueError(f"No FactSet stored for request {request_id}")

    stored_rows = (
        await db.execute(
            select(AnalysisResult).where(AnalysisResult.factset_id == factset.id)
        )
    ).scalars().all()
    stored = [
        {
            "analysis_type": row.analysis_type,
            "output": row.output,
            "thresholds_used": row.thresholds_used,
            "code_version": row.code_version,
        }
        for row in stored_rows
    ]

    confirmed = folder.confirmed_params or {}
    analysis_types = list(confirmed.get("analysis_types") or ["descriptive"])

    # Same above-threshold fact filter the pipeline applies (FR4.1.6).
    threshold = settings.COLLECTION_FACT_CONFIDENCE_THRESHOLD
    facts = [
        f for f in (factset.facts or [])
        if (f.get("confidence") or 0) >= threshold
    ]

    # Re-run with the thresholds recorded on the stored results.
    recorded_thresholds = {
        row["analysis_type"]: row["thresholds_used"]
        for row in stored
        if row.get("thresholds_used")
    }
    fresh = AnalysisEngine().run(facts, analysis_types, recorded_thresholds or None)

    return {
        "analyses": fresh,
        "stored": stored,
        "factset_id": str(factset.id),
        "factset_version": factset.version,
        "fact_count": len(facts),
        "analysis_types": analysis_types,
    }


def compare_reproduction(reproduction: dict[str, Any]) -> dict[str, Any]:
    """Compare stored AnalysisResult outputs to the fresh reproduction.

    Returns {matches, differences, code_version_stored,
    code_version_current, note}. ``matches`` is True/False, or None when a
    code-version change makes exact comparison meaningless.
    """
    stored = reproduction.get("stored") or []
    fresh_by_type = {
        a.get("analysis_type"): a for a in reproduction.get("analyses") or []
    }

    stored_versions = sorted({s.get("code_version") for s in stored if s.get("code_version")})
    code_version_stored = stored_versions[0] if len(stored_versions) == 1 else stored_versions

    result: dict[str, Any] = {
        "code_version_stored": code_version_stored,
        "code_version_current": ANALYSIS_CODE_VERSION,
        "differences": [],
        "note": None,
    }

    if any(v != ANALYSIS_CODE_VERSION for v in stored_versions):
        result["matches"] = None
        result["note"] = CODE_VERSION_CHANGED_NOTE
        return result

    differences: list[dict[str, Any]] = []
    for entry in stored:
        analysis_type = entry.get("analysis_type")
        fresh = fresh_by_type.get(analysis_type)
        if fresh is None:
            differences.append({
                "analysis_type": analysis_type,
                "reason": "analysis type not reproduced "
                          "(not in confirmed_params analysis_types)",
            })
            continue
        if fresh.get("output") != entry.get("output"):
            differences.append({
                "analysis_type": analysis_type,
                "reason": "stored output differs from fresh reproduction",
                "stored_output": entry.get("output"),
                "fresh_output": fresh.get("output"),
            })
    result["differences"] = differences
    result["matches"] = not differences
    return result
