# Embed Server Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract EmbeddingService from in-process usage into an isolated `sowknow4-embed-server` FastAPI container so the 1.3 GB multilingual-e5-large model loads exactly once across all callers.

**Architecture:** A new `embed-server` container runs a minimal FastAPI app that wraps the existing `EmbeddingService` singleton; all Celery workers and the backend replace direct `embedding_service.encode()` calls with an `EmbedClient` HTTP wrapper that preserves the exact same Python interface. `celery-heavy` keeps the `pipeline.embed` queue but its tasks become pure I/O (HTTP calls), dropping its memory footprint from 4 GB to 512 MB.

**Tech Stack:** FastAPI, uvicorn, httpx (sync), existing sentence-transformers/PyTorch stack already in Dockerfile.worker base image.

---

## File Structure

### New files
| Path | Responsibility |
|------|----------------|
| `backend/embed_server/__init__.py` | Empty package marker |
| `backend/embed_server/main.py` | FastAPI app — `/embed`, `/embed-query`, `/health` |
| `backend/embed_server/requirements.txt` | Minimal deps: fastapi, uvicorn, sentence-transformers, torch (CPU), numpy, psutil |
| `backend/Dockerfile.embed` | Lean image (no OCR, no whisper, no Celery) |
| `backend/app/services/embed_client.py` | Sync HTTP client with the same interface as EmbeddingService |
| `backend/tests/test_embed_server.py` | TestClient integration tests for the FastAPI app |
| `backend/tests/test_embed_client.py` | Unit tests for EmbedClient (httpx mocked) |

### Modified files
| Path | Change |
|------|--------|
| `backend/app/tasks/pipeline_tasks.py` | `from app.services.embed_client import embedding_service` |
| `backend/app/tasks/embedding_tasks.py` | Same import swap (×2 tasks) |
| `backend/app/tasks/document_tasks.py` | Same import swap |
| `backend/app/tasks/article_tasks.py` | Same import swap |
| `backend/app/services/search_service.py` | Same import swap (uses `can_embed` + `encode_query`) |
| `backend/app/services/similarity_service.py` | Remove unused `embedding_service` import |
| `docker-compose.yml` | Add `embed-server` service; drop model volume from `celery-heavy`; lower `celery-heavy` memory to 512 MB; add `EMBED_SERVER_URL` env var to all callers |
| `.env.example` | Add `EMBED_SERVER_URL=http://embed-server:8000` |

---

## Task 1: FastAPI embed server

**Files:**
- Create: `backend/embed_server/__init__.py`
- Create: `backend/embed_server/main.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_embed_server.py
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    """TestClient with model loading bypassed (no GPU/model in CI)."""
    from unittest.mock import MagicMock, patch
    import numpy as np

    mock_svc = MagicMock()
    mock_svc.health_check.return_value = {"status": "healthy", "model_loaded": True}
    mock_svc.encode.return_value = [[0.1] * 1024, [0.2] * 1024]
    mock_svc.encode_query.return_value = [0.3] * 1024

    with patch("embed_server.main.svc", mock_svc):
        from embed_server.main import app
        yield TestClient(app)


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_embed_returns_vectors(client):
    resp = client.post("/embed", json={"texts": ["hello", "world"]})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert len(data[0]) == 1024


def test_embed_empty_texts(client):
    resp = client.post("/embed", json={"texts": []})
    assert resp.status_code == 200
    assert resp.json() == []


def test_embed_query_returns_vector(client):
    resp = client.post("/embed-query", json={"text": "search query"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1024


def test_embed_query_empty_text(client):
    resp = client.post("/embed-query", json={"text": ""})
    assert resp.status_code == 200
    assert resp.json() == [0.0] * 1024
```

- [ ] **Step 2: Run test to confirm it fails (module not found)**

```bash
cd /home/development/src/active/sowknow4/backend
python -m pytest tests/test_embed_server.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'embed_server'`

- [ ] **Step 3: Create the package marker**

```bash
touch backend/embed_server/__init__.py
```

- [ ] **Step 4: Create `backend/embed_server/main.py`**

```python
"""
Embedding microservice — exposes EmbeddingService over HTTP.

Endpoints
---------
POST /embed         — passage embeddings for indexing (list[str] → list[list[float]])
POST /embed-query   — query embedding for search    (str → list[float])
GET  /health        — liveness + model status
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

# Singleton — model loads lazily on first request via EmbeddingService._load_model()
svc = EmbeddingService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Trigger model load at startup so the first real request isn't slow."""
    logger.info("Embed server warming up — loading model...")
    _ = svc.model  # access the property → triggers lazy load
    logger.info("Embed server ready.")
    yield


app = FastAPI(title="SOWKNOW Embed Server", version="1.0.0", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: list[str]
    batch_size: int = 32


class EmbedQueryRequest(BaseModel):
    text: str


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
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
cd /home/development/src/active/sowknow4/backend
PYTHONPATH=/home/development/src/active/sowknow4/backend python -m pytest tests/test_embed_server.py -v
```

Expected: 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/embed_server/ backend/tests/test_embed_server.py
git commit -m "feat(embed-server): add FastAPI embed microservice with /embed, /embed-query, /health"
```

---

## Task 2: Embed server requirements and Dockerfile

**Files:**
- Create: `backend/embed_server/requirements.txt`
- Create: `backend/Dockerfile.embed`

- [ ] **Step 1: Create `backend/embed_server/requirements.txt`**

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
sentence-transformers==2.7.0
numpy>=1.24
psutil>=5.9
```

Note: torch is installed separately (CPU wheel) in the Dockerfile, same as Dockerfile.worker.

- [ ] **Step 2: Create `backend/Dockerfile.embed`**

```dockerfile
FROM python:3.11.11-slim

WORKDIR /app

# Minimal system deps (no OCR, no Whisper)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1001 appuser && useradd -g appuser -u 1001 -m appuser

# CPU-only PyTorch (200 MB vs 2 GB for full)
RUN pip install --no-cache-dir torch==2.1.0 --index-url https://download.pytorch.org/whl/cpu

COPY embed_server/requirements.txt /tmp/embed_requirements.txt
RUN pip install --no-cache-dir -r /tmp/embed_requirements.txt

# Model cache dir — volume-mounted at runtime, NOT baked in
RUN mkdir -p /models && chown appuser:appuser /models

# Source code arrives via bind mount ./backend:/app
RUN mkdir -p /data && chown -R appuser:appuser /app /data

ENV PYTHONPATH=/app
ENV SENTENCE_TRANSFORMERS_HOME=/models
ENV HF_HOME=/models
ENV TRANSFORMERS_CACHE=/models

USER appuser

CMD ["uvicorn", "embed_server.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

- [ ] **Step 3: Verify Dockerfile syntax (dry-run build check)**

```bash
docker build -f backend/Dockerfile.embed --no-cache --progress=plain backend/ 2>&1 | tail -20
```

Expected: `Successfully built <image_id>` (may take a few minutes — installs torch + sentence-transformers).

- [ ] **Step 4: Commit**

```bash
git add backend/Dockerfile.embed backend/embed_server/requirements.txt
git commit -m "feat(embed-server): add Dockerfile.embed for standalone embedding container"
```

---

## Task 3: EmbedClient HTTP wrapper

**Files:**
- Create: `backend/app/services/embed_client.py`
- Create: `backend/tests/test_embed_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_embed_client.py
import os

import httpx
import pytest
from unittest.mock import patch, MagicMock


def make_client(url="http://embed-server:8000"):
    import importlib
    import app.services.embed_client as mod
    from unittest.mock import patch
    with patch.dict(os.environ, {"EMBED_SERVER_URL": url}):
        importlib.reload(mod)  # re-runs EMBED_SERVER_URL = os.getenv(...) with patched env
        return mod.EmbedClient()


def _mock_response(status_code: int, json_body):
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.json.return_value = json_body
    mock.raise_for_status = MagicMock()
    return mock


def test_encode_calls_embed_endpoint(monkeypatch):
    client = make_client()
    expected = [[0.1] * 1024, [0.2] * 1024]
    with patch("httpx.post", return_value=_mock_response(200, expected)) as mock_post:
        result = client.encode(["hello", "world"])
    assert result == expected
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "/embed" in call_kwargs[0][0]
    assert call_kwargs[1]["json"]["texts"] == ["hello", "world"]


def test_encode_empty_returns_empty(monkeypatch):
    client = make_client()
    result = client.encode([])
    assert result == []


def test_encode_query_calls_embed_query_endpoint(monkeypatch):
    client = make_client()
    expected = [0.3] * 1024
    with patch("httpx.post", return_value=_mock_response(200, expected)):
        result = client.encode_query("my search")
    assert result == expected


def test_encode_query_empty_returns_zero_vector(monkeypatch):
    client = make_client()
    result = client.encode_query("")
    assert result == [0.0] * 1024
    assert len(result) == 1024


def test_encode_single_wraps_encode(monkeypatch):
    client = make_client()
    expected = [0.5] * 1024
    with patch("httpx.post", return_value=_mock_response(200, [expected])):
        result = client.encode_single("one doc")
    assert result == expected


def test_can_embed_true_when_server_healthy(monkeypatch):
    client = make_client()
    health_resp = _mock_response(200, {"status": "healthy"})
    with patch("httpx.get", return_value=health_resp):
        assert client.can_embed is True


def test_can_embed_false_when_server_unreachable(monkeypatch):
    client = make_client()
    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        assert client.can_embed is False


def test_encode_returns_zero_vectors_on_connection_error(monkeypatch):
    client = make_client()
    with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
        result = client.encode(["hello"])
    assert result == [[0.0] * 1024]


def test_encode_query_returns_zero_vector_on_connection_error(monkeypatch):
    client = make_client()
    with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
        result = client.encode_query("search")
    assert result == [0.0] * 1024
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd /home/development/src/active/sowknow4/backend
PYTHONPATH=/home/development/src/active/sowknow4/backend python -m pytest tests/test_embed_client.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'app.services.embed_client'`

- [ ] **Step 3: Create `backend/app/services/embed_client.py`**

```python
"""
HTTP client for the sowknow4-embed-server microservice.

Drop-in replacement for EmbeddingService — exposes the same interface:
  encode(texts, batch_size)  →  list[list[float]]
  encode_query(text)         →  list[float]
  encode_single(text)        →  list[float]
  can_embed                  →  bool (property, TTL-cached)

When the embed server is unreachable the client falls back to zero vectors,
preserving the graceful-degradation behaviour of the original EmbeddingService.
"""

import asyncio
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

EMBED_SERVER_URL = os.getenv("EMBED_SERVER_URL", "http://embed-server:8000")
EMBEDDING_DIM = 1024
_ENCODE_TIMEOUT = 120.0   # seconds — large batches can be slow on CPU
_QUERY_TIMEOUT = 30.0
_HEALTH_TIMEOUT = 5.0
_HEALTH_TTL = 15.0        # seconds — re-check server health at most every 15s

_ZERO_VECTOR: list[float] = [0.0] * EMBEDDING_DIM


class EmbedClient:
    """Thin sync HTTP wrapper around the embed-server FastAPI microservice."""

    def __init__(self) -> None:
        self._can_embed_cache: bool = False
        self._can_embed_checked_at: float = 0.0

    @property
    def embedding_dim(self) -> int:
        return EMBEDDING_DIM

    @property
    def can_embed(self) -> bool:
        """Return True when the embed server is reachable and healthy (TTL-cached)."""
        now = time.monotonic()
        if now - self._can_embed_checked_at < _HEALTH_TTL:
            return self._can_embed_cache
        try:
            resp = httpx.get(f"{EMBED_SERVER_URL}/health", timeout=_HEALTH_TIMEOUT)
            result = resp.status_code == 200 and resp.json().get("status") == "healthy"
        except Exception:
            result = False
        self._can_embed_cache = result
        self._can_embed_checked_at = now
        return result

    def encode(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """
        Generate passage embeddings for a list of texts.

        Returns zero vectors on server failure (graceful degradation).
        """
        if not texts:
            return []
        try:
            resp = httpx.post(
                f"{EMBED_SERVER_URL}/embed",
                json={"texts": texts, "batch_size": batch_size},
                timeout=_ENCODE_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("EmbedClient.encode: server unavailable (%s); returning zero vectors", exc)
            return [list(_ZERO_VECTOR) for _ in texts]

    def encode_single(self, text: str) -> list[float]:
        """Generate a passage embedding for a single text."""
        if not text or not text.strip():
            return list(_ZERO_VECTOR)
        result = self.encode([text])
        return result[0] if result else list(_ZERO_VECTOR)

    def encode_query(self, text: str) -> list[float]:
        """
        Generate a query embedding (uses 'query:' prefix internally).

        Returns zero vector on server failure.
        """
        if not text or not text.strip():
            return list(_ZERO_VECTOR)
        try:
            resp = httpx.post(
                f"{EMBED_SERVER_URL}/embed-query",
                json={"text": text},
                timeout=_QUERY_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("EmbedClient.encode_query: server unavailable (%s); returning zero vector", exc)
            return list(_ZERO_VECTOR)

    async def encode_async(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Async wrapper — runs encode() in a thread pool (preserves existing call sites)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.encode, texts, batch_size)


# Module-level singleton — same name as the original so callers just change the import path
embedding_service = EmbedClient()
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd /home/development/src/active/sowknow4/backend
PYTHONPATH=/home/development/src/active/sowknow4/backend python -m pytest tests/test_embed_client.py -v
```

Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/embed_client.py backend/tests/test_embed_client.py
git commit -m "feat(embed-client): add EmbedClient HTTP wrapper with same interface as EmbeddingService"
```

---

## Task 4: Swap callers in Celery tasks

**Files:**
- Modify: `backend/app/tasks/pipeline_tasks.py`
- Modify: `backend/app/tasks/embedding_tasks.py`
- Modify: `backend/app/tasks/document_tasks.py`
- Modify: `backend/app/tasks/article_tasks.py`

Each file currently has (inside the task function body, as a deferred import):
```python
from app.services.embedding_service import embedding_service
```

Replace every occurrence with:
```python
from app.services.embed_client import embedding_service
```

- [ ] **Step 1: Swap pipeline_tasks.py**

In `backend/app/tasks/pipeline_tasks.py` around line 301, change:
```python
    from app.services.embedding_service import embedding_service
```
to:
```python
    from app.services.embed_client import embedding_service
```

- [ ] **Step 2: Verify pipeline_tasks change**

```bash
grep -n "embedding_service" backend/app/tasks/pipeline_tasks.py
```

Expected: shows `embed_client` in the import, no `embedding_service` import line.

- [ ] **Step 3: Swap embedding_tasks.py (2 occurrences)**

In `backend/app/tasks/embedding_tasks.py`, change both occurrences of:
```python
    from app.services.embedding_service import embedding_service
```
to:
```python
    from app.services.embed_client import embedding_service
```

(Line ~61 in `generate_embeddings_batch` and line ~149 in `recompute_embeddings_for_document`.)

Note: `upgrade_embeddings_model` task does NOT import embedding_service — it imports SentenceTransformer directly and creates its own model. Leave that task unchanged.

- [ ] **Step 4: Swap document_tasks.py**

In `backend/app/tasks/document_tasks.py` around line 488, change:
```python
    from app.services.embedding_service import embedding_service
```
to:
```python
    from app.services.embed_client import embedding_service
```

- [ ] **Step 5: Swap article_tasks.py**

In `backend/app/tasks/article_tasks.py` around line 267, change:
```python
    from app.services.embedding_service import embedding_service
```
to:
```python
    from app.services.embed_client import embedding_service
```

- [ ] **Step 6: Verify all 4 files**

```bash
grep -rn "from app.services.embedding_service import embedding_service" backend/app/tasks/
```

Expected: no output (all swapped).

```bash
grep -rn "from app.services.embed_client import embedding_service" backend/app/tasks/
```

Expected: 4 lines (pipeline_tasks.py, embedding_tasks.py ×2 occurrences, document_tasks.py, article_tasks.py).

- [ ] **Step 7: Run existing tests to catch regressions**

```bash
cd /home/development/src/active/sowknow4/backend
PYTHONPATH=/home/development/src/active/sowknow4/backend python -m pytest tests/ -v --ignore=tests/test_embed_server.py --ignore=tests/test_embed_client.py -x 2>&1 | tail -30
```

Expected: same pass/fail as before this change.

- [ ] **Step 8: Commit**

```bash
git add backend/app/tasks/pipeline_tasks.py backend/app/tasks/embedding_tasks.py \
        backend/app/tasks/document_tasks.py backend/app/tasks/article_tasks.py
git commit -m "refactor(tasks): route embedding calls through embed-server HTTP client"
```

---

## Task 5: Swap caller in search_service and clean up similarity_service

**Files:**
- Modify: `backend/app/services/search_service.py`
- Modify: `backend/app/services/similarity_service.py`

- [ ] **Step 1: Swap search_service.py**

In `backend/app/services/search_service.py` line 19, change:
```python
from app.services.embedding_service import embedding_service
```
to:
```python
from app.services.embed_client import embedding_service
```

`can_embed` and `encode_query` are on EmbedClient with the same signatures. No other changes needed.

- [ ] **Step 2: Clean up similarity_service.py**

In `backend/app/services/similarity_service.py`:

Remove line 17:
```python
from app.services.embedding_service import embedding_service
```

And remove line 58:
```python
        self.embedding_service = embedding_service
```

(The similarity service uses pre-stored chunk embeddings from the DB via numpy — it never calls encode().)

- [ ] **Step 3: Verify no remaining references to embedding_service from embedding_service.py**

```bash
grep -rn "from app.services.embedding_service import embedding_service" backend/app/
```

Expected: no output.

- [ ] **Step 4: Quick import smoke test**

```bash
cd /home/development/src/active/sowknow4/backend
PYTHONPATH=/home/development/src/active/sowknow4/backend python -c "
from app.services.search_service import SearchService
from app.services.similarity_service import SimilarityService
print('imports OK')
"
```

Expected: `imports OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/search_service.py backend/app/services/similarity_service.py
git commit -m "refactor(services): route search embedding calls through embed-server; drop unused import in similarity_service"
```

---

## Task 6: docker-compose.yml — add embed-server, update celery-heavy

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

### 6a — Add embed-server service

- [ ] **Step 1: Add embed-server service block to docker-compose.yml**

Insert after the `nats:` service block (before `# --- Application ---`), or at the bottom of the Application section. Add this service:

```yaml
  embed-server:
    <<: *common-env
    init: true
    security_opt:
      - no-new-privileges:true
    build:
      context: ./backend
      dockerfile: Dockerfile.embed
    container_name: sowknow4-embed-server
    restart: unless-stopped
    logging: *default-logging
    environment:
      - SENTENCE_TRANSFORMERS_HOME=/models
      - HF_HOME=/models
      - TRANSFORMERS_CACHE=/models
    volumes:
      - sowknow-model-cache:/models
      - ./backend:/app
    # NO ports — internal only. Access: http://embed-server:8000
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8000/health | grep -q 'healthy' || exit 1"]
      interval: 30s
      timeout: 15s
      retries: 5
      start_period: 120s
    deploy:
      resources:
        limits:
          memory: 2048M
          cpus: '2.0'
    networks:
      - sowknow-net
```

### 6b — Update celery-heavy

- [ ] **Step 2: Update celery-heavy in docker-compose.yml**

celery-heavy no longer loads the model. Make these changes:

1. Drop `sowknow-model-cache:/models` from its `volumes:` block — it doesn't need the model volume.
2. Add `EMBED_SERVER_URL: http://embed-server:8000` to its `environment:`.
3. Add `embed-server` to its `depends_on:` (condition: `service_healthy`).
4. Lower memory limit from `4096M` to `512M`.
5. Remove the long comment about prefork/OOM that no longer applies.

After edits, celery-heavy should look like:

```yaml
  celery-heavy:
    <<: *common-env
    init: true
    security_opt:
      - no-new-privileges:true
    build:
      context: ./backend
      dockerfile: Dockerfile.worker
    container_name: sowknow4-celery-heavy
    restart: unless-stopped
    logging: *default-logging
    environment:
      - DATABASE_URL=postgresql://${DATABASE_USER:-sowknow}:${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set in .env}@postgres:5432/${DATABASE_NAME:-sowknow}
      - REDIS_HOST=redis
      - EMBED_SERVER_URL=http://embed-server:8000
      - SKIP_MODEL_DOWNLOAD=1
    volumes:
      - sowknow-public-data:/data/public
      - sowknow-confidential-data:/data/confidential
      - sowknow-audio-data:/data/audio
      - ./backend:/app
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      embed-server:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "cat /proc/1/cmdline 2>/dev/null | tr '\\0' ' ' | grep -q celery || exit 1"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 120s
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '1.0'
    command: >-
      celery -A app.celery_app worker --loglevel=info --concurrency=2
      --pool=prefork
      -Q pipeline.embed
      --prefetch-multiplier=1
      -n heavy@%h
    networks:
      - sowknow-net
```

Note: pool changed back to `prefork` (or `threads`) now that the task is I/O bound (HTTP call). concurrency raised to 2 since no model in memory.

### 6c — Add EMBED_SERVER_URL to other callers

- [ ] **Step 3: Add EMBED_SERVER_URL to celery-light environment**

In `celery-light`'s `environment:` block, add:
```yaml
      - EMBED_SERVER_URL=http://embed-server:8000
```

Also add `embed-server` to celery-light's `depends_on:`:
```yaml
      embed-server:
        condition: service_healthy
```

- [ ] **Step 4: Add EMBED_SERVER_URL to backend environment**

In `backend`'s `environment:` block, add:
```yaml
      - EMBED_SERVER_URL=http://embed-server:8000
```

Also add `embed-server` to backend's `depends_on:`:
```yaml
      embed-server:
        condition: service_healthy
```

- [ ] **Step 5: Update .env.example**

Add this line to `.env.example` in the "AI Services" section (or at end):
```
EMBED_SERVER_URL=http://embed-server:8000
```

- [ ] **Step 6: Update memory budget comment at top of docker-compose.yml**

Find the memory allocation comment at the top of docker-compose.yml and update to reflect:
- `embed-server: 2048MB` (new)
- `celery-heavy: 512MB` (was 4096MB)
- Update TOTAL accordingly

Before:
```yaml
#   celery-heavy:    5120MB  (prefork pool, concurrency=1, 1.3GB model, max-tasks-per-child=30)
```
After:
```yaml
#   embed-server:    2048MB  (embedding model, serves all callers via HTTP)
#   celery-heavy:     512MB  (pipeline.embed queue consumer, I/O bound HTTP calls)
```

- [ ] **Step 7: Validate docker-compose syntax**

```bash
cd /home/development/src/active/sowknow4
docker compose config --quiet && echo "Compose config OK"
```

Expected: `Compose config OK` (no errors).

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "feat(infra): add sowknow4-embed-server container; downsize celery-heavy to 512MB"
```

---

## Task 7: Smoke test the full stack locally (optional but recommended)

- [ ] **Step 1: Build the new image**

```bash
cd /home/development/src/active/sowknow4
docker compose build embed-server
```

Expected: build succeeds (may take several minutes for torch/sentence-transformers install).

- [ ] **Step 2: Start embed-server in isolation**

```bash
docker compose up embed-server -d
docker compose logs embed-server --follow --until=60s
```

Expected: logs show `Embed server warming up` then `Embed server ready.`

- [ ] **Step 3: Curl the health endpoint from host**

```bash
docker exec sowknow4-embed-server curl -s http://localhost:8000/health | python3 -m json.tool
```

Expected JSON:
```json
{
  "status": "healthy",
  "model_loaded": true,
  ...
}
```

- [ ] **Step 4: Test embed endpoint**

```bash
docker exec sowknow4-embed-server curl -s -X POST http://localhost:8000/embed \
  -H "Content-Type: application/json" \
  -d '{"texts": ["Bonjour le monde", "Hello world"]}' | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'Got {len(data)} vectors of dim {len(data[0])}')
assert len(data) == 2
assert len(data[0]) == 1024
print('OK')
"
```

Expected: `Got 2 vectors of dim 1024` then `OK`.

- [ ] **Step 5: Run full unit test suite**

```bash
cd /home/development/src/active/sowknow4/backend
PYTHONPATH=/home/development/src/active/sowknow4/backend python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: all previously passing tests still pass; 14 new tests (5 embed_server + 9 embed_client) pass.

---

## Self-Review Checklist

### Spec coverage
- [x] Option B — custom FastAPI wrapper reusing existing EmbeddingService class ✓
- [x] Handles `passage:` / `query:` prefixes internally (EmbeddingService already does this) ✓
- [x] Single endpoint exposes both indexing (`/embed`) and search (`/embed-query`) ✓
- [x] Same PyTorch stack — Dockerfile.embed reuses same pip deps ✓
- [x] Full control, easy to debug ✓
- [x] All 5 call sites swapped: pipeline_tasks, embedding_tasks, document_tasks, article_tasks, search_service ✓
- [x] similarity_service cleaned up (unused import) ✓
- [x] celery-heavy downsized from 4 GB to 512 MB ✓
- [x] Graceful degradation preserved: EmbedClient returns zero vectors on server unavailability ✓
- [x] `can_embed` TTL-cached (15s) — no live HTTP call on every search request ✓
- [x] `@app.on_event("startup")` replaced with `lifespan` context manager (FastAPI ≥ 0.93) ✓
- [x] `asyncio.get_event_loop()` → `asyncio.get_running_loop()` (Python 3.10+ safe) ✓
- [x] `_ZERO_VECTOR` module constant — zero vector allocated once, not on every fallback ✓
- [x] `show_progress` dead parameter removed from `encode()` ✓
- [x] Test `make_client()` uses `patch.dict(os.environ, ...)` — no permanent env mutation ✓
- [x] Healthcheck added to embed-server (curl /health) ✓
- [x] `sowknow4-` naming prefix ✓
- [x] No host port exposure for embed-server ✓

### Placeholder scan
- No TBD / TODO / "implement later" in any step ✓
- All code blocks complete ✓
- All commands include expected output ✓

### Type consistency
- `EmbedClient.encode()` → `list[list[float]]` matches all call sites that do `embeddings[i]` ✓
- `EmbedClient.encode_query()` → `list[float]` matches search_service usage ✓
- `EmbedClient.can_embed` → `bool` property matches `if not embedding_service.can_embed:` guards ✓
- `EmbedClient.encode_async()` → `list[list[float]]` matches any async callers ✓
