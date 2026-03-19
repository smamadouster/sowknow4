"""
API status endpoint.
"""

import os
from typing import Any

from fastapi import APIRouter

from app.services.openrouter_service import openrouter_service

router = APIRouter(prefix="/status", tags=["status"])


@router.get("")
async def api_status() -> dict[str, Any]:
    """API status endpoint with OpenRouter integration"""
    llm_stats = {"status": "unknown"}
    try:
        llm_stats = await openrouter_service.get_usage_stats()
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
            {"name": "Multi-Agent Search", "status": "⏳", "description": "Agentic search architecture"},
        ],
        "next_steps": [
            "Final system QA and end-to-end testing",
            "Performance optimization and tuning",
            "Documentation updates",
            "User acceptance testing",
        ],
    }
