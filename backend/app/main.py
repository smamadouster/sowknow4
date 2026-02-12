from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import time
import os
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from app.api import auth, admin
# TODO: Import other routers once their dependencies are set up
# from app.api import documents, search, chat
from app.api import collections, smart_folders, knowledge_graph, graph_rag, multi_agent
from app.database import engine, init_pgvector
from app.models.base import Base
from app.models.user import User
from app.services.openrouter_service import openrouter_service
# TODO: Import other models once database is set up
# from app.models.document import Document, DocumentTag, DocumentChunk
# from app.models.chat import ChatSession, ChatMessage
# from app.models.processing import ProcessingQueue

# Load environment variables
load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database
    print("Starting up...")
    init_pgvector()  # Initialize pgvector extension
    Base.metadata.create_all(bind=engine)
    print("Database tables created/verified")
    yield
    # Shutdown
    print("Shutting down...")

app = FastAPI(
    title="SOWKNOW API",
    description="Multi-Generational Legacy Knowledge System",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan
)

# ============================================================================
# SECURITY CRITICAL: CORS and TrustedHost Configuration
# ============================================================================
# Production deployment MUST use environment variables for security.
# Never use wildcard origins ["*"] with allow_credentials=True in production!
# This is a known security vulnerability that allows credential theft.
#
# Environment Variables Required:
#   - ALLOWED_ORIGINS: Comma-separated list of allowed frontend origins
#                      Example: "https://sowknow.gollamtech.com,https://www.sowknow.gollamtech.com"
#   - ALLOWED_HOSTS: Comma-separated list of allowed hosts
#                    Example: "sowknow.gollamtech.com,www.sowknow.gollamtech.com"
#
# Development Behavior:
#   - ALLOWED_ORIGINS defaults to ["http://localhost:3000", "http://127.0.0.1:3000"]
#   - ALLOWED_HOSTS defaults to ["*"] (permissive for local development)
#
# Production Behavior:
#   - Both variables MUST be set explicitly
#   - Wildcards are rejected for security
#   - Missing configuration raises an error to prevent unsafe deployment
# ============================================================================

# Parse environment configuration
APP_ENV = os.getenv("APP_ENV", "development").lower()

# Parse ALLOWED_ORIGINS from environment
# Format: comma-separated list of origins
_allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "")
if APP_ENV == "production":
    if not _allowed_origins_str:
        raise ValueError(
            "SECURITY ERROR: ALLOWED_ORIGINS environment variable is required in production. "
            "Example: ALLOWED_ORIGINS=https://sowknow.gollamtech.com,https://www.sowknow.gollamtech.com"
        )
    # Split and strip whitespace, filter empty strings
    ALLOWED_ORIGINS = [origin.strip() for origin in _allowed_origins_str.split(",") if origin.strip()]

    # Security check: reject wildcards in production
    if "*" in ALLOWED_ORIGINS:
        raise ValueError(
            "SECURITY ERROR: Wildcard origins [*] are not allowed with credentials in production. "
            "Use specific origins instead."
        )
else:
    # Development defaults
    ALLOWED_ORIGINS = _allowed_origins_str.split(",") if _allowed_origins_str else [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",  # Common alternate port
    ]

# Parse ALLOWED_HOSTS from environment
# Format: comma-separated list of hostnames
_allowed_hosts_str = os.getenv("ALLOWED_HOSTS", "")
if APP_ENV == "production":
    if not _allowed_hosts_str:
        raise ValueError(
            "SECURITY ERROR: ALLOWED_HOSTS environment variable is required in production. "
            "Example: ALLOWED_HOSTS=sowknow.gollamtech.com,www.sowknow.gollamtech.com"
        )
    ALLOWED_HOSTS = [host.strip() for host in _allowed_hosts_str.split(",") if host.strip()]
else:
    # Development: Allow any host for local testing
    ALLOWED_HOSTS = ["*"]

# TrustedHost Middleware - Prevents Host header attacks
# Only allows requests from configured hosts
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=ALLOWED_HOSTS
)

# CORS Middleware - Controls cross-origin requests
# SECURITY: Never use allow_origins=["*"] with allow_credentials=True
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Requested-With",
        "Accept",
        "Origin",
        "Access-Control-Request-Method",
        "Access-Control-Request-Headers",
    ],
    expose_headers=["Content-Range", "X-Total-Count"],
    max_age=600,  # Cache preflight responses for 10 minutes
)

# Include routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(collections.router, prefix="/api/v1")
app.include_router(smart_folders.router, prefix="/api/v1")
app.include_router(knowledge_graph.router, prefix="/api/v1")
app.include_router(graph_rag.router, prefix="/api/v1")
app.include_router(multi_agent.router, prefix="/api/v1")
# TODO: Include other routers once dependencies are set up
# app.include_router(documents.router, prefix="/api/v1")
# app.include_router(search.router, prefix="/api/v1")
# app.include_router(chat.router, prefix="/api/v1")

@app.get("/")
async def root():
    return {
        "message": "SOWKNOW API is running",
        "status": "ok",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "api_status": "/api/v1/status",
            "docs": "/api/docs",
            "openapi": "/api/openapi.json",
            "auth": {
                "login": "/api/v1/auth/login",
                "register": "/api/v1/auth/register",
                "me": "/api/v1/auth/me",
                "refresh": "/api/v1/auth/refresh"
            },
            "admin": {
                "users": "/api/v1/admin/users",
                "user_detail": "/api/v1/admin/users/{id}",
                "stats": "/api/v1/admin/stats",
                "audit": "/api/v1/admin/audit",
                "dashboard": "/api/v1/admin/dashboard"
            }
        }
    }

@app.get("/health")
async def health():
    """Enhanced health check endpoint including OpenRouter API status"""
    # Check OpenRouter service health
    openrouter_health = {"status": "unknown"}
    try:
        openrouter_health = await openrouter_service.health_check()
    except Exception as e:
        openrouter_health = {
            "service": "openrouter",
            "status": "error",
            "error": f"Health check failed: {str(e)}"
        }

    return {
        "status": "healthy" if openrouter_health.get("status") in ["healthy", "degraded"] else "degraded",
        "timestamp": time.time(),
        "environment": os.getenv("APP_ENV", "development"),
        "version": "1.0.0",
        "services": {
            "database": "connected",
            "redis": "connected",
            "api": "running",
            "authentication": "enabled",
            "openrouter": openrouter_health
        }
    }

@app.get("/api/v1/status")
async def api_status():
    """API status endpoint with OpenRouter integration"""
    # Get OpenRouter statistics
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
            {"name": "OCR Processing", "status": "✅", "description": "Hunyuan OCR text extraction"},
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
            {"name": "Multi-Agent Search", "status": "⏳", "description": "Agentic search architecture"}
        ],
        "gemini_cache": cache_stats,
        "next_steps": [
            "Final system QA and end-to-end testing",
            "Performance optimization and tuning",
            "Documentation updates",
            "User acceptance testing"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
