"""
Embedding microservice — exposes EmbeddingService over HTTP.

Endpoints
---------
POST /embed         — passage embeddings for indexing (list[str] → list[list[float]])
POST /embed-query   — query embedding for search    (str → list[float])
GET  /health        — liveness + model status

Concurrency control
-------------------
Embedding is CPU-bound and memory-intensive.  A single batch can spike
RAM by 2–4 GB temporarily.  To prevent OOMs under load we serialize all
encode calls with an asyncio.Semaphore so only one request touches the
model at a time.  PyTorch internal threads are also clamped to 1 so
we don't get hidden parallelism inside a single encode() call.

Because the encode methods are synchronous (PyTorch / sentence-transformers),
they are off-loaded via asyncio.to_thread().  The semaphore ensures we never
spawn more than one encoding thread concurrently, eliminating the thread-pile-up
that previously caused 200 % CPU from GIL contention.
"""

import faulthandler
import os
import signal
import sys

faulthandler.enable()
faulthandler.register(signal.SIGUSR1, all_threads=True)

# ── CRITICAL: set thread counts BEFORE torch is imported ──
# EmbeddingService imports sentence-transformers → torch.
# Once torch is loaded these env vars are read and cached.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

try:
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    print(f"[embed-server] torch threads set: intra={torch.get_num_threads()}, interop={torch.get_num_interop_threads()}", flush=True)
except Exception as e:
    print(f"[embed-server] torch thread config failed: {e}", flush=True)

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

# EmbeddingService is a singleton (__new__ ensures one instance globally);
# this call returns the existing instance or creates the first one.
svc = EmbeddingService()

# ── Bounded concurrency: only one encode() in flight at a time ──
# This prevents FastAPI's default ThreadPoolExecutor from spawning dozens
# of blocked threads that spin on the GIL and consume 200 % CPU.
_encode_sem = asyncio.Semaphore(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Embed server warming up — loading model...")
    await asyncio.to_thread(lambda: svc.model)  # triggers lazy load without blocking event loop
    logger.info("Embed server ready (torch threads=%s).", torch.get_num_threads() if "torch" in sys.modules else "n/a")
    yield


app = FastAPI(title="SOWKNOW Embed Server", version="1.2.0", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: list[str]
    batch_size: int = Field(default=32, ge=1, le=128)


class EmbedQueryRequest(BaseModel):
    text: str


@app.get("/health")
async def health() -> dict:
    return svc.health_check()


@app.post("/embed")
async def embed(req: EmbedRequest) -> list[list[float]]:
    if not req.texts:
        return []
    if not svc.can_embed:
        raise HTTPException(status_code=503, detail="Embedding model not loaded")
    async with _encode_sem:
        return await asyncio.to_thread(svc.encode, texts=req.texts, batch_size=req.batch_size)


@app.post("/embed-query")
async def embed_query(req: EmbedQueryRequest) -> list[float]:
    if not req.text or not req.text.strip():
        return [0.0] * svc.embedding_dim
    if not svc.can_embed:
        raise HTTPException(status_code=503, detail="Embedding model not loaded")
    async with _encode_sem:
        return await asyncio.to_thread(svc.encode_query, req.text)
