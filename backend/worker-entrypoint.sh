#!/bin/bash
set -e

# Only download model for worker (not beat — beat has no model volume and only 128MB)
if [ "${SKIP_MODEL_DOWNLOAD:-0}" != "1" ]; then
    MODEL_DIR="${SENTENCE_TRANSFORMERS_HOME:-/models}"

    if [ -z "$(ls -A "${MODEL_DIR}" 2>/dev/null)" ]; then
        echo "[worker-entrypoint] First run — downloading multilingual-e5-large model to ${MODEL_DIR}..."
        python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-large')"
        echo "[worker-entrypoint] Model downloaded and cached."
    else
        echo "[worker-entrypoint] Model cache found in ${MODEL_DIR}."
    fi
fi

exec "$@"
