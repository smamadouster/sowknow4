"""
SOWKNOW API - Minimal Working Version
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import time
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Starting up...")
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

# Include auth router (keep it simple for now)
from app.api import auth
app.include_router(auth.router, prefix="/api/v1")

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
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "environment": os.getenv("APP_ENV", "development"),
        "version": "1.0.0",
        "services": {
            "api": "running",
            "authentication": "enabled"
        }
    }

@app.get("/api/v1/status")
async def api_status():
    return {
        "phase": "1 - Core MVP",
        "sprint": "1 - Foundation",
        "status": "development",
        "version": "1.0.0",
        "features": [
            {"name": "Infrastructure", "status": "✅", "description": "Docker containers, PostgreSQL, Redis"},
            {"name": "Authentication", "status": "✅", "description": "JWT login/register system"},
            {"name": "Database Models", "status": "⏳", "description": "SQLAlchemy models with pgvector"},
            {"name": "Document Upload", "status": "⏳", "description": "File upload and processing"},
            {"name": "OCR Processing", "status": "⏳", "description": "Text extraction from documents"},
            {"name": "RAG Search", "status": "⏳", "description": "Vector search with embeddings"},
            {"name": "Telegram Bot", "status": "⏳", "description": "Telegram integration"}
        ],
        "next_steps": [
            "Implement document models",
            "Create document upload API",
            "Set up file storage buckets",
            "Integrate Hunyuan OCR API",
            "Implement vector embeddings"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
