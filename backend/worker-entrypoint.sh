#!/bin/bash
set -e

MODEL_DIR="${SENTENCE_TRANSFORMERS_HOME:-/models}"

# Download embedding model on first run (persisted in named volume)
if [ -z "$(ls -A "${MODEL_DIR}" 2>/dev/null)" ]; then
    echo "[worker-entrypoint] First run — downloading multilingual-e5-large model to ${MODEL_DIR}..."
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-large')"
    echo "[worker-entrypoint] Model downloaded and cached."
else
    echo "[worker-entrypoint] Model cache found in ${MODEL_DIR}."
fi

exec "$@"
