"""Live end-to-end scenario check for the Collection Orchestrator.

Runs two real collection requests against the LIVE database (read-only with
respect to source documents; creates smart_folders/source_items/deliverables
rows like normal UI usage; makes real LLM calls):

  S3 analog — trend intent: "Evolution des resultats MATFORCE entre 2006 et 2026"
  S5 analog — ACL trimming: MATFORCE query as guardian-probe (public bucket only)

Usage (throwaway container on the app network, new code mounted):

  docker run --rm --network sowknow4_sowknow-net \
    --env-file /tmp/backend_container.env \
    -v $PWD/backend:/app -w /app sowknow4-backend:latest \
    python /app/../scripts/collection_scenario_check.py

(backend_container.env = `docker inspect sowknow-backend --format
'{{range .Config.Env}}{{println .}}{{end}}'` — keeps secrets out of shell history)
"""
import asyncio
import json
import sys
import uuid

sys.path.insert(0, "/app")

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.collection_orchestrator import (
    AnalysisResult, CollectionAuditEvent, Deliverable, FactSet, Insight, SourceItem,
)
from app.models.smart_folder import CollectionJobState, SmartFolder, SmartFolderStatus
from app.models.user import User
from app.services.collection_orchestrator.conversation_manager import ConversationManager
from app.services.collection_orchestrator.pipeline_runner import get_pipeline_runner


async def run_scenario(query: str, user_email: str) -> dict:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == user_email))).scalar_one()
        sf = SmartFolder(
            id=uuid.uuid4(), user_id=user.id, name=query[:80], query_text=query,
            status=SmartFolderStatus.DRAFT.value, job_state=CollectionJobState.CLARIFYING.value,
        )
        db.add(sf)
        await db.flush()
        cm = ConversationManager()
        session = await cm.start_session(sf, user, db)
        await db.commit()
        await cm.process_answer(session, {}, True, user, db)
        params = await cm.confirm(session, user, db)
        sf.confirmed_params = params
        sf.job_state = CollectionJobState.QUEUED.value
        await db.commit()
        rid, uid = sf.id, user.id

    async with AsyncSessionLocal() as db:
        await get_pipeline_runner().run(rid, uid, db)
        await db.commit()

    async with AsyncSessionLocal() as db:
        sf = (await db.execute(select(SmartFolder).where(SmartFolder.id == rid))).scalar_one()
        deliverable = (
            await db.execute(
                select(Deliverable).where(Deliverable.request_id == rid).order_by(Deliverable.version.desc())
            )
        ).scalars().first()
        analyses = (
            await db.execute(
                select(AnalysisResult.analysis_type, AnalysisResult.output)
                .join(FactSet, AnalysisResult.factset_id == FactSet.id)
                .where(FactSet.request_id == rid)
            )
        ).all()
        items = (
            await db.execute(
                select(SourceItem.acl_stamp, SourceItem.status)
                .where(SourceItem.request_id == rid)
            )
        ).all()
        insight_rows = (
            await db.execute(
                select(Insight.statement)
                .join(AnalysisResult, Insight.analysis_id == AnalysisResult.id)
                .join(FactSet, AnalysisResult.factset_id == FactSet.id)
                .where(FactSet.request_id == rid)
            )
        ).all()

        analysis_summary = []
        for atype, output in analyses:
            out = output or {}
            entry = {"type": atype}
            if atype == "trend":
                entry["trends"] = [
                    {k: t.get(k) for k in ("metric", "direction", "slope", "sufficient_data", "message", "yoy_changes")}
                    for t in (out.get("trends") or [])[:5]
                ]
            elif atype == "anomaly":
                entry["anomalies_found"] = sum(
                    len(m.get("anomalies") or []) for m in (out.get("metrics") or [])
                )
            elif atype == "correlation":
                entry["correlations"] = out.get("correlations") or out.get("message")
            elif atype == "comparison":
                entry["ranking_size"] = len(out.get("ranking") or [])
            analysis_summary.append(entry)

        return {
            "query": query,
            "user": user_email,
            "job_state": sf.job_state,
            "error": sf.error_message,
            "analysis_types_requested": (params or {}).get("analysis_types"),
            "item_acl_stamps": sorted({a for a, _ in items if a}),
            "status_counts": {s: sum(1 for _, st in items if st == s) for s in {st for _, st in items}},
            "analyses": analysis_summary,
            "insight_statements": [s for (s,) in insight_rows][:12],
            "summary_present": bool(deliverable and deliverable.summary_md),
            "disclosures": deliverable.disclosures if deliverable else None,
        }


async def main():
    out = []
    scenarios = [
        ("Evolution des resultats MATFORCE entre 2006 et 2026", "msow@gollamsys.com"),   # S3: trend intent
        ("Toutes les informations sur MATFORCE", "guardian-probe@sowknow.local"),          # S5: regular user, public bucket only
    ]
    for query, email in scenarios:
        try:
            out.append(await run_scenario(query, email))
        except Exception as exc:
            import traceback
            traceback.print_exc()
            out.append({"query": query, "user": email, "fatal_error": repr(exc)})
    print("SCENARIO_RESULTS " + json.dumps(out, indent=2, ensure_ascii=False, default=str))

asyncio.run(main())
