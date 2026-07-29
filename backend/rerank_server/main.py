"""
SOWKNOW Re-rank Server

Lightweight FastAPI microservice running a cross-encoder for fine-grained
passage re-ranking. Designed to run alongside embed-server.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Lazy-loaded model
_model = None


def _load_model():
    global _model
    if _model is not None:
        return _model
    try:
        import torch

        # Clamp CPU threads to the container's CPU limit (compose: 2.0).
        # Default torch thread count (= host cores) thrashes under CFS
        # throttling and made a 2-passage rerank take ~6s (2026-07-29).
        torch.set_num_threads(int(os.getenv("RERANK_TORCH_THREADS", "2")))

        from sentence_transformers import CrossEncoder

        model_name = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        logger.info("Loading cross-encoder model: %s", model_name)
        _model = CrossEncoder(model_name)
        logger.info("Cross-encoder loaded successfully")
        return _model
    except Exception as exc:
        logger.exception("Failed to load cross-encoder model: %s", exc)
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model on startup, cleanup on shutdown."""
    _load_model()
    yield
    global _model
    _model = None


app = FastAPI(title="SOWKNOW Re-rank Server", lifespan=lifespan)


class RerankRequest(BaseModel):
    query: str
    passages: list[str]


class RerankResponse(BaseModel):
    scores: list[float]


@app.post("/rerank", response_model=RerankResponse)
async def rerank(request: RerankRequest) -> RerankResponse:
    """Score passages for relevance to the query."""
    model = _load_model()
    pairs = [(request.query, p) for p in request.passages]
    scores = model.predict(pairs).tolist()
    return RerankResponse(scores=scores)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "model_loaded": _model is not None}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("RERANK_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
