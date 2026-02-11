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
