"""
Embedding microservice — exposes EmbeddingService over HTTP.

Endpoints
---------
POST /embed         — passage embeddings for indexing (list[str] → list[list[float]])
POST /embed-query   — query embedding for search    (str → list[float])
GET  /health        — liveness + model status
"""

import logging
from fastapi import FastAPI
from pydantic import BaseModel

from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

app = FastAPI(title="SOWKNOW Embed Server", version="1.0.0")

# Singleton — model loads lazily on first request via EmbeddingService._load_model()
svc = EmbeddingService()


class EmbedRequest(BaseModel):
    texts: list[str]
    batch_size: int = 32


class EmbedQueryRequest(BaseModel):
    text: str


@app.on_event("startup")
def warm_up():
    """Trigger model load at startup so the first real request isn't slow."""
    logger.info("Embed server warming up — loading model...")
    _ = svc.model  # access the property → triggers lazy load
    logger.info("Embed server ready.")


@app.get("/health")
def health() -> dict:
    return svc.health_check()


@app.post("/embed")
def embed(req: EmbedRequest) -> list[list[float]]:
    if not req.texts:
        return []
    return svc.encode(texts=req.texts, batch_size=req.batch_size)


@app.post("/embed-query")
def embed_query(req: EmbedQueryRequest) -> list[float]:
    if not req.text or not req.text.strip():
        return [0.0] * svc.embedding_dim
    return svc.encode_query(req.text)
