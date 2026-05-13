"""
Embedding microservice with dynamic batching.

Coalesces concurrent /embed and /embed-query requests into larger batches
to improve CPU/BLAS utilization. Each request waits up to BATCH_WINDOW_MS
for additional requests to arrive before the batch is dispatched.

Endpoints
---------
POST /embed         — passage embeddings for indexing (list[str] → list[list[float]])
POST /embed-query   — query embedding for search    (str → list[float])
GET  /health        — liveness + model status + queue depth
"""

import faulthandler
import os
import signal
import sys

faulthandler.enable()
faulthandler.register(signal.SIGUSR1, all_threads=True)

# ── CRITICAL: set thread counts BEFORE torch is imported ──
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

try:
    import torch

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    print(
        f"[embed-server] torch threads set: intra={torch.get_num_threads()}, "
        f"interop={torch.get_num_interop_threads()}",
        flush=True,
    )
except Exception as e:
    print(f"[embed-server] torch thread config failed: {e}", flush=True)

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── Backend switch ──────────────────────────────────────────────
# Set EMBED_BACKEND=onnx to use the ONNX/INT8 implementation.
# Default remains sentence-transformers for zero-downtime rollout.
if os.getenv("EMBED_BACKEND", "st") == "onnx":
    from app.services.embedding_service_onnx import embedding_service as svc
else:
    from app.services.embedding_service import EmbeddingService

    svc = EmbeddingService()

logger = logging.getLogger(__name__)

BATCH_WINDOW_MS = int(os.getenv("EMBED_BATCH_WINDOW_MS", "10"))
MAX_BATCH_SIZE = int(os.getenv("EMBED_MAX_BATCH_SIZE", "64"))
MAX_QUEUE_DEPTH = int(os.getenv("EMBED_MAX_QUEUE_DEPTH", "512"))


@dataclass
class _BatchItem:
    kind: Literal["passage", "query"]
    texts: list[str]
    future: asyncio.Future = field(default_factory=asyncio.Future)


class DynamicBatcher:
    """Background coroutine that drains a queue and dispatches grouped encode calls."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[_BatchItem] = asyncio.Queue(maxsize=MAX_QUEUE_DEPTH)
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="embed-batcher")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def submit(
        self, kind: Literal["passage", "query"], texts: list[str]
    ) -> list[list[float]]:
        if self.queue.qsize() >= MAX_QUEUE_DEPTH:
            raise HTTPException(status_code=503, detail="embed queue saturated")
        item = _BatchItem(kind=kind, texts=texts)
        await self.queue.put(item)
        return await item.future

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            first = await self.queue.get()
            batch: list[_BatchItem] = [first]
            deadline = loop.time() + (BATCH_WINDOW_MS / 1000)

            # Coalesce additional items within the window, up to MAX_BATCH_SIZE texts
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                if sum(len(b.texts) for b in batch) >= MAX_BATCH_SIZE:
                    break
                try:
                    nxt = await asyncio.wait_for(self.queue.get(), timeout=remaining)
                    batch.append(nxt)
                except asyncio.TimeoutError:
                    break

            # Passages and queries use different prefixes — dispatch separately
            passages = [b for b in batch if b.kind == "passage"]
            queries = [b for b in batch if b.kind == "query"]
            if passages:
                await self._dispatch(loop, passages, is_query=False)
            if queries:
                await self._dispatch(loop, queries, is_query=True)

    async def _dispatch(
        self,
        loop: asyncio.AbstractEventLoop,
        items: list[_BatchItem],
        *,
        is_query: bool,
    ) -> None:
        flat: list[str] = []
        boundaries: list[tuple[_BatchItem, int, int]] = []
        for it in items:
            start = len(flat)
            flat.extend(it.texts)
            boundaries.append((it, start, len(flat)))

        t0 = time.perf_counter()
        try:
            if is_query:
                # Inline the prefix here so we can batch many queries in one encode call
                vectors = await loop.run_in_executor(
                    None,
                    lambda: svc.model.encode(
                        [f"query: {t}" for t in flat],
                        batch_size=len(flat),
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    ),
                )
            else:
                vectors = await loop.run_in_executor(
                    None,
                    lambda: svc.encode(texts=flat, batch_size=len(flat)),
                )
        except Exception as exc:
            logger.exception(
                "embed batch failed: items=%d texts=%d kind=%s",
                len(items),
                len(flat),
                "query" if is_query else "passage",
            )
            for it, _, _ in boundaries:
                if not it.future.done():
                    it.future.set_exception(exc)
            return

        dt_ms = (time.perf_counter() - t0) * 1000

        # Normalize to list of lists for JSON serialization regardless of backend
        if not isinstance(vectors, list):
            vectors = vectors.tolist()

        logger.info(
            "embed batch ok: kind=%s items=%d texts=%d dt=%.1fms tput=%.1f/s",
            "query" if is_query else "passage",
            len(items),
            len(flat),
            dt_ms,
            len(flat) / max(dt_ms / 1000, 1e-6),
        )

        for it, start, end in boundaries:
            if not it.future.done():
                it.future.set_result(vectors[start:end])


batcher = DynamicBatcher()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Embed server warming up — loading model...")
    await asyncio.to_thread(lambda: svc.model)  # trigger lazy load without blocking event loop
    batcher.start()
    logger.info(
        "Embed server ready (backend=%s, torch threads=%s).",
        os.getenv("EMBED_BACKEND", "st"),
        torch.get_num_threads() if "torch" in sys.modules else "n/a",
    )
    yield
    await batcher.stop()


app = FastAPI(title="SOWKNOW Embed Server", version="1.3.0", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: list[str]
    batch_size: int = Field(default=32, ge=1, le=128)


class EmbedQueryRequest(BaseModel):
    text: str


@app.get("/health")
async def health() -> dict:
    return {**svc.health_check(), "queue_depth": batcher.queue.qsize()}


@app.post("/embed")
async def embed(req: EmbedRequest) -> list[list[float]]:
    if not req.texts:
        return []
    if not svc.can_embed:
        raise HTTPException(status_code=503, detail="Embedding model not loaded")
    return await batcher.submit("passage", req.texts)


@app.post("/embed-query")
async def embed_query(req: EmbedQueryRequest) -> list[float]:
    if not req.text or not req.text.strip():
        return [0.0] * svc.embedding_dim
    if not svc.can_embed:
        raise HTTPException(status_code=503, detail="Embedding model not loaded")
    result = await batcher.submit("query", [req.text])
    return result[0]
