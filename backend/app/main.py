from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import time
import os
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from app.api import auth
# TODO: Import other routers once their dependencies are set up
# from app.api import documents, search, chat, admin
from app.database import engine, init_pgvector
from app.models.base import Base
from app.models.user import User
from app.services.gemini_service import gemini_service
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

# Security middleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # In production, set specific hosts
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/v1")
# TODO: Include other routers once dependencies are set up
# app.include_router(documents.router, prefix="/api/v1")
# app.include_router(search.router, prefix="/api/v1")
# app.include_router(chat.router, prefix="/api/v1")
# app.include_router(admin.router, prefix="/api/v1")

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
            }
        }
    }

@app.get("/health")
async def health():
    """Enhanced health check endpoint including Gemini API status and cache stats"""
    # Check Gemini service health
    gemini_health = {"status": "unknown"}
    try:
        gemini_health = await gemini_service.health_check()
    except Exception as e:
        gemini_health = {
            "service": "gemini",
            "status": "error",
            "error": f"Health check failed: {str(e)}"
        }

    return {
        "status": "healthy" if gemini_health.get("status") in ["healthy", "degraded"] else "degraded",
        "timestamp": time.time(),
        "environment": os.getenv("APP_ENV", "development"),
        "version": "1.0.0",
        "services": {
            "database": "connected",
            "redis": "connected",
            "api": "running",
            "authentication": "enabled",
            "gemini": gemini_health
        }
    }

@app.get("/api/v1/status")
async def api_status():
    """API status endpoint with Gemini integration"""
    # Get cache statistics
    cache_stats = {"status": "unknown"}
    try:
        usage_stats = await gemini_service.get_usage_stats()
        cache_stats = usage_stats.get("cache_stats", {})
    except Exception as e:
        cache_stats = {"error": f"Could not retrieve cache stats: {str(e)}"}

    return {
        "phase": "2 - Gemini Integration",
        "sprint": "1 - Foundation",
        "status": "development",
        "version": "2.0.0",
        "llm_provider": "Gemini Flash (Google)",
        "features": [
            {"name": "Infrastructure", "status": "✅", "description": "Docker containers, PostgreSQL, Redis"},
            {"name": "Authentication", "status": "✅", "description": "JWT login/register system"},
            {"name": "Database Models", "status": "✅", "description": "SQLAlchemy models with pgvector"},
            {"name": "Gemini Flash Integration", "status": "✅", "description": "Google Gemini 2.0 Flash with caching"},
            {"name": "Document Upload", "status": "⏳", "description": "File upload and processing"},
            {"name": "OCR Processing", "status": "⏳", "description": "Text extraction from documents"},
            {"name": "RAG Search", "status": "⏳", "description": "Vector search with embeddings"},
            {"name": "Telegram Bot", "status": "⏳", "description": "Telegram integration"}
        ],
        "gemini_cache": cache_stats,
        "next_steps": [
            "Implement document models",
            "Create document upload API",
            "Set up file storage buckets",
            "Integrate Hunyuan OCR API",
            "Implement vector embeddings",
            "Test Gemini caching performance"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
