"""
API status endpoint.
"""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.user import User
from app.services.llm_gateway import llm_gateway
from app.services.rollback_monitor import rollback_monitor

router = APIRouter(prefix="/status", tags=["status"])


@router.get("/pipeline-health")
async def pipeline_health(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """
    Public pipeline health indicator for upload throttling.

    Returns RED/YELLOW/GREEN so users know when to stop uploading.
    """
    try:
        import redis as _redis
        from app.core.redis_url import safe_redis_url
        from app.tasks.pipeline_orchestrator import MAX_QUEUE_DEPTH

        r = _redis.from_url(safe_redis_url(), socket_timeout=5)
        queues = {}
        total_depth = 0
        for queue_name in [
            "pipeline.ocr",
            "pipeline.chunk",
            "pipeline.embed",
            "pipeline.index",
            "pipeline.articles",
            "pipeline.entities",
        ]:
            depth = r.llen(queue_name)
            queues[queue_name] = {
                "depth": depth,
                "max": MAX_QUEUE_DEPTH.get(queue_name),
            }
            total_depth += depth

        embed_depth = queues.get("pipeline.embed", {}).get("depth", 0)

        # Traffic-light logic tuned for CPU-only embed VPS
        if total_depth > 700 or embed_depth > 300:
            status = "red"
            message = "Pipeline overloaded — stop uploading until queue drains"
        elif total_depth > 300 or embed_depth > 150:
            status = "yellow"
            message = "Pipeline busy — slow down uploads"
        else:
            status = "green"
            message = "Pipeline healthy — upload freely"

        return {
            "status": status,
            "message": message,
            "total_queue_depth": total_depth,
            "queues": queues,
        }
    except Exception as exc:
        return {
            "status": "yellow",
            "message": f"Could not read pipeline status: {exc}",
            "total_queue_depth": -1,
            "queues": {},
        }


@router.get("")
async def api_status() -> dict[str, Any]:
    """API status endpoint with LLM gateway integration"""
    llm_stats = {"status": "unknown"}
    try:
        llm_stats = await llm_gateway.get_usage_stats()
    except Exception as e:
        llm_stats = {"error": f"Could not retrieve LLM stats: {str(e)}"}

    return {
        "phase": "3 - Knowledge Graph + Graph-RAG + Multi-Agent Search",
        "sprint": "10 - Multi-Agent Search (COMPLETE)",
        "status": "Phase 3 Complete - All Sprints Implemented",
        "version": "3.0.0",
        "llm_provider": "OpenRouter (MiniMax)",
        "features": [
            {"name": "Infrastructure", "status": "✅", "description": "Docker containers, PostgreSQL, Redis"},
            {"name": "Authentication", "status": "✅", "description": "JWT login/register system"},
            {"name": "Database Models", "status": "✅", "description": "SQLAlchemy models with pgvector"},
            {"name": "OpenRouter Integration", "status": "✅", "description": "OpenRouter API with MiniMax"},
            {"name": "Document Upload", "status": "✅", "description": "File upload and processing"},
            {"name": "OCR Processing", "status": "✅", "description": "PaddleOCR text extraction"},
            {"name": "RAG Search", "status": "✅", "description": "Hybrid vector + keyword search"},
            {"name": "Smart Collections", "status": "✅", "description": "NL query to document groups with chat"},
            {"name": "Smart Folders", "status": "✅", "description": "AI-generated articles from docs"},
            {"name": "PDF Reports", "status": "✅", "description": "3 report templates with export"},
            {"name": "Auto-Tagging", "status": "✅", "description": "AI tagging on document ingestion"},
            {"name": "Similarity Grouping", "status": "✅", "description": "Cluster similar documents"},
            {"name": "Mac Sync Agent", "status": "✅", "description": "File sync from local/iCloud/Dropbox"},
            {"name": "Deduplication", "status": "✅", "description": "Hash-based duplicate detection"},
            {"name": "Performance Tuning", "status": "✅", "description": "Batch optimization & caching"},
            {"name": "E2E Tests", "status": "✅", "description": "Phase 2 test coverage"},
            {"name": "Entity Extraction", "status": "✅", "description": "LLM-powered entity extraction"},
            {"name": "Knowledge Graph", "status": "✅", "description": "Entity + relationship storage"},
            {"name": "Relationship Mapping", "status": "✅", "description": "Graph relationship inference"},
            {"name": "Timeline Construction", "status": "✅", "description": "Event timeline + insights"},
            {"name": "Graph Visualization", "status": "✅", "description": "Interactive graph explorer"},
            {"name": "Graph-RAG", "status": "✅", "description": "Graph-augmented retrieval"},
            {"name": "Synthesis Pipeline", "status": "✅", "description": "Map-Reduce document synthesis"},
            {"name": "Temporal Reasoning", "status": "✅", "description": "Time-based relationship analysis"},
            {"name": "Progressive Revelation", "status": "✅", "description": "Role-based information disclosure"},
            {"name": "Family Context", "status": "✅", "description": "Family narrative generation"},
            {"name": "Multi-Agent Search", "status": "✅", "description": "Agentic search architecture via /api/v1/search/orchestrate"},
        ],
        "next_steps": [
            "Final system QA and end-to-end testing",
            "Performance optimization and tuning",
            "Documentation updates",
            "User acceptance testing",
        ],
    }


@router.get("/rollback")
async def rollback_status(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """
    §3.4 rollback plan status.

    Returns current tier metrics, active triggers, and recommended rollback actions.
    Requires authentication.
    """
    return rollback_monitor.get_status()
