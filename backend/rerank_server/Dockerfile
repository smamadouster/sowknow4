FROM python:3.12-slim

WORKDIR /app

# Install build dependencies and curl (for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

# Pre-download model at build time (optional; can also download at runtime)
ENV SENTENCE_TRANSFORMERS_HOME=/models
ENV HF_HOME=/models
ENV TRANSFORMERS_CACHE=/models
ENV RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2

EXPOSE 8000

CMD ["python", "main.py"]
