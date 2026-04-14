"""
Embedding microservice — exposes EmbeddingService over HTTP.

Endpoints
---------
POST /embed         — passage embeddings for indexing (list[str] → list[list[float]])
POST /embed-query   — query embedding for search    (str → list[float])
GET  /health        — liveness + model status
"""

import asyncio
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

# EmbeddingService is a singleton (__new__ ensures one instance globally);
# this call returns the existing instance or creates the first one.
svc = EmbeddingService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Embed server warming up — loading model...")
    await asyncio.to_thread(lambda: svc.model)  # triggers lazy load without blocking event loop
    logger.info("Embed server ready.")
    yield


app = FastAPI(title="SOWKNOW Embed Server", version="1.0.0", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: list[str]
    batch_size: int = Field(default=32, ge=1, le=512)


class EmbedQueryRequest(BaseModel):
    text: str


@app.get("/health")
def health() -> dict:
    return svc.health_check()


@app.post("/embed")
def embed(req: EmbedRequest) -> list[list[float]]:
    if not req.texts:
        return []
    if not svc.can_embed:
        raise HTTPException(status_code=503, detail="Embedding model not loaded")
    return svc.encode(texts=req.texts, batch_size=req.batch_size)


@app.post("/embed-query")
def embed_query(req: EmbedQueryRequest) -> list[float]:
    if not req.text or not req.text.strip():
        return [0.0] * svc.embedding_dim
    if not svc.can_embed:
        raise HTTPException(status_code=503, detail="Embedding model not loaded")
    return svc.encode_query(req.text)
