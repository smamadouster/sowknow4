"""ONNX Runtime + INT8 implementation of EmbeddingService.

Drop-in replacement for EmbeddingService used by embed_server/main.py.
Same public interface:
  - encode(texts, batch_size, ...)
  - encode_query(text)
  - embedding_dim
  - health_check()
  - model property (compatibility shim)
"""

import logging
import os
from pathlib import Path

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

logger = logging.getLogger(__name__)

MODEL_DIR = os.getenv("E5_ONNX_DIR", "/models/e5-large-onnx-int8")
ONNX_FILE = "model_quantized.onnx"  # optimum's default output name
EMBEDDING_DIM = 1024
MAX_LEN = 512


class EmbeddingServiceONNX:
    def __init__(self) -> None:
        self._tokenizer = None
        self._session: ort.InferenceSession | None = None

    @property
    def embedding_dim(self) -> int:
        return EMBEDDING_DIM

    @property
    def model(self):
        """Compatibility shim — returns self so batcher's svc.model.encode works."""
        self._ensure_loaded()
        return self

    @property
    def is_loaded(self) -> bool:
        return self._session is not None

    @property
    def can_embed(self) -> bool:
        return self._session is not None

    def encode(
        self,
        texts: list[str] | None = None,
        batch_size: int = 32,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ):
        """Mirrors sentence-transformers signature; returns numpy array.

        Callers that need JSON-serializable output should call .tolist().
        """
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        # If called via batcher's lambda (already-prefixed inputs), don't double-prefix
        if texts and not (
            texts[0].startswith("passage: ") or texts[0].startswith("query: ")
        ):
            texts = [f"passage: {t}" for t in texts]
        out_rows: list[np.ndarray] = []
        for i in range(0, len(texts), batch_size):
            out_rows.append(self._encode_raw(texts[i : i + batch_size]))
        return np.vstack(out_rows)

    def encode_query(self, text: str) -> list[float]:
        if not text or not text.strip():
            return [0.0] * EMBEDDING_DIM
        return self._encode_raw([f"query: {text}"])[0].tolist()

    def health_check(self) -> dict:
        try:
            self._ensure_loaded()
            return {"status": "healthy", "model_loaded": True, "backend": "onnx-int8"}
        except Exception as exc:
            return {"status": "degraded", "model_loaded": False, "error": str(exc)}

    # ---- internals ----

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return
        model_path = Path(MODEL_DIR) / ONNX_FILE
        logger.info("Loading ONNX model from %s", model_path)

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = int(os.getenv("ONNX_INTRA_THREADS", "2"))
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self._session = ort.InferenceSession(
            str(model_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
        logger.info("ONNX model loaded.")

    def _encode_raw(self, texts: list[str]) -> np.ndarray:
        self._ensure_loaded()
        enc = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=MAX_LEN,
            return_tensors="np",
        )
        outputs = self._session.run(
            None,
            {
                "input_ids": enc["input_ids"].astype(np.int64),
                "attention_mask": enc["attention_mask"].astype(np.int64),
            },
        )
        last_hidden = outputs[0]  # (B, S, H)
        mask = enc["attention_mask"][..., None].astype(np.float32)
        summed = (last_hidden * mask).sum(axis=1)
        counts = mask.sum(axis=1).clip(min=1e-9)
        pooled = summed / counts  # mean-pool
        norms = np.linalg.norm(pooled, axis=1, keepdims=True).clip(min=1e-12)
        return (pooled / norms).astype(np.float32)  # L2-normalize


embedding_service = EmbeddingServiceONNX()
